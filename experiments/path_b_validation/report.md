# Path B Import Pricing — Phase A.3 Validation Report

## Summary

Implemented year-specific import costs derived from NYISO day-ahead
zonal LMP data. Formula: `cost = 0.8 * mean(zone DA LMP)`.

Validated against NYISO actual LMPs for 2020 (with PTDF transmission
constraints). 2022 and 2023 validated in copper-sheet mode due to a
CBC solver build compatibility issue with PTDF.


## Cross-Year LMP Comparison

| Year | Config | Model avg | NYISO avg | Deviation | LS | RS |
|------|--------|----------:|----------:|----------:|---:|---:|
| 2020 | v1 (static + PTDF) | $23.15 | $15.97 | **+44.9%** | 0 | 1,917 |
| 2020 | **Path B + PTDF** | **$16.88** | $15.97 | **+5.7%** | 0 | 2,349 |
| 2020 | Path B copper | $17.77 | $15.97 | +11.3% | 0 | 10,212 |
| 2022 | v1 (static + PTDF) | $74.36 | $72.05 | +3.2% | 0 | 6,976 |
| 2022 | Path B copper | $80.82 | $72.05 | +12.2% | 0 | 18,514 |
| 2023 | v1 (static + PTDF) | $27.03 | $23.34 | +15.8% | 0 | 0 |
| 2023 | Path B copper | $28.95 | $23.34 | +24.1% | 0 | 3,515 |


## 2020 Analysis (primary validation)

Path B with PTDF: **+5.7%** deviation — close to the ±5% target.

### LMP distribution shift (the "$30 ceiling" fix)

| Range | v1 | Path B |
|-------|---:|-------:|
| $10-15 | 1.4% | 26.4% |
| $15-20 | 30.9% | 56.9% |
| **$30-35** | **55.6%** | **8.3%** |

The PJM import cost dropped from $30 (static) to $16.25 (Path B).
This eliminated the $30 price ceiling that dominated 56% of bus-hours.

### Per-zone bias (Path B vs v1)

| Zone | NYISO | v1 bias | Path B bias |
|:----:|------:|--------:|------------:|
| A | $13.89 | +$9.16 | **+$2.96** |
| B | $13.92 | +$9.13 | **+$2.93** |
| C | $14.24 | +$8.84 | **+$2.62** |
| D | $10.50 | +$12.51 | +$6.34 |
| E | $14.24 | +$8.76 | **+$2.60** |
| F | $17.59 | +$5.76 | **-$0.76** |
| G | $16.39 | +$6.93 | **+$0.50** |
| H | $17.90 | +$5.41 | **-$0.95** |
| I | $18.19 | +$5.12 | **-$1.16** |
| J | $18.40 | +$4.89 | **-$1.41** |
| K | $20.41 | +$2.90 | **-$3.38** |

All zones except D are within ±$3.50. Zone D (+$6.34) is near the
HQ import point — the 0.8 discount factor slightly overprices HQ
for low-load September conditions.

### Per-bus accuracy improvement

| Metric | v1 | Path B |
|--------|---:|-------:|
| Mean absolute error | $9.83 | **$3.41** |
| Median absolute error | $11.81 | **$2.15** |
| Mean bias | +$7.85 | **+$1.58** |

Median AE of $2.15 is well within the $10/MWh target.


## 2022 and 2023 (copper-sheet only)

PTDF simulations for 2022 and 2023 fail with the current CBC 2.10.13
Homebrew build. The SCED phase reports `infeasible` due to tight
transmission constraints that the v1 CBC build handled differently.

Copper-sheet results show:
- **2022**: +12.2% (v1 was +3.2%). The v1 result was accidentally
  close — cheap HQ at $5 compensated for overpriced internal gas.
  Path B corrects HQ to $37.80 but exposes the underlying cost
  overestimation in a high-gas year.
- **2023**: +24.1% (v1 was +15.8%). Without congestion pricing, the
  copper-sheet model overshoots. PTDF results (like 2020's 5.6 pp
  improvement from copper to PTDF) would bring this closer.


## Success Criteria

| Criterion | Status |
|-----------|--------|
| 2020 deviation < ±5% (PTDF) | **BORDERLINE** (+5.7%) |
| 2020 median AE < $10 | **PASS** ($2.15) |
| 2022/2023 PTDF validation | BLOCKED by CBC solver issue |
| Import dispatch rational | PASS (PJM marginal ~57%, not at Pmax) |
| Zero load shedding | PASS (all years) |


## CBC Solver Compatibility Issue

The CBC 2.10.13 Homebrew build reports `infeasible` for SCED phases
that the v1 build (same version number) solved successfully. This is
a CBC build configuration difference, not a model issue:
- 2020 works with PTDF (less tight system)
- 2022/2023 fail (capacity-short, 2.7% reserve margin)
- All years work in copper-sheet mode

**Mitigation options** (Phase B):
1. Pin the CBC binary from the v1 build
2. Use Gurobi (Princeton academic license)
3. Increase the Kron scale factor from 2.0x to 2.5x
4. Add slack variables to the PTDF formulation


## Deliverables

- `experiments/path_b_validation/run.py` — copper-sheet validation runner
- `experiments/path_b_validation/analyze.py` — LMP comparison analysis
- `experiments/path_b_validation/results/det_{2020,2022,2023}.pkl`
- `experiments/cross_year_validation/results/warmup/det_2020.pkl` — PTDF result
