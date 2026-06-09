"""Parity check: the production short-history regularizer (pgscen.short_history)
reproduces the validated experiments prototype (short_history_reg.py).

Two things are asserted on one held-out day:
  1. build_factors agree (same young-plant set, same factors) given the same
     history -- the factor math is byte-identical across the two copies.
  2. widen_engine_scenarios (DataFrame, production) reproduces widen (tensor,
     experiments) on engine.scenarios -- the two appliers give the same MW.

Run:
    python check_short_history_parity.py --scen-day 2024-07-15
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from run_wind_per_plant import run_one_day, load_wind  # noqa: E402
import short_history_reg as exp  # noqa: E402
from pgscen.short_history import (  # noqa: E402
    build_factors as prod_build_factors,
    widen_engine_scenarios,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scen-day", default="2024-07-15")
    p.add_argument("--nscen", type=int, default=300)
    args = p.parse_args()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = load_wind()

    # history strictly before the scenario start (same split run_one_day uses)
    import pandas as pd
    scen_start = pd.Timestamp(args.scen_day).tz_localize("UTC")
    from pgscen.utils.data_utils import (split_actuals_hist_future,
                                         split_forecasts_hist_future)
    scen_ts = pd.date_range(scen_start, periods=24, freq="h", tz="UTC")
    a_hist, _ = split_actuals_hist_future(pre[0], scen_ts, in_sample=False)
    f_hist, _ = split_forecasts_hist_future(pre[1], scen_ts, in_sample=False)

    # 1. factor parity --------------------------------------------------------
    exp_factors, _ = exp.build_factors((a_hist, f_hist, pre[2]), args.scen_day)
    prod_factors, _ = prod_build_factors(a_hist, f_hist, scen_start.year)
    assert set(exp_factors) == set(prod_factors), (
        f"young set differs: {set(exp_factors) ^ set(prod_factors)}")
    for k in exp_factors:
        assert abs(exp_factors[k] - prod_factors[k]) < 1e-9, (
            f"factor {k}: exp {exp_factors[k]} vs prod {prod_factors[k]}")
    print(f"[1] factor parity OK: {len(exp_factors)} young plants, "
          f"max |delta| = "
          f"{max(abs(exp_factors[k]-prod_factors[k]) for k in exp_factors):.2e}")

    # 2. applier parity -------------------------------------------------------
    # experiments path: run_one_day -> tensor, widen() in place
    res = run_one_day(args.scen_day, nscen=args.nscen, preloaded=pre,
                      seed=0, verbose=False)
    eng = res["engine"]
    scen_ts = res["scen_timesteps"]
    assets = res["assets"]
    # reconstruct forecast_future the engine saw (re-split, same as run_one_day)
    _, f_future = split_forecasts_hist_future(pre[1], pd.DatetimeIndex(scen_ts),
                                              in_sample=False)

    # production applier on a copy of engine.scenarios
    base = eng.scenarios["wind"].copy()
    widen_engine_scenarios(eng, f_future, scen_ts, prod_factors)
    prod_mw = np.stack([eng.scenarios["wind"][a].loc[:, list(scen_ts)].values
                        for a in assets], axis=1)   # (nscen, n_asset, 24)

    # experiments applier on the tensor
    exp.widen(res, exp_factors)
    exp_mw = res["mw_all"]

    max_abs = float(np.nanmax(np.abs(prod_mw - exp_mw)))
    print(f"[2] applier parity: max |prod_mw - exp_mw| = {max_abs:.4e} MW "
          f"over {prod_mw.size:,} values")
    assert max_abs < 1e-6, "production widener diverges from experiments widener"
    print("\nPARITY OK -- production regularizer matches the validated prototype.")


if __name__ == "__main__":
    main()
