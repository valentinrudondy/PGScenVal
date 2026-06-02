"""Multi-cell HRRR aggregation pilot — Task 1.1.

Runs the v3 physics in three modes for a small plant subset (Copenhagen +
Marble agg) over a chosen time window:

  - **single**: v3 baseline (one HRRR cell per plant, plant centroid)
  - **multiA**: per-cell curve eval, then nameplate-weighted sum to plant
  - **multiB**: weight-averaged WS over cells, then one curve eval per plant

The plant→cell weights come from USWTDB per-turbine coordinates (each
turbine assigned to its nearest HRRR cell, weight = turbine count / total
turbines in the plant). Pres/T2m are extracted per cell, density is
corrected per cell in A and at plant level in B.

Outputs: hourly per-plant MW for each method, to
``docs/figures/wind_v3/multicell_pilot_<window>.csv``. The script also
prints A vs B vs single-cell ramp-distribution and (where PLUSWIND covers
the year) point-error metrics against PLUSWIND truth.

Designed for the 1-week sniff test first, then scalable to full-year. CLI:
  --start 2020-06-01 --end 2020-06-08   (1 week, ~340 S3 fetches)
  --start 2020-01-01 --end 2021-01-01   (full year, ~17.5k fetches)
"""
from __future__ import annotations

import argparse
import io
import logging
import struct
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import botocore
import eccodes
import numpy as np
import pandas as pd
import xarray as xr  # noqa: F401 — kept for environment parity
from scipy.spatial import cKDTree
from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "PGscen-2nd"))
ARCH_CURVES_CSV = REPO_ROOT / "docs" / "figures" / "wind_v3" / "archetype_curves.csv"
ARCH_ASSIGN_CSV = REPO_ROOT / "docs" / "figures" / "wind_v3" / "archetype_assignment.csv"
from pgscen.utils.wind_physics import (
    build_sam_curves,
    estimate_shear_alpha,
    extrapolate_to_hub,
    pluswind_v3_power_all_plants,
    pluswind_v4_power_multicell_A,
    pluswind_v4_power_multicell_B,
    pluswind_v5_power_multicell_A_hubshear,
    pluswind_v6_power_multicell_A_learned,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("multicell-pilot")

PM_DIR    = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
WIND_DIR  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
CACHE_DIR = REPO_ROOT / "PGscen-2nd" / "data" / "cache" / "hrrr"
PLUSWIND_RAW = REPO_ROOT / "data" / "pluswind_raw"
OUT_DIR   = REPO_ROOT / "docs" / "figures" / "wind_v3"

# Pilot plants (Option A scope)
PILOT_SITES = [
    "wind_323753",  # Copenhagen (clean LPI anchor, 80 MW)
    "wind_323696",  # Marble River      (Marble agg, 215 MW)
    "wind_323614",  # Chateaugay        (Marble agg, 106 MW)
    "wind_323605",  # Clinton           (Marble agg, 100 MW)
    "wind_323604",  # Ellenburg         (Marble agg,  81 MW)
]

# S3 access (public, no auth)
S3_BUCKET = "noaa-hrrr-bdp-pds"
_s3_client = None


def _s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            config=botocore.config.Config(
                signature_version=botocore.UNSIGNED,
                max_pool_connections=60,
            ),
        )
    return _s3_client


WIND_IDX_PATTERNS    = ["UGRD:80 m above ground", "VGRD:80 m above ground"]
DENSITY_IDX_PATTERNS = ["PRES:surface", "TMP:2 m above ground"]
# 10 m wind for shear extrapolation (Task 1.2). HRRR variable names: u10/v10
# (shortNames in eccodes); index strings below match the .idx file syntax.
WIND10_IDX_PATTERNS  = ["UGRD:10 m above ground", "VGRD:10 m above ground"]
_IDX_CACHE: dict[str, str] = {}
_IDX_LOCK = threading.Lock()


def hrrr_s3_key(date_str: str, init_hour: int, fhour: int) -> str:
    return (f"hrrr.{date_str}/conus/"
            f"hrrr.t{init_hour:02d}z.wrfsfcf{fhour:02d}.grib2")


def _get_idx(key: str) -> str | None:
    with _IDX_LOCK:
        c = _IDX_CACHE.get(key)
    if c is not None:
        return c
    try:
        resp = _s3().get_object(Bucket=S3_BUCKET, Key=key + ".idx")
        t = resp["Body"].read().decode()
    except botocore.exceptions.ClientError:
        return None
    with _IDX_LOCK:
        _IDX_CACHE[key] = t
    return t


