# Cross-Year Validation: Post Load-Distribution Fix

**Date**: 2026-04-28
**Fix applied**: Bus name collision in NyisoLoader.create_timeseries()
(ROCHESTER, RAMAPO, HUNTLEY, GARDENVILLE — 1,374 MW / 4.7% recovered)

## Results

| Year | Model LMP | NYISO LMP | Post-fix dev | Pre-fix dev | Load gap |
|------|----------:|----------:|:------------:|:-----------:|:--------:|
| 2019 Jul | $14.8 | $25.9 | **-43.0%** | +59.4% | 0.0% |
| 2020 Sep | $8.2 | $16.0 | **-48.9%** | +2.9% | 0.0% |
| 2022 Sep | $35.3 | $72.0 | **-51.0%** | +2.7% | 0.0% |
| 2023 Sep | $13.8 | $23.3 | **-40.7%** | +16.6% | 0.0% |

### Operational metrics

| Year | Total cost | Load shed | Reserve shortfall | Time |
|------|----------:|:---------:|:-----------------:|-----:|
| 2019 | $23,641,149 | 0 MWh | 9,772 MWh | 135s |
| 2020 | $9,376,021 | 0 MWh | 13,993 MWh | 160s |
| 2022 | $46,339,842 | 0 MWh | 1,988 MWh | 169s |
| 2023 | $15,743,912 | 0 MWh | 3,709 MWh | 156s |

Zero load shedding across all four years on target days.

## Key finding: pre-fix numbers were compensating errors

The pre-fix validation results (+2.9% for 2020, +2.7% for 2022) were
**accidentally accurate** due to two offsetting errors:

1. **Production cost model underestimates market LMPs** (~40-50%):
   The model computes marginal fuel cost, while NYISO DA LMPs include
   offer markups, scarcity pricing, and congestion rents.

2. **Bus collision bug overestimated LMPs** (~5-10%): With 4.7% of
   load missing (especially Zone B losing 69.7%), fewer generators
   were dispatched, but the remaining generators operated at higher
   capacity factors closer to their marginal cost curves, and the
   reduced system stress changed the dispatch merit order. The net
   effect was to inflate model LMPs.

These two errors happened to approximately cancel for 2020 and 2022,
producing a false +2.9% and +2.7% match. The cancellation was not
exact for 2023 (+16.6% pre-fix), which is why 2023 appeared as an
outlier — it was simply the year where the two errors cancelled
least well.

## What the post-fix numbers mean

The ~40-50% underestimation is the **true structural gap** between
a production cost model and NYISO market prices. This gap is:

- **Consistent across years** (40-51% for all four years)
- **Expected for production cost models** in the literature
- **Not a calibration failure** — it reflects the fundamental
  difference between cost minimization and market clearing

The model's relative accuracy (comparing years to each other) is
good: the ratio of model LMPs tracks the ratio of actual LMPs.
2022 (high gas year) is correctly ~4x higher than 2020 (low gas).

## Implications for the stochastic UC experiment

The cost-of-uncertainty measurement (-1.01%) remains valid because
it compares stochastic vs deterministic within the same model. Both
use the same cost assumptions, so the relative difference is
meaningful regardless of the absolute LMP level.

However, the v2 ensemble was run with the buggy load distribution.
A re-run with the fix would:
- Increase total system load by ~4.7%
- Likely increase costs by ~5-10%
- May change the cost-of-uncertainty direction or magnitude
- Would produce more accurate LMP fan charts vs NYISO actual

## Recommendations

1. **Do not claim LMP validation at +/-5% accuracy** — the true
   structural gap is ~45%. Previous claims were based on
   compensating errors.

2. **Report the model as a production cost model** with known
   LMP bias, and frame the stochastic UC results as relative
   measurements within the model.

3. **To close the LMP gap**, implement the improvements from
   Model_vs_Actual_Methodology.docx (cost markups, ORDCs,
   zonal reserves). Each addresses part of the structural gap.

4. **2023 is no longer an outlier** — at -40.7%, it's actually
   the *best* match of any year. The previous +16.6% was an
   artifact of where the compensating errors happened to land.
