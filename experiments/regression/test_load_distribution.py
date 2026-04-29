"""Regression test: bus-level load distribution matches NYISO zonal totals.

Tests that NyisoLoader.create_timeseries() distributes zonal load to buses
without losing load due to bus name collisions or other mapping errors.

Bug history: prior to 2026-04-28, four bus pairs sharing names (ROCHESTER,
RAMAPO, HUNTLEY, GARDENVILLE) caused dict key overwrites in the bzf mapping,
silently dropping 1,374 MW (4.7%) of system load. Zone B (GENESE) lost 69.7%.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "Vatic"))

ZONES = ['CAPITL', 'CENTRL', 'DUNWOD', 'GENESE', 'HUD VL', 'LONGIL',
         'MHK VL', 'MILLWD', 'N.Y.C.', 'NORTH', 'WEST']
PGSCEN_DIR = str(PROJECT_ROOT / 'PGscen-2nd' / 'data' / 'NYISO_real')
LOAD_ACTUAL_PATH = (PROJECT_ROOT / 'PGscen-2nd' / 'data' / 'NYISO_real' /
                    'load_actual_1h_zone_2018_2019_2020_2021_2022_2023_2024_2025_utc.csv')
LOAD_FCST_PATH = (PROJECT_ROOT / 'PGscen-2nd' / 'data' / 'NYISO_real' /
                  'load_day_ahead_forecast_zone_2018_2019_2020_2021_2022_2023_2024_2025_utc.csv')


@pytest.fixture(scope="module")
def loader_2019():
    from vatic.data.nyiso_loader import NyisoLoader
    return NyisoLoader(
        use_reduced_network=True,
        fuel_price_date='2019-07-17',
        pgscen_dir=PGSCEN_DIR,
        year=2019,
    )


@pytest.fixture(scope="module")
def timeseries_2019(loader_2019):
    start = pd.Timestamp('2019-07-17', tz='utc')
    end = start + pd.Timedelta(days=2)
    gen_data, load_data = loader_2019.create_timeseries(
        start_date=start, end_date=end)
    return gen_data, load_data


@pytest.fixture(scope="module")
def nyiso_actual():
    la = pd.read_csv(LOAD_ACTUAL_PATH, parse_dates=['Time'])
    la['ts'] = pd.to_datetime(la['Time'], utc=True).dt.tz_localize(None)
    return la.set_index('ts')


@pytest.fixture(scope="module")
def nyiso_forecast():
    lf = pd.read_csv(LOAD_FCST_PATH, parse_dates=['Forecast_time'])
    lf = lf.drop(columns=['Issue_time']).set_index('Forecast_time')
    lf.index = pd.to_datetime(lf.index, utc=True).tz_localize(None)
    return lf


def test_total_load_matches_nyiso_actual(timeseries_2019, nyiso_actual):
    """Bus-distributed actual load must match NYISO zonal actual within 1%."""
    _, load_data = timeseries_2019
    actl_cols = [c for c in load_data.columns if c[0] == 'actl']

    ts = pd.Timestamp('2019-07-17 20:00:00', tz='utc')
    loader_total = float(load_data.loc[ts, actl_cols].sum())
    nyiso_total = float(nyiso_actual.loc[
        pd.Timestamp('2019-07-17 20:00:00'), ZONES].sum())

    pct_diff = abs(loader_total - nyiso_total) / nyiso_total * 100
    assert pct_diff < 1.0, (
        f"Loader actual load {loader_total:.0f} MW differs from NYISO "
        f"actual {nyiso_total:.0f} MW by {pct_diff:.1f}% (threshold 1%). "
        f"Bus name collision bug may have reappeared."
    )


def test_total_load_matches_nyiso_forecast(timeseries_2019, nyiso_forecast):
    """Bus-distributed forecast load must match NYISO DA forecast within 1%."""
    _, load_data = timeseries_2019
    fcst_cols = [c for c in load_data.columns if c[0] == 'fcst']

    ts = pd.Timestamp('2019-07-17 20:00:00', tz='utc')
    loader_total = float(load_data.loc[ts, fcst_cols].sum())
    nyiso_total = float(nyiso_forecast.loc[
        pd.Timestamp('2019-07-17 20:00:00'), ZONES].sum())

    pct_diff = abs(loader_total - nyiso_total) / nyiso_total * 100
    assert pct_diff < 1.0, (
        f"Loader forecast load {loader_total:.0f} MW differs from NYISO "
        f"DA forecast {nyiso_total:.0f} MW by {pct_diff:.1f}%."
    )


def test_no_zone_loses_significant_load(timeseries_2019, nyiso_actual, loader_2019):
    """No individual zone should lose more than 2% of its load."""
    from vatic.data.nyiso_loader import _ZONE_NAME_TO_LETTER, _ROOT

    _, load_data = timeseries_2019
    actl_cols = [c for c in load_data.columns if c[0] == 'actl']
    ts = pd.Timestamp('2019-07-17 20:00:00', tz='utc')

    # Build zone -> bus_names mapping from the loader
    renew = pd.read_csv(Path(_ROOT, '..', '..', '..', 'third_party',
                             'NYgrid', 'Data', 'RenewableGen.csv'))
    bus_name_by_id = {b.ID: b.Name for b in loader_2019.buses}
    bus_set = set(loader_2019.template['Buses'])
    letter_to_name = {v: k for k, v in _ZONE_NAME_TO_LETTER.items()
                      if len(k) > 1}

    zone_buses = {}  # zone_letter -> set of bus names
    for _, r in renew.iterrows():
        bid = int(r['bus_id']); z = r['Zone']; lv = r['Load']
        if pd.notna(lv) and lv > 0:
            n = bus_name_by_id.get(bid)
            if n and n in bus_set:
                zone_buses.setdefault(z, set()).add(n)

    for zone_letter, bus_names in zone_buses.items():
        zone_name = letter_to_name.get(zone_letter)
        if not zone_name:
            continue

        bus_total = sum(
            float(load_data.loc[ts, ('actl', bn)])
            for bn in bus_names
            if ('actl', bn) in load_data.columns
        )
        nyiso_zone = float(nyiso_actual.loc[
            pd.Timestamp('2019-07-17 20:00:00'), zone_name])

        if nyiso_zone < 100:  # skip tiny zones
            continue

        pct_diff = abs(bus_total - nyiso_zone) / nyiso_zone * 100
        assert pct_diff < 2.0, (
            f"Zone {zone_letter} ({zone_name}): loader {bus_total:.0f} MW "
            f"vs NYISO {nyiso_zone:.0f} MW = {pct_diff:.1f}% diff. "
            f"Bus name collision may affect this zone."
        )


def test_load_fractions_sum_to_one(loader_2019):
    """Per-zone load participation factors must sum to ~1.0."""
    from vatic.data.nyiso_loader import _ROOT

    renew = pd.read_csv(Path(_ROOT, '..', '..', '..', 'third_party',
                             'NYgrid', 'Data', 'RenewableGen.csv'))
    bus_name_by_id = {b.ID: b.Name for b in loader_2019.buses}
    bus_set = set(loader_2019.template['Buses'])

    bz, bs = {}, {}
    for _, r in renew.iterrows():
        bid = int(r['bus_id']); z = r['Zone']; lv = r['Load']
        if pd.notna(lv) and lv > 0:
            bz[bid] = z; bs[bid] = lv
    zt = {}
    for bid, s in bs.items():
        zt[bz[bid]] = zt.get(bz[bid], 0) + s

    # Accumulate fractions per zone (mimicking fixed code)
    zone_frac_sum = {}
    for bid, s in bs.items():
        n = bus_name_by_id.get(bid)
        if n and n in bus_set:
            z = bz[bid]
            zone_frac_sum[z] = zone_frac_sum.get(z, 0) + s / zt[z]

    for z, frac_sum in zone_frac_sum.items():
        assert abs(frac_sum - 1.0) < 0.01, (
            f"Zone {z}: load fractions sum to {frac_sum:.4f}, not 1.0. "
            f"Some bus load is being lost."
        )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
