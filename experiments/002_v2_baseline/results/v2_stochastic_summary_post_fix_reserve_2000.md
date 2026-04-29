# V2 Stochastic Experiment: Post Load-Fix, 2000 MW Reserve

**Date**: 2026-04-28
**Configuration**: Post bus-collision fix, Gurobi PTDF, 2000 MW reserve

## Headline Results

- **100/100 scenarios completed, 6 with load shedding**
- **Cost of uncertainty: -2.71%**
- **Cost CV: 0.73%**
- **Load match to NYISO: 0.0%**

## Reserve Sensitivity Comparison

| Metric | 2620 MW | 2000 MW | Difference |
|--------|:-------:|:-------:|:----------:|
| Completion | 100/100 | 100/100 | Same |
| Load shedding | 0/100 | 6/100 | +6 |
| Det total cost | $72.7M | $73.2M | +0.8% |
| Stoch mean cost | $70.9M | $71.3M | +0.6% |
| **Cost of uncertainty** | **-2.52%** | **-2.71%** | **0.19 pp** |
| Cost CV | 0.62% | 0.73% | +0.11 pp |
| Det reserve shortfall | 54,399 MWh | 38,308 MWh | -30% |
| Stoch mean RS | 37,574 MWh | 28,271 MWh | -25% |
| Det bus LMP | $64.9/MWh | $72.7/MWh | +12% |

## Key Finding: Cost-of-Uncertainty is Robust

The cost-of-uncertainty changes by only **0.19 percentage points**
between the two reserve settings (well within the 1 pp stability
threshold). Both show:

- **Direction**: Negative (stochastic cheaper than deterministic)
- **Magnitude**: ~2.5-2.7%
- **Interpretation**: The DA forecast consistently overestimates
  system stress during this heat wave week. Stochastic scenarios
  that realize lower-than-forecast load save more than high-load
  scenarios cost.

This is a robust finding that does not depend on the reserve
calibration choice.

## Load Shedding at 2000 MW

6 of 100 scenarios experienced some load shedding at the 2000 MW
setting. This indicates that the July 2019 heat wave pushes the
system close to its capacity limits. The 2620 MW setting avoids
load shedding entirely by maintaining more headroom, at the cost
of higher reserve shortfall penalties.

## Bus LMP Paradox

Counter-intuitively, the lower reserve (2000 MW) produces *higher*
bus LMPs ($72.7 vs $64.9). This is because:

1. With less reserve headroom, the optimizer commits fewer units
   purely for reserve, but the units that are committed run at
   higher capacity factors closer to their steep marginal cost
   segments.
2. The 6 load-shedding scenarios at $10,000/MWh penalty pull up
   the average bus LMP.
3. The reserve shortfall penalty at $1,000/MWh fires less often
   but the energy-only marginal cost is higher.

This confirms the decomposition finding: the reserve requirement
interacts with commitment decisions in complex ways that affect
the marginal price non-linearly.

## Cost Distribution (2000 MW)

| Percentile | Cost ($) |
|------------|----------|
| P5 | 70,404,204 |
| P25 | 70,878,118 |
| P50 | 71,221,303 |
| P75 | 71,659,478 |
| P95 | 72,239,331 |
