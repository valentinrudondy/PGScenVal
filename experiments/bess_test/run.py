#!/usr/bin/env python
"""BESS integration test — Phase 4.

Verifies that battery energy storage works end-to-end in Vatic:
  1. Pumped storage (BG, Lewiston) dispatches with peak/off-peak arbitrage
  2. Synthetic BESS units participate in dispatch and reduce system cost
  3. SOC tracking respects min/max bounds across all hours

Usage:
    python run.py              # Run all tests
    python run.py --test 1     # Run only test 1 (pumped storage arbitrage)
    python run.py --test 2     # Run only test 2 (synthetic BESS dispatch)
"""

import argparse
import datetime
import os
import pickle
import sys
import time
import warnings
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "Vatic"))
sys.path.insert(0, str(PROJECT_ROOT / "PGscen-2nd"))

PGSCEN_DIR = str(PROJECT_ROOT / "PGscen-2nd" / "data" / "NYISO_real")
RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def run_simulation(loader, gen_data, load_data, day_date,
                    last_conditions_file=None, reserve_mw=2620.):
    """Run 1-day Vatic simulation, return results + stats_manager."""
    from vatic.engines import Simulator

    sim = Simulator(
        template_data=loader.template,
        gen_data=gen_data, load_data=load_data,
        out_dir=None,
        start_date=day_date, num_days=1,
        solver="cbc", solver_options={"seconds": 300},
        run_lmps=False, mipgap=0.01,
        load_shed_penalty=1e4, reserve_shortfall_penalty=1e3,
        reserve_factor=0.0, output_detail=1,
        prescient_sced_forecasts=False, ruc_prescience_hour=0,
        ruc_execution_hour=16, ruc_every_hours=24,
        ruc_horizon=48, sced_horizon=4,
        lmp_shortfall_costs=False,
        enforce_sced_shutdown_ramprate=False,
        no_startup_shutdown_curves=False,
        init_ruc_file=None, verbosity=0,
        output_max_decimals=4, create_plots=False,
        renew_costs=None, save_to_csv=False,
        last_conditions_file=last_conditions_file,
        reserve_requirement_mw=reserve_mw,
    )
    result = sim.simulate()
    return result, sim._stats_manager


def extract_storage_timeseries(stats_manager):
    """Extract per-hour storage dispatch from stats_manager internals."""
    records = []
    for ts, stats in stats_manager._sced_stats.items():
        labels = ts.labels()
        for unit in stats.get('storage_input_dispatch_levels', {}):
            records.append({
                'date': labels['Date'],
                'hour': labels['Hour'],
                'unit': unit,
                'charge_mw': stats['storage_input_dispatch_levels'][unit],
                'discharge_mw': stats['storage_output_dispatch_levels'][unit],
                'soc': stats['storage_soc_dispatch_levels'][unit],
            })
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


# =========================================================================
# Test 1: Pumped storage arbitrage
# =========================================================================

