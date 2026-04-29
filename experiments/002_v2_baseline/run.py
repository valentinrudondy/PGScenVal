#!/usr/bin/env python
"""
Experiment 002: v2 Stochastic vs. Deterministic Unit Commitment — July 2019
===========================================================================

Re-runs the same scientific experiment as 001 under fully validated v2
infrastructure: Gurobi PTDF, Path B import costs, PTDF slacks ($5k/MWh),
multi-bus imports, BESS + pumped storage, mandatory warmup, fixed 2,620 MW
reserve.

Usage:
    # Smoke test: 5 scenarios, 1 day (July 18) with warmup day
    python run.py --smoke

    # Full run: 100 scenarios, 7 days (July 15–21) with warmup day
    python run.py

    # Steps can be run individually:
    python run.py --step scenarios       # generate PGscen scenarios only
    python run.py --step deterministic   # run deterministic baseline only
    python run.py --step stochastic      # run stochastic ensemble only
"""

import argparse
import datetime
import logging
import os
import pickle
import sys
import time
import traceback
import warnings
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Resolve project paths so imports work regardless of cwd
# ---------------------------------------------------------------------------
EXPERIMENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENT_DIR.parent.parent  # /Users/val/Desktop/Princeton

sys.path.insert(0, str(PROJECT_ROOT / "PGscen-2nd"))
sys.path.insert(0, str(PROJECT_ROOT / "Vatic"))

# Verify Egret patch before running (see docs/egret_patch_required.md)
from vatic._egret_compat import check_egret_patch
check_egret_patch()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config():
    with open(EXPERIMENT_DIR / "config.yaml") as f:
        return yaml.safe_load(f)

CFG = load_config()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("experiment002")


# ============================================================================
# STEP 1: Generate PGscen scenarios (identical to 001)
# ============================================================================

