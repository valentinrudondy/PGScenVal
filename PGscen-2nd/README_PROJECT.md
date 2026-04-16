# PGScen NYISO — Project Documentation

## Overview

This project adapts the PGScen (Power Grid Scenario Generation) framework — originally developed at Princeton for Texas/ERCOT data — to generate Monte Carlo scenarios for load, wind, and solar power in the **NYISO (New York)** region using **real NYISO data** for load and **NREL/PERFORM synthetic data** for wind and solar.

The methodology is based on the paper:
> R. Carmona & X. Yang, *"Joint Granular Model for Load, Solar and Wind Power Scenario Generation"*, IEEE, 2021.
> File: `ieee_revision_2.pdf`

---

## Repository Structure

```
PGscen-main/
├── pgscen/                          # PGScen Python package (modified fork)
│   ├── engine.py                    # GeminiEngine — orchestrates scenario generation
│   ├── model.py                     # GeminiModel — GEMINI fitting + MC generation
│   ├── pca.py                       # PCAGeminiEngine — solar scenario generation with PCA
│   ├── scoring.py                   # Energy scores and variograms
│   ├── utils/
│   │   ├── data_utils.py            # Data loading + train/test split (modified: timezone fix)
│   │   └── r_utils.py               # Python↔R bridge: GPD fitting, ECDF, gaussianize, GEMINI
│   └── rts_gmlc/                    # RTS-GMLC variant (not used here)
│
├── data/
│   ├── NYISO/                       # NREL/PERFORM synthetic data (bundled)
│   │   ├── Load/                    # Synthetic load actuals + forecasts (2018-2019)
│   │   ├── Wind/                    # Synthetic wind actuals + forecasts + metadata (2019)
│   │   └── Solar/                   # Synthetic solar actuals + forecasts + metadata (2018-2019)
│   └── NYISO_real/                  # Real NYISO data (downloaded by script)
│       ├── load_actual_1h_zone_2018_..._utc.csv
│       └── load_day_ahead_forecast_zone_2018_..._utc.csv
│
├── Rsafd/                           # R package for GPD fitting (source, compiled at install)
├── Rsafd.zip                        # Archived source of Rsafd
├── pgscen_nyiso_analysis.ipynb      # Main analysis notebook
├── download_nyiso_real_load.py      # Script to download real NYISO load data
├── setup.py                         # Package installation (pip install -e .)
└── environment.yml                  # Conda environment specification
```

---

## Data Sources

### Load (real NYISO data)

Downloaded by `download_nyiso_real_load.py` from `mis.nyiso.com`:

- **Actuals**: hourly realized load per zone (11 zones), from the `pal` (Real-Time Actual Load) dataset. This is **net load** (includes behind-the-meter solar subtraction).
- **Forecasts**: day-ahead ISO load forecast per zone, from the `isolf` dataset. Each daily CSV file covers ~6 days of forecasts. The script selects only the **true day-ahead forecast** (file dated J-1 for forecast day J).

**Timezone handling**: NYISO publishes in Eastern time. The script converts to UTC. A forecast for Eastern day June 15 (00:00-23:00 ET) becomes UTC 04:00 June 15 → 03:00 June 16 (during EDT). Issue_time is set to J-1 18:00 UTC.

**Format (PGScen convention)**:
- `load_actual_1h_zone_*.csv`: index = `Time` (UTC), columns = zone names
- `load_day_ahead_forecast_zone_*.csv`: columns = `Issue_time`, `Forecast_time` (both UTC), + zone names

**Known data issue**: the MHK VL (Mohawk Valley) zone has a persistent ~100 MW positive bias (actual > forecast, ~97% of hours). This is a real NYISO forecast quality issue, likely caused by rapid growth of data centers/crypto mining in the region that traditional weather-based forecast models don't capture well. The bias has been decreasing over time (150 MW in 2018 → 60 MW in 2025).

### Wind and Solar (NREL/PERFORM synthetic data)

Bundled in `data/NYISO/`. Loaded via `load_ny_wind_data()` and `load_ny_solar_data()` in `data_utils.py`.

- **Wind**: 80 sites (existing + planned), actuals + forecasts for 2019, metadata with lat/lon/capacity
- **Solar**: 314 sites (existing + planned), actuals + forecasts for 2018-2019, metadata with lat/lon/capacity

