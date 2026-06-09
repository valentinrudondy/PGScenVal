"""Multi-day per-plant calibration of the per-plant wind scenarios.

This is the calibration the per-plant wind path never had (it was only ever
physics-validated on fleet sums). Mirrors
`stage_b_conditional_loads/multi_day_calibration.py` but per PLANT instead of per
zone. For each held-out UTC scenario day in a sweep we run `run_one_day` and, per
(plant, hour) with the plant online and the actual finite, record:

  - in_50 / in_80 / in_90 : actual within p25-p75 / p10-p90 / p05-p95 (targets .50/.80/.90)
  - pit                   : rank of actual among the nscen scenarios in (0,1); calibrated -> uniform
  - crps                  : continuous ranked probability score (kernel form, lower better)
  - bias                  : actual - p50  (signed MW)

Aggregated per plant and per zone. A fleet-sum coverage line is also reported.

IMPORTANT — what this proves (see ../../Per_Plant_Wind_Plan.md s9). The "actual"
here is the v4 modeled potential the engine was fit on, so PIT/coverage measure
GEMINI's SELF-CONSISTENCY (does the residual model reproduce the per-plant deviation
distribution), NOT real-world interval coverage — there is no hourly per-plant
metered truth for ~28/31 plants. Real external checks live elsewhere (fleet-sum vs
rtfuelmix; the 2 single-plant LPI groups). Read these numbers accordingly.

Default sweep: every 7 days in 2024 (~52 UTC days), seed 0.
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from run_wind_per_plant import run_one_day, load_wind  # noqa: E402
from short_history_reg import build_factors, widen  # noqa: E402

WIND_META = Path("/Users/val/Desktop/Princeton/PGscen-2nd/data/NYISO_real/"
                 "plant_metadata/wind_meta.csv")


def crps_kernel(scenarios: np.ndarray, y: float) -> float:
    """CRPS = E|X - y| - 0.5 E|X - X'|, kernel form over the nscen ensemble."""
    if not np.isfinite(y):
        return np.nan
    s = np.asarray(scenarios, dtype=float)
    t1 = np.abs(s - y).mean()
    t2 = 0.5 * np.abs(s[:, None] - s[None, :]).mean()
    return float(t1 - t2)


