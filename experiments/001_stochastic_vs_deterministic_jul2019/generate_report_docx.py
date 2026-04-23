#!/usr/bin/env python
"""Generate the Word document explaining Experiment 001."""

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from pathlib import Path
import datetime

doc = Document()

# ── Styles ──
style = doc.styles['Normal']
style.font.name = 'Calibri'
style.font.size = Pt(11)
style.paragraph_format.space_after = Pt(6)
style.paragraph_format.line_spacing = 1.15

for level in range(1, 4):
    hs = doc.styles[f'Heading {level}']
    hs.font.color.rgb = RGBColor(0x1B, 0x3A, 0x5C)

# ══════════════════════════════════════════════════════════════════════
# TITLE
# ══════════════════════════════════════════════════════════════════════
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('Stochastic vs. Deterministic Unit Commitment\non the NYISO Grid')
run.bold = True
run.font.size = Pt(22)
run.font.color.rgb = RGBColor(0x1B, 0x3A, 0x5C)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('Experiment 001 — Technical Report')
run.font.size = Pt(14)
run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run(f'Valentin Rudondy\nPrinceton University\n{datetime.date.today().strftime("%B %d, %Y")}')
run.font.size = Pt(11)
run.font.color.rgb = RGBColor(0x77, 0x77, 0x77)

doc.add_page_break()

# ══════════════════════════════════════════════════════════════════════
# TABLE OF CONTENTS (manual)
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('Table of Contents', level=1)
toc_items = [
    '1. Research Question',
    '2. Infrastructure Overview',
    '   2.1. PGscen-2nd — Scenario Generator',
    '   2.2. Vatic + NyisoLoader — Grid Simulator',
    '   2.3. How They Connect',
    '3. Data Sources',
    '   3.1. Wind Data (HRRR-Derived)',
    '   3.2. Solar Data',
    '   3.3. Load Data',
    '   3.4. Grid Topology (NYgrid)',
    '   3.5. Fuel Prices',
    '4. Experiment Design',
    '   4.1. Date Range and Warmup',
    '   4.2. Scenario Generation',
    '   4.3. Deterministic Baseline',
    '   4.4. Stochastic Ensemble',
    '5. Code Architecture',
    '   5.1. run.py — Main Runner',
    '   5.2. analyze.py — Results Processing',
    '   5.3. config.yaml — Experiment Parameters',
    '6. What the Code Produces',
    '   6.1. Scenario Files',
    '   6.2. Simulation Outputs',
    '   6.3. Figures',
    '   6.4. Summary Report',
    '7. Key Technical Decisions',
    '8. Smoke Test Results',
    '9. Expected Full-Run Results',
]
for item in toc_items:
    p = doc.add_paragraph(item)
    p.paragraph_format.space_after = Pt(2)
    if item.startswith('   '):
        p.paragraph_format.left_indent = Cm(1.5)

doc.add_page_break()

# ══════════════════════════════════════════════════════════════════════
# 1. RESEARCH QUESTION
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('1. Research Question', level=1)

doc.add_paragraph(
    'For a fixed summer peak week (July 15–21, 2019), how much does accounting '
    'for renewable and load uncertainty change expected production cost and '
    'commitment behavior compared to a deterministic run using NYISO\'s point '
    'forecast?'
)

doc.add_paragraph(
    'This is the simplest version of the "cost of uncertainty" question. '
    'We run 100 Monte Carlo scenarios of correlated wind, solar, and load '
    'through a full unit commitment / economic dispatch (UC/ED) simulation '
    'of the New York ISO grid and compare the distribution of outcomes '
    'against the single deterministic forecast. The gap between the '
    'deterministic cost and the expected stochastic cost measures '
    'the economic value of capturing uncertainty in operational planning.'
)

doc.add_paragraph(
    'This experiment is the first end-to-end integration of two systems built '
    'over the past months: PGscen-2nd (scenario generation) and Vatic with the '
    'NyisoLoader (grid simulation). Everything is wired; what has never been '
    'done is running scenarios through the simulation and analyzing the ensemble.'
)

