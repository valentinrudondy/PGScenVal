#!/usr/bin/env python3
"""
download_nyiso_real_load.py
===========================
Télécharge les données réelles de charge NYISO (actuals + forecasts day-ahead)
et les reformate au format attendu par PGScen.

Prérequis :
    pip install git+https://github.com/m4rz910/NYISOToolkit#egg=nyisotoolkit

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
#  1. Téléchargement des données via NYISOToolkit
# ─────────────────────────────────────────────────────────────
def download_actuals(years):
    """
    Télécharge les actuals horaires de charge par zone NYISO.
    
    Retourne un DataFrame indexé par Time (UTC) avec une colonne par zone.
    """
    from nyisotoolkit import NYISOData

    frames = []
    for year in years:
        print(f"  Téléchargement actuals {year}...")
        df = NYISOData(dataset='load_h', year=str(year)).df
        # df est déjà en UTC avec un DatetimeIndex
        frames.append(df)

    actuals = pd.concat(frames).sort_index()

    # Supprimer les doublons éventuels (chevauchement entre années)
    actuals = actuals[~actuals.index.duplicated(keep='first')]

    # Identifier les colonnes de zones (exclure le total NYISO s'il existe)
    zone_cols = [c for c in actuals.columns if c not in EXCLUDE_COLS]
    actuals = actuals[zone_cols]

    # Renommer les colonnes si nécessaire (parfois NYISOToolkit les retourne déjà
    # avec les bons noms, parfois avec des noms longs)
    rename_map = {}
    for col in actuals.columns:
        for short_name, target in ZONE_NAME_MAP.items():
            if short_name.lower() in col.lower() or col == short_name:
                rename_map[col] = target
                break
    if rename_map:
        actuals = actuals.rename(columns=rename_map)

    # S'assurer que l'index est nommé 'Time'
    actuals.index.name = 'Time'

    print(f"  → Actuals: {actuals.shape[0]} heures, {actuals.shape[1]} zones")
    print(f"    Période: {actuals.index.min()} → {actuals.index.max()}")
    print(f"    Zones: {list(actuals.columns)}")

    return actuals


def download_forecasts(years):
    """
    Télécharge les prévisions day-ahead de charge par zone NYISO.
    
    Retourne un DataFrame avec colonnes Issue_time, Forecast_time, + zones.
    
    Convention PGScen :
      - Issue_time  = quand la prévision a été émise (ex: 2019-06-14 18:00 UTC)
      - Forecast_time = l'heure pour laquelle la prévision est faite (ex: 2019-06-15 06:00 UTC)
      
    NYISO publie le forecast day-ahead chaque jour. Le forecast couvre les 24h
    du jour suivant. L'issue_time est typiquement la veille vers 18:00 UTC
    (12:00-13:00 Eastern, après le close du marché day-ahead).
    """
    from nyisotoolkit import NYISOData

    frames = []
    for year in years:
        print(f"  Téléchargement forecasts {year}...")
        df = NYISOData(dataset='load_forecast_h', year=str(year)).df
        frames.append(df)

    forecasts_raw = pd.concat(frames).sort_index()
    forecasts_raw = forecasts_raw[~forecasts_raw.index.duplicated(keep='first')]

    # Identifier les colonnes de zones
    zone_cols = [c for c in forecasts_raw.columns if c not in EXCLUDE_COLS]
    forecasts_raw = forecasts_raw[zone_cols]

    # Renommer les colonnes
    rename_map = {}
    for col in forecasts_raw.columns:
        for short_name, target in ZONE_NAME_MAP.items():
            if short_name.lower() in col.lower() or col == short_name:
                rename_map[col] = target
                break
    if rename_map:
        forecasts_raw = forecasts_raw.rename(columns=rename_map)

    # ─── Construction du format PGScen ───
    # PGScen attend un forecast day-ahead avec :
    #   Issue_time :    moment d'émission (veille à 18:00 UTC = 12:00 EST + lead time)
    #   Forecast_time : l'heure prédite
    #
    # Le forecast NYISO couvre le jour suivant de 00:00 à 23:00 (Eastern).
    # Lead time PGScen pour NYISO = 12h (start_hour='06:00:00' UTC, issue = veille 18:00 UTC)
    #
    # On regroupe par jour calendaire UTC et on assigne l'issue_time correspondant.

    forecasts_raw.index.name = 'Forecast_time'
    forecasts_raw = forecasts_raw.reset_index()

    # Déterminer le jour de forecast (en UTC)
    forecasts_raw['forecast_date'] = forecasts_raw['Forecast_time'].dt.date

    # Issue_time = veille à 18:00 UTC (convention PGScen pour NYISO, lead time = 12h,
    # les scénarios commencent à 06:00 UTC du jour J)
    forecasts_raw['Issue_time'] = pd.to_datetime(
        forecasts_raw['forecast_date'] - pd.Timedelta(days=1)
    ) + pd.Timedelta(hours=18)
    forecasts_raw['Issue_time'] = forecasts_raw['Issue_time'].dt.tz_localize('UTC')

    # Réorganiser les colonnes dans l'ordre PGScen
    zone_cols_final = [c for c in forecasts_raw.columns 
                       if c not in {'Forecast_time', 'Issue_time', 'forecast_date'}]
    forecasts = forecasts_raw[['Issue_time', 'Forecast_time'] + zone_cols_final].copy()

    # Supprimer les lignes où toutes les zones sont NaN
    forecasts = forecasts.dropna(subset=zone_cols_final, how='all')

    print(f"  → Forecasts: {len(forecasts)} lignes")
    print(f"    Période: {forecasts['Forecast_time'].min()} → {forecasts['Forecast_time'].max()}")
    print(f"    Zones: {zone_cols_final}")
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
