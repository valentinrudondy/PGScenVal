#!/usr/bin/env python3
"""
download_nyiso_btm_solar.py
============================
Downloads NYISO Behind-The-Meter (BTM) solar data (estimated actuals + day-ahead
zonal forecasts) and reformats to the PGScen convention (wide format, UTC index).

Data source: mis.nyiso.com
  - Estimated Actuals  (P-70A): csv/btmactualforecast/  YYYYMMDDBTMEstimatedActual_csv.zip
  - Day-Ahead Forecast (P-70B): csv/btmdaforecast/      YYYYMMDDbtmdaforecast_csv.zip

Available from November 2020 onward.

Output (in OUTPUT_DIR):
    - btm_solar_actual_1h_zone_{years}_utc.csv
    - btm_solar_day_ahead_forecast_zone_{years}_utc.csv

Usage:
    python download_nyiso_btm_solar.py
    python download_nyiso_btm_solar.py --years 2023 2024 2025 --output ./data/NYISO_real
"""

import argparse
import io
import sys
import zipfile
import urllib.request
from datetime import date as dt_date, timedelta
from pathlib import Path

import pandas as pd
import numpy as np


# ─────────────────────────────────────────────────────────────
#  Zone names (same zones as load data + SYSTEM total)
# ─────────────────────────────────────────────────────────────
ZONES = [
    'CAPITL', 'CENTRL', 'DUNWOD', 'GENESE', 'HUD VL',
    'LONGIL', 'MHK VL', 'MILLWD', 'N.Y.C.', 'NORTH', 'WEST',
]
SYSTEM_ZONE = 'SYSTEM'


# ─────────────────────────────────────────────────────────────
#  1. Download estimated actuals
# ─────────────────────────────────────────────────────────────
def _download_btm_actual_zip(year, month):
    """Download a single month of BTM Estimated Actual CSV from mis.nyiso.com."""
    url = (f"http://mis.nyiso.com/public/csv/btmactualforecast/"
           f"{year}{month:02d}01BTMEstimatedActual_csv.zip")
    try:
        resp = urllib.request.urlopen(url, timeout=60)
        zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    except Exception as e:
        print(f"    Could not download {year}-{month:02d} actuals: {e}")
        return pd.DataFrame()

    frames = []
    for name in sorted(zf.namelist()):
        if name.endswith('.csv'):
            with zf.open(name) as f:
                df = pd.read_csv(f)
                frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def download_actuals(years):
    """
    Download hourly BTM solar estimated actuals by zone from mis.nyiso.com.
    Returns a wide DataFrame indexed by Time (UTC) with one column per zone + NYCA.
    """
    frames = []
    for year in years:
        print(f"  Downloading actuals {year}...")
        for month in range(1, 13):
            df = _download_btm_actual_zip(year, month)
            if len(df) > 0:
                frames.append(df)

    if not frames:
        raise RuntimeError("No BTM actual files downloaded!")

    raw = pd.concat(frames, ignore_index=True)
    return _parse_long_to_wide(raw, label='actuals')


# ─────────────────────────────────────────────────────────────
#  2. Download day-ahead forecasts
# ─────────────────────────────────────────────────────────────
def _download_btm_forecast_zip(year, month):
    """Download a single month of BTM Day-Ahead Forecast CSV from mis.nyiso.com."""
    url = (f"http://mis.nyiso.com/public/csv/btmdaforecast/"
           f"{year}{month:02d}01btmdaforecast_csv.zip")
    try:
        resp = urllib.request.urlopen(url, timeout=60)
        zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    except Exception as e:
        print(f"    Could not download {year}-{month:02d} forecasts: {e}")
        return pd.DataFrame()

    frames = []
    for name in sorted(zf.namelist()):
        if name.endswith('.csv'):
            # Extract file date from filename (e.g. "20230615btmdaforecast.csv")
            basename = name.split('/')[-1].replace('btmdaforecast.csv', '')
            try:
                file_date = dt_date(int(basename[:4]), int(basename[4:6]),
                                    int(basename[6:8]))
            except (ValueError, IndexError):
                file_date = None

            with zf.open(name) as f:
                df = pd.read_csv(f)
                df['_file_date'] = file_date
                frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def download_forecasts(years):
    """
    Download hourly BTM solar day-ahead forecasts by zone from mis.nyiso.com.

    Convention (matching PGScen load forecasts):
      - Issue_time  = day before at 18:00 UTC
      - Forecast_time = the hour being forecast (UTC)

    The forecast file dated D contains the day-ahead forecast FOR day D
    (issued/posted on day D-1).

    Returns a DataFrame with columns: Issue_time, Forecast_time, + zones + NYCA.
    """
    frames = []
    for year in years:
        print(f"  Downloading forecasts {year}...")
        for month in range(1, 13):
            df = _download_btm_forecast_zip(year, month)
            if len(df) > 0:
                frames.append(df)

    if not frames:
        raise RuntimeError("No BTM forecast files downloaded!")

    raw = pd.concat(frames, ignore_index=True)
    return _parse_forecasts(raw)


