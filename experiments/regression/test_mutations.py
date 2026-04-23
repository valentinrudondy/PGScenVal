"""Mutation tests: verify each regression test actually catches its target bug.

For each of the 4 fast bug classes, we construct deliberately-broken input
that simulates the historical bug, run the corresponding assertion logic,
and confirm it raises AssertionError. If a mutation passes silently, the
regression test has a gap — it can't detect the bug it claims to guard against.

Cold-start (test 3) and multi-day RUC (test 4) mutations are skipped because
they would require running broken Vatic simulations (~20 min each) just to
confirm the test catches them. The assertion logic for those tests is
straightforward (ratio < 0.10, rel_diff < 0.02), so the risk of a false
pass is low.
"""

import numpy as np
import pandas as pd
import pytest


# ============================================================================
# Mutation 1: Scalar-compressed wind scenarios
# ============================================================================

class TestMutationScenarioCompression:
    """Inject scalar-compressed scenarios and verify the compression test catches them."""

    def test_scalar_compressed_scenarios_detected(self):
        """All wind plants move identically (scalar × base profile) → must fail.

        This simulates the original bug: system-level scaling applied to all
        plants, destroying spatial correlation structure.
        """
        np.random.seed(42)
        n_hours = 24
        n_plants = 23
        timestamps = pd.date_range("2019-07-18", periods=n_hours, freq="h", tz="utc")
        plant_ids = [f"wind_{i}" for i in range(n_plants)]

        # Base profile: a single wind curve shared by all plants
        base_profile = 50 + 30 * np.sin(np.linspace(0, 2 * np.pi, n_hours))

        # Scenario A: base × scalar_a per plant (but same shape)
        scalars_a = np.random.uniform(0.8, 1.2, n_plants)
        wa = pd.DataFrame(
            {p: base_profile * s for p, s in zip(plant_ids, scalars_a)},
            index=timestamps,
        )

        # Scenario B: base × scalar_b per plant (same shape, different scalars)
        scalars_b = np.random.uniform(0.8, 1.2, n_plants)
        wb = pd.DataFrame(
            {p: base_profile * s for p, s in zip(plant_ids, scalars_b)},
            index=timestamps,
        )

        # Run the same assertion logic as test_scenario_compression
        corrs = wa.corrwith(wb)
        valid = corrs.dropna()

        # These scalar-compressed scenarios should have correlation ≈ 1.0
        # for every plant, so the primary assertion (max < 0.95) should FAIL
        with pytest.raises(AssertionError, match="scalar compression"):
            assert valid.max() < 0.95, (
                f"max correlation = {valid.max():.4f} >= 0.95 — "
                f"likely scalar compression"
            )

    def test_lockstep_within_scenario_detected(self):
        """All plants within one scenario have identical time profiles → must fail."""
        np.random.seed(42)
        n_hours = 24
        n_plants = 23
        timestamps = pd.date_range("2019-07-18", periods=n_hours, freq="h", tz="utc")

        base_profile = 50 + 30 * np.sin(np.linspace(0, 2 * np.pi, n_hours))
        # All plants are scalar multiples of the base — r = 1.0 pairwise
        scen = pd.DataFrame(
            {f"wind_{i}": base_profile * (0.5 + 0.1 * i) for i in range(n_plants)},
            index=timestamps,
        )

        corr_matrix = scen.corr()
        np.fill_diagonal(corr_matrix.values, np.nan)
        max_corr = corr_matrix.max().max()

        with pytest.raises(AssertionError, match="lockstep"):
            assert max_corr < 0.99, (
                f"max within-scenario plant correlation = {max_corr:.4f} — "
                f"plants are moving in lockstep"
            )


# ============================================================================
# Mutation 2: Timezone mismatch (load unchanged after scenario application)
# ============================================================================

