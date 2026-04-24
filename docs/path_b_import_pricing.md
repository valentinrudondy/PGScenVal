# Path B Import Pricing

## Problem

External import equivalents (PJM, HQ, NE, IESO) use static cost
parameters that don't track commodity price changes across years:

| Import | Static cost | Actual price dynamics |
|--------|------------:|----------------------|
| HQ | $5/MWh | Hydro bilateral: tracks Zone D LMP loosely |
| PJM | $30/MWh | Tracks Zone G LMP (gas-driven) |
| NE | $35/MWh | Tracks Zone F LMP (gas-driven) |
| IESO | $15/MWh | Hydro/nuclear: tracks Zone A LMP |

This causes two problems:
1. **2019-2020**: PJM at $30 is too high (actual was ~$20-21), making
   PJM marginal 43-56% of hours and creating a $30 price ceiling.
2. **2022**: HQ at $5 is catastrophically low (actual was ~$48),
   causing the model to import maximum cheap HQ power and crash LMPs.


## Methodology

**Formula**: For each external equivalent and each year:

```
import_cost[year] = 0.8 × mean(Zone_DA_LMP[year])
```

**Zone mapping**:
| Import | Reference Zone | Rationale |
|--------|:-------------:|-----------|
| HQ | Zone D (NORTH) | HQ enters at Moses E; Zone D is the receiving zone |
| NE | Zone F (CAPITL) | NE enters at New Scotland; Zone F is the receiving zone |
| PJM | Zone G (HUD VL) | PJM enters at Ramapo; Zone G is the receiving zone |
| IESO | Zone A (WEST) | IESO enters at Niagara; Zone A is the receiving zone |

**The 0.8 discount factor** reflects the gap between spot market
clearing prices and the effective cost of bilateral/firm imports:
- Long-term bilateral contracts (e.g., HQ-NY) are priced below spot
- Transmission losses and wheeling charges consume ~5-10% of value
- Market participant markup averages ~10-15% above production cost
- Net effect: import prices trade at approximately 80% of the
  receiving zone's spot average

This factor is approximate. A more sophisticated approach would use
actual bilateral contract prices (not publicly available) or
hourly-varying import costs (computationally expensive).


## Computed Costs

| Year | HQ ($/MWh) | NE ($/MWh) | PJM ($/MWh) | IESO ($/MWh) |
|------|----------:|----------:|-----------:|------------:|
| 2019 | 14.51 | 21.51 | 20.86 | 20.50 |
| 2020 | 10.14 | 17.06 | 16.25 | 14.32 |
| 2022 | 37.80 | 75.61 | 65.76 | 45.70 |
| 2023 | 19.36 | 29.10 | 26.61 | 20.54 |
| **Static** | **5.00** | **35.00** | **30.00** | **15.00** |


## Data Sources

1. **Primary**: `data/nyiso_cache/{year}/da_lbmp/` — NYISO day-ahead
   zonal LBMP data, downloaded monthly from `mis.nyiso.com`.
2. **Fallback**: `third_party/NYgrid/Data/priceHourly_{year}.csv` —
   legacy NYgrid format (same data, different layout).

The function `_compute_path_b_import_costs(year)` in
`nyiso_loader.py` tries both sources.


## Implementation

Path B is automatic: `NyisoLoader(year=YYYY)` computes import costs
from cached DA LMP data. If data is unavailable for a given year, it
falls back to the static costs in `_EXTERNAL_EQUIVALENTS`.

- **Import limits (Pmax)** are NOT changed by Path B. They remain at
  2019 p95 actual flows.
- **Only the $/MWh cost** is updated year-by-year.

This is by design: Path B addresses cost-only distortion. Changing
Pmax to declared capability requires Path B costs to prevent the
optimizer from over-importing cheap power (see known_limitations.md
item 1 for the HQ Pmax/cost coupling issue).


## Expected Impact

### 2019
- PJM drops from $30 to $20.86 — less PJM-marginal hours, better
  hourly LMP dynamics
- HQ rises from $5 to $14.51 — less HQ over-dispatch

### 2020
- PJM drops from $30 to $16.25 — should significantly reduce the
  positive bias observed in Phase A.2 (was +$7.81)
- HQ rises from $5 to $10.14 — moderate improvement

### 2022
- HQ rises from $5 to $37.80 — should dramatically fix the 2022
  LMP deviation (was +10.8% in v1, expected to approach 0%)
- PJM rises from $30 to $65.76 — matches the gas price environment

### 2023
- PJM drops from $30 to $26.61 — modest improvement
- HQ rises from $5 to $19.36 — reduces northern zone bias


## Regression Test

`experiments/regression/test_path_b_costs.py` (17 tests):
- Verifies costs are computed for all 4 imports for 2020/2022/2023
- Verifies costs are positive, plausible ($1-200), and differ from static
- Verifies 2022 HQ cost is >$20 (gas spike year)
- Verifies NyisoLoader applies Path B costs to generator cost curves
- Verifies total import capacity is unchanged


## Validation

Full before/after cross-year validation requires re-running
simulations with the CBC solver. The expected improvements are:

| Year | v1 LMP deviation | Path B expected |
|------|:-----------------:|:---------------:|
| 2019 | ~1.31x ratio | Should improve (PJM drops from $30 to $21) |
| 2020 | +$7.81 bias | Should improve (PJM drops from $30 to $16) |
| 2022 | +10.8% | Should approach 0% (HQ rises from $5 to $38) |
| 2023 | +$4.17 bias | Modest improvement (PJM drops from $30 to $27) |
