"""Per-plant wind scenario pipeline (the per-plant alternative to Stage A wind + Stage C).

Rationale and decision record: ../../Per_Plant_Wind_Plan.md. The grid optimizer
dispatches wind PER PLANT (per bus), so the end product is per-plant. Rather than
model zonal sums (Stage A) and disaggregate back to plants (Stage C, a lossy
plant->sum->plant round-trip), this models the ~31 NYISO wind plants DIRECTLY with
the existing `GeminiEngine(asset_type='wind')` path: per-plant ECDF marginals + a
geographic `asset_rho` (glasso penalty scaled by the pairwise lat/lon distance
matrix), which carries the inter-plant spatial coupling without ever aggregating.

This module promotes `scripts/10_run_pgscen_wind.py` (a CLI smoke script) into a
reusable `run_one_day()` callable, and fixes two things needed for honest work:

  1. LEAKAGE FIX. The smoke script split history with `in_sample=True`, i.e. it
     trained on every hour EXCEPT the 24 scenario hours — including data AFTER the
     scenario day. Held-out calibration requires `in_sample=False` (history strictly
     before the scenario start). This module uses False.

  2. PRELOAD PATH. Data is loaded once and threaded through `preloaded=` so a
     multi-day calibration sweep doesn't re-read the CSVs every day.

Day convention: UTC scenario days. `load_ny_real_wind_data` re-bases the forecast
`Issue_time` to `Forecast_time.normalize() - 18h`, i.e. the forecast is organized by
UTC day (24 hours share one issue time, lead = 18h from a UTC-midnight start). An ET
scenario day would straddle two UTC forecast buckets and break the 24-row block, so
we keep UTC days here. Aligning the wind day boundary to the load Stage A/B ET days
is a known integration follow-up (see the plan), not a calibration blocker.

Run:
    python run_wind_per_plant.py --scen-day 2024-07-15 --nscen 1000
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

PGSCEN_ROOT = Path("/Users/val/Desktop/Princeton/PGscen-2nd")
sys.path.insert(0, str(PGSCEN_ROOT))

from pgscen.engine import GeminiEngine  # noqa: E402
from pgscen.utils.data_utils import (  # noqa: E402
    load_ny_real_wind_data,
    split_actuals_hist_future,
    split_forecasts_hist_future,
)

# Forecast lead from a UTC-midnight scenario start back to the (normalized) 06Z
# issue time the loader stamps on every forecast row (= prev-day-midnight - 18h).
WIND_LEAD_HOURS = 18
DEFAULT_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]


def load_wind(years=None, variant="pluswind_v4", use_raw_forecast=False):
    """Load wind actuals/forecasts/meta and tz-localize the actuals index to UTC.

    Returned as a tuple suitable for `run_one_day(preloaded=...)`.
    """
    actual_df, forecast_df, meta_df = load_ny_real_wind_data(
        years=years, use_raw_forecast=use_raw_forecast, variant=variant)
    if actual_df.index.tz is None:
        actual_df.index = actual_df.index.tz_localize("UTC")
    return actual_df, forecast_df, meta_df


def run_one_day(scen_day, nscen=1000, asset_rho=0.5, time_rho=0.05,
                nearest_days=None, variant="pluswind_v4", use_raw_forecast=False,
                years=None, preloaded=None, seed=None, verbose=True,
                restrict_precod=True) -> dict:
    """Generate `nscen` day-ahead per-plant wind scenarios for one UTC scenario day.

    Parameters
    ----------
    scen_day : str | pd.Timestamp
        UTC calendar date (YYYY-MM-DD). Scenarios cover its 24 hours 00:00..23:00 UTC.
    asset_rho, time_rho : float
        Base glasso penalties. `asset_rho` is rescaled to the fleet geography as
        `2 * asset_rho * dist / dist.max()` (closer plants penalized less).
    nearest_days : int | None
        If given, restrict training to a +/- window of days around the scenario
        date in each year (seasonal restriction). None = use all history.
    preloaded : tuple | None
        (actual_df, forecast_df, meta_df) from `load_wind()`, to avoid re-loading.

    Returns
    -------
    dict with:
        mw_all         : (nscen, n_asset, 24) MW, asset-major in `assets` order
        fleet          : (nscen, 24) MW, sum across all modeled plants
        assets         : list[str] plant site_ids (engine.asset_list order)
        capacity       : (n_asset,) nameplate MW, `assets` order
        scen_timesteps : list of 24 UTC Timestamps
        forecast_today : (n_asset, 24) raw DA forecast MW, `assets` order
        actual_today   : (n_asset, 24) actual MW (NaN where plant offline), `assets` order
        online         : (n_asset,) bool — plant had nonzero forecast this day (post-COD)
        engine         : fitted GeminiEngine (for cov inspection)
        fit_time_s     : float
    """
    t0 = time.time()
    if seed is not None:
        np.random.seed(seed)

    if preloaded is None:
        actual_df, forecast_df, meta_df = load_wind(
            years=years if years is not None else DEFAULT_YEARS,
            variant=variant, use_raw_forecast=use_raw_forecast)
    else:
        actual_df, forecast_df, meta_df = preloaded

    # --- scenario-day timing (UTC day; lead 18h to the normalized issue time)
    scen_start = pd.Timestamp(scen_day).normalize()
    if scen_start.tz is None:
        scen_start = scen_start.tz_localize("UTC")
    scen_timesteps = pd.date_range(scen_start, periods=24, freq="h", tz="UTC")

    # --- leakage-safe split: history strictly before the scenario start
    actual_hist, actual_future = split_actuals_hist_future(
        actual_df, scen_timesteps, in_sample=False)
    forecast_hist, forecast_future = split_forecasts_hist_future(
        forecast_df, scen_timesteps, in_sample=False)

    # --- fit GEMINI (per-plant, geographic asset_rho) and generate scenarios
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        engine = GeminiEngine(
            actual_hist, forecast_hist, scen_timesteps[0],
            meta_df=meta_df, asset_type="wind",
            forecast_lead_time_in_hour=WIND_LEAD_HOURS,
        )
        dist = engine.asset_distance().values
        engine.fit(2 * asset_rho * dist / dist.max(), time_rho,
                   nearest_days=nearest_days)
        # Drop pre-commissioning history from the conditional marginals so a young
        # plant's pre-COD zeros don't collapse its low-forecast scenario fan to a
        # point mass at the forecast (pgscen.short_history). Must be between fit
        # and create_scenario.
        if restrict_precod:
            from pgscen.short_history import restrict_marginals_to_operating
            restrict_marginals_to_operating(engine)
        engine.create_scenario(nscen, forecast_future)

    assets = list(engine.asset_list)
    scen = engine.scenarios["wind"]  # MultiIndex columns (asset, timestamp)

    # --- assemble the (nscen, n_asset, 24) MW tensor
    mw_all = np.empty((nscen, len(assets), 24))
    for ai, a in enumerate(assets):
        mw_all[:, ai, :] = scen[a].loc[:, list(scen_timesteps)].values
    fleet = mw_all.sum(axis=1)

    # --- raw forecast / actual for the scenario day, `assets` order
    fc_block = forecast_future[
        forecast_future["Issue_time"] == engine.forecast_issue_time]
    fc_idx = (fc_block.drop(columns="Issue_time")
              .set_index("Forecast_time").reindex(scen_timesteps))
    forecast_today = fc_idx[assets].values.T                     # (n_asset, 24)

    act_idx = actual_future.reindex(scen_timesteps)
    actual_today = act_idx[assets].values.T.astype(float)        # (n_asset, 24)

    # online = plant has post-COD output this day (physics gates pre-COD to 0).
    online = forecast_today.sum(axis=1) > 0.0
    # mark offline plant-days as NaN in actuals so calibration skips them
    actual_today[~online, :] = np.nan

    capacity = engine.meta_df["Capacity"].reindex(assets).values

    if verbose:
        peak = np.nansum(actual_today, axis=0).max()
        print(f"  [{scen_start.date()}] {int(online.sum())}/{len(assets)} plants "
              f"online, fleet-peak-actual={peak:.0f} MW ({time.time()-t0:.1f}s)")

    return {
        "mw_all": mw_all,
        "fleet": fleet,
        "assets": assets,
        "capacity": capacity,
        "scen_timesteps": list(scen_timesteps),
        "forecast_today": forecast_today,
        "actual_today": actual_today,
        "online": online,
        "engine": engine,
        "fit_time_s": time.time() - t0,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scen-day", default="2024-07-15", help="UTC date YYYY-MM-DD.")
    p.add_argument("--nscen", type=int, default=1000)
    p.add_argument("--asset-rho", type=float, default=0.5,
                   help="cross-zone-corrected ship default (RESULTS.md s4); "
                        "0.05 was the old over-coupling default.")
    p.add_argument("--time-rho", type=float, default=0.05)
    p.add_argument("--nearest-days", type=int, default=None,
                   help="seasonal training window radius in days (default: all history).")
    p.add_argument("--years", type=int, nargs="+", default=DEFAULT_YEARS)
    p.add_argument("--variant", default="pluswind_v4")
    p.add_argument("--use-raw-forecast", action="store_true")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out-dir",
                   default=str(Path(__file__).resolve().parent / "outputs"))
    args = p.parse_args()

    print("=== Per-plant wind scenarios ===")
    print(f"scen-day (UTC): {args.scen_day}   nscen: {args.nscen}")
    print(f"rho: asset={args.asset_rho} (geographic), time={args.time_rho}   "
          f"nearest_days={args.nearest_days}")

    res = run_one_day(
        scen_day=args.scen_day, nscen=args.nscen,
        asset_rho=args.asset_rho, time_rho=args.time_rho,
        nearest_days=args.nearest_days, variant=args.variant,
        use_raw_forecast=args.use_raw_forecast, years=args.years,
        seed=args.seed, verbose=True,
    )

    assets = res["assets"]
    mw_all = res["mw_all"]
    scen_timesteps = res["scen_timesteps"]
    out_dir = Path(args.out_dir, f"wind_per_plant_{args.scen_day}")
    out_dir.mkdir(parents=True, exist_ok=True)

    labels = [t.strftime("%Y-%m-%d %H:%M") for t in scen_timesteps]
    rows = []
    for ai, a in enumerate(assets):
        for h, ts in enumerate(scen_timesteps):
            col = mw_all[:, ai, h]
            y = res["actual_today"][ai, h]
            rows.append({
                "site_id": a,
                "utc_time": labels[h],
                "online": bool(res["online"][ai]),
                "actual_mw": float(y) if np.isfinite(y) else np.nan,
                "forecast_mw": float(res["forecast_today"][ai, h]),
                "p10": float(np.quantile(col, 0.10)),
                "p50": float(np.quantile(col, 0.50)),
                "p90": float(np.quantile(col, 0.90)),
                "mean": float(col.mean()), "std": float(col.std()),
            })
    pd.DataFrame(rows).to_csv(out_dir / "summary_p10_p50_p90.csv", index=False)
    res["engine"].model.asset_cov.to_csv(out_dir / "asset_cov.csv")
    print(f"  {len(assets)} plants, fit {res['fit_time_s']:.1f}s -> wrote {out_dir}")


if __name__ == "__main__":
    main()
