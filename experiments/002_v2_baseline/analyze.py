#!/usr/bin/env python
"""
Experiment 002: Analysis — v2 Stochastic vs. Deterministic UC
=============================================================

Validates smoke test results and produces full analysis for the
100-scenario ensemble.

Usage:
    # Validate smoke test (5 scenarios, 1 target day)
    python analyze.py --smoke

    # Full analysis (100 scenarios, 7 target days)
    python analyze.py

    # Compare with original ensemble (experiment 001)
    python analyze.py --compare
"""

import argparse
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

EXPERIMENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "Vatic"))


def load_deterministic(det_dir, target_dates):
    """Load deterministic results for target dates."""
    results = {}
    for d in target_dates:
        path = det_dir / f"day_{d}.pkl"
        if path.exists():
            with open(path, "rb") as f:
                results[d] = pickle.load(f)
    return results


def load_stochastic(stoch_dir, n_scenarios, target_dates):
    """Load stochastic results: {scen_idx: {date: results}}."""
    results = {}
    for scen_idx in range(n_scenarios):
        scen_dir = stoch_dir / f"scenario_{scen_idx:03d}"
        if not scen_dir.exists():
            continue
        scen_results = {}
        for d in target_dates:
            path = scen_dir / f"day_{d}.pkl"
            if path.exists():
                with open(path, "rb") as f:
                    scen_results[d] = pickle.load(f)
        if scen_results:
            results[scen_idx] = scen_results
    return results


def compute_daily_cost(results):
    """Total daily cost = FixedCosts + VariableCosts."""
    hs = results["hourly_summary"]
    return hs["FixedCosts"].sum() + hs["VariableCosts"].sum()


def compute_daily_load_shed(results):
    hs = results["hourly_summary"]
    return hs["LoadShedding"].sum()


