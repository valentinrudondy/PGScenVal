# HRRR Pipeline for PGScen-NYISO Wind & Solar Timeseries

## Overview

This pipeline produces hourly actuals and day-ahead forecasts for 31 wind and 16 solar plants in the NYISO region, derived entirely from NOAA's High-Resolution Rapid Refresh (HRRR) model. Both actuals and forecasts come from HRRR, ensuring the deviation (actual - forecast) captures the model's own forecast error — the quantity GEMINI should be modeling.

## Data Source

- **HRRR archive**: `s3://noaa-hrrr-bdp-pds/` (AWS Open Data, public, no authentication)
- **File pattern**: `hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcfFF.grib2`
- **Archive start**: July 30, 2014
- **Grid**: 3 km Lambert Conformal Conic (CONUS), 1059 x 1799 grid points

## Actuals vs Forecasts

| Quantity | HRRR Run | Forecast Horizon | Interpretation |
|----------|----------|-----------------|----------------|
| **Actuals** | Every hour (00-23Z) | F00 (analysis) | Best estimate of the atmosphere at the valid hour |
| **Day-ahead forecasts** | 06Z run of J-1 | F18-F41 | Previous day's 06Z extended run forecasting hours 00-23Z of day J |

The 06Z run is one of four "extended" HRRR runs (00, 06, 12, 18 UTC) that produce forecasts out to 48 hours. The standard runs only go to 18 hours.

## HRRR Variables Extracted

Extraction uses byte-range downloads via `.idx` sidecar files, downloading ~2 MB per file instead of the full ~137 MB `wrfsfc` file.

| Variable | GRIB shortName | Level | Used for |
|----------|---------------|-------|----------|
| U-wind 80m | `u` | heightAboveGround, level=80 | Wind power (U component) |
| V-wind 80m | `v` | heightAboveGround, level=80 | Wind power (V component) |
| Downward SW radiation | `sdswrf` | surface | Solar power (GHI) |
| 2m temperature | `2t` | heightAboveGround, level=2 | Solar cell temperature model |

## Power Conversion

### Wind

Generic onshore power curve for modern large-rotor turbines (no per-turbine data available from Gold Book):

- **Cut-in**: 3 m/s
- **Rated wind speed**: 11 m/s (fleet-weighted average for NY: mix of older 12 m/s turbines and newer large-rotor designs at ~10 m/s)
- **Cut-out**: 25 m/s
- **Ramp**: Cubic interpolation between cut-in and rated: `P = nameplate * ((ws - 3) / (11 - 3))^3`
- **Output**: Scaled to each plant's `nameplate_mw`

Wind speed at 80 m AGL is computed as `ws80 = sqrt(U^2 + V^2)`.

### Solar

PVlib-based conversion with PVWatts model:

- **Tilt**: Fixed at latitude of each plant (south-facing, azimuth=180)
- **DNI decomposition**: DISC model from GHI
- **Cell temperature**: SAPM model (default open-rack glass/cell coefficients)
- **DC power**: PVWatts model with temperature coefficient -0.4%/C
- **AC output**: PVWatts default losses (~14%)
- **Clipped** to [0, nameplate_mw]

No per-plant module/inverter selection — we don't know the actual hardware.

## Plant Metadata

Plant list comes from `data/NYISO_real/plant_metadata/wind_meta.csv` and `solar_meta.csv`, produced by scripts 01-04 from the 2025 Gold Book, EIA-860, and USWTDB.

**Operating year filter**: Plants are excluded from years before their `operating_year`. A plant that came online in 2023 produces zero output in all files for 2019-2022.

## Nearest-Neighbor Lookup

HRRR uses a Lambert Conformal Conic projection. We build a KDTree on the HRRR lat/lon 2D arrays (converted to -180..180 longitude) and query nearest-neighbor for each plant's lat/lon. Typical distance to nearest grid point: ~1-2 km (the HRRR grid is 3 km).

The KDTree is built once from a reference file and reused for all hours (the HRRR grid is static across all runs).

## HRRR Version History

| Version | Date | Notes |
|---------|------|-------|
| v1 | Sep 2014 | Initial operational HRRR |
| v2 | Aug 2016 | Improved physics, data assimilation |
| v3 | Jul 2018 | Smoke/dust, more obs assimilated |
| v4 | Dec 2020 | Major upgrade, sub-hourly output |

Variable names and levels are stable across versions. Forecast skill improves with each version. The 2018+ range (v3/v4) is recommended for PGScen training.

## Output Format

### Actuals (`wind_actual_1h_site_YYYY_utc.csv`)

```
Time,wind_323596,wind_323608,...
2019-01-01 00:00:00+00:00,12.3,45.1,...
```

- Index: `Time`, hourly UTC
- Columns: `site_id` from metadata
- Values: MW

### Day-ahead Forecasts (`wind_day_ahead_forecast_site_YYYY_utc.csv`)

```
Issue_time,Forecast_time,wind_323596,wind_323608,...
2018-12-31 06:00:00+00:00,2019-01-01 00:00:00+00:00,10.5,42.8,...
```

- `Issue_time`: J-1 06:00 UTC
- `Forecast_time`: each hour of day J (00-23 UTC)
- 24 rows per day, 8760 rows per year

## Known Limitations

1. **Generic power curve**: All wind plants use the same IEC Class III curve regardless of actual turbine type. This introduces systematic bias for plants with different turbine models.
2. **Fixed-tilt solar assumption**: All solar plants assumed latitude-tilt south-facing. Actual installations may track or have different orientations.
3. **Single grid point**: Each plant maps to one 3 km HRRR grid point. Large wind farms span multiple grid cells — no spatial averaging is done.
4. **HRRR model bias**: HRRR has known biases in wind speed and GHI that vary by region and season. No bias correction is applied.
5. **Missing data**: Some HRRR runs failed operationally. These hours appear as NaN in the output. Typical miss rate is <1%.

## Usage

```bash
python scripts/05_build_hrrr_timeseries.py \
    --resource wind --year 2019 \
    --meta data/NYISO_real/plant_metadata/wind_meta.csv \
    --out data/NYISO_real/wind/ \
    --workers 15
```
