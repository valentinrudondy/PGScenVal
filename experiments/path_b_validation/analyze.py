#!/usr/bin/env python3
"""Path B validation analysis — compare model LMPs to NYISO actuals.

Reads simulation results from cross_year_validation and compares
zonal-average LMPs to NYISO day-ahead zonal LBMPs.
"""

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / 'experiments' / 'cross_year_validation' / 'results' / 'warmup'
V1_DIR = ROOT / 'experiments' / 'cross_year_validation' / 'results' / 'warmup_v1_backup'
NYISO_CACHE = ROOT / 'data' / 'nyiso_cache'

# Bus name -> zone mapping
import json
BUS_ZONE = {}
with open(ROOT / 'third_party' / 'NYgrid' / 'nygrid_baseline.json') as f:
    for b in json.load(f)['bus']:
        if b['zone'] != 'EXT':
            BUS_ZONE[b['name'].strip()] = b['zone']

ZONE_TO_NYISO = {
    'A': 'WEST', 'B': 'GENESE', 'C': 'CENTRL', 'D': 'NORTH',
    'E': 'MHK VL', 'F': 'CAPITL', 'G': 'HUD VL', 'H': 'MILLWD',
    'I': 'DUNWOD', 'J': 'N.Y.C.', 'K': 'LONGIL',
}

YEAR_DATES = {
    2020: ['2020-09-22', '2020-09-23', '2020-09-24'],
    2022: ['2022-09-20', '2022-09-21', '2022-09-22'],
    2023: ['2023-09-19', '2023-09-20', '2023-09-21'],
}


def load_nyiso_zonal(year, dates):
    """Load NYISO zonal DA LMP for specific dates."""
    month = f"{dates[0][5:7]}"
    dfs = []
    for d in dates:
        p = NYISO_CACHE / str(year) / 'da_lbmp' / f'{year}{month}' / f'{d.replace("-","")}damlbmp_zone.csv'
        if p.exists():
            dfs.append(pd.read_csv(p))
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def analyze_year(year, dates, results_dir, label=""):
    """Analyze model vs NYISO LMPs for one year."""
    pkl = results_dir / f'det_{year}.pkl'
    if not pkl.exists():
        print(f"  {label} {year}: no results found")
        return None

    with open(pkl, 'rb') as f:
        data = pickle.load(f)

    bus_detail = data['bus_detail']
    hs = data['hourly_summary']

    # Compute zone-average model LMPs
    bus_detail_reset = bus_detail.reset_index()
    bus_detail_reset['Zone'] = bus_detail_reset['Bus'].str.strip().map(BUS_ZONE)

    model_zonal = bus_detail_reset.groupby(['Date', 'Hour', 'Zone'])['LMP'].mean()
    model_zonal = model_zonal.reset_index()

    # Load NYISO zonal
    nyiso = load_nyiso_zonal(year, dates)
    if nyiso.empty:
        print(f"  {label} {year}: no NYISO data")
        return None

    # Compute NYISO system average
    nyiso_zones = nyiso[nyiso['Name'].isin(ZONE_TO_NYISO.values())]
    nyiso_sys_avg = nyiso_zones.groupby('Time Stamp')['LBMP ($/MWHr)'].mean()

    # Model system average
    model_sys_avg = bus_detail['LMP'].groupby(['Date', 'Hour']).mean()

    # Per-zone comparison
    zone_results = {}
    for zone_letter, nyiso_name in ZONE_TO_NYISO.items():
        model_z = model_zonal[model_zonal['Zone'] == zone_letter]['LMP']
        nyiso_z = nyiso[nyiso['Name'] == nyiso_name]['LBMP ($/MWHr)']
        if len(model_z) > 0 and len(nyiso_z) > 0:
            zone_results[zone_letter] = {
                'model_avg': model_z.mean(),
                'nyiso_avg': nyiso_z.mean(),
                'bias': model_z.mean() - nyiso_z.mean(),
            }

    # System-wide averages
    model_avg = bus_detail['LMP'].mean()
    nyiso_avg = nyiso_zones['LBMP ($/MWHr)'].mean()
    deviation_pct = (model_avg - nyiso_avg) / nyiso_avg * 100

    # Import dispatch analysis
    thermal = data.get('thermal_detail')
    import_stats = {}
    if thermal is not None:
        thermal_reset = thermal.reset_index()
        imports = thermal_reset[thermal_reset['Generator'].str.contains('import', case=False)]
        if not imports.empty:
            for name in ['PJM', 'HQ', 'NE', 'IESO']:
                imp = imports[imports['Generator'].str.contains(name)]
                if not imp.empty:
                    total_mw = imp.groupby(['Date', 'Hour'])['Dispatch'].sum()
                    import_stats[name] = {
                        'avg_dispatch': total_mw.mean(),
                        'pct_at_max': 0,  # would need Pmax to compute
                    }

    result = {
        'model_avg': model_avg,
        'nyiso_avg': nyiso_avg,
        'deviation_pct': deviation_pct,
        'bias': model_avg - nyiso_avg,
        'total_cost': hs['FixedCosts'].sum() + hs['VariableCosts'].sum(),
        'load_shed': hs['LoadShedding'].sum(),
        'reserve_shortfall': hs['ReserveShortfall'].sum(),
        'zone_results': zone_results,
        'import_stats': import_stats,
    }
    return result


def main():
    print("=" * 70)
    print("  Path B Cross-Year Validation Analysis")
    print("=" * 70)

    # Analyze both v1 and Path B results
    for year, dates in sorted(YEAR_DATES.items()):
        print(f"\n{'='*60}")
        print(f"  Year {year}")
        print(f"{'='*60}")

        v1 = analyze_year(year, dates, V1_DIR, "v1")
        pb = analyze_year(year, dates, RESULTS_DIR, "PathB")

        if v1:
            print(f"\n  v1 (static costs):")
            print(f"    Model avg LMP: ${v1['model_avg']:.2f}")
            print(f"    NYISO avg LMP: ${v1['nyiso_avg']:.2f}")
            print(f"    Deviation: {v1['deviation_pct']:+.1f}%")
            print(f"    Load shedding: {v1['load_shed']:.0f} MWh")

        if pb:
            print(f"\n  Path B (year-specific costs):")
            print(f"    Model avg LMP: ${pb['model_avg']:.2f}")
            print(f"    NYISO avg LMP: ${pb['nyiso_avg']:.2f}")
            print(f"    Deviation: {pb['deviation_pct']:+.1f}%")
            print(f"    Load shedding: {pb['load_shed']:.0f} MWh")

        if v1 and pb:
            print(f"\n  Improvement:")
            print(f"    Deviation: {v1['deviation_pct']:+.1f}% → {pb['deviation_pct']:+.1f}%")
            delta = abs(pb['deviation_pct']) - abs(v1['deviation_pct'])
            print(f"    Change: {delta:+.1f} pp {'(improved)' if delta < 0 else '(regressed)'}")

            print(f"\n  Per-zone bias (Path B):")
            for zone in sorted(pb['zone_results']):
                z = pb['zone_results'][zone]
                v1z = v1['zone_results'].get(zone, {})
                v1_bias = v1z.get('bias', float('nan'))
                print(f"    Zone {zone} ({ZONE_TO_NYISO[zone]:<8}): "
                      f"bias ${z['bias']:+.1f} "
                      f"(was ${v1_bias:+.1f})")

    print(f"\n{'='*70}")
    print("  DONE")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
