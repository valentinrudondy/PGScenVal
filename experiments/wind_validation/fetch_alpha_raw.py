"""R1.1 step 1 — fetch raw HRRR ws80 / ws10 / pres / t2m for the alpha
(shear-exponent) diagnostic and the offline alpha-sensitivity sweep.

S3 cost is one GET per hour per variable-set, INDEPENDENT of how many cells
we extract from each downloaded GRIB. So we extract the union of every HRRR
cell the full 31-plant fleet touches (~180 cells) for the same cost as the
5-plant pilot — giving a fleet-wide alpha distribution for free.

One fetch, then every alpha treatment (full / clip / climatology-blend) is
computed offline by analyze_alpha.py — no re-fetching.

Output: docs/figures/wind_v3/alpha_raw_<year>.npz containing
  ws80, ws10, pres, t2m   — float arrays (n_hours, n_cells)
  times                   — int64 epoch-seconds (n_hours,)
  cell_rows, cell_cols    — int arrays (n_cells,)  [HRRR grid indices]
  W                       — (n_plants, n_cells) plant->cell weight matrix
  site_ids                — (n_plants,) str
  nameplate_mw, hub_h     — (n_plants,) float
  dominant_cell_col       — (n_plants,) int  [argmax of W, for single-cell]
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_multicell_pilot import (  # noqa: E402
    build_plant_cell_weights,
    fetch_one_hour,
    load_hrrr_reference_grid,
)

PM_DIR  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
OUT_DIR = REPO_ROOT / "docs" / "figures" / "wind_v3"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", required=True, type=int)
    ap.add_argument("--workers", type=int, default=15)
    args = ap.parse_args()
    year = args.year

    meta = pd.read_csv(PM_DIR / "wind_meta.csv")
    turbines = pd.read_csv(PM_DIR / "uswtdb_ny_turbines.csv")

    # Map the FULL fleet to HRRR cells (union ~180 cells).
    print(f"Fetching HRRR reference grid for {year}…", flush=True)
    grid_lat, grid_lon = load_hrrr_reference_grid(year)
    W, unique_cells = build_plant_cell_weights(meta, turbines, grid_lat, grid_lon)
    print(f"Full fleet: W {W.shape}; {len(unique_cells)} unique HRRR cells")

    # Per-plant hub heights (USWTDB t_hh mean; 80 m fallback).
    t_hh = (turbines.dropna(subset=["t_hh"])
            .groupby("eia_id")["t_hh"].mean().to_dict())
    hub_h = np.array([
        float(t_hh.get(int(e), 80.0)) if pd.notna(e) else 80.0
        for e in meta["eia_plant_id"]], dtype=float)
    dominant_cell_col = W.argmax(axis=1)

    # Hours for the full year.
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end   = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    hours = []
    t = start
    while t < end:
        hours.append(t); t += timedelta(hours=1)
    n_hours = len(hours)
    n_cells = len(unique_cells)
    print(f"Year {year}: {n_hours} hours × {n_cells} cells")

    ws80 = np.full((n_hours, n_cells), np.nan)
    ws10 = np.full((n_hours, n_cells), np.nan)
    pres = np.full((n_hours, n_cells), np.nan)
    t2m  = np.full((n_hours, n_cells), np.nan)

    def _do(i_h):
        i, h = i_h
        try:
            return i, fetch_one_hour(h, unique_cells)
        except Exception:
            return i, None      # never let one bad hour crash the pool

    n_ok = n_fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_do, (i, h)): i for i, h in enumerate(hours)}
        with tqdm(total=len(futs), desc=f"alpha-raw {year}", unit="hr") as pbar:
            for fut in as_completed(futs):
                try:
                    i, r = fut.result()
                except Exception:
                    n_fail += 1; pbar.update(1); continue
                if r is None:
                    n_fail += 1
                else:
                    _, a_ws80, a_pres, a_t2m, a_ws10 = r
                    ws80[i, :] = a_ws80
                    ws10[i, :] = a_ws10
                    pres[i, :] = a_pres
                    t2m[i, :]  = a_t2m
                    n_ok += 1
                pbar.update(1)
    print(f"Fetched {n_ok} hours OK, {n_fail} failed")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"alpha_raw_{year}.npz"
    times = np.array([int(h.timestamp()) for h in hours], dtype=np.int64)
    np.savez_compressed(
        out,
        ws80=ws80, ws10=ws10, pres=pres, t2m=t2m,
        times=times,
        cell_rows=np.array([rc[0] for rc in unique_cells]),
        cell_cols=np.array([rc[1] for rc in unique_cells]),
        W=W,
        site_ids=np.array(meta["site_id"].tolist()),
        nameplate_mw=meta["nameplate_mw"].to_numpy(float),
        hub_h=hub_h,
        dominant_cell_col=dominant_cell_col,
    )
    print(f"Wrote {out}  ({out.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
