#!/usr/bin/env python
"""Generate result plots for Experiment 002."""

import pickle
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

plt.rcParams.update({
    'figure.dpi': 150,
    'font.size': 10,
    'axes.titlesize': 12,
    'axes.labelsize': 11,
})

EXPERIMENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "Vatic"))

# Paths to actual NYISO data
ACTUAL_LMP_PATH = PROJECT_ROOT / 'third_party' / 'NYgrid' / 'Data' / 'priceHourly_2019.csv'
ACTUAL_LOAD_PATH = (PROJECT_ROOT / 'PGscen-2nd' / 'data' / 'NYISO_real' /
                    'load_actual_1h_zone_2018_2019_2020_2021_2022_2023_2024_2025_utc.csv')
NYISO_LOAD_ZONES = ['CAPITL', 'CENTRL', 'DUNWOD', 'GENESE', 'HUD VL',
                    'LONGIL', 'MHK VL', 'MILLWD', 'N.Y.C.', 'NORTH', 'WEST']

TARGET_DATES = [
    '2019-07-15', '2019-07-16', '2019-07-17', '2019-07-18',
    '2019-07-19', '2019-07-20', '2019-07-21',
]
N_SCENARIOS = 100
FIG_DIR = EXPERIMENT_DIR / 'results' / 'figures'
FIG_DIR.mkdir(parents=True, exist_ok=True)

DET_DIR = EXPERIMENT_DIR / 'results' / 'deterministic'
STOCH_DIR = EXPERIMENT_DIR / 'results' / 'stochastic'


def load_results():
    """Load all deterministic and stochastic results."""
    det = {}
    for d in TARGET_DATES:
        with open(DET_DIR / f'day_{d}.pkl', 'rb') as f:
            det[d] = pickle.load(f)

    stoch = {}
    for i in range(N_SCENARIOS):
        scen = {}
        for d in TARGET_DATES:
            with open(STOCH_DIR / f'scenario_{i:03d}/day_{d}.pkl', 'rb') as f:
                scen[d] = pickle.load(f)
        stoch[i] = scen

    return det, stoch


def daily_cost(results):
    hs = results['hourly_summary']
    return hs['FixedCosts'].sum() + hs['VariableCosts'].sum()


def plot_cost_histogram(det, stoch):
    """Cost histogram: deterministic vs stochastic distribution."""
    det_total = sum(daily_cost(r) for r in det.values())
    stoch_totals = [
        sum(daily_cost(r) for r in stoch[i].values())
        for i in range(N_SCENARIOS)
    ]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(np.array(stoch_totals) / 1e6, bins=25, color='steelblue',
            alpha=0.8, edgecolor='white', label='Stochastic scenarios')
    ax.axvline(det_total / 1e6, color='crimson', linewidth=2.5,
               linestyle='--', label=f'Deterministic (${det_total/1e6:.1f}M)')
    ax.axvline(np.mean(stoch_totals) / 1e6, color='navy', linewidth=2,
               linestyle=':', label=f'Stochastic mean (${np.mean(stoch_totals)/1e6:.1f}M)')

    ax.set_xlabel('7-Day Total Production Cost ($M)')
    ax.set_ylabel('Number of Scenarios')
    ax.set_title('v2 Cost Distribution: Deterministic vs. 100 Stochastic Scenarios\n'
                 f'CV = {np.std(stoch_totals, ddof=1)/np.mean(stoch_totals)*100:.2f}%, '
                 f'Cost of Uncertainty = {(np.mean(stoch_totals)-det_total)/det_total*100:+.2f}%')
    ax.legend(fontsize=10)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter('$%.1fM'))

    fig.tight_layout()
    fig.savefig(FIG_DIR / 'cost_histogram.png')
    plt.close(fig)
    print('Saved cost_histogram.png')


