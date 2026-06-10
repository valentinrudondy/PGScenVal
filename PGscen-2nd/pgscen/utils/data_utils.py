"""Utilities for parsing ERCOT/NREL actual and forecast datasets."""

from pathlib import Path
import pandas as pd
import bz2
try:
    import dill as pickle
except ModuleNotFoundError:
    import pickle

data_path = Path(Path(__file__).parent.parent.parent, 'data')
test_path = Path(Path(__file__).parent.parent.parent, 'test', 'resources')


def split_actuals_hist_future(actual_df, scenario_timesteps, in_sample=False):
    ts0 = scenario_timesteps[0]
    # Align timezone info to allow comparison
    if hasattr(ts0, 'tzinfo') and ts0.tzinfo is not None and actual_df.index.tz is None:
        ts0 = ts0.tz_localize(None)
        scenario_timesteps = [t.tz_localize(None) if hasattr(t, 'tz_localize') else t
                              for t in scenario_timesteps]
    elif (not hasattr(ts0, 'tzinfo') or ts0.tzinfo is None) and actual_df.index.tz is not None:
        ts0 = pd.Timestamp(ts0, tz=actual_df.index.tz)

    if in_sample:
        hist_index = ~actual_df.index.isin(scenario_timesteps)
    else:
        hist_index = actual_df.index < ts0

    return actual_df[hist_index], actual_df[~hist_index]


def split_forecasts_hist_future(forecast_df, scenario_timesteps,
                                in_sample=False):
    ts0 = scenario_timesteps[0]
    # Align timezone info to allow comparison
    if hasattr(ts0, 'tzinfo') and ts0.tzinfo is not None and forecast_df.Forecast_time.dt.tz is None:
        ts0 = ts0.tz_localize(None)
        scenario_timesteps = [t.tz_localize(None) if hasattr(t, 'tz_localize') else t
                              for t in scenario_timesteps]
    elif (not hasattr(ts0, 'tzinfo') or ts0.tzinfo is None) and forecast_df.Forecast_time.dt.tz is not None:
        ts0 = pd.Timestamp(ts0, tz=forecast_df.Forecast_time.dt.tz)

    if in_sample:
        hist_index = ~forecast_df.Forecast_time.isin(scenario_timesteps)
    else:
        hist_index = forecast_df.Forecast_time < ts0

    return forecast_df[hist_index], forecast_df[~hist_index]


################################ ERCOT ########################################
def load_load_data(test=False):
    if test:
        with bz2.BZ2File(Path(test_path, 'load.p.gz'), 'rb') as f:
            data = pickle.load(f)
        return data[0], data[1]
    else:
        load_zone_actual_df = pd.read_csv(
            Path(data_path, 'ERCOT', 'Load', 'Actual',
                 'load_actual_1h_zone_2017_2018_utc.csv'),
            parse_dates=['Time'], index_col='Time'
            )

        load_zone_forecast_df = pd.read_csv(
            Path(data_path, 'ERCOT', 'Load', 'Day-ahead',
                 'load_day_ahead_forecast_zone_2017_2018_utc.csv'),
            parse_dates=['Issue_time', 'Forecast_time']
            )

        return load_zone_actual_df, load_zone_forecast_df


def load_wind_data(test=False):
    if test:
        with bz2.BZ2File(Path(test_path, 'wind.p.gz'), 'rb') as f:
            data = pickle.load(f)
        return data[0], data[1], data[2]
    else:
        wind_site_actual_df = pd.read_csv(
            Path(data_path, 'ERCOT', 'Wind', 'Actual',
                 'wind_actual_1h_site_2017_2018_utc.csv'),
            parse_dates=['Time'], index_col='Time'
            )

        wind_site_forecast_df = pd.read_csv(
            Path(data_path, 'ERCOT', 'Wind', 'Day-ahead',
                 'wind_day_ahead_forecast_site_2018_utc.csv'),
            parse_dates=['Issue_time', 'Forecast_time']
            )

        wind_meta_df = pd.read_excel(Path(data_path, 'ERCOT', 'MetaData', 'wind_meta.xlsx'))

        return wind_site_actual_df, wind_site_forecast_df, wind_meta_df