# ══════════════════════════════════════════════════════════════════════
# 2. INFRASTRUCTURE OVERVIEW
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('2. Infrastructure Overview', level=1)

doc.add_heading('2.1. PGscen-2nd — Scenario Generator', level=2)

doc.add_paragraph(
    'PGscen-2nd is a Monte Carlo scenario generator following the GEMINI '
    '(GEneration of MultIvariate Non-parametric Interdependent) methodology '
    'from Carmona & Yang (IEEE 2021). It produces correlated day-ahead '
    'scenarios for wind, solar, and load simultaneously.'
)

doc.add_paragraph('How it works, step by step:')

items = [
    ('Historical deviations', 'For each day in the historical record, PGscen '
     'computes the difference between the actual value and the day-ahead '
     'forecast at each plant for each hour: deviation = actual − forecast.'),
    ('Gaussianization', 'The historical deviations are transformed to '
     'approximately Gaussian marginals using empirical CDFs (ECDF) or '
     'generalized Pareto distributions (GPD), then mapped through the '
     'inverse normal CDF.'),
    ('Regime identification', 'A Hidden Markov Model (HMM) with 3 regimes '
     'is fitted via the EM algorithm. Each regime captures a different '
     'weather pattern (e.g., high-wind vs. calm vs. transitional).'),
    ('Spatial–temporal covariance', 'Within each regime, a graphical LASSO '
     'estimates sparse precision matrices for both spatial (between-plant) '
     'and temporal (between-hour) correlations.'),
    ('Scenario sampling', 'New Gaussian deviations are drawn from the '
     'regime-weighted covariance structure, then reverse-transformed through '
     'the marginal distributions and added to the day-ahead forecast to '
     'produce scenario trajectories.'),
    ('Clipping', 'Wind/solar outputs are clipped to [0, nameplate capacity]. '
     'Load scenarios are clipped to non-negative values.'),
]
for title, text in items:
    p = doc.add_paragraph()
    run = p.add_run(f'{title}: ')
    run.bold = True
    p.add_run(text)

doc.add_paragraph(
    'Each call to PGscen generates scenarios for one day (24 hours). '
    'For a 7-day week, we call it 7 times independently — correlations '
    'between days are not modeled.'
)

doc.add_heading('2.2. Vatic + NyisoLoader — Grid Simulator', level=2)

doc.add_paragraph(
    'Vatic is a power grid simulation package that solves alternating '
    'unit commitment (UC) and economic dispatch (ED) problems using '
    'Pyomo and the Egret power systems library. It was originally built '
    'for PJM\'s RTS-GMLC test system and has been extended with a '
    'NyisoLoader for the NYISO grid.'
)

doc.add_paragraph('The NyisoLoader provides:')

bullets = [
    'A 46-bus Kron-reduced model of New York State derived from Cornell\'s '
    'NYgrid (originally 140-bus NPCC). External areas (PJM, Hydro-Québec, '
    'New England, IESO) are eliminated via Gaussian elimination on the '
    'admittance matrix, with equivalent import generators at boundary buses.',
    '235 thermal generators (227 fossil + 6 nuclear + 2 dispatchable hydro '
    'at Niagara and St. Lawrence) with class-based UC parameters (min up/down '
    'times, startup costs, ramp rates).',
    '31 wind generators and 16 solar generators registered from PGscen '
    'metadata, modeled as non-dispatchable resources.',
    '7 NYISO interface constraints (Dysinger East, West Central, Total East, '
    'Moses South, Central East, UPNY-ConEd, Sprainbrook/Dunwoodie-South) '
    'enforced via PTDF power flow.',
    '2 pumped storage units (Blenheim-Gilboa 1,160 MW + Lewiston 240 MW).',
    'Week-specific fuel prices from EIA data via a fuel_price_date parameter.',
]
for b in bullets:
    doc.add_paragraph(b, style='List Bullet')

doc.add_paragraph('The simulation loop for each day:')

