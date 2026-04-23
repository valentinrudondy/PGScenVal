#!/usr/bin/env python
"""
Experiment 001: Analysis & Plotting
====================================

Reads deterministic and stochastic simulation outputs, produces summary
statistics, validation checks, and publication-quality figures.

Usage:
    python analyze.py                # analyze full run
    python analyze.py --smoke        # analyze smoke-test outputs
"""

import argparse
import datetime
import pickle
import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

EXPERIMENT_DIR = Path(__file__).resolve().parent

def load_config():
    with open(EXPERIMENT_DIR / "config.yaml") as f:
        return yaml.safe_load(f)

CFG = load_config()

# Matplotlib style
plt.style.use("seaborn-v0_8-whitegrid")
plt.rcParams.update({
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.figsize": (10, 6),
})


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_results(path):
    with open(path, "rb") as f:
        return pickle.load(f)


def parse_dates(start_str, end_str):
    start = datetime.date.fromisoformat(start_str)
    end = datetime.date.fromisoformat(end_str)
    return [start + datetime.timedelta(days=i)
            for i in range((end - start).days + 1)]


def collect_deterministic(dates):
    """Load all deterministic day results into a dict."""
    det_dir = EXPERIMENT_DIR / CFG["paths"]["deterministic_dir"]
    results = {}
    for d in dates:
        path = det_dir / f"day_{d.isoformat()}.pkl"
        if path.exists():
            results[d] = load_results(path)
    return results


def collect_stochastic(dates, n_scenarios):
    """Load all stochastic results into nested dict[scenario][date]."""
    stoch_dir = EXPERIMENT_DIR / CFG["paths"]["stochastic_dir"]
    results = {}
    for scen_idx in range(n_scenarios):
        scen_dir = stoch_dir / f"scenario_{scen_idx:03d}"
        scen_results = {}
        for d in dates:
            path = scen_dir / f"day_{d.isoformat()}.pkl"
            if path.exists():
                scen_results[d] = load_results(path)
        if scen_results:
            results[scen_idx] = scen_results
    return results


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

def daily_cost(result):
    """Total production cost (fixed + variable) from hourly_summary."""
    hs = result["hourly_summary"]
    return hs["FixedCosts"].sum() + hs["VariableCosts"].sum()


def daily_load_shedding(result):
    return result["hourly_summary"]["LoadShedding"].sum()


def daily_reserve_shortfall(result):
    return result["hourly_summary"]["ReserveShortfall"].sum()


def hourly_system_lmp(result):
    """System-level marginal price for each hour.

    Uses hourly_summary['Price'] which reflects the system marginal cost
    without penalty spikes from localized load shedding / reserve shortfall.
    Bus-level LMPs can hit $10,000/MWh (load shed penalty) at constrained
    buses, which would inflate the system average misleadingly.
    """
    return result["hourly_summary"]["Price"]


def weekly_cost(day_results):
    """Sum daily costs across a week."""
    return sum(daily_cost(r) for r in day_results.values())


def weekly_lmp_series(day_results):
    """Concatenate hourly LMPs across the week."""
    parts = []
    for d in sorted(day_results.keys()):
        lmps = hourly_system_lmp(day_results[d])
        parts.append(lmps)
    return pd.concat(parts)


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_cost_histogram(det_cost, stoch_costs, fig_dir):
    """Histogram of total weekly production cost across scenarios."""
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(stoch_costs, bins=25, alpha=0.7, color="#4C72B0",
            edgecolor="white", label="Stochastic scenarios")
    ax.axvline(det_cost, color="#C44E52", linewidth=2, linestyle="--",
               label=f"Deterministic: ${det_cost:,.0f}")
    ax.axvline(np.mean(stoch_costs), color="#55A868", linewidth=2,
               linestyle="-.",
               label=f"Stochastic mean: ${np.mean(stoch_costs):,.0f}")

    ax.set_xlabel("Total Weekly Production Cost ($)")
    ax.set_ylabel("Number of Scenarios")
    ax.set_title("Distribution of Weekly Production Cost")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "cost_histogram.png")
    plt.close(fig)


