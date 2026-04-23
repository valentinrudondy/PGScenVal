"""Test 5: Load scenario diversity across zones.

Bug class: Load scenarios never applied.
In an earlier version, the load scenario application path silently failed —
the baseline load was passed through unchanged to every scenario. All 100
stochastic runs used identical load, eliminating the demand uncertainty
that's the entire point of stochastic UC. The symptom: zero variance in
load across scenarios.

Guard: Generate 10 load scenarios for a single day. For each of the 11 NYISO
zones, the coefficient of variation (CV) across the 10 scenarios must be
at least 0.3%, confirming that scenarios represent real demand uncertainty.
"""

import numpy as np
import pandas as pd
import pytest

from conftest import SCENARIO_DIR, generate_n_load_scenarios


class TestLoadDiversity:
    """Verify load scenarios exhibit meaningful zonal diversity."""

    def test_pregenerated_load_cv(self, scenario_parquets):
        """Pre-generated scenarios must show per-zone load variation.

        For a single hour, compute the CV of load across 10 scenarios
        for each NYISO zone. CV < 0.3% means the scenarios are
        effectively identical — load perturbations are not being applied.
        """
        day = pd.Timestamp("2019-07-18", tz="utc")

        # Collect load values per zone per scenario for one representative hour
        # (hour 20 UTC = 4 PM EDT, near peak)
        target_hour = day + pd.Timedelta(hours=20)

        zone_values = {}  # zone -> list of values across scenarios
        for scen_df in scenario_parquets[:10]:
            load = scen_df[scen_df["asset_type"] == "load"]
            for zone in load.index.get_level_values("asset_id").unique():
                zone_data = load.xs(zone, level="asset_id")
                # Find the closest timestamp to target_hour
                ts_list = zone_data.index.get_level_values("timestamp")
                if target_hour in ts_list:
                    val = zone_data.loc[target_hour, "value_mw"]
                else:
                    # Try without timezone matching
                    diffs = abs(ts_list - target_hour)
                    closest = ts_list[diffs.argmin()]
                    val = zone_data.loc[closest, "value_mw"]
                zone_values.setdefault(zone, []).append(val)

        assert len(zone_values) >= 11, (
            f"Only {len(zone_values)} zones found in scenarios, expected 11"
        )

        failing_zones = []
        for zone, values in zone_values.items():
            arr = np.array(values)
            mean = arr.mean()
            if mean < 1.0:
                continue  # Skip negligible zones
            cv = arr.std() / mean
            if cv < 0.003:
                failing_zones.append((zone, cv))

        assert not failing_zones, (
            f"Zones with CV < 0.3% (load scenarios not applied): "
            + ", ".join(f"{z}: CV={cv:.5f}" for z, cv in failing_zones)
        )

    def test_freshly_generated_load_diversity(self, pgscen_load_data):
        """Freshly generated load scenarios must have per-zone CV >= 0.3%.

        This tests the current PGscen code, not archived outputs.
        """
        load_actuals, load_forecasts = pgscen_load_data
        scens = generate_n_load_scenarios(
            load_actuals, load_forecasts,
            day_str="2019-07-18", n_scenarios=10, seed=789
        )

        all_zones = scens[0].columns.tolist()
        assert len(all_zones) == 11, (
            f"Expected 11 NYISO zones, got {len(all_zones)}"
        )

        # Check CV at a peak hour (hour 14 in the scenario = 20:00 UTC)
        peak_idx = 14  # roughly 2–3 PM EDT

        failing_zones = []
        for zone in all_zones:
            values = []
            for scen in scens:
                if peak_idx < len(scen):
                    values.append(scen.iloc[peak_idx][zone])
            arr = np.array(values)
            mean = arr.mean()
            if mean < 1.0:
                continue
            cv = arr.std() / mean
            if cv < 0.003:
                failing_zones.append((zone, cv))

        assert not failing_zones, (
            f"Freshly generated load scenarios show near-zero diversity: "
            + ", ".join(f"{z}: CV={cv:.5f}" for z, cv in failing_zones)
        )

    def test_load_scenarios_not_identical(self, pgscen_load_data):
        """No two load scenarios should be identical across all zones and hours.

        This catches the degenerate case where PGscen generates scenarios
        but they all collapse to the forecast (delta=0).
        """
        load_actuals, load_forecasts = pgscen_load_data
        scens = generate_n_load_scenarios(
            load_actuals, load_forecasts,
            day_str="2019-07-18", n_scenarios=10, seed=321
        )

        n_identical = 0
        for i in range(len(scens)):
            for j in range(i + 1, len(scens)):
                if scens[i].equals(scens[j]):
                    n_identical += 1

        assert n_identical == 0, (
            f"{n_identical} pairs of load scenarios are identical — "
            f"PGscen may be generating degenerate scenarios"
        )