def generate_scenarios(dates, n_scenarios, seed, log):
    """Generate correlated wind/solar/load scenarios for each day.

    Identical to experiment 001 — same PGscen parameters, same seed.
    """
    from pgscen.utils.data_utils import (
        load_ny_load_data,
        load_ny_solar_data,
        load_ny_real_wind_data,
        split_actuals_hist_future,
        split_forecasts_hist_future,
    )
    from pgscen.regime_model import RegimeGeminiEngine, RegimePCAGeminiEngine

    scen_dir = EXPERIMENT_DIR / CFG["paths"]["scenarios_dir"]
    scen_dir.mkdir(parents=True, exist_ok=True)

    asset_rho = CFG["pgscen"]["asset_rho"]
    time_rho = CFG["pgscen"]["time_rho"]
    pca_components = CFG["pgscen"]["pca_components"]

    log.info("Loading historical data for PGscen...")
    t0 = time.time()

    load_actuals, load_forecasts = load_ny_load_data()
    wind_actuals, wind_forecasts, wind_meta = load_ny_real_wind_data(
        years=[2019]
    )
    solar_actuals, solar_forecasts, solar_meta = load_ny_solar_data()

    log.info("Data loaded in %.1f s. Wind(HRRR): %d sites, "
             "Solar(std): %d sites, Load: %d zones",
             time.time() - t0,
             len(wind_actuals.columns),
             len(solar_actuals.columns),
             len(load_actuals.columns))

    all_scenario_data = {i: [] for i in range(n_scenarios)}

    for day_date in dates:
        day_str = day_date.strftime("%Y-%m-%d")
        log.info("=== Generating %d scenarios for %s ===", n_scenarios, day_str)
        day_t0 = time.time()

        if seed is not None:
            np.random.seed(seed + day_date.toordinal())

        # ── WIND (NYISO_real, 00:00 UTC start, lead_time=18h) ──
        wind_scen_start = pd.Timestamp(f"{day_str} 00:00:00", tz="utc")
        wind_scen_timesteps = pd.date_range(
            start=wind_scen_start, periods=24, freq="h"
        )

        wind_actual_hist, _ = split_actuals_hist_future(
            wind_actuals, wind_scen_timesteps, in_sample=True
        )
        wind_forecast_hist, wind_forecast_future = split_forecasts_hist_future(
            wind_forecasts, wind_scen_timesteps, in_sample=True
        )

        log.info("  Fitting wind model (HRRR, %d sites)...",
                 len(wind_actuals.columns))
        wind_engine = RegimeGeminiEngine(
            wind_actual_hist, wind_forecast_hist,
            wind_scen_timesteps[0], wind_meta, asset_type="wind",
            forecast_lead_time_in_hour=18,
        )
        dist = wind_engine.asset_distance().values
        wind_engine.fit(2 * asset_rho * dist / dist.max(), time_rho)
        wind_engine.create_scenario(n_scenarios, wind_forecast_future)
        wind_scens = wind_engine.scenarios["wind"]

        # ── LOAD (standard PGscen, 06:00 UTC start) ──
        load_scen_start = pd.Timestamp(f"{day_str} 06:00:00", tz="utc")
        load_scen_timesteps = pd.date_range(
            start=load_scen_start, periods=24, freq="h"
        )

        load_actual_hist, _ = split_actuals_hist_future(
            load_actuals, load_scen_timesteps, in_sample=False
        )
        load_forecast_hist, load_forecast_future = split_forecasts_hist_future(
            load_forecasts, load_scen_timesteps, in_sample=False
        )

        log.info("  Fitting load model (11 zones)...")
        load_engine = RegimeGeminiEngine(
            load_actual_hist, load_forecast_hist,
            load_scen_timesteps[0], asset_type="load",
        )
        load_engine.fit(asset_rho, time_rho)
        load_engine.create_scenario(n_scenarios, load_forecast_future)
        load_scens = load_engine.scenarios["load"]

        # ── SOLAR (standard PGscen, 06:00 UTC start) ──
        solar_actual_hist, _ = split_actuals_hist_future(
            solar_actuals, load_scen_timesteps, in_sample=False
        )
        solar_forecast_hist, solar_forecast_future = split_forecasts_hist_future(
            solar_forecasts, load_scen_timesteps, in_sample=False
        )

        log.info("  Fitting solar model (PCA, %d sites)...",
                 len(solar_actuals.columns))
        solar_engine = RegimePCAGeminiEngine(
            solar_actual_hist, solar_forecast_hist,
            load_scen_timesteps[0], solar_meta, us_state="New York",
        )
        sdist = solar_engine.asset_distance().values
        solar_engine.fit(
            asset_rho=20 * asset_rho * sdist / sdist.max(),
            pca_comp_rho=time_rho,
            num_of_components=pca_components,
            nearest_days=50,
        )
        solar_engine.create_scenario(n_scenarios, solar_forecast_future)
        solar_scens = solar_engine.scenarios["solar"]
        solar_fcst = solar_engine.forecasts["solar"]

        log.info("  Day %s generated in %.1f s", day_str, time.time() - day_t0)

        # -- Compute solar system-level ratios --
        solar_fcst_hourly = {}
        for (site, ts), val in solar_fcst.items():
            solar_fcst_hourly[ts] = solar_fcst_hourly.get(ts, 0) + max(val, 0)

        # -- Store per-scenario data --
        for scen_idx in range(n_scenarios):
            records = []

            # Wind: per-site values
            wind_row = wind_scens.iloc[scen_idx]
            for (site, ts), val in wind_row.items():
                records.append({
                    "timestamp": ts, "asset_id": site,
                    "asset_type": "wind", "value_mw": max(0, val),
                })

            # Solar: system-level ratio
            solar_row = solar_scens.iloc[scen_idx]
            solar_scen_hourly = {}
            for (site, ts), val in solar_row.items():
                solar_scen_hourly[ts] = (
                    solar_scen_hourly.get(ts, 0) + max(val, 0)
                )

            for ts in load_scen_timesteps:
                fcst_total = solar_fcst_hourly.get(ts, 0)
                scen_total = solar_scen_hourly.get(ts, 0)
                ratio = scen_total / fcst_total if fcst_total > 1.0 else 1.0
                records.append({
                    "timestamp": ts, "asset_id": "_solar_system",
                    "asset_type": "solar_ratio", "value_mw": ratio,
                })

            # Load: per-zone values
            load_row = load_scens.iloc[scen_idx]
            for (zone, ts), val in load_row.items():
                records.append({
                    "timestamp": ts, "asset_id": zone,
                    "asset_type": "load", "value_mw": max(0, val),
                })

            all_scenario_data[scen_idx].append(pd.DataFrame(records))

    # -- Save each scenario as a single parquet --
    for scen_idx in range(n_scenarios):
        df = pd.concat(all_scenario_data[scen_idx], ignore_index=True)
        df = df.set_index(["timestamp", "asset_id"]).sort_index()
        out_path = scen_dir / f"scenario_{scen_idx:03d}.parquet"
        df.to_parquet(out_path)

    log.info("All %d scenarios saved to %s", n_scenarios, scen_dir)