These use a **different time convention** than the real NYISO data:
- Forecast blocks cover **06:00-05:00 UTC** (midnight-midnight Eastern, approximately)
- Issue_time at 18:00 UTC previous day
- Lead time = **12h**

---

## Scenario Generation Pipeline

### Model Fitting (for each asset type)

For a target date D:

1. **Train/test split**: all data before D is "historical" (training), D is the target.

2. **Compute deviations**: for each historical day, each zone/site and each hour: `deviation = actual - forecast`

3. **Gaussianization** (paper Section III.A, steps 3-5):
   - For **load**: fit a Generalized Pareto Distribution (GPD) to each (zone, hour) deviation series to handle heavy tails. Apply the GPD CDF → uniform [0,1] → apply Φ⁻¹ (inverse normal CDF) → Gaussian N(0,1).
   - For **wind**: use empirical CDF (ECDF) instead of GPD (deviations are bounded by capacity, no heavy tails).
   - For **solar**: same as wind (ECDF), then apply PCA to handle the diurnal zero-production issue.
   - Implemented in `r_utils.py:gaussianize()`, which calls R's Rsafd package.

4. **Standardization**: remove empirical mean and std from each column → exactly mean 0, variance 1. Saves `gauss_mean` and `gauss_std` for later reversal.

5. **GEMINI fit** (`model.py:282-329`): estimate a **separable** (Kronecker product) covariance structure:
   - `Σ = Σ_spatial ⊗ Σ_temporal`
   - `Σ_spatial` (N_zones × N_zones): captures correlations between zones/sites
   - `Σ_temporal` (24 × 24): captures correlations between hours
   - Uses the GEMINI algorithm (a variant of graphical LASSO for separable structures) from Zhou (2014).
   - Regularization parameters: `asset_rho` (spatial), `horizon_rho` (temporal). For wind, `asset_rho` is proportional to physical distance between sites.

### Scenario Generation

6. **Draw Gaussian samples** (`model.py:402-451`): generate N_scenarios vectors from N(0, Σ_spatial ⊗ Σ_temporal) using `sqrt(Σ_spatial) ⊗ sqrt(Σ_temporal) × random_normal`.

7. **De-standardize** (`model.py:456-457`): `scen = scen × gauss_std + gauss_mean`

8. **Inverse-gaussianize** (`model.py:464-476`):
   - Apply normal CDF Φ → uniform [0,1]
   - Apply inverse GPD/ECDF → deviations in MW with original marginal distribution
   - For wind: uses **conditional marginals** (ECDF conditioned on similar forecast values) to account for forecast-dependent deviation distributions (paper Section IV.C).

9. **Add forecast** (`model.py:482`): `scenario = deviation + forecast_for_day_D`

10. **Clip** (`model.py:484-496`): clip to [0, capacity] (load clipped at 0, wind/solar at [0, capacity]).

Result: a DataFrame of shape (N_scenarios, N_assets × 24) with scenario values in MW.

---

## Notebook Structure (`pgscen_nyiso_analysis.ipynb`)

### Section 1 — Data Loading and Exploration
- **Cell 1**: Imports. Forces `sys.path` to use the local pgscen package, not conda-installed.
- **Cell 4**: Data source config. `USE_REAL_NYISO_LOAD = True` loads real NYISO data via `download_nyiso_real_load.py`. Wind/solar always from NREL.
- **Cells 5-6**: Exploratory plots (load time series, wind/solar site map).

### Section 2 — Load Scenario Generation
- **Cell 8**: Parameters. `SCEN_DATE`, `START_HOUR = '04:00:00'` (start of Eastern day in UTC), `N_SCENARIOS = 1000`.
- **Cell 9**: `GeminiEngine` with `forecast_lead_time_in_hour=10` (18:00 UTC + 10h = 04:00 UTC).
- **Cell 11**: Q-Q plots of load deviations — checks for heavy tails (justifies GPD fitting).
- **Cell 13**: GEMINI correlation visualization (temporal chain + spatial graph).
- **Cells 15-16**: `plot_scenarios()` — 1%-99% band, 10 sample scenarios, actual (red), forecast (blue).