def _parse_idx(idx_text: str) -> list[tuple[int, int, str]]:
    lines = [l.strip() for l in idx_text.strip().split("\n") if l.strip()]
    entries = []
    for line in lines:
        parts = line.split(":")
        if len(parts) >= 6:
            entries.append((int(parts[1]), f"{parts[3]}:{parts[4]}"))
    result = []
    for i, (start, desc) in enumerate(entries):
        end = entries[i + 1][0] - 1 if i + 1 < len(entries) else -1
        result.append((start, end, desc))
    return result


def download_subset(s3_key: str, patterns: list[str]) -> bytes | None:
    """Download a HRRR byte-range subset and return its bytes (no disk write)."""
    idx = _get_idx(s3_key)
    if idx is None:
        return None
    ranges = [(s, e) for s, e, d in _parse_idx(idx) if any(p in d for p in patterns)]
    if not ranges:
        return None
    buf = bytearray()
    for s, e in ranges:
        rng = f"bytes={s}-" if e == -1 else f"bytes={s}-{e}"
        try:
            r = _s3().get_object(Bucket=S3_BUCKET, Key=s3_key, Range=rng)
            buf.extend(r["Body"].read())
        except botocore.exceptions.ClientError:
            return None
    return bytes(buf)


def _read_grib_bytes(b: bytes) -> dict[str, np.ndarray]:
    """Parse a GRIB2 bytes blob into shortName→2D array, plus lat/lon."""
    # eccodes wants a file path; write to a temp file
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".grib2", delete=False)
    try:
        tmp.write(b)
        tmp.flush()
        tmp.close()
        out = {}
        with open(tmp.name, "rb") as f:
            while True:
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None:
                    break
                sn = eccodes.codes_get(gid, "shortName")
                ni = eccodes.codes_get(gid, "Ni")
                nj = eccodes.codes_get(gid, "Nj")
                out[sn] = eccodes.codes_get_values(gid).reshape(nj, ni)
                if "latitude" not in out:
                    out["latitude"]  = eccodes.codes_get_array(gid, "latitudes").reshape(nj, ni)
                    out["longitude"] = eccodes.codes_get_array(gid, "longitudes").reshape(nj, ni)
                eccodes.codes_release(gid)
        return out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Plant→cell weights from USWTDB
# --------------------------------------------------------------------------