# ============================================================================
# Shared: build NyisoLoader and timeseries for a day
# ============================================================================

def _build_loader_and_timeseries(day_str, cfg, init_state_file=None):
    """Create NyisoLoader and get gen_data/load_data for a day + buffer."""
    from vatic.data.nyiso_loader import NyisoLoader

    pgscen_dir = str(Path(cfg["_experiment_dir"]) / cfg["vatic"]["pgscen_dir"])

    loader = NyisoLoader(
        init_state_file=init_state_file,
        use_reduced_network=cfg["vatic"]["use_reduced_network"],
        fuel_price_date=day_str,
        pgscen_dir=pgscen_dir,
        year=cfg["dates"]["year"],
    )

    start_dt = pd.Timestamp(day_str, tz="utc")
    end_dt = start_dt + pd.Timedelta(days=2)  # need 48h for RUC horizon
    gen_data, load_data = loader.create_timeseries(
        start_date=start_dt, end_date=end_dt
    )

    return loader, gen_data, load_data


def _run_vatic_simulation(loader, gen_data, load_data, day_date, cfg,
                          last_conditions_file=None):
    """Run one Vatic Simulator for one day, return results dict.

    v2 changes vs. 001:
    - Gurobi solver (5x faster than CBC)
    - Fixed 2,620 MW reserve (reserve_requirement_mw)
    - reserve_factor=0 (use fixed MW, not % of load)
    - Solver timeout 1200s
    - Verbosity 1 (aggressive logging)
    """
    from vatic.engines import Simulator

    sim = Simulator(
        template_data=loader.template,
        gen_data=gen_data,
        load_data=load_data,
        out_dir=None,
        start_date=day_date,
        num_days=1,
        solver=cfg["vatic"]["solver"],
        solver_options=cfg["vatic"]["solver_options"],
        run_lmps=cfg["vatic"]["run_lmps"],
        mipgap=cfg["vatic"]["mipgap"],
        load_shed_penalty=1e4,
        reserve_shortfall_penalty=1e3,
        reserve_factor=cfg["vatic"]["reserve_factor"],
        output_detail=cfg["vatic"]["output_detail"],
        prescient_sced_forecasts=False,
        ruc_prescience_hour=0,
        ruc_execution_hour=16,
        ruc_every_hours=24,
        ruc_horizon=cfg["vatic"]["ruc_horizon"],
        sced_horizon=cfg["vatic"]["sced_horizon"],
        lmp_shortfall_costs=False,
        enforce_sced_shutdown_ramprate=False,
        no_startup_shutdown_curves=False,
        init_ruc_file=None,
        verbosity=cfg["vatic"]["verbosity"],
        output_max_decimals=4,
        create_plots=False,
        renew_costs=None,
        save_to_csv=False,
        last_conditions_file=last_conditions_file,
        reserve_requirement_mw=cfg["vatic"]["reserve_requirement_mw"],
    )

    return sim.simulate()


# ============================================================================
# Scenario application (identical to 001)
# ============================================================================