def _load_actual_lmps():
    """Load actual NYISO zonal LMPs and compute system-average hourly LMP in UTC."""
    df = pd.read_csv(ACTUAL_LMP_PATH)
    # Filter to NYISO load zones only (exclude H Q, NPX, O H, PJM)
    df = df[df['ZoneName'].isin(NYISO_LOAD_ZONES)].copy()
    # Parse local ET timestamps and convert to UTC (EDT = UTC-4 in July)
    df['ts_local'] = pd.to_datetime(df['TimeStamp'])
    df['ts_utc'] = df['ts_local'] + pd.Timedelta(hours=4)
    # System-average LMP = mean across 11 zones for each hour
    hourly = df.groupby('ts_utc')['LBMP'].mean().sort_index()
    return hourly


def _load_actual_load():
    """Load actual NYISO zonal load (already UTC) and compute system total."""
    df = pd.read_csv(ACTUAL_LOAD_PATH, parse_dates=['Time'])
    df['ts_utc'] = pd.to_datetime(df['Time'], utc=True).dt.tz_localize(None)
    df = df.set_index('ts_utc')
    system_load = df[NYISO_LOAD_ZONES].sum(axis=1).sort_index()
    return system_load


def plot_lmp_fan_chart(det, stoch):
    """LMP fan chart with percentile bands and NYISO actual overlay."""
    # Extract hourly LMPs (system average = Price column)
    det_lmps = []
    for d in TARGET_DATES:
        hs = det[d]['hourly_summary']
        det_lmps.extend(hs['Price'].values)
    det_lmps = np.array(det_lmps)

    stoch_lmps = np.zeros((N_SCENARIOS, len(det_lmps)))
    for i in range(N_SCENARIOS):
        idx = 0
        for d in TARGET_DATES:
            hs = stoch[i][d]['hourly_summary']
            n = len(hs['Price'])
            stoch_lmps[i, idx:idx+n] = hs['Price'].values
            idx += n

    # Load actual NYISO LMPs
    actual_lmps_series = _load_actual_lmps()
    actual_lmps = []
    for d in TARGET_DATES:
        for h in range(24):
            ts = pd.Timestamp(f'{d} {h:02d}:00:00')
            if ts in actual_lmps_series.index:
                actual_lmps.append(actual_lmps_series[ts])
            else:
                actual_lmps.append(np.nan)
    actual_lmps = np.array(actual_lmps)

    hours = np.arange(len(det_lmps))

    fig, ax = plt.subplots(figsize=(14, 6))

    # Percentile bands
    p5 = np.percentile(stoch_lmps, 5, axis=0)
    p25 = np.percentile(stoch_lmps, 25, axis=0)
    p50 = np.percentile(stoch_lmps, 50, axis=0)
    p75 = np.percentile(stoch_lmps, 75, axis=0)
    p95 = np.percentile(stoch_lmps, 95, axis=0)

    ax.fill_between(hours, p5, p95, alpha=0.15, color='steelblue', label='P5-P95')
    ax.fill_between(hours, p25, p75, alpha=0.3, color='steelblue', label='P25-P75')
    ax.plot(hours, p50, color='navy', linewidth=1.5, label='Stochastic median')
    ax.plot(hours, det_lmps, color='crimson', linewidth=1.5, linestyle='--',
            label='Deterministic', alpha=0.8)
    ax.plot(hours, actual_lmps, color='limegreen', linewidth=2, label='NYISO actual',
            zorder=5)

    # Day boundaries
    for i in range(1, 7):
        ax.axvline(i * 24, color='gray', linewidth=0.5, alpha=0.5)

    # Day labels
    day_labels = ['Jul 15\nTue', 'Jul 16\nWed', 'Jul 17\nThu',
                  'Jul 18\nFri', 'Jul 19\nSat', 'Jul 20\nSun', 'Jul 21\nMon']
    for i, lbl in enumerate(day_labels):
        ax.text(i * 24 + 12, ax.get_ylim()[0], lbl, ha='center', va='bottom',
                fontsize=8, alpha=0.7)

    ax.set_xlabel('Hour of Week')
    ax.set_ylabel('System LMP ($/MWh)')
    ax.set_title('v2 LMP Fan Chart — July 15-21, 2019\n'
                 '100 PGscen scenarios vs. NYISO actual DA LMP')
    ax.legend(loc='upper right', fontsize=9)
    ax.set_xlim(0, len(det_lmps))

    fig.tight_layout()
    fig.savefig(FIG_DIR / 'lmp_fan_chart.png')
    plt.close(fig)
    print('Saved lmp_fan_chart.png')