def plot_lmp_fan_chart(det_lmps, stoch_lmp_matrix, fig_dir):
    """Fan chart of system LMP across scenarios vs deterministic."""
    fig, ax = plt.subplots(figsize=(12, 6))
    hours = np.arange(len(det_lmps))

    p5 = np.percentile(stoch_lmp_matrix, 5, axis=0)
    p25 = np.percentile(stoch_lmp_matrix, 25, axis=0)
    p50 = np.percentile(stoch_lmp_matrix, 50, axis=0)
    p75 = np.percentile(stoch_lmp_matrix, 75, axis=0)
    p95 = np.percentile(stoch_lmp_matrix, 95, axis=0)

    ax.fill_between(hours, p5, p95, alpha=0.15, color="#4C72B0",
                     label="5th–95th pct")
    ax.fill_between(hours, p25, p75, alpha=0.3, color="#4C72B0",
                     label="25th–75th pct")
    ax.plot(hours, p50, color="#4C72B0", linewidth=1.5,
            label="Stochastic median")
    ax.plot(hours, det_lmps.values, color="#C44E52", linewidth=1.5,
            linestyle="--", label="Deterministic")

    ax.set_xlabel("Hour of Week")
    ax.set_ylabel("System LMP ($/MWh)")
    ax.set_title("System LMP Fan Chart: Stochastic Ensemble vs. Deterministic")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(fig_dir / "lmp_fan_chart.png")
    plt.close(fig)


def plot_commitment_heatmap(stoch_results, dates, fig_dir):
    """Heatmap: fraction of scenarios each generator is committed per hour."""
    # Collect commitment states from thermal_detail
    all_commits = []
    n_scenarios = len(stoch_results)

    for scen_idx, day_results in stoch_results.items():
        for d in sorted(day_results.keys()):
            if "thermal_detail" not in day_results[d]:
                continue
            td = day_results[d]["thermal_detail"]
            if "Unit State" in td.columns:
                commits = td["Unit State"].unstack(level="Generator")
                all_commits.append(commits)

    if not all_commits:
        print("WARNING: No commitment data available for heatmap")
        return

    # Stack all scenario commits and compute fraction
    combined = pd.concat(all_commits, keys=range(len(all_commits)))
    frac = combined.groupby(level=[1, 2]).mean()  # avg across scenarios

    # Select top 30 generators by commitment variability
    variability = frac.std()
    top_gens = variability.nlargest(30).index

    plot_data = frac[top_gens]

    fig, ax = plt.subplots(figsize=(14, 8))
    im = ax.imshow(plot_data.T.values, aspect="auto", cmap="YlOrRd",
                   vmin=0, vmax=1)
    ax.set_ylabel("Generator")
    ax.set_xlabel("Time Period")
    ax.set_yticks(range(len(top_gens)))
    ax.set_yticklabels(top_gens, fontsize=6)
    ax.set_title("Commitment Probability Heatmap (Top 30 Variable Generators)")
    plt.colorbar(im, ax=ax, label="Fraction of scenarios committed")
    fig.tight_layout()
    fig.savefig(fig_dir / "commitment_heatmap.png")
    plt.close(fig)