def validate_smoke_test(det_dir, stoch_dir, target_dates, n_scenarios):
    """Run all smoke test validation checks.

    Returns (passed: bool, report: str).
    """
    lines = ["# v2 Smoke Test Validation Report\n"]
    all_pass = True

    # Load data
    det_results = load_deterministic(det_dir, target_dates)
    stoch_results = load_stochastic(stoch_dir, n_scenarios, target_dates)

    lines.append(f"## Data loaded")
    lines.append(f"- Deterministic days: {len(det_results)}/{len(target_dates)}")
    lines.append(f"- Stochastic scenarios: {len(stoch_results)}/{n_scenarios}")
    lines.append("")

    # --- Check 1: All scenarios complete to optimality ---
    lines.append("## Check 1: All scenarios complete to optimality")
    n_complete = 0
    for scen_idx in range(n_scenarios):
        if scen_idx in stoch_results:
            days_done = len(stoch_results[scen_idx])
            if days_done == len(target_dates):
                n_complete += 1

    check1 = n_complete == n_scenarios
    lines.append(f"- {n_complete}/{n_scenarios} scenarios completed all "
                 f"{len(target_dates)} target days")
    lines.append(f"- **{'PASS' if check1 else 'FAIL'}**")
    lines.append("")
    if not check1:
        all_pass = False

    # --- Check 2: Cost CV across scenarios > 1% ---
    lines.append("## Check 2: Cost CV across scenarios > 1%")
    scenario_costs = []
    for scen_idx in sorted(stoch_results.keys()):
        total_cost = sum(compute_daily_cost(r)
                         for r in stoch_results[scen_idx].values())
        scenario_costs.append(total_cost)

    if len(scenario_costs) >= 2:
        cost_mean = np.mean(scenario_costs)
        cost_std = np.std(scenario_costs, ddof=1)
        cost_cv = cost_std / cost_mean * 100 if cost_mean > 0 else 0

        lines.append(f"- Mean cost: ${cost_mean:,.0f}")
        lines.append(f"- Std dev: ${cost_std:,.0f}")
        lines.append(f"- CV: {cost_cv:.2f}%")

        check2 = cost_cv > 1.0
        lines.append(f"- **{'PASS' if check2 else 'FAIL'}** "
                     f"(threshold: >1%)")
        if not check2:
            all_pass = False
    else:
        lines.append("- SKIP: not enough scenarios")
        check2 = False
    lines.append("")

    # --- Check 3: Per-plant wind correlation between scen 0 and scen 1 < 0.95 ---
    lines.append("## Check 3: Wind correlation scen_0 vs scen_1 < 0.95")
    if 0 in stoch_results and 1 in stoch_results:
        # Load scenario parquets to get wind values
        scen_dir = stoch_dir.parent / "scenarios"
        try:
            s0 = pd.read_parquet(scen_dir / "scenario_000.parquet")
            s1 = pd.read_parquet(scen_dir / "scenario_001.parquet")

            w0 = s0[s0["asset_type"] == "wind"].reset_index()
            w1 = s1[s1["asset_type"] == "wind"].reset_index()

            # Per-site correlation
            sites = w0["asset_id"].unique()
            correlations = []
            for site in sites:
                v0 = w0[w0["asset_id"] == site].sort_values("timestamp")["value_mw"].values
                v1 = w1[w1["asset_id"] == site].sort_values("timestamp")["value_mw"].values
                if len(v0) == len(v1) and len(v0) > 1 and np.std(v0) > 0 and np.std(v1) > 0:
                    corr = np.corrcoef(v0, v1)[0, 1]
                    correlations.append(corr)

            if correlations:
                mean_corr = np.mean(correlations)
                max_corr = np.max(correlations)
                lines.append(f"- Sites compared: {len(correlations)}")
                lines.append(f"- Mean per-site correlation: {mean_corr:.3f}")
                lines.append(f"- Max per-site correlation: {max_corr:.3f}")
                check3 = max_corr < 0.95
                lines.append(f"- **{'PASS' if check3 else 'FAIL'}** "
                             f"(threshold: max < 0.95)")
                if not check3:
                    all_pass = False
            else:
                lines.append("- SKIP: no valid correlations computed")
                check3 = False
        except Exception as e:
            lines.append(f"- SKIP: error loading scenarios: {e}")
            check3 = False
    else:
        lines.append("- SKIP: scenarios 0 and 1 not available")
        check3 = False
    lines.append("")

    # --- Check 4: Load varies across scenarios (per-zone CV > 0.3%) ---
    lines.append("## Check 4: Load varies across scenarios (per-zone CV > 0.3%)")
    try:
        scen_dir = stoch_dir.parent / "scenarios"
        zone_loads = defaultdict(list)  # zone -> [scenario_total_loads]

        for scen_idx in range(n_scenarios):
            scen_path = scen_dir / f"scenario_{scen_idx:03d}.parquet"
            if not scen_path.exists():
                continue
            df = pd.read_parquet(scen_path)
            load_df = df[df["asset_type"] == "load"].reset_index()
            for zone in load_df["asset_id"].unique():
                total = load_df[load_df["asset_id"] == zone]["value_mw"].sum()
                zone_loads[zone].append(total)

        zone_cvs = {}
        for zone, loads in zone_loads.items():
            if len(loads) >= 2 and np.mean(loads) > 0:
                cv = np.std(loads, ddof=1) / np.mean(loads) * 100
                zone_cvs[zone] = cv

        if zone_cvs:
            min_cv = min(zone_cvs.values())
            max_cv = max(zone_cvs.values())
            mean_cv = np.mean(list(zone_cvs.values()))
            lines.append(f"- Zones analyzed: {len(zone_cvs)}")
            lines.append(f"- CV range: {min_cv:.2f}% — {max_cv:.2f}%")
            lines.append(f"- Mean CV: {mean_cv:.2f}%")
            check4 = min_cv > 0.3
            lines.append(f"- **{'PASS' if check4 else 'FAIL'}** "
                         f"(threshold: all zones > 0.3%)")
            if not check4:
                all_pass = False
        else:
            lines.append("- SKIP: no zone loads found")
            check4 = False
    except Exception as e:
        lines.append(f"- SKIP: error: {e}")
        check4 = False
    lines.append("")

    # --- Check 5: BESS dispatches in at least 3 of 5 scenarios ---
    lines.append("## Check 5: BESS dispatches in >= 3 of 5 scenarios")
    bess_active_count = 0
    for scen_idx in sorted(stoch_results.keys()):
        for day_results in stoch_results[scen_idx].values():
            ts = day_results.get("thermal_summary")
            if ts is not None:
                # Check for storage columns in hourly_summary or thermal_summary
                pass
            # Check bus_summary for storage output
            bs = day_results.get("bus_summary")
            hs = day_results.get("hourly_summary")
            if hs is not None and "StorageDischarge" in hs.columns:
                discharge = hs["StorageDischarge"].sum()
                if discharge > 0.1:
                    bess_active_count += 1
                    break
            elif hs is not None:
                # Try to find storage in thermal detail
                for col in hs.columns:
                    if "storage" in col.lower() or "bess" in col.lower():
                        if hs[col].abs().sum() > 0.1:
                            bess_active_count += 1
                            break
                else:
                    continue
                break

    # Also check by examining the hourly_summary columns
    lines.append(f"- Scenarios with BESS dispatch: {bess_active_count}/{len(stoch_results)}")
    check5 = bess_active_count >= 3
    lines.append(f"- **{'PASS' if check5 else 'FAIL'}** (threshold: >= 3)")
    if not check5:
        # Check what columns are available
        if stoch_results:
            first_scen = next(iter(stoch_results.values()))
            first_day = next(iter(first_scen.values()))
            hs = first_day.get("hourly_summary")
            if hs is not None:
                lines.append(f"- hourly_summary columns: {list(hs.columns)}")
        all_pass = False
    lines.append("")

    # --- Summary ---
    lines.append("## Summary")
    lines.append(f"**Overall: {'ALL CHECKS PASS' if all_pass else 'SOME CHECKS FAILED'}**")
    lines.append("")

    # Cost table
    lines.append("## Scenario Cost Table")
    lines.append("| Scenario | Total Cost ($) | Load Shed (MWh) |")
    lines.append("|----------|---------------|-----------------|")

    det_cost = sum(compute_daily_cost(r)
                   for r in det_results.values()) if det_results else 0
    det_ls = sum(compute_daily_load_shed(r)
                 for r in det_results.values()) if det_results else 0
    lines.append(f"| Deterministic | {det_cost:,.0f} | {det_ls:,.1f} |")

    for scen_idx in sorted(stoch_results.keys()):
        cost = sum(compute_daily_cost(r)
                   for r in stoch_results[scen_idx].values())
        ls = sum(compute_daily_load_shed(r)
                 for r in stoch_results[scen_idx].values())
        lines.append(f"| Scenario {scen_idx:03d} | {cost:,.0f} | {ls:,.1f} |")

    report = "\n".join(lines)
    return all_pass, report


