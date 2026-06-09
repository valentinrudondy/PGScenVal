"""Why is the per-plant fan mildly over-conservative? (cov_80 mean 0.826 vs 0.80)

Diagnostic only — does NOT touch the ship config. For each held-out 2024 day we run
the shipped model (run_one_day, pre-COD fix on) and, per (plant, hour) with the plant
online and the actual finite, record the ensemble dispersion the engine SAMPLED and
the realized error. Per plant we then compute the spread-skill ratio and decompose the
over-dispersion into a YEAR effect vs a BINNING effect:

  sigma_scen  : mean per-(day,hour) ensemble std            (the fan dispersion sampled)
  skill       : RMSE per-(day,hour) of (actual - p50)       (the realized error of the median)
  ratio       : sigma_scen / skill                          (>1 => fan too wide => over-cover)

  sigma_pool  : std of the plant's FULL post-COD operating deviations (2018-2024 pool)
  sigma_2024  : std of the plant's 2024 operating deviations
  year_ratio  : sigma_pool / sigma_2024  (>1 => 2024 calmer than the pool the marginal draws on)

If ratio > 1 broadly, the marginal is wider than the realized error (confirms the fan is
the cause, not centering). If year_ratio explains most of ratio, it's a year effect; the
residual ratio/year_ratio is the forecast-bin pooling inflation.
"""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from run_wind_per_plant import run_one_day, load_wind  # noqa: E402

WIND_META = Path("/Users/val/Desktop/Princeton/PGscen-2nd/data/NYISO_real/"
                 "plant_metadata/wind_meta.csv")


def operating_dev_std(actual_df, forecast_df, site_id, year=None):
    """Std of (actual - forecast) over post-COD operating hours (optionally one year)."""
    if site_id not in actual_df.columns:
        return np.nan
    fc = (forecast_df[["Forecast_time", site_id]]
          .drop_duplicates("Forecast_time", keep="last")
          .set_index("Forecast_time")[site_id])
    a = actual_df[site_id]
    common = a.index.intersection(fc.index)
    av, f = a.loc[common].values, fc.loc[common].values
    operating = ~((np.abs(f) < 1e-9) & (np.abs(av) < 1e-9))
    idx = common[operating]
    if year is not None:
        idx = idx[idx.year == year]
    if len(idx) < 50:
        return np.nan
    return float(np.std((a.loc[idx].values - fc.loc[idx].values)))


def main():
    days = [d.strftime("%Y-%m-%d")
            for d in pd.date_range("2024-01-03", "2024-12-25", freq="7D")]
    meta = pd.read_csv(WIND_META).set_index("site_id")
    zone_of, name_of, oy_of = (meta["zone"].to_dict(), meta["site_name"].to_dict(),
                               meta["operating_year"].to_dict())

    print("pre-loading ...")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = load_wind()
    actual_df, forecast_df, _ = pre

    acc = {}   # site_id -> dict of accumulators
    t0 = time.time()
    for i, day in enumerate(days):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = run_one_day(day, nscen=1000, asset_rho=0.5, preloaded=pre,
                              seed=i, verbose=False, restrict_precod=True)
        mw, act, fc, online = (res["mw_all"], res["actual_today"],
                               res["forecast_today"], res["online"])
        for ai, a in enumerate(res["assets"]):
            if not online[ai]:
                continue
            d = acc.setdefault(a, {"std": [], "se": [], "n": 0})
            for h in range(24):
                y = act[ai, h]
                if not np.isfinite(y):
                    continue
                col = mw[:, ai, h]
                d["std"].append(col.std())
                d["se"].append((y - np.median(col)) ** 2)
                d["n"] += 1
        if (i + 1) % 10 == 0 or i == len(days) - 1:
            print(f"  [{i+1}/{len(days)}]  ({(time.time()-t0)/60:.1f}m)")

    rows = []
    for a, d in acc.items():
        if d["n"] < 100:
            continue
        sigma_scen = float(np.mean(d["std"]))
        skill = float(np.sqrt(np.mean(d["se"])))
        sigma_pool = operating_dev_std(actual_df, forecast_df, a)
        sigma_2024 = operating_dev_std(actual_df, forecast_df, a, year=2024)
        rows.append({
            "zone": zone_of.get(a), "name": str(name_of.get(a))[:24],
            "COD": oy_of.get(a), "n": d["n"],
            "sigma_scen": sigma_scen, "skill": skill,
            "ratio": sigma_scen / skill if skill else np.nan,
            "sigma_pool": sigma_pool, "sigma_2024": sigma_2024,
            "year_ratio": sigma_pool / sigma_2024 if sigma_2024 else np.nan,
        })
    df = pd.DataFrame(rows).sort_values(["zone", "name"])
    out = THIS_DIR / "outputs" / "diagnose" / "spread_skill.csv"
    df.to_csv(out, index=False)

    show = df.copy()
    for c in ["sigma_scen", "skill", "ratio", "sigma_pool", "sigma_2024", "year_ratio"]:
        show[c] = show[c].round(3)
    print("\n=== per-plant spread-skill (sampled fan std vs realized error) ===")
    print(show[["zone", "name", "COD", "sigma_scen", "skill", "ratio",
                "sigma_pool", "sigma_2024", "year_ratio"]].to_string(index=False))
    print("\n=== summary (means over plants) ===")
    print(f"  spread/skill ratio : mean {df['ratio'].mean():.3f}  "
          f"median {df['ratio'].median():.3f}  (#>1: {(df['ratio']>1).sum()}/{len(df)})")
    print(f"  year_ratio (pool/2024): mean {df['year_ratio'].mean():.3f}  "
          f"median {df['year_ratio'].median():.3f}  (#>1: {(df['year_ratio']>1).sum()}/{len(df)})")
    print(f"  binning residual (ratio/year_ratio): mean "
          f"{(df['ratio']/df['year_ratio']).mean():.3f}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