def plot_dispatch_percentiles(det_results, stoch_results, dates, fig_dir):
    """Dispatch stack for median vs 5th/95th percentile scenarios."""
    # Compute total cost per scenario to identify percentile scenarios
    scen_costs = {}
    for scen_idx, day_results in stoch_results.items():
        scen_costs[scen_idx] = weekly_cost(day_results)

    costs_arr = np.array(list(scen_costs.values()))
    scen_ids = list(scen_costs.keys())

    idx_5th = scen_ids[np.argmin(np.abs(costs_arr - np.percentile(costs_arr, 5)))]
    idx_50th = scen_ids[np.argmin(np.abs(costs_arr - np.percentile(costs_arr, 50)))]
    idx_95th = scen_ids[np.argmin(np.abs(costs_arr - np.percentile(costs_arr, 95)))]

    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
    labels = [f"5th pct (Scenario {idx_5th})",
              f"Median (Scenario {idx_50th})",
              f"95th pct (Scenario {idx_95th})"]

    for ax, scen_idx, label in zip(axes, [idx_5th, idx_50th, idx_95th], labels):
        day_results = stoch_results[scen_idx]
        dispatch_by_type = {"Nuclear": [], "Gas": [], "Hydro": [],
                            "Oil": [], "Wind": [], "Solar": [], "Other": []}

        for d in sorted(day_results.keys()):
            if "thermal_detail" in day_results[d]:
                td = day_results[d]["thermal_detail"]
                if "Dispatch" in td.columns:
                    dispatch = td["Dispatch"].unstack(level="Generator")
                    dispatch_by_type["Gas"].append(dispatch.sum(axis=1))
            if "renew_detail" in day_results[d]:
                rd = day_results[d]["renew_detail"]
                if "Output" in rd.columns:
                    renew = rd["Output"].unstack(level="Generator")
                    dispatch_by_type["Wind"].append(renew.sum(axis=1))

        # Simple total dispatch plot
        total = []
        for dtype, parts in dispatch_by_type.items():
            if parts:
                total.append(pd.concat(parts))

        if total:
            combined = pd.concat(total, axis=1)
            combined.columns = range(len(combined.columns))
            ax.plot(range(len(combined)), combined.sum(axis=1).values,
                    linewidth=1.5)

        ax.set_ylabel("Dispatch (MW)")
        ax.set_title(label)

    axes[-1].set_xlabel("Hour")
    fig.suptitle("Total Dispatch: Percentile Scenarios", fontsize=13)
    fig.tight_layout()
    fig.savefig(fig_dir / "dispatch_percentiles.png")
    plt.close(fig)


