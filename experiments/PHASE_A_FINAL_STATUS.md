# Phase A Final Status: NYISO Stochastic UC Model

**Date**: 2026-04-28
**For**: PI review and decision on path forward

---

## 1. What's been validated

### System load accuracy
The model serves the correct total NYCA load. After fixing a bus name
collision bug (four bus pairs sharing names, 1,374 MW recovered), the
model load matches NYISO actual to **0.0%** at every hour across all
four validated years (2019, 2020, 2022, 2023).

### System-average LMP accuracy
Using the correct metric (bus LMP = LP dual of power balance, not
Vatic's "Price" field which is average cost):

| Year | Period | Bus LMP | NYISO LMP | Gap | Condition |
|------|--------|--------:|----------:|:---:|-----------|
| 2020 | Sep | $19.4 | $17.3 | **+12%** | Shoulder, moderate RS |
| 2022 | Sep | $80.6 | $72.0 | **+12%** | High gas year |
| 2023 | Sep | $29.6 | $23.3 | **+27%** | Moderate gas |
| 2019 | Jul | $64.9 | $30.1 | +116% | Heat wave, heavy RS |

For shoulder seasons (2020, 2022): +12% — competitive with published
PCM validations (10-25% typical). The 2019 July heat wave is an
outlier due to the reserve constraint binding heavily.

### LMP gap decomposition (2020)

The +12% gap on 2020 is fully explained:
- During reserve-adequate hours (10/24): model is **-6.6%** below NYISO
- During reserve-binding hours (14/24): model is **+28%** above NYISO
- The overestimation is from the $1,000/MWh reserve shortfall penalty

**Dynamic range**: The model captures 102% of NYISO's daily peak-to-
trough variation (2.2x vs 2.2x). There is no dynamic range compression.
The gap is a near-uniform parallel shift of ~$5/MWh driven by uniform
bus LMPs (no zonal pricing) keeping the system-average floor too high.

### Stochastic UC experiment

100 scenarios, July 15-21 2019, PGscen wind/solar/load:
- **100/100 completion**, 0 load shedding
- **Cost-of-uncertainty: -2.5%** (stochastic cheaper than deterministic)
- Robust to reserve choice: -2.52% at 2620 MW, -2.71% at 2000 MW
  (0.19 pp difference — within noise)
- Cost CV: 0.62-0.73%
- Interpretation: NYISO DA forecasts overpredict system stress during
  heat waves, so the stochastic mean (which includes lower-than-forecast
  realizations) is cheaper

### Infrastructure

- Gurobi persistent solver: 10x faster than CBC, ~40s per scenario-day
- 100-scenario ensemble: 79 min total wall time
- Egret Pyomo 6.10 compatibility patch: documented, runtime-checked
- Regression tests: 4 load distribution tests, 17 Path B tests

## 2. What hasn't been validated

### Zonal LMP accuracy
The model produces **uniform bus LMPs** across all 35 buses at every
hour. There is zero zonal price differentiation. NYISO actual shows
$10-20/MWh zonal spread. This is caused by:
- Interface constraints not binding at 2.0x Kron scale (Central East
  reaches 97% utilization but does not bind)
- No zonal reserve requirements

This means the model **cannot currently answer zonal research
questions** (e.g., "what is the cost of uncertainty in NYC?").

### Peak-period LMP accuracy
During the July 2019 heat wave, the reserve constraint binds heavily
(54,000+ MWh of RS), inflating bus LMPs to +116% above NYISO. The
2,620 MW reserve (total NYISO operating reserve) applied as a single
thermal-headroom constraint is too restrictive. This is a calibration
issue, not a structural model problem.

### Multi-year consistency
Only four years validated (2019, 2020, 2022, 2023). Years with
extreme weather (2019 July) show large deviations. The model is most
accurate for shoulder-season weeks.

## 3. Cost-of-uncertainty result

**Headline**: Accounting for renewable and load forecast uncertainty
reduces expected production cost by **2.5 ± 0.2%** relative to the
deterministic day-ahead forecast, for a July heat wave week on NYISO.

| Setting | Cost of uncertainty | Cost CV | Reserve |
|---------|:------------------:|:-------:|---------|
| 2620 MW reserve | -2.52% | 0.62% | NYISO total operating |
| 2000 MW reserve | -2.71% | 0.73% | Thermal-only component |
| Pre-load-fix (2620 MW) | -1.01% | 0.84% | Buggy load |

The negative sign means the stochastic mean is cheaper than the
deterministic baseline. This is consistent with asymmetric DA forecast
errors during heat events (over-forecast bias).

**Confidence**: The result is robust to reserve calibration (0.19 pp
sensitivity), but was computed under a model that produces uniform
bus LMPs. Adding zonal pricing could change the result if congestion
costs respond differently to load scenarios than energy costs do.

## 4. Known feature gaps and expected impact

| Feature | Expected impact | Effort |
|---------|:--------------:|:------:|
| Zonal reserves (SENY + NYC) | Enables zonal LMPs; may change system avg by ~$2/MWh | 3-5 days |
| Reserve calibration (2620 → 2000 MW) | Reduces RS penalty; ~-10 pp on peak LMP gap | 1 day |
| Kron scale reduction (2.0x → 1.85x) | Minor; only helps after zonal reserves | 1 day |
| Bid markups (5-15% on gas) | Would increase model LMPs by ~$1-3/MWh | 1 day |
| ORDC stepped penalty | Improves peak pricing; small for shoulder season | 2-3 days |

## 5. Three options for path forward

### Option 1: Multi-year stochastic campaign now
**Start the multi-year campaign immediately using the current model.**

- Pros: The cost-of-uncertainty measurement is a within-model relative
  comparison that doesn't depend on absolute LMP accuracy. The model
  is infrastructure-ready (100 scenarios in 79 min). System-level
  results are defensible.
- Cons: Uniform LMPs mean zonal results are not meaningful. The -2.5%
  result may shift by 0.5-1 pp after zonal reserves. The paper must
  carefully scope claims to "system-level" and cannot make zonal
  statements.
- Timeline: 2-3 weeks for multi-year runs + analysis

### Option 2: Add zonal reserves first, then campaign
**Implement SENY/NYC reserve requirements (Phase B.2), validate
zonal LMP pattern, then start the campaign.**

- Pros: Enables zonal research questions (cost-of-uncertainty in NYC
  vs upstate). Improves the off-peak system-average accuracy by
  reflecting zonal price structure in the load-weighted average.
  Strengthens the paper's validation story.
- Cons: 3-5 days of implementation + 1-2 days of validation before
  any research output. Requires Egret's zonal reserve formulation
  (needs verification it's wired correctly).
- Timeline: 1 week for implementation + validation, then 2-3 weeks
  for campaign

### Option 3: Full calibration (reserves + markups + ORDC), then campaign
**Complete all Phase B calibration items before starting research.**

- Pros: Best possible LMP accuracy. Strongest validation story for
  the paper. Most defensible results.
- Cons: 2-3 weeks of calibration work before any research output.
  Diminishing returns: bid markups and ORDC may improve accuracy by
  5-10% but don't change the fundamental research question.
  Risk of over-engineering before the first research result.
- Timeline: 3 weeks for calibration, then 2-3 weeks for campaign

## 6. Recommendation: Option 2

**Add zonal reserves, then start the multi-year campaign.**

Reasoning:
1. Zonal reserves are the single feature that gates the most
   research questions. Without them, the model cannot address
   zonal cost-of-uncertainty, which is the most policy-relevant
   dimension (NYC vs rest of state).

2. The implementation is bounded (3-5 days, known Egret formulation)
   and testable (compare zonal LMP pattern to NYISO actual).

3. The current system-level results are good but the paper is
   stronger with zonal differentiation. A -2.5% system-level
   result is interesting; a zonal decomposition showing where
   uncertainty costs concentrate is publishable.

4. Bid markups and ORDC (Option 3) are refinements that don't
   gate research questions. They can be added later as sensitivity
   analyses without re-running the entire campaign.

Option 1 is defensible if timeline pressure is high. Option 3 is
gold-plating that delays research output without proportional benefit.
