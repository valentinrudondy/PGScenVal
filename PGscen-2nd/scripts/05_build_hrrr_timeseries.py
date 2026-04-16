"""
Build HRRR-based actuals and day-ahead forecasts for NY wind and solar plants.

HRRR data source:
    s3://noaa-hrrr-bdp-pds/  (public, no auth)
    Key: hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcfFF.grib2

Actuals  = HRRR F00 analysis (best estimate of atmospheric state at valid hour)
Forecasts = HRRR F18-F41 from 06Z run of previous day (day-ahead forecast)

HRRR versions: v2 (Aug 2016), v3 (Jul 2018), v4 (Dec 2020).
Variable names/levels are stable across versions; skill improves over time.

Usage:
    python 05_build_hrrr_timeseries.py --resource wind --year 2019 \
        --meta data/NYISO_real/plant_metadata/wind_meta.csv \
        --out data/NYISO_real/wind/

    python 05_build_hrrr_timeseries.py --resource solar --year 2019 \
        --meta data/NYISO_real/plant_metadata/solar_meta.csv \
        --out data/NYISO_real/solar/

Dependencies: boto3, botocore, xarray, cfgrib, pvlib, numpy, pandas, scipy, tqdm
System: brew install eccodes (for cfgrib GRIB2 decoding)
"""

from __future__ import annotations

import argparse
import io
import logging
import struct
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import botocore
import numpy as np
import pandas as pd
import xarray as xr
from scipy.spatial import cKDTree
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "cache" / "hrrr"

# ---------------------------------------------------------------------------
# S3 access (public bucket, no credentials)
# ---------------------------------------------------------------------------
S3_BUCKET = "noaa-hrrr-bdp-pds"
_s3_client = None


def get_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            config=botocore.config.Config(
                signature_version=botocore.UNSIGNED,
                max_pool_connections=25,
            ),
        )
    return _s3_client


def hrrr_s3_key(date_str: str, init_hour: int, fhour: int) -> str:
    """S3 key for a HRRR wrfsfc file.
    date_str: 'YYYYMMDD', init_hour: 0-23, fhour: forecast hour 0-48.
    """
    return (
        f"hrrr.{date_str}/conus/"
        f"hrrr.t{init_hour:02d}z.wrfsfcf{fhour:02d}.grib2"
    )


# ---------------------------------------------------------------------------
# Byte-range download using .idx files (downloads ~2-5 MB instead of ~137 MB)
# ---------------------------------------------------------------------------

# GRIB variable specs we need from each file, keyed by resource type.
# Each tuple: (idx_match_string, ...) — patterns to match in .idx lines
WIND_IDX_PATTERNS = ["UGRD:80 m above ground", "VGRD:80 m above ground"]
SOLAR_IDX_PATTERNS = ["DSWRF:surface", "TMP:2 m above ground"]


def parse_idx(idx_text: str) -> list[tuple[int, int, str]]:
    """Parse a HRRR .idx file into (byte_start, byte_end, description) tuples.
    byte_end is the start of the next message (or -1 for the last message).
    """
    lines = [l.strip() for l in idx_text.strip().split("\n") if l.strip()]
    entries = []
    for line in lines:
        parts = line.split(":")
        # format: msg_num:byte_offset:d=YYYYMMDDHH:VAR:LEVEL:FORECAST
        if len(parts) >= 6:
            byte_start = int(parts[1])
            desc = f"{parts[3]}:{parts[4]}"
            entries.append((byte_start, desc))
    # Compute byte ranges
    result = []
    for i, (start, desc) in enumerate(entries):
        end = entries[i + 1][0] - 1 if i + 1 < len(entries) else -1
        result.append((start, end, desc))
    return result


