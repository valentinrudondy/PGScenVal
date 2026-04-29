# V2 Stochastic Experiment: Post Load-Fix, 2620 MW Reserve

**Date**: 2026-04-28
**Configuration**: Post bus-collision fix, Gurobi PTDF, 2620 MW reserve

## Headline Results

- **100/100 scenarios completed, 0 load shedding**
- **Cost of uncertainty: -2.52%**
- **Cost CV: 0.62%**
- **Load match to NYISO: 0.0%** (bus collision fix verified)

## Comparison to Pre-Fix

| Metric | Pre-fix | Post-fix | Change |
|--------|:-------:|:--------:|:------:|
| Det total cost | $62.7M | $72.7M | +16.0% |
| Stoch mean cost | $62.0M | $70.9M | +14.2% |
| Cost of uncertainty | -1.01% | **-2.52%** | -1.5 pp |
| Cost CV | 0.84% | 0.62% | -0.22 pp |
| Load match | -5.9% | **0.0%** | Fixed |

The cost increase (+16%) reflects the recovered 1,374 MW of load
now being served by marginal generators. The deepening of the
cost-of-uncertainty from -1.01% to -2.52% indicates the DA forecast
bias effect is amplified at correct load levels.

## Cost Distribution

| Percentile | Cost ($) |
|------------|----------|
| P5 | 70,114,794 |
| P25 | 70,537,585 |
| P50 | 70,797,365 |
| P75 | 71,167,199 |
| P95 | 71,567,483 |

## Bus LMP

Model bus LMP (deterministic): $64.9/MWh vs NYISO $30.1/MWh (+115.7%).
The large overestimation is driven by the 2,620 MW reserve binding
heavily during the July heat wave (54,399 MWh RS on deterministic,
37,574 MWh mean across stochastic). See reserve sensitivity analysis
in the companion 2000 MW report.