def pit_value(scenarios: np.ndarray, y: float) -> float:
    """PIT: mid-rank of y among the ensemble in (0,1). Calibrated -> uniform."""
    if not np.isfinite(y):
        return np.nan
    s = np.asarray(scenarios, dtype=float)
    n = len(s)
    return float((np.sum(s < y) + 0.5 * np.sum(s == y)) / n)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2024-01-03", help="first UTC scenario day")
    p.add_argument("--end", default="2024-12-25", help="last UTC scenario day")
    p.add_argument("--step-days", type=int, default=7)
    p.add_argument("--years", type=int, nargs="+",
                   default=[2018, 2019, 2020, 2021, 2022, 2023, 2024])
    p.add_argument("--nscen", type=int, default=1000)
    p.add_argument("--asset-rho", type=float, default=0.5)
    p.add_argument("--time-rho", type=float, default=0.05)
    p.add_argument("--nearest-days", type=int, default=None)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--short-history-reg", action="store_true",
                   help="widen young-plant (<=2yr) marginals to the mature-fleet "
                        "spread (short_history_reg.py).")
    p.add_argument("--out-dir", default=str(THIS_DIR / "outputs" / "calibration"))
    args = p.parse_args()

    days = [d.strftime("%Y-%m-%d")
            for d in pd.date_range(args.start, args.end, freq=f"{args.step_days}D")]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # plant -> (zone, name, capacity) for grouping
    meta = pd.read_csv(WIND_META).set_index("site_id")
    zone_of = meta["zone"].to_dict()
    name_of = meta["site_name"].to_dict()

    print("=== Per-plant wind multi-day calibration ===")
    print(f"days: {len(days)} ({days[0]} -> {days[-1]}, every {args.step_days}d, UTC)")
    print(f"nscen={args.nscen}, training years={args.years}, "
          f"rho=(asset {args.asset_rho} geographic, time {args.time_rho}), "
          f"nearest_days={args.nearest_days}")

    print("\npre-loading wind data once ...")
    t0 = time.time()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = load_wind(years=args.years)
    print(f"  actuals {pre[0].shape}, {len(pre[2])} plants ({time.time()-t0:.1f}s)")

    factors = None
    if args.short_history_reg:
        factors, fdiag = build_factors(pre, args.start, verbose=True)
        print(f"  short-history regularizer ON: widening {len(factors)} young plants")
        fdiag.to_csv(out_dir / "short_history_factors.csv", index=False)

    rng_seed = args.seed
    all_rows: list[dict] = []
    fleet_rows: list[dict] = []
    t_loop = time.time()
    for i, day in enumerate(days):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = run_one_day(
                    scen_day=day, nscen=args.nscen,
                    asset_rho=args.asset_rho, time_rho=args.time_rho,
                    nearest_days=args.nearest_days, preloaded=pre,
                    seed=rng_seed + i, verbose=False)
                if factors:
                    widen(res, factors)
        except Exception as e:
            print(f"  [{i+1}/{len(days)}] {day}: FAILED {type(e).__name__}: {e}")
            continue

        mw = res["mw_all"]            # (nscen, n_asset, 24)
        act = res["actual_today"]     # (n_asset, 24), NaN where offline
        fc = res["forecast_today"]    # (n_asset, 24)
        assets = res["assets"]
        caps = res["capacity"]

        for ai, a in enumerate(assets):
            if not res["online"][ai]:
                continue
            for h in range(24):
                y = act[ai, h]
                if not np.isfinite(y):
                    continue
                col = mw[:, ai, h]
                p05, p10, p25, p50, p75, p90, p95 = np.quantile(
                    col, [.05, .10, .25, .50, .75, .90, .95])
                all_rows.append({
                    "day": day, "site_id": a, "zone": zone_of.get(a, "?"),
                    "hour_utc": h, "cap_mw": float(caps[ai]),
                    "actual_mw": float(y), "forecast_mw": float(fc[ai, h]),
                    "p50": float(p50), "std": float(col.std()),
                    "in_50": float(p25 <= y <= p75),
                    "in_80": float(p10 <= y <= p90),
                    "in_90": float(p05 <= y <= p95),
                    "pit": pit_value(col, y),
                    "crps": crps_kernel(col, y),
                    "bias": float(y) - float(p50),
                })

        # fleet sum over online plants (real-ish aggregate coverage)
        on = res["online"]
        fleet = mw[:, on, :].sum(axis=1)                  # (nscen, 24)
        fleet_act = np.nansum(act[on], axis=0)            # (24,)
        for h in range(24):
            col = fleet[:, h]
            p10, p50, p90, p05, p95 = np.quantile(col, [.10, .50, .90, .05, .95])
            fleet_rows.append({
                "day": day, "hour_utc": h,
                "actual_mw": float(fleet_act[h]),
                "in_80": float(p10 <= fleet_act[h] <= p90),
                "in_90": float(p05 <= fleet_act[h] <= p95),
                "pit": pit_value(col, fleet_act[h]),
                "crps": crps_kernel(col, fleet_act[h]),
                "bias": float(fleet_act[h]) - float(p50),
            })

        if (i + 1) % 5 == 0 or i == len(days) - 1:
            el = time.time() - t_loop
            eta = el / (i + 1) * (len(days) - i - 1)
            print(f"  [{i+1}/{len(days)}] {day}  ({el/60:.1f}m, eta {eta/60:.1f}m)")

    df = pd.DataFrame(all_rows)
    df.to_csv(out_dir / "per_day_per_plant_per_hour.csv", index=False)
    fl = pd.DataFrame(fleet_rows)
    fl.to_csv(out_dir / "fleet_per_day_per_hour.csv", index=False)

    # --- per-plant aggregate
    agg = (df.groupby(["zone", "site_id"])
           .agg(n_obs=("actual_mw", "size"),
                cap_mw=("cap_mw", "first"),
                cov_50=("in_50", "mean"), cov_80=("in_80", "mean"),
                cov_90=("in_90", "mean"),
                mean_crps=("crps", "mean"), mean_bias=("bias", "mean"),
                mean_actual=("actual_mw", "mean"))
           .reset_index().sort_values(["zone", "site_id"]))
    agg["crps_pct_cap"] = 100 * agg["mean_crps"] / agg["cap_mw"]
    agg["name"] = agg["site_id"].map(name_of)
    agg.to_csv(out_dir / "per_plant_summary.csv", index=False)

    # --- per-zone aggregate (pool plant-hours within zone)
    zagg = (df.groupby("zone")
            .agg(n_obs=("actual_mw", "size"),
                 cov_50=("in_50", "mean"), cov_80=("in_80", "mean"),
                 cov_90=("in_90", "mean"),
                 mean_crps=("crps", "mean"), mean_bias=("bias", "mean"))
            .reset_index())
    zagg.to_csv(out_dir / "per_zone_summary.csv", index=False)

    print("\n=== per-plant calibration (online plant-hours, 2024) ===")
    show = agg[["zone", "name", "n_obs", "cov_50", "cov_80", "cov_90",
                "mean_bias", "crps_pct_cap"]].copy()
    show["name"] = show["name"].str.slice(0, 26)
    print(show.round(3).to_string(index=False))
    print("\n=== per-zone ===")
    print(zagg.round(3).to_string(index=False))
    print(f"\n=== FLEET-sum coverage ===  cov_80={fl['in_80'].mean():.3f}  "
          f"cov_90={fl['in_90'].mean():.3f}  mean_bias={fl['bias'].mean():.0f} MW")
    print("Targets: cov_50=.50 cov_80=.80 cov_90=.90 (lower = under-dispersed)")
    print(f"\nwrote {out_dir}")


if __name__ == "__main__":
    main()
