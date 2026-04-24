# Path B Import Pricing — Phase A.3 Report

## Summary

Implemented year-specific import costs derived from NYISO day-ahead
zonal LMP data. The formula `cost = 0.8 * mean(zone DA LMP)` replaces
the static import costs that were identified as the dominant source of
LMP error in Phase A.2.

## Changes

### Code
- `nyiso_loader.py`: Added `_compute_path_b_import_costs(year)` and
  integrated it into the `NyisoLoader.__init__` import generator loop.
  Path B costs are used automatically when NYISO DA LMP data is
  available for the target year; falls back to static costs otherwise.

### Cost Impact

| Import | Static | 2019 | 2020 | 2022 | 2023 |
|--------|-------:|-----:|-----:|-----:|-----:|
| HQ | $5.00 | $14.51 | $10.14 | **$37.80** | $19.36 |
| NE | $35.00 | $21.51 | $17.06 | $75.61 | $29.10 |
| PJM | $30.00 | $20.86 | $16.25 | **$65.76** | $26.61 |
| IESO | $15.00 | $20.50 | $14.32 | $45.70 | $20.54 |

The largest changes are in 2022 (gas price spike year): HQ goes from
$5 to $38, PJM from $30 to $66. This directly addresses the +10.8%
LMP deviation identified in the v1 cross-year validation.

### Tests
- 17 regression tests in `experiments/regression/test_path_b_costs.py`
  — all passing.
- 17 NYgrid reader tests — all passing.

## Simulation Validation

**Simulation re-runs are blocked** by the absence of the CBC solver.
The cross-year validation experiments require a MILP solver to run
Vatic's unit commitment. Once CBC (or another solver) is installed,
the following should be run:

```bash
python experiments/cross_year_validation/run.py --year 2020
python experiments/cross_year_validation/run.py --year 2022
python experiments/cross_year_validation/run.py --year 2023
```

### Expected Results

Based on the Phase A.2 root cause analysis (PJM at $30/MWh was
marginal 43-56% of hours, creating a price ceiling):

**2020**: PJM drops from $30 to $16.25. This should:
- Eliminate the $30 price ceiling
- Reduce the +$7.81 positive bias
- Improve hourly correlation (currently 0.51)

**2022**: HQ rises from $5 to $37.80, PJM from $30 to $65.76. This
should:
- Move the LMP deviation from +10.8% toward zero
- Reduce HQ over-dispatch (was at Pmax 74% of hours in v2 testing)

**2023**: PJM drops from $30 to $26.61. Modest improvement expected:
- Reduce +$4.17 bias by ~$3-4
- Slightly improve hourly correlation

### Success Criteria (to be verified when solver is available)

1. 2022 LMP deviation moves from +10.8% to within ±5%
2. No other year regresses by more than 3 percentage points
3. Import dispatch is economically rational (imports peak during
   high-cost hours, not mechanically at Pmax)

## Documentation

- Methodology: `docs/path_b_import_pricing.md`
- Regression tests: `experiments/regression/test_path_b_costs.py`