def plot_zonal_lmp_boxplot(stoch_results, dates, fig_dir):
    """Boxplot of LMP by zone, highlighting J/K (NYC/Long Island) premium."""
    if not stoch_results:
        return

    # Collect bus LMPs and map to zones
    zone_lmps = {}
    for scen_idx, day_results in stoch_results.items():
        for d, result in day_results.items():
            if "bus_detail" in result and "LMP" in result["bus_detail"].columns:
                bus_lmp = result["bus_detail"]["LMP"]
                for idx_tuple, val in bus_lmp.items():
                    bus_name = idx_tuple[2] if len(idx_tuple) > 2 else "unknown"
                    zone_lmps.setdefault(bus_name, []).append(val)

    if not zone_lmps:
        # Fall back: plot hourly_summary Price across scenarios
        all_prices = []
        for scen_idx, day_results in stoch_results.items():
            for d, result in day_results.items():
                prices = result["hourly_summary"]["Price"]
                all_prices.extend(prices.values)

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.hist(all_prices, bins=30, alpha=0.7, color="#4C72B0",
                edgecolor="white")
        ax.set_xlabel("System Price ($/MWh)")
        ax.set_ylabel("Count")
        ax.set_title("Distribution of Hourly System Price Across Scenarios")
        fig.tight_layout()
        fig.savefig(fig_dir / "zonal_lmp_boxplot.png")
        plt.close(fig)
        return

    # Aggregate by first few chars for zone grouping
    df_lmps = pd.DataFrame({k: pd.Series(v) for k, v in zone_lmps.items()})

    fig, ax = plt.subplots(figsize=(12, 6))
    df_lmps.boxplot(ax=ax, rot=90)
    ax.set_ylabel("LMP ($/MWh)")
    ax.set_title("Zonal LMP Distribution Across Scenarios")
    fig.tight_layout()
    fig.savefig(fig_dir / "zonal_lmp_boxplot.png")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def write_summary_report(det_results, stoch_results, dates, fig_dir,
                         report_path):
    """Write a plain-text Markdown summary with all key metrics."""

    det_cost = weekly_cost(det_results)
    stoch_costs = [weekly_cost(dr) for dr in stoch_results.values()]
    stoch_mean = np.mean(stoch_costs)
    stoch_median = np.median(stoch_costs)
    stoch_p5 = np.percentile(stoch_costs, 5)
    stoch_p95 = np.percentile(stoch_costs, 95)

    cost_of_uncertainty = stoch_mean - det_cost
    cost_of_uncertainty_pct = (cost_of_uncertainty / det_cost) * 100

    # Load shedding
    det_ls = sum(daily_load_shedding(r) for r in det_results.values())
    stoch_ls_counts = sum(
        1 for dr in stoch_results.values()
        for r in dr.values()
        if daily_load_shedding(r) > 0.1
    )

    # Reserve shortfall
    det_rs = sum(daily_reserve_shortfall(r) for r in det_results.values())
    stoch_rs_counts = sum(
        1 for dr in stoch_results.values()
        for r in dr.values()
        if daily_reserve_shortfall(r) > 0.1
    )

    # LMP stats
    det_lmps = weekly_lmp_series(det_results)
    det_avg_lmp = det_lmps.mean()

    stoch_avg_lmps = []
    for dr in stoch_results.values():
        lmp_series = weekly_lmp_series(dr)
        stoch_avg_lmps.append(lmp_series.mean())

    n_scenarios = len(stoch_results)
    n_days = len(dates)

    report = textwrap.dedent(f"""\
    # Experiment 001: Stochastic vs Deterministic UC — Summary Report

    **Date range:** {dates[0].isoformat()} to {dates[-1].isoformat()} ({n_days} days)
    **Scenarios:** {n_scenarios}
    **Solver:** CBC (MIP gap {CFG['vatic']['mipgap']})

    ---

    ## Production Cost

    | Metric | Value |
    |--------|-------|
    | Deterministic weekly cost | ${det_cost:,.0f} |
    | Stochastic mean | ${stoch_mean:,.0f} |
    | Stochastic median | ${stoch_median:,.0f} |
    | Stochastic 5th percentile | ${stoch_p5:,.0f} |
    | Stochastic 95th percentile | ${stoch_p95:,.0f} |
    | **Cost of uncertainty** | **${cost_of_uncertainty:+,.0f} ({cost_of_uncertainty_pct:+.2f}%)** |

    ## System LMP ($/MWh)

    | Metric | Value |
    |--------|-------|
    | Deterministic avg LMP | ${det_avg_lmp:.2f}/MWh |
    | Stochastic mean avg LMP | ${np.mean(stoch_avg_lmps):.2f}/MWh |
    | Stochastic median avg LMP | ${np.median(stoch_avg_lmps):.2f}/MWh |

    ## Reliability Events

    | Metric | Value |
    |--------|-------|
    | Deterministic load shedding (MWh) | {det_ls:.1f} |
    | Stochastic scenarios with load shedding | {stoch_ls_counts} / {n_scenarios * n_days} day-scenarios |
    | Deterministic reserve shortfall (MWh) | {det_rs:.1f} |
    | Stochastic scenarios with reserve shortfall | {stoch_rs_counts} / {n_scenarios * n_days} day-scenarios |

    ## Validation Checks

    ### Cost reasonableness
    """)

    # Rough NYISO summer week cost: ~$200-400M for full system
    # Our model is reduced, so expect lower
    report += f"- Deterministic cost: ${det_cost:,.0f}\n"
    if det_cost < 1e3:
        report += "- WARNING: Cost seems unrealistically low. Check units.\n"
    elif det_cost > 1e10:
        report += "- WARNING: Cost seems unrealistically high. Check solver.\n"
    else:
        report += "- Cost in plausible range.\n"

    report += f"\n### LMP reasonableness\n"
    report += f"- Deterministic avg LMP: ${det_avg_lmp:.2f}/MWh\n"
    if 10 <= det_avg_lmp <= 200:
        report += "- LMP in plausible range ($10–$200/MWh).\n"
    else:
        report += f"- WARNING: Avg LMP outside plausible range.\n"

    report += f"\n### Scenario spread\n"
    spread = np.std(stoch_costs) / stoch_mean * 100 if stoch_mean > 0 else 0
    report += f"- Cost coefficient of variation: {spread:.2f}%\n"
    if spread < 1:
        report += ("- WARNING: Very low spread (<1% CV). Either scenarios have "
                   "minimal variance or the system is insensitive to "
                   "renewable/load uncertainty.\n")
    else:
        report += "- Meaningful scenario spread detected.\n"

    report += f"\n### Deterministic vs stochastic\n"
    if abs(cost_of_uncertainty_pct) < 1:
        report += (f"- Cost of uncertainty is small ({cost_of_uncertainty_pct:+.2f}%). "
                   "Either scenarios are narrow or the deterministic forecast "
                   "is a good point estimate.\n")
    else:
        report += (f"- Cost of uncertainty: {cost_of_uncertainty_pct:+.2f}% — "
                   "uncertainty has a material impact on expected cost.\n")

    report += "\n---\n\n## Figures\n\n"
    report += "![Cost Histogram](figures/cost_histogram.png)\n\n"
    report += "![LMP Fan Chart](figures/lmp_fan_chart.png)\n\n"
    report += "![Commitment Heatmap](figures/commitment_heatmap.png)\n\n"
    report += "![Dispatch Percentiles](figures/dispatch_percentiles.png)\n\n"
    report += "![Zonal LMP](figures/zonal_lmp_boxplot.png)\n\n"

    with open(report_path, "w") as f:
        f.write(report)

    print(f"Summary report written to {report_path}")
    return cost_of_uncertainty_pct


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Analyze experiment 001 results")
    parser.add_argument("--smoke", action="store_true",
                        help="Analyze smoke-test results (1 day, 5 scenarios)")
    args = parser.parse_args()

    if args.smoke:
        # Exclude warmup day — analyze only the target day
        dates = parse_dates(CFG["scenarios"]["smoke_test_day"],
                            CFG["scenarios"]["smoke_test_day"])
        n_scenarios = CFG["scenarios"]["smoke_test_count"]
    else:
        # Exclude warmup day — analyze only target days
        dates = parse_dates(CFG["dates"]["start"], CFG["dates"]["end"])
        n_scenarios = CFG["scenarios"]["count"]

    fig_dir = EXPERIMENT_DIR / CFG["paths"]["figures_dir"]
    fig_dir.mkdir(parents=True, exist_ok=True)
    report_path = EXPERIMENT_DIR / CFG["paths"]["results_dir"] / "summary_report.md"

    print(f"Loading deterministic results for {len(dates)} day(s)...")
    det_results = collect_deterministic(dates)
    print(f"  Loaded {len(det_results)} deterministic day(s)")

    print(f"Loading stochastic results for up to {n_scenarios} scenarios...")
    stoch_results = collect_stochastic(dates, n_scenarios)
    print(f"  Loaded {len(stoch_results)} scenarios")

    if not det_results:
        print("ERROR: No deterministic results found. Run `python run.py` first.")
        sys.exit(1)
    if not stoch_results:
        print("ERROR: No stochastic results found. Run `python run.py` first.")
        sys.exit(1)

    # --- Summary statistics ---
    det_cost = weekly_cost(det_results)
    stoch_costs = [weekly_cost(dr) for dr in stoch_results.values()]

    print(f"\n{'='*60}")
    print(f"Deterministic cost:        ${det_cost:>14,.0f}")
    print(f"Stochastic mean:           ${np.mean(stoch_costs):>14,.0f}")
    print(f"Stochastic median:         ${np.median(stoch_costs):>14,.0f}")
    print(f"Stochastic 5th pct:        ${np.percentile(stoch_costs, 5):>14,.0f}")
    print(f"Stochastic 95th pct:       ${np.percentile(stoch_costs, 95):>14,.0f}")
    cost_unc = np.mean(stoch_costs) - det_cost
    print(f"Cost of uncertainty:       ${cost_unc:>+14,.0f} "
          f"({cost_unc/det_cost*100:+.2f}%)")
    print(f"{'='*60}\n")

    # --- Plots ---
    print("Generating plots...")

    # 1. Cost histogram
    plot_cost_histogram(det_cost, stoch_costs, fig_dir)
    print("  cost_histogram.png")

    # 2. LMP fan chart
    det_lmps = weekly_lmp_series(det_results)
    stoch_lmp_matrix = []
    for dr in stoch_results.values():
        lmp_series = weekly_lmp_series(dr)
        stoch_lmp_matrix.append(lmp_series.values)

    # Pad/truncate to same length
    min_len = min(len(det_lmps), min(len(s) for s in stoch_lmp_matrix))
    det_lmps_plot = det_lmps.iloc[:min_len]
    stoch_lmp_arr = np.array([s[:min_len] for s in stoch_lmp_matrix])
    plot_lmp_fan_chart(det_lmps_plot, stoch_lmp_arr, fig_dir)
    print("  lmp_fan_chart.png")

    # 3. Commitment heatmap
    plot_commitment_heatmap(stoch_results, dates, fig_dir)
    print("  commitment_heatmap.png")

    # 4. Dispatch percentiles
    plot_dispatch_percentiles(det_results, stoch_results, dates, fig_dir)
    print("  dispatch_percentiles.png")

    # 5. Zonal LMP boxplot
    plot_zonal_lmp_boxplot(stoch_results, dates, fig_dir)
    print("  zonal_lmp_boxplot.png")

    # --- Summary report ---
    print("\nWriting summary report...")
    write_summary_report(det_results, stoch_results, dates, fig_dir, report_path)

    # --- Smoke-test validation ---
    if args.smoke:
        print("\n--- SMOKE TEST VALIDATION ---")
        ok = True

        # Check all scenarios solved
        expected = n_scenarios
        actual = len(stoch_results)
        print(f"  Scenarios completed: {actual}/{expected}", end="")
        if actual == expected:
            print(" OK")
        else:
            print(" FAIL")
            ok = False

        # Check LMP range
        avg_lmps = [weekly_lmp_series(dr).mean()
                     for dr in stoch_results.values()]
        lmp_min, lmp_max = min(avg_lmps), max(avg_lmps)
        print(f"  LMP range: ${lmp_min:.1f}–${lmp_max:.1f}/MWh", end="")
        if 10 <= lmp_min and lmp_max <= 500:
            print(" OK (plausible)")
        else:
            print(" WARNING (outside $10–$500 range)")

        # Check nonzero variance
        cv = np.std(stoch_costs) / np.mean(stoch_costs) * 100
        print(f"  Cost CV: {cv:.2f}%", end="")
        if cv > 0.01:
            print(" OK (nonzero spread)")
        else:
            print(" WARNING (near-zero spread)")
            ok = False

        # Check output shape
        for scen_idx, day_results in stoch_results.items():
            for d, result in day_results.items():
                hs = result["hourly_summary"]
                if len(hs) < 20:
                    print(f"  WARNING: scenario_{scen_idx:03d}/{d} has only "
                          f"{len(hs)} hours (expected ~24)")
                    ok = False

        if ok:
            print("\n  SMOKE TEST PASSED — safe to launch full run")
        else:
            print("\n  SMOKE TEST HAS WARNINGS — inspect before full run")


if __name__ == "__main__":
    main()