# ─────────────────────────────────────────────────────────────
#  Parsing helpers
# ─────────────────────────────────────────────────────────────
def _parse_long_to_wide(raw, label='data'):
    """
    Convert NYISO long format (Time Stamp, Time Zone, Zone Name, MW Value)
    to wide format indexed by UTC timestamp with one column per zone.
    Renames SYSTEM -> NYCA for consistency with load data.
    """
    ts_col = 'Time Stamp'
    raw['Time_ET'] = pd.to_datetime(raw[ts_col])

    # Convert Eastern -> UTC using the Time Zone column (EST/EDT)
    # This avoids ambiguous timestamp issues during DST transitions
    tz_col = raw['Time Zone'].str.strip()
    utc_offset = tz_col.map({'EST': pd.Timedelta(hours=-5),
                             'EDT': pd.Timedelta(hours=-4)})
    # Fallback for any unexpected values
    utc_offset = utc_offset.fillna(pd.Timedelta(hours=-5))
    raw['Time'] = pd.to_datetime(raw['Time_ET']) - utc_offset
    raw['Time'] = raw['Time'].dt.tz_localize('UTC')

    # Rename SYSTEM -> NYCA for consistency with load convention
    raw['Zone Name'] = raw['Zone Name'].replace({'SYSTEM': 'NYCA'})

    # Pivot to wide format
    wide = raw.pivot_table(
        index='Time', columns='Zone Name', values='MW Value',
        aggfunc='mean'
    ).sort_index()

    # Ensure column order: zones + NYCA
    cols = [z for z in ZONES if z in wide.columns]
    if 'NYCA' in wide.columns:
        cols.append('NYCA')
    wide = wide[cols]

    # Remove timezone info from index for CSV compatibility, but keep UTC values
    wide.index = wide.index.tz_localize(None)
    wide.index.name = 'Time'

    # Remove duplicates
    wide = wide[~wide.index.duplicated(keep='first')]

    print(f"  -> {label}: {wide.shape[0]} hours, {wide.shape[1]} zones")
    print(f"     Period: {wide.index.min()} -> {wide.index.max()}")
    print(f"     Zones: {list(wide.columns)}")

    return wide


