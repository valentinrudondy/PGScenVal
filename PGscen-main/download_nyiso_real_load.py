#!/usr/bin/env python3
"""
download_nyiso_real_load.py
===========================
Télécharge les données réelles de charge NYISO (actuals + forecasts day-ahead)
et les reformate au format attendu par PGScen.

Prérequis :
    pip install pandas numpy requests

Sortie (dans OUTPUT_DIR) :
    - load_actual_1h_zone_{years}_utc.csv       →  remplace le fichier NREL/PERFORM
    - load_day_ahead_forecast_zone_{years}_utc.csv  →  remplace le fichier NREL/PERFORM

Usage :
    python download_nyiso_real_load.py
    python download_nyiso_real_load.py --years 2022 2023 --output ./data/NYISO_real

Après exécution, vous pouvez soit :
  (a) Copier les CSV dans data/NYISO/Load/ du repo PGScen pour remplacer les fichiers NREL
  (b) Les charger directement dans le notebook avec la fonction load_real_ny_load_data()
      fournie en bas de ce script.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import numpy as np


# ─────────────────────────────────────────────────────────────
#  Mapping des noms de zones NYISO
# ─────────────────────────────────────────────────────────────
# NYISOToolkit utilise les noms longs, PGScen les noms courts.
# Les noms courts correspondent à ceux des fichiers NREL/PERFORM.
# Ajustez si les noms de colonnes de votre version diffèrent.

ZONE_NAME_MAP = {
    'CAPITL':  'CAPITL',
    'CENTRL':  'CENTRL',
    'DUNWOD':  'DUNWOD',
    'GENESE':  'GENESE',
    'HUD VL':  'HUD VL',
    'LONGIL':  'LONGIL',
    'MHK VL':  'MHK VL',
    'MILLWD':  'MILLWD',
    'N.Y.C.':  'N.Y.C.',
    'NORTH':   'NORTH',
    'WEST':    'WEST',
}

# Colonnes à exclure (total système, etc.)
EXCLUDE_COLS = {'NYISO', 'Time', 'Timestamp', 'Name'}


# ─────────────────────────────────────────────────────────────
#  1. Téléchargement des actuals depuis mis.nyiso.com
# ─────────────────────────────────────────────────────────────
def _download_pal_csv(year, month):
    """
    Download a single month of NYISO Actual Load CSV from mis.nyiso.com.
    Dataset: palIntegrated (Integrated Real-Time Actual Load).
    """
    import io
    import zipfile
    import urllib.request

    url = (f"http://mis.nyiso.com/public/csv/palIntegrated/"
           f"{year}{month:02d}01palIntegrated_csv.zip")

    try:
        resp = urllib.request.urlopen(url, timeout=60)
        zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    except Exception as e:
        print(f"    ⚠ Could not download {url}: {e}")
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
    Télécharge les actuals horaires de charge par zone NYISO
    directement depuis mis.nyiso.com (sans NYISOToolkit).

    Retourne un DataFrame indexé par Time (UTC) avec une colonne par zone.
    """
    frames = []
    for year in years:
        print(f"  Téléchargement actuals {year}...")
        for month in range(1, 13):
            df = _download_pal_csv(year, month)
            if len(df) > 0:
                frames.append(df)

    if not frames:
        raise RuntimeError("Aucun fichier actuals téléchargé !")

    raw = pd.concat(frames, ignore_index=True)

    # Parse timestamp column (Eastern time in NYISO files)
    ts_col = [c for c in raw.columns if 'time' in c.lower() or 'stamp' in c.lower()][0]
    raw['Time_ET'] = pd.to_datetime(raw[ts_col])

    # Identify zone columns (exclude timestamp cols and system total)
    zone_cols_raw = [c for c in raw.columns
                     if c not in {ts_col, 'Time_ET'}
                     and c not in EXCLUDE_COLS
                     and 'time' not in c.lower() and 'stamp' not in c.lower()]

    # Rename columns to match PGScen conventions
    col_rename = {}
    for col in zone_cols_raw:
        for short_name, target in ZONE_NAME_MAP.items():
            if col.strip().upper() == short_name.upper():
                col_rename[col] = target
                break
            elif col.strip().upper().replace(' ', '') == short_name.upper().replace(' ', ''):
                col_rename[col] = target
                break

    raw = raw.rename(columns=col_rename)
    zone_cols = sorted(col_rename.values())

    # Convert Eastern -> UTC
    raw['Time'] = (raw['Time_ET']
                   .dt.tz_localize('America/New_York', ambiguous='infer',
                                   nonexistent='shift_forward')
                   .dt.tz_convert('UTC')
                   .dt.tz_localize(None))

    # One row per hour, one column per zone
    actuals = raw.groupby('Time')[zone_cols].mean().sort_index()

    # Remove duplicates
    actuals = actuals[~actuals.index.duplicated(keep='first')]

    actuals.index.name = 'Time'

    print(f"  → Actuals: {actuals.shape[0]} heures, {actuals.shape[1]} zones")
    print(f"    Période: {actuals.index.min()} → {actuals.index.max()}")
    print(f"    Zones: {list(actuals.columns)}")

    return actuals


