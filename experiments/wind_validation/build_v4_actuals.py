"""R2.1 — build the v4 actuals series from a year's raw HRRR npz.

v4 = multi-cell Method A + clip-0.25 hub-shear (the R1.1-adopted physics),
all 31 plants, written in the production CSV format
(wind_actual_1h_site_<year>_utc.pluswind_v4.csv) so it is a drop-in for the
.pluswind_v3 actuals Stage A consumes.

Reads docs/figures/wind_v3/alpha_raw_<year>.npz (produced by fetch_alpha_raw.py
AFTER the R1.3 metadata fixes, so Canandaigua/Baron are correct). Computes
per-hour power for all 31 plants, writes only the columns active that year
(operating_year <= year, matching the v3 active-plant convention). Keeps v3 +
.raw_backup untouched (I4).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "PGscen-2nd"))
from pgscen.utils.wind_physics import (  # noqa: E402
    build_sam_curves, pluswind_v5_power_multicell_A_hubshear,
)

PM_DIR   = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
WIND_DIR = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
RAW_DIR  = REPO_ROOT / "docs" / "figures" / "wind_v3"
CLIP = {"alpha_max": 0.25}    # R1.1-adopted hub-shear treatment


def build_year(year: int) -> Path | None:
    npz = RAW_DIR / f"alpha_raw_{year}.npz"
    if not npz.exists():
        print(f"  {year}: {npz.name} missing — skip")
        return None
    d = np.load(npz, allow_pickle=True)
    ws80, ws10, pres, t2m = d["ws80"], d["ws10"], d["pres"], d["t2m"]
    W = d["W"]; hub_h = d["hub_h"]
    npz_site_ids = [str(s) for s in d["site_ids"]]
    times = pd.to_datetime(d["times"], unit="s", utc=True)
    n_hours = ws80.shape[0]

    # Rebuild SAM curves (year-aware overrides) in npz site order from CURRENT
    # wind_meta (so the R1.3 Baron nameplate + Canandaigua EIA-ID fixes apply).
    meta = pd.read_csv(PM_DIR / "wind_meta.csv").set_index("site_id")
    turbines = pd.read_csv(PM_DIR / "uswtdb_ny_turbines.csv")
    meta_ord = meta.loc[npz_site_ids].reset_index()
    curve_ws, curve_cf, rated_ws = build_sam_curves(meta_ord, turbines, year=year)
    nameplate = meta_ord["nameplate_mw"].to_numpy(float)

    # Per-hour power for all 31 plants (clip-0.25 hub-shear).
    P = np.full((n_hours, len(npz_site_ids)), np.nan)
    for h in range(n_hours):
        if np.isnan(ws80[h]).all():
            continue
        P[h] = pluswind_v5_power_multicell_A_hubshear(
            ws80[h], ws10[h], pres[h], t2m[h], W, hub_h,
            nameplate, curve_ws, curve_cf, rated_ws, alpha_kwargs=CLIP)

    df = pd.DataFrame(P, index=times, columns=npz_site_ids)
    df.index.name = "Time"

    # Active-plant filter (matches v3 build_wind_timeseries): operating_year <= year.
    op_year = meta_ord.set_index("site_id")["operating_year"].astype(int)
    active = [s for s in npz_site_ids if op_year[s] <= year]
    df = df[active]

    out = WIND_DIR / f"wind_actual_1h_site_{year}_utc.pluswind_v4.csv"
    df.to_csv(out, float_format="%.6f")
    miss = int(np.isnan(P).all(axis=1).sum())
    print(f"  {year}: wrote {out.name}  ({len(df)} hrs x {len(active)} active "
          f"plants; {miss} all-NaN hrs; fleet mean {df.sum(axis=1).mean():.0f} MW)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+",
                    default=list(range(2018, 2025)))
    args = ap.parse_args()
    print(f"Building v4 actuals (multi-A + clip-0.25 hub-shear) for {args.years}")
    for y in args.years:
        build_year(y)


if __name__ == "__main__":
    main()