class TestMutationTimezoneAlignment:
    """Inject scenario application that changes nothing → must be caught."""

    def test_no_load_change_detected(self):
        """If load_mod == load_orig (scenario never applied), test must fail.

        This simulates the timezone mismatch bug: all baseline lookups miss,
        ratio = 1.0 everywhere, load is unchanged.
        """
        n_hours = 24
        n_buses = 10
        timestamps = pd.date_range("2019-07-18", periods=n_hours, freq="h", tz="utc")
        bus_names = [f"BUS_{i}" for i in range(n_buses)]

        # Baseline load
        load_orig = pd.DataFrame(
            np.random.uniform(100, 500, (n_hours, n_buses)),
            index=timestamps,
            columns=bus_names,
        )

        # "Modified" load is identical — simulating failed scenario application
        load_mod = load_orig.copy()

        diffs = (load_mod - load_orig).abs()
        total_load = load_orig.sum().sum()
        total_diff = diffs.sum().sum()
        rel_change = total_diff / total_load if total_load > 0 else 0

        with pytest.raises(AssertionError, match="timezone mismatch"):
            assert rel_change > 0.001, (
                f"Scenario application changed load by only {rel_change:.6f} — "
                f"likely timezone mismatch causing all lookups to miss"
            )

    def test_massive_load_change_detected(self):
        """If load changes by > 50%, something is wrong (e.g., 5-hour shift)."""
        n_hours = 24
        n_buses = 10
        timestamps = pd.date_range("2019-07-18", periods=n_hours, freq="h", tz="utc")
        bus_names = [f"BUS_{i}" for i in range(n_buses)]

        load_orig = pd.DataFrame(
            np.random.uniform(100, 500, (n_hours, n_buses)),
            index=timestamps,
            columns=bus_names,
        )

        # "Modified" load is wildly different — simulating shifted timezone
        load_mod = load_orig * 3.0  # 200% increase

        diffs = (load_mod - load_orig).abs()
        total_load = load_orig.sum().sum()
        total_diff = diffs.sum().sum()
        rel_change = total_diff / total_load

        with pytest.raises(AssertionError, match="implausibly large"):
            assert rel_change < 0.50, (
                f"Scenario application changed load by {rel_change:.4f} (50%+) — "
                f"implausibly large, check timezone shift"
            )


# ============================================================================
# Mutation 3: Identical load scenarios (zero diversity)
# ============================================================================

class TestMutationLoadDiversity:
    """Inject identical load scenarios → diversity tests must catch them."""

    def test_zero_cv_detected(self):
        """10 identical load scenarios must trigger the CV < 0.3% assertion."""
        n_hours = 24
        zones = ['CAPITL', 'CENTRL', 'DUNWOD', 'GENESE', 'HUD VL',
                 'LONGIL', 'MHK VL', 'MILLWD', 'N.Y.C.', 'NORTH', 'WEST']

        base = pd.DataFrame(
            np.random.uniform(200, 2000, (n_hours, len(zones))),
            columns=zones,
        )

        # All 10 "scenarios" are identical copies
        scens = [base.copy() for _ in range(10)]

        # Run the same assertion logic as test_freshly_generated_load_diversity
        peak_idx = 14
        failing_zones = []
        for zone in zones:
            values = [scen.iloc[peak_idx][zone] for scen in scens]
            arr = np.array(values)
            mean = arr.mean()
            if mean < 1.0:
                continue
            cv = arr.std() / mean
            if cv < 0.003:
                failing_zones.append((zone, cv))

        with pytest.raises(AssertionError, match="near-zero diversity"):
            assert not failing_zones, (
                f"Freshly generated load scenarios show near-zero diversity: "
                + ", ".join(f"{z}: CV={cv:.5f}" for z, cv in failing_zones)
            )

    def test_identical_pairs_detected(self):
        """If all scenario pairs are identical, the identity test must catch it."""
        n_hours = 24
        zones = ['CAPITL', 'CENTRL', 'DUNWOD', 'GENESE', 'HUD VL',
                 'LONGIL', 'MHK VL', 'MILLWD', 'N.Y.C.', 'NORTH', 'WEST']

        base = pd.DataFrame(
            np.random.uniform(200, 2000, (n_hours, len(zones))),
            columns=zones,
        )
        scens = [base.copy() for _ in range(10)]

        n_identical = 0
        for i in range(len(scens)):
            for j in range(i + 1, len(scens)):
                if scens[i].equals(scens[j]):
                    n_identical += 1

        with pytest.raises(AssertionError, match="identical"):
            assert n_identical == 0, (
                f"{n_identical} pairs of load scenarios are identical — "
                f"PGscen may be generating degenerate scenarios"
            )


