"""Shared fixtures for the NYISO pipeline regression test suite.

All heavy data loading (PGscen historical data, NyisoLoader template) is
session-scoped so the cost is paid once per pytest invocation.
"""

import sys
from pathlib import Path

import pytest
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PGSCEN_DIR = PROJECT_ROOT / "PGscen-2nd"
VATIC_DIR = PROJECT_ROOT / "Vatic"
DATA_DIR = PGSCEN_DIR / "data"
NYISO_REAL_DIR = DATA_DIR / "NYISO_real"
SCENARIO_DIR = (PROJECT_ROOT / "experiments"
                / "001_stochastic_vs_deterministic_jul2019"
                / "results" / "scenarios")

# Ensure importable
sys.path.insert(0, str(PGSCEN_DIR))
sys.path.insert(0, str(VATIC_DIR))


# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------
def pytest_configure(config):
    config.addinivalue_line("markers", "slow: requires a Vatic simulation run")


# ---------------------------------------------------------------------------
# PGscen data fixtures (session-scoped — loaded once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pgscen_load_data():
    """Load actuals and forecasts for NYISO load (11 zones)."""
    from pgscen.utils.data_utils import load_ny_load_data
    actuals, forecasts = load_ny_load_data()
    return actuals, forecasts


@pytest.fixture(scope="session")
def pgscen_wind_data():
    """Load actuals, forecasts, and metadata for NYISO wind (HRRR, 23 sites)."""
    from pgscen.utils.data_utils import load_ny_real_wind_data
    actuals, forecasts, meta = load_ny_real_wind_data(years=[2019])
    return actuals, forecasts, meta


@pytest.fixture(scope="session")
def pgscen_solar_data():
    """Load actuals, forecasts, and metadata for NYISO solar (314 sites)."""
    from pgscen.utils.data_utils import load_ny_solar_data
    actuals, forecasts, meta = load_ny_solar_data()
    return actuals, forecasts, meta


# ---------------------------------------------------------------------------
# NyisoLoader fixture (session-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def nyiso_loader():
    """Build a NyisoLoader for 2019 with Kron-reduced network."""
    from vatic.data.nyiso_loader import NyisoLoader
    loader = NyisoLoader(
        pgscen_dir=str(NYISO_REAL_DIR),
        use_reduced_network=True,
        fuel_price_date="2019-07-18",
        year=2019,
    )
    return loader


@pytest.fixture(scope="session")
def nyiso_timeseries(nyiso_loader):
    """gen_data and load_data for July 18–19 2019 (48 hours for RUC horizon)."""
    start = pd.Timestamp("2019-07-18", tz="utc")
    end = start + pd.Timedelta(days=2)
    gen_data, load_data = nyiso_loader.create_timeseries(start, end)
    return gen_data, load_data


# ---------------------------------------------------------------------------
# Pre-generated scenario files
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def scenario_parquets():
    """Load the first 10 scenario parquet files (if they exist)."""
    if not SCENARIO_DIR.exists():
        pytest.skip("Scenario parquet files not found — run experiment 001 first")
    paths = sorted(SCENARIO_DIR.glob("scenario_*.parquet"))[:10]
    if len(paths) < 2:
        pytest.skip("Need at least 2 scenario parquets for regression tests")
    return [pd.read_parquet(p) for p in paths]


# ---------------------------------------------------------------------------
# Scenario generation helper
# ---------------------------------------------------------------------------

def generate_n_wind_scenarios(wind_actuals, wind_forecasts, wind_meta,
                              day_str, n_scenarios, seed=42):
    """Generate n PGscen wind scenarios for a single day.

    Returns a list of DataFrames, one per scenario, indexed by timestamp
    with columns = site IDs and values = MW.
    """
    from pgscen.utils.data_utils import (
        split_actuals_hist_future,
        split_forecasts_hist_future,
    )
    from pgscen.regime_model import RegimeGeminiEngine

    np.random.seed(seed)

    scen_start = pd.Timestamp(f"{day_str} 00:00:00", tz="utc")
    scen_timesteps = pd.date_range(start=scen_start, periods=24, freq="h")

    actual_hist, _ = split_actuals_hist_future(
        wind_actuals, scen_timesteps, in_sample=True
    )
    forecast_hist, forecast_future = split_forecasts_hist_future(
        wind_forecasts, scen_timesteps, in_sample=True
    )

    engine = RegimeGeminiEngine(
        actual_hist, forecast_hist,
        scen_timesteps[0], wind_meta, asset_type="wind",
        forecast_lead_time_in_hour=18,
    )
    dist = engine.asset_distance().values
    engine.fit(2 * 0.05 * dist / dist.max(), 0.05)
    engine.create_scenario(n_scenarios, forecast_future)
    scens_raw = engine.scenarios["wind"]

    # Reshape: each row is a scenario, columns are (site, timestamp) MultiIndex
    results = []
    for idx in range(n_scenarios):
        row = scens_raw.iloc[idx]
        records = {}
        for (site, ts), val in row.items():
            records.setdefault(ts, {})[site] = max(0, val)
        df = pd.DataFrame(records).T.sort_index()
        df.index.name = "timestamp"
        results.append(df)

    return results


def generate_n_load_scenarios(load_actuals, load_forecasts,
                               day_str, n_scenarios, seed=42):
    """Generate n PGscen load scenarios for a single day.

    Returns a list of DataFrames, one per scenario, indexed by timestamp
    with columns = zone names and values = MW.
    """
    from pgscen.utils.data_utils import (
        split_actuals_hist_future,
        split_forecasts_hist_future,
    )
    from pgscen.regime_model import RegimeGeminiEngine

    np.random.seed(seed)

    scen_start = pd.Timestamp(f"{day_str} 06:00:00", tz="utc")
    scen_timesteps = pd.date_range(start=scen_start, periods=24, freq="h")

    actual_hist, _ = split_actuals_hist_future(
        load_actuals, scen_timesteps, in_sample=False
    )
    forecast_hist, forecast_future = split_forecasts_hist_future(
        load_forecasts, scen_timesteps, in_sample=False
    )

    engine = RegimeGeminiEngine(
        actual_hist, forecast_hist,
        scen_timesteps[0], asset_type="load",
    )
    engine.fit(0.05, 0.05)
    engine.create_scenario(n_scenarios, forecast_future)
    scens_raw = engine.scenarios["load"]

    results = []
    for idx in range(n_scenarios):
        row = scens_raw.iloc[idx]
        records = {}
        for (zone, ts), val in row.items():
            records.setdefault(ts, {})[zone] = max(0, val)
        df = pd.DataFrame(records).T.sort_index()
        df.index.name = "timestamp"
        results.append(df)

    return results
