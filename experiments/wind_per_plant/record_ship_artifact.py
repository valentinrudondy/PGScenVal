"""Record the SHIP-CONFIG coverage artifact from the PRODUCTION code path.

calibration.py applies the experiments-prototype widener (short_history_reg.py, on
the result tensor). THIS script instead routes every day through the PRODUCTION
regularizer module `pgscen.short_history` (build_factors + widen_engine_scenarios,
operating on engine.scenarios['wind']) -- the exact code `10_run_pgscen_wind.py`
runs -- with per-day history-derived factors, then scores per-plant / per-zone /
fleet coverage. The fit itself is identical to the runner's (geographic
asset_rho=0.5, time_rho=0.05, in_sample=False, lead 18h).

Output is the ship artifact: coverage produced by production code at production
settings, tied to a commit (recorded in ship_config.json). Parity with the
prototype is independently guaranteed by check_short_history_parity.py, so these
should match RESULTS.md; the point is provenance, not a new number.

Run:
    python record_ship_artifact.py --nscen 1000
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from run_wind_per_plant import run_one_day, load_wind  # noqa: E402
from calibration import crps_kernel, pit_value  # noqa: E402
from pgscen.short_history import (  # noqa: E402
    build_factors as prod_build_factors,
    widen_engine_scenarios,
)
from pgscen.utils.data_utils import (  # noqa: E402
    split_actuals_hist_future, split_forecasts_hist_future)

WIND_META = Path("/Users/val/Desktop/Princeton/PGscen-2nd/data/NYISO_real/"
                 "plant_metadata/wind_meta.csv")


def _git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(THIS_DIR),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2024-01-03")
    p.add_argument("--end", default="2024-12-25")
    p.add_argument("--step-days", type=int, default=7)
    p.add_argument("--nscen", type=int, default=1000)
    p.add_argument("--asset-rho", type=float, default=0.5)
    p.add_argument("--time-rho", type=float, default=0.05)
    p.add_argument("--years", type=int, nargs="+",
                   default=[2018, 2019, 2020, 2021, 2022, 2023, 2024])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", default=str(THIS_DIR / "outputs" / "ship_artifact"))
    args = p.parse_args()

    days = [d.strftime("%Y-%m-%d")
            for d in pd.date_range(args.start, args.end, freq=f"{args.step_days}D")]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = pd.read_csv(WIND_META).set_index("site_id")
    zone_of, name_of = meta["zone"].to_dict(), meta["site_name"].to_dict()

    print("=== SHIP-CONFIG coverage artifact (PRODUCTION path) ===")
    print(f"days: {len(days)} ({days[0]} -> {days[-1]}, every {args.step_days}d)")
    print(f"asset_rho={args.asset_rho} (geographic), time_rho={args.time_rho}, "
          f"short-history reg via pgscen.short_history, in_sample=False, nscen={args.nscen}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = load_wind(years=args.years)
    actual_df, forecast_df, _ = pre

    all_rows, fleet_rows = [], []
    t_loop = time.time()
    for i, day in enumerate(days):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = run_one_day(day, nscen=args.nscen, asset_rho=args.asset_rho,
                                  time_rho=args.time_rho, preloaded=pre,
                                  seed=args.seed + i, verbose=False)
                # --- PRODUCTION regularizer path (per-day history factors) ---
                scen_ts = pd.DatetimeIndex(res["scen_timesteps"])
                a_hist, _ = split_actuals_hist_future(actual_df, scen_ts,
                                                      in_sample=False)
                f_hist, f_future = split_forecasts_hist_future(forecast_df, scen_ts,
                                                               in_sample=False)
                factors, _ = prod_build_factors(a_hist, f_hist,
                                                pd.Timestamp(day).year)
                widen_engine_scenarios(res["engine"], f_future,
                                       res["scen_timesteps"], factors)
                # re-extract the widened tensor from engine.scenarios
                eng_scen = res["engine"].scenarios["wind"]
                assets = res["assets"]
                mw = np.stack([eng_scen[a].loc[:, res["scen_timesteps"]].values
                               for a in assets], axis=1)   # (nscen, n_asset, 24)
        except Exception as e:
            print(f"  [{i+1}/{len(days)}] {day}: FAILED {type(e).__name__}: {e}")
            continue

        act, fc = res["actual_today"], res["forecast_today"]
        caps, online = res["capacity"], res["online"]
        for ai, a in enumerate(assets):
            if not online[ai]:
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
                    "actual_mw": float(y), "p50": float(p50),
                    "in_50": float(p25 <= y <= p75), "in_80": float(p10 <= y <= p90),
                    "in_90": float(p05 <= y <= p95),
                    "pit": pit_value(col, y), "crps": crps_kernel(col, y),
                    "bias": float(y) - float(p50)})

        on = online
        fleet = mw[:, on, :].sum(axis=1)
        fleet_act = np.nansum(act[on], axis=0)
        for h in range(24):
            col = fleet[:, h]
            p10, p50, p90, p05, p95 = np.quantile(col, [.10, .50, .90, .05, .95])
            fleet_rows.append({
                "day": day, "hour_utc": h, "actual_mw": float(fleet_act[h]),
                "in_80": float(p10 <= fleet_act[h] <= p90),
                "in_90": float(p05 <= fleet_act[h] <= p95),
                "pit": pit_value(col, fleet_act[h]), "bias": float(fleet_act[h]) - float(p50)})

        if (i + 1) % 10 == 0 or i == len(days) - 1:
            el = time.time() - t_loop
            print(f"  [{i+1}/{len(days)}] {day}  ({el/60:.1f}m, "
                  f"eta {el/(i+1)*(len(days)-i-1)/60:.1f}m)")

    df = pd.DataFrame(all_rows)
    fl = pd.DataFrame(fleet_rows)
    df.to_csv(out_dir / "per_day_per_plant_per_hour.csv", index=False)
    fl.to_csv(out_dir / "fleet_per_day_per_hour.csv", index=False)

    agg = (df.groupby(["zone", "site_id"])
           .agg(n_obs=("actual_mw", "size"), cap_mw=("cap_mw", "first"),
                cov_50=("in_50", "mean"), cov_80=("in_80", "mean"),
                cov_90=("in_90", "mean"), mean_crps=("crps", "mean"),
                mean_bias=("bias", "mean")).reset_index().sort_values(["zone", "site_id"]))
    agg["crps_pct_cap"] = 100 * agg["mean_crps"] / agg["cap_mw"]
    agg["name"] = agg["site_id"].map(name_of)
    agg.to_csv(out_dir / "per_plant_summary.csv", index=False)
    zagg = (df.groupby("zone").agg(
        n_obs=("actual_mw", "size"), cov_50=("in_50", "mean"),
        cov_80=("in_80", "mean"), cov_90=("in_90", "mean"),
        mean_bias=("bias", "mean")).reset_index())
    zagg.to_csv(out_dir / "per_zone_summary.csv", index=False)

    cfg = {"commit": _git_commit(), "asset_rho": args.asset_rho,
           "time_rho": args.time_rho, "short_history_reg": True,
           "regularizer_module": "pgscen.short_history", "in_sample": False,
           "nscen": args.nscen, "days": len(days), "stride_days": args.step_days,
           "fleet_cov_80": float(fl["in_80"].mean()),
           "fleet_cov_90": float(fl["in_90"].mean()),
           "fleet_mean_bias_mw": float(fl["bias"].mean())}
    (out_dir / "ship_config.json").write_text(json.dumps(cfg, indent=2))

    print("\n=== per-zone (production path) ===")
    print(zagg.round(3).to_string(index=False))
    print(f"\n=== FLEET ===  cov_80={cfg['fleet_cov_80']:.3f}  "
          f"cov_90={cfg['fleet_cov_90']:.3f}  bias={cfg['fleet_mean_bias_mw']:.0f} MW")
    print(f"commit {cfg['commit'][:10]}  ->  wrote {out_dir}")


if __name__ == "__main__":
    main()