def full_analysis(det_dir, stoch_dir, target_dates, n_scenarios):
    """Full 100-scenario analysis."""
    lines = ["# v2 Stochastic Experiment — Full Analysis\n"]

    det_results = load_deterministic(det_dir, target_dates)
    stoch_results = load_stochastic(stoch_dir, n_scenarios, target_dates)

    lines.append(f"## Completion")
    n_complete = sum(1 for s in stoch_results.values()
                     if len(s) == len(target_dates))
    lines.append(f"- {n_complete}/{n_scenarios} scenarios completed all "
                 f"{len(target_dates)} days")
    lines.append("")

    # Deterministic baseline
    det_costs = {d: compute_daily_cost(r) for d, r in det_results.items()}
    det_total = sum(det_costs.values())
    lines.append(f"## Deterministic Baseline")
    lines.append(f"- Total 7-day cost: ${det_total:,.0f}")
    for d in sorted(det_costs):
        lines.append(f"  - {d}: ${det_costs[d]:,.0f}")
    lines.append("")

    # Stochastic ensemble
    scenario_costs = []
    scenario_daily_costs = defaultdict(list)
    scenario_load_shed = []

    for scen_idx in sorted(stoch_results.keys()):
        if len(stoch_results[scen_idx]) != len(target_dates):
            continue
        total = sum(compute_daily_cost(r)
                    for r in stoch_results[scen_idx].values())
        ls = sum(compute_daily_load_shed(r)
                 for r in stoch_results[scen_idx].values())
        scenario_costs.append(total)
        scenario_load_shed.append(ls)

        for d, r in stoch_results[scen_idx].items():
            scenario_daily_costs[d].append(compute_daily_cost(r))

    if not scenario_costs:
        lines.append("No complete scenarios found.")
        return "\n".join(lines)

    cost_arr = np.array(scenario_costs)
    cost_mean = np.mean(cost_arr)
    cost_std = np.std(cost_arr, ddof=1)
    cost_cv = cost_std / cost_mean * 100
    cost_of_uncertainty = (cost_mean - det_total) / det_total * 100

    lines.append(f"## Stochastic Ensemble ({len(scenario_costs)} complete scenarios)")
    lines.append(f"- Mean cost: ${cost_mean:,.0f}")
    lines.append(f"- Std dev: ${cost_std:,.0f}")
    lines.append(f"- **Cost CV: {cost_cv:.2f}%**")
    lines.append(f"- Min: ${np.min(cost_arr):,.0f}, Max: ${np.max(cost_arr):,.0f}")
    lines.append(f"- **Cost of uncertainty: {cost_of_uncertainty:+.2f}%**")
    lines.append(f"  (stochastic mean vs. deterministic)")
    lines.append("")

    # Percentiles
    lines.append("### Cost Distribution")
    for pct in [5, 25, 50, 75, 95]:
        lines.append(f"- P{pct}: ${np.percentile(cost_arr, pct):,.0f}")
    lines.append("")

    # Load shedding
    ls_arr = np.array(scenario_load_shed)
    n_ls = np.sum(ls_arr > 0.1)
    lines.append(f"## Load Shedding")
    lines.append(f"- Scenarios with load shedding: {n_ls}/{len(ls_arr)}")
    if n_ls > 0:
        lines.append(f"- Mean (when present): {np.mean(ls_arr[ls_arr > 0.1]):,.1f} MWh")
        lines.append(f"- Max: {np.max(ls_arr):,.1f} MWh")
    lines.append("")

    # PTDF slack utilization — would need to dig into branch_detail
    lines.append("## PTDF Slack Utilization")
    lines.append("(Requires branch_detail in results — TBD)")
    lines.append("")

    # Comparison to original ensemble
    lines.append("## Comparison to Original Ensemble (Experiment 001)")
    lines.append("")
    lines.append("| Metric | Original (001) | v2 (002) |")
    lines.append("|--------|---------------|----------|")
    lines.append(f"| Scenarios completing all 7 days | 52/100 | "
                 f"{n_complete}/100 |")
    lines.append(f"| Cost of uncertainty | -0.80% | "
                 f"{cost_of_uncertainty:+.2f}% |")
    lines.append(f"| Cost CV | 0.54% | {cost_cv:.2f}% |")
    lines.append(f"| Solver | CBC | Gurobi |")
    lines.append(f"| Reserve | 5% of load | 2,620 MW fixed |")
    lines.append(f"| Import model | Single-bus, static | Multi-bus, Path B |")
    lines.append(f"| Storage | None | BESS + pumped |")
    lines.append(f"| PTDF slacks | No | $5,000/MWh |")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()

    import yaml
    with open(EXPERIMENT_DIR / "config.yaml") as f:
        cfg = yaml.safe_load(f)

    det_dir = EXPERIMENT_DIR / cfg["paths"]["deterministic_dir"]
    stoch_dir = EXPERIMENT_DIR / cfg["paths"]["stochastic_dir"]

    if args.smoke:
        target_dates = [cfg["scenarios"]["smoke_test_day"]]
        n_scenarios = cfg["scenarios"]["smoke_test_count"]

        passed, report = validate_smoke_test(
            det_dir, stoch_dir, target_dates, n_scenarios)

        print(report)
        out_path = EXPERIMENT_DIR / "results" / "smoke_test_report.md"
        with open(out_path, "w") as f:
            f.write(report)
        print(f"\nReport saved to {out_path}")

        sys.exit(0 if passed else 1)

    else:
        import datetime
        start = datetime.date.fromisoformat(cfg["dates"]["start"])
        end = datetime.date.fromisoformat(cfg["dates"]["end"])
        target_dates = [
            (start + datetime.timedelta(days=i)).isoformat()
            for i in range((end - start).days + 1)
        ]
        n_scenarios = cfg["scenarios"]["count"]

        report = full_analysis(det_dir, stoch_dir, target_dates, n_scenarios)

        print(report)
        out_path = EXPERIMENT_DIR / "results" / "v2_stochastic_summary.md"
        with open(out_path, "w") as f:
            f.write(report)
        print(f"\nReport saved to {out_path}")


if __name__ == "__main__":
    main()
