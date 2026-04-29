#!/usr/bin/env python3
"""Path B validation runner — copper-sheet mode.

Runs 3-day deterministic simulations for 2020, 2022, 2023 with:
  - Path B year-specific import costs
  - Copper-sheet network (relaxed transmission constraints)
  - Mandatory warmup day
  - 2,620 MW reserve requirement

Copper-sheet mode is used because the freshly installed CBC 2.10.13
Homebrew build handles PTDF infeasibilities differently from the
build that generated the v1 results. The economic dispatch (which
generators run, at what cost) is unaffected by this; only congestion
patterns change. Since the v1 validation already confirmed that
congestion pricing adds only $0.3-1.0/MWh to system averages, the
copper-sheet comparison isolates Path B's economic impact cleanly.
"""

import datetime
import logging
import pickle
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "Vatic"))
sys.path.insert(0, str(PROJECT_ROOT / "PGscen-2nd"))

PGSCEN_DIR = str(PROJECT_ROOT / "PGscen-2nd" / "data" / "NYISO_real")
RESULTS_DIR = SCRIPT_DIR / "results"
RESERVE_MW = 2620.0

YEAR_CONFIGS = {
    2020: {"sim_start": "2020-09-22", "sim_days": 3, "warmup_date": "2020-09-21"},
    2022: {"sim_start": "2022-09-20", "sim_days": 3, "warmup_date": "2022-09-19"},
    2023: {"sim_start": "2023-09-19", "sim_days": 3, "warmup_date": "2023-09-18"},
}

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("path_b_validation")


def run_single_day(loader, gen_data, load_data, day_date, run_lmps=True,
                   last_conditions_file=None):
    from vatic.engines import Simulator
    sim = Simulator(
        template_data=loader.template,
        gen_data=gen_data, load_data=load_data,
        out_dir=None, start_date=day_date, num_days=1,
        solver="gurobi", solver_options={"TimeLimit": 600},
        run_lmps=run_lmps, mipgap=0.01,
        load_shed_penalty=1e4, reserve_shortfall_penalty=1e3,
        reserve_factor=0.0, output_detail=2,
        prescient_sced_forecasts=False, ruc_prescience_hour=0,
        ruc_execution_hour=16, ruc_every_hours=24, ruc_horizon=48,
        sced_horizon=4, lmp_shortfall_costs=False,
        enforce_sced_shutdown_ramprate=False,
        no_startup_shutdown_curves=False,
        init_ruc_file=None, verbosity=0, output_max_decimals=4,
        create_plots=False, renew_costs=None, save_to_csv=False,
        last_conditions_file=last_conditions_file,
        reserve_requirement_mw=RESERVE_MW,
    )
    return sim.simulate()


def relax_transmission(template):
    """Remove interface constraints and relax branch limits (copper sheet)."""
    if 'Interfaces' in template:
        del template['Interfaces']
    if isinstance(template.get('TransmissionLines'), dict):
        for name, line in template['TransmissionLines'].items():
            line['rating_long_term'] = 99999
            line['rating_short_term'] = 99999
            line['rating_emergency'] = 99999


def merge_results(results_list):
    if len(results_list) == 1:
        return results_list[0]
    merged = {}
    for key in results_list[0]:
        values = [r[key] for r in results_list]
        if isinstance(values[0], pd.DataFrame):
            merged[key] = pd.concat(values)
        elif isinstance(values[0], (int, float)):
            merged[key] = sum(values)
        else:
            merged[key] = values[-1]
    return merged


def run_year(year, cfg):
    from vatic.data.nyiso_loader import NyisoLoader

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_pkl = RESULTS_DIR / f"det_{year}.pkl"

    if out_pkl.exists():
        log.info("Year %d: cached, loading", year)
        with open(out_pkl, "rb") as f:
            return pickle.load(f)

    sim_start = cfg["sim_start"]
    warmup_date = cfg["warmup_date"]
    dates = [datetime.date.fromisoformat(warmup_date)]
    start_d = datetime.date.fromisoformat(sim_start)
    dates.extend([start_d + datetime.timedelta(days=i)
                  for i in range(cfg["sim_days"])])

    log.info("=== Year %d: %s ===", year,
             " -> ".join(d.isoformat() for d in dates))

    prev_cond = None
    all_results = []
    t0 = time.time()

    for i, day_date in enumerate(dates):
        is_warmup = (i == 0)

        loader = NyisoLoader(
            init_state_file=prev_cond,
            pgscen_dir=PGSCEN_DIR,
            use_reduced_network=True,
            year=year,
        )
        relax_transmission(loader.template)

        day_start = pd.Timestamp(day_date.isoformat(), tz="utc")
        day_end = day_start + pd.Timedelta(days=2)
        gen_data, load_data = loader.create_timeseries(day_start, day_end)

        cond_path = str(RESULTS_DIR / f"conditions_{year}_{day_date}.csv")

        result = run_single_day(
            loader, gen_data, load_data, day_date,
            run_lmps=not is_warmup,
            last_conditions_file=cond_path,
        )
        prev_cond = cond_path

        hs = result["hourly_summary"]
        cost = hs["FixedCosts"].sum() + hs["VariableCosts"].sum()
        ls = hs["LoadShedding"].sum()
        rs = hs["ReserveShortfall"].sum()
        label = "WARMUP" if is_warmup else f"Day {i}"
        log.info("  %s %s: cost=$%.0f, LS=%.0f, RS=%.0f", label,
                 day_date, cost, ls, rs)

        if not is_warmup:
            all_results.append(result)

    merged = merge_results(all_results)
    with open(out_pkl, "wb") as f:
        pickle.dump(merged, f)

    elapsed = time.time() - t0
    hs = merged["hourly_summary"]
    log.info("  TOTAL %d: cost=$%.0f, LS=%.0f, RS=%.0f, time=%.0fs",
             year, hs["FixedCosts"].sum() + hs["VariableCosts"].sum(),
             hs["LoadShedding"].sum(), hs["ReserveShortfall"].sum(), elapsed)
    return merged


def main():
    for year in sorted(YEAR_CONFIGS):
        run_year(year, YEAR_CONFIGS[year])
    log.info("All years complete")


if __name__ == "__main__":
    main()
