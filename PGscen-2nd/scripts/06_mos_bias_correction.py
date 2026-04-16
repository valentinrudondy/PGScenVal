"""
MOS (Model Output Statistics) bias correction + temporal smoothing
for HRRR-derived wind and solar day-ahead forecasts.

Fits a mean-variance correction per (plant, month, hour-of-day) bin
using historical (actual, forecast) pairs, then applies it.
Finally, applies temporal smoothing (rolling average) to remove
hour-to-hour noise from the NWP forecast.

Usage:
    python 06_mos_bias_correction.py \
        --resource wind \
        --data-dir data/NYISO_real/wind/ \
        --meta data/NYISO_real/plant_metadata/wind_meta.csv \
        --years 2019 2020 2021 2022 2023 2024 \
        --smooth-window 3
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def load_actual_forecast(data_dir: Path, resource: str, years: list[int],
                         meta: pd.DataFrame):
    """Load and align actual + forecast data for given years."""
    actual_dfs = []
    forecast_dfs = []

    for y in years:
        act_path = data_dir / f"{resource}_actual_1h_site_{y}_utc.csv"
        fc_path = data_dir / f"{resource}_day_ahead_forecast_site_{y}_utc.csv"
        if not act_path.exists() or not fc_path.exists():
            log.warning("Missing files for %d, skipping", y)
            continue

        act = pd.read_csv(act_path, parse_dates=["Time"], index_col="Time")
        fc = pd.read_csv(fc_path, parse_dates=["Issue_time", "Forecast_time"])
        actual_dfs.append(act)
        forecast_dfs.append(fc)

    actual = pd.concat(actual_dfs).sort_index()
    actual = actual[~actual.index.duplicated(keep="first")].dropna()

    forecast = pd.concat(forecast_dfs, ignore_index=True)
    forecast = forecast.drop_duplicates(
        subset=["Issue_time", "Forecast_time"], keep="first"
    )

    # Site columns = intersection of actual columns and forecast columns
    site_cols = sorted(
        set(actual.columns) & set(forecast.columns) - {"Issue_time", "Forecast_time"}
    )

    return actual[site_cols], forecast, site_cols


def fit_mos_params(actual: pd.DataFrame, forecast: pd.DataFrame,
                   site_cols: list[str]) -> pd.DataFrame:
    """Fit MOS parameters: per (plant, month, hour) mean-variance correction.

    Returns DataFrame indexed by (site, month, hour) with columns:
        mu_a, sigma_a, mu_f, sigma_f
    """
    # Align actual and forecast on time
    fc = forecast.set_index("Forecast_time")[site_cols].copy()
    fc.index = pd.to_datetime(fc.index, utc=True)
    common_idx = actual.index.intersection(fc.index)

    act_aligned = actual.loc[common_idx]
    fc_aligned = fc.loc[common_idx]

    log.info("Fitting MOS on %d aligned hours, %d plants", len(common_idx), len(site_cols))

    records = []
    for site in site_cols:
        a = act_aligned[site]
        f = fc_aligned[site]
        for month in range(1, 13):
            for hour in range(24):
                mask = (a.index.month == month) & (a.index.hour == hour)
                a_sub = a[mask]
                f_sub = f[mask]
                if len(a_sub) < 5:
                    continue
                records.append({
                    "site": site,
                    "month": month,
                    "hour": hour,
                    "mu_a": a_sub.mean(),
                    "sigma_a": a_sub.std(),
                    "mu_f": f_sub.mean(),
                    "sigma_f": f_sub.std(),
                    "count": len(a_sub),
                })

    params = pd.DataFrame(records)
    log.info("MOS params: %d rows", len(params))
    return params


def apply_mos(forecast: pd.DataFrame, params: pd.DataFrame,
              site_cols: list[str], nameplates: dict[str, float]) -> pd.DataFrame:
    """Apply MOS correction to forecast DataFrame.

    corrected = (raw - mu_f) * (sigma_a / sigma_f) + mu_a
    Then clip to [0, nameplate].
    """
    fc = forecast.copy()
    fc_time = pd.to_datetime(fc["Forecast_time"], utc=True)

    # Build lookup: (site, month, hour) -> params
    params_idx = params.set_index(["site", "month", "hour"])

    for site in site_cols:
        raw = fc[site].values.copy()
        months = fc_time.dt.month.values
        hours_utc = fc_time.dt.hour.values
        corrected = raw.copy()

        for i in range(len(raw)):
            key = (site, int(months[i]), int(hours_utc[i]))
            if key in params_idx.index:
                p = params_idx.loc[key]
                mu_f = p["mu_f"]
                sigma_f = p["sigma_f"]
                mu_a = p["mu_a"]
                sigma_a = p["sigma_a"]

                if sigma_f > 1e-6:
                    corrected[i] = (raw[i] - mu_f) * (sigma_a / sigma_f) + mu_a
                else:
                    corrected[i] = mu_a

        # Clip to [0, nameplate]
        np_mw = nameplates.get(site, np.inf)
        corrected = np.clip(corrected, 0, np_mw)
        fc[site] = corrected

    return fc


def apply_temporal_smoothing(forecast: pd.DataFrame, site_cols: list[str],
                             window: int = 3) -> pd.DataFrame:
    """Apply centered rolling average to forecast within each day's 24h block."""
    fc = forecast.copy()

    # Group by Issue_time (each day's forecast block)
    groups = fc.groupby("Issue_time")
    smoothed_parts = []

    for issue_time, group in groups:
        g = group.sort_values("Forecast_time").copy()
        g[site_cols] = g[site_cols].rolling(
            window, center=True, min_periods=1
        ).mean()
        smoothed_parts.append(g)

    result = pd.concat(smoothed_parts, ignore_index=True)
    # Clip to non-negative
    result[site_cols] = result[site_cols].clip(lower=0)
    return result