### Section 3 — Wind Scenario Generation
- **Cell 18**: Uses NREL data, `WIND_SCEN_DATE = '2019-06-15'`, `START_HOUR = '06:00:00'`, `lead_time=12` (NREL convention). Spatial regularization proportional to inter-site distance.
- **Cell 20**: Wind scenario visualization with `wind_scen_timesteps`.
- **Cell 22**: Scatter plot of deviations vs forecasts (shows forecast-dependent variance, justifies conditional marginals).

### Section 4 — Solar Scenario Generation
- **Cell 24**: Uses `PCAGeminiEngine`, NREL data, `SOLAR_SCEN_DATE = '2019-06-15'`, `START_HOUR = '06:00:00'`, `lead_time=12`. PCA with 90% explained variance, `nearest_days=50`.
- **Cell 26**: Solar scenario visualization with `solar_scen_timesteps`.

### Section 5 — GPD vs Gaussian Comparison
- **Cell 28**: Compares scenario coverage with and without heavy-tail GPD fitting (reproduces paper Figures 5-6).

### Section 6 — Evaluation Metrics
- **Cells 30-31**: Energy Scores (multivariate proper scoring rule).
- **Cells 33-34**: Variograms (spatial-temporal dependency assessment).

### Section 7 — Multi-day Execution
- **Cell 36**: Runs scenarios across multiple dates. Load uses real NYISO dates (2023) with `start=04:00, lead=10`. Wind/solar use NREL dates (2019) with `start=06:00, lead=12`.
- **Cells 37-38**: Summary bar plots of mean Energy Scores and Variograms.
- **Cell 40**: Recap table.

---

## Key Parameters and Conventions

### Two different time conventions coexist:

| Data source | Forecast block (UTC) | START_HOUR (UTC) | lead_time | Issue_time |
|---|---|---|---|---|
| Real NYISO load | 04:00 → 03:00+1d | `04:00:00` | **10h** | J-1 18:00 UTC |
| NREL wind/solar | 06:00 → 05:00+1d | `06:00:00` | **12h** | J-1 18:00 UTC |

This difference exists because real NYISO forecasts cover an Eastern calendar day (00:00-23:00 ET = 04:00-03:00 UTC in summer), while NREL synthetic data was designed for ERCOT with a slightly different convention.

### Regularization parameters
- `ASSET_RHO = 0.1` — spatial regularization (higher = sparser spatial graph)
- `TIME_RHO = 0.1` — temporal regularization (higher = sparser temporal graph)
- Wind: `asset_rho = 2 × ASSET_RHO × dist / dist.max()` (proportional to distance)
- Solar: `asset_rho = 20 × ASSET_RHO × dist / dist.max()` (stronger regularization)

---

## Modified Files (vs original PGScen)

### `pgscen/model.py` (line 235)
- `set_levels(..., level=0)` instead of `level=1` — fixes MultiIndex level assignment for the (asset, horizon) deviation matrix.

### `pgscen/utils/data_utils.py` (lines 15-45)
- Added timezone alignment in `split_actuals_hist_future()` and `split_forecasts_hist_future()` to handle comparison between tz-aware (real NYISO UTC) and tz-naive timestamps.

### `download_nyiso_real_load.py`
- **Actuals**: downloaded via NYISOToolkit (`load_h` dataset). Works correctly.
- **Forecasts**: downloaded **directly from mis.nyiso.com** (not via NYISOToolkit, which has timezone/resampling bugs). Parses `isolf` CSV files, converts Eastern → UTC, selects true day-ahead forecast (file dated J-1 for day J).

---

## Environment

- **Python 3.8** (required for rpy2/R bridge)
- **R 4.2** (via conda) with packages: Rsafd, glasso, qgraph, robustbase
- **rpy2 3.5.11** — Python↔R interface
- **pandas 1.5.3** — compatible with PGScen code
- **Conda env**: `pgscen` (see `environment.yml`)
- **NYISOToolkit**: `pip install --no-deps git+https://github.com/m4rz910/NYISOToolkit` (used only for actuals, not forecasts)

To recreate from scratch:
```bash
conda create -n pgscen -c conda-forge python=3.8 r-essentials=4.2 r-envstats r-robustbase r-quantreg r-mvtnorm r-quadprog pandas=1.5.3 rpy2=3.5.11
conda activate pgscen
pip install -e .
pip install --no-deps git+https://github.com/m4rz910/NYISOToolkit
python download_nyiso_real_load.py --years 2018 2019 2020 2021 2022 2023 2024 2025
```