def _parse_forecasts(raw):
    """
    Convert long-format BTM forecast data to PGScen convention.
    Each file dated D contains the day-ahead forecast for day D.
    Issue_time = D-1 at 18:00 UTC.
    """
    ts_col = 'Time Stamp'
    raw['Forecast_time_ET'] = pd.to_datetime(raw[ts_col])

    # Eastern -> UTC using the Time Zone column (EST/EDT)
    tz_col = raw['Time Zone'].str.strip()
    utc_offset = tz_col.map({'EST': pd.Timedelta(hours=-5),
                             'EDT': pd.Timedelta(hours=-4)})
    utc_offset = utc_offset.fillna(pd.Timedelta(hours=-5))
    raw['Forecast_time'] = pd.to_datetime(raw['Forecast_time_ET']) - utc_offset
    raw['Forecast_time'] = raw['Forecast_time'].dt.tz_localize('UTC')

    # The forecast file dated D contains forecasts for day D.
    # Keep only rows where the forecast date (Eastern) matches the file date.
    raw['forecast_date_ET'] = raw['Forecast_time_ET'].dt.date
    raw = raw[raw['_file_date'] == raw['forecast_date_ET']].copy()

    # Rename SYSTEM -> NYCA
    raw['Zone Name'] = raw['Zone Name'].replace({'SYSTEM': 'NYCA'})

    # Pivot to wide
    wide = raw.pivot_table(
        index='Forecast_time', columns='Zone Name', values='MW Value',
        aggfunc='mean'
    ).sort_index()

    # Column order
    zone_cols = [z for z in ZONES if z in wide.columns]
    if 'NYCA' in wide.columns:
        zone_cols.append('NYCA')
    wide = wide[zone_cols]

    # Build Issue_time: day before at 18:00 UTC
    # Use the Eastern date from the original data to determine the forecast day
    wide = wide.reset_index()
    # Convert Forecast_time (UTC) to Eastern to get the calendar date
    ft_utc = wide['Forecast_time']
    ft_et = ft_utc.dt.tz_convert('US/Eastern')
    forecast_date_et = ft_et.dt.date
    # Issue_time = day before at 18:00 UTC
    wide['Issue_time'] = pd.to_datetime(
        pd.Series(forecast_date_et) - timedelta(days=1)
    ) + pd.Timedelta(hours=18)
    wide['Issue_time'] = wide['Issue_time'].dt.tz_localize('UTC')

    # Reorder columns
    wide = wide[['Issue_time', 'Forecast_time'] + zone_cols]

    # Remove duplicates
    wide = wide.drop_duplicates(subset=['Forecast_time'], keep='first')
    wide = wide.sort_values('Forecast_time').reset_index(drop=True)

    # Filter incomplete forecast blocks (PGScen requires 24h per Issue_time)
    group_sizes = wide.groupby('Issue_time').size()
    complete_issues = group_sizes[group_sizes == 24].index
    n_dropped = len(group_sizes) - len(complete_issues)
    if n_dropped > 0:
        print(f"  Filtering: dropped {n_dropped} incomplete forecast blocks "
              f"(kept {len(complete_issues)}/{len(group_sizes)})")
    wide = wide[wide['Issue_time'].isin(complete_issues)].reset_index(drop=True)

    print(f"  -> Forecasts: {len(wide)} rows")
    print(f"     Period: {wide['Forecast_time'].min()} -> {wide['Forecast_time'].max()}")
    print(f"     Zones: {zone_cols}")
    print(f"     Unique Issue_times: {wide['Issue_time'].nunique()}")

    return wide


# ─────────────────────────────────────────────────────────────
#  3. Validation
# ─────────────────────────────────────────────────────────────
def validate_and_clean(actuals, forecasts):
    """Validate consistency between actuals and forecasts."""
    actual_zones = sorted(actuals.columns)
    forecast_zones = sorted([c for c in forecasts.columns
                             if c not in {'Issue_time', 'Forecast_time'}])

    print(f"\n=== Validation ===")
    print(f"  Zones actuals:   {actual_zones}")
    print(f"  Zones forecasts: {forecast_zones}")

    common_zones = sorted(set(actual_zones) & set(forecast_zones))
    if set(actual_zones) != set(forecast_zones):
        print(f"  Mismatch! Common zones: {common_zones}")
        actuals = actuals[common_zones]
        forecasts = forecasts[['Issue_time', 'Forecast_time'] + common_zones]
    else:
        print(f"  Zones match.")

    # Check NaN
    na_actual = actuals.isna().sum().sum()
    na_forecast = forecasts[common_zones].isna().sum().sum()
    print(f"  NaN in actuals:   {na_actual}")
    print(f"  NaN in forecasts: {na_forecast}")

    if na_actual > 0:
        print(f"  -> Interpolating NaN in actuals")
        actuals = actuals.interpolate(method='linear').ffill().bfill()

    if na_forecast > 0:
        print(f"  -> Interpolating NaN in forecasts")
        forecasts[common_zones] = forecasts[common_zones].interpolate(
            method='linear').ffill().bfill()

    # Temporal overlap (handle tz-naive actuals vs tz-aware forecasts)
    a_min = actuals.index.min()
    a_max = actuals.index.max()
    f_min = forecasts['Forecast_time'].min()
    f_max = forecasts['Forecast_time'].max()
    # Strip tz for comparison
    if hasattr(f_min, 'tz') and f_min.tz is not None:
        f_min = f_min.tz_localize(None)
        f_max = f_max.tz_localize(None)
    overlap_start = max(a_min, f_min)
    overlap_end = min(a_max, f_max)
    print(f"  Overlap period: {overlap_start} -> {overlap_end}")

    return actuals, forecasts