def plot_commitment_heatmap(det):
    """Commitment heatmap for deterministic baseline across the week."""
    # daily_commits is indexed by (Date, Hour, Generator) with (Commit, period) cols
    # Extract unit state from thermal_detail instead — cleaner
    gen_hours = {}  # gen_name -> list of 0/1 across 7 days × 24 hours

    for d in TARGET_DATES:
        td = det[d]['thermal_detail']
        # td is indexed by (Date, Hour, Generator), columns: Dispatch, Headroom, Unit State, Unit Cost
        for gen in td.index.get_level_values('Generator').unique():
            if gen not in gen_hours:
                gen_hours[gen] = []
            gen_data = td.xs(gen, level='Generator')
            for h in range(24):
                if h in gen_data.index.get_level_values('Hour'):
                    state = gen_data.xs(h, level='Hour')['Unit State'].values[0]
                    gen_hours[gen].append(1 if state > 0 else 0)
                else:
                    gen_hours[gen].append(0)

    gen_names = sorted(gen_hours.keys())
    full_commits = np.array([gen_hours[g] for g in gen_names])

    # Sort by total hours committed
    total_on = full_commits.sum(axis=1)
    sort_idx = np.argsort(-total_on)

    # Filter: on at least once but not always
    n_hours = full_commits.shape[1]
    always_on = total_on >= n_hours - 1
    never_on = total_on <= 1
    interesting = ~always_on & ~never_on
    interesting_idx = sort_idx[interesting[sort_idx]]

    if len(interesting_idx) > 60:
        interesting_idx = interesting_idx[:60]

    fig, ax = plt.subplots(figsize=(14, max(8, len(interesting_idx) * 0.15)))

    data = full_commits[interesting_idx, :]
    names = [gen_names[i] for i in interesting_idx]
    short_names = [n.replace('NYISO_', '').replace('_import', ' Imp') for n in names]

    ax.imshow(data, aspect='auto', cmap='YlOrRd', interpolation='nearest',
              vmin=0, vmax=1)

    ax.set_yticks(range(len(short_names)))
    ax.set_yticklabels(short_names, fontsize=6)

    for i in range(1, 7):
        ax.axvline(i * 24 - 0.5, color='black', linewidth=0.8)

    day_labels = ['Jul 15', 'Jul 16', 'Jul 17', 'Jul 18',
                  'Jul 19', 'Jul 20', 'Jul 21']
    for i, lbl in enumerate(day_labels):
        ax.text(i * 24 + 12, -1.5, lbl, ha='center', fontsize=8)

    ax.set_xlabel('Hour of Week')
    ax.set_title('Deterministic Commitment Heatmap — July 15-21, 2019\n'
                 '(generators that cycle on/off; always-on and never-on excluded)')

    fig.tight_layout()
    fig.savefig(FIG_DIR / 'commitment_heatmap.png')
    plt.close(fig)
    print('Saved commitment_heatmap.png')