steps = [
    'Day-ahead RUC (Reliability Unit Commitment): a 48-hour mixed-integer '
    'linear program (MILP) that decides which generators to commit (turn on/off) '
    'based on forecasted load and renewable output. Solved with the CBC solver.',
    'Hourly SCED (Security-Constrained Economic Dispatch): for each of the 24 '
    'hours, a linear program dispatches committed generators to meet actual '
    'demand at minimum cost, subject to network constraints.',
    'LMP calculation: after each SCED, the LP is re-solved with binary '
    'variables relaxed to extract dual variables, giving locational marginal '
    'prices at each bus.',
]
for i, s in enumerate(steps):
    doc.add_paragraph(f'{i+1}. {s}')

doc.add_heading('2.3. How They Connect', level=2)

doc.add_paragraph(
    'PGscen produces per-site scenario trajectories (MW per plant per hour). '
    'The experiment runner (run.py) maps these to NyisoLoader\'s gen_data '
    'DataFrame, which Vatic consumes:'
)

items = [
    ('Wind (23 HRRR sites)', 'Each PGscen wind site ID (e.g., wind_323596) '
     'maps 1:1 to a NyisoLoader generator (e.g., NYISO_W_wind_323596) via '
     'the loader\'s _pgscen_site_map. The scenario\'s per-site, per-hour MW '
     'value directly replaces the baseline forecast and actual in gen_data.'),
    ('Solar (system ratio)', 'PGscen\'s 314 synthetic solar sites are '
     'aggregated to a system-level ratio (scenario_total / forecast_total) '
     'per hour. This ratio scales the 2 NyisoLoader solar generators. '
     'Solar is only 4 MW total — negligible impact.'),
    ('Load (11 zones)', 'PGscen produces per-zone load scenarios (CAPITL, '
     'CENTRL, N.Y.C., etc.). The runner computes the ratio of scenario '
     'zonal load to baseline zonal load for each hour, then scales all '
     'buses in that zone proportionally.'),
]
for title, text in items:
    p = doc.add_paragraph()
    run = p.add_run(f'{title}: ')
    run.bold = True
    p.add_run(text)

# ══════════════════════════════════════════════════════════════════════
# 3. DATA SOURCES
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('3. Data Sources', level=1)

doc.add_heading('3.1. Wind Data (HRRR-Derived)', level=2)
doc.add_paragraph(
    'Wind actuals and day-ahead forecasts come from the HRRR (High-Resolution '
    'Rapid Refresh) reanalysis pipeline built in PGscen-2nd. Located at '
    'PGscen-2nd/data/NYISO_real/wind/.'
)

t = doc.add_table(rows=5, cols=2, style='Light Grid Accent 1')
t.alignment = WD_TABLE_ALIGNMENT.CENTER
data = [
    ('Files', 'wind_actual_1h_site_2019_utc.csv\nwind_day_ahead_forecast_site_2019_utc.csv'),
    ('Sites', '23 NYISO-registered wind plants (1,881 MW nameplate with data)'),
    ('Format', 'Hourly UTC timestamps × site columns (MW)'),
    ('History', '2019 (full year, 8,760 hours)'),
    ('Metadata', 'plant_metadata/wind_meta.csv (site_id, lat, lon, nameplate_mw)'),
]
for i, (k, v) in enumerate(data):
    t.rows[i].cells[0].text = k
    t.rows[i].cells[1].text = v

doc.add_heading('3.2. Solar Data', level=2)
doc.add_paragraph(
    'Solar data uses the standard PGscen dataset (not HRRR) because the '
    'NYISO_real solar data has only 2 sites in 2019 and the PCA engine '
    'needs more. Located at PGscen-2nd/data/NYISO/Solar/.'
)
doc.add_paragraph(
    '314 synthetic solar sites, but NyisoLoader only has 2 solar generators '
    '(56.5 MW nameplate). Solar contributes ~4 MW average output — negligible '
    'in a 24 GW system.'
)

doc.add_heading('3.3. Load Data', level=2)
doc.add_paragraph(
    'Zonal load actuals and day-ahead forecasts from the standard PGscen '
    'NYISO dataset. Located at PGscen-2nd/data/NYISO/Load/. '
    '11 NYISO zones (A through K), covering 2018–2019.'
)
doc.add_paragraph(
    'July 2019 peak week load ranges from ~18 GW overnight to ~29 GW '
    'during afternoon peaks. Day-ahead forecast error is typically 0.7–1.2% '
    'coefficient of variation.'
)