def load_solar_data(test=False):
    if test:
        with bz2.BZ2File(Path(test_path, 'solar.p.gz'), 'rb') as f:
            data = pickle.load(f)
        return data[0], data[1], data[2]
    else:
        solar_site_actual_df = pd.read_csv(
            Path(data_path, 'ERCOT', 'Solar', 'Actual',
                 'solar_actual_1h_site_2017_2018_utc.csv'),
            parse_dates=['Time'], index_col='Time'
            )

        solar_site_forecast_df = pd.read_csv(
            Path(data_path, 'ERCOT', 'Solar', 'Day-ahead',
                 'solar_day_ahead_forecast_site_2017_2018_utc.csv'),
            parse_dates=['Issue_time', 'Forecast_time']
            )

        solar_meta_df = pd.read_excel(
            Path(data_path, 'ERCOT', 'MetaData', 'solar_meta.xlsx'))

        return solar_site_actual_df, solar_site_forecast_df, solar_meta_df

################################ NYISO ##########################################
def load_ny_load_data():
    load_zone_actual_df = pd.read_csv(
        Path(data_path, 'NYISO', 'Load', 'Actual',
             'load_actual_1h_zone_2018_2019_utc.csv'),
        parse_dates=['Time'], index_col='Time'
        )

    load_zone_forecast_df = pd.read_csv(
        Path(data_path, 'NYISO', 'Load', 'Day-ahead',
             'load_day_ahead_forecast_zone_2018_2019_utc.csv'),
        parse_dates=['Issue_time', 'Forecast_time']
        )

    return load_zone_actual_df, load_zone_forecast_df


def load_ny_wind_data():
    wind_site_actual_df = pd.read_csv(
        Path(data_path, 'NYISO', 'Wind', 'Actual',
             'wind_actual_1h_site_2019_utc.csv'),
        parse_dates=['Time'], index_col='Time'
        )

    wind_site_forecast_df = pd.read_csv(
        Path(data_path, 'NYISO', 'Wind', 'Day-ahead',
             'wind_day_ahead_forecast_site_2019_utc.csv'),
        parse_dates=['Issue_time', 'Forecast_time']
        )

    wind_meta_df = pd.read_csv(Path(data_path, 'NYISO', 'MetaData', 'wind_meta.csv'))

    return wind_site_actual_df, wind_site_forecast_df, wind_meta_df


def load_ny_solar_data():
    solar_site_actual_df = pd.read_csv(
        Path(data_path, 'NYISO', 'Solar', 'Actual',
             'solar_actual_1h_site_2018_2019_utc.csv'),
        parse_dates=['Time'], index_col='Time'
        )

    solar_site_forecast_df = pd.read_csv(
        Path(data_path, 'NYISO', 'Solar', 'Day-ahead',
             'solar_day_ahead_forecast_site_2018_2019_utc.csv'),
        parse_dates=['Issue_time', 'Forecast_time']
        )

    solar_meta_df = pd.read_csv(
        Path(data_path, 'NYISO', 'MetaData', 'solar_meta.csv'))

    return solar_site_actual_df, solar_site_forecast_df, solar_meta_df


################################ NYISO Real (HRRR-derived) #####################