def _apply_scenario_to_timeseries(gen_data, load_data, scen_df, day_date,
                                   loader, cfg):
    """Override gen_data/load_data with scenario values for one day."""
    start_dt = pd.Timestamp(day_date.isoformat(), tz="utc")
    end_dt = start_dt + pd.Timedelta(days=1)

    gen_data = gen_data.copy()
    load_data = load_data.copy()

    site_map = loader._pgscen_site_map

    # --- Wind: per-site direct mapping ---
    wind_scen = scen_df[scen_df["asset_type"] == "wind"]
    if not wind_scen.empty:
        for site_id in wind_scen.index.get_level_values("asset_id").unique():
            gen_id = site_map.get(site_id)
            if gen_id is None:
                continue
            if ("fcst", gen_id) not in gen_data.columns:
                continue

            site_data = wind_scen.xs(site_id, level="asset_id")
            for ts in site_data.index.get_level_values("timestamp"):
                if ts < start_dt or ts >= end_dt:
                    continue
                if ts not in gen_data.index:
                    continue
                val = max(0, site_data.loc[ts, "value_mw"])
                gen_data.loc[ts, ("fcst", gen_id)] = val
                gen_data.loc[ts, ("actl", gen_id)] = val

    # --- Solar: system-level ratio ---
    solar_ratio = scen_df[scen_df["asset_type"] == "solar_ratio"]
    if not solar_ratio.empty:
        solar_ratio_data = solar_ratio.xs("_solar_system", level="asset_id")
        solar_gens = [g for g in gen_data.columns.get_level_values(1).unique()
                      if g.startswith("NYISO_S_")]

        for ts in solar_ratio_data.index.get_level_values("timestamp"):
            if ts not in gen_data.index:
                continue
            ratio = solar_ratio_data.loc[ts, "value_mw"]
            for gen_id in solar_gens:
                if ("fcst", gen_id) in gen_data.columns:
                    gen_data.loc[ts, ("fcst", gen_id)] *= ratio
                    gen_data.loc[ts, ("actl", gen_id)] *= ratio

    # --- Load: per-zone scaling ---
    load_scen = scen_df[scen_df["asset_type"] == "load"]
    if not load_scen.empty:
        pgscen_dir = Path(cfg["_experiment_dir"]) / cfg["vatic"]["pgscen_dir"]
        la_file = pgscen_dir / ("load_actual_1h_zone_2018_2019_2020_2021"
                                "_2022_2023_2024_2025_utc.csv")
        if la_file.exists():
            la = pd.read_csv(la_file, parse_dates=["Time"], index_col="Time")
        else:
            la_file2 = (pgscen_dir.parent / "NYISO" / "Load" / "Day-ahead"
                        / "load_day_ahead_forecast_zone_2018_2019_utc.csv")
            la = pd.read_csv(la_file2, parse_dates=["Forecast_time"])
            la = la.drop(columns=["Issue_time"]).set_index("Forecast_time")

        from vatic.data.nyiso_loader import _ZONE_NAME_TO_LETTER, _ROOT
        renew_path = Path(_ROOT, '..', '..', '..', 'third_party', 'NYgrid',
                          'Data', 'RenewableGen.csv')
        renew_df = pd.read_csv(renew_path)
        bus_name_by_id = {b.ID: b.Name for b in loader.buses}
        bus_set = set(loader.template['Buses'])
        letter_to_buses = {}
        for _, r in renew_df.iterrows():
            bid = int(r['bus_id']); z = r['Zone']; lv = r['Load']
            if pd.notna(lv) and lv > 0:
                n = bus_name_by_id.get(bid)
                if n and n in bus_set:
                    letter_to_buses.setdefault(z, set()).add(n)

        for zone_name in load_scen.index.get_level_values("asset_id").unique():
            if zone_name not in la.columns:
                continue

            zone_letter = _ZONE_NAME_TO_LETTER.get(zone_name)
            if zone_letter is None or zone_letter not in letter_to_buses:
                continue
            zone_bus_names = letter_to_buses[zone_letter]

            zone_scen_data = load_scen.xs(zone_name, level="asset_id")

            for ts in zone_scen_data.index.get_level_values("timestamp"):
                if ts not in load_data.index:
                    continue

                scen_val = zone_scen_data.loc[ts, "value_mw"]
                ts_lookup = ts
                if la.index.tz is None and ts.tzinfo is not None:
                    ts_lookup = ts.tz_localize(None)
                elif la.index.tz is not None and ts.tzinfo is None:
                    ts_lookup = ts.tz_localize(la.index.tz)
                if ts_lookup not in la.index:
                    continue

                baseline_zone = la.loc[ts_lookup, zone_name]
                if baseline_zone > 10:
                    ratio = scen_val / baseline_zone
                else:
                    ratio = 1.0

                for bus_name in zone_bus_names:
                    if ("fcst", bus_name) in load_data.columns:
                        load_data.loc[ts, ("fcst", bus_name)] *= ratio
                        load_data.loc[ts, ("actl", bus_name)] *= ratio

    gen_data = gen_data.clip(lower=0)
    load_data = load_data.clip(lower=0)

    return gen_data, load_data


# ============================================================================
# STEP 2: Deterministic baseline
# ============================================================================