doc.add_heading('3.4. Grid Topology (NYgrid)', level=2)
doc.add_paragraph(
    'The grid model comes from Cornell\'s NYgrid project (Anderson Energy Lab). '
    'The original 140-bus NPCC model was Kron-reduced to 46 NY-only buses with '
    '74 branches. Generator data from NYgrid\'s genParamAll.csv (227 thermal '
    'generators with heat rate curves, ramp rates, and bus assignments). '
    'Serialized in third_party/NYgrid/nygrid_baseline.json and '
    'nygrid_kron_reduced.json.'
)

doc.add_heading('3.5. Fuel Prices', level=2)
doc.add_paragraph(
    'Week-specific fuel prices from EIA data (natural gas Henry Hub, '
    'No. 2 distillate, residual fuel oil) are applied to generator cost '
    'curves via the fuel_price_date parameter. For July 2019, natural gas '
    'was approximately $3.60–3.90/MMBTU.'
)

# ══════════════════════════════════════════════════════════════════════
# 4. EXPERIMENT DESIGN
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('4. Experiment Design', level=1)

doc.add_heading('4.1. Date Range and Warmup', level=2)

t = doc.add_table(rows=4, cols=2, style='Light Grid Accent 1')
t.alignment = WD_TABLE_ALIGNMENT.CENTER
data = [
    ('Warmup day', 'July 14, 2019 (excluded from analysis)'),
    ('Target week', 'July 15–21, 2019 (7 days)'),
    ('Year', '2019'),
    ('Purpose of warmup', 'Eliminates cold-start load shedding by providing '
     'realistic generator initial states for July 15'),
]
for i, (k, v) in enumerate(data):
    t.rows[i].cells[0].text = k
    t.rows[i].cells[1].text = v

doc.add_paragraph('')
doc.add_paragraph(
    'Without a warmup day, the first simulation day suffers from a "cold start": '
    'the solver has no prior commitment state, so slow-start generators (steam '
    'turbines with 8–12 hour minimum up times) are not online at midnight. '
    'This caused 14,807 MWh of load shedding in the original smoke test. '
    'With the warmup, load shedding drops to zero.'
)

doc.add_heading('4.2. Scenario Generation (Step 1)', level=2)
doc.add_paragraph(
    'For each of the 8 days (1 warmup + 7 target), PGscen generates 100 '
    'correlated scenarios of wind, solar, and load output. Each scenario is '
    'a complete 24-hour trajectory at hourly resolution for all plants/zones.'
)

doc.add_paragraph('Parameters:')
params = [
    ('Scenario count', '100'),
    ('Random seed', '42 (reproducible)'),
    ('Asset rho (spatial LASSO penalty)', '0.05'),
    ('Time rho (temporal LASSO penalty)', '0.05'),
    ('Solar PCA components', '0.9 (90% variance explained)'),
    ('Wind lead time', '18 hours (HRRR convention)'),
    ('Solar/load lead time', '12 hours (standard PGscen)'),
]
t = doc.add_table(rows=len(params), cols=2, style='Light Grid Accent 1')
t.alignment = WD_TABLE_ALIGNMENT.CENTER
for i, (k, v) in enumerate(params):
    t.rows[i].cells[0].text = k
    t.rows[i].cells[1].text = v

doc.add_paragraph('')
doc.add_paragraph(
    'Output: one Parquet file per scenario (scenario_000.parquet through '
    'scenario_099.parquet), each containing per-site wind values, per-zone '
    'load values, and system-level solar ratios for all 8 days.'
)

doc.add_heading('4.3. Deterministic Baseline (Step 2)', level=2)
doc.add_paragraph(
    'For each of the 8 days, Vatic runs a single simulation using the '
    'NyisoLoader\'s baseline timeseries (NYISO day-ahead forecast as both '
    'forecast and actual). Each day\'s final generator states are saved as '
    'a CSV file and passed to the next day as initial conditions, creating '
    'a chain: July 14 → July 15 → ... → July 21.'
)
doc.add_paragraph(
    'This produces the "what happens if the forecast is perfect" reference '
    'cost for each day.'
)

