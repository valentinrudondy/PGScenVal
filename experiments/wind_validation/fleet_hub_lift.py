"""R1.1 — fleet-wide hub-shear lift under the adopted clip-0.25 treatment.

Answers "what does hub-shear do to the OTHER plants?" Uses alpha_raw_2020.npz
(all 31 plants' cell weights + hub heights + 180 fleet cells) to compute each
plant's annual-mean modeled power under v4 (no hub) vs v5 (multi-A + hub shear,
alpha clipped at 0.25), and the lift ratio. The 80 m plants must be ~1.00
(invariant); the lift scales with hub height and local shear.

Output: docs/figures/wind_v3/fleet_hub_lift_clip025.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "PGscen-2nd"))
from pgscen.utils.wind_physics import (  # noqa: E402
    build_sam_curves, pluswind_v4_power_multicell_A,
    pluswind_v5_power_multicell_A_hubshear,
)

PM_DIR  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
OUT_DIR = REPO_ROOT / "docs" / "figures" / "wind_v3"
CLIP = {"alpha_max": 0.25}


def main():
    d = np.load(OUT_DIR / "alpha_raw_2020.npz", allow_pickle=True)
    ws80, ws10, pres, t2m = d["ws80"], d["ws10"], d["pres"], d["t2m"]
    W = d["W"]; site_ids = [str(s) for s in d["site_ids"]]
    nameplate = d["nameplate_mw"]; hub_h = d["hub_h"]
    n_hours = ws80.shape[0]

    meta = pd.read_csv(PM_DIR / "wind_meta.csv").set_index("site_id")
    turbines = pd.read_csv(PM_DIR / "uswtdb_ny_turbines.csv")
    meta_ord = meta.loc[site_ids].reset_index()
    curve_ws, curve_cf, rated_ws = build_sam_curves(meta_ord, turbines, year=2020)

    sum_v4 = np.zeros(len(site_ids))
    sum_v5 = np.zeros(len(site_ids))
    n_ok = 0
    for h in range(n_hours):
        if np.isnan(ws80[h]).all():
            continue
        v4 = pluswind_v4_power_multicell_A(
            ws80[h], pres[h], t2m[h], W, nameplate, curve_ws, curve_cf, rated_ws)
        v5 = pluswind_v5_power_multicell_A_hubshear(
            ws80[h], ws10[h], pres[h], t2m[h], W, hub_h, nameplate,
            curve_ws, curve_cf, rated_ws, alpha_kwargs=CLIP)
        sum_v4 += np.nan_to_num(v4)
        sum_v5 += np.nan_to_num(v5)
        n_ok += 1

    mean_v4 = sum_v4 / n_ok
    mean_v5 = sum_v5 / n_ok
    rows = []
    for i, sid in enumerate(site_ids):
        rows.append({
            "site_id": sid,
            "name": meta.loc[sid, "site_name"][:34],
            "op_year": int(meta.loc[sid, "operating_year"]),
            "hub_h_m": round(float(hub_h[i]), 1),
            "nameplate_mw": float(nameplate[i]),
            "mean_v4_mw": round(float(mean_v4[i]), 3),
            "mean_v5_clip025_mw": round(float(mean_v5[i]), 3),
            "lift_pct": round(100 * (mean_v5[i] - mean_v4[i]) / mean_v4[i], 2)
                        if mean_v4[i] > 0 else float("nan"),
        })
    df = pd.DataFrame(rows).sort_values("hub_h_m")
    df.to_csv(OUT_DIR / "fleet_hub_lift_clip025.csv", index=False)

    pd.set_option("display.width", 200)
    print("=" * 92)
    print("Fleet hub-shear lift under clip-0.25 (2020 HRRR, all 31 plants)")
    print("=" * 92)
    print(df.to_string(index=False))

    # Fleet-weighted lift + tier summary
    fleet_v4 = mean_v4.sum(); fleet_v5 = mean_v5.sum()
    print(f"\nFleet-sum mean power: v4 {fleet_v4:.1f} MW -> v5_clip025 {fleet_v5:.1f} MW "
          f"({100*(fleet_v5-fleet_v4)/fleet_v4:+.2f}%)")
    for lo, hi, lbl in [(0, 82, "<=82 m (baseline)"),
                        (82, 100, "82-100 m"),
                        (100, 999, ">100 m")]:
        m = (df["hub_h_m"] > lo) & (df["hub_h_m"] <= hi)
        if m.any():
            print(f"  hub {lbl:18s}: {m.sum():2d} plants, "
                  f"lift {df[m]['lift_pct'].min():+.1f}% .. {df[m]['lift_pct'].max():+.1f}% "
                  f"(mean {df[m]['lift_pct'].mean():+.1f}%)")


if __name__ == "__main__":
    main()
