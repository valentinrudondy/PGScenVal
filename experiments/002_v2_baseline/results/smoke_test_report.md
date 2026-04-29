# v2 Smoke Test Validation Report

## Data loaded
- Deterministic days: 1/1
- Stochastic scenarios: 5/5

## Check 1: All scenarios complete to optimality
- 5/5 scenarios completed all 1 target days
- **PASS**

## Check 2: Cost CV across scenarios > 1%
- Mean cost: $9,091,709
- Std dev: $75,613
- CV: 0.83%
- **FAIL** (threshold: >1%)

## Check 3: Wind correlation scen_0 vs scen_1 < 0.95
- Sites compared: 23
- Mean per-site correlation: 0.388
- Max per-site correlation: 0.929
- **PASS** (threshold: max < 0.95)

## Check 4: Load varies across scenarios (per-zone CV > 0.3%)
- Zones analyzed: 11
- CV range: 0.21% — 1.21%
- Mean CV: 0.49%
- **FAIL** (threshold: all zones > 0.3%)

## Check 5: BESS dispatches in >= 3 of 5 scenarios
- Scenarios with BESS dispatch: 0/5
- **FAIL** (threshold: >= 3)
- hourly_summary columns: ['FixedCosts', 'VariableCosts', 'LoadShedding', 'OverGeneration', 'AvailableReserves', 'ReserveShortfall', 'RenewablesUsed', 'RenewablesAvailable', 'RenewablesCurtailment', 'Demand', 'Price', 'Number on/offs', 'Sum on/off ramps', 'Sum nominal ramps']

## Summary
**Overall: SOME CHECKS FAILED**

## Scenario Cost Table
| Scenario | Total Cost ($) | Load Shed (MWh) |
|----------|---------------|-----------------|
| Deterministic | 8,235,940 | 0.0 |
| Scenario 000 | 9,135,276 | 0.0 |
| Scenario 001 | 9,183,936 | 0.0 |
| Scenario 002 | 9,035,402 | 0.0 |
| Scenario 003 | 9,107,357 | 0.0 |
| Scenario 004 | 8,996,576 | 0.0 |