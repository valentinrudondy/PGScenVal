#!/usr/bin/env python
"""
Experiment 001: Stochastic vs. Deterministic Unit Commitment — July 2019
========================================================================

Runs PGscen scenario generation for NYISO wind/solar/load, then feeds each
scenario through Vatic's NyisoLoader + Simulator to compare stochastic
ensemble costs against a deterministic baseline.

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
    return logging.getLogger("experiment001")


# ============================================================================
# STEP 1: Generate PGscen scenarios
# ============================================================================

def generate_scenarios(dates, n_scenarios, seed, log):
    """Generate correlated wind/solar/load scenarios for each day.

    Wind: NYISO_real HRRR data (23 sites matching NyisoLoader's 23 wind
    generators). Per-site trajectories preserved — no scalar compression.
    Uses scen_start at 00:00 UTC + forecast_lead_time=18h to match
    NYISO_real Issue_time convention.

    Solar: Standard PGscen data (314 sites). Only 2 solar generators in
    NyisoLoader (~4 MW total), so system-level ratio is acceptable.

    Load: Standard PGscen data (11 NYISO zones). Zones match NyisoLoader
    exactly.
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

    # -- Load all historical data once --
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

    # -- Generate day-at-a-time --
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

            # Wind: per-site values (site IDs match NyisoLoader exactly)
            wind_row = wind_scens.iloc[scen_idx]
            for (site, ts), val in wind_row.items():
                records.append({
                    "timestamp": ts, "asset_id": site,
                    "asset_type": "wind", "value_mw": max(0, val),
                })

            # Solar: system-level ratio (only 2 generators in NyisoLoader)
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
    """Run one Vatic Simulator for one day, return results dict."""
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
        verbosity=0,
        output_max_decimals=4,
        create_plots=False,
        renew_costs=None,
        save_to_csv=False,
        last_conditions_file=last_conditions_file,
    )

    return sim.simulate()


# ============================================================================
# Scenario application: map PGscen output to NyisoLoader gen_data/load_data
# ============================================================================

def _apply_scenario_to_timeseries(gen_data, load_data, scen_df, day_date,
                                   loader, cfg):
    """Override gen_data/load_data with scenario values for one day.

    Wind: per-site mapping (NYISO_real site IDs → NyisoLoader gen IDs).
    Solar: system-level ratio (only 2 generators, ~4 MW total).
    Load: per-zone scaling using zonal actual baseline.
    """
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
        # Load the zonal baseline for ratio computation
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

        # Build zone_name → [bus_names] mapping from RenewableGen.csv
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

            # Find zone letter and its buses
            zone_letter = _ZONE_NAME_TO_LETTER.get(zone_name)
            if zone_letter is None or zone_letter not in letter_to_buses:
                continue
            zone_bus_names = letter_to_buses[zone_letter]

            zone_scen_data = load_scen.xs(zone_name, level="asset_id")

            for ts in zone_scen_data.index.get_level_values("timestamp"):
                if ts not in load_data.index:
                    continue

                scen_val = zone_scen_data.loc[ts, "value_mw"]
                # Match timezone for la lookup
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

                # Scale only buses belonging to this zone
                for bus_name in zone_bus_names:
                    if ("fcst", bus_name) in load_data.columns:
                        load_data.loc[ts, ("fcst", bus_name)] *= ratio
                        load_data.loc[ts, ("actl", bus_name)] *= ratio

    gen_data = gen_data.clip(lower=0)
    load_data = load_data.clip(lower=0)

    return gen_data, load_data


# ============================================================================
# STEP 2: Deterministic baseline (NYISO day-ahead forecast)
# ============================================================================

def run_deterministic(dates, log):
    """Run Vatic on the NYISO day-ahead forecast for each day.

    If dates[0] is the warmup day, its last_conditions are passed as
    init_ruc_file to dates[1].
    """
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