def main():
    ap = argparse.ArgumentParser(
        description="MOS bias correction + temporal smoothing for forecasts"
    )
    ap.add_argument("--resource", required=True, choices=["wind", "solar"])
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--meta", required=True, type=Path)
    ap.add_argument("--years", required=True, nargs="+", type=int)
    ap.add_argument("--smooth-window", type=int, default=3)
    args = ap.parse_args()

    meta = pd.read_csv(args.meta)
    nameplates = dict(zip(meta["site_id"], meta["nameplate_mw"]))

    # Load all data
    actual, forecast, site_cols = load_actual_forecast(
        args.data_dir, args.resource, args.years, meta
    )

    # Fit MOS
    params = fit_mos_params(actual, forecast, site_cols)
    params_path = args.data_dir / f"{args.resource}_mos_params.csv"
    params.to_csv(params_path, index=False)
    log.info("Saved MOS params to %s", params_path)

    # Apply MOS + smoothing to each year's forecast file
    for y in args.years:
        fc_path = args.data_dir / f"{args.resource}_day_ahead_forecast_site_{y}_utc.csv"
        if not fc_path.exists():
            continue

        fc = pd.read_csv(fc_path, parse_dates=["Issue_time", "Forecast_time"])
        fc_site_cols = [c for c in site_cols if c in fc.columns]

        # Backup original
        backup_path = fc_path.with_suffix(".csv.raw_backup")
        if not backup_path.exists():
            fc.to_csv(backup_path, index=False)
            log.info("Backed up original forecast to %s", backup_path)

        # Apply MOS
        fc_corrected = apply_mos(fc, params, fc_site_cols, nameplates)

        # Apply temporal smoothing
        fc_smoothed = apply_temporal_smoothing(
            fc_corrected, fc_site_cols, window=args.smooth_window
        )

        # Write
        fc_smoothed.to_csv(fc_path, index=False)
        log.info("Wrote corrected forecast: %s", fc_path)

    log.info("Done!")


if __name__ == "__main__":
    main()