def run_deterministic(dates, log):
    """Run Vatic on the NYISO day-ahead forecast for each day."""
    det_dir = EXPERIMENT_DIR / CFG["paths"]["deterministic_dir"]
    det_dir.mkdir(parents=True, exist_ok=True)

    cfg = {**CFG, "_experiment_dir": str(EXPERIMENT_DIR)}
    prev_conditions_csv = None

    for day_date in dates:
        day_str = day_date.strftime("%Y-%m-%d")
        out_path = det_dir / f"day_{day_str}.pkl"
        cond_path = det_dir / f"conditions_{day_str}.csv"

        if out_path.exists():
            log.info("Deterministic day %s already exists, skipping", day_str)
            if cond_path.exists():
                prev_conditions_csv = str(cond_path)
            continue

        log.info("=== Deterministic run: %s ===", day_str)
        t0 = time.time()

        loader, gen_data, load_data = _build_loader_and_timeseries(
            day_str, cfg, init_state_file=prev_conditions_csv
        )
        results = _run_vatic_simulation(
            loader, gen_data, load_data, day_date, cfg,
            last_conditions_file=str(cond_path),
        )
        elapsed = time.time() - t0

        with open(out_path, "wb") as f:
            pickle.dump(results, f)

        prev_conditions_csv = str(cond_path)

        cost = (results["hourly_summary"]["FixedCosts"].sum()
                + results["hourly_summary"]["VariableCosts"].sum())
        ls = results["hourly_summary"]["LoadShedding"].sum()
        log.info("  Day %s done in %.1f s — cost: $%.0f, load_shed: %.0f MWh",
                 day_str, elapsed, cost, ls)


# ============================================================================
# STEP 3: Stochastic ensemble
# ============================================================================

def _run_single_scenario_multiday(args):
    """Worker: run all target days for one scenario, chaining conditions."""
    scen_idx, target_dates, warmup_date, cfg_copy = args

    import pickle
    import time
    import sys
    import warnings
    from pathlib import Path

    warnings.filterwarnings("ignore", category=RuntimeWarning)

    project_root = Path(cfg_copy["_experiment_dir"]).parent.parent
    sys.path.insert(0, str(project_root / "PGscen-2nd"))
    sys.path.insert(0, str(project_root / "Vatic"))

    import pandas as pd

    experiment_dir = Path(cfg_copy["_experiment_dir"])
    stoch_dir = experiment_dir / cfg_copy["paths"]["stochastic_dir"]
    scen_out_dir = stoch_dir / f"scenario_{scen_idx:03d}"
    scen_out_dir.mkdir(parents=True, exist_ok=True)

    # Check if already fully complete
    last_day = target_dates[-1].strftime("%Y-%m-%d")
    if (scen_out_dir / f"day_{last_day}.pkl").exists():
        return (scen_idx, True, 0.0, len(target_dates), len(target_dates), None)

    try:
        t0 = time.time()

        scen_path = (experiment_dir / cfg_copy["paths"]["scenarios_dir"]
                     / f"scenario_{scen_idx:03d}.parquet")
        scen_df = pd.read_parquet(scen_path)

        # Start from deterministic warmup day's conditions
        det_dir = experiment_dir / cfg_copy["paths"]["deterministic_dir"]
        warmup_str = warmup_date.strftime("%Y-%m-%d")
        prev_conditions = str(det_dir / f"conditions_{warmup_str}.csv")
        if not Path(prev_conditions).exists():
            prev_conditions = None

        days_completed = 0
        for day_date in target_dates:
            day_str = day_date.strftime("%Y-%m-%d")
            out_path = scen_out_dir / f"day_{day_str}.pkl"
            cond_path = scen_out_dir / f"conditions_{day_str}.csv"

            if out_path.exists():
                if cond_path.exists():
                    prev_conditions = str(cond_path)
                days_completed += 1
                continue

            loader, gen_data, load_data = _build_loader_and_timeseries(
                day_str, cfg_copy, init_state_file=prev_conditions
            )
            gen_data, load_data = _apply_scenario_to_timeseries(
                gen_data, load_data, scen_df, day_date, loader, cfg_copy
            )
            results = _run_vatic_simulation(
                loader, gen_data, load_data, day_date, cfg_copy,
                last_conditions_file=str(cond_path),
            )

            with open(out_path, "wb") as f:
                pickle.dump(results, f)

            if cond_path.exists():
                prev_conditions = str(cond_path)
            days_completed += 1

        elapsed = time.time() - t0
        return (scen_idx, True, elapsed, days_completed,
                len(target_dates), None)

    except Exception:
        elapsed = time.time() - t0
        return (scen_idx, False, elapsed, days_completed,
                len(target_dates), traceback.format_exc())