def load_ny_real_wind_data(years=None, use_raw_forecast=False, variant='pluswind_v3'):
    """Load HRRR-derived wind actuals, forecasts, and metadata.

    Parameters
    ----------
    years : list[int] or None
        Years to load (e.g., [2019, 2020]). If None, loads all available.
    use_raw_forecast : bool
        If True, load the raw (pre-MOS) forecast backups instead of the
        MOS-corrected forecasts.
    variant : str
        Physics variant suffix. Default 'pluswind_v3' reads the production
        files (HRRR + density correction + per-plant SAM curve + 7% loss,
        validated in notebooks/01_validate_forecast_calibration.ipynb).
        Pass '' (empty string) to read the legacy files.

    Returns
    -------
    (actual_df, forecast_df, meta_df) matching the PGScen engine interface.
    """
    wind_dir = Path(data_path, 'NYISO_real', 'wind')
    meta_path = Path(data_path, 'NYISO_real', 'plant_metadata', 'wind_meta.csv')
    suffix = f'.{variant}' if variant else ''

    if years is None:
        pattern = f'wind_actual_1h_site_*_utc{suffix}.csv'
        actual_files = sorted(wind_dir.glob(pattern))
        # filename stem looks like 'wind_actual_1h_site_2024_utc.pluswind_v3'
        # so year is the 5th underscore-delimited token
        years = [int(f.name.split('_')[4]) for f in actual_files]

    # Load and concatenate actuals
    actual_dfs = []
    for y in years:
        df = pd.read_csv(
            Path(wind_dir, f'wind_actual_1h_site_{y}_utc{suffix}.csv'),
            parse_dates=['Time'], index_col='Time')
        actual_dfs.append(df)
    actual_df = pd.concat(actual_dfs).sort_index()
    actual_df = actual_df[~actual_df.index.duplicated(keep='first')]
    actual_df = actual_df.fillna(0.0)
    actual_df = actual_df[actual_df.sum(axis=1).notna()]

    # Load and concatenate forecasts
    forecast_dfs = []
    for y in years:
        if use_raw_forecast:
            fc_path = Path(wind_dir,
                           f'wind_day_ahead_forecast_site_{y}_utc{suffix}.csv.raw_backup')
            if not fc_path.exists():
                fc_path = Path(wind_dir,
                               f'wind_day_ahead_forecast_site_{y}_utc{suffix}.csv')
        else:
            fc_path = Path(wind_dir,
                           f'wind_day_ahead_forecast_site_{y}_utc{suffix}.csv')
        df = pd.read_csv(fc_path,
            parse_dates=['Issue_time', 'Forecast_time'])
        forecast_dfs.append(df)
    forecast_df = pd.concat(forecast_dfs, ignore_index=True)
    forecast_df = forecast_df.fillna(0.0)
    forecast_df = forecast_df.drop_duplicates(
        subset=['Issue_time', 'Forecast_time'], keep='first')

    # Normalize Issue_time: PGScen expects 24 rows per Issue_time.
    # Our data has 19 rows from 06Z and 5 from 12Z per day.
    # Set all to 06Z of the day before the forecast date for consistency.
    forecast_df['Issue_time'] = (
        forecast_df['Forecast_time'].dt.normalize() - pd.Timedelta(hours=18)
    )

    # Load metadata and transform to engine format
    # Engine expects: Facility.Name, longi, lati, Capacity
    raw_meta = pd.read_csv(meta_path)
    meta_df = pd.DataFrame({
        'Facility.Name': raw_meta['site_id'],
        'longi': raw_meta['longitude'],
        'lati': raw_meta['latitude'],
        'Capacity': raw_meta['nameplate_mw'],
    })

    # Only include plants that appear in the actual data columns
    meta_df = meta_df[meta_df['Facility.Name'].isin(actual_df.columns)]

    return actual_df, forecast_df, meta_df


