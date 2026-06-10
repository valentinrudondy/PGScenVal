"""Single-stage 11-zone NYISO load scenario generation (production).

The production NYISO load model: fit ONE GeminiEngine over all 11 load zones and
draw scenarios DIRECTLY (the natural PGScen usage). Load is modelled on its own
-- independent of wind/solar/BTM -- because their cross-group forecast-error
correlation is ~0 (partial corr 0.004; the three_way_dependency_graph diagnostic
puts wind and solar in their own glasso components). What matters is the strong
load<->load cross-zone correlation (empirical |corr| ~0.30, all 11 zones one
component), and that lives directly in the engine's asset_cov.

A two-stage joint-load+wind approach (Stage A + Stage B conditional) was tried
and abandoned once that no-correlation result was in: it was calibration-
equivalent (52 held-out 2024 days: per-zone cov_80 0.765 vs 0.767, fleet 0.797
vs 0.795 -- identical within noise) but ~3.6x slower and far more complex (two
fits, a conditional sampler, a marginal-inconsistency caveat). See Claude_load.md
for the full record.

asset_rho=0.002 is optimal for the 11-zone load-only fit (per-zone cov is
rho-insensitive; fleet cov is best at the lowest rho); horizon_rho=0.05;
in_sample=False (leakage-safe: history strictly before the scenario start).
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .engine import GeminiEngine
from .utils.data_utils import (
    load_ny_real_load_data,
    split_actuals_hist_future,
    split_forecasts_hist_future,
)

ET = "US/Eastern"
NYISO_DA_ISSUE_HOUR_UTC = 18                  # NYISO DA forecast issued 18Z prev day
ALL_ZONES = list("ABCDEFGHIJK")               # the 11 NYISO load zones
LOAD_PREFIX = "LOAD_"


def issue_time_for_scen_day(scen_day) -> pd.Timestamp:
    """Issue_time = 18:00 UTC on the day before the ET scenario day (NYISO DA conv)."""
    et_midnight = pd.Timestamp(scen_day).tz_localize(ET).normalize()
    prev_et_date = (et_midnight - pd.Timedelta(days=1)).date()
    return pd.Timestamp(f"{prev_et_date} {NYISO_DA_ISSUE_HOUR_UTC:02d}:00:00", tz="UTC")


def run_load_one_day(scen_day, nscen: int = 1000, asset_rho: float = 0.002,
                     horizon_rho: float = 0.05, preloaded=None, seed=None):
    """Fit the 11-zone load engine for one ET scenario day and draw all zones.

    Parameters
    ----------
    scen_day : str | pd.Timestamp
        Eastern calendar date (YYYY-MM-DD). Scenarios cover its 24 ET hours.
    preloaded : (actual_df, forecast_df) from ``load_ny_real_load_data()``, to
        avoid re-reading the CSVs in a multi-day loop.

    Returns
    -------
    (engine, actual_future, scen_timesteps, scen_start_utc)
        Ready for ``engine.write_to_csv(out_dir, actual_future, write_forecasts=True)``
        which emits per-zone scenario CSVs under ``<out_dir>/<YYYYMMDD>/load/``.
        ``engine.scenarios['load']`` holds the (nscen, 11x24) draws.
    """
    if preloaded is None:
        actual_df, forecast_df = load_ny_real_load_data()
    else:
        actual_df, forecast_df = preloaded

    et_midnight = pd.Timestamp(scen_day).tz_localize(ET).normalize()
    scen_start_utc = et_midnight.tz_convert("UTC")
    issue_utc = issue_time_for_scen_day(scen_day)
    lead_h = int((scen_start_utc - issue_utc).total_seconds() // 3600)
    scen_timesteps = pd.date_range(
        scen_start_utc, scen_start_utc + pd.Timedelta(hours=23), freq="h").tolist()

    # leakage-safe: history strictly before the scenario start
    actual_hist, actual_future = split_actuals_hist_future(
        actual_df, scen_timesteps, in_sample=False)
    fc_hist, fc_future = split_forecasts_hist_future(
        forecast_df, scen_timesteps, in_sample=False)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        engine = GeminiEngine(
            hist_actual_df=actual_hist, hist_forecast_df=fc_hist,
            scen_start_time=scen_start_utc, meta_df=None, asset_type="load",
            forecast_resolution_in_minute=60, num_of_horizons=24,
            forecast_lead_time_in_hour=lead_h,
        )
        engine.fit(asset_rho=asset_rho, horizon_rho=horizon_rho, nearest_days=None)
        # Seed AFTER the fit, immediately before the draw, so fit's random-state
        # consumption doesn't shift the scenario draw (matches run_one_day_single).
        if seed is not None:
            np.random.seed(seed)
        engine.create_scenario(nscen=nscen, forecast_df=fc_future)

    return engine, actual_future, scen_timesteps, scen_start_utc