def download_hrrr_subset(
    s3_key: str,
    patterns: list[str],
    cache_dir: Path = CACHE_DIR,
) -> Path | None:
    """Download only the GRIB messages matching `patterns` from a HRRR file.

    Uses the .idx sidecar file to find byte ranges, then fetches only those
    ranges via S3 GetObject with Range header. Result is a minimal GRIB2 file
    cached locally (~2-5 MB instead of ~137 MB).

    Returns local path to the subset GRIB2 file, or None if the file is missing.
    """
    cache_name = s3_key.replace("/", "_")
    # Include a hash of patterns in the cache key to avoid collisions
    # between wind (UGRD/VGRD) and solar (DSWRF/TMP) subsets
    pattern_tag = "wind" if "UGRD" in patterns[0] else "solar"
    local_path = cache_dir / f"{cache_name}.{pattern_tag}.subset"
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path

    s3 = get_s3()

    # 1. Get the .idx file
    idx_key = s3_key + ".idx"
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=idx_key)
        idx_text = resp["Body"].read().decode()
    except botocore.exceptions.ClientError:
        log.warning("No .idx file for %s — skipping", s3_key)
        return None

    # 2. Parse idx and find matching messages
    entries = parse_idx(idx_text)
    ranges = []
    for start, end, desc in entries:
        if any(p in desc for p in patterns):
            ranges.append((start, end))

    if not ranges:
        log.warning("No matching variables in %s for patterns %s", s3_key, patterns)
        return None

    # 3. Download byte ranges and concatenate into a single GRIB2 file
    local_path.parent.mkdir(parents=True, exist_ok=True)
    buf = bytearray()
    for start, end in ranges:
        if end == -1:
            range_header = f"bytes={start}-"
        else:
            range_header = f"bytes={start}-{end}"
        try:
            resp = s3.get_object(
                Bucket=S3_BUCKET, Key=s3_key, Range=range_header
            )
            buf.extend(resp["Body"].read())
        except botocore.exceptions.ClientError as e:
            log.warning("Range request failed for %s range %s: %s", s3_key, range_header, e)
            return None

    local_path.write_bytes(buf)
    return local_path


def download_hrrr_full(s3_key: str, cache_dir: Path = CACHE_DIR) -> Path | None:
    """Download a full HRRR GRIB2 file (fallback if .idx not available)."""
    local_path = cache_dir / s3_key.replace("/", "_")
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        get_s3().download_file(S3_BUCKET, s3_key, str(local_path))
        return local_path
    except botocore.exceptions.ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchKey"):
            log.warning("File not found on S3: %s", s3_key)
        else:
            log.error("S3 error for %s: %s", s3_key, e)
        return None


# ---------------------------------------------------------------------------
# GRIB2 extraction — uses eccodes directly (10-20x faster than cfgrib/xarray)
# ---------------------------------------------------------------------------

import eccodes


