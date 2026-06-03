"""Task 4 — rebuild the DA forecast series on final v4 physics.

Single DAM issuance per day at 18:00 UTC (per the work order), forecasting the
next UTC day's 24 hours from that run's f6..f29. v4 physics: multi-cell Method A
+ clip-0.25 hub-shear (the final adopted physics; Tasks 2/3 triggered no plant
rebuilds). Writes the production Issue_time/Forecast_time format so
06_mos_bias_correction.py --variant .pluswind_v4 can refit the MOS on v4
(actual, forecast) pairs.

Footing-consistency: the forecast uses the SAME v4 physics module as the v4
actuals, so the ~4.8% hub lift is common-mode and cancels in actual−forecast.
The issuance structure differs from v3 (06Z/12Z 4-run blend) — that is a
deliberate, tractable choice; the MOS is refit on v4 pairs so the bias
correction adapts to this structure.

Writes wind_day_ahead_forecast_site_<year>_utc.pluswind_v4.csv. NEVER touches
the v3 forecast or .raw_backup (I4).

Reuses the hardened combined single-fetch (all 6 fields, retry-on-timeout,
catch-all) from run_multicell_pilot. Sequential-solo.

Smoke test (cheap, before the full run):
  python build_v4_forecast.py --start 2020-06-15 --end 2020-06-16 \
      --plants wind_323753 wind_323696 wind_323822 --smoke
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

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "PGscen-2nd"))
from run_multicell_pilot import (  # noqa: E402
    ALL_IDX_PATTERNS, download_subset, _read_grib_bytes, hrrr_s3_key,
    build_plant_cell_weights, load_hrrr_reference_grid,
)
from pgscen.utils.wind_physics import (  # noqa: E402
    build_sam_curves, pluswind_v5_power_multicell_A_hubshear,
)

PM = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
WIND = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
CLIP = {"alpha_max": 0.25}
DAM_INIT_HOUR = 18            # 18:00 UTC issuance
LEAD_FIRST, LEAD_LAST = 6, 29  # f6..f29 covers the next UTC day's hours 00..23


def extract_cells(s3_key, rows, cols):
    """Combined fetch + extract (ws80, ws10, pres, t2m) at cells, or None."""
    blob = download_subset(s3_key, ALL_IDX_PATTERNS)
    if blob is None:
        return None
    g = _read_grib_bytes(blob)
    try:
        ws80 = np.sqrt(g["u"][rows, cols] ** 2 + g["v"][rows, cols] ** 2)
        u10 = g["10u"] if "10u" in g else g["u"]
        v10 = g["10v"] if "10v" in g else g["v"]
        ws10 = np.sqrt(u10[rows, cols] ** 2 + v10[rows, cols] ** 2)
        return ws80, g["sp"][rows, cols], g["2t"][rows, cols], ws10
    except KeyError:
        return None


def forecast_hours(year, start=None, end=None):
    """List of (forecast_time, issue_time, fhour) for the year (or a sub-range).
    Each forecast hour H of UTC day D is issued from (D-1) 18Z at fhour = H + 6."""
    s = start or datetime(year, 1, 1, tzinfo=timezone.utc)
    e = end or datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    out = []
    t = s
    while t < e:
        issue = (t.replace(hour=DAM_INIT_HOUR, minute=0, second=0)
                 - timedelta(days=1))
        fhour = int((t - issue).total_seconds() // 3600)
        if LEAD_FIRST <= fhour <= LEAD_LAST:
            out.append((t, issue, fhour))
        t += timedelta(hours=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--plants", nargs="+", default=None)
    ap.add_argument("--workers", type=int, default=15)
    ap.add_argument("--smoke", action="store_true",
                    help="print head + MOS-pair join sanity, don't write the year file")
    args = ap.parse_args()

    if args.start:
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
        year = start.year
    else:
        year = args.year
        start = end = None

    meta_all = pd.read_csv(PM / "wind_meta.csv")
    turbines = pd.read_csv(PM / "uswtdb_ny_turbines.csv")
    meta_all["operating_year"] = pd.to_numeric(meta_all["operating_year"], errors="coerce")

    # Active plants this year (production convention), optionally subset for smoke.
    active = meta_all[meta_all["operating_year"] <= year].reset_index(drop=True)
    if args.plants:
        active = active[active["site_id"].isin(args.plants)].reset_index(drop=True)
    site_ids = active["site_id"].tolist()

    grid_lat, grid_lon = load_hrrr_reference_grid(year)
    W, cells = build_plant_cell_weights(active, turbines, grid_lat, grid_lon)
    rows_idx = np.array([c[0] for c in cells]); cols_idx = np.array([c[1] for c in cells])
    cws, ccf, crs = build_sam_curves(active, turbines, year=year)
    nameplate = active["nameplate_mw"].to_numpy(float)
    t_hh = turbines.dropna(subset=["t_hh"]).groupby("eia_id")["t_hh"].mean().to_dict()
    hub_h = np.array([float(t_hh.get(int(e), 80.0)) if pd.notna(e) else 80.0
                      for e in active["eia_plant_id"]])
    print(f"year {year}: {len(site_ids)} plants, {len(cells)} cells, hub-shear clip-0.25")

    fhrs = forecast_hours(year, start, end)
    print(f"forecast hours to fetch: {len(fhrs)} (one 18Z DAM issuance/day, f6..f29)")

    def _do(item):
        i, (ftime, issue, fh) = item
        key = hrrr_s3_key(issue.strftime("%Y%m%d"), DAM_INIT_HOUR, fh)
        r = extract_cells(key, rows_idx, cols_idx)
        if r is None:
            return i, None
        ws80, pres, t2m, ws10 = r
        p = pluswind_v5_power_multicell_A_hubshear(
            ws80, ws10, pres, t2m, W, hub_h, nameplate, cws, ccf, crs,
            alpha_kwargs=CLIP)
        return i, p

    power = np.full((len(fhrs), len(site_ids)), np.nan)
    n_ok = n_fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_do, (i, it)): i for i, it in enumerate(fhrs)}
        with tqdm(total=len(futs), desc=f"fc {year}", unit="hr") as pbar:
            for fut in as_completed(futs):
                try:
                    i, p = fut.result()
                except Exception:
                    n_fail += 1; pbar.update(1); continue
                if p is None:
                    n_fail += 1
                else:
                    power[i] = p; n_ok += 1
                pbar.update(1)
    print(f"fetched {n_ok} forecast hours OK, {n_fail} failed")

    df = pd.DataFrame({
        "Issue_time": [it[1] for it in fhrs],
        "Forecast_time": [it[0] for it in fhrs],
    })
    for j, sid in enumerate(site_ids):
        df[sid] = power[:, j]

    if args.smoke:
        print("\n=== SMOKE: forecast head ===")
        print(df.head(6).to_string())
        print("\n=== SMOKE: MOS-pair join vs v4 actuals (same Forecast_time) ===")
        af = WIND / f"wind_actual_1h_site_{year}_utc.pluswind_v4.csv"
        if af.exists():
            act = pd.read_csv(af, parse_dates=["Time"], index_col="Time")
            fc = df.set_index("Forecast_time")
            common = [c for c in site_ids if c in act.columns]
            j = fc[common].join(act[common], lsuffix="_fc", rsuffix="_act", how="inner")
            for c in common:
                pair = j[[f"{c}_fc", f"{c}_act"]].dropna()
                if len(pair):
                    err = (pair[f"{c}_fc"] - pair[f"{c}_act"])
                    print(f"  {c}: n={len(pair)} fc_mean={pair[f'{c}_fc'].mean():.2f} "
                          f"act_mean={pair[f'{c}_act'].mean():.2f} "
                          f"fc-act bias={err.mean():+.2f} MAE={err.abs().mean():.2f}")
        else:
            print(f"  (v4 actuals {af.name} not found for join)")
        return

    out = WIND / f"wind_day_ahead_forecast_site_{year}_utc.pluswind_v4.csv"
    df.to_csv(out, index=False)
    print(f"wrote {out.name} ({len(df)} rows x {len(site_ids)} plants)")


if __name__ == "__main__":
    main()