def _run_single_scenario_day(args):
    """Worker function for parallel stochastic runs."""
    scen_idx, day_date, cfg_copy = args
    day_str = day_date.strftime("%Y-%m-%d")

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
    out_path = scen_out_dir / f"day_{day_str}.pkl"

    if out_path.exists():
        return (scen_idx, day_str, True, 0.0, "already exists")

    try:
        t0 = time.time()

        scen_path = (experiment_dir / cfg_copy["paths"]["scenarios_dir"]
                     / f"scenario_{scen_idx:03d}.parquet")
        scen_df = pd.read_parquet(scen_path)

        # Use warmup day's conditions if available
        det_dir = experiment_dir / cfg_copy["paths"]["deterministic_dir"]
        warmup_day = (day_date - datetime.timedelta(days=1)).isoformat()
        warmup_cond = det_dir / f"conditions_{warmup_day}.csv"
        init_state = str(warmup_cond) if warmup_cond.exists() else None

        loader, gen_data, load_data = _build_loader_and_timeseries(
            day_str, cfg_copy, init_state_file=init_state
        )

        gen_data, load_data = _apply_scenario_to_timeseries(
            gen_data, load_data, scen_df, day_date, loader, cfg_copy
        )

        results = _run_vatic_simulation(
            loader, gen_data, load_data, day_date, cfg_copy,
        )
        elapsed = time.time() - t0

        with open(out_path, "wb") as f:
            pickle.dump(results, f)

        return (scen_idx, day_str, True, elapsed, None)

    except Exception:
        elapsed = time.time() - t0
        return (scen_idx, day_str, False, elapsed, traceback.format_exc())


def run_stochastic(dates, n_scenarios, log):
    """Run Vatic for each scenario × day, parallelized across scenarios."""
    stoch_dir = EXPERIMENT_DIR / CFG["paths"]["stochastic_dir"]
    stoch_dir.mkdir(parents=True, exist_ok=True)

    max_workers = CFG["parallelism"]["max_workers"]
    if max_workers is None:
        max_workers = max(1, cpu_count() - 1)

    cfg = {**CFG, "_experiment_dir": str(EXPERIMENT_DIR)}

    # Exclude warmup day (first date) from stochastic runs
    target_dates = dates[1:]  # first date is always the warmup

    tasks = []
    for scen_idx in range(n_scenarios):
        for day_date in target_dates:
            tasks.append((scen_idx, day_date, cfg))

    total = len(tasks)
    log.info("Launching %d stochastic solves (%d scenarios × %d days) "
             "with %d workers",
             total, n_scenarios, len(target_dates), max_workers)

    completed = 0
    failed = 0
    failed_tasks = []

    t0 = time.time()

    with Pool(processes=max_workers) as pool:
        for result in pool.imap_unordered(_run_single_scenario_day, tasks):
            scen_idx, day_str, success, elapsed, err = result
            completed += 1

            if success:
                if err != "already exists":
                    log.info("  [%d/%d] scenario_%03d / %s — %.1f s",
                             completed, total, scen_idx, day_str, elapsed)
            else:
                failed += 1
                failed_tasks.append((scen_idx, day_str, err))
                log.error("  [%d/%d] FAILED scenario_%03d / %s — %.1f s\n%s",
                          completed, total, scen_idx, day_str, elapsed, err)

    wall_time = time.time() - t0
    log.info("Stochastic ensemble complete: %d/%d succeeded, %d failed. "
             "Wall time: %.0f s (%.1f min)",
             completed - failed, total, failed, wall_time, wall_time / 60)

    if failed_tasks:
        log.warning("Failed tasks:")
        for scen_idx, day_str, err in failed_tasks:
            log.warning("  scenario_%03d / %s", scen_idx, day_str)


# ============================================================================
# Main
# ============================================================================

def parse_dates(start_str, end_str):
    """Return list of datetime.date objects from start to end inclusive."""
    start = datetime.date.fromisoformat(start_str)
    end = datetime.date.fromisoformat(end_str)
    return [start + datetime.timedelta(days=i)
            for i in range((end - start).days + 1)]


def main():
    parser = argparse.ArgumentParser(
        description="Experiment 001: Stochastic vs Deterministic UC"
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
        # Smoke: warmup day + 1 target day
        warmup = CFG["dates"]["warmup_smoke"]
        target = CFG["scenarios"]["smoke_test_day"]
        dates = parse_dates(warmup, target)
        n_scenarios = CFG["scenarios"]["smoke_test_count"]
        log.info("=== SMOKE TEST: %d scenarios, %d day(s) "
                 "(warmup: %s, target: %s) ===",
                 n_scenarios, len(dates), warmup, target)
    else:
        warmup = CFG["dates"]["warmup"]
        dates = parse_dates(warmup, CFG["dates"]["end"])
        n_scenarios = CFG["scenarios"]["count"]
        log.info("=== FULL RUN: %d scenarios, %d days "
                 "(warmup: %s, target: %s to %s) ===",
                 n_scenarios, len(dates),
                 warmup, CFG["dates"]["start"], CFG["dates"]["end"])

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