def load_ny_real_solar_data(years=None, use_raw_forecast=True):
    """Load HRRR-derived solar actuals, forecasts, and metadata.

    Parameters
    ----------
    years : list[int] or None
        Years to load (e.g., [2019, 2020]). If None, loads all available.
    use_raw_forecast : bool
        If True (default), load the raw (pre-MOS) HRRR-pvlib forecast.
        If False, load the MOS bias-corrected variant. Default is True
        because the production NYISO solar pipeline (decision recorded
        in docs/Solar_Modeling_Decision.md) is B1-raw: MOS has not been
        validated out-of-sample for solar, and the engine should see
        the true forecast-error distribution for residual modelling.

    Returns
    -------
    (actual_df, forecast_df, meta_df) matching the PGScen engine interface.
    """
    solar_dir = Path(data_path, 'NYISO_real', 'solar')
    meta_path = Path(data_path, 'NYISO_real', 'plant_metadata', 'solar_meta.csv')

    if years is None:
        actual_files = sorted(solar_dir.glob('solar_actual_1h_site_*_utc.csv'))
        years = [int(f.stem.split('_')[-2]) for f in actual_files]

    # Load and concatenate actuals
    actual_dfs = []
    for y in years:
        df = pd.read_csv(
            Path(solar_dir, f'solar_actual_1h_site_{y}_utc.csv'),
            parse_dates=['Time'], index_col='Time')
        actual_dfs.append(df)
    actual_df = pd.concat(actual_dfs).sort_index()
    actual_df = actual_df[~actual_df.index.duplicated(keep='first')]
    actual_df = actual_df.fillna(0.0)

    # Load and concatenate forecasts
    forecast_dfs = []
    for y in years:
        if use_raw_forecast:
            fc_path = Path(solar_dir,
                           f'solar_day_ahead_forecast_site_{y}_utc.csv.raw_backup')
            if not fc_path.exists():
                fc_path = Path(solar_dir,
                               f'solar_day_ahead_forecast_site_{y}_utc.csv')
        else:
            fc_path = Path(solar_dir,
                           f'solar_day_ahead_forecast_site_{y}_utc.csv')
        df = pd.read_csv(fc_path, parse_dates=['Issue_time', 'Forecast_time'])
        forecast_dfs.append(df)
    forecast_df = pd.concat(forecast_dfs, ignore_index=True)
    forecast_df = forecast_df.fillna(0.0)
    forecast_df = forecast_df.drop_duplicates(
        subset=['Issue_time', 'Forecast_time'], keep='first')

    # Normalize Issue_time (same as wind)
    forecast_df['Issue_time'] = (
        forecast_df['Forecast_time'].dt.normalize() - pd.Timedelta(hours=18)
    )

    # Load metadata and transform to engine format
    # Engine expects: site_ids, longitude, latitude, AC_capacity_MW
    raw_meta = pd.read_csv(meta_path)

    # Deduplicate plants sharing eia_plant_id. Some NYISO PTIDs map to
    # the same EIA plant (e.g. Albany County Solar 1 / Solar 2 share
    # eia_plant_id=64077 at identical lat/lon). When that happens,
    # HRRR+pvlib emits byte-identical actuals/forecast columns for both
    # PTIDs, which makes the asset covariance perfectly collinear and
    # crashes PCAGeminiEngine's graphical-lasso fit (sqrtm sees inf/NaN
    # after inversion of a near-singular precision). Fix at the data
    # layer: collapse PTIDs sharing an eia_plant_id into one virtual
    # plant — sum nameplate AND sum the per-plant generation columns,
    # which preserves the merged plant's energy contribution. Keep the
    # first PTID's site_id and lat/lon as the merged identifier.
    # Diagnostics:
    # experiments/solar_failure_characterization/diagnose_root_cause.py
    keepers, drop_rest, summed_caps = [], [], {}
    for _, grp in raw_meta.groupby('eia_plant_id'):
        sites = grp['site_id'].tolist()
        keeper = sites[0]
        keepers.append(keeper)
        summed_caps[keeper] = float(grp['nameplate_mw'].sum())
        if len(sites) > 1:
            for col in (actual_df, forecast_df):
                present = [s for s in sites if s in col.columns]
                if present:
                    col[keeper] = col[present].sum(axis=1)
            drop_rest.extend(sites[1:])
    if drop_rest:
        actual_df = actual_df.drop(columns=drop_rest, errors='ignore')
        forecast_df = forecast_df.drop(columns=drop_rest, errors='ignore')

    meta_df = pd.DataFrame({
        'site_ids': raw_meta['site_id'],
        'longitude': raw_meta['longitude'],
        'latitude': raw_meta['latitude'],
        'AC_capacity_MW': raw_meta['nameplate_mw'],
    })
    meta_df = meta_df[meta_df['site_ids'].isin(keepers)].copy()
    meta_df['AC_capacity_MW'] = meta_df['site_ids'].map(summed_caps)
    meta_df = meta_df[meta_df['site_ids'].isin(actual_df.columns)]

    return actual_df, forecast_df, meta_df