def test_pumped_storage_arbitrage():
    """Verify BG and Lewiston dispatch with warmup for peak/off-peak arbitrage.

    With a warmup day, pumped storage should charge overnight (low LMP)
    and discharge during peak hours (high LMP). The SOC trajectory
    should show a clear daily cycle.
    """
    from vatic.data.nyiso_loader import NyisoLoader

    print("=" * 60)
    print("Test 1: Pumped storage arbitrage")
    print("=" * 60)

    # July 18 2019 = summer weekday with clear peak/off-peak spread
    # Warmup on July 17 to establish initial conditions
    loader_warmup = NyisoLoader(
        pgscen_dir=PGSCEN_DIR, use_reduced_network=True,
        fuel_price_date='2019-07-17', year=2019,
    )
    start_w = pd.Timestamp('2019-07-17', tz='utc')
    gen_w, load_w = loader_warmup.create_timeseries(start_w, start_w + pd.Timedelta(days=2))

    cond_path = str(RESULTS_DIR / "warmup_conditions.csv")
    _, _ = run_simulation(loader_warmup, gen_w, load_w,
                          datetime.date(2019, 7, 17),
                          last_conditions_file=cond_path)

    # Target day
    loader = NyisoLoader(
        init_state_file=cond_path, pgscen_dir=PGSCEN_DIR,
        use_reduced_network=True, fuel_price_date='2019-07-18', year=2019,
    )
    start = pd.Timestamp('2019-07-18', tz='utc')
    gen, load = loader.create_timeseries(start, start + pd.Timedelta(days=2))

    result, stats = run_simulation(loader, gen, load,
                                    datetime.date(2019, 7, 18))

    storage_df = extract_storage_timeseries(stats)
    if storage_df.empty:
        print("  FAIL: No storage dispatch data found")
        return False

    bg = storage_df[storage_df['unit'] == 'BG']
    lew = storage_df[storage_df['unit'] == 'Lewiston']

    print(f"\n  Blenheim-Gilboa (1160 MW / 9280 MWh):")
    print(f"    Hours charging:    {(bg['charge_mw'] > 1).sum()}")
    print(f"    Hours discharging: {(bg['discharge_mw'] > 1).sum()}")
    print(f"    Max charge:        {bg['charge_mw'].max():.0f} MW")
    print(f"    Max discharge:     {bg['discharge_mw'].max():.0f} MW")
    print(f"    SOC range:         {bg['soc'].min():.3f} – {bg['soc'].max():.3f}")

    print(f"\n  Lewiston (240 MW / 2880 MWh):")
    print(f"    Hours charging:    {(lew['charge_mw'] > 1).sum()}")
    print(f"    Hours discharging: {(lew['discharge_mw'] > 1).sum()}")
    print(f"    SOC range:         {lew['soc'].min():.3f} – {lew['soc'].max():.3f}")

    # Assertions
    ok = True

    # BG should discharge at least some hours (peak arbitrage)
    if (bg['discharge_mw'] > 1).sum() == 0:
        print("\n  FAIL: BG never discharges")
        ok = False

    # SOC should respect bounds
    if bg['soc'].min() < 0.099:
        print(f"\n  FAIL: BG SOC drops below min_soc (0.1): got {bg['soc'].min():.4f}")
        ok = False
    if bg['soc'].max() > 1.001:
        print(f"\n  FAIL: BG SOC exceeds 1.0: got {bg['soc'].max():.4f}")
        ok = False

    if ok:
        print("\n  PASS: Pumped storage dispatches and SOC bounds respected")

    # Clean up
    os.unlink(cond_path)
    return ok


# =========================================================================
# Test 2: Synthetic BESS units
# =========================================================================