def plot_daily_cost_spread(det, stoch):
    """Box plot of daily costs across scenarios vs deterministic."""
    fig, ax = plt.subplots(figsize=(12, 6))

    daily_stoch = []
    daily_det = []
    labels = []
    for d in TARGET_DATES:
        costs = [daily_cost(stoch[i][d]) / 1e6 for i in range(N_SCENARIOS)]
        daily_stoch.append(costs)
        daily_det.append(daily_cost(det[d]) / 1e6)
        labels.append(d[5:])  # MM-DD

    positions = np.arange(len(TARGET_DATES))
    bp = ax.boxplot(daily_stoch, positions=positions, widths=0.5,
                    patch_artist=True, showfliers=True,
                    flierprops=dict(marker='.', markersize=3, alpha=0.5))

    for patch in bp['boxes']:
        patch.set_facecolor('steelblue')
        patch.set_alpha(0.6)

    ax.scatter(positions, daily_det, color='crimson', marker='D', s=80,
               zorder=5, label='Deterministic')

    ax.set_xticks(positions)
    ax.set_xticklabels(labels)
    ax.set_xlabel('Date (2019)')
    ax.set_ylabel('Daily Production Cost ($M)')
    ax.set_title('v2 Daily Cost Spread: 100 Scenarios vs. Deterministic')
    ax.legend(fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('$%.1fM'))

    fig.tight_layout()
    fig.savefig(FIG_DIR / 'daily_cost_boxplot.png')
    plt.close(fig)
    print('Saved daily_cost_boxplot.png')


def plot_reserve_shortfall(det, stoch):
    """Hourly reserve shortfall across the week."""
    det_rsf = []
    for d in TARGET_DATES:
        hs = det[d]['hourly_summary']
        det_rsf.extend(hs['ReserveShortfall'].values)
    det_rsf = np.array(det_rsf)

    stoch_rsf = np.zeros((N_SCENARIOS, len(det_rsf)))
    for i in range(N_SCENARIOS):
        idx = 0
        for d in TARGET_DATES:
            hs = stoch[i][d]['hourly_summary']
            n = len(hs['ReserveShortfall'])
            stoch_rsf[i, idx:idx+n] = hs['ReserveShortfall'].values
            idx += n

    hours = np.arange(len(det_rsf))

    fig, ax = plt.subplots(figsize=(14, 5))

    p5 = np.percentile(stoch_rsf, 5, axis=0)
    p50 = np.percentile(stoch_rsf, 50, axis=0)
    p95 = np.percentile(stoch_rsf, 95, axis=0)

    ax.fill_between(hours, p5, p95, alpha=0.2, color='orange', label='P5-P95')
    ax.plot(hours, p50, color='darkorange', linewidth=1.5, label='Stochastic median')
    ax.plot(hours, det_rsf, color='crimson', linewidth=1.5, linestyle='--',
            label='Deterministic')

    for i in range(1, 7):
        ax.axvline(i * 24, color='gray', linewidth=0.5, alpha=0.5)

    ax.set_xlabel('Hour of Week')
    ax.set_ylabel('Reserve Shortfall (MW)')
    ax.set_title('Reserve Shortfall — 2,620 MW Fixed Requirement\n'
                 'Shortfall indicates binding reserve constraint (soft penalty $1k/MWh)')
    ax.legend(fontsize=9)
    ax.set_xlim(0, len(det_rsf))

    fig.tight_layout()
    fig.savefig(FIG_DIR / 'reserve_shortfall.png')
    plt.close(fig)
    print('Saved reserve_shortfall.png')