def run_stochastic(dates, n_scenarios, log):
    """Run Vatic for each scenario across all target days."""
    stoch_dir = EXPERIMENT_DIR / CFG["paths"]["stochastic_dir"]
    stoch_dir.mkdir(parents=True, exist_ok=True)

    max_workers = CFG["parallelism"]["max_workers"]
    if max_workers is None:
        max_workers = max(1, cpu_count() - 1)

    cfg = {**CFG, "_experiment_dir": str(EXPERIMENT_DIR)}

    warmup_date = dates[0]
    target_dates = dates[1:]

    tasks = []
    for scen_idx in range(n_scenarios):
        tasks.append((scen_idx, target_dates, warmup_date, cfg))

    log.info("Launching %d stochastic scenarios (%d target days each) "
             "with %d workers — Gurobi, 2620 MW reserve",
             n_scenarios, len(target_dates), max_workers)

    completed = 0
    failed = 0
    wall_times = []

    t0 = time.time()

    with Pool(processes=max_workers) as pool:
        for result in pool.imap_unordered(_run_single_scenario_multiday, tasks):
            scen_idx, success, elapsed, days_done, days_total, err = result
            completed += 1
            wall_times.append(elapsed)

            if success:
                log.info("  [%d/%d] scenario_%03d — %d/%d days, %.1f s",
                         completed, n_scenarios, scen_idx,
                         days_done, days_total, elapsed)
            else:
                failed += 1
                log.error("  [%d/%d] FAILED scenario_%03d at day %d/%d "
                          "— %.1f s\n%s",
                          completed, n_scenarios, scen_idx,
                          days_done, days_total, elapsed, err)

    total_wall = time.time() - t0
    log.info("Stochastic ensemble complete: %d/%d succeeded, %d failed. "
             "Wall time: %.0f s (%.1f min)",
             completed - failed, n_scenarios, failed,
             total_wall, total_wall / 60)

    if wall_times:
        wt = sorted(wall_times)
        log.info("Per-scenario wall time: median=%.0fs, p95=%.0fs, max=%.0fs",
                 wt[len(wt)//2], wt[int(len(wt)*0.95)], wt[-1])


# ============================================================================
# Main
# ============================================================================

def parse_dates(start_str, end_str):
    start = datetime.date.fromisoformat(start_str)
    end = datetime.date.fromisoformat(end_str)
    return [start + datetime.timedelta(days=i)
            for i in range((end - start).days + 1)]


def main():
    parser = argparse.ArgumentParser(
        description="Experiment 002: v2 Stochastic vs Deterministic UC"
    )
    parser.add_argument("--smoke", action="store_true",
                        help="Smoke test: 5 scenarios, 1 target day + warmup")
    parser.add_argument("--step", choices=["scenarios", "deterministic",
                                           "stochastic", "all"],
                        default="all",
                        help="Run only a specific step")
    args = parser.parse_args()

    log_path = EXPERIMENT_DIR / CFG["paths"]["log_file"]
    log = setup_logging(log_path)

    if args.smoke:
        warmup = CFG["dates"]["warmup_smoke"]
        target = CFG["scenarios"]["smoke_test_day"]
        dates = parse_dates(warmup, target)
        n_scenarios = CFG["scenarios"]["smoke_test_count"]
        log.info("=== v2 SMOKE TEST: %d scenarios, %d day(s) "
                 "(warmup: %s, target: %s) ===",
                 n_scenarios, len(dates), warmup, target)
        log.info("v2 config: solver=%s, reserve_mw=%d, PTDF slacks=$5k/MWh",
                 CFG["vatic"]["solver"],
                 CFG["vatic"]["reserve_requirement_mw"])
    else:
        warmup = CFG["dates"]["warmup"]
        dates = parse_dates(warmup, CFG["dates"]["end"])
        n_scenarios = CFG["scenarios"]["count"]
        log.info("=== v2 FULL RUN: %d scenarios, %d days "
                 "(warmup: %s, target: %s to %s) ===",
                 n_scenarios, len(dates),
                 warmup, CFG["dates"]["start"], CFG["dates"]["end"])
        log.info("v2 config: solver=%s, reserve_mw=%d, PTDF slacks=$5k/MWh",
                 CFG["vatic"]["solver"],
                 CFG["vatic"]["reserve_requirement_mw"])

    seed = CFG["scenarios"]["random_seed"]
    overall_t0 = time.time()

    if args.step in ("all", "scenarios"):
        log.info("--- Step 1: Generate PGscen scenarios ---")
        generate_scenarios(dates, n_scenarios, seed, log)

    if args.step in ("all", "deterministic"):
        log.info("--- Step 2: Deterministic baseline ---")
        run_deterministic(dates, log)

    if args.step in ("all", "stochastic"):
        log.info("--- Step 3: Stochastic ensemble ---")
        run_stochastic(dates, n_scenarios, log)

    total_time = time.time() - overall_t0
    log.info("=== TOTAL WALL TIME: %.0f s (%.1f min) ===",
             total_time, total_time / 60)


if __name__ == "__main__":
    main()
