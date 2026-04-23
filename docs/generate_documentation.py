#!/usr/bin/env python3
"""Generate a comprehensive Word document covering PGScen, Vatic, NYISOLoader,
and their integration into the NYISO power grid simulation pipeline."""

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.style import WD_STYLE_TYPE
import os

doc = Document()

# ── Style helpers ──────────────────────────────────────────────────────
style = doc.styles['Normal']
font = style.font
font.name = 'Calibri'
font.size = Pt(11)
style.paragraph_format.space_after = Pt(6)
style.paragraph_format.line_spacing = 1.15

for level in range(1, 5):
    hs = doc.styles[f'Heading {level}']
    hs.font.color.rgb = RGBColor(0x1B, 0x3A, 0x5C)

def add_code_block(text):
    p = doc.add_paragraph()
    p.style = doc.styles['Normal']
    p.paragraph_format.left_indent = Cm(1)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    run.font.name = 'Consolas'
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    return p

def add_table(headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Light Shading Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(10)
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = str(val)
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(10)
    return table

def add_bullet(text, level=0, bold_prefix=None):
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.left_indent = Cm(1.27 + level * 0.63)
    if bold_prefix:
        run = p.add_run(bold_prefix)
        run.bold = True
        p.add_run(text)
    else:
        p.add_run(text)
    return p

# ══════════════════════════════════════════════════════════════════════
#  TITLE PAGE
# ══════════════════════════════════════════════════════════════════════
for _ in range(6):
    doc.add_paragraph()

title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run('NYISO Power Grid Simulation Pipeline')
run.bold = True
run.font.size = Pt(28)
run.font.color.rgb = RGBColor(0x1B, 0x3A, 0x5C)

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = subtitle.add_run(
    'Technical Documentation\n'
    'PGScen \u2022 Vatic \u2022 NYISOLoader \u2022 System Integration'
)
run.font.size = Pt(14)
run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

for _ in range(4):
    doc.add_paragraph()

meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = meta.add_run(
    'Princeton University \u2013 Operations Research & Financial Engineering\n'
    'April 2026\n\n'
    'Authors: Valentin Rudon\n'
    'Advisors: Warren B. Powell'
)
run.font.size = Pt(11)
run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

doc.add_page_break()

# ══════════════════════════════════════════════════════════════════════
#  TABLE OF CONTENTS (placeholder)
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('Table of Contents', level=1)
toc_items = [
    'Part I \u2013 PGScen: Probabilistic Scenario Generation',
    '    1.1  Overview and Motivation',
    '    1.2  Mathematical Foundation: The GEMINI Model',
    '    1.3  Software Architecture',
    '    1.4  Data Pipeline',
    '    1.5  NYISO Adaptation',
    '    1.6  HRRR Real-Time Weather Pipeline (PGScen-2nd)',
    '    1.7  Validation and Calibration',
    '    1.8  Configuration and Hyperparameters',
    '',
    'Part II \u2013 Vatic: Power Grid Simulation Engine',
    '    2.1  Overview and Purpose',
    '    2.2  Unit Commitment and Economic Dispatch',
    '    2.3  Software Architecture',
    '    2.4  Optimization Formulations',
    '    2.5  Data Structures and Model Representation',
    '    2.6  Simulation Workflow',
    '    2.7  Output and Results',
    '    2.8  Supported Grid Datasets',
    '',
    'Part III \u2013 NYISOLoader: Grid Model Adapter',
    '    3.1  Overview and Design Rationale',
    '    3.2  The NYgrid Baseline (NPCC-140)',
    '    3.3  Data Mapping: NYgrid to Vatic',
    '    3.4  Generator Modeling',
    '    3.5  Transmission and Interfaces',
    '    3.6  Timeseries Integration',
    '    3.7  Fleet Updates Across Years',
    '    3.8  Supporting Modules',
    '',
    'Part IV \u2013 System Integration',
    '    4.1  End-to-End Pipeline Overview',
    '    4.2  Data Flow Architecture',
    '    4.3  Experiment Orchestration',
    '    4.4  Stochastic vs. Deterministic Analysis',
    '    4.5  Validated Results',
    '    4.6  Known Limitations and Future Work',
]
for item in toc_items:
    if item == '':
        doc.add_paragraph()
    elif item.startswith('Part'):
        p = doc.add_paragraph(item)
        for run in p.runs:
            run.bold = True
    else:
        doc.add_paragraph(item)

doc.add_page_break()

# ══════════════════════════════════════════════════════════════════════
#  PART I: PGScen
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('Part I \u2013 PGScen: Probabilistic Scenario Generation', level=1)

# ── 1.1 Overview ──
doc.add_heading('1.1  Overview and Motivation', level=2)
doc.add_paragraph(
    'PGScen (Power Grid Scenario Generation) is a Monte Carlo scenario generation '
    'framework developed at Princeton University for creating realistic, '
    'spatially and temporally correlated power system scenarios. The framework '
    'generates probabilistic scenarios for load demand, wind generation, and '
    'solar generation that capture the full joint distribution of forecast '
    'errors across multiple assets and time horizons.'
)
doc.add_paragraph(
    'The core motivation is that power system operations \u2014 particularly unit '
    'commitment and economic dispatch \u2014 must account for uncertainty in '
    'renewable generation and load demand. Point forecasts alone are insufficient; '
    'operators need an ensemble of plausible futures that faithfully represent '
    'the spread, correlations, and tail risks of forecast errors. PGScen provides '
    'this capability through a statistically rigorous approach based on the '
    'GEMINI (Generalized Graphical Models with Kronecker-structured covariances) '
    'framework.'
)
doc.add_paragraph(
    'The project has evolved through two major versions:'
)
add_bullet('PGScen-main: The original framework, adapted from ERCOT (Texas) datasets '
           'to NYISO using real NYISO load data and synthetic NREL wind/solar data.')
add_bullet('PGScen-2nd: An enhanced version incorporating HRRR (High-Resolution '
           'Rapid Refresh) real-time meteorological data for wind and solar '
           'generation at actual NYISO plant locations.')
doc.add_paragraph(
    'Key insight: PGScen scenarios capture both the spread of possible outcomes '
    'and their correlations across space (different plants) and time (hour-to-hour) '
    '\u2014 not just point forecasts with additive random noise.'
)

# ── 1.2 Mathematical Foundation ──
doc.add_heading('1.2  Mathematical Foundation: The GEMINI Model', level=2)

doc.add_heading('1.2.1  Problem Formulation', level=3)
doc.add_paragraph(
    'Let Y(a,h) denote the actual power output (or demand) for asset a at '
    'forecast horizon h, and let F(a,h) denote the corresponding day-ahead '
    'forecast. The deviation (forecast error) is:'
)
add_code_block('D(a,h) = Y(a,h) \u2212 F(a,h)')
doc.add_paragraph(
    'The goal is to model the joint distribution of the deviation vector '
    'D = [D(a\u2081,h\u2081), D(a\u2081,h\u2082), ..., D(a_m,h_f)] across m assets '
    'and f = 24 forecast horizons, then sample from this distribution to '
    'generate scenarios.'
)

doc.add_heading('1.2.2  Gaussianization', level=3)
doc.add_paragraph(
    'Raw deviations are typically non-Gaussian with heavy tails, bounded support, '
    'and possibly multi-modal structure. PGScen transforms each marginal '
    'distribution to standard Gaussian using a two-step copula transform:'
)
doc.add_paragraph(
    'Step 1 \u2013 CDF Transform: For each (asset, horizon) pair, fit either a '
    'Generalized Pareto Distribution (GPD, for load with heavy tails) or an '
    'Empirical CDF (ECDF, for wind/solar with bounded support) to the historical '
    'deviation samples. Apply the fitted CDF:'
)
add_code_block('u = F_GPD(d)  or  u = F_ECDF(d)    \u2192  u \u2208 [0, 1]')
doc.add_paragraph(
    'Step 2 \u2013 Inverse Normal Transform: Apply the inverse standard normal CDF:'
)
add_code_block('z = \u03a6\u207b\u00b9(u)    \u2192  z \u2208 \u211d,  approximately N(0,1)')
doc.add_paragraph(
    'After Gaussianization, z-scores are standardized (mean removal and '
    'unit-variance scaling) to produce approximately i.i.d. N(0,1) marginals. '
    'The GPD fitting uses R\'s Rsafd package via rpy2, fitting separate GPD '
    'models to the upper and lower tails with ECDF for the central region.'
)

doc.add_heading('1.2.3  Separable Covariance via GEMINI', level=3)
doc.add_paragraph(
    'The key innovation in PGScen is fitting a separable (Kronecker-structured) '
    'covariance to the Gaussianized deviations. If we reshape the m\u00d7f '
    'deviation vector for each historical day into an f\u00d7m matrix X, the '
    'GEMINI model assumes:'
)
add_code_block('\u03a3 = \u03a3_spatial \u2297 \u03a3_temporal')
doc.add_paragraph('where:')
add_bullet('\u03a3_spatial (m \u00d7 m) captures cross-asset correlations '
           '(e.g., nearby wind farms experiencing similar weather)')
add_bullet('\u03a3_temporal (24 \u00d7 24) captures hour-to-hour autocorrelation '
           '(e.g., persistence of forecast errors)')
add_bullet('\u2297 denotes the Kronecker product')

doc.add_paragraph(
    'The GEMINI algorithm estimates these two covariance matrices by solving '
    'two nested graphical LASSO problems. For each matrix, the algorithm '
    'solves an L1-penalized maximum-likelihood estimation of the precision '
    '(inverse covariance) matrix:'
)
add_code_block(
    'A_rho = argmin_A { -log det(A) + tr(G_A \u00b7 A) + \u03c1_A \u2016A\u2016\u2081 }\n'
    'B_rho = argmin_B { -log det(B) + tr(G_B \u00b7 B) + \u03c1_B \u2016B\u2016\u2081 }'
)
doc.add_paragraph(
    'where G_A and G_B are empirical correlation matrices computed from the '
    'reshaped data, and \u03c1_A, \u03c1_B are regularization parameters that '
    'control sparsity. The graphical LASSO is solved using R\'s glasso package. '
    'Sparse entries in the precision matrix encode conditional independence: '
    'A_rho(i,j) = 0 means assets i and j are conditionally independent given '
    'all other assets.'
)

doc.add_heading('1.2.4  Scenario Sampling', level=3)
doc.add_paragraph(
    'Given the fitted covariance structure, new scenarios are sampled by '
    'reversing the Gaussianization pipeline:'
)
add_code_block(
    '1. Compute Kronecker square root:  L = sqrtm(\u03a3_spatial) \u2297 sqrtm(\u03a3_temporal)\n'
    '2. Sample standard normal:          z ~ N(0, I_{m\u00d7f})\n'
    '3. Apply covariance structure:       y = L \u00b7 z\n'
    '4. De-standardize:                   y\' = y \u00d7 \u03c3_gauss + \u03bc_gauss\n'
    '5. Inverse-Gaussianize:              u = \u03a6(y\')  \u2192  d = F\u207b\u00b9(u)\n'
    '6. Add day-ahead forecast:           s = d + forecast\n'
    '7. Clip to physical bounds:          s = clip(s, 0, capacity)'
)
doc.add_paragraph(
    'This procedure produces correlated scenario vectors that respect the '
    'observed marginal distributions, spatial correlations across assets, '
    'and temporal persistence across the 24-hour horizon. Typical runs '
    'generate 100\u20131000 scenarios per day.'
)

doc.add_heading('1.2.5  PCA Extension for Solar', level=3)
doc.add_paragraph(
    'Solar generation presents a unique challenge: nighttime hours have zero '
    'production, creating a degenerate (zero-inflated) distribution that '
    'violates the Gaussianization assumptions. PGScen addresses this through '
    'PCAGeminiEngine, which:'
)
add_bullet('Detects sunrise/sunset times using the astral library for each plant '
           'location and target date')
add_bullet('Restricts analysis to daytime-only hours (typically 6\u201318 depending on season)')
add_bullet('Applies PCA dimensionality reduction (default: 90% explained variance) '
           'to the daytime deviation matrix')
add_bullet('Fits GEMINI on the PCA-projected components, avoiding ill-conditioning '
           'from zero-inflated columns')
add_bullet('Generates scenarios in PCA space, then back-projects to original dimensions')
add_bullet('Pads nighttime hours with zeros in the final output')

# ── 1.3 Software Architecture ──
doc.add_heading('1.3  Software Architecture', level=2)

doc.add_heading('1.3.1  Core Modules', level=3)
add_table(
    ['Module', 'Primary Class', 'Responsibility'],
    [
        ['engine.py', 'GeminiEngine', 'Orchestrates the full scenario generation workflow: '
         'data loading, model fitting, scenario creation, and CSV export'],
        ['model.py', 'GeminiModel', 'Core algorithm: Gaussianization, standardization, '
         'GEMINI fitting, scenario sampling, and inverse transforms'],
        ['pca.py', 'PCAGeminiEngine', 'Solar-specific extension with sunrise/sunset detection '
         'and PCA dimensionality reduction'],
        ['utils/data_utils.py', '(functions)', 'Data loading for ERCOT, NYISO bundled, '
         'and HRRR-derived datasets'],
        ['utils/r_utils.py', '(functions)', 'Python\u2194R bridge: GPD fitting, Gaussianization, '
         'graphical LASSO, GEMINI algorithm'],
        ['scoring.py', '(functions)', 'Quality metrics: energy scores and variograms'],
    ]
)

doc.add_heading('1.3.2  GeminiEngine Class', level=3)
doc.add_paragraph(
    'GeminiEngine is the primary user-facing class. Its workflow:'
)
add_code_block(
    'engine = GeminiEngine(\n'
    '    hist_actual_df, hist_forecast_df,     # Historical training data\n'
    '    scen_start_time,                       # Target date (UTC)\n'
    '    asset_type="load",                     # "load", "wind", or "solar"\n'
    '    forecast_lead_time_in_hour=10          # Hours between issue and start\n'
    ')\n\n'
    'engine.fit(\n'
    '    asset_rho=0.1,       # Spatial regularization penalty\n'
    '    horizon_rho=0.1,     # Temporal regularization penalty\n'
    '    nearest_days=50      # Seasonal window (or None for all history)\n'
    ')\n\n'
    'engine.create_scenario(nscen=1000, forecast_df=fc_future)\n'
    'engine.write_to_csv(save_dir="scenarios/", actual_dfs=act_future)'
)

doc.add_heading('1.3.3  GeminiModel Class', level=3)
doc.add_paragraph(
    'GeminiModel (model.py, 616 lines) encapsulates the statistical machinery. '
    'Key attributes after fitting:'
)
add_table(
    ['Attribute', 'Shape', 'Description'],
    [
        ['gauss_df', 'n_days \u00d7 (m\u00d724)', 'Gaussianized, standardized deviations'],
        ['gpd_dict', 'dict per (asset, hour)', 'Fitted GPD or ECDF per marginal'],
        ['gauss_mean', 'm\u00d724', 'Mean for de-standardization'],
        ['gauss_std', 'm\u00d724', 'Std dev for de-standardization'],
        ['asset_cov', 'm \u00d7 m', 'Spatial covariance from GEMINI'],
        ['horizon_cov', '24 \u00d7 24', 'Temporal covariance from GEMINI'],
        ['scen_df', 'nscen \u00d7 (m\u00d724)', 'Final generated scenarios'],
    ]
)

# ── 1.4 Data Pipeline ──
doc.add_heading('1.4  Data Pipeline', level=2)

doc.add_heading('1.4.1  Input Data Format', level=3)
doc.add_paragraph('Actuals (e.g., load_actual_1h_zone_YYYY_utc.csv):')
add_code_block(
    'Time (index),              Zone_A, Zone_B, ...\n'
    '2018-01-01 00:00:00+00:00, 500,    450,    ...'
)
doc.add_paragraph('Forecasts (e.g., load_day_ahead_forecast_zone_YYYY_utc.csv):')
add_code_block(
    'Issue_time,                 Forecast_time,         Zone_A, Zone_B, ...\n'
    '2017-12-31 18:00:00+00:00, 2018-01-01 00:00:00,   480,    430,    ...\n'
    '2017-12-31 18:00:00+00:00, 2018-01-01 01:00:00,   485,    435,    ...'
)
doc.add_paragraph(
    'Forecasts use a MultiIndex with (Issue_time, Forecast_time). The issue '
    'time for day-ahead forecasts is typically 18:00 UTC on day J\u22121 for '
    'scenario day J, giving a 6\u201330 hour lead time depending on the forecast hour.'
)

doc.add_heading('1.4.2  Data Loading Functions', level=3)
add_table(
    ['Function', 'Source', 'Returns'],
    [
        ['load_ny_load_data()', 'Bundled NYISO CSVs', '(actual_df, forecast_df)'],
        ['load_ny_wind_data()', 'Bundled NREL CSVs', '(actual_df, forecast_df, meta_df)'],
        ['load_ny_solar_data()', 'Bundled NREL CSVs', '(actual_df, forecast_df, meta_df)'],
        ['load_ny_real_wind_data(years)', 'HRRR-derived CSVs', '(actual_df, forecast_df, meta_df)'],
        ['load_ny_real_solar_data(years)', 'HRRR-derived CSVs', '(actual_df, forecast_df, meta_df)'],
    ]
)

doc.add_heading('1.4.3  Deviation Extraction and Train/Test Split', level=3)
doc.add_paragraph(
    'For a target scenario date D, the engine computes deviations over the '
    'historical training window and provides two splitting strategies:'
)
add_bullet('Seasonal window (nearest_days=N): Uses only historical days within \u00b1N '
           'calendar days of the target date. Captures seasonality but reduces sample size.', bold_prefix='')
add_bullet('Full history (nearest_days=None): Uses all historical data before the '
           'target date. Maximizes sample size but ignores seasonal patterns.', bold_prefix='')

# ── 1.5 NYISO Adaptation ──
doc.add_heading('1.5  NYISO Adaptation', level=2)

doc.add_heading('1.5.1  Real NYISO Load Data', level=3)
doc.add_paragraph(
    'Real NYISO load data is downloaded from mis.nyiso.com using the '
    'download_nyiso_real_load.py script. The data comprises:'
)
add_bullet('Actuals: 11 NYISO zones (A through K), hourly real-time load from the '
           '"pal" (Integrated Real-Time Actual Load) dataset')
add_bullet('Forecasts: Day-ahead zonal load forecasts from the "isolf" '
           '(ISO Load Forecast) dataset')
add_bullet('Timezone handling: NYISO publishes in Eastern time; all data is '
           'converted to UTC for consistency')
add_bullet('Issue time convention: For scenario day J, the forecast is issued '
           'at 18:00 UTC on day J\u22121')

doc.add_paragraph(
    'A known data quality issue exists for the MHK VL (Mohawk Valley, Zone E) '
    'zone, which exhibits a persistent positive forecast bias of approximately '
    '60\u2013150 MW. This bias has been decreasing over time (150 MW in 2018, '
    '60 MW in 2025) and is attributed to rapid data center growth in the zone '
    'outpacing NYISO\'s load forecasting model.'
)

doc.add_heading('1.5.2  Synthetic NREL Wind and Solar Data', level=3)
doc.add_paragraph(
    'For wind and solar, the initial adaptation uses synthetic data from the '
    'NREL PERFORM dataset, bundled in the repository:'
)
add_bullet('Wind: 80 synthetic sites across New York, 2019 only, with NREL-generated '
           'forecast errors')
add_bullet('Solar: 314 synthetic sites, 2018\u20132019, with NREL-generated forecasts')
add_bullet('Forecast blocks: 06:00\u201305:00 UTC (corresponding to midnight\u2013midnight Eastern)')

# ── 1.6 HRRR Pipeline ──
doc.add_heading('1.6  HRRR Real-Time Weather Pipeline (PGScen-2nd)', level=2)
doc.add_paragraph(
    'PGScen-2nd introduces a complete pipeline for deriving wind and solar '
    'generation data from NOAA\'s High-Resolution Rapid Refresh (HRRR) '
    'numerical weather prediction model. This replaces the synthetic NREL '
    'data with real meteorological observations and forecasts at actual '
    'NYISO plant locations.'
)

doc.add_heading('1.6.1  Pipeline Steps', level=3)
add_table(
    ['Step', 'Script', 'Purpose', 'Output'],
    [
        ['1', '01_parse_goldbook.py', 'Extract plant data from 2025 NYISO Gold Book PDF', 'plant_master.csv'],
        ['2', '02_download_eia860.py', 'Fetch EIA Form 860 (lat/lon, capacity)', 'eia860_NY.csv'],
        ['3', '03_download_uswtdb.py', 'Fetch US Wind Turbine Database', 'uswtdb_NY.csv'],
        ['4', '04_build_plant_metadata.py', 'Fuzzy-match Gold Book \u2194 EIA/USWTDB', 'wind_meta.csv, solar_meta.csv'],
        ['5', '05_build_hrrr_timeseries.py', 'Download HRRR GRIB2 + power conversion', 'Actual/forecast CSVs'],
        ['6', '06_mos_bias_correction.py', 'Statistical post-processing (MOS)', 'Corrected forecast CSVs'],
    ]
)

doc.add_heading('1.6.2  HRRR Data Specifics', level=3)
add_bullet('Archive: AWS S3 bucket noaa-hrrr-bdp-pds (public, no authentication required)')
add_bullet('Grid resolution: 3 km Lambert Conformal (1059 \u00d7 1799 grid points)')
add_bullet('Byte-range downloads: ~2\u20135 MB per file instead of the full 137 MB GRIB2 '
           'using .idx sidecar index files')
add_bullet('Actuals: HRRR F00 (analysis fields) from every hour\'s run')
add_bullet('Forecasts: HRRR F18\u2013F41 from the 06Z run of the previous day (true day-ahead)')

doc.add_heading('1.6.3  Power Conversion Models', level=3)
doc.add_paragraph('Wind power conversion:')
add_bullet('Extracts UGRD and VGRD (U and V wind components) at 80 m above ground level')
add_bullet('Computes wind speed: ws = sqrt(U\u00b2 + V\u00b2)')
add_bullet('Applies generic IEC Class III onshore power curve: cut-in = 3 m/s, '
           'rated = 11 m/s, cut-out = 25 m/s')
add_bullet('Cubic ramp: P = nameplate \u00d7 [(ws \u2212 3) / (11 \u2212 3)]\u00b3')

doc.add_paragraph('Solar power conversion:')
add_bullet('Extracts DSWRF (downward shortwave radiation flux, i.e., GHI) and '
           'TMP (2 m temperature)')
add_bullet('Uses pvlib DISC model to decompose GHI into DNI + DHI')
add_bullet('Computes cell temperature using SAPM (Sandia Array Performance Model)')
add_bullet('Converts to DC power via PVWatts model, then applies ~14% AC losses')

doc.add_heading('1.6.4  Coverage', level=3)
doc.add_paragraph(
    'The HRRR pipeline covers 31 wind farms and 16 solar plants across New York '
    'State. Solar coverage increases over time as new plants come online '
    '(9 active in 2023, all 16 active by 2024). Plant metadata is matched '
    'across three databases (Gold Book, EIA-860, USWTDB) using fuzzy name '
    'matching combined with county and capacity sanity checks.'
)

# ── 1.7 Validation ──
doc.add_heading('1.7  Validation and Calibration', level=2)
doc.add_paragraph(
    'PGScen-2nd includes a comprehensive validation notebook that tests '
    'scenario calibration across 20 days spanning all four seasons of 2024. '
    'Key metrics:'
)
add_table(
    ['Metric', 'Wind', 'Solar'],
    [
        ['Per-plant P5\u2013P95 exceedance', '8\u201312%', '7\u201313%'],
        ['Per-plant P1\u2013P99 exceedance', '1\u20133%', '0.5\u20132%'],
        ['Fleet P5\u2013P95 exceedance', '18\u201325%', '12\u201318%'],
        ['Fleet P1\u2013P99 exceedance', '3\u20138%', '1\u20134%'],
    ]
)
doc.add_paragraph(
    'The fleet-level exceedance rates exceed the per-plant rates because '
    'GEMINI\'s Kronecker structure underestimates cross-plant correlations. '
    'When all wind farms experience low wind simultaneously (e.g., a '
    'large-scale high-pressure system), the separable model underestimates '
    'the probability of this joint event. This is a structural limitation '
    'of the Kronecker assumption, not a data issue.'
)
doc.add_paragraph(
    'Scenario quality is also assessed using energy scores '
    '(a multivariate proper scoring rule) and variograms (spatial-temporal '
    'dependency assessment), implemented in scoring.py.'
)

# ── 1.8 Configuration ──
doc.add_heading('1.8  Configuration and Hyperparameters', level=2)
add_table(
    ['Parameter', 'Typical Range', 'Effect'],
    [
        ['asset_rho', '0.02\u20130.10', 'Spatial regularization (higher = sparser graph, narrower correlations)'],
        ['horizon_rho', '0.05\u20130.10', 'Temporal regularization (higher = fewer hour-hour correlations)'],
        ['forecast_lead_time_in_hour', '10 (load), 12 (renew.)', 'Hours between issue time and scenario start'],
        ['nearest_days', '50\u2013100 or None', 'Seasonal training window; None = all historical data'],
        ['num_of_horizons', '24', 'Hours in scenario day (fixed at 24)'],
        ['nscen', '100\u20131000', 'Number of Monte Carlo scenarios to generate'],
    ]
)
doc.add_paragraph(
    'For wind, asset_rho is typically scaled by the inter-asset distance matrix '
    '(0.05 \u00d7 d_ij / d_max) to encode the prior that distant wind farms have '
    'weaker correlations. Solar uses a lower base penalty (0.02) because solar '
    'correlations are driven by cloud systems that can affect wider regions.'
)

doc.add_page_break()

# ══════════════════════════════════════════════════════════════════════
#  PART II: Vatic
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('Part II \u2013 Vatic: Power Grid Simulation Engine', level=1)

# ── 2.1 Overview ──
doc.add_heading('2.1  Overview and Purpose', level=2)
doc.add_paragraph(
    'Vatic is a Python package for power grid simulation that implements '
    'alternating day-ahead unit commitment (UC) and real-time '
    'security-constrained economic dispatch (SCED). It is a lightweight '
    'adaptation of Prescient (developed by Sandia National Laboratories) '
    'built on mixed-integer linear programming (MILP) optimization via Pyomo '
    'and power system formulations from the Egret library.'
)
doc.add_paragraph(
    'Vatic\'s role in the pipeline is to take the probabilistic scenarios '
    'generated by PGScen and simulate actual grid operations: which generators '
    'are turned on/off (commitment), how much power each produces (dispatch), '
    'and the resulting costs, reserves, and locational marginal prices (LMPs).'
)
doc.add_paragraph(
    'Vatic supports multiple grid datasets: RTS-GMLC (Reliability Test System), '
    'Texas-7k (7,000-bus Texas model for 2020 and 2030), and NYISO. The NYISO '
    'dataset is loaded through the NYISOLoader adapter described in Part III.'
)

# ── 2.2 UC and ED ──
doc.add_heading('2.2  Unit Commitment and Economic Dispatch', level=2)

doc.add_heading('2.2.1  Day-Ahead Unit Commitment (RUC)', level=3)
doc.add_paragraph(
    'The Reliability Unit Commitment (RUC) is a day-ahead planning problem '
    'that determines which generators should be committed (turned on) for the '
    'next operating day. It is typically solved once per day, at 16:00 the '
    'day before, with a 48-hour planning horizon.'
)
doc.add_paragraph('The RUC optimization minimizes total expected costs subject to:')
add_bullet('Power balance: total generation must meet forecasted demand at each bus')
add_bullet('Generator limits: each unit must operate between Pmin and Pmax when on')
add_bullet('Ramp rate constraints: power output cannot change faster than the '
           'unit\'s ramp rate (MW/hour)')
add_bullet('Minimum up/down time: once started, a generator must run for at '
           'least its minimum up time; once shut down, it must remain off for '
           'its minimum down time')
add_bullet('Startup costs: units incur cold/warm/hot startup costs depending on '
           'how long they have been offline')
add_bullet('Reserve requirements: a spinning reserve margin (typically 5% of demand) '
           'must be maintained')
add_bullet('Transmission constraints: power flows must not exceed line thermal limits '
           '(enforced via PTDF)')

doc.add_heading('2.2.2  Real-Time Economic Dispatch (SCED)', level=3)
doc.add_paragraph(
    'The Security-Constrained Economic Dispatch runs every hour (or sub-hourly) '
    'with a 4-hour look-ahead horizon. It takes the commitment decisions from '
    'the RUC as fixed and optimizes the dispatch (power output) of committed '
    'generators to meet actual (realized) demand at minimum cost.'
)
doc.add_paragraph(
    'The SCED uses actual renewable generation and load demand rather than '
    'forecasts. When actual conditions differ significantly from the day-ahead '
    'forecast (e.g., a wind ramp event), the SCED must re-optimize dispatch '
    'within the constraints set by the commitment decisions. If committed '
    'capacity is insufficient, load shedding occurs at a high penalty cost '
    '($10,000/MWh default).'
)

# ── 2.3 Architecture ──
doc.add_heading('2.3  Software Architecture', level=2)
add_table(
    ['Class', 'File', 'Lines', 'Purpose'],
    [
        ['Simulator', 'engines.py', '641', 'Main simulation engine orchestrating RUCs and SCEDs'],
        ['UCModel', 'models/_interface.py', '414', 'Pyomo model wrapper for UC formulations'],
        ['VaticModelData', 'model_data.py', '640', 'Grid state: buses, generators, branches, loads, storage'],
        ['VaticSimulationState', 'simulation_state.py', '377', 'Tracks commitments, initial conditions, forecasts/actuals'],
        ['PickleProvider', 'data_providers.py', '941', 'Loads datasets, generates RUC/SCED model instances'],
        ['VaticTimeManager', 'time_manager.py', '165', 'Manages simulation time steps and RUC scheduling'],
        ['VaticPTDFManager', 'ptdf_manager.py', '172', 'Lazy PTDF constraints for transmission security'],
        ['StatsManager', 'stats_manager.py', '726', 'Collects results and generates output files/plots'],
        ['GridLoader', 'data/loaders.py', '~500', 'Abstract base class; subclasses parse grid datasets'],
    ]
)

# ── 2.4 Optimization Formulations ──
doc.add_heading('2.4  Optimization Formulations', level=2)
doc.add_paragraph(
    'Vatic uses formulation "modules" from the Egret library, assembled into '
    'complete UC and SCED models. Each formulation module defines a set of '
    'variables, constraints, or objective terms.'
)

doc.add_heading('2.4.1  RUC Formulation Stack', level=3)
add_table(
    ['Module', 'Formulation', 'Description'],
    [
        ['Status variables', 'garver_3bin_vars', 'Three binary variables per unit-hour: on, startup, shutdown'],
        ['Power variables', 'garver_power_vars', 'Continuous power output bounded by commitment'],
        ['Reserve', 'garver_power_avail_vars', 'Spinning reserve availability'],
        ['Generation limits', 'pan_guan_gentile_KOW', 'Tight bounds on power output intervals'],
        ['Ramping', 'damcikurt_ramping', 'Ramp-up/down limits between hours'],
        ['Production costs', 'KOW_production_costs_tightened', 'Piecewise-linear cost curves'],
        ['Up/down time', 'rajan_takriti_UT_DT', 'Minimum up-time and down-time constraints'],
        ['Startup costs', 'KOW_startup_costs', 'Multi-stage (cold/warm/hot) startup costs'],
        ['Network', 'ptdf_power_flow', 'DC power flow via Power Transfer Distribution Factors'],
    ]
)

doc.add_heading('2.4.2  SCED Formulation Stack', level=3)
doc.add_paragraph(
    'The SCED uses simplified formulations for faster solving:'
)
add_bullet('MLR_reserve_vars: Simplified reserve model for real-time')
add_bullet('MLR_generation_limits: Simplified generation bounds')
add_bullet('CA_production_costs: Simplified cost model')
add_bullet('MLR_startup_costs: Simplified startup costs')
doc.add_paragraph(
    'The SCED retains the same network (ptdf_power_flow) and ramping '
    '(damcikurt_ramping) formulations as the RUC.'
)

doc.add_heading('2.4.3  Objective Function', level=3)
doc.add_paragraph('The total cost minimized by both RUC and SCED comprises:')
add_bullet('No-load costs: fixed cost of keeping a unit running at minimum output')
add_bullet('Production costs: piecewise-linear fuel cost as a function of MW output')
add_bullet('Startup costs: cold/warm/hot startup costs when committing a unit')
add_bullet('Shutdown costs: cost of de-committing a unit')
add_bullet('Load mismatch penalties: $10,000/MWh for unserved load (load shedding)')
add_bullet('Reserve shortfall penalties: $1,000/MWh for insufficient spinning reserve')
add_bullet('Transmission violation costs: penalties for line overloads')
add_bullet('Storage cycling costs: optional degradation cost for battery dispatch')

doc.add_heading('2.4.4  Lazy PTDF Management', level=3)
doc.add_paragraph(
    'Rather than enforcing all transmission constraints simultaneously (which '
    'would create thousands of constraints), Vatic uses a lazy constraint '
    'approach via VaticPTDFManager. At each SCED solve:'
)
add_bullet('The manager checks current power injections against all line limits')
add_bullet('Lines that are congested (flow > limit) are added as active constraints')
add_bullet('Lines that have been inactive for 5 consecutive cycles are removed')
add_bullet('This dramatically reduces problem size while ensuring feasibility')

# ── 2.5 Data Structures ──
doc.add_heading('2.5  Data Structures and Model Representation', level=2)
doc.add_paragraph(
    'Vatic represents the grid through VaticModelData, a nested dictionary '
    'structure compatible with Egret\'s model formulations. The top-level '
    'structure contains:'
)
add_bullet('system: global parameters (baseMVA, reserve requirements, penalty costs, time keys)', bold_prefix='')
add_bullet('elements/bus: bus names, base voltages, loads', bold_prefix='')
add_bullet('elements/generator: fuel type, Pmin/Pmax, ramp rates, cost curves, '
           'commitment states, initial conditions', bold_prefix='')
add_bullet('elements/branch: transmission lines with impedance and thermal limits', bold_prefix='')
add_bullet('elements/load: time-varying load at each bus', bold_prefix='')
add_bullet('elements/storage: battery parameters (capacity, charge/discharge rates, efficiency)', bold_prefix='')

# ── 2.6 Simulation Workflow ──
doc.add_heading('2.6  Simulation Workflow', level=2)
doc.add_paragraph('The Simulator.simulate() method executes the following loop:')
add_code_block(
    'def simulate(self):\n'
    '    # 1. INITIALIZATION: Solve RUC for the first operating day\n'
    '    self.initialize_oracle()\n'
    '\n'
    '    # 2. MAIN LOOP: iterate through all time steps\n'
    '    for time_step in self._time_manager.time_steps():\n'
    '\n'
    '        # 2a. PLANNING: solve day-ahead RUC (once per day at 16:00)\n'
    '        if time_step.is_planning_time:\n'
    '            self.call_planning_oracle()  # 48-hour RUC\n'
    '\n'
    '        # 2b. OPERATION: solve real-time SCED (every hour)\n'
    '        self.call_oracle()  # 4-hour SCED\n'
    '\n'
    '        # 2c. UPDATE: advance state with SCED results\n'
    '        self._simulation_state.apply_sced(current_sced)\n'
    '\n'
    '    # 3. OUTPUT: save results\n'
    '    return self._stats_manager.save_output(sim_time)'
)
doc.add_paragraph(
    'A typical 1-day simulation solves 1 RUC (the most expensive problem, '
    'taking ~10\u201360 seconds) and 24 SCEDs (each taking ~1\u20135 seconds), '
    'for a total wall-clock time of approximately 45\u201390 seconds per '
    'simulation day on the Kron-reduced NYISO network.'
)

# ── 2.7 Output ──
doc.add_heading('2.7  Output and Results', level=2)
doc.add_paragraph('Vatic produces structured output at three detail levels:')
add_table(
    ['Detail Level', 'Contents'],
    [
        ['0 (minimal)', 'Hourly system-wide: total load, generation, costs, reserves'],
        ['1 (default)', 'Level 0 + per-generator: dispatch (MW), headroom, on/off status'],
        ['2 (full)', 'Level 1 + per-bus load mismatches, per-line congestion, '
         'interface flows'],
    ]
)
doc.add_paragraph(
    'When LMP calculation is enabled (--lmps flag), Vatic re-solves each SCED '
    'with relaxed binary variables to compute locational marginal prices at '
    'each bus. LMPs decompose into energy, congestion, and loss components.'
)

# ── 2.8 Grid Datasets ──
doc.add_heading('2.8  Supported Grid Datasets', level=2)
add_table(
    ['Dataset', 'Buses', 'Generators', 'Branches', 'Source'],
    [
        ['RTS-GMLC', '73', '158', '120', 'Reliability Test System (IEEE/NREL)'],
        ['Texas-7k (2020)', '~7,000', '~4,000', '~8,800', 'Texas Interconnection model'],
        ['Texas-7k (2030)', '~7,000', '~5,000', '~8,800', 'Texas 2030 with 50% renewables'],
        ['NYISO', '46 (reduced)', '~243', '~226', 'Cornell NYgrid via NYISOLoader'],
    ]
)

doc.add_page_break()

# ══════════════════════════════════════════════════════════════════════
#  PART III: NYISOLoader
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('Part III \u2013 NYISOLoader: Grid Model Adapter', level=1)

# ── 3.1 Overview ──
doc.add_heading('3.1  Overview and Design Rationale', level=2)
doc.add_paragraph(
    'NYISOLoader is a GridLoader subclass that transforms the Cornell NYgrid '
    'NPCC-140 baseline model \u2014 a detailed 140-bus MATPOWER representation '
    'of the New York ISO power system \u2014 into Vatic\'s standardized template '
    'format for power grid simulation and optimization.'
)
doc.add_paragraph(
    'The design follows two software patterns. The Template Method pattern: '
    'GridLoader defines abstract methods that NYISOLoader implements '
    'differently from RtsLoader or T7kLoader. The Adapter pattern: NYISOLoader '
    'transforms NYgrid\'s JSON format into Vatic\'s expected dictionary structure, '
    'handling format mismatches in cost curves, generator types, and network topology.'
)
doc.add_paragraph(
    'NYISOLoader is the critical bridge between PGScen\'s probabilistic '
    'scenarios and Vatic\'s deterministic grid simulation. It maps abstract '
    'scenario data (MW by site or zone) to concrete grid elements (generators '
    'at specific buses with specific operating constraints).'
)

# ── 3.2 NYgrid Baseline ──
doc.add_heading('3.2  The NYgrid Baseline (NPCC-140)', level=2)
doc.add_paragraph(
    'The NYgrid baseline model, developed by Liu et al. (2023) at Cornell '
    'University, provides a detailed representation of the New York power '
    'system within the larger NPCC (Northeast Power Coordinating Council) '
    'interconnection.'
)
add_table(
    ['Component', 'Count', 'Details'],
    [
        ['Buses', '140 total (46 in NY)', '11 NYISO zones (A\u2013K), rest external (PJM, NE, HQ, IESO)'],
        ['Thermal generators', '227', '~27,064 MW: natural gas, oil, coal'],
        ['Nuclear generators', '6', '~5,430 MW: Indian Point (retired 2021), Nine Mile Point, etc.'],
        ['Dispatchable hydro', '2 major', 'Niagara (2,460 MW), St. Lawrence (856 MW)'],
        ['Run-of-river hydro', '7\u201310', '~879 MW at ~50% capacity factor'],
        ['Transmission lines', '226', 'Including 7 major NYISO interfaces'],
        ['External equivalents', '4', 'PJM, Hydro-Qu\u00e9bec, New England, IESO imports'],
    ]
)
doc.add_paragraph(
    'The baseline JSON file (nygrid_baseline.json) is stored in the third_party/NYgrid/ '
    'directory and includes bus data (ID, name, zone, load, voltage, coordinates), '
    'generator data (name, bus, fuel, capacity, cost curves, UC parameters), and '
    'branch data (from/to buses, impedance, thermal limits).'
)

doc.add_heading('3.2.1  Kron Reduction', level=3)
doc.add_paragraph(
    'For PTDF-based transmission modeling, NYISOLoader supports Kron reduction, '
    'which eliminates the 94 external buses and reduces the network to 46 NY-only '
    'buses. This dramatically improves solver performance while preserving the '
    'electrical equivalence through modified branch impedances and limits. '
    'Interface flow limits are empirically scaled by 2\u00d7 to account for the '
    'approximation introduced by the reduction.'
)

# ── 3.3 Data Mapping ──
doc.add_heading('3.3  Data Mapping: NYgrid to Vatic', level=2)
doc.add_paragraph(
    'NYISOLoader performs extensive data transformation to populate Vatic\'s '
    'template dictionary. The major mapping tasks are described below.'
)

doc.add_heading('3.3.1  Bus Mapping', level=3)
doc.add_paragraph(
    'NYgrid buses are filtered to the 46 New York buses (IDs 37\u201382) and '
    'mapped to Vatic bus names. Each bus is assigned to one of the 11 NYISO '
    'zones (A\u2013K) using the zone lookup table:'
)
add_code_block(
    'WEST \u2192 A,  GENESE \u2192 B,  CENTRL \u2192 C,  NORTH \u2192 D,\n'
    'MHK VL \u2192 E, CAPITL \u2192 F,  HUD VL \u2192 G,  MILLWD \u2192 H,\n'
    'DUNWOD \u2192 I, N.Y.C. \u2192 J,  LONGIL \u2192 K'
)

doc.add_heading('3.3.2  Fuel Type Mapping', level=3)
add_table(
    ['NYgrid Fuel', 'Vatic Code', 'Generator Type'],
    [
        ['Natural Gas', 'NG', 'G (Gas)'],
        ['Fuel Oil 2 / Fuel Oil 6', 'Oil', 'O (Oil)'],
        ['Coal', 'Coal', 'C (Coal)'],
        ['Nuclear', 'Nuclear', 'N (Nuclear)'],
        ['Wind', 'Wind', 'W (Wind)'],
        ['Solar', 'Solar', 'S (Solar)'],
        ['Hydro', 'Hydro', 'H (Hydro)'],
    ]
)

# ── 3.4 Generator Modeling ──
doc.add_heading('3.4  Generator Modeling', level=2)

doc.add_heading('3.4.1  Cost Curve Transformation', level=3)
doc.add_paragraph(
    'NYgrid provides cost data as linear (or optional quadratic) heat rate '
    'models in MMBTU/h. Vatic requires piecewise-linear cost curves in $/h. '
    'NYISOLoader performs the conversion:'
)
add_code_block(
    'NYgrid:   total_heat(P) = slope \u00d7 P + intercept     [MMBTU/h]\n'
    'Convert:  total_cost(P) = total_heat(P) \u00d7 fuel_price  [$/h]\n'
    'Vatic:    piecewise_linear[(P1, $1), (P2, $2), ...]'
)
doc.add_paragraph(
    'Fuel prices are zone-specific (e.g., natural gas at $3.63/MMBTU in '
    'western NY vs. $4.40/MMBTU in the Hudson Valley). The loader can use '
    'either 2019 annual averages or weekly prices from EIA data.'
)

doc.add_heading('3.4.2  Unit Commitment Parameters', level=3)
doc.add_paragraph(
    'Startup constraints and minimum up/down times are assigned by '
    '(unit_type, fuel_type) lookup. Example entries:'
)
add_table(
    ['Unit Type', 'Fuel', 'Min Up (h)', 'Min Down (h)', 'Cold Start (h)', 'Cold Cost ($/MMBTU)'],
    [
        ['Steam Turbine', 'Natural Gas', '8', '8', '48', '110'],
        ['Combined Cycle', 'Natural Gas', '4', '4', '12', '70'],
        ['Combustion Turbine', 'Natural Gas', '1', '1', '2', '20'],
        ['Steam Turbine', 'Coal', '24', '24', '168', '150'],
        ['Nuclear', 'Nuclear', '72', '72', '168', 'Must-run'],
    ]
)
doc.add_paragraph(
    'Three-stage startup is modeled: hot (short offline), warm (medium), and '
    'cold (long offline), each with increasing startup costs. Startup cost is '
    'computed as: cost_per_MMBTU \u00d7 Pmax \u00d7 heat_rate_slope.'
)

doc.add_heading('3.4.3  Dispatchable Hydro', level=3)
doc.add_paragraph(
    'Two major hydroelectric facilities receive special treatment:'
)
add_bullet('Niagara (2,460 MW, Zone A): Treaty-controlled with Pmin = 1,560 MW '
           '(~63.5% capacity factor, reflecting US\u2013Canada treaty flow obligations) '
           'and Pmax = 2,460 MW. Modeled as must-run.')
add_bullet('St. Lawrence (856 MW, Zone D): Pmin = 700 MW, Pmax = 856 MW. '
           'Also must-run due to international treaty obligations.')
doc.add_paragraph(
    'These are modeled as dispatchable generators (not renewable) because '
    'their output can be adjusted within the treaty bounds by the system operator.'
)

doc.add_heading('3.4.4  Pumped Storage', level=3)
add_table(
    ['Facility', 'Capacity (MW)', 'Energy (MWh)', 'Bus', 'Zone', 'Charge Eff.', 'Discharge Eff.'],
    [
        ['Blenheim-Gilboa', '1,160', '9,280', '38', 'E', '87%', '92%'],
        ['Lewiston', '240', '2,880', '55', 'A', '85%', '90%'],
    ]
)
doc.add_paragraph(
    'Pumped storage is modeled through Egret\'s storage dictionary, separate '
    'from generators. Each unit has charge/discharge rates, energy capacity, '
    'round-trip efficiency, and initial state of charge (default 50%).'
)

doc.add_heading('3.4.5  External Equivalents', level=3)
doc.add_paragraph(
    'Rather than modeling the full external networks (PJM, Hydro-Qu\u00e9bec, '
    'New England, IESO), NYISOLoader represents them as equivalent generators '
    'at border buses:'
)
add_table(
    ['Interconnection', 'Bus', 'Pmax (MW)', 'Cost ($/MWh)', 'Zone'],
    [
        ['PJM', 'RAMAPO (75)', '2,650', '30', 'G'],
        ['Hydro-Qu\u00e9bec', 'Chateauguay (48)', '1,690', '5', 'D'],
        ['New England', 'Cross Sound (37)', '300', '35', 'F'],
        ['IESO (Ontario)', 'Niagara (54)', '1,290', '15', 'A'],
    ]
)
doc.add_paragraph(
    'Pmax values are set at the 95th percentile of 2019 actual flows. '
    'Costs approximate the average LMP of the neighboring region. '
    'These equivalents are one-directional (imports only in the base model); '
    'export capability can be added by setting negative Pmin.'
)

# ── 3.5 Transmission ──
doc.add_heading('3.5  Transmission and Interfaces', level=2)
doc.add_paragraph(
    'NYISOLoader models 226 transmission lines with thermal limits and '
    'impedances from the NYgrid baseline. Seven major NYISO interface '
    'constraints are enforced:'
)
add_table(
    ['Interface', 'Limit (MW)', 'Direction'],
    [
        ['DYSINGER EAST', '6,300', 'West \u2192 East (Zone A\u2192B)'],
        ['WEST CENTRAL', '4,400', 'Zone B \u2192 C'],
        ['TOTAL EAST', '5,150', 'Upstate \u2192 Downstate'],
        ['MOSES SOUTH', '2,350', 'Zone D \u2192 south'],
        ['CENTRAL EAST', '3,225', 'Zone C \u2192 E/F'],
        ['UPNY-SENY', '5,400', 'Upstate NY \u2192 Southeast NY'],
        ['UPNY-ConEd', '5,750', 'Upstate \u2192 ConEd territory'],
    ]
)
doc.add_paragraph(
    'Interface constraints are defined as linear combinations of branch flows '
    'with specified orientations. When using the Kron-reduced network, interface '
    'limits are scaled by 2\u00d7 to compensate for the reduced network\'s modified '
    'impedance structure.'
)

# ── 3.6 Timeseries Integration ──
doc.add_heading('3.6  Timeseries Integration', level=2)
doc.add_paragraph(
    'NYISOLoader\'s create_timeseries() method builds the (gen_data, load_data) '
    'DataFrames required by Vatic. It supports two data paths:'
)

doc.add_heading('3.6.1  PGScen Path (Preferred)', level=3)
doc.add_paragraph(
    'When pgscen_dir is specified, the loader reads PGScen-generated CSV files:'
)
add_bullet('Wind: Maps per-site MW values to NYISO_W_{site_id} generators')
add_bullet('Solar: Maps per-site MW values to NYISO_S_{site_id} generators')
add_bullet('Load: Distributes zonal load to buses using load proportion factors '
           'from the NYgrid baseline\'s bus-level load data')
doc.add_paragraph(
    'Each column in the output DataFrame has both actual and forecast sub-columns, '
    'corresponding to real-time operations and day-ahead planning respectively.'
)

doc.add_heading('3.6.2  NYISO Public Data Path (Fallback)', level=3)
doc.add_paragraph(
    'When PGScen data is unavailable, the loader falls back to NYISO public data:'
)
add_bullet('Load: Downloads from mis.nyiso.com "pal" dataset (5-minute resolution, '
           'aggregated to hourly)')
add_bullet('Wind: System-wide wind from "rtfuelmix" dataset, distributed to '
           'individual generators using RenewableGen.csv capacity fractions')
add_bullet('Solar: Similar distribution from fuel mix data')
doc.add_paragraph(
    'The public data path provides less granularity (system-level wind rather '
    'than per-plant) and no forecast error modeling, making it suitable for '
    'deterministic simulations but not for stochastic analysis.'
)

# ── 3.7 Fleet Updates ──
doc.add_heading('3.7  Fleet Updates Across Years', level=2)
doc.add_paragraph(
    'The FleetUpdater class (nyiso_fleet_updater.py, 668 lines) enables '
    'updating the generator fleet for any target year. It processes:'
)
add_bullet('Retirements: Removes generators that have been decommissioned '
           '(e.g., Indian Point Units 2 and 3 in 2020\u20132021)')
add_bullet('Additions: Adds new generators from the NYISO interconnection queue, '
           'NYSERDA pipeline, and Gold Book forecasts')
add_bullet('Capacity updates: Adjusts nameplate capacity for re-rated units')
add_bullet('Battery storage: Adds grid-scale batteries from Gold Book and '
           'interconnection queue data')
doc.add_paragraph(
    'The updater produces year-specific baseline JSON files '
    '(e.g., nygrid_baseline_2023.json) that NYISOLoader can load directly. '
    'Gold Book fuel codes are mapped to NYgrid names: NG\u2192Natural Gas, '
    'UR\u2192Nuclear, WAT\u2192Hydro, WND\u2192Wind, SUN\u2192Solar, BAT\u2192Battery.'
)

# ── 3.8 Supporting Modules ──
doc.add_heading('3.8  Supporting Modules', level=2)
add_table(
    ['Module', 'Lines', 'Purpose'],
    [
        ['nygrid_reader.py', '141', 'Parses NYgrid JSON baseline and validates structure'],
        ['nyiso_downloader.py', '944', 'Downloads NYISO public data (zonal load, LMPs, fuel mix) with caching'],
        ['nyiso_timeseries.py', '391', 'Builds timeseries from cached NYISO data or PGScen output'],
        ['nyiso_fleet_updater.py', '668', 'Updates generator fleet for target year using Gold Book data'],
        ['nyiso_endpoints.yaml', '\u2014', 'URL configuration for NYISO API endpoints'],
    ]
)

doc.add_page_break()

# ══════════════════════════════════════════════════════════════════════
#  PART IV: System Integration
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('Part IV \u2013 System Integration', level=1)

# ── 4.1 Pipeline Overview ──
doc.add_heading('4.1  End-to-End Pipeline Overview', level=2)
doc.add_paragraph(
    'The three components form a layered pipeline for stochastic power grid '
    'simulation of the New York ISO system:'
)
add_table(
    ['Layer', 'Component', 'Role', 'Input', 'Output'],
    [
        ['1. Scenario Generation', 'PGScen', 'Generate probabilistic wind/solar/load scenarios',
         'Historical NYISO data + HRRR forecasts', '100\u20131000 correlated scenarios per day'],
        ['2. Grid Model', 'NYISOLoader', 'Build power grid model with scenario timeseries',
         'NYgrid baseline + PGScen scenarios', 'Vatic template + (gen_data, load_data)'],
        ['3. Simulation', 'Vatic', 'Run unit commitment and economic dispatch',
         'Vatic template + timeseries', 'Costs, dispatch, LMPs, reserves'],
    ]
)
doc.add_paragraph(
    'This architecture is modular: each layer can be used independently or '
    'replaced. For example, PGScen scenarios could feed a different simulation '
    'engine, or Vatic could use a different scenario generator.'
)

# ── 4.2 Data Flow ──
doc.add_heading('4.2  Data Flow Architecture', level=2)
doc.add_paragraph(
    'Data flows through the pipeline via standardized file formats:'
)

doc.add_heading('4.2.1  PGScen \u2192 NYISOLoader', level=3)
doc.add_paragraph(
    'PGScen produces CSV files with UTC-indexed, multi-column DataFrames. '
    'The file naming convention is:'
)
add_code_block(
    'pgscen_dir/\n'
    '  wind/\n'
    '    wind_actual_1h_site_YYYY_utc.csv       # Actuals\n'
    '    wind_day_ahead_forecast_site_YYYY_utc.csv  # Forecasts\n'
    '    wind_meta.csv                           # Site metadata\n'
    '  solar/\n'
    '    solar_actual_1h_site_YYYY_utc.csv\n'
    '    solar_day_ahead_forecast_site_YYYY_utc.csv\n'
    '    solar_meta.csv\n'
    '  load/\n'
    '    load_actual_1h_zone_YYYY_utc.csv\n'
    '    load_day_ahead_forecast_zone_YYYY_utc.csv'
)
doc.add_paragraph(
    'NYISOLoader reads these files in create_timeseries() and maps them to '
    'grid-specific generator and bus identifiers.'
)

doc.add_heading('4.2.2  NYISOLoader \u2192 Vatic', level=3)
doc.add_paragraph(
    'NYISOLoader provides Vatic with two objects:'
)
add_bullet('template (dict): Static grid data \u2014 all generators, buses, branches, '
           'cost curves, constraints, and operating limits', bold_prefix='')
add_bullet('(gen_data, load_data) (DataFrames): Time-varying data \u2014 renewable '
           'generation and load demand with actual and forecast columns', bold_prefix='')
doc.add_paragraph(
    'The template is created once per grid configuration. The timeseries data '
    'is created per simulation period and can be overridden with PGScen '
    'scenario data for stochastic analysis.'
)

doc.add_heading('4.2.3  Experiment-Level Scenario Override', level=3)
doc.add_paragraph(
    'For stochastic ensemble simulations, the experiment orchestration script '
    'applies PGScen scenarios on top of the base timeseries. For each scenario:'
)
add_bullet('Wind: Per-site direct mapping via site_id \u2192 NYISO_W_{site_id}')
add_bullet('Solar: System-level ratio scaling (limited generators in NYISOLoader)')
add_bullet('Load: Per-zone scaling using zonal baseline load proportions')

# ── 4.3 Experiment Orchestration ──
doc.add_heading('4.3  Experiment Orchestration', level=2)
doc.add_paragraph(
    'The experiments/ directory contains structured experiment scripts that '
    'orchestrate the full pipeline. A typical experiment (e.g., '
    '001_stochastic_vs_deterministic_jul2019) follows three phases:'
)

doc.add_heading('4.3.1  Phase 1: Scenario Generation', level=3)
add_code_block(
    '# Load historical data\n'
    'load_act, load_fc = load_ny_load_data()\n'
    'wind_act, wind_fc, wind_meta = load_ny_real_wind_data(years=[2019])\n'
    'solar_act, solar_fc, solar_meta = load_ny_solar_data()\n'
    '\n'
    '# Generate scenarios for each day\n'
    'for day_date in dates:\n'
    '    wind_engine = GeminiEngine(..., forecast_lead_time_in_hour=18)\n'
    '    wind_engine.fit(asset_rho * dist/dist.max(), time_rho)\n'
    '    wind_engine.create_scenario(n_scenarios, wind_fc_future)\n'
    '    \n'
    '    load_engine = GeminiEngine(..., asset_type="load")\n'
    '    load_engine.fit(asset_rho, time_rho)\n'
    '    load_engine.create_scenario(n_scenarios, load_fc_future)\n'
    '    \n'
    '    solar_engine = PCAGeminiEngine(..., us_state="New York")\n'
    '    solar_engine.fit(asset_rho, pca_comp_rho, num_of_components=0.9)\n'
    '    solar_engine.create_scenario(n_scenarios, solar_fc_future)\n'
    '\n'
    '# Output: 100 parquet files (one per scenario)'
)

doc.add_heading('4.3.2  Phase 2: Deterministic Baseline', level=3)
add_code_block(
    '# Load grid model with PGScen timeseries\n'
    'loader = NyisoLoader(\n'
    '    use_reduced_network=True,\n'
    '    fuel_price_date="2019-07-15",\n'
    '    pgscen_dir="../../PGscen-2nd/data/NYISO_real",\n'
    '    year=2019\n'
    ')\n'
    'gen_data, load_data = loader.create_timeseries(start, end)\n'
    '\n'
    '# Run deterministic simulation using day-ahead forecast\n'
    'sim = Simulator(template, gen_data, load_data, solver="gurobi")\n'
    'results_det = sim.simulate()'
)

doc.add_heading('4.3.3  Phase 3: Stochastic Ensemble', level=3)
add_code_block(
    '# For each scenario (parallel across cores):\n'
    'for scen_idx in range(100):\n'
    '    scen_df = pd.read_parquet(f"scenario_{scen_idx:03d}.parquet")\n'
    '    \n'
    '    # Override timeseries with scenario values\n'
    '    gen_data_s, load_data_s = apply_scenario(\n'
    '        gen_data, load_data, scen_df, day_date, loader\n'
    '    )\n'
    '    \n'
    '    # Run simulation with scenario-specific timeseries\n'
    '    sim = Simulator(template, gen_data_s, load_data_s, solver="gurobi")\n'
    '    results[scen_idx] = sim.simulate()'
)
doc.add_paragraph(
    'This produces 100 simulation results per day, each representing a '
    'different realization of wind, solar, and load uncertainty. The ensemble '
    'can then be analyzed for expected costs, cost distributions, reliability '
    'metrics, and value of stochastic information.'
)

# ── 4.4 Stochastic vs Deterministic ──
doc.add_heading('4.4  Stochastic vs. Deterministic Analysis', level=2)
doc.add_paragraph(
    'The primary research question addressed by this pipeline is: what is '
    'the value of accounting for uncertainty in power system operations? '
    'The stochastic vs. deterministic comparison proceeds as follows:'
)
add_bullet('Deterministic baseline: Uses the day-ahead forecast as if it were '
           'certain. The RUC commits generators based on the single forecast, '
           'and the SCED dispatches against actual conditions. Mismatches between '
           'forecast and actual cause sub-optimal commitment decisions.')
add_bullet('Stochastic ensemble: Generates N scenarios (e.g., 100) that span '
           'the range of plausible outcomes. Each scenario represents a different '
           'realization of the joint wind/solar/load distribution. The RUC can '
           'be run with the mean or a robust commitment, while the SCED runs '
           'against each scenario\'s realization.')
doc.add_paragraph(
    'Key metrics for comparison include: total generation cost, load shedding '
    'events (frequency and magnitude), reserve shortfalls, and LMP distributions '
    'across zones. The difference in expected cost between deterministic and '
    'stochastic operations quantifies the "value of stochastic solution" (VSS).'
)

# ── 4.5 Validated Results ──
doc.add_heading('4.5  Validated Results', level=2)
doc.add_paragraph(
    'The pipeline has been validated against 2019 NYISO actual data for a '
    '24-hour RUC + hourly SCED simulation:'
)
add_table(
    ['Metric', 'Simulated', 'Actual 2019', 'Ratio'],
    [
        ['System LMP (July 8)', '$27.59/MWh', '$23.03/MWh', '1.20\u00d7'],
        ['Zone J (NYC) LMP', '$34.25/MWh', '$24.90/MWh', '1.38\u00d7'],
        ['Zone A (West) LMP', '$25.76/MWh', '$18.19/MWh', '1.42\u00d7'],
        ['Simulation time', '~45 seconds', '\u2014', '\u2014'],
    ]
)
doc.add_paragraph(
    'The 20\u201340% LMP overestimation is primarily attributed to: '
    '(1) the model imports from but does not export to neighboring regions, '
    'while actual NYISO exported ~656 MW on average to New England in 2019; '
    '(2) placeholder UC parameters that may commit more expensive units than '
    'necessary; and (3) the 2\u00d7 interface scaling that may over-constrain '
    'some transmission corridors.'
)

# ── 4.6 Limitations and Future Work ──
doc.add_heading('4.6  Known Limitations and Future Work', level=2)

doc.add_heading('4.6.1  PGScen Limitations', level=3)
add_bullet('Fleet-level correlations: The Kronecker structure underestimates '
           'cross-plant correlations, producing overly narrow fleet-level scenario fans')
add_bullet('HRRR model bias: Systematic wind speed and GHI biases are only '
           'partially corrected by MOS')
add_bullet('Generic power curves: All wind plants use the same IEC Class III curve; '
           'no plant-specific turbine data')
add_bullet('Fixed-tilt solar: No tracking or orientation diversity modeled')
add_bullet('Single grid point: Large wind farms don\'t use spatial averaging '
           'across multiple HRRR grid cells')

doc.add_heading('4.6.2  NYISOLoader Limitations', level=3)
add_bullet('UC parameters: Placeholder values from industry references, not '
           'validated against NYISO-specific unit data')
add_bullet('Hydro bounds: Static monthly averages; hourly variation from river '
           'flow data (USGS) not yet integrated')
add_bullet('Topology frozen at 2019: Missing major transmission upgrades '
           '(CHPE, Smart Path, Clean Path NY)')
add_bullet('No NE exports: Model only imports; actual net exports to NE '
           'average ~656 MW')

doc.add_heading('4.6.3  Vatic Limitations', level=3)
add_bullet('Deterministic solver: Vatic solves deterministic UC/ED; true '
           'stochastic programming (e.g., two-stage stochastic UC) is not '
           'implemented \u2014 each scenario runs independently')
add_bullet('No demand response: The model does not include demand-side flexibility')
add_bullet('No energy market coupling: LMPs are computed post-hoc, not '
           'co-optimized with commitment')

doc.add_heading('4.6.4  Integration Priorities', level=3)
add_table(
    ['Priority', 'Item', 'Impact', 'Estimated Effort'],
    [
        ['High', 'Validate UC parameters against EIA-860 Schedule 3', 'Reduce LMP overestimation', 'Medium'],
        ['High', 'Add NE export capability', 'Fix 656 MW import bias', 'Low'],
        ['Medium', 'Integrate USGS river flow for hourly hydro bounds', 'Improve dispatch realism', 'High'],
        ['Medium', 'Wire Blenheim-Gilboa storage into template', 'Add 1,160 MW flexibility', 'Low'],
        ['Medium', 'Improve fleet-level correlations in PGScen', 'Better tail risk capture', 'High'],
        ['Low', 'Add plant-specific wind turbine curves', 'Marginal accuracy gain', 'Medium'],
        ['Low', 'Update topology for 2025+ transmission', 'Required for forward studies', 'Medium'],
    ]
)

# ── Summary ──
doc.add_page_break()
doc.add_heading('Summary', level=1)
doc.add_paragraph(
    'This document has described the three-layer NYISO power grid simulation '
    'pipeline developed at Princeton University:'
)
doc.add_paragraph(
    'PGScen provides the probabilistic foundation by generating '
    'spatially and temporally correlated scenarios for wind, solar, and load '
    'using the GEMINI copula model. Its NYISO adaptation uses real NYISO load '
    'data and HRRR-derived meteorological data at actual plant locations, '
    'producing calibrated scenario ensembles that capture the statistical '
    'properties of forecast errors.'
)
doc.add_paragraph(
    'NYISOLoader bridges the gap between abstract scenario data and concrete '
    'grid simulation by transforming the Cornell NYgrid 140-bus baseline model '
    'into Vatic\'s format. It handles the intricate details of generator cost '
    'curves, unit commitment parameters, dispatchable hydro, pumped storage, '
    'external interconnections, and transmission interfaces.'
)
doc.add_paragraph(
    'Vatic provides the optimization engine, solving daily unit commitment '
    'and hourly economic dispatch problems using mixed-integer linear '
    'programming. It produces the final operational results: generator '
    'commitments, power dispatch, system costs, and locational marginal prices.'
)
doc.add_paragraph(
    'Together, these components enable a complete stochastic analysis workflow: '
    'generate hundreds of plausible futures, simulate grid operations under '
    'each, and analyze the distribution of outcomes. This capability is '
    'essential for understanding the operational impacts of renewable energy '
    'uncertainty on the New York power system and for quantifying the value '
    'of improved forecasting and stochastic optimization.'
)

# ── Save ──
out_path = os.path.join(os.path.dirname(__file__),
                        'NYISO_Pipeline_Technical_Documentation.docx')
doc.save(out_path)
print(f'Document saved to: {out_path}')
