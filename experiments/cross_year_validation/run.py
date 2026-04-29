#!/usr/bin/env python
"""Cross-year deterministic validation runner.

Runs 3-day deterministic Vatic simulations for multiple years with:
  - Mandatory warmup day (prevents cold-start shedding artifact)
  - Fixed 2,620 MW system-wide reserve requirement (NYISO Ancillary
    Services Manual: 10-min + 30-min operating reserves, fixed-MW,
    independent of load level)

Usage:
    # Run all years with warmup (default):
    python run.py

    # Run a single year:
    python run.py --year 2022

    # Override warmup requirement (NOT recommended — cold-start artifact):
    python run.py --no-warmup
"""

import argparse
import datetime
import logging
import os
import pickle
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

sys.path.insert(0, str(PROJECT_ROOT / "Vatic"))
sys.path.insert(0, str(PROJECT_ROOT / "PGscen-2nd"))

# Verify Egret patch before running (see docs/egret_patch_required.md)
from vatic._egret_compat import check_egret_patch
check_egret_patch()

PGSCEN_DIR = str(PROJECT_ROOT / "PGscen-2nd" / "data" / "NYISO_real")
RESULTS_DIR = SCRIPT_DIR / "results"

# ---------------------------------------------------------------------------
# NYISO operating reserve requirement (fixed MW).
# Source: NYISO Ancillary Services Manual, Section 5.
# 10-min spinning + 10-min non-sync + 30-min = ~2,620 MW.
# This is set by the largest single contingency (Nine Mile Point 2,
# 1,299 MW), independent of system load level.
# ---------------------------------------------------------------------------
NYISO_RESERVE_REQUIREMENT_MW = 2620.0

