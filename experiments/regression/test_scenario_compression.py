"""Test 1: Scenario compression detection.

Bug class: Scalar compression.
When PGscen scenarios are generated incorrectly (e.g., system-level scaling
instead of per-plant trajectories), all wind plants in a scenario move in
lockstep — a single scalar multiplied across all sites. This destroys spatial
correlation structure and makes scenario-based analysis meaningless.

Guard: For any two arbitrary scenarios, per-plant Pearson correlation across
wind generators must show genuine spatial diversity, not scalar lockstep.
"""

import numpy as np
import pandas as pd
import pytest

from conftest import SCENARIO_DIR, generate_n_wind_scenarios


class TestScenarioCompression:
    """Detect scalar compression in wind scenarios."""

    def test_pregenerated_scenario_correlation(self, scenario_parquets):
        """Two pre-generated scenarios must not be scalar copies of each other.

        For each pair of consecutive scenarios, pivot wind data into
        (timestamp × plant) matrices and compute per-plant Pearson correlation.
        If all correlations are > 0.95, the scenarios are scalar multiples.
        """
        day = pd.Timestamp("2019-07-18", tz="utc")
        day_end = day + pd.Timedelta(days=1)

        for i in range(min(4, len(scenario_parquets) - 1)):
            scen_a = scenario_parquets[i]
            scen_b = scenario_parquets[i + 1]

            def _pivot_wind(scen):
                wind = scen[scen["asset_type"] == "wind"].reset_index()
                wind = wind[
                    (wind["timestamp"] >= day) & (wind["timestamp"] < day_end)
                ]
                return wind.pivot(
                    index="timestamp", columns="asset_id", values="value_mw"
                )

            wa = _pivot_wind(scen_a)
            wb = _pivot_wind(scen_b)

            # Per-plant correlation between scenario A and B
            corrs = wa.corrwith(wb)
            valid = corrs.dropna()

            # Primary assertion: max correlation must be < 0.95
            assert valid.max() < 0.95, (
                f"Scenarios {i} and {i+1}: max per-plant correlation "
                f"= {valid.max():.4f} >= 0.95 — likely scalar compression"
            )

            # Secondary assertion: at least 2 of top-5 plants have |r| < 0.7
            # (With 24 hourly samples per plant, correlation estimates are
            # noisy — a threshold of 2/5 catches true scalar compression
            # while tolerating sampling variance)
            top5 = valid.abs().nlargest(5)
            n_diverse = (top5 < 0.7).sum()
            assert n_diverse >= 2, (
                f"Scenarios {i} and {i+1}: only {n_diverse}/5 top-correlated "
                f"plants have |r| < 0.7 — insufficient spatial diversity"
            )

    def test_freshly_generated_scenario_correlation(self, pgscen_wind_data):
        """Freshly generated wind scenarios must not be scalar copies.

        Generates 5 scenarios with PGscen and checks the same correlation
        structure as above. This tests the current PGscen code path, not
        just archived outputs.
        """
        wind_actuals, wind_forecasts, wind_meta = pgscen_wind_data
        scens = generate_n_wind_scenarios(
            wind_actuals, wind_forecasts, wind_meta,
            day_str="2019-07-18", n_scenarios=5, seed=123
        )

        for i in range(len(scens) - 1):
            corrs = scens[i].corrwith(scens[i + 1])
            valid = corrs.dropna()

            assert valid.max() < 0.95, (
                f"Fresh scenarios {i} vs {i+1}: max correlation "
                f"= {valid.max():.4f} — scalar compression detected"
            )

            top5 = valid.abs().nlargest(5)
            n_diverse = (top5 < 0.7).sum()
            assert n_diverse >= 2, (
                f"Fresh scenarios {i} vs {i+1}: only {n_diverse}/5 "
                f"top plants have |r| < 0.7"
            )

    def test_within_scenario_plant_independence(self, pgscen_wind_data):
        """Within a single scenario, wind plants must not be perfectly correlated.

        If all plants within one scenario move identically (same shape, different
        scale), that's also scalar compression — just applied at generation time.
        """
        wind_actuals, wind_forecasts, wind_meta = pgscen_wind_data
        scens = generate_n_wind_scenarios(
            wind_actuals, wind_forecasts, wind_meta,
            day_str="2019-07-18", n_scenarios=3, seed=456
        )

        for idx, scen in enumerate(scens):
            # Correlation matrix among all plants within this scenario
            corr_matrix = scen.corr()
            # Exclude diagonal
            np.fill_diagonal(corr_matrix.values, np.nan)
            max_corr = corr_matrix.max().max()

            assert max_corr < 0.99, (
                f"Scenario {idx}: max within-scenario plant correlation "
                f"= {max_corr:.4f} — plants are moving in lockstep"
            )
