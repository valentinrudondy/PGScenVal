"""Run PGScen single-stage 11-zone NYISO LOAD scenario generation (production).

Fits ONE GeminiEngine over all 11 NYISO load zones and draws scenarios directly
(``pgscen.load_scenarios.run_load_one_day``). This is the production load runner.
Load is modelled independently of wind/solar/BTM (their cross-group correlation
is ~0; see ``pgscen/load_scenarios.py`` and ``Claude_load.md``). Mirrors
``10_run_pgscen_wind.py`` and writes per-zone scenario CSVs under
``<out_dir>/<YYYYMMDD>/load/`` (the same ``engine.write_to_csv`` schema the grid
bridge consumes for wind).

Usage
-----
    python scripts/12_run_pgscen_load.py 2024-07-15 1 --scenario-count 100
    python scripts/12_run_pgscen_load.py 2024-07-15 7 --scenario-count 1000 \\
        -o outputs/load_scenarios_2024Q3
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pgscen.utils.data_utils import load_ny_real_load_data
from pgscen.load_scenarios import run_load_one_day

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split('\n')[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('start', help='first ET scenario day, YYYY-MM-DD')
    ap.add_argument('days', type=int, help='number of consecutive ET days')
    ap.add_argument('-o', '--out-dir', default='outputs/load_scenarios')
    ap.add_argument('-n', '--scenario-count', type=int, default=1000)
    ap.add_argument('--asset-rho', type=float, default=0.002,
                    help='glasso penalty on zone (asset) interactions. 0.002 is '
                         'optimal for the 11-zone load-only fit: per-zone cov is '
                         'rho-insensitive (marginal-driven) and the fleet/total '
                         'cov is best at the lowest rho.')
    ap.add_argument('--horizon-rho', type=float, default=0.05)
    ap.add_argument('--years', type=int, nargs='+', default=None,
                    help='years of load history to load (default: all available, '
                         'matching the validated calibration). The leakage-safe '
                         'split uses only history strictly before each scenario day.')
    ap.add_argument('--random-seed', type=int, default=None)
    args = ap.parse_args()

    log.info('Loading NYISO 11-zone load data (years=%s)', args.years)
    t0 = time.time()
    actual_df, forecast_df = load_ny_real_load_data(years=args.years)
    log.info('Loaded in %.1fs: actuals %s, forecast %d rows',
             time.time() - t0, actual_df.shape, len(forecast_df))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(args.start)
    log.info('Generating 11-zone load scenarios for %d ET day(s) from %s',
             args.days, start.date())

    for d in range(args.days):
        day = (start + pd.Timedelta(days=d)).strftime('%Y-%m-%d')
        seed = None if args.random_seed is None else args.random_seed + d
        engine, actual_future, _, _ = run_load_one_day(
            day, nscen=args.scenario_count, asset_rho=args.asset_rho,
            horizon_rho=args.horizon_rho, preloaded=(actual_df, forecast_df),
            seed=seed)
        engine.write_to_csv(out_dir, actual_future, write_forecasts=True)
        log.info('[%s] wrote 11-zone load scenarios to %s/%s/load/',
                 day, out_dir, pd.Timestamp(day).strftime('%Y%m%d'))

    log.info('Done.')


if __name__ == '__main__':
    main()
