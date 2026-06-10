"""Tune (asset_rho, time_rho) for per-plant wind via held-out energy score.

Held-out energy-score rho tuning for the per-plant wind fit. The energy score (proper,
multivariate CRPS generalization) is computed on the ONLINE-plant x 24-hour vector,
standardized per coordinate by its historical hour-of-day std so every plant-hour
contributes equally. `asset_rho` is the BASE scalar that run_one_day rescales to the
fleet geography (2 * asset_rho * dist / dist.max()); we tune that base + time_rho.

    ES(F, y) = E_X ||X - y||  -  0.5 E_{X,X'} ||X - X'||   (standardized coords)

Run (after the calibration sweep):
    python tune_rho.py
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


def energy_score(scenarios: np.ndarray, obs: np.ndarray, stds: np.ndarray) -> float:
    S = scenarios / stds
    y = obs / stds
    N = S.shape[0]
    t1 = np.linalg.norm(S - y[None, :], axis=1).mean()
    chunk, pair_sum, pair_count = 200, 0.0, 0
    for i in range(0, N, chunk):
        block = S[i:i+chunk]
        d = np.linalg.norm(block[:, None, :] - S[None, :, :], axis=2)
        pair_sum += d.sum(); pair_count += d.size
    return float(t1 - 0.5 * pair_sum / pair_count)


def hour_of_day_stds(actual_df: pd.DataFrame) -> pd.DataFrame:
    """(asset x 24) std table: std of each plant's output by UTC hour-of-day."""
    hours = actual_df.index.hour
    out = {}
    for a in actual_df.columns:
        s = pd.Series(actual_df[a].values).groupby(hours).std(ddof=1)
        out[a] = s.reindex(range(24)).fillna(1.0).values
    tab = pd.DataFrame(out).T            # rows=asset, cols=hour
    tab[tab < 1e-6] = 1.0
    return tab


def score_day(day, asset_rho, time_rho, nscen, nearest_days, pre, std_tab) -> dict:
    t0 = time.time()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = run_one_day(day, nscen=nscen, asset_rho=asset_rho,
                              time_rho=time_rho, nearest_days=nearest_days,
                              preloaded=pre, seed=0, verbose=False)
    except Exception as e:
        return {"day": day, "asset_rho": asset_rho, "time_rho": time_rho,
                "es": np.nan, "note": f"fail:{type(e).__name__}",
                "elapsed_s": time.time()-t0}

    assets = res["assets"]
    act = res["actual_today"]
    mw = res["mw_all"]
    # online plants with a complete finite actual day
    idx = [ai for ai in range(len(assets))
           if res["online"][ai] and np.isfinite(act[ai]).all()]
    if not idx:
        return {"day": day, "asset_rho": asset_rho, "time_rho": time_rho,
                "es": np.nan, "note": "no_online", "elapsed_s": time.time()-t0}

    obs = act[idx].reshape(-1)                       # (n_on*24,)
    scen = mw[:, idx, :].reshape(mw.shape[0], -1)    # (nscen, n_on*24)
    stds = std_tab.loc[[assets[ai] for ai in idx]].values.reshape(-1)
    es = energy_score(scen, obs, stds)
    return {"day": day, "asset_rho": asset_rho, "time_rho": time_rho,
            "es": es, "note": "", "elapsed_s": time.time()-t0,
            "n_online": len(idx)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", nargs="+",
                   default=["2024-01-15", "2024-04-15", "2024-07-15", "2024-10-15"])
    p.add_argument("--asset-rhos", nargs="+", type=float, default=[0.01, 0.05, 0.2])
    p.add_argument("--time-rhos", nargs="+", type=float, default=[0.01, 0.05, 0.2])
    p.add_argument("--years", nargs="+", type=int,
                   default=[2018, 2019, 2020, 2021, 2022, 2023, 2024])
    p.add_argument("--nscen", type=int, default=500)
    p.add_argument("--nearest-days", type=int, default=None)
    p.add_argument("--out-dir", default=str(THIS_DIR / "outputs" / "tune_rho"))
    args = p.parse_args()

    print("=== Per-plant wind: tune (asset_rho, time_rho) via energy score ===")
    print(f"days: {args.days}")
    print(f"asset_rhos: {args.asset_rhos}   time_rhos: {args.time_rhos}")
    print(f"nscen={args.nscen}, nearest_days={args.nearest_days}")

    print("\npre-loading + computing hour-of-day stds ...")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = load_wind(years=args.years)
    std_tab = hour_of_day_stds(pre[0])

    n_cells = len(args.days) * len(args.asset_rhos) * len(args.time_rhos)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    rows, done, t0 = [], 0, time.time()
    for day in args.days:
        for ar in args.asset_rhos:
            for tr in args.time_rhos:
                r = score_day(day, ar, tr, args.nscen, args.nearest_days,
                              pre, std_tab)
                rows.append(r); done += 1
                if done % 5 == 0 or done == n_cells:
                    el = time.time() - t0
                    print(f"  [{done}/{n_cells}] day={day} ar={ar} tr={tr} "
                          f"es={r['es']:.4f} ({el/60:.1f}m, "
                          f"eta {el/done*(n_cells-done)/60:.1f}m)")

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "tune_results.csv", index=False)
    heat = (df.dropna(subset=["es"]).groupby(["asset_rho", "time_rho"])["es"]
            .mean().unstack("time_rho"))
    heat.to_csv(out_dir / "tune_heatmap.csv")
    best = heat.stack().idxmin(); best_es = heat.stack().min()
    msg = (f"=== per-plant wind tuning ===\n"
           f"BEST asset_rho={best[0]} time_rho={best[1]} mean_ES={best_es:.4f}\n\n"
           f"Mean ES heatmap (rows asset_rho, cols time_rho; lower=better):\n"
           f"{heat.round(4)}\n")
    (out_dir / "tune_best.txt").write_text(msg)
    print("\n" + msg + f"wrote {out_dir}")


if __name__ == "__main__":
    main()