def _download_isolf_csv(year, month):
    """
    Download a single month of NYISO ISO Load Forecast CSV from mis.nyiso.com.

    Each daily file (e.g. 20230614isolf.csv) contains forecasts for ~6 days.
    The TRUE day-ahead forecast for day J is in the file dated J-1.
    We tag each row with the source file date so we can filter later.
    """
    import io
    import zipfile
    import urllib.request
    from datetime import date as dt_date

    url = (f"http://mis.nyiso.com/public/csv/isolf/"
           f"{year}{month:02d}01isolf_csv.zip")

    try:
        resp = urllib.request.urlopen(url, timeout=60)
        zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    except Exception as e:
        print(f"    ⚠ Could not download {url}: {e}")
        return pd.DataFrame()

    frames = []
    for name in sorted(zf.namelist()):
        if name.endswith('.csv'):
            # Extract the file date from the filename (e.g. "20230614isolf.csv")
            basename = name.replace('isolf.csv', '').replace('/', '')
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
    Télécharge les prévisions day-ahead de charge par zone NYISO
    directement depuis mis.nyiso.com (sans NYISOToolkit, qui introduit
    des erreurs de timezone et de resampling).

    Retourne un DataFrame avec colonnes Issue_time, Forecast_time, + zones.

    Convention PGScen :
      - Issue_time  = quand la prévision a été émise (veille à 18:00 UTC)
      - Forecast_time = l'heure pour laquelle la prévision est faite (UTC)

    Le CSV NYISO « isolf » contient des timestamps en heure locale Eastern
    (EST/EDT). Chaque fichier couvre typiquement 3-4 jours de forecasts.
    On ne garde que le dernier forecast émis pour chaque jour (le plus récent).
    """
    frames = []
    for year in years:
        print(f"  Téléchargement forecasts {year}...")
        for month in range(1, 13):
            df = _download_isolf_csv(year, month)
            if len(df) > 0:
                frames.append(df)

    if not frames:
        raise RuntimeError("Aucun fichier forecast téléchargé !")

    raw = pd.concat(frames, ignore_index=True)

    # ─── Parsing des timestamps ───
    # La colonne s'appelle "Time Stamp" et est en Eastern time
    ts_col = [c for c in raw.columns if 'time' in c.lower() or 'stamp' in c.lower()][0]
    raw['Forecast_time_ET'] = pd.to_datetime(raw[ts_col])

    # Identifier les colonnes de zones (exclure timestamp et total)
    zone_cols_raw = [c for c in raw.columns
                     if c not in {ts_col, 'Forecast_time_ET', 'NYISO', 'NYCA'}
                     and 'time' not in c.lower() and 'stamp' not in c.lower()]

    # Renommer les colonnes pour matcher PGScen
    # NYISO utilise "Capitl", "Centrl", "Mhk Vl", etc.
    col_rename = {}
    for col in zone_cols_raw:
        for short_name, target in ZONE_NAME_MAP.items():
            if col.strip().upper() == short_name.upper():
                col_rename[col] = target
                break
            elif col.strip().upper().replace(' ', '') == short_name.upper().replace(' ', ''):
                col_rename[col] = target
                break
        if col not in col_rename:
            # Try case-insensitive partial match
            for short_name, target in ZONE_NAME_MAP.items():
                if short_name.lower() in col.lower() or col.lower() in short_name.lower():
                    col_rename[col] = target
                    break

    raw = raw.rename(columns=col_rename)
    zone_cols = sorted([v for v in col_rename.values()])

    # ─── Conversion Eastern → UTC ───
    # Les timestamps sont en heure locale Eastern (EST/EDT).
    # On localise puis on convertit en UTC.
    raw['Forecast_time'] = (
        raw['Forecast_time_ET']
        .dt.tz_localize('US/Eastern', ambiguous='infer', nonexistent='shift_forward')
        .dt.tz_convert('UTC')
    )

    # ─── Sélection du vrai forecast day-ahead ───
    # Chaque fichier daté J contient des forecasts pour J, J+1, ..., J+5.
    # Le VRAI day-ahead forecast pour le jour D (Eastern) est celui du
    # fichier daté D-1.
    # Le forecast pour le jour D couvre 00:00-23:00 Eastern, ce qui en UTC
    # donne 04:00/05:00 jour D → 03:00/04:00 jour D+1 (selon DST).
    # On utilise la date Eastern (pas UTC) pour le matching.
    raw['forecast_date_ET'] = raw['Forecast_time_ET'].dt.date

    from datetime import timedelta
    raw['_expected_file_date'] = raw['forecast_date_ET'] - timedelta(days=1)
    raw = raw[raw['_file_date'] == raw['_expected_file_date']].copy()
    raw = raw.drop(columns=['_file_date', '_expected_file_date'])

    # Supprimer les doublons restants
    raw = raw.drop_duplicates(subset=['Forecast_time'], keep='first')
    raw = raw.sort_values('Forecast_time').reset_index(drop=True)

    # ─── Construction du format PGScen ───
    # Issue_time = veille à 18:00 UTC
    # Le forecast couvre 00:00-23:00 Eastern du jour J.
    # 00:00 Eastern = 04:00 ou 05:00 UTC selon DST.
    # Issue_time = jour J-1 à 18:00 UTC.
    raw['Issue_time'] = (
        pd.to_datetime(raw['forecast_date_ET'] - pd.Timedelta(days=1))
        + pd.Timedelta(hours=18)
    ).dt.tz_localize('UTC')

    # Réorganiser
    forecasts = raw[['Issue_time', 'Forecast_time'] + zone_cols].copy()

    # Convertir les valeurs en float
    for z in zone_cols:
        forecasts[z] = pd.to_numeric(forecasts[z], errors='coerce')

    # Supprimer les lignes vides
    forecasts = forecasts.dropna(subset=zone_cols, how='all')

    # ─── Filtrer les blocs incomplets ───
    group_sizes = forecasts.groupby('Issue_time').size()
    complete_issues = group_sizes[group_sizes == 24].index
    n_dropped = len(group_sizes) - len(complete_issues)
    if n_dropped > 0:
        print(f"  ⚠ {n_dropped} blocs de forecast incomplets supprimés "
              f"(gardé {len(complete_issues)}/{len(group_sizes)})")
        forecasts = forecasts[
            forecasts['Issue_time'].isin(complete_issues)
        ].reset_index(drop=True)

    print(f"  → Forecasts: {len(forecasts)} lignes")
    print(f"    Période: {forecasts['Forecast_time'].min()} → {forecasts['Forecast_time'].max()}")
    print(f"    Zones: {zone_cols}")
    print(f"    Issue_times uniques: {forecasts['Issue_time'].nunique()}")

    return forecasts


# ─────────────────────────────────────────────────────────────
#  2. Validation et nettoyage
# ─────────────────────────────────────────────────────────────
def validate_and_clean(actuals, forecasts):
    """
    Valide la cohérence entre actuals et forecasts.
    Vérifie que les noms de zones correspondent.
    """
    actual_zones = sorted(actuals.columns)
    forecast_zones = sorted([c for c in forecasts.columns 
                             if c not in {'Issue_time', 'Forecast_time'}])

    print(f"\n=== Validation ===")
    print(f"  Zones actuals:   {actual_zones}")
    print(f"  Zones forecasts: {forecast_zones}")

    # Vérifier que les zones correspondent
    common_zones = sorted(set(actual_zones) & set(forecast_zones))
    if set(actual_zones) != set(forecast_zones):
        print(f"  ⚠ Mismatch! Zones communes: {common_zones}")
        print(f"    → On ne garde que les zones communes.")
        actuals = actuals[common_zones]
        forecasts = forecasts[['Issue_time', 'Forecast_time'] + common_zones]
    else:
        print(f"  ✓ Les zones correspondent.")

    # Vérifier les NaN
    na_actual = actuals.isna().sum().sum()
    na_forecast = forecasts[common_zones].isna().sum().sum()
    print(f"  NaN dans actuals:   {na_actual}")
    print(f"  NaN dans forecasts: {na_forecast}")

    if na_actual > 0:
        print(f"  → Interpolation linéaire des NaN dans actuals")
        actuals = actuals.interpolate(method='linear').ffill().bfill()

    if na_forecast > 0:
        print(f"  → Interpolation linéaire des NaN dans forecasts")
        forecasts[common_zones] = forecasts[common_zones].interpolate(
            method='linear').ffill().bfill()

    # Vérifier la couverture temporelle
    overlap_start = max(actuals.index.min(), forecasts['Forecast_time'].min())
    overlap_end = min(actuals.index.max(), forecasts['Forecast_time'].max())
    print(f"  Période de chevauchement: {overlap_start} → {overlap_end}")

    # Filtrer les blocs de forecast incomplets (PGScen exige 24 horizons par Issue_time)
    group_sizes = forecasts.groupby('Issue_time').size()
    complete_issues = group_sizes[group_sizes == 24].index
    n_dropped = len(group_sizes) - len(complete_issues)
    if n_dropped > 0:
        print(f"  ⚠ {n_dropped} blocs de forecast incomplets supprimés "
              f"(gardé {len(complete_issues)}/{len(group_sizes)})")
        forecasts = forecasts[
            forecasts['Issue_time'].isin(complete_issues)
        ].reset_index(drop=True)

    return actuals, forecasts


# ─────────────────────────────────────────────────────────────
#  3. Sauvegarde au format PGScen
# ─────────────────────────────────────────────────────────────
def save_pgscen_format(actuals, forecasts, output_dir, years):
    """Sauvegarde les CSV au format attendu par PGScen."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    years_str = '_'.join(str(y) for y in years)

    # Actuals
    actual_path = output_dir / f'load_actual_1h_zone_{years_str}_utc.csv'
    actuals.to_csv(actual_path)
    print(f"\n  ✓ Actuals sauvegardés: {actual_path}")
    print(f"    ({actuals.shape[0]} lignes × {actuals.shape[1]} colonnes)")

    # Forecasts
    forecast_path = output_dir / f'load_day_ahead_forecast_zone_{years_str}_utc.csv'
    forecasts.to_csv(forecast_path, index=False)
    print(f"  ✓ Forecasts sauvegardés: {forecast_path}")
    print(f"    ({forecasts.shape[0]} lignes × {forecasts.shape[1] - 2} zones)")

    return actual_path, forecast_path