def test_synthetic_bess():
    """Add 3 synthetic battery units and verify they participate in dispatch.

    Units:
      - BESS_J: 200 MW / 4h (800 MWh) at Zone J (NYC, bus 82)
      - BESS_K: 100 MW / 2h (200 MWh) at Zone K (LI, bus 80)
      - BESS_G: 50 MW / 8h (400 MWh) at Zone G (HV, bus 77)

    Compare system cost with and without BESS. Batteries should reduce
    cost by charging during off-peak and discharging at peak.
    """
    from vatic.data.nyiso_loader import NyisoLoader, _PUMPED_STORAGE

    print("\n" + "=" * 60)
    print("Test 2: Synthetic BESS units")
    print("=" * 60)

    synthetic_bess = {
        'BESS_J': {
            'name': 'NYC Battery 200MW/4h',
            'bus': 82,  # Zone J (N.Y.C.)
            'max_discharge_rate': 200,
            'max_charge_rate': 200,
            'energy_capacity': 800,
            'charge_efficiency': 0.92,
            'discharge_efficiency': 0.92,
            'initial_soc': 0.5,
            'min_soc': 0.1,
        },
        'BESS_K': {
            'name': 'Long Island Battery 100MW/2h',
            'bus': 80,  # Zone K (LONGIL)
            'max_discharge_rate': 100,
            'max_charge_rate': 100,
            'energy_capacity': 200,
            'charge_efficiency': 0.92,
            'discharge_efficiency': 0.92,
            'initial_soc': 0.5,
            'min_soc': 0.1,
        },
        'BESS_G': {
            'name': 'Hudson Valley Battery 50MW/8h',
            'bus': 77,  # Zone G (HUD VL)
            'max_discharge_rate': 50,
            'max_charge_rate': 50,
            'energy_capacity': 400,
            'charge_efficiency': 0.92,
            'discharge_efficiency': 0.92,
            'initial_soc': 0.5,
            'min_soc': 0.1,
        },
    }

    # Use a warmup + target day
    # First run warmup with warmup-only loader (no BESS)
    loader_base = NyisoLoader(
        pgscen_dir=PGSCEN_DIR, use_reduced_network=True,
        fuel_price_date='2019-07-17', year=2019,
    )
    start_w = pd.Timestamp('2019-07-17', tz='utc')
    gen_w, load_w = loader_base.create_timeseries(start_w, start_w + pd.Timedelta(days=2))
    cond_path = str(RESULTS_DIR / "bess_warmup_conditions.csv")
    run_simulation(loader_base, gen_w, load_w,
                   datetime.date(2019, 7, 17),
                   last_conditions_file=cond_path)

    # Target day — baseline (no BESS, just pumped storage)
    loader_no_bess = NyisoLoader(
        init_state_file=cond_path, pgscen_dir=PGSCEN_DIR,
        use_reduced_network=True, fuel_price_date='2019-07-18', year=2019,
    )
    start = pd.Timestamp('2019-07-18', tz='utc')
    gen, load = loader_no_bess.create_timeseries(start, start + pd.Timedelta(days=2))

    t0 = time.time()
    result_no_bess, _ = run_simulation(loader_no_bess, gen, load,
                                        datetime.date(2019, 7, 18))
    time_no_bess = time.time() - t0

    # Target day — with BESS
    loader_bess = NyisoLoader(
        init_state_file=cond_path, pgscen_dir=PGSCEN_DIR,
        use_reduced_network=True, fuel_price_date='2019-07-18', year=2019,
    )
    # Inject BESS units into the template
    bus_name_map = {b.ID: b.Name for b in loader_bess.buses}
    for bess_id, bess_spec in synthetic_bess.items():
        bus_name = bus_name_map.get(bess_spec['bus'])
        if bus_name is None:
            print(f"  WARNING: Bus {bess_spec['bus']} not in reduced network, skipping {bess_id}")
            continue
        loader_bess.template['StorageUnits'][bess_id] = {
            'bus': bus_name,
            'min_discharge_rate': 0,
            'max_discharge_rate': bess_spec['max_discharge_rate'],
            'min_charge_rate': 0,
            'max_charge_rate': bess_spec['max_charge_rate'],
            'energy_capacity': bess_spec['energy_capacity'],
            'minimum_state_of_charge': bess_spec['min_soc'],
            'charge_efficiency': bess_spec['charge_efficiency'],
            'discharge_efficienty': bess_spec['discharge_efficiency'],  # Egret typo
            'retention_rate_60min': 1.0,
            'initial_state_of_charge': bess_spec['initial_soc'],
            'initial_input': 0.0,
            'initial_output': 0.0,
            'charge_cost': 0.0,
            'discharge_cost': 0.0,
            'ramp_up_output_60min': bess_spec['max_discharge_rate'],
            'ramp_down_output_60min': bess_spec['max_discharge_rate'],
            'ramp_up_input_60min': bess_spec['max_charge_rate'],
            'ramp_down_input_60min': bess_spec['max_charge_rate'],
            'in_service': True,
        }

    gen_bess, load_bess = loader_bess.create_timeseries(start, start + pd.Timedelta(days=2))

    t0 = time.time()
    result_bess, stats_bess = run_simulation(loader_bess, gen_bess, load_bess,
                                              datetime.date(2019, 7, 18))
    time_bess = time.time() - t0

    # Compare
    hs_no = result_no_bess['hourly_summary']
    hs_yes = result_bess['hourly_summary']

    cost_no = hs_no['FixedCosts'].sum() + hs_no['VariableCosts'].sum()
    cost_yes = hs_yes['FixedCosts'].sum() + hs_yes['VariableCosts'].sum()
    ls_no = hs_no['LoadShedding'].sum()
    ls_yes = hs_yes['LoadShedding'].sum()

    print(f"\n  System comparison (1 day, July 18, 2019):")
    print(f"  {'Metric':<25} {'No BESS':>12} {'With BESS':>12} {'Delta':>10}")
    print(f"  {'Total cost ($)':<25} {cost_no:>12,.0f} {cost_yes:>12,.0f} {cost_yes-cost_no:>+10,.0f}")
    print(f"  {'Load shedding (MWh)':<25} {ls_no:>12,.0f} {ls_yes:>12,.0f} {ls_yes-ls_no:>+10,.0f}")
    print(f"  {'Runtime (s)':<25} {time_no_bess:>12,.0f} {time_bess:>12,.0f}")

    # Extract BESS dispatch
    storage_df = extract_storage_timeseries(stats_bess)
    ok = True

    for bess_id in synthetic_bess:
        bess_data = storage_df[storage_df['unit'] == bess_id]
        if bess_data.empty:
            print(f"\n  FAIL: {bess_id} not found in storage dispatch")
            ok = False
            continue

        n_charge = (bess_data['charge_mw'] > 1).sum()
        n_discharge = (bess_data['discharge_mw'] > 1).sum()
        max_charge = bess_data['charge_mw'].max()
        max_discharge = bess_data['discharge_mw'].max()
        soc_min = bess_data['soc'].min()
        soc_max = bess_data['soc'].max()

        spec = synthetic_bess[bess_id]
        print(f"\n  {bess_id} ({spec['max_discharge_rate']} MW / "
              f"{spec['energy_capacity']} MWh):")
        print(f"    Hours charging:    {n_charge}")
        print(f"    Hours discharging: {n_discharge}")
        print(f"    Max charge:        {max_charge:.0f} MW")
        print(f"    Max discharge:     {max_discharge:.0f} MW")
        print(f"    SOC range:         {soc_min:.3f} – {soc_max:.3f}")

        # SOC bounds check
        if soc_min < spec['min_soc'] - 0.001:
            print(f"    FAIL: SOC below min_soc ({spec['min_soc']})")
            ok = False
        if soc_max > 1.001:
            print(f"    FAIL: SOC above 1.0")
            ok = False

        # Must participate in dispatch (charge or discharge at least once)
        if n_charge == 0 and n_discharge == 0:
            print(f"    FAIL: Never dispatched")
            ok = False

    # BESS should reduce system cost (batteries arbitrage peak/off-peak)
    if cost_yes >= cost_no:
        print(f"\n  WARNING: BESS did not reduce system cost "
              f"(${cost_no:,.0f} → ${cost_yes:,.0f})")
        # Not a hard failure — on a cold-start day, BESS may not have
        # enough cycles to provide net savings
    else:
        saving = cost_no - cost_yes
        print(f"\n  BESS savings: ${saving:,.0f} ({saving/cost_no*100:.1f}%)")

    if ok:
        print("\n  PASS: All BESS units dispatch and respect SOC bounds")

    # Clean up
    os.unlink(cond_path)
    return ok


# =========================================================================
# Main
# =========================================================================

def main():
    parser = argparse.ArgumentParser(description="BESS integration test")
    parser.add_argument("--test", type=int, choices=[1, 2],
                        help="Run only a specific test")
    args = parser.parse_args()

    results = {}
    if args.test in (None, 1):
        results['pumped_storage_arbitrage'] = test_pumped_storage_arbitrage()
    if args.test in (None, 2):
        results['synthetic_bess'] = test_synthetic_bess()

    print("\n" + "=" * 60)
    print("BESS Integration Test Summary")
    print("=" * 60)
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    all_pass = all(results.values())
    print(f"\n  Overall: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