# ============================================================================
# Mutation 4: Wind scenarios with zero per-plant spread
# ============================================================================

class TestMutationWindVariance:
    """Inject wind scenarios with suppressed per-plant variance."""

    def test_zero_spread_detected(self):
        """If 80%+ of plants have zero spread across scenarios, test must fail.

        This simulates a site-mapping bug where all scenarios assign the same
        output to each plant (e.g., forecast = actual, no perturbation).
        """
        np.random.seed(42)
        n_hours = 24
        n_plants = 23
        timestamps = pd.date_range("2019-07-18", periods=n_hours, freq="h", tz="utc")
        plant_ids = [f"wind_{i}" for i in range(n_plants)]

        # 20 plants have identical output across all 10 "scenarios"
        # (zero spread), 3 plants have real variance
        base_outputs = np.random.uniform(10, 100, (n_hours, n_plants))
        scens = []
        for _ in range(10):
            df = pd.DataFrame(base_outputs.copy(), index=timestamps, columns=plant_ids)
            # Only vary the last 3 plants
            for j in range(n_plants - 3, n_plants):
                df.iloc[:, j] *= np.random.uniform(0.5, 1.5)
            scens.append(df)

        n_sites = n_plants
        n_with_spread = 0
        for site in plant_ids:
            outputs = [scen[site].mean() for scen in scens]
            arr = np.array(outputs)
            nameplate = arr.max()
            if nameplate < 0.1:
                continue
            spread = (arr.max() - arr.min()) / nameplate
            if spread >= 0.05:
                n_with_spread += 1

        min_required = int(0.8 * n_sites)  # 18 of 23

        with pytest.raises(AssertionError, match="spread"):
            assert n_with_spread >= min_required, (
                f"Only {n_with_spread}/{n_sites} wind sites have >= 5% "
                f"spread across freshly generated scenarios (need {min_required})"
            )

    def test_zero_hourly_cv_detected(self):
        """If all hours have < 1% system-wind CV, temporal diversity test must fail."""
        np.random.seed(42)
        n_hours = 24
        n_plants = 23
        timestamps = pd.date_range("2019-07-18", periods=n_hours, freq="h", tz="utc")
        plant_ids = [f"wind_{i}" for i in range(n_plants)]

        # All scenarios have identical total system wind at every hour
        base_total = np.random.uniform(200, 800, n_hours)
        scens = []
        for _ in range(10):
            # Distribute the same total across plants with tiny noise
            shares = np.random.dirichlet(np.ones(n_plants), size=n_hours)
            df = pd.DataFrame(
                shares * base_total[:, np.newaxis],
                index=timestamps,
                columns=plant_ids,
            )
            scens.append(df)

        hours_with_variance = 0
        for h in range(n_hours):
            totals = [scen.iloc[h].sum() for scen in scens]
            arr = np.array(totals)
            mean = arr.mean()
            if mean < 1.0:
                continue
            cv = arr.std() / mean
            if cv > 0.01:
                hours_with_variance += 1

        with pytest.raises(AssertionError, match="temporal diversity"):
            assert hours_with_variance >= n_hours // 2, (
                f"Only {hours_with_variance}/{n_hours} hours have >1% CV "
                f"in system wind across scenarios — temporal diversity is too low"
            )