# ─────────────────────────────────────────────────────────────
#  4. Fonction de chargement pour le notebook
# ─────────────────────────────────────────────────────────────
def load_real_ny_load_data(data_dir, years=None):
    """
    Charge les données réelles NYISO au format PGScen.
    
    À utiliser dans le notebook à la place de load_ny_load_data() :
    
        from download_nyiso_real_load import load_real_ny_load_data
        load_actual, load_forecast = load_real_ny_load_data('./data/NYISO_real')
    
    Ou en spécifiant les années :
        load_actual, load_forecast = load_real_ny_load_data('./data/NYISO_real', 
                                                             years=[2022, 2023])
    """
    data_dir = Path(data_dir)

    # Trouver les fichiers
    if years:
        years_str = '_'.join(str(y) for y in years)
        actual_file = data_dir / f'load_actual_1h_zone_{years_str}_utc.csv'
        forecast_file = data_dir / f'load_day_ahead_forecast_zone_{years_str}_utc.csv'
    else:
        # Chercher le premier fichier qui match
        actual_files = list(data_dir.glob('load_actual_1h_zone_*_utc.csv'))
        forecast_files = list(data_dir.glob('load_day_ahead_forecast_zone_*_utc.csv'))
        if not actual_files or not forecast_files:
            raise FileNotFoundError(
                f"Fichiers load non trouvés dans {data_dir}. "
                "Exécutez d'abord: python download_nyiso_real_load.py"
            )
        actual_file = sorted(actual_files)[-1]
        forecast_file = sorted(forecast_files)[-1]

    print(f"Chargement actuals:   {actual_file}")
    print(f"Chargement forecasts: {forecast_file}")

    load_actual_df = pd.read_csv(
        actual_file, parse_dates=['Time'], index_col='Time'
    )

    load_forecast_df = pd.read_csv(
        forecast_file, parse_dates=['Issue_time', 'Forecast_time']
    )

    # ── Filter out incomplete forecast blocks ──
    # PGScen requires exactly 24 forecast horizons per Issue_time.
    # Real NYISO data often has truncated blocks at the start/end of the dataset.
    group_sizes = load_forecast_df.groupby('Issue_time').size()
    complete_issues = group_sizes[group_sizes == 24].index
    n_dropped = len(group_sizes) - len(complete_issues)
    if n_dropped > 0:
        print(f"  Filtering: dropped {n_dropped} incomplete forecast blocks "
              f"(kept {len(complete_issues)}/{len(group_sizes)})")
    load_forecast_df = load_forecast_df[
        load_forecast_df['Issue_time'].isin(complete_issues)
    ].reset_index(drop=True)

    return load_actual_df, load_forecast_df