doc.add_heading('4.4. Stochastic Ensemble (Step 3)', level=2)
doc.add_paragraph(
    'For each of the 100 scenarios, for each of the 7 target days '
    '(excluding the warmup), Vatic runs a simulation with that scenario\'s '
    'wind/solar/load replacing the baseline forecast. Total: 700 simulations.'
)
doc.add_paragraph(
    'Each scenario uses the deterministic warmup day\'s conditions as '
    'initial state (all scenarios start from the same commitment state). '
    'Scenarios are independent and run in parallel using Python\'s '
    'multiprocessing.Pool with N−1 CPU cores.'
)

doc.add_paragraph('Solver settings:')
solver = [
    ('Solver', 'CBC (open-source MILP, via Homebrew)'),
    ('MIP gap', '1% (optimality tolerance)'),
    ('Timeout', '600 seconds per solve'),
    ('Reserve factor', '5% of forecasted load'),
    ('Load shedding penalty', '$10,000/MWh'),
    ('Reserve shortfall penalty', '$1,000/MWh'),
    ('RUC horizon', '48 hours'),
    ('SCED horizon', '4 hours'),
    ('Network model', 'PTDF power flow (DC approximation)'),
]
t = doc.add_table(rows=len(solver), cols=2, style='Light Grid Accent 1')
t.alignment = WD_TABLE_ALIGNMENT.CENTER
for i, (k, v) in enumerate(solver):
    t.rows[i].cells[0].text = k
    t.rows[i].cells[1].text = v

# ══════════════════════════════════════════════════════════════════════
# 5. CODE ARCHITECTURE
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('5. Code Architecture', level=1)

doc.add_paragraph(
    'All experiment code lives in experiments/001_stochastic_vs_deterministic_jul2019/. '
    'No Vatic or PGscen core code is modified.'
)

doc.add_heading('5.1. run.py — Main Runner', level=2)
doc.add_paragraph(
    'The main entry point. Orchestrates all three steps: scenario generation, '
    'deterministic baseline, and stochastic ensemble. Key functions:'
)
funcs = [
    ('generate_scenarios()', 'Calls PGscen engines for each day, saves '
     'per-scenario Parquet files.'),
    ('run_deterministic()', 'Runs Vatic day-by-day with warmup chaining.'),
    ('run_stochastic()', 'Distributes 700 simulation tasks across a '
     'multiprocessing pool.'),
    ('_apply_scenario_to_timeseries()', 'Maps PGscen output to Vatic\'s '
     'gen_data/load_data DataFrames — the core adapter layer.'),
    ('_build_loader_and_timeseries()', 'Creates NyisoLoader instance and '
     'baseline timeseries for a given day.'),
]
for name, desc in funcs:
    p = doc.add_paragraph()
    run = p.add_run(name + ' ')
    run.bold = True
    run.font.name = 'Consolas'
    run.font.size = Pt(10)
    p.add_run('— ' + desc)

doc.add_heading('5.2. analyze.py — Results Processing', level=2)
doc.add_paragraph(
    'Reads all simulation outputs and produces summary statistics, '
    'validation checks, and 5 publication-quality figures (300 dpi PNG). '
    'Outputs a Markdown summary report at results/summary_report.md.'
)

doc.add_heading('5.3. config.yaml — Experiment Parameters', level=2)
doc.add_paragraph(
    'All experiment parameters (dates, scenario count, solver options, '
    'file paths) in one YAML file. Nothing is hardcoded in the Python scripts.'
)

# ══════════════════════════════════════════════════════════════════════
# 6. WHAT THE CODE PRODUCES
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('6. What the Code Produces', level=1)

doc.add_heading('6.1. Scenario Files', level=2)
doc.add_paragraph(
    '100 Parquet files in results/scenarios/ (scenario_000.parquet through '
    'scenario_099.parquet). Each file contains a DataFrame indexed by '
    '(timestamp, asset_id) with columns asset_type and value_mw.'
)