def load_ny_real_btm_solar_data(years=None):
    """Load NYISO behind-the-meter (BTM) solar zonal actuals + DA forecasts.

    BTM solar is published by NYISO MIS as a *zonal* product (the same 11
    NYISO load zones, plus the NYCA system total), so it loads exactly like
    the zonal load data: estimated actuals (P-70A) and a day-ahead zonal
    forecast (P-70B), both hourly UTC. Coverage starts November 2020.

    This is the pure data layer for the A2/B2 BTM track documented in
    docs/Solar_Modeling_Decision.md. It deliberately returns RAW MW (no
    relative-by-forecast normalization, no night-zero patch) — those
    modelling adaptations live in the runner
    (experiments/btm_solar_zonal/run_btm_solar.py) so this loader stays a
    drop-in sibling of load_ny_real_wind_data / load_ny_real_solar_data.

    Parameters
    ----------
    years : list[int] or None
        If given, restrict to these calendar years (actuals by index year,
        forecast by Forecast_time year). If None, return all available.

    Returns
    -------
    (actual_df, forecast_df, zones)
        actual_df   : DatetimeIndex (UTC), columns = 11 zone codes + 'NYCA'.
        forecast_df : columns ['Issue_time','Forecast_time', <zones>, 'NYCA'],
                      Issue_time in NYISO's native DA convention (18Z on the
                      day before each Eastern scenario day); only complete
                      24-row Issue_time blocks are kept.
        zones       : list of the 11 zone column names (NYCA excluded), so a
                      caller can model the zones and treat NYCA as a check.
    """
    btm_dir = Path(data_path, 'NYISO_real')

    def _widest(pattern):
        # The BTM data ships as single multi-year files, e.g.
        # btm_solar_actual_1h_zone_2020_2021_..._2025_utc.csv. Pick the file
        # spanning the most years (most underscore-delimited 4-digit tokens).
        files = list(btm_dir.glob(pattern))
        if not files:
            raise FileNotFoundError(
                f"No BTM solar files matching {pattern} in {btm_dir}. "
                "Run scripts/07_download_nyiso_btm_solar.py first."
            )
        def _n_years(p):
            return sum(t.isdigit() and len(t) == 4 for t in p.stem.split('_'))
        return max(files, key=_n_years)

    actual_file = _widest('btm_solar_actual_1h_zone_*_utc.csv')
    forecast_file = _widest('btm_solar_day_ahead_forecast_zone_*_utc.csv')

    actual_df = pd.read_csv(actual_file, parse_dates=['Time'], index_col='Time')
    if actual_df.index.tz is None:
        actual_df.index = actual_df.index.tz_localize('UTC')
    actual_df = actual_df[~actual_df.index.duplicated(keep='first')].sort_index()

    forecast_df = pd.read_csv(forecast_file,
                              parse_dates=['Issue_time', 'Forecast_time'])
    for col in ('Issue_time', 'Forecast_time'):
        if forecast_df[col].dt.tz is None:
            forecast_df[col] = forecast_df[col].dt.tz_localize('UTC')

    # Keep only complete day-ahead blocks (24 forecast rows per Issue_time).
    grp_sizes = forecast_df.groupby('Issue_time').size()
    complete = grp_sizes[grp_sizes == 24].index
    forecast_df = forecast_df[forecast_df['Issue_time'].isin(complete)] \
        .sort_values(['Issue_time', 'Forecast_time']).reset_index(drop=True)

    if years is not None:
        years = set(int(y) for y in years)
        actual_df = actual_df[actual_df.index.year.isin(years)]
        forecast_df = forecast_df[
            forecast_df['Forecast_time'].dt.year.isin(years)].reset_index(drop=True)

    zones = [c for c in actual_df.columns if c != 'NYCA']
    return actual_df, forecast_df, zones