def plot_demand_profile(det, stoch):
    """System demand across the week with scenario spread and NYISO actual."""
    det_demand = []
    for d in TARGET_DATES:
        hs = det[d]['hourly_summary']
        det_demand.extend(hs['Demand'].values)
    det_demand = np.array(det_demand)

    stoch_demand = np.zeros((N_SCENARIOS, len(det_demand)))
    for i in range(N_SCENARIOS):
        idx = 0
        for d in TARGET_DATES:
            hs = stoch[i][d]['hourly_summary']
            n = len(hs['Demand'])
            stoch_demand[i, idx:idx+n] = hs['Demand'].values
            idx += n

    # Load actual NYISO system load
    actual_load_series = _load_actual_load()
    actual_demand = []
    for d in TARGET_DATES:
        for h in range(24):
            ts = pd.Timestamp(f'{d} {h:02d}:00:00')
            if ts in actual_load_series.index:
                actual_demand.append(actual_load_series[ts])
            else:
                actual_demand.append(np.nan)
    actual_demand = np.array(actual_demand)

    hours = np.arange(len(det_demand))

    fig, ax = plt.subplots(figsize=(14, 5))

    p5 = np.percentile(stoch_demand, 5, axis=0)
    p25 = np.percentile(stoch_demand, 25, axis=0)
    p75 = np.percentile(stoch_demand, 75, axis=0)
    p95 = np.percentile(stoch_demand, 95, axis=0)
    p50 = np.percentile(stoch_demand, 50, axis=0)

    ax.fill_between(hours, p5/1e3, p95/1e3, alpha=0.15, color='steelblue', label='P5-P95')
    ax.fill_between(hours, p25/1e3, p75/1e3, alpha=0.3, color='steelblue', label='P25-P75')
    ax.plot(hours, p50/1e3, color='navy', linewidth=1.5, label='Stochastic median')
    ax.plot(hours, det_demand/1e3, color='crimson', linewidth=1.5, linestyle='--',
            label='Deterministic (DA forecast)', alpha=0.8)
    ax.plot(hours, actual_demand/1e3, color='limegreen', linewidth=2,
            label='NYISO actual', zorder=5)

    for i in range(1, 7):
        ax.axvline(i * 24, color='gray', linewidth=0.5, alpha=0.5)

    ax.set_xlabel('Hour of Week')
    ax.set_ylabel('System Demand (GW)')
    ax.set_title('System Demand — July 15-21, 2019 Heat Wave\n'
                 'Model scenarios vs. NYISO actual load')
    ax.legend(fontsize=9)
    ax.set_xlim(0, len(det_demand))

    fig.tight_layout()
    fig.savefig(FIG_DIR / 'demand_profile.png')
    plt.close(fig)
    print('Saved demand_profile.png')


def plot_scenario_cost_scatter(stoch):
    """Per-scenario cost scatter: each dot is one scenario's 7-day total."""
    costs = [sum(daily_cost(stoch[i][d]) for d in TARGET_DATES) / 1e6
             for i in range(N_SCENARIOS)]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.scatter(range(N_SCENARIOS), costs, c='steelblue', s=20, alpha=0.7)
    ax.axhline(np.mean(costs), color='navy', linestyle=':', linewidth=1.5,
               label=f'Mean ${np.mean(costs):.1f}M')
    ax.axhline(np.mean(costs) + np.std(costs, ddof=1), color='gray',
               linestyle='--', linewidth=1, alpha=0.5, label='+/- 1 std')
    ax.axhline(np.mean(costs) - np.std(costs, ddof=1), color='gray',
               linestyle='--', linewidth=1, alpha=0.5)

    ax.set_xlabel('Scenario Index')
    ax.set_ylabel('7-Day Total Cost ($M)')
    ax.set_title('Per-Scenario Cost — 100 v2 Stochastic Scenarios')
    ax.legend(fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('$%.1fM'))

    fig.tight_layout()
    fig.savefig(FIG_DIR / 'scenario_cost_scatter.png')
    plt.close(fig)
    print('Saved scenario_cost_scatter.png')


if __name__ == '__main__':
    print('Loading results...')
    det, stoch = load_results()
    print(f'Loaded {len(det)} det days, {len(stoch)} scenarios')

    plot_cost_histogram(det, stoch)
    plot_lmp_fan_chart(det, stoch)
    plot_commitment_heatmap(det)
    plot_daily_cost_spread(det, stoch)
    plot_reserve_shortfall(det, stoch)
    plot_demand_profile(det, stoch)
    plot_scenario_cost_scatter(stoch)

    print(f'\nAll plots saved to {FIG_DIR}')