doc.add_heading('6.2. Simulation Outputs', level=2)
doc.add_paragraph(
    'Each simulation (deterministic or stochastic) produces a Python pickle '
    'file containing a dictionary of DataFrames:'
)
outputs = [
    ('hourly_summary', 'Fixed costs, variable costs, load shedding, '
     'reserve shortfall, renewables used, demand, system price per hour.'),
    ('thermal_detail', 'Per-generator dispatch (MW), headroom (MW), '
     'unit state (on/off), and unit cost ($) for each hour.'),
    ('renew_detail', 'Per-renewable output (MW) and curtailment (MW).'),
    ('bus_detail', 'Per-bus demand (MW), mismatch (MW), and LMP ($/MWh).'),
    ('line_detail', 'Per-branch flow (MW).'),
    ('ruc_summary', 'Day-ahead commitment costs.'),
    ('daily_commits', 'Full 48-hour commitment schedule from the RUC.'),
]
for name, desc in outputs:
    p = doc.add_paragraph()
    run = p.add_run(name + ': ')
    run.bold = True
    run.font.name = 'Consolas'
    run.font.size = Pt(10)
    p.add_run(desc)

doc.add_heading('6.3. Figures', level=2)
figs = [
    ('cost_histogram.png', 'Distribution of total weekly production cost '
     'across 100 scenarios, with the deterministic cost marked.'),
    ('lmp_fan_chart.png', 'Hourly system LMP fan chart showing the 5th–95th '
     'percentile envelope across scenarios vs. the deterministic trace.'),
    ('commitment_heatmap.png', 'For each generator, the fraction of '
     'scenarios in which it is committed at each hour — highlights '
     'which units are on the margin.'),
    ('dispatch_percentiles.png', 'Total dispatch for the 5th, median, '
     'and 95th percentile cost scenarios.'),
    ('zonal_lmp_boxplot.png', 'LMP distribution by zone, showing the '
     'NYC (J) and Long Island (K) premium over upstate.'),
]
for name, desc in figs:
    p = doc.add_paragraph()
    run = p.add_run(name + ': ')
    run.bold = True
    run.font.name = 'Consolas'
    run.font.size = Pt(10)
    p.add_run(desc)

doc.add_heading('6.4. Summary Report', level=2)
doc.add_paragraph(
    'A Markdown file (results/summary_report.md) with all key metrics: '
    'production cost statistics, LMP statistics, load shedding events, '
    'reserve shortfall events, and validation checks.'
)

# ══════════════════════════════════════════════════════════════════════
# 7. KEY TECHNICAL DECISIONS
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('7. Key Technical Decisions', level=1)

decisions = [
    ('HRRR wind data instead of standard PGscen synthetic data',
     'The NYISO_real HRRR-derived data has 23 sites that map 1:1 to '
     'NyisoLoader\'s wind generators. This preserves per-site spatial '
     'correlation. The standard PGscen data has 80 synthetic sites with '
     'different names that cannot be mapped to NyisoLoader generators. '
     'Using HRRR data required fixing a timestamp convention mismatch '
     '(scen_start at 00:00 UTC with 18h lead time instead of 06:00 UTC '
     'with 12h lead time).'),
    ('Per-site wind mapping instead of system-level scalar ratio',
     'The original implementation collapsed all 80 PGscen wind sites into '
     'a single hourly scaling ratio applied uniformly to all generators. '
     'This destroyed all spatial correlation (correlation between scenarios '
     'was r=1.000). With per-site mapping, per-plant correlations are '
     'r=−0.35 to +0.40 — genuinely independent.'),
    ('1-day warmup to eliminate cold-start artifacts',
     'Without a prior day\'s commitment state, the initial RUC has no '
     'history of which generators were online. Steam units with 8–12 hour '
     'minimum up times are not committed at midnight, causing load shedding. '
     'Running July 14 as a warmup and passing its final generator states to '
     'July 15 eliminated 14,807 MWh of load shedding.'),
    ('CBC solver (open source) instead of Gurobi',
     'CBC is freely available and produces feasible solutions for this '
     'model size (~235 generators, 46 buses) in ~5–6 minutes per day. '
     'Gurobi would be faster but requires a commercial license.'),
    ('Solar system-level ratio is acceptable',
     'NyisoLoader only has 2 solar generators (56.5 MW nameplate, ~4 MW '
     'average output). At 0.02% of system capacity, per-site solar variance '
     'has no measurable impact on production cost.'),
]
for title, text in decisions:
    p = doc.add_paragraph()
    run = p.add_run(title + '. ')
    run.bold = True
    p.add_run(text)