# ─────────────────────────────────────────────────────────────
#  4. Save to PGScen format
# ─────────────────────────────────────────────────────────────
def save_pgscen_format(actuals, forecasts, output_dir, years):
    """Save CSVs in PGScen convention."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    years_str = '_'.join(str(y) for y in years)

    actual_path = output_dir / f'btm_solar_actual_1h_zone_{years_str}_utc.csv'
    actuals.to_csv(actual_path)
    print(f"\n  Actuals saved: {actual_path}")
    print(f"    ({actuals.shape[0]} rows x {actuals.shape[1]} columns)")

    forecast_path = output_dir / f'btm_solar_day_ahead_forecast_zone_{years_str}_utc.csv'
    forecasts.to_csv(forecast_path, index=False)
    print(f"  Forecasts saved: {forecast_path}")
    print(f"    ({forecasts.shape[0]} rows x {forecasts.shape[1] - 2} zones)")

    return actual_path, forecast_path


# ─────────────────────────────────────────────────────────────
#  5. Loading function for notebooks
# ─────────────────────────────────────────────────────────────
def load_real_ny_btm_solar_data(data_dir, years=None):
    """
    Load real NYISO BTM solar data in PGScen format.

    Usage in notebook:
        from download_nyiso_btm_solar import load_real_ny_btm_solar_data
        btm_actual, btm_forecast = load_real_ny_btm_solar_data('./data/NYISO_real')

    Returns:
        btm_actual:   DataFrame indexed by Time (UTC), columns = zones + NYCA
        btm_forecast: DataFrame with Issue_time, Forecast_time, + zones + NYCA
    """
    data_dir = Path(data_dir)

    if years:
        years_str = '_'.join(str(y) for y in years)
        actual_file = data_dir / f'btm_solar_actual_1h_zone_{years_str}_utc.csv'
        forecast_file = data_dir / f'btm_solar_day_ahead_forecast_zone_{years_str}_utc.csv'
    else:
        actual_files = list(data_dir.glob('btm_solar_actual_1h_zone_*_utc.csv'))
        forecast_files = list(data_dir.glob('btm_solar_day_ahead_forecast_zone_*_utc.csv'))
        if not actual_files or not forecast_files:
            raise FileNotFoundError(
                f"BTM solar files not found in {data_dir}. "
                "Run first: python download_nyiso_btm_solar.py"
            )
        actual_file = sorted(actual_files)[-1]
        forecast_file = sorted(forecast_files)[-1]

    print(f"Loading actuals:   {actual_file}")
    print(f"Loading forecasts: {forecast_file}")

    btm_actual = pd.read_csv(
        actual_file, parse_dates=['Time'], index_col='Time'
    )

    btm_forecast = pd.read_csv(
        forecast_file, parse_dates=['Issue_time', 'Forecast_time']
    )

    # Filter incomplete forecast blocks
    group_sizes = btm_forecast.groupby('Issue_time').size()
    complete_issues = group_sizes[group_sizes == 24].index
    n_dropped = len(group_sizes) - len(complete_issues)
    if n_dropped > 0:
        print(f"  Filtering: dropped {n_dropped} incomplete forecast blocks "
              f"(kept {len(complete_issues)}/{len(group_sizes)})")
    btm_forecast = btm_forecast[
        btm_forecast['Issue_time'].isin(complete_issues)
    ].reset_index(drop=True)

    return btm_actual, btm_forecast


# ─────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Download NYISO BTM solar data (estimated actuals + DA forecasts)"
    )
    parser.add_argument(
        '--years', nargs='+', type=int,
        default=list(range(2021, 2027)),
        help='Years to download (default: 2021-2026). Data available from Nov 2020.'
    )
    parser.add_argument(
        '--output', '-o', type=str, default='./data/NYISO_real',
        help='Output directory (default: ./data/NYISO_real)'
    )

    args = parser.parse_args()
    years = sorted(args.years)
    output_dir = args.output

    print("=" * 60)
    print("Downloading NYISO Behind-The-Meter Solar Data")
    print("=" * 60)
    print(f"Years: {years}")
    print(f"Output: {output_dir}")
    print()

    print("--- Estimated Actuals ---")
    actuals = download_actuals(years)

    print("\n--- Day-Ahead Forecasts ---")
    forecasts = download_forecasts(years)

    actuals, forecasts = validate_and_clean(actuals, forecasts)

    actual_path, forecast_path = save_pgscen_format(
        actuals, forecasts, output_dir, years
    )

    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)
    print()
    print("To use in a notebook:")
    print()
    print("  from download_nyiso_btm_solar import load_real_ny_btm_solar_data")
    print(f"  btm_actual, btm_forecast = load_real_ny_btm_solar_data('{output_dir}')")


if __name__ == '__main__':
    main()