# ---------------------------------------------------------------------------
# Simulation configs per year
# ---------------------------------------------------------------------------
YEAR_CONFIGS = {
    2019: {
        "sim_start": "2019-07-08",
        "sim_days": 3,
        "warmup_date": "2019-07-07",
        "fuel_price_date": "2019-07-08",
    },
    2020: {
        "sim_start": "2020-09-22",
        "sim_days": 3,
        "warmup_date": "2020-09-21",
        "fuel_price_date": "2020-09-22",
    },
    2022: {
        "sim_start": "2022-09-20",
        "sim_days": 3,
        "warmup_date": "2022-09-19",
        "fuel_price_date": None,  # EIA-based
    },
    2023: {
        "sim_start": "2023-09-19",
        "sim_days": 3,
        "warmup_date": "2023-09-18",
        "fuel_price_date": None,  # EIA-based
    },
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(RESULTS_DIR / "run.log", mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("cross_year_validation")


# ---------------------------------------------------------------------------
# Core simulation functions
# ---------------------------------------------------------------------------

def run_single_day(loader, gen_data, load_data, day_date, run_lmps=True,
                   last_conditions_file=None, reserve_mw=0.):
    """Run Vatic for one day, return results dict."""
    from vatic.engines import Simulator

    sim = Simulator(
        template_data=loader.template,
        gen_data=gen_data,
        load_data=load_data,
        out_dir=None,
        start_date=day_date,
        num_days=1,
        solver="gurobi",
        solver_options={"TimeLimit": 600},
        run_lmps=run_lmps,
        mipgap=0.01,
        load_shed_penalty=1e4,
        reserve_shortfall_penalty=1e3,
        reserve_factor=0.0,  # disabled — using fixed MW instead
        output_detail=2,
        prescient_sced_forecasts=False,
        ruc_prescience_hour=0,
        ruc_execution_hour=16,
        ruc_every_hours=24,
        ruc_horizon=48,
        sced_horizon=4,
        lmp_shortfall_costs=False,
        enforce_sced_shutdown_ramprate=False,
        no_startup_shutdown_curves=False,
        init_ruc_file=None,
        verbosity=0,
        output_max_decimals=4,
        create_plots=False,
        renew_costs=None,
        save_to_csv=False,
        last_conditions_file=last_conditions_file,
        reserve_requirement_mw=reserve_mw,
    )
    return sim.simulate()


def run_year(year, cfg, log, use_warmup=True):
    """Run a multi-day deterministic simulation for one year.

    With warmup=True (default), a warmup day is simulated first and its
    final generator states seed the target days. The warmup day results
    are discarded.
    """
    from vatic.data.nyiso_loader import NyisoLoader

    tag = "warmup" if use_warmup else "no_warmup"
    out_dir = RESULTS_DIR / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pkl = out_dir / f"det_{year}.pkl"

    if out_pkl.exists():
        log.info("Year %d (%s): cached result exists, loading", year, tag)
        with open(out_pkl, "rb") as f:
            return pickle.load(f)

    sim_start = cfg["sim_start"]
    sim_days = cfg["sim_days"]
    warmup_date = cfg["warmup_date"]

    # Build date list
    if use_warmup:
        dates = [datetime.date.fromisoformat(warmup_date)]
    else:
        dates = []
    start_d = datetime.date.fromisoformat(sim_start)
    dates.extend([start_d + datetime.timedelta(days=i) for i in range(sim_days)])

    log.info("=== Year %d (%s): %s ===", year, tag,
             " → ".join(d.isoformat() for d in dates))

    prev_cond = None
    all_results = []
    t0 = time.time()

    for i, day_date in enumerate(dates):
        day_str = day_date.isoformat()
        is_warmup = use_warmup and i == 0

        # Build loader and timeseries for this day + RUC horizon
        loader = NyisoLoader(
            init_state_file=prev_cond,
            pgscen_dir=PGSCEN_DIR,
            use_reduced_network=True,
            fuel_price_date=cfg["fuel_price_date"],
            year=year,
        )
        day_start = pd.Timestamp(day_str, tz="utc")
        day_end = day_start + pd.Timedelta(days=2)
        gen_data, load_data = loader.create_timeseries(day_start, day_end)

        # Conditions file for chaining
        cond_path = str(out_dir / f"conditions_{year}_{day_str}.csv")

        result = run_single_day(
            loader, gen_data, load_data, day_date,
            run_lmps=not is_warmup,  # skip LMPs on warmup for speed
            last_conditions_file=cond_path,
            reserve_mw=NYISO_RESERVE_REQUIREMENT_MW,
        )

        prev_cond = cond_path

        hs = result["hourly_summary"]
        cost = hs["FixedCosts"].sum() + hs["VariableCosts"].sum()
        ls = hs["LoadShedding"].sum()
        rs = hs["ReserveShortfall"].sum()

        label = "WARMUP" if is_warmup else f"Day {i - (1 if use_warmup else 0) + 1}"
        log.info("  %s %s: cost=$%.0f, LS=%.0f MWh, RS=%.0f MWh",
                 label, day_str, cost, ls, rs)

        if not is_warmup:
            all_results.append(result)

    elapsed = time.time() - t0

    # Merge target-day results into a single result dict
    merged = _merge_results(all_results)

    with open(out_pkl, "wb") as f:
        pickle.dump(merged, f)

    hs = merged["hourly_summary"]
    total_cost = hs["FixedCosts"].sum() + hs["VariableCosts"].sum()
    total_ls = hs["LoadShedding"].sum()
    total_rs = hs["ReserveShortfall"].sum()
    log.info("  TOTAL %d: cost=$%.0f, LS=%.0f MWh, RS=%.0f MWh, time=%.0fs",
             year, total_cost, total_ls, total_rs, elapsed)

    return merged


def _merge_results(results_list):
    """Merge multiple single-day result dicts into one."""
    if len(results_list) == 1:
        return results_list[0]

    merged = {}
    for key in results_list[0]:
        values = [r[key] for r in results_list]
        if isinstance(values[0], pd.DataFrame):
            merged[key] = pd.concat(values)
        elif isinstance(values[0], (int, float)):
            merged[key] = sum(values)
        elif isinstance(values[0], dict):
            merged[key] = values[-1]  # take last day's dict
        else:
            merged[key] = values[-1]

    return merged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Cross-year deterministic validation"
    )
    parser.add_argument("--year", type=int, choices=list(YEAR_CONFIGS.keys()),
                        help="Run a single year (default: all)")
    parser.add_argument(
        "--no-warmup", action="store_true",
        help="DANGEROUS: Skip warmup day. Produces cold-start artifacts. "
             "Only use for regression testing the cold-start bug."
    )
    args = parser.parse_args()

    log = setup_logging()

    if args.no_warmup:
        log.warning("=" * 70)
        log.warning("WARNING: --no-warmup flag set. Simulations will start")
        log.warning("from cold state, producing load shedding artifacts at")
        log.warning("hour 0. Results are NOT valid for analysis. Use warmup")
        log.warning("days for all production runs.")
        log.warning("=" * 70)

    use_warmup = not args.no_warmup
    years = [args.year] if args.year else sorted(YEAR_CONFIGS.keys())

    log.info("Reserve requirement: %.0f MW (fixed, NYISO Ancillary Services Manual)",
             NYISO_RESERVE_REQUIREMENT_MW)
    log.info("Warmup: %s", "enabled" if use_warmup else "DISABLED (--no-warmup)")

    for year in years:
        cfg = YEAR_CONFIGS[year]
        run_year(year, cfg, log, use_warmup=use_warmup)


if __name__ == "__main__":
    main()
