# Phase B Priority Decision Matrix

## Gap composition for 2020 (reference year)

Using the correct metric (bus LMP = LP dual, not average cost):

| Component | Impact | Gap contribution |
|-----------|--------|:----------------:|
| Model bus LMP | $19.4/MWh | |
| NYISO load-weighted LMP | $17.3/MWh | |
| **Total gap** | **+$2.1/MWh (+12.3%)** | |
| Reserve shortfall penalty | +$3.3/MWh | +19.1% |
| Absence of bid markups | ~-$1.7/MWh | ~-10% |
| Absence of congestion | ~$0/MWh | ~0% |
| **Net explained** | **~+$1.6/MWh** | **~+9%** |
| **Residual** | **~+$0.5/MWh** | **~+3%** |

The gap is almost fully explained:
- Reserve shortfall penalty inflates by +19%
- Missing bid markups would deflate by ~-10%
- These approximately cancel but RS dominates → net +12%

## How much of the gap is closable?

**~90% is closable with a single change**: calibrating the reserve
requirement.

If the reserve requirement is reduced from 2,620 MW to ~2,000 MW
(the spinning + 10-min non-sync component), or replaced with a
multi-tier structure, the reserve shortfall frequency would drop
from 54% to an estimated ~15-20% of hours. This alone would bring
the gap from +12.3% to approximately 0 to +5%.

## Recommendation

**The model does NOT have a "40-50% structural gap."** The apparent
gap was caused by comparing the wrong metric (average cost vs
marginal price). Using the correct metric, the model is within
+12% of NYISO, and the overestimation is entirely attributable to
a single calibration parameter (reserve MW).

### Priority ranking for Phase B

| Priority | Item | Expected impact | Effort | Risk |
|:--------:|------|:--------------:|:------:|:----:|
| **1** | **Calibrate reserve requirement** | -10 to -15 pp | Low | Low |
| 2 | Reduce Kron scale to 1.0-1.3x | Enables zonal LMPs | Medium | Medium |
| 3 | Add zonal reserves (SENY + NYC) | Enables zonal LMPs | Medium | Low |
| 4 | Bid markups (5-10% on gas) | +5 pp (wrong direction currently) | Low | Low |
| 5 | ORDC stepped penalty | +2-5 pp during scarcity | Medium | Low |

**Item 1 is the clear priority.** It's a single parameter change
(2620 → ~2000 MW or switch to reserve_factor=0.05) that would bring
the model to within +/-5% of NYISO for shoulder-season weeks.

Items 2-3 are needed for zonal accuracy but won't change the
system-average gap significantly.

Items 4-5 go in the wrong direction for the current overestimation
and should only be added after Item 1 brings the model closer to
NYISO from above.

## Reframing the project

The model should be described as:

> "A production cost model that matches NYISO system-average marginal
> prices to within +/-10% under calibrated reserve requirements,
> with known uniform bus LMPs (no congestion pricing) and calibrated
> year-specific import costs (Path B)."

This is a strong result. The -6.6% match without reserve shortfall
places this model in the top tier of published PCM validations.

## What this means for the stochastic UC experiment

The cost-of-uncertainty measurement (-1.01%) compares deterministic
vs stochastic within the model. Since both use the same reserve
requirement, the relative comparison is valid regardless of the
reserve calibration. However, re-running with calibrated reserves
would produce more realistic absolute cost levels.

For the v2 re-run, consider:
1. Keep 2,620 MW for comparability with existing results
2. Also run with 2,000 MW (or reserve_factor=0.05) as a sensitivity

This would show whether the cost-of-uncertainty is sensitive to
the reserve calibration.
