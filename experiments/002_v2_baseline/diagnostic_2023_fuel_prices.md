# 2023 Fuel Price Diagnostic

**Date**: 2026-04-27, updated 2026-04-28
**Question**: Is the residual +16.6% LMP deviation for 2023 a fuel price
data issue or a deeper model issue?

## Original finding: Missing weekly fuel price data

`fuelPriceWeekly_2023.csv` did not exist. Weekly files stopped at 2021.

## Resolution: Fuel price hypothesis DISPROVEN

`fuelPriceWeekly_2023.csv` was created from EIA Henry Hub weekly spot
prices with zonal basis differentials derived from 2019-2021 NYgrid
files.

However, re-running 2023 (Sep 19-21) with the new weekly file showed
**negligible change**:

| Run | NG_A2E (Sep 19) | Model LMP | NYISO actual | Deviation |
|-----|-----------------|-----------|--------------|-----------|
| EIA annual (before) | $3.60/MMBtu | $12.8/MWh | $23.3/MWh | -44.9% |
| Weekly CSV (after) | $3.85/MMBtu | $13.1/MWh | $23.3/MWh | -44.1% |
| 2019 hardcoded default | $3.63/MMBtu | — | — | — |

The September 2023 delivered NY gas price (~$3.72/MMBtu) is almost
identical to the 2019 default ($3.63/MMBtu). The initial diagnostic
was wrong because it compared Henry Hub spot ($2.55) to the NYgrid
delivered price ($3.63) without accounting for the NY pipeline basis
differential (~$1.10/MMBtu).

## Actual root cause of model-vs-actual LMP gap

The ~45% model LMP underestimation is structural: production cost
models compute marginal fuel cost, while NYISO DA LMPs include offer
markups, scarcity pricing, and congestion rents. This gap is present
for all years (2019: ~57%, 2023: ~45%) and is inherent to the
modeling approach, not a data issue.

The previously reported +16.6% deviation was computed as a
cost-weighted metric comparing model total production cost against
NYISO cost benchmarks, not a raw LMP comparison. The two metrics
measure different things.

## Status

- `fuelPriceWeekly_2023.csv` created and placed in `third_party/NYgrid/Data/`
- Source: EIA Henry Hub weekly spot (rngwhhdW.htm) + zonal basis ratios
- The file improves internal consistency but does not materially
  change the model-vs-actual LMP comparison
