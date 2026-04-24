#!/usr/bin/env python
"""Check 3: BESS cycling on a high-stress 2022 summer window.

2022 has $9.10/MMBTU gas → LMPs should swing $30 overnight to $100+ peak.
Batteries should show clear charge/discharge cycling.
"""
import sys, datetime, os
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent / 'Vatic'))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent / 'PGscen-2nd'))

import pandas as pd, numpy as np
from vatic.data.nyiso_loader import NyisoLoader
from vatic.engines import Simulator

PGSCEN = str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent
             / 'PGscen-2nd' / 'data' / 'NYISO_real')

def run_day(loader, gen, load, day, cond_out, reserve_mw=2620.):
    sim = Simulator(
        template_data=loader.template, gen_data=gen, load_data=load,
        out_dir=None, start_date=day, num_days=1,
        solver='cbc', solver_options={'seconds': 300}, run_lmps=False,
        mipgap=0.01, load_shed_penalty=1e4, reserve_shortfall_penalty=1e3,
        reserve_factor=0.0, output_detail=1, prescient_sced_forecasts=False,
        ruc_prescience_hour=0, ruc_execution_hour=16, ruc_every_hours=24,
        ruc_horizon=48, sced_horizon=4, lmp_shortfall_costs=False,
        enforce_sced_shutdown_ramprate=False, no_startup_shutdown_curves=False,
        init_ruc_file=None, verbosity=0, output_max_decimals=4,
        create_plots=False, renew_costs=None, save_to_csv=False,
        last_conditions_file=cond_out, reserve_requirement_mw=reserve_mw,
    )
    return sim.simulate(), sim._stats_manager

# Inject BESS into template
def add_bess(loader):
    bus_map = {b.ID: b.Name for b in loader.buses}
    for bess_id, spec in {
        'BESS_J': {'bus': 82, 'mw': 200, 'mwh': 800},
        'BESS_K': {'bus': 80, 'mw': 100, 'mwh': 200},
        'BESS_G': {'bus': 77, 'mw': 50, 'mwh': 400},
    }.items():
        bus_name = bus_map.get(spec['bus'])
        if not bus_name:
            continue
        loader.template['StorageUnits'][bess_id] = {
            'bus': bus_name,
            'min_discharge_rate': 0, 'max_discharge_rate': spec['mw'],
            'min_charge_rate': 0, 'max_charge_rate': spec['mw'],
            'energy_capacity': spec['mwh'],
            'minimum_state_of_charge': 0.1,
            'charge_efficiency': 0.92,
            'discharge_efficienty': 0.92,  # Egret typo
            'retention_rate_60min': 1.0,
            'initial_state_of_charge': 0.5,
            'initial_input': 0.0, 'initial_output': 0.0,
            'charge_cost': 0.0, 'discharge_cost': 0.0,
            'ramp_up_output_60min': spec['mw'],
            'ramp_down_output_60min': spec['mw'],
            'ramp_up_input_60min': spec['mw'],
            'ramp_down_input_60min': spec['mw'],
            'in_service': True,
        }

print("="*70)
print("CHECK 3: 2022 Summer Peak — BESS Cycling Test")
print("  Window: July 19 (warmup) → July 20-22 (target)")
print("="*70)

# Warmup
loader_w = NyisoLoader(pgscen_dir=PGSCEN, use_reduced_network=True, year=2022)
add_bess(loader_w)
start_w = pd.Timestamp('2022-07-19', tz='utc')
gen_w, load_w = loader_w.create_timeseries(start_w, start_w + pd.Timedelta(days=2))
cond = '/tmp/bess_2022_warmup.csv'
run_day(loader_w, gen_w, load_w, datetime.date(2022, 7, 19), cond)
print("  Warmup done")

# 3 target days
all_soc = []
all_prices = []
prev_cond = cond

for day_offset in range(3):
    day = datetime.date(2022, 7, 20) + datetime.timedelta(days=day_offset)
    day_str = day.isoformat()
    print(f"  Running {day_str}...")

    loader = NyisoLoader(
        init_state_file=prev_cond, pgscen_dir=PGSCEN,
        use_reduced_network=True, year=2022)
    add_bess(loader)
    start = pd.Timestamp(day_str, tz='utc')
    gen, load = loader.create_timeseries(start, start + pd.Timedelta(days=2))

    next_cond = f'/tmp/bess_2022_{day_str}.csv'
    result, stats = run_day(loader, gen, load, day, next_cond)

    for ts, s in stats._sced_stats.items():
        labels = ts.labels()
        hour_idx = day_offset * 24 + int(labels['Hour'])
        all_prices.append({'hour': hour_idx, 'date': labels['Date'],
                          'h': int(labels['Hour']), 'price': s.get('price', 0)})
        for unit in s.get('storage_soc_dispatch_levels', {}):
            all_soc.append({
                'hour': hour_idx, 'unit': unit,
                'soc': s['storage_soc_dispatch_levels'][unit],
                'charge': s['storage_input_dispatch_levels'][unit],
                'discharge': s['storage_output_dispatch_levels'][unit],
            })
    prev_cond = next_cond

soc_df = pd.DataFrame(all_soc)
price_df = pd.DataFrame(all_prices)

print("\n" + "="*70)
print("RESULTS")
print("="*70)

# Price analysis
print("\nHourly system price:")
for _, row in price_df.iterrows():
    print(f"  H{row['hour']:02d} ({row['date']} {row['h']:02d}UTC): ${row['price']:.2f}")

for day_off in range(3):
    dp = price_df[(price_df['hour'] >= day_off*24) & (price_df['hour'] < (day_off+1)*24)]
    peak, trough = dp['price'].max(), dp['price'].min()
    spread = peak - trough
    profit = peak - trough / 0.85
    print(f"\n  Day {day_off+1}: peak=${peak:.2f}, trough=${trough:.2f}, "
          f"spread=${spread:.2f}, arb profit=${profit:.2f}/MWh")

# SOC trajectories
for unit in ['BG', 'BESS_J', 'BESS_G']:
    u = soc_df[soc_df['unit'] == unit].sort_values('hour')
    if u.empty:
        continue
    print(f"\n{unit} SOC trajectory:")
    for _, row in u.iterrows():
        bar = '#' * int(row['soc'] * 40)
        mode = 'CHG' if row['charge'] > 1 else ('DIS' if row['discharge'] > 1 else '   ')
        print(f"  H{row['hour']:02d}: SOC={row['soc']:.3f} {mode} "
              f"{row['charge']:>6.0f}/{row['discharge']:>6.0f}  |{bar}")
    n_c = (u['charge'] > 1).sum()
    n_d = (u['discharge'] > 1).sum()
    print(f"  Charging hours: {n_c}, Discharging hours: {n_d}")

# Cleanup
for f in [cond] + [f'/tmp/bess_2022_{datetime.date(2022,7,20)+datetime.timedelta(days=i)}.csv' for i in range(3)]:
    if os.path.exists(f): os.unlink(f)
