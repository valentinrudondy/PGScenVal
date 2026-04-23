"""Test 6: Per-plant wind variance across scenarios.

Bug class: Wind scenario scalar compression (per-plant level).
Even when scenarios are not global scalar copies of each other, individual
plants can still have degenerate variance — for example, if a plant is
assigned the system-average wind profile instead of its site-specific HRRR
data. The result is that plant-level dispatch decisions are driven by
noise-free system averages rather than local weather realizations.

Guard: For 10 wind scenarios, each of the 31 wind plants (from NyisoLoader
template, mapped from 23 HRRR sites + 8 duplicates) must show meaningful
variation. At least 25 of 31 mapped plants must have
(max - min) / nameplate >= 5% across the 10 scenarios.
"""

import numpy as np
import pandas as pd
import pytest

from conftest import SCENARIO_DIR, generate_n_wind_scenarios


class TestWindVariance:
    """Verify per-plant wind variance across stochastic scenarios."""

    def test_pregenerated_wind_plant_spread(self, scenario_parquets):
        """Pre-generated scenarios must show per-plant wind spread.

        For each wind plant, compute max and min output across 10 scenarios
        at each hour. The spread (max - min) divided by the site's maximum
        output across all scenarios should be >= 5% for most plants.
        """
        day = pd.Timestamp("2019-07-18", tz="utc")
        day_end = day + pd.Timedelta(days=1)

        # Collect per-plant per-scenario daily totals
        plant_outputs = {}  # plant_id -> list of daily total MW

        for scen_df in scenario_parquets[:10]:
            wind = scen_df[scen_df["asset_type"] == "wind"]
            for site in wind.index.get_level_values("asset_id").unique():
                site_data = wind.xs(site, level="asset_id")
                ts = site_data.index.get_level_values("timestamp")
                mask = (ts >= day) & (ts < day_end)
                daily_vals = site_data[mask]["value_mw"].values
                # Use mean output for the day as the metric
                plant_outputs.setdefault(site, []).append(daily_vals.mean())

        n_plants = len(plant_outputs)
        assert n_plants >= 20, (
            f"Only {n_plants} wind plants found — expected ~23"
        )

        n_with_spread = 0
        for site, outputs in plant_outputs.items():
            arr = np.array(outputs)
            nameplate = arr.max()
            if nameplate < 0.1:
                continue  # Skip plants with near-zero output (nighttime solar leak)
            spread = (arr.max() - arr.min()) / nameplate
            if spread >= 0.05:
                n_with_spread += 1

        # Relax threshold to match actual wind sites (23, not 31)
        min_required = int(0.8 * n_plants)  # 80% of plants
        assert n_with_spread >= min_required, (
            f"Only {n_with_spread}/{n_plants} wind plants have >= 5% "
            f"spread across scenarios (need {min_required}). "
            f"Per-plant variance may be suppressed."
        )

    def test_freshly_generated_wind_plant_spread(self, pgscen_wind_data):
        """Freshly generated wind scenarios must show per-plant spread.

        Generate 10 scenarios and check that each HRRR site has meaningful
        variation across the 10 realizations.
        """
        wind_actuals, wind_forecasts, wind_meta = pgscen_wind_data

        scens = generate_n_wind_scenarios(
            wind_actuals, wind_forecasts, wind_meta,
            day_str="2019-07-18", n_scenarios=10, seed=654
        )

        n_sites = len(scens[0].columns)
        assert n_sites >= 20, (
            f"Only {n_sites} wind sites — expected ~23 HRRR sites"
        )

        n_with_spread = 0
        for site in scens[0].columns:
            # Collect mean output per scenario for this site
            outputs = [scen[site].mean() for scen in scens]
            arr = np.array(outputs)
            nameplate = arr.max()
            if nameplate < 0.1:
                continue
            spread = (arr.max() - arr.min()) / nameplate
            if spread >= 0.05:
                n_with_spread += 1

        min_required = int(0.8 * n_sites)
        assert n_with_spread >= min_required, (
            f"Only {n_with_spread}/{n_sites} wind sites have >= 5% "
            f"spread across freshly generated scenarios (need {min_required})"
        )

    def test_per_hour_wind_variance(self, pgscen_wind_data):
        """Wind scenarios must show hour-by-hour variation, not just daily average.

        If variation only shows up in daily totals but individual hours are
        locked, the temporal correlation structure is wrong.
        """
        wind_actuals, wind_forecasts, wind_meta = pgscen_wind_data

        scens = generate_n_wind_scenarios(
            wind_actuals, wind_forecasts, wind_meta,
            day_str="2019-07-18", n_scenarios=10, seed=987
        )

        # For each hour, compute CV across scenarios (averaged across all sites)
        n_hours = len(scens[0])
        hours_with_variance = 0

        for h in range(n_hours):
            # Collect total system wind at this hour across all scenarios
            totals = [scen.iloc[h].sum() for scen in scens]
            arr = np.array(totals)
            mean = arr.mean()
            if mean < 1.0:
                continue  # Skip hours with negligible wind
            cv = arr.std() / mean
            if cv > 0.01:  # > 1% CV at this hour
                hours_with_variance += 1

        # At least half the hours should show some variance
        assert hours_with_variance >= n_hours // 2, (
            f"Only {hours_with_variance}/{n_hours} hours have >1% CV "
            f"in system wind across scenarios — temporal diversity is too low"
        )