# ══════════════════════════════════════════════════════════════════════
# 8. SMOKE TEST RESULTS
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('8. Smoke Test Results', level=1)

doc.add_paragraph(
    'Before launching the full 100-scenario run, a 5-scenario smoke test '
    'was run on July 17 (warmup) + July 18 (target).'
)

t = doc.add_table(rows=9, cols=2, style='Light Grid Accent 1')
t.alignment = WD_TABLE_ALIGNMENT.CENTER
smoke = [
    ('Scenarios completed', '5/5 (no failures)'),
    ('Deterministic cost (July 18)', '$8,210,029'),
    ('Stochastic mean', '$8,179,745'),
    ('Cost of uncertainty', '−$30,285 (−0.37%)'),
    ('Cost CV', '0.05%'),
    ('Load shedding (deterministic)', '0 MWh (warmup eliminated it)'),
    ('Average system LMP', '$15.20/MWh'),
    ('Per-plant wind correlation (scen 0 vs 1)', 'r = −0.35 to +0.40'),
    ('Wall time per day-solve', '~5–6 minutes (CBC)'),
]
for i, (k, v) in enumerate(smoke):
    t.rows[i].cells[0].text = k
    t.rows[i].cells[1].text = v

doc.add_paragraph('')
doc.add_paragraph(
    'The low cost CV (0.05%) is a genuine feature of NYISO 2019, not an '
    'artifact. Renewable penetration is only 0.3% (69 MW wind + 4 MW solar '
    'vs. 24 GW load), and the generators that toggle across scenarios are '
    'oil peakers at identical marginal costs ($247/MWh) — substituting one '
    'for another changes commitment but not cost.'
)

# ══════════════════════════════════════════════════════════════════════
# 9. EXPECTED FULL-RUN RESULTS
# ══════════════════════════════════════════════════════════════════════
doc.add_heading('9. Expected Full-Run Results', level=1)

doc.add_paragraph(
    'The full run (100 scenarios × 7 target days + 1 warmup) is estimated '
    'to take approximately 6 hours. Expected outputs:'
)

expected = [
    '100 scenario Parquet files (~1 MB each)',
    '8 deterministic simulation outputs + conditions files',
    '700 stochastic simulation outputs (100 scenarios × 7 days)',
    '5 publication-quality figures',
    'Summary report with cost-of-uncertainty statistics',
]
for e in expected:
    doc.add_paragraph(e, style='List Bullet')

doc.add_paragraph(
    'The cost-of-uncertainty is expected to remain small (< 1%) because '
    'NYISO 2019 has low renewable penetration. However, the ensemble will '
    'capture more tail events over 7 days and 100 scenarios, which may '
    'reveal higher-impact hours (e.g., coincident high load + low wind). '
    'The commitment heatmap and zonal LMP analysis will be the most '
    'informative outputs — they show which generators and transmission '
    'corridors are sensitive to uncertainty.'
)

doc.add_paragraph(
    'This experiment establishes the baseline methodology. Future runs '
    'with higher-penetration years (as NYISO adds offshore wind and solar) '
    'are expected to show significantly larger cost-of-uncertainty effects.'
)

# ── Save ──
out_path = Path('/Users/val/Desktop/Princeton/experiments/'
                '001_stochastic_vs_deterministic_jul2019/'
                'Experiment_001_Technical_Report.docx')
doc.save(str(out_path))
print(f'Saved: {out_path}')