# ─────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Télécharge les données réelles NYISO load pour PGScen"
    )
    parser.add_argument(
        '--years', nargs='+', type=int,
        default=list(range(2010, 2026)),
        help='Années à télécharger (défaut: 2010 à 2025)'
    )
    parser.add_argument(
        '--output', '-o', type=str, default='./data/NYISO_real',
        help='Répertoire de sortie (défaut: ./data/NYISO_real)'
    )

    args = parser.parse_args()
    years = sorted(args.years)
    output_dir = args.output

    print("=" * 60)
    print("Téléchargement des données réelles NYISO Load")
    print("=" * 60)
    print(f"Années: {years}")
    print(f"Sortie: {output_dir}")
    print()

    # Télécharger
    print("--- Actuals (load_h) ---")
    actuals = download_actuals(years)

    print("\n--- Forecasts day-ahead (load_forecast_h) ---")
    forecasts = download_forecasts(years)

    # Valider
    actuals, forecasts = validate_and_clean(actuals, forecasts)

    # Sauvegarder
    actual_path, forecast_path = save_pgscen_format(
        actuals, forecasts, output_dir, years
    )

    # Instructions
    print("\n" + "=" * 60)
    print("TERMINÉ !")
    print("=" * 60)
    print()
    print("Pour utiliser ces données dans le notebook PGScen :")
    print()
    print("  Option 1 — Remplacer les fichiers NREL :")
    print(f"    cp {actual_path} <pgscen_repo>/data/NYISO/Load/Actual/")
    print(f"    cp {forecast_path} <pgscen_repo>/data/NYISO/Load/Day-ahead/")
    print("    (il faudra renommer les fichiers pour matcher les noms attendus)")
    print()
    print("  Option 2 — Charger directement dans le notebook :")
    print("    from download_nyiso_real_load import load_real_ny_load_data")
    print(f"    load_actual, load_forecast = load_real_ny_load_data('{output_dir}')")
    print()
    print("  Note: pour wind et solar, les données NREL/PERFORM restent")
    print("  la meilleure source publique à granularité site-par-site.")


if __name__ == '__main__':
    main()