def load_ny_real_load_data(years=None):
    """Load NYISO 11-zone LOAD actuals + day-ahead forecasts (official MIS feed).

    Source: NYISO Market Information System -- actuals from ``palIntegrated``
    (Real-Time Actual Load), day-ahead forecast from ``isolf`` (ISO Load
    Forecast), downloaded by ``download_nyiso_real_load.py``. Hourly UTC, the 11
    NYISO load zones (A..K). NOTE: reported NYISO load is NET of behind-the-meter
    solar. Columns are renamed to ``LOAD_<zone>`` (the GeminiEngine asset names
    used by the load scenario model). Drop-in sibling of
    ``load_ny_real_btm_solar_data`` (same zonal data shape + native DA convention).

    Returns
    -------
    (actual_df, forecast_df)
        actual_df   : DatetimeIndex (UTC), columns LOAD_A..LOAD_K.
        forecast_df : ['Issue_time','Forecast_time', LOAD_A..LOAD_K]; native
                      NYISO DA convention (Issue_time = 18Z on the day before each
                      ET scenario day); only complete 24-row blocks kept.
    """
    zone_col = {"A": "WEST", "B": "GENESE", "C": "CENTRL", "D": "NORTH",
                "E": "MHK VL", "F": "CAPITL", "G": "HUD VL", "H": "MILLWD",
                "I": "DUNWOD", "J": "N.Y.C.", "K": "LONGIL"}
    load_dir = Path(data_path, 'NYISO_real')

    def _widest(pattern):
        files = list(load_dir.glob(pattern))
        if not files:
            raise FileNotFoundError(
                f"No load files matching {pattern} in {load_dir}. "
                "Run download_nyiso_real_load.py first.")
        return max(files, key=lambda p: sum(
            t.isdigit() and len(t) == 4 for t in p.stem.split('_')))

    actual_df = pd.read_csv(_widest('load_actual_1h_zone_*_utc.csv'),
                            parse_dates=['Time'], index_col='Time')
    if actual_df.index.tz is None:
        actual_df.index = actual_df.index.tz_localize('UTC')
    actual_df = actual_df[~actual_df.index.duplicated(keep='first')].sort_index()

    forecast_df = pd.read_csv(_widest('load_day_ahead_forecast_zone_*_utc.csv'),
                              parse_dates=['Issue_time', 'Forecast_time'])
    for col in ('Issue_time', 'Forecast_time'):
        if forecast_df[col].dt.tz is None:
            forecast_df[col] = forecast_df[col].dt.tz_localize('UTC')
    grp = forecast_df.groupby('Issue_time').size()
    forecast_df = (forecast_df[forecast_df['Issue_time'].isin(grp[grp == 24].index)]
                   .sort_values(['Issue_time', 'Forecast_time']).reset_index(drop=True))

    zones = list(zone_col)                       # canonical A..K
    cols = [zone_col[z] for z in zones]
    rename = {zone_col[z]: f"LOAD_{z}" for z in zones}
    actual_df = actual_df[cols].rename(columns=rename)
    forecast_df = forecast_df[['Issue_time', 'Forecast_time'] + cols].rename(columns=rename)

    if years is not None:
        years = set(int(y) for y in years)
        actual_df = actual_df[actual_df.index.year.isin(years)]
        forecast_df = forecast_df[
            forecast_df['Forecast_time'].dt.year.isin(years)].reset_index(drop=True)

    return actual_df, forecast_df


def apply_solar_night_mask(scenarios_df, plant_latlons, scen_timesteps):
    """Zero out solar scenarios during nighttime hours.

    Parameters
    ----------
    scenarios_df : pd.DataFrame
        Shape (n_scenarios, n_plants * n_hours). Columns are a flat
        sequence of plant1_h0, plant1_h1, ..., plant1_h23, plant2_h0, ...
    plant_latlons : dict
        {plant_id: (lat, lon)} for each solar plant in the scenario.
    scen_timesteps : list[pd.Timestamp]
        The 24 UTC timestamps of the scenario day.

    Returns
    -------
    pd.DataFrame with nighttime values set to zero.
    """
    import pvlib
    from pvlib.location import Location

    plants = list(plant_latlons.keys())
    n_plants = len(plants)
    n_hours = len(scen_timesteps)

    # Compute solar zenith for each (plant, hour)
    night_mask = []  # flat list matching scenario column order
    for plant in plants:
        lat, lon = plant_latlons[plant]
        loc = Location(lat, lon, tz='UTC')
        times = pd.DatetimeIndex(scen_timesteps, tz='UTC')
        solpos = loc.get_solarposition(times)
        for h in range(n_hours):
            # Night = sun below horizon (zenith >= 90)
            night_mask.append(solpos['apparent_zenith'].iloc[h] >= 90)

    # Apply mask: set nighttime columns to zero
    result = scenarios_df.copy()
    for col_idx, is_night in enumerate(night_mask):
        if is_night:
            result.iloc[:, col_idx] = 0.0

    return result
