"""Test 2: Timezone alignment between PGscen scenarios and NyisoLoader baseline.

Bug class: HRRR timezone mismatch.
PGscen wind data (HRRR-derived) uses UTC, but the original PGscen standard
data used EST-like 06:00 UTC starts. If the scenario-application code doesn't
align timezones correctly, scenario perturbations land on the wrong hours —
shifting load/wind peaks by 5–6 hours and producing nonsensical results.

Guard: After applying a scenario to NyisoLoader baseline timeseries, the
modified values must differ meaningfully from the baseline at the same
timestamps (not shifted), and the magnitude of differences must be plausible
(0.5%–50% for load, measurable for wind).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from conftest import (
    PROJECT_ROOT, SCENARIO_DIR, generate_n_load_scenarios,
    generate_n_wind_scenarios,
)

# Import the scenario application function from experiment 001
EXP_DIR = PROJECT_ROOT / "experiments" / "001_stochastic_vs_deterministic_jul2019"
sys.path.insert(0, str(EXP_DIR))


class TestTimezoneAlignment:
    """Verify timezone consistency across the PGscen → NyisoLoader boundary."""

    def test_load_baseline_and_scenario_share_timezone(
        self, nyiso_loader, nyiso_timeseries, pgscen_load_data
    ):
        """Load baseline (NyisoLoader) and PGscen scenarios must share UTC.

        If the baseline is UTC but scenarios are naive (or EST), the ratio
        computation in _apply_scenario_to_timeseries will silently produce
        ratio=1.0 for all hours (baseline lookup miss), meaning scenarios
        are never applied.
        """
        gen_data, load_data = nyiso_timeseries

        # NyisoLoader timeseries must be UTC
        assert load_data.index.tz is not None, (
            "NyisoLoader load_data has no timezone — should be UTC"
        )
        assert str(load_data.index.tz) == "UTC", (
            f"NyisoLoader load_data timezone is {load_data.index.tz}, not UTC"
        )

        # PGscen load actuals must also be UTC
        load_actuals, _ = pgscen_load_data
        assert load_actuals.index.tz is not None, (
            "PGscen load actuals have no timezone"
        )
        assert str(load_actuals.index.tz) == "UTC", (
            f"PGscen load timezone is {load_actuals.index.tz}, not UTC"
        )

    def test_wind_baseline_and_scenario_share_timezone(
        self, nyiso_timeseries, pgscen_wind_data
    ):
        """Wind baseline and HRRR scenarios must both be UTC.

        The HRRR data files are explicitly named *_utc.csv. If PGscen
        returns naive timestamps, the per-site override in
        _apply_scenario_to_timeseries will skip all hours.
        """
        gen_data, _ = nyiso_timeseries

        assert gen_data.index.tz is not None, (
            "NyisoLoader gen_data has no timezone"
        )
        assert str(gen_data.index.tz) == "UTC", (
            f"NyisoLoader gen_data timezone is {gen_data.index.tz}, not UTC"
        )

        # PGscen wind actuals
        wind_actuals, _, _ = pgscen_wind_data
        assert wind_actuals.index.tz is not None, (
            "PGscen wind actuals have no timezone"
        )
        assert str(wind_actuals.index.tz) == "UTC"

    def test_scenario_application_changes_load(
        self, nyiso_loader, nyiso_timeseries, scenario_parquets
    ):
        """Applying a scenario to load_data must produce nonzero changes.

        If timezone mismatch causes all lookups to miss, load_data stays
        identical to the baseline (ratio=1.0 everywhere). This test catches
        that silent failure.
        """
        from run import _apply_scenario_to_timeseries

        gen_data, load_data = nyiso_timeseries
        scen_df = scenario_parquets[0]
        day_date = pd.Timestamp("2019-07-18").date()

        import datetime
        day_date = datetime.date(2019, 7, 18)

        cfg = {
            "_experiment_dir": str(EXP_DIR),
            "vatic": {
                "pgscen_dir": "../../PGscen-2nd/data/NYISO_real",
            },
        }

        gen_mod, load_mod = _apply_scenario_to_timeseries(
            gen_data, load_data, scen_df, day_date, nyiso_loader, cfg
        )

        # Focus on the target day hours
        day_start = pd.Timestamp("2019-07-18", tz="utc")
        day_end = day_start + pd.Timedelta(days=1)
        mask = (load_mod.index >= day_start) & (load_mod.index < day_end)

        load_orig = load_data.loc[mask, "fcst"]
        load_new = load_mod.loc[mask, "fcst"]

        # Compute relative change across all buses and hours
        diffs = (load_new - load_orig).abs()
        total_load = load_orig.sum().sum()
        total_diff = diffs.sum().sum()
        rel_change = total_diff / total_load if total_load > 0 else 0

        assert rel_change > 0.001, (
            f"Scenario application changed load by only {rel_change:.6f} — "
            f"likely timezone mismatch causing all lookups to miss"
        )
        assert rel_change < 0.50, (
            f"Scenario application changed load by {rel_change:.4f} (50%+) — "
            f"implausibly large, check timezone shift"
        )

    def test_scenario_application_changes_wind(
        self, nyiso_loader, nyiso_timeseries, scenario_parquets
    ):
        """Applying a scenario must change wind gen_data for at least some plants."""
        from run import _apply_scenario_to_timeseries

        gen_data, load_data = nyiso_timeseries
        scen_df = scenario_parquets[0]

        import datetime
        day_date = datetime.date(2019, 7, 18)

        cfg = {
            "_experiment_dir": str(EXP_DIR),
            "vatic": {
                "pgscen_dir": "../../PGscen-2nd/data/NYISO_real",
            },
        }

        gen_mod, _ = _apply_scenario_to_timeseries(
            gen_data, load_data, scen_df, day_date, nyiso_loader, cfg
        )

        day_start = pd.Timestamp("2019-07-18", tz="utc")
        day_end = day_start + pd.Timedelta(days=1)
        mask = (gen_mod.index >= day_start) & (gen_mod.index < day_end)

        # Find wind generators
        wind_cols = [c for c in gen_mod.columns
                     if c[1].startswith("NYISO_W_")]

        if not wind_cols:
            pytest.skip("No wind generators found in gen_data")

        wind_orig = gen_data.loc[mask, wind_cols]
        wind_new = gen_mod.loc[mask, wind_cols]

        diffs = (wind_new - wind_orig).abs()
        n_changed = (diffs.sum(axis=0) > 0.01).sum()

        assert n_changed >= 5, (
            f"Only {n_changed} wind generators changed after scenario "
            f"application — expected most of 23 sites to change"
        )