def _read_grib_messages(grib_path: Path) -> dict[str, np.ndarray]:
    """Read all messages from a GRIB2 file using eccodes directly.
    Returns dict mapping shortName -> 2D numpy array (nj, ni).
    Also returns 'latitude' and 'longitude' 2D arrays from the first message.
    """
    result = {}
    with open(grib_path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            sn = eccodes.codes_get(gid, "shortName")
            ni = eccodes.codes_get(gid, "Ni")
            nj = eccodes.codes_get(gid, "Nj")
            vals = eccodes.codes_get_values(gid).reshape(nj, ni)
            result[sn] = vals
            if "latitude" not in result:
                result["latitude"] = eccodes.codes_get_array(
                    gid, "latitudes"
                ).reshape(nj, ni)
                result["longitude"] = eccodes.codes_get_array(
                    gid, "longitudes"
                ).reshape(nj, ni)
            eccodes.codes_release(gid)
    return result


def build_hrrr_kdtree_from_grids(
    lats: np.ndarray, lons: np.ndarray,
):
    """Build a KDTree from HRRR lat/lon 2D arrays.
    Returns (tree, grid_shape). HRRR longitudes are 0-360; we convert to -180..180.
    """
    lons = np.where(lons > 180, lons - 360, lons)
    coords = np.column_stack([lats.ravel(), lons.ravel()])
    tree = cKDTree(coords)
    return tree, lats.shape


def precompute_grid_indices_from_grids(
    lats: np.ndarray, lons: np.ndarray, meta: pd.DataFrame,
) -> list[tuple[int, int]]:
    """For each plant in meta, find the (row, col) of the nearest HRRR grid point."""
    tree, grid_shape = build_hrrr_kdtree_from_grids(lats, lons)
    indices = []
    for _, plant in meta.iterrows():
        lat, lon = plant["latitude"], plant["longitude"]
        _, idx = tree.query([lat, lon])
        row, col = np.unravel_index(idx, grid_shape)
        indices.append((int(row), int(col)))
    return indices


def extract_wind_speeds_from_grids(
    grids: dict[str, np.ndarray], indices: list[tuple[int, int]],
) -> np.ndarray:
    """Extract 80m wind speed at all plant locations from eccodes grids."""
    u = grids["u"]
    v = grids["v"]
    rows = [i[0] for i in indices]
    cols = [i[1] for i in indices]
    return np.sqrt(u[rows, cols] ** 2 + v[rows, cols] ** 2)


def extract_ghi_t2m_from_grids(
    grids: dict[str, np.ndarray], indices: list[tuple[int, int]],
) -> tuple[np.ndarray, np.ndarray]:
    """Extract GHI and T2m at all plant locations from eccodes grids."""
    ghi = grids["sdswrf"]
    t2m = grids["2t"]
    rows = [i[0] for i in indices]
    cols = [i[1] for i in indices]
    return ghi[rows, cols], t2m[rows, cols]


# ---------------------------------------------------------------------------
# Power conversion
# ---------------------------------------------------------------------------

def wind_power_from_speed(
    ws: float | np.ndarray, nameplate_mw: float
) -> float | np.ndarray:
    """Generic onshore power curve (modern large-rotor turbines).
    Cut-in: 3 m/s, Rated: 11 m/s, Cut-out: 25 m/s.
    Cubic ramp between cut-in and rated.
    Rated at 11 m/s reflects the fleet-weighted average for NY onshore wind
    (mix of older 12 m/s turbines and newer large-rotor designs at ~10 m/s).
    """
    ws = np.asarray(ws, dtype=float)
    cut_in, rated, cut_out = 3.0, 11.0, 25.0
    power = np.zeros_like(ws)
    ramp = (ws >= cut_in) & (ws < rated)
    power[ramp] = nameplate_mw * ((ws[ramp] - cut_in) / (rated - cut_in)) ** 3
    full = (ws >= rated) & (ws <= cut_out)
    power[full] = nameplate_mw
    return float(power) if power.ndim == 0 else power


def wind_power_all_plants(
    wind_speeds: np.ndarray, nameplates: np.ndarray
) -> np.ndarray:
    """Apply power curve to all plants at once.
    wind_speeds: shape (n_plants,), nameplates: shape (n_plants,).
    Returns: shape (n_plants,) in MW.
    """
    cut_in, rated, cut_out = 3.0, 11.0, 25.0
    power = np.zeros_like(wind_speeds)
    ramp = (wind_speeds >= cut_in) & (wind_speeds < rated)
    power[ramp] = nameplates[ramp] * (
        (wind_speeds[ramp] - cut_in) / (rated - cut_in)
    ) ** 3
    full = (wind_speeds >= rated) & (wind_speeds <= cut_out)
    power[full] = nameplates[full]
    return power


def solar_power_from_weather(
    ghi: float, t2m_kelvin: float,
    lat: float, lon: float,
    timestamp_utc: pd.Timestamp,
    nameplate_mw: float,
    tilt: float | None = None,
    azimuth: float = 180.0,
) -> float:
    """Convert GHI + T2m to AC power using pvlib.

    Simple fixed-tilt model: tilt = latitude (if not specified), south-facing.
    Uses pvlib's DISC model for DNI estimation, then isotropic transposition.
    """
    import pvlib
    from pvlib.location import Location
    from pvlib.irradiance import get_total_irradiance
    from pvlib.temperature import sapm_cell
    from pvlib.pvsystem import pvwatts_dc, pvwatts_losses

    if tilt is None:
        tilt = abs(lat)

    loc = Location(lat, lon, tz="UTC")
    times = pd.DatetimeIndex([timestamp_utc], tz="UTC")
    solpos = loc.get_solarposition(times)
    zenith = solpos["apparent_zenith"].iloc[0]
    azimuth_sun = solpos["azimuth"].iloc[0]

    if zenith >= 90 or ghi <= 0:
        return 0.0

    disc_out = pvlib.irradiance.disc(ghi, zenith, times)
    dni = float(disc_out["dni"].iloc[0])
    dhi = ghi - dni * np.cos(np.radians(zenith))
    dhi = max(dhi, 0.0)

    poa = get_total_irradiance(
        surface_tilt=tilt, surface_azimuth=azimuth,
        solar_zenith=zenith, solar_azimuth=azimuth_sun,
        dni=dni, ghi=ghi, dhi=dhi,
    )
    poa_global = float(poa["poa_global"])
    if poa_global <= 0:
        return 0.0

    t_air_c = t2m_kelvin - 273.15
    t_cell = float(sapm_cell(poa_global, t_air_c, 1.0, -3.56, -0.0750, 3.0))

    nameplate_w = nameplate_mw * 1e6
    pdc = float(pvwatts_dc(poa_global, t_cell, nameplate_w, -0.004))

    losses = pvwatts_losses()
    loss_frac = losses / 100 if isinstance(losses, (int, float)) else 0.14
    pac_mw = pdc * (1 - loss_frac) / 1e6

    return float(np.clip(pac_mw, 0, nameplate_mw))


# ---------------------------------------------------------------------------
# Job definitions: what to download for each hour
# ---------------------------------------------------------------------------

def actual_job(valid_time: datetime) -> tuple[str, str]:
    """S3 key for the F00 analysis at valid_time.
    Returns (s3_key, job_type='actual').
    """
    date_str = valid_time.strftime("%Y%m%d")
    init_hour = valid_time.hour
    return hrrr_s3_key(date_str, init_hour, 0), "actual"


def forecast_job(valid_time: datetime) -> tuple[str, str]:
    """S3 key for a single day-ahead forecast (legacy, used by solar)."""
    if valid_time.hour <= 18:
        init_day = valid_time - timedelta(days=1)
        date_str = init_day.strftime("%Y%m%d")
        fhour = valid_time.hour + 18
        return hrrr_s3_key(date_str, 6, fhour), "forecast"
    else:
        init_day = valid_time - timedelta(days=1)
        date_str = init_day.strftime("%Y%m%d")
        fhour = valid_time.hour + 12
        return hrrr_s3_key(date_str, 12, fhour), "forecast"


def forecast_jobs_blend(valid_time: datetime, max_fhour: int = 36,
                        min_lead_hours: int = 24) -> list[tuple[str, float]]:
    """Return multiple (s3_key, weight) tuples for blending day-ahead forecasts.

    Checks 4 candidate HRRR extended runs. Includes a run only if:
      - lead time >= min_lead_hours (default 24h)
      - forecast horizon <= max_fhour (default 36, safe for all HRRR versions)

    Returns equal-weighted list. If no run qualifies, falls back to the
    closest single run with lead >= 18h.
    """
    candidates = []
    # Candidate init times: (day_offset, init_hour)
    # day_offset: 0 = same day as valid_time, -1 = previous day, etc.
    for day_off, init_h in [(-1, 0), (-1, 6), (-1, 12), (-2, 18)]:
        init_time = datetime(
            valid_time.year, valid_time.month, valid_time.day,
            init_h, 0, 0, tzinfo=timezone.utc
        ) + timedelta(days=day_off)
        lead_hours = (valid_time - init_time).total_seconds() / 3600
        fhour = int(lead_hours)
        if lead_hours >= min_lead_hours and fhour <= max_fhour:
            date_str = init_time.strftime("%Y%m%d")
            s3_key = hrrr_s3_key(date_str, init_h, fhour)
            candidates.append(s3_key)

    if candidates:
        w = 1.0 / len(candidates)
        return [(k, w) for k in candidates]

    # Fallback: use the single closest run (legacy behavior)
    fk, _ = forecast_job(valid_time)
    return [(fk, 1.0)]


# ---------------------------------------------------------------------------
# Numpy array cache — avoids re-parsing GRIB files (~100x faster on re-runs)
#
# Strategy: cache values for ALL plant locations (the full metadata set) in
# one npz per GRIB file, keyed only by s3_key + resource. Any year's subset
# of plants indexes into the same cached array. This means one GRIB parse
# serves all 6 years instead of separate parses per year.
# ---------------------------------------------------------------------------

NPZ_CACHE_DIR = CACHE_DIR / "npz_v2"


def _hash_indices(indices: list[tuple[int, int]]) -> str:
    """Short hash of plant grid indices (kept for API compat)."""
    import hashlib
    return hashlib.md5(str(indices).encode()).hexdigest()[:8]

# Global registry of all plant grid indices (set once at startup)
_ALL_WIND_INDICES: list[tuple[int, int]] | None = None
_ALL_SOLAR_INDICES: list[tuple[int, int]] | None = None


def set_all_indices(resource: str, indices: list[tuple[int, int]]):
    """Register the full set of plant grid indices for universal caching."""
    global _ALL_WIND_INDICES, _ALL_SOLAR_INDICES
    if resource == "wind":
        _ALL_WIND_INDICES = indices
    else:
        _ALL_SOLAR_INDICES = indices


def _npz_cache_path_v2(s3_key: str, resource: str) -> Path:
    """Cache path — keyed only by s3_key + resource, not by plant subset."""
    name = s3_key.replace("/", "_")
    return NPZ_CACHE_DIR / f"{name}.{resource}.npz"


def extract_wind_cached(
    s3_key: str,
    indices: list[tuple[int, int]],
    indices_hash: str,  # kept for API compat, not used in cache key
) -> np.ndarray | None:
    """Extract 80m wind speeds at plant locations, with universal npz cache.
    Caches ALL plant locations; returns only the subset for `indices`.
    """
    all_indices = _ALL_WIND_INDICES or indices
    npz_path = _npz_cache_path_v2(s3_key, "wind")

    if npz_path.exists():
        all_ws = np.load(npz_path)["ws"]
    else:
        local_path = download_hrrr_subset(s3_key, WIND_IDX_PATTERNS)
        if local_path is None:
            return None
        try:
            grids = _read_grib_messages(local_path)
            all_ws = extract_wind_speeds_from_grids(grids, all_indices)
            npz_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(npz_path, ws=all_ws)
        except Exception as e:
            log.warning("Failed to extract wind from %s: %s", s3_key, e)
            return None

    # Select subset for this year's active plants
    if indices is all_indices or len(indices) == len(all_indices):
        return all_ws
    # Map this year's indices to positions in the all_indices array
    idx_map = {v: i for i, v in enumerate(all_indices)}
    subset = np.array([all_ws[idx_map[idx]] for idx in indices])
    return subset


def extract_solar_cached(
    s3_key: str,
    indices: list[tuple[int, int]],
    indices_hash: str,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Extract GHI and T2m at plant locations, with universal npz cache."""
    all_indices = _ALL_SOLAR_INDICES or indices
    npz_path = _npz_cache_path_v2(s3_key, "solar")

    if npz_path.exists():
        data = np.load(npz_path)
        all_ghi, all_t2m = data["ghi"], data["t2m"]
    else:
        local_path = download_hrrr_subset(s3_key, SOLAR_IDX_PATTERNS)
        if local_path is None:
            return None
        try:
            grids = _read_grib_messages(local_path)
            all_ghi, all_t2m = extract_ghi_t2m_from_grids(grids, all_indices)
            npz_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(npz_path, ghi=all_ghi, t2m=all_t2m)
        except Exception as e:
            log.warning("Failed to extract solar from %s: %s", s3_key, e)
            return None

    if indices is all_indices or len(indices) == len(all_indices):
        return all_ghi, all_t2m
    idx_map = {v: i for i, v in enumerate(all_indices)}
    sub_ghi = np.array([all_ghi[idx_map[idx]] for idx in indices])
    sub_t2m = np.array([all_t2m[idx_map[idx]] for idx in indices])
    return sub_ghi, sub_t2m


def build_wind_timeseries(
    meta: pd.DataFrame, year: int, out_dir: Path, n_workers: int = 15
):
    """Build actuals and day-ahead forecast CSVs for wind, one year."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Filter plants operating by this year
    meta = meta.copy()
    meta["operating_year"] = pd.to_numeric(meta["operating_year"], errors="coerce")
    active = meta[meta["operating_year"] <= year].reset_index(drop=True)
    inactive_ids = set(meta["site_id"]) - set(active["site_id"])
    if inactive_ids:
        log.info(
            "Year %d: %d plants not yet operating, excluded: %s",
            year, len(inactive_ids), inactive_ids,
        )
    log.info(
        "Year %d: %d active wind plants, %.0f MW total nameplate",
        year, len(active), active["nameplate_mw"].sum(),
    )

    site_ids = active["site_id"].tolist()
    nameplates = active["nameplate_mw"].values.astype(float)

    # Precompute grid indices from a single reference file.
    # We compute indices for ALL plants (not just active) so the npz cache
    # is universal across years. Then we select the active subset.
    log.info("Downloading reference HRRR file to build KDTree...")
    ref_key = hrrr_s3_key(f"{year}0615", 6, 18)
    ref_path = download_hrrr_subset(ref_key, WIND_IDX_PATTERNS)
    if ref_path is None:
        ref_key = hrrr_s3_key(f"{year}0701", 6, 18)
        ref_path = download_hrrr_subset(ref_key, WIND_IDX_PATTERNS)
    if ref_path is None:
        raise RuntimeError("Cannot download any reference HRRR file")
    grids_ref = _read_grib_messages(ref_path)

    # Indices for ALL plants (universal cache)
    all_indices = precompute_grid_indices_from_grids(
        grids_ref["latitude"], grids_ref["longitude"], meta
    )
    set_all_indices("wind", all_indices)

    # Indices for this year's active plants (subset of all_indices)
    active_mask = meta["site_id"].isin(set(active["site_id"]))
    indices = [all_indices[i] for i in range(len(meta)) if active_mask.iloc[i]]
    log.info("Grid indices: %d all plants, %d active this year.", len(all_indices), len(indices))

    # Build list of all hours in the year
    start = datetime(year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    hours = []
    t = start
    while t < end:
        hours.append(t)
        t += timedelta(hours=1)
    n_hours = len(hours)
    log.info("Year %d: %d hours to process", year, n_hours)

    # Prepare storage
    actual_data = np.full((n_hours, len(active)), np.nan)
    forecast_data = np.full((n_hours, len(active)), 0.0)
    forecast_weight = np.full((n_hours, len(active)), 0.0)

    # Build job list with multi-run blending for forecasts
    from collections import defaultdict
    key_to_jobs = defaultdict(list)  # s3_key -> [(hour_idx, job_type, weight)]

    for i, h in enumerate(hours):
        # Actuals: single F00 file, weight=1
        ak, _ = actual_job(h)
        key_to_jobs[ak].append((i, "actual", 1.0))

        # Forecasts: multiple blended runs
        for fk, w in forecast_jobs_blend(h):
            key_to_jobs[fk].append((i, "forecast", w))

    unique_keys = list(key_to_jobs.keys())
    log.info("Total unique HRRR files to download: %d", len(unique_keys))

    # Compute indices hash for npz caching
    idx_hash = _hash_indices(indices)
    log.info("Indices hash: %s (changes if plant list changes)", idx_hash)

    # Process with thread pool — uses npz cache for instant re-runs
    def _process(s3_key):
        ws = extract_wind_cached(s3_key, indices, idx_hash)
        if ws is None:
            return s3_key, None
        return s3_key, wind_power_all_plants(ws, nameplates)

    n_success = 0
    n_fail = 0
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_process, k): k for k in unique_keys}
        with tqdm(total=len(futures), desc=f"Wind {year}", unit="file") as pbar:
            for future in as_completed(futures):
                s3_key, power = future.result()
                if power is not None:
                    for hour_idx, job_type, weight in key_to_jobs[s3_key]:
                        if job_type == "actual":
                            actual_data[hour_idx, :] = power
                        else:
                            forecast_data[hour_idx, :] += power * weight
                            forecast_weight[hour_idx, :] += weight
                    n_success += 1
                else:
                    n_fail += 1
                pbar.update(1)

    # Normalize blended forecast by total weight (handles missing runs)
    valid_fc = forecast_weight > 0
    forecast_data[valid_fc] = forecast_data[valid_fc] / forecast_weight[valid_fc]
    forecast_data[~valid_fc] = np.nan

    log.info("Done. Success: %d, Failed: %d", n_success, n_fail)

    # Check for gaps
    actual_missing = np.isnan(actual_data).all(axis=1).sum()
    forecast_missing = np.isnan(forecast_data).all(axis=1).sum()
    log.info(
        "Missing hours — actual: %d/%d (%.1f%%), forecast: %d/%d (%.1f%%)",
        actual_missing, n_hours, 100 * actual_missing / n_hours,
        forecast_missing, n_hours, 100 * forecast_missing / n_hours,
    )

    # Build DataFrames
    time_index = pd.DatetimeIndex(hours, tz="UTC", name="Time")

    # --- Actuals CSV ---
    df_actual = pd.DataFrame(actual_data, index=time_index, columns=site_ids)
    actual_path = out_dir / f"wind_actual_1h_site_{year}_utc.csv"
    df_actual.to_csv(actual_path)
    log.info("Wrote %s (%d rows x %d cols)", actual_path, len(df_actual), len(site_ids))

    # --- Forecast CSV ---
    # Format: Issue_time, Forecast_time, site_1, ..., site_N
    # Issue_time depends on which HRRR run was used:
    #   hours 00-18 UTC: J-1 06:00 UTC
    #   hours 19-23 UTC: J-1 12:00 UTC
    forecast_rows = []
    for i, h in enumerate(hours):
        if h.hour <= 18:
            issue_t = datetime(
                h.year, h.month, h.day, 6, 0, 0, tzinfo=timezone.utc
            ) - timedelta(days=1)
        else:
            issue_t = datetime(
                h.year, h.month, h.day, 12, 0, 0, tzinfo=timezone.utc
            ) - timedelta(days=1)
        row = {"Issue_time": issue_t, "Forecast_time": h}
        for j, sid in enumerate(site_ids):
            row[sid] = forecast_data[i, j]
        forecast_rows.append(row)

    df_forecast = pd.DataFrame(forecast_rows)
    forecast_path = out_dir / f"wind_day_ahead_forecast_site_{year}_utc.csv"
    df_forecast.to_csv(forecast_path, index=False)
    log.info(
        "Wrote %s (%d rows x %d cols)", forecast_path, len(df_forecast), len(site_ids)
    )

    return df_actual, df_forecast


# ---------------------------------------------------------------------------
# Solar pipeline (Step 6)
# ---------------------------------------------------------------------------

def build_solar_timeseries(
    meta: pd.DataFrame, year: int, out_dir: Path, n_workers: int = 15
):
    """Build actuals and day-ahead forecast CSVs for solar, one year."""
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = meta.copy()
    meta["operating_year"] = pd.to_numeric(meta["operating_year"], errors="coerce")
    active = meta[meta["operating_year"] <= year].reset_index(drop=True)
    inactive_ids = set(meta["site_id"]) - set(active["site_id"])
    if inactive_ids:
        log.info(
            "Year %d: %d solar plants not yet operating, excluded: %s",
            year, len(inactive_ids), inactive_ids,
        )
    log.info(
        "Year %d: %d active solar plants, %.0f MW total nameplate",
        year, len(active), active["nameplate_mw"].sum(),
    )

    site_ids = active["site_id"].tolist()
    nameplates = active["nameplate_mw"].values.astype(float)
    lats = active["latitude"].values.astype(float)
    lons = active["longitude"].values.astype(float)

    # Precompute grid indices (universal cache for all plants)
    log.info("Downloading reference HRRR file to build KDTree (solar)...")
    ref_key = hrrr_s3_key(f"{year}0615", 6, 18)
    ref_path = download_hrrr_subset(ref_key, SOLAR_IDX_PATTERNS)
    if ref_path is None:
        ref_key = hrrr_s3_key(f"{year}0701", 6, 18)
        ref_path = download_hrrr_subset(ref_key, SOLAR_IDX_PATTERNS)
    if ref_path is None:
        raise RuntimeError("Cannot download reference HRRR file for solar")
    grids_ref = _read_grib_messages(ref_path)

    all_indices = precompute_grid_indices_from_grids(
        grids_ref["latitude"], grids_ref["longitude"], meta
    )
    set_all_indices("solar", all_indices)

    active_mask = meta["site_id"].isin(set(active["site_id"]))
    indices = [all_indices[i] for i in range(len(meta)) if active_mask.iloc[i]]
    log.info("Grid indices: %d all plants, %d active this year.", len(all_indices), len(indices))

    # All hours in the year
    start = datetime(year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    hours = []
    t = start
    while t < end:
        hours.append(t)
        t += timedelta(hours=1)
    n_hours = len(hours)

    actual_data = np.full((n_hours, len(active)), np.nan)
    forecast_data = np.full((n_hours, len(active)), np.nan)

    # For solar, we need the valid timestamp for pvlib solar position.
    # We process file-by-file: download, extract GHI+T2m, convert to power.

    from collections import defaultdict
    jobs = []
    for i, h in enumerate(hours):
        ak, _ = actual_job(h)
        fk, _ = forecast_job(h)
        jobs.append((i, ak, "actual"))
        jobs.append((i, fk, "forecast"))

    key_to_jobs = defaultdict(list)
    for hour_idx, s3_key, job_type in jobs:
        key_to_jobs[s3_key].append((hour_idx, job_type))

    unique_keys = list(key_to_jobs.keys())
    log.info("Total unique HRRR files for solar: %d", len(unique_keys))

    # Compute indices hash for npz caching
    idx_hash = _hash_indices(indices)
    log.info("Indices hash: %s", idx_hash)

    # Phase 1: Extract weather data (download + GRIB parse, or npz cache hit)
    # Use thread pool for downloads, sequential for GRIB parsing
    def _extract_one(s3_key):
        return s3_key, extract_solar_cached(s3_key, indices, idx_hash)

    extracted = {}  # s3_key -> (ghi_arr, t2m_arr)
    n_dl_fail = 0
    log.info("Phase 1: extracting solar weather data (with npz cache)...")
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_extract_one, k): k for k in unique_keys}
        with tqdm(total=len(futures), desc=f"Solar extract {year}", unit="file") as pbar:
            for future in as_completed(futures):
                s3_key, result = future.result()
                if result is not None:
                    extracted[s3_key] = result
                else:
                    n_dl_fail += 1
                pbar.update(1)

    log.info("Extracted %d files, %d failed", len(extracted), n_dl_fail)

    # Phase 2: Convert weather to power (pvlib — CPU bound, sequential)
    n_success = 0
    log.info("Phase 2: converting weather to solar power...")
    for s3_key in tqdm(extracted, desc=f"Solar power {year}", unit="file"):
        ghi_arr, t2m_arr = extracted[s3_key]
        for hour_idx, job_type in key_to_jobs[s3_key]:
            valid_time = hours[hour_idx]
            ts = pd.Timestamp(valid_time)
            powers = np.zeros(len(active))
            for j in range(len(active)):
                powers[j] = solar_power_from_weather(
                    float(ghi_arr[j]),
                    float(t2m_arr[j]),
                    lats[j], lons[j],
                    ts, nameplates[j],
                )
            if job_type == "actual":
                actual_data[hour_idx, :] = powers
            else:
                forecast_data[hour_idx, :] = powers
        n_success += 1

    log.info("Solar done. Success: %d, Failed: %d", n_success, n_dl_fail)

    actual_missing = np.isnan(actual_data).all(axis=1).sum()
    forecast_missing = np.isnan(forecast_data).all(axis=1).sum()
    log.info(
        "Missing hours — actual: %d/%d, forecast: %d/%d",
        actual_missing, n_hours, forecast_missing, n_hours,
    )

    time_index = pd.DatetimeIndex(hours, tz="UTC", name="Time")

    df_actual = pd.DataFrame(actual_data, index=time_index, columns=site_ids)
    actual_path = out_dir / f"solar_actual_1h_site_{year}_utc.csv"
    df_actual.to_csv(actual_path)
    log.info("Wrote %s", actual_path)

    forecast_rows = []
    for i, h in enumerate(hours):
        if h.hour <= 18:
            issue_t = datetime(
                h.year, h.month, h.day, 6, 0, 0, tzinfo=timezone.utc
            ) - timedelta(days=1)
        else:
            issue_t = datetime(
                h.year, h.month, h.day, 12, 0, 0, tzinfo=timezone.utc
            ) - timedelta(days=1)
        row = {"Issue_time": issue_t, "Forecast_time": h}
        for j, sid in enumerate(site_ids):
            row[sid] = forecast_data[i, j]
        forecast_rows.append(row)

    df_forecast = pd.DataFrame(forecast_rows)
    forecast_path = out_dir / f"solar_day_ahead_forecast_site_{year}_utc.csv"
    df_forecast.to_csv(forecast_path, index=False)
    log.info("Wrote %s", forecast_path)

    return df_actual, df_forecast


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Build HRRR-based wind/solar timeseries for PGScen-NYISO"
    )
    ap.add_argument(
        "--resource", required=True, choices=["wind", "solar"],
        help="Resource type to process",
    )
    ap.add_argument("--year", required=True, type=int, help="Year to process")
    ap.add_argument(
        "--meta", required=True, type=Path,
        help="Path to plant metadata CSV (wind_meta.csv or solar_meta.csv)",
    )
    ap.add_argument(
        "--out", required=True, type=Path,
        help="Output directory for CSV files",
    )
    ap.add_argument(
        "--workers", type=int, default=15,
        help="Number of parallel download workers (default: 15)",
    )
    args = ap.parse_args()

    meta = pd.read_csv(args.meta)
    log.info(
        "Loaded %d %s plants from %s", len(meta), args.resource, args.meta
    )

    if args.resource == "wind":
        build_wind_timeseries(meta, args.year, args.out, n_workers=args.workers)
    else:
        build_solar_timeseries(meta, args.year, args.out, n_workers=args.workers)


if __name__ == "__main__":
    main()