def build_plant_cell_weights(
    meta_subset: pd.DataFrame, turbines: pd.DataFrame,
    grid_lat: np.ndarray, grid_lon: np.ndarray,
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """For the plants in *meta_subset*, map turbines→nearest HRRR cell and
    return:
      W              — shape (N_plants, N_unique_cells). Row sums to 1 for
                       plants with USWTDB turbines (count weighting); plants
                       without turbines fall back to plant-centroid single
                       cell with weight 1.
      unique_cells   — list of (row, col) tuples (length N_unique_cells)
                       — what to extract from each HRRR grid.

    Count weighting (n_turbines_in_cell / n_turbines_total) is the obvious
    first choice. Capacity-weighting would matter only if a project has a
    mix of turbine sizes — not common in NY.
    """
    grid_lon_normalised = np.where(grid_lon > 180, grid_lon - 360, grid_lon)
    coords = np.column_stack([grid_lat.ravel(), grid_lon_normalised.ravel()])
    tree = cKDTree(coords)
    grid_shape = grid_lat.shape

    plant_cells: list[dict[tuple[int, int], float]] = []
    for _, row in meta_subset.iterrows():
        eia = row["eia_plant_id"]
        t = turbines[turbines["eia_id"] == eia].dropna(subset=["xlong", "ylat"])
        cell_w: dict[tuple[int, int], float] = {}
        if len(t) == 0:
            # fall back: plant centroid cell, weight 1
            _, idx = tree.query([row["latitude"], row["longitude"]])
            r, c = np.unravel_index(idx, grid_shape)
            cell_w[(int(r), int(c))] = 1.0
        else:
            tc = t[["ylat", "xlong"]].to_numpy()
            _, ids = tree.query(tc)
            for idx in ids:
                r, c = np.unravel_index(idx, grid_shape)
                cell_w[(int(r), int(c))] = cell_w.get((int(r), int(c)), 0.0) + 1.0
            total = sum(cell_w.values())
            for k in cell_w:
                cell_w[k] /= total
        plant_cells.append(cell_w)

    unique_cells = sorted({rc for pc in plant_cells for rc in pc})
    cell_to_col = {rc: i for i, rc in enumerate(unique_cells)}
    W = np.zeros((len(plant_cells), len(unique_cells)), dtype=float)
    for p, cell_w in enumerate(plant_cells):
        for rc, w in cell_w.items():
            W[p, cell_to_col[rc]] = w
    return W, unique_cells


# --------------------------------------------------------------------------
# HRRR extraction at the unique-cell set, per hour
# --------------------------------------------------------------------------

def fetch_one_hour(
    valid_time: datetime, unique_cells: list[tuple[int, int]],
) -> tuple[datetime, np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """Return (valid_time, ws80, pres, t2m, ws10) at the unique cells, or None.

    Single F00 actuals for valid_time. ws10 is the HRRR 10 m wind speed used
    by Task 1.2 (hub-height shear). It's pulled from the SAME GRIB file as
    ws80 — both UGRD/VGRD live in the wrfsfc file — but with a different idx
    pattern set, so it's a second byte-range request to S3.
    """
    s3_key = hrrr_s3_key(valid_time.strftime("%Y%m%d"), valid_time.hour, 0)
    rows = np.array([rc[0] for rc in unique_cells])
    cols = np.array([rc[1] for rc in unique_cells])

    # Wind 80 m
    wind_bytes = download_subset(s3_key, WIND_IDX_PATTERNS)
    if wind_bytes is None:
        return None
    wind = _read_grib_bytes(wind_bytes)
    ws80 = np.sqrt(wind["u"][rows, cols] ** 2 + wind["v"][rows, cols] ** 2)

    # Wind 10 m (separate byte-range pattern set). eccodes shortName for 10 m
    # winds is "10u"/"10v" (not "u"/"v" which it uses for 80 m). Be tolerant
    # in case the convention shifts across HRRR versions.
    w10_bytes = download_subset(s3_key, WIND10_IDX_PATTERNS)
    if w10_bytes is None:
        return None
    w10 = _read_grib_bytes(w10_bytes)
    u10_key = "10u" if "10u" in w10 else "u"
    v10_key = "10v" if "10v" in w10 else "v"
    ws10 = np.sqrt(w10[u10_key][rows, cols] ** 2 + w10[v10_key][rows, cols] ** 2)

    # Density (PRES surface, TMP 2m)
    dens_bytes = download_subset(s3_key, DENSITY_IDX_PATTERNS)
    if dens_bytes is None:
        return None
    dens = _read_grib_bytes(dens_bytes)
    pres = dens["sp"][rows, cols]
    t2m  = dens["2t"][rows, cols]
    return valid_time, ws80, pres, t2m, ws10


# --------------------------------------------------------------------------
# Reference grid loader — uses S3 instead of disk cache (cache GRIBs deleted)
# --------------------------------------------------------------------------

def load_hrrr_reference_grid(year: int) -> tuple[np.ndarray, np.ndarray]:
    """Return HRRR (lat, lon) 2D grids for the year (one reference hour).

    Cache stores npz with only the 31 plant cells; we need the full 2D grid
    to build the multi-cell tree. Fetch one GRIB and parse its geometry.
    """
    s3_key = hrrr_s3_key(f"{year}0615", 6, 18)
    b = download_subset(s3_key, WIND_IDX_PATTERNS)
    if b is None:
        # Try a backup date
        s3_key = hrrr_s3_key(f"{year}0701", 6, 18)
        b = download_subset(s3_key, WIND_IDX_PATTERNS)
    if b is None:
        raise RuntimeError(f"Cannot fetch any HRRR reference for {year}")
    grids = _read_grib_bytes(b)
    return grids["latitude"], grids["longitude"]


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True,
                    help="UTC start, ISO format, e.g. 2020-06-01")
    ap.add_argument("--end",   required=True,
                    help="UTC end (exclusive), ISO format")
    ap.add_argument("--workers", type=int, default=15)
    ap.add_argument("--out-tag", default=None,
                    help="Suffix for output CSV (defaults to start_end)")
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end   = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    assert end > start
    year = start.year
    if args.out_tag is None:
        args.out_tag = f"{args.start}_{args.end}"

    # ----- metadata + USWTDB -----
    log.info("Loading metadata + USWTDB turbines")
    meta = pd.read_csv(PM_DIR / "wind_meta.csv")
    turbines = pd.read_csv(PM_DIR / "uswtdb_ny_turbines.csv")
    meta_subset = meta[meta["site_id"].isin(PILOT_SITES)].reset_index(drop=True)
    log.info(f"Pilot plants: {meta_subset['site_id'].tolist()}")

    # ----- SAM curves (year-aware) -----
    log.info("Building SAM curves for pilot plants…")
    curve_ws, curve_cf, rated_ws = build_sam_curves(
        meta_subset, turbines, year=year)
    log.info(f"  SAM curve grid: {len(curve_ws)} pts; rated WS "
             f"{rated_ws.min():.2f}-{rated_ws.max():.2f} m/s")
    nameplate_mw = meta_subset["nameplate_mw"].to_numpy(float)

    # ----- HRRR grid + plant→cell weights -----
    log.info(f"Fetching one HRRR reference for {year} to build cell map…")
    grid_lat, grid_lon = load_hrrr_reference_grid(year)
    W, unique_cells = build_plant_cell_weights(
        meta_subset, turbines, grid_lat, grid_lon)
    log.info(f"Plant→cell weight matrix W shape {W.shape}; "
             f"{len(unique_cells)} unique HRRR cells across the {len(W)} pilot plants")
    # Per-plant cell counts
    for i, sid in enumerate(meta_subset["site_id"]):
        n_cells = int((W[i] > 0).sum())
        log.info(f"  {sid}: {n_cells} cells, NP {nameplate_mw[i]:.0f} MW")

    # ----- For single-cell baseline, pick each plant's dominant cell -----
    # (Mirrors what 05_build_hrrr_timeseries does, but on our unique-cell
    # index rather than the global plant centroid — these can differ slightly
    # because of the count-weighted dominant cell vs. nearest-to-centroid.)
    single_cell_col = W.argmax(axis=1)  # (N,) col index per plant

    # ----- Per-plant archetype curve (Task 2.1 — v6 path) -----
    # Build per-plant curve_cf array: archetype curve for plants with known
    # archetype, SAM curve as the fallback. Curve_ws is the archetype grid.
    v6_enabled = ARCH_CURVES_CSV.exists() and ARCH_ASSIGN_CSV.exists()
    v6_curve_ws = None
    v6_plant_curve_cf = None
    if v6_enabled:
        ac = pd.read_csv(ARCH_CURVES_CSV)
        assign = pd.read_csv(ARCH_ASSIGN_CSV)
        v6_curve_ws = ac["ws"].to_numpy()
        # Build (N, K) per-plant curve table by archetype mapping.
        per_plant_curves = np.zeros((len(meta_subset), len(v6_curve_ws)))
        for i, sid in enumerate(meta_subset["site_id"]):
            arow = assign[assign["site_id"] == sid]
            if arow.empty:
                arch = "unknown"
            else:
                arch = arow.iloc[0]["archetype"]
            if arch in ac.columns:
                per_plant_curves[i, :] = ac[arch].to_numpy()
            else:
                # SAM fallback for unknown — interpolate SAM curve to v6 ws grid
                sam_cf_i = np.interp(v6_curve_ws, curve_ws, curve_cf[i],
                                     left=0.0, right=0.0)
                per_plant_curves[i, :] = sam_cf_i
                log.info(f"  v6 fallback: {sid} -> SAM curve "
                         f"({arch} not in archetype table)")
        v6_plant_curve_cf = per_plant_curves
        # Log archetype per plant
        for i, sid in enumerate(meta_subset["site_id"]):
            arow = assign[assign["site_id"] == sid]
            a = arow.iloc[0]["archetype"] if not arow.empty else "unknown"
            sp = arow.iloc[0]["spec_pw"] if not arow.empty else float("nan")
            log.info(f"  arch[{sid}] = {a}  (spec_pw {sp:.0f} W/m^2)")
    else:
        log.warning("v6 archetype curves not found; v6hub path disabled")

    # ----- Per-plant hub height (USWTDB t_hh mean per EIA plant) -----
    # Task 1.2 lever. Plants without USWTDB hub height (e.g. South Fork
    # offshore) fall back to 80 m so the shear-extrapolation ratio is 1.
    t_hh = (turbines.dropna(subset=["t_hh"])
            .groupby("eia_id")["t_hh"].mean().to_dict())
    hub_h = np.array([
        float(t_hh.get(int(eid), 80.0)) if pd.notna(eid) else 80.0
        for eid in meta_subset["eia_plant_id"]
    ], dtype=float)
    for sid, h, eid in zip(meta_subset["site_id"], hub_h,
                            meta_subset["eia_plant_id"]):
        in_uswtdb = pd.notna(eid) and int(eid) in t_hh
        log.info(f"  hub_h[{sid}] = {h:.1f} m"
                 f"{'' if in_uswtdb else ' (fallback to 80 m, no USWTDB)'}")

    # ----- Hour list -----
    hours = []
    t = start
    while t < end:
        hours.append(t); t += timedelta(hours=1)
    log.info(f"Hours to fetch: {len(hours)} (single F00 actuals each)")

    # ----- Fetch + compute power for each hour, in parallel -----
    n_cells = len(unique_cells)
    n_plants = len(meta_subset)
    power_single = np.full((len(hours), n_plants), np.nan)
    power_multiA = np.full((len(hours), n_plants), np.nan)
    power_multiB = np.full((len(hours), n_plants), np.nan)
    power_v5_hub = np.full((len(hours), n_plants), np.nan)
    power_v6_lrn = np.full((len(hours), n_plants), np.nan) if v6_enabled else None

    def _do_hour(i_h):
        i, h = i_h
        res = fetch_one_hour(h, unique_cells)
        if res is None:
            return i, None
        _, ws80, pres, t2m, ws10 = res
        # Method A (v4): per-cell curve, then sum — uses WS80 only.
        pA = pluswind_v4_power_multicell_A(
            ws80, pres, t2m, W, nameplate_mw, curve_ws, curve_cf, rated_ws)
        # Method B (v4): average WS then curve.
        pB = pluswind_v4_power_multicell_B(
            ws80, pres, t2m, W, nameplate_mw, curve_ws, curve_cf, rated_ws)
        # Method A v5: multi-cell + hub-height shear extrapolation.
        pV5 = pluswind_v5_power_multicell_A_hubshear(
            ws80, ws10, pres, t2m, W, hub_h,
            nameplate_mw, curve_ws, curve_cf, rated_ws)
        # Method A v6: multi-cell + per-plant archetype-pooled learned curve.
        pV6 = (pluswind_v6_power_multicell_A_learned(
                   ws80, pres, t2m, W, nameplate_mw,
                   v6_curve_ws, v6_plant_curve_cf)
               if v6_enabled else None)
        # Single-cell baseline (v3): each plant uses only its dominant cell, WS80.
        ws_s   = ws80[single_cell_col]
        pres_s = pres[single_cell_col]
        t2m_s  = t2m[single_cell_col]
        pS = pluswind_v3_power_all_plants(
            ws_s, pres_s, t2m_s, nameplate_mw,
            curve_ws, curve_cf, rated_ws)
        return i, (pS, pA, pB, pV5, pV6)

    n_ok = n_fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_do_hour, (i, h)): i for i, h in enumerate(hours)}
        with tqdm(total=len(futures), desc="hours", unit="hr") as pbar:
            for fut in as_completed(futures):
                i, out = fut.result()
                if out is None:
                    n_fail += 1
                else:
                    pS, pA, pB, pV5, pV6 = out
                    power_single[i, :] = pS
                    power_multiA[i, :] = pA
                    power_multiB[i, :] = pB
                    power_v5_hub[i, :] = pV5
                    if pV6 is not None and power_v6_lrn is not None:
                        power_v6_lrn[i, :] = pV6
                    n_ok += 1
                pbar.update(1)
    log.info(f"Fetch + compute: {n_ok} hours OK, {n_fail} failed")

    # ----- Write outputs -----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    idx = pd.DatetimeIndex(hours, tz="UTC", name="Time")
    site_ids = meta_subset["site_id"].tolist()
    methods_out = [("single", power_single),
                   ("multiA", power_multiA),
                   ("multiB", power_multiB),
                   ("v5hub",  power_v5_hub)]
    if power_v6_lrn is not None:
        methods_out.append(("v6lrn", power_v6_lrn))
    for name, arr in methods_out:
        df = pd.DataFrame(arr, index=idx, columns=site_ids)
        out = OUT_DIR / f"multicell_pilot_{args.out_tag}_{name}.csv"
        df.to_csv(out, float_format="%.4f")
        log.info(f"Wrote {out}")

    # ----- Stash inputs/weights too, for downstream review -----
    weights_df = pd.DataFrame(W, index=site_ids,
                              columns=[f"r{r}_c{c}" for r, c in unique_cells])
    weights_df.to_csv(
        OUT_DIR / f"multicell_pilot_{args.out_tag}_weights.csv",
        float_format="%.4f")
    log.info(f"Wrote weights matrix ({W.shape}) for review")
    log.info("Pilot complete. Run score_multicell_pilot.py next for A vs B numbers.")


if __name__ == "__main__":
    main()
