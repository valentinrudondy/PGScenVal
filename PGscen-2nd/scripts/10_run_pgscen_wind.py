"""Run PGScen scenario generation on NYISO physics_v3 + MOS wind data.

Wires the validated `physics_v3` actuals + MOS forecasts (see
`docs/Forecast_Calibration_Methods.md`) into the `GeminiEngine` scenario
generator.

Usage
-----
Smoke test (1 day, 100 scenarios):
    python scripts/10_run_pgscen_wind.py 2024-07-15 1 --scenario-count 100

Production-style run (week, 1000 scenarios):
    python scripts/10_run_pgscen_wind.py 2024-07-15 7 --scenario-count 1000 \\
        -o outputs/wind_scenarios_2024Q3
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pgscen.engine import GeminiEngine
from pgscen.scoring import compute_energy_scores
from pgscen.utils.data_utils import (
    load_ny_real_wind_data,
    split_actuals_hist_future,
    split_forecasts_hist_future,
)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split('\n')[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('start', help='scenario start date, YYYY-MM-DD UTC')
    ap.add_argument('days', type=int, help='number of consecutive days')
    ap.add_argument('-o', '--out-dir', default='outputs/wind_scenarios',
                    help='where to save scenarios')
    ap.add_argument('-n', '--scenario-count', type=int, default=1000)
    # asset_rho=0.5 is the cross-zone-corrected default (per-plant ship config,
    # Per_Plant_Wind_Plan.md / experiments/wind_per_plant/RESULTS.md s4): the
    # geographic kernel at the old 0.05 over-coupled distant zones ~10x.
    ap.add_argument('--asset-rho', type=float, default=0.5)
    ap.add_argument('--time-rho', type=float, default=0.05)
    ap.add_argument('--short-history-reg', action=argparse.BooleanOptionalAction,
                    default=True,
                    help='widen 2023-24 young-plant marginals to the mature-fleet '
                         'spread (pgscen.short_history; on by default). '
                         '--no-short-history-reg to disable.')
    ap.add_argument('--years', type=int, nargs='+',
                    default=[2019, 2020, 2021, 2022, 2023, 2024],
                    help='years to load actuals + forecasts from')
    ap.add_argument('--use-raw-forecast', action='store_true',
                    help='use raw (pre-MOS) forecasts; default is MOS')
    ap.add_argument('--variant', default='pluswind_v4',
                    help='physics variant suffix (default: pluswind_v4; '
                         'multi-cell A + clip-0.25 hub-shear, frozen 2026-06-03)')
    ap.add_argument('--random-seed', type=int, default=None)
    ap.add_argument('--score', action='store_true',
                    help='compute energy scores per day and write summary CSV')
    args = ap.parse_args()

    if args.random_seed is not None:
        np.random.seed(args.random_seed)

    # ------------------------------------------------------------------
    # 1. Load actuals + DA forecasts + plant metadata.
    # ------------------------------------------------------------------
    log.info('Loading wind data (variant=%s, years=%s, use_raw=%s)',
             args.variant, args.years, args.use_raw_forecast)
    t0 = time.time()
    actual_df, forecast_df, meta_df = load_ny_real_wind_data(
        years=args.years, use_raw_forecast=args.use_raw_forecast,
        variant=args.variant,
    )
    log.info('Loaded in %.1fs: actuals %s, forecasts %d rows, meta %d plants',
             time.time() - t0, actual_df.shape, len(forecast_df), len(meta_df))

    # The engine expects forecast_df.Forecast_time to be a DatetimeIndex
    # field, and times must match actual_df.index.
    if actual_df.index.tz is None:
        actual_df.index = actual_df.index.tz_localize('UTC')

    # ------------------------------------------------------------------
    # 2. Build the per-day scenario time grids.
    # ------------------------------------------------------------------
    start_ts = pd.Timestamp(args.start, tz='UTC')
    log.info('Generating scenarios for %d day(s) starting %s',
             args.days, start_ts.date())

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for d in range(args.days):
        day_start = start_ts + pd.Timedelta(days=d)
        scen_timesteps = pd.date_range(day_start, periods=24, freq='h', tz='UTC')

        # ------------------------------------------------------------------
        # 3. Split history/future for both actuals and forecasts.
        # ------------------------------------------------------------------
        # in_sample=False: history strictly BEFORE the scenario start. The old
        # in_sample=True trained on every hour except the 24 scenario hours --
        # i.e. on data AFTER the scenario day -- which leaks in any backtest
        # (Per_Plant_Wind_Plan.md s4). For a true forward run history is naturally
        # pre-scenario, so this is the correct default in both cases.
        actual_hist, actual_future = split_actuals_hist_future(
            actual_df, scen_timesteps, in_sample=False)
        forecast_hist, forecast_future = split_forecasts_hist_future(
            forecast_df, scen_timesteps, in_sample=False)

        log.info('[%s] hist: %d hours of actuals, %d forecast rows',
                 day_start.date(), len(actual_hist), len(forecast_hist))

        # ------------------------------------------------------------------
        # 4. Fit the engine and generate scenarios.
        # ------------------------------------------------------------------
        # forecast_lead_time_in_hour=18: our forecasts are issued at 06Z and
        # the first forecast hour is 00Z next day (matches the Issue_time
        # normalization in load_ny_real_wind_data). The engine default of 12
        # is for ERCOT/NREL conventions and would mis-align our windows.
        engine = GeminiEngine(
            actual_hist, forecast_hist, scen_timesteps[0],
            meta_df=meta_df, asset_type='wind',
            forecast_lead_time_in_hour=18,
        )
        dist = engine.asset_distance().values
        # geographic asset_rho scaled to fleet diameter (matches T7k pattern)
        engine.fit(2 * args.asset_rho * dist / dist.max(), args.time_rho)
        engine.create_scenario(args.scenario_count, forecast_future)

        # ------------------------------------------------------------------
        # 4b. Short-history regularizer: widen young-plant (2023-24) marginals
        #     to the mature-fleet spread, in place, before writing.
        # ------------------------------------------------------------------
        if args.short_history_reg:
            from pgscen.short_history import build_factors, widen_engine_scenarios
            factors, _ = build_factors(actual_hist, forecast_hist,
                                       day_start.year)
            widen_engine_scenarios(engine, forecast_future, scen_timesteps,
                                   factors)
            log.info('[%s] short-history reg: widened %d young plant(s)',
                     day_start.date(), len(factors))

        # ------------------------------------------------------------------
        # 5. Write per-asset scenario CSVs to <out_dir>/<YYYYMMDD>/wind/
        # ------------------------------------------------------------------
        engine.write_to_csv(out_dir, actual_future, write_forecasts=True)
        log.info('[%s] wrote scenarios to %s/%s/wind/',
                 day_start.date(), out_dir, day_start.strftime('%Y%m%d'))

        # ------------------------------------------------------------------
        # 6. Optional: compute energy scores for this day.
        # ------------------------------------------------------------------
        if args.score:
            scen_df = engine.scenarios['wind']
            day_actual = actual_future.loc[scen_timesteps]
            day_forecast = forecast_future[
                forecast_future.Forecast_time.isin(scen_timesteps)]
            try:
                es = compute_energy_scores(scen_df, day_actual, day_forecast)
                # Normalize per-plant by capacity for comparability
                caps = meta_df.set_index('Facility.Name')['Capacity']
                es_norm = (es / caps.reindex(es.index)) * 100  # % of cap
                log.info('[%s] energy score (mean %.2f, normalised mean %.2f%% of cap)',
                         day_start.date(), es.mean(), es_norm.mean())
                summary_path = out_dir / 'energy_scores.csv'
                row = pd.DataFrame({
                    'date': day_start.strftime('%Y-%m-%d'),
                    'asset': es.index, 'energy_score': es.values,
                    'cap_mw': caps.reindex(es.index).values,
                    'energy_score_pct_cap': es_norm.values,
                })
                if summary_path.exists():
                    row.to_csv(summary_path, mode='a', header=False, index=False)
                else:
                    row.to_csv(summary_path, index=False)
            except Exception as e:
                log.warning('[%s] energy score failed: %s',
                            day_start.date(), e)

    log.info('Done.')


if __name__ == '__main__':
    main()
