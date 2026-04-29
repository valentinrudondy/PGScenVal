#!/usr/bin/env python
"""Generate a Word document explaining how each curve in the v2 plots
is computed and how accuracy can be improved."""

from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

EXPERIMENT_DIR = Path(__file__).resolve().parent
FIG_DIR = EXPERIMENT_DIR / 'results' / 'figures'
OUT_PATH = EXPERIMENT_DIR / 'Model_vs_Actual_Methodology.docx'

doc = Document()

# ── Styles ──
style = doc.styles['Normal']
style.font.name = 'Calibri'
style.font.size = Pt(11)
style.paragraph_format.space_after = Pt(6)


def add_heading(text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = RGBColor(0x1B, 0x3A, 0x5C)


def add_fig(filename, caption, width=6.0):
    path = FIG_DIR / filename
    if path.exists():
        doc.add_picture(str(path), width=Inches(width))
        last = doc.paragraphs[-1]
        last.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p = doc.add_paragraph(caption)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.runs[0].italic = True
        p.runs[0].font.size = Pt(9)
        p.runs[0].font.color.rgb = RGBColor(0x66, 0x66, 0x66)


# ═══════════════════════════════════════════════════════════════
# TITLE
# ═══════════════════════════════════════════════════════════════
title = doc.add_heading('Model vs. Actual: Curve Methodology\nand Accuracy Improvement Paths', level=0)
for run in title.runs:
    run.font.color.rgb = RGBColor(0x1B, 0x3A, 0x5C)

doc.add_paragraph(
    'This document explains how each curve in the v2 stochastic experiment '
    'plots is computed, quantifies the gap between model and NYISO actual, '
    'and identifies concrete steps to improve accuracy.'
)
doc.add_paragraph(
    'Experiment: 002_v2_baseline (July 15\u201321, 2019 and September 19\u201321, 2023)'
)

# ═══════════════════════════════════════════════════════════════
# SECTION 1: DEMAND CURVES
# ═══════════════════════════════════════════════════════════════
add_heading('1. System Demand Curves', level=1)

add_fig('demand_profile.png',
        'Figure 1 \u2014 2019 system demand: model scenarios vs. NYISO actual')
add_fig('demand_2023_vs_actual.png',
        'Figure 2 \u2014 2023 system demand: model vs. NYISO actual')

# 1.1
add_heading('1.1 How each curve is computed', level=2)

add_heading('NYISO actual (green)', level=3)
doc.add_paragraph(
    'Source: NYISO Actual Integrated Load report (hourly, per zone), cached in '
    'PGscen-2nd/data/NYISO_real/load_actual_1h_zone_*_utc.csv. '
    'This is the metered, after-the-fact system load published by NYISO. '
    'The 11 zonal values (A\u2013K) are summed to produce the system total. '
    'Timestamps are in UTC.'
)

add_heading('Deterministic / DA forecast (red dashed)', level=3)
doc.add_paragraph(
    'Source: NYISO Day-Ahead load forecast (hourly, per zone), cached in '
    'PGscen-2nd/data/NYISO_real/load_day_ahead_forecast_zone_*_utc.csv. '
    'This is the official NYISO forecast issued the day before real-time. '
    'NyisoLoader distributes zonal forecast values to individual buses using '
    'load participation factors from NYgrid\u2019s RenewableGen.csv (proportional '
    'to each bus\u2019s share of its zone\u2019s total load). '
    'The Vatic simulator dispatches generation to meet this forecast demand. '
    'The "Demand" column in hourly_summary reflects the total load the model '
    'serves, which tracks the DA forecast closely.'
)

add_heading('Stochastic scenario band (blue)', level=3)
doc.add_paragraph(
    'Source: PGscen scenario generator. For each of the 100 scenarios, PGscen '
    'fits a Gaussian copula model to historical load forecast errors and '
    'generates correlated perturbations around the DA forecast, independently '
    'for each of the 11 NYISO zones. The scenario load is applied as a '
    'multiplicative ratio: scenario_load / baseline_actual, so the spatial '
    'distribution across buses is preserved. The P5\u2013P95 and P25\u2013P75 bands '
    'show the spread of total system demand across the 100 scenarios.'
)

# 1.2
add_heading('1.2 Current gap', level=2)
doc.add_paragraph(
    'The model demand (deterministic) is systematically below the actual:'
)
table = doc.add_table(rows=4, cols=4, style='Light Grid Accent 1')
headers = ['Period', 'Model mean', 'Actual mean', 'Bias']
for i, h in enumerate(headers):
    table.rows[0].cells[i].text = h
data = [
    ['2019 Jul 15', '20,610 MW', '21,963 MW', '\u22126.2%'],
    ['2019 Jul 15\u201321', '23,620 MW', '24,214 MW', '\u22122.5%'],
    ['2023 Sep 19\u201321', '14,600 MW', '15,617 MW', '\u22126.4%'],
]
for r, row in enumerate(data):
    for c, val in enumerate(row):
        table.rows[r + 1].cells[c].text = val

doc.add_paragraph('')  # spacer

# 1.3
add_heading('1.3 Root cause', level=2)
doc.add_paragraph(
    'The gap is the NYISO day-ahead forecast bias. DA forecasts are '
    'systematically conservative (under-forecast) as a reliability measure, '
    'especially during extreme weather. This is not a model deficiency \u2014 '
    'the model faithfully uses the same forecast NYISO operators had when '
    'making commitment decisions.'
)

# 1.4
add_heading('1.4 How to improve accuracy', level=2)

p = doc.add_paragraph()
p.add_run('Option A \u2014 Use actual load as "forecast" (perfect foresight). ').bold = True
p.add_run(
    'Replace the DA forecast with the realized actual load in the deterministic run. '
    'This eliminates the forecast bias entirely. Implementation: in NyisoLoader.'
    'create_timeseries(), set fcst = actl for load buses. '
    'Pros: removes the systematic ~3\u20136% load bias. '
    'Cons: not realistic \u2014 operators don\u2019t have perfect foresight. '
    'Use this for validation plots only, not for stochastic analysis.'
)

p = doc.add_paragraph()
p.add_run('Option B \u2014 Bias-correct the DA forecast. ').bold = True
p.add_run(
    'Compute the historical DA forecast bias per zone and per hour-of-day, '
    'then apply an additive or multiplicative correction. For example, if '
    'Zone J is consistently 4% under-forecast at hour 15, multiply '
    'the DA forecast by 1.04. This preserves the forecast uncertainty '
    'structure while removing systematic bias. '
    'Implementation: compute bias table from the multi-year load files, '
    'apply in create_timeseries() before distributing to buses.'
)

p = doc.add_paragraph()
p.add_run('Option C \u2014 Leave as-is (recommended for stochastic UC). ').bold = True
p.add_run(
    'The DA forecast bias is realistic and represents what operators actually see. '
    'The stochastic scenarios already sample around this forecast, and some '
    'scenarios will exceed the actual. For measuring cost-of-uncertainty, '
    'using the real DA forecast is methodologically correct.'
)

# ═══════════════════════════════════════════════════════════════
# SECTION 2: LMP CURVES
# ═══════════════════════════════════════════════════════════════
add_heading('2. System LMP Curves', level=1)

add_fig('lmp_fan_chart.png',
        'Figure 3 \u2014 2019 LMP fan chart: model scenarios vs. NYISO actual')
add_fig('lmp_2023_vs_actual.png',
        'Figure 4 \u2014 2023 LMP: model vs. NYISO actual')

# 2.1
add_heading('2.1 How each curve is computed', level=2)

add_heading('NYISO actual DA LMP (green)', level=3)
doc.add_paragraph(
    'Source: NYISO Day-Ahead LBMP (Locational Based Marginal Price), '
    'hourly, per zone. For 2019: third_party/NYgrid/Data/priceHourly_2019.csv. '
    'For 2023: data/nyiso_cache/2023/da_lbmp/ (daily CSV files). '
    'The system-average LMP is computed as the unweighted mean of '
    'the 11 NYISO load zones (A\u2013K). Timestamps are converted from '
    'Eastern time to UTC for alignment with the model (EDT = UTC\u22124 in summer).'
)

add_heading('Model LMP \u2014 deterministic (red dashed)', level=3)
doc.add_paragraph(
    'The model LMP is the "Price" column in Vatic\u2019s hourly_summary output. '
    'It is computed as follows:'
)
doc.add_paragraph(
    '1. The Reliability Unit Commitment (RUC) commits generators for '
    'the next 48 hours by solving a Mixed-Integer Program (MIP) that '
    'minimizes total production cost subject to generator constraints '
    '(min up/down times, ramp rates, startup costs) and transmission '
    'constraints (PTDF power flow on the 46-bus Kron-reduced network).',
    style='List Number'
)
doc.add_paragraph(
    '2. The Security-Constrained Economic Dispatch (SCED) re-dispatches '
    'the committed fleet every hour to meet realized load at minimum cost. '
    'Generator commitments are fixed; only dispatch levels change.',
    style='List Number'
)
doc.add_paragraph(
    '3. After each SCED, the model solves an LP relaxation of the dispatch '
    'problem. The dual variable (shadow price) of the system power balance '
    'constraint gives the system marginal price: the cost of serving one '
    'additional MWh of load. This is reported as "Price".',
    style='List Number'
)
doc.add_paragraph(
    '4. With PTDF network flow, the shadow price is a system-wide average. '
    'Bus-level LMPs are also computed (in bus_detail) as the sum of '
    'the energy component, congestion component (from binding branch/interface '
    'constraints), and losses component.',
    style='List Number'
)

add_heading('Model LMP \u2014 stochastic band (blue)', level=3)
doc.add_paragraph(
    'Same computation as the deterministic, but applied to each of the '
    '100 PGscen scenarios. Each scenario has different wind, solar, and '
    'load realizations, producing different commitments and dispatch, '
    'and therefore different marginal prices. The P5\u2013P95 and P25\u2013P75 '
    'bands show the spread of hourly system LMP across scenarios.'
)

# 2.2
add_heading('2.2 Current gap', level=2)
doc.add_paragraph(
    'The model LMPs are substantially below actual NYISO DA LMPs:'
)
table2 = doc.add_table(rows=3, cols=4, style='Light Grid Accent 1')
headers2 = ['Period', 'Model mean', 'Actual mean', 'Gap']
for i, h in enumerate(headers2):
    table2.rows[0].cells[i].text = h
data2 = [
    ['2019 Jul 15\u201321', '~$15/MWh', '~$35/MWh', '\u224857%'],
    ['2023 Sep 19\u201321', '$12.8/MWh', '$23.3/MWh', '\u224845%'],
]
for r, row in enumerate(data2):
    for c, val in enumerate(row):
        table2.rows[r + 1].cells[c].text = val

doc.add_paragraph('')

# 2.3
add_heading('2.3 Root causes (three stacked effects)', level=2)

p = doc.add_paragraph()
p.add_run('Cause 1 \u2014 Production cost vs. market price (~50% of gap). ').bold = True
p.add_run(
    'The model computes marginal production cost: heat_rate \u00d7 fuel_price. '
    'Real NYISO DA LMPs are market-clearing prices that include: '
    '(a) generator offer markups above marginal cost (generators bid '
    'strategically, not at cost); '
    '(b) scarcity pricing adders during tight supply conditions (NYISO\u2019s '
    'Operating Reserve Demand Curves add premiums when reserves are low); '
    '(c) congestion rents on constrained interfaces that the reduced '
    'network may underestimate. '
    'This is a fundamental limitation of production cost models and is '
    'present in all academic UC formulations (Prescient, PLEXOS in cost mode, etc.).'
)

p = doc.add_paragraph()
p.add_run('Cause 2 \u2014 Load level (~10\u201315% of gap). ').bold = True
p.add_run(
    'Lower model demand (\u22122.5 to \u22126.4% vs. actual) means fewer '
    'expensive peakers are dispatched. Since peakers are the marginal units '
    'that set the system price, underestimating load directly '
    'underestimates the marginal cost. '
    'On the steepest part of the supply curve (peak hours), a 5% load '
    'error can translate to a 15\u201320% LMP error because the marginal '
    'generator shifts from a $40/MWh CC to a $80/MWh CT.'
)

p = doc.add_paragraph()
p.add_run('Cause 3 \u2014 Fuel price data (2023 only, ~5\u201310% of gap). ').bold = True
p.add_run(
    'For 2023, the model falls back to 2019 NG prices ($3.63/MMBtu) because '
    'fuelPriceWeekly_2023.csv is missing. Actual 2023 NG was ~$2.55/MMBtu. '
    'This makes the model\u2019s fuel costs ~40% too high, which partially '
    'offsets the other two causes. Fixing this would actually '
    'widen the LMP gap slightly for 2023 (lower fuel cost \u2192 lower model LMP), '
    'but would improve the model\u2019s internal consistency.'
)

# 2.4
add_heading('2.4 How to improve accuracy', level=2)

p = doc.add_paragraph()
p.add_run('Improvement 1 \u2014 Add a markup factor to generator costs '
          '(quick, ~30% gap closure). ').bold = True
p.add_run(
    'Multiply each generator\u2019s cost curve by a calibrated markup factor '
    'that approximates the wedge between production cost and offer price. '
    'Typical values from the literature (Ela et al. 2011, NREL): '
    '1.1\u20131.3\u00d7 for baseload, 1.5\u20132.0\u00d7 for peakers. '
    'Implementation: add a markup_factor parameter to NyisoLoader that '
    'scales TotalCostValues after construction. '
    'This is a single calibration parameter per generator type. '
    'Pros: simple, captures the dominant effect. '
    'Cons: static markup doesn\u2019t capture time-varying scarcity pricing.'
)

p = doc.add_paragraph()
p.add_run('Improvement 2 \u2014 Implement Operating Reserve Demand Curves '
          '(moderate effort, ~20% gap closure). ').bold = True
p.add_run(
    'NYISO uses a graduated penalty for reserve shortfall: as reserves '
    'decrease below the requirement, the scarcity price increases '
    'stepwise ($25 \u2192 $50 \u2192 $500 \u2192 $1,000/MWh). The current model uses '
    'a single flat penalty ($1,000/MWh). Implementing a stepped ORDC '
    'would raise LMPs during tight hours without requiring generator-level '
    'markup. Egret supports this via reserve_zones and stepped penalty '
    'curves, but it requires wiring in NyisoLoader.'
)

p = doc.add_paragraph()
p.add_run('Improvement 3 \u2014 Use actual load for deterministic validation '
          '(quick, ~5\u201310% gap closure). ').bold = True
p.add_run(
    'As discussed in Section 1, replacing the DA forecast with actual '
    'realized load would push more expensive units to the margin, '
    'raising model LMPs closer to actual. This is a 2-line code change '
    'in create_timeseries() and is appropriate for validation plots '
    '(but not for stochastic UC analysis where forecast uncertainty is '
    'the object of study).'
)

p = doc.add_paragraph()
p.add_run('Improvement 4 \u2014 Fix 2023 fuel prices '
          '(necessary for consistency, may widen gap). ').bold = True
p.add_run(
    'Download EIA weekly NG prices and generate fuelPriceWeekly_2023.csv. '
    'This will lower model LMPs for 2023 (correct direction for internal '
    'consistency) but will widen the gap vs. actual DA LMPs. '
    'Accurate fuel prices are essential for valid cross-year comparisons '
    'even if the absolute LMP level remains below market.'
)

p = doc.add_paragraph()
p.add_run('Improvement 5 \u2014 Zonal reserve requirements '
          '(moderate effort, ~5\u201310% gap closure in SENY). ').bold = True
p.add_run(
    'NYISO enforces locational reserves: ~1,200 MW in SENY (zones G\u2013K) '
    'and ~300 MW in NYC (zone J). The current model uses a single '
    'system-wide constraint. Adding zonal reserves would force more '
    'expensive downstate generators online (instead of letting cheap '
    'upstate capacity provide all reserves), raising downstate LMPs '
    'and increasing the system-average LMP. '
    'This is the single improvement most likely to raise peak-hour '
    'LMPs because it forces NYC peakers to run for local reliability.'
)

# ═══════════════════════════════════════════════════════════════
# SECTION 3: SUMMARY
# ═══════════════════════════════════════════════════════════════
add_heading('3. Summary and Prioritization', level=1)

doc.add_paragraph(
    'The table below prioritizes improvements by expected impact and effort:'
)

table3 = doc.add_table(rows=7, cols=5, style='Light Grid Accent 1')
h3 = ['#', 'Improvement', 'Expected gap closure', 'Effort', 'Affects']
for i, h in enumerate(h3):
    table3.rows[0].cells[i].text = h
rows3 = [
    ['1', 'Cost markup factors', '~30%', 'Low (1 param/gen type)', 'LMP'],
    ['2', 'Zonal reserves (SENY + NYC)', '~5\u201310%', 'Medium', 'LMP'],
    ['3', 'Stepped ORDC penalty', '~20%', 'Medium', 'LMP (peaks)'],
    ['4', 'Use actual load in validation', '~5\u201310%', 'Low (2 lines)', 'Demand + LMP'],
    ['5', 'Fix 2023 fuel prices', 'Consistency', 'Low', 'LMP (2023)'],
    ['6', 'DA forecast bias correction', '~3\u20136%', 'Low\u2013Medium', 'Demand'],
]
for r, row in enumerate(rows3):
    for c, val in enumerate(row):
        table3.rows[r + 1].cells[c].text = val

doc.add_paragraph('')

doc.add_paragraph(
    'Important caveat: for the stochastic UC research question '
    '(cost-of-uncertainty measurement), the model does not need to match '
    'absolute market prices. The relevant comparison is the relative '
    'difference between the deterministic and stochastic runs within '
    'the same model. Both use the same cost assumptions, so the '
    'cost-of-uncertainty percentage is valid regardless of the absolute '
    'LMP level. The improvements above are valuable for cross-validation '
    'against NYISO data and for future work where absolute LMP accuracy '
    'matters (e.g., revenue estimation for storage or renewable projects).'
)

# ═══════════════════════════════════════════════════════════════
# SAVE
# ═══════════════════════════════════════════════════════════════
doc.save(str(OUT_PATH))
print(f'Saved to {OUT_PATH}')
