# Grid Model Validation — Phase A Report

## Overview

Phase A validates and calibrates the current 46-bus Kron-reduced NYISO
grid model on its existing NPCC-140 base. New topology (CHPE, Clean
Path, Smart Path) and zonal reserves are explicitly out of scope
(Phase B).

Five sub-phases were completed:

| Phase | Task | Status |
|-------|------|--------|
| A.1 | Kron reduction fidelity | DONE — fixed + validated |
| A.2 | Per-bus LMP validation | DONE — root cause identified |
| A.3 | Path B import pricing | DONE — implemented, awaiting solver |
| A.4 | IP2 mid-2020 retirement | DONE — implemented |
| A.5 | Heat rate policy | DONE — Decision A (freeze at 2019) |


## A.1: Kron Reduction Fidelity

**Report**: `experiments/kron_fidelity/report.md`

### Findings

1. **JSON arithmetic error**: The original `nygrid_kron_reduced.json`
   had 0.70% relative error in 7 Kron-equivalent branch impedances.
   Corrected by recomputing analytically from the full 140-bus
   admittance matrix. Now matches to machine precision (10⁻¹² degrees).

2. **Single-bus import approximation**: External imports were modeled
   at a single NY boundary bus, but the full model shows power
   distributing across 2-3 boundary points. Worst case: HQ splits
   50/50 between Moses E (Zone D) and Niagara W (Zone A).

### Changes

- **`nygrid_kron_reduced.json`**: Updated 8 branch impedances.
- **`nyiso_loader.py`**: Replaced single-bus `_EXTERNAL_EQUIVALENTS`
  with multi-bus distribution (9 import generators, was 4). Total
  import capacity unchanged.

### Result

| Metric | Before | After |
|--------|-------:|------:|
| Max interface flow error | 46.7% | **2.8%** |
| Max bus angle error | 19.2° | **1.7°** |


## A.2: Per-Bus LMP Validation

**Report**: `experiments/per_bus_lmp_validation/report.md`

### Findings

Downloaded NYISO generator-level nodal LMP data (~560 nodes/hour) and
compared against model bus-level LMPs from cached simulations.

| Year | Med. Abs. Error | Correlation | Bias |
|------|----------------:|:-----------:|-----:|
| 2020 | $9.06 | 0.51 | +$7.81 |
| 2022 | $27.17 | 0.26 | +$4.55 |
| 2023 | $7.25 | 0.23 | +$4.17 |

### Root cause

**Import pricing dominates the LMP distribution.** 43-56% of
bus-hours have LMP = $30/MWh (PJM import cost), creating a price
ceiling. The model cannot track hourly price dynamics when a single
import source sets the marginal price.

Worst buses are near external import points (Zone D for HQ, Zone A
for IESO). The grid topology, impedances, and generator costs are
not the problem — import pricing is.

### Deliverable

Bus mapping: `docs/nygrid_to_nyiso_node_mapping.md` (17 nodal + 18
zonal matches).


## A.3: Path B Import Pricing

**Report**: `experiments/path_b_validation/report.md`

### Implementation

Added `_compute_path_b_import_costs(year)` to `nyiso_loader.py`.
Formula: `cost = 0.8 × mean(zone DA LMP[year])`.

| Import | Static | 2019 | 2020 | 2022 | 2023 |
|--------|-------:|-----:|-----:|-----:|-----:|
| HQ | $5 | $14.51 | $10.14 | **$37.80** | $19.36 |
| PJM | $30 | $20.86 | $16.25 | **$65.76** | $26.61 |
| NE | $35 | $21.51 | $17.06 | $75.61 | $29.10 |
| IESO | $15 | $20.50 | $14.32 | $45.70 | $20.54 |

### Status

Code implemented and tested (17/17 regression tests pass).
Simulation re-runs are blocked by the absence of the CBC solver.

### Expected impact

- 2022 LMP deviation should move from +10.8% toward 0% (HQ: $5→$38)
- 2020 positive bias should decrease (PJM: $30→$16)
- PJM-marginal hours should drop from 43-56% to a much lower fraction

### Deliverables

- Methodology: `docs/path_b_import_pricing.md`
- Regression test: `experiments/regression/test_path_b_costs.py`


## A.4: IP2 Mid-2020 Retirement

### Implementation

Added `_NUCLEAR_RETIREMENTS` dict to `nyiso_fleet_updater.py` with
date-level retirement tracking:

```python
_NUCLEAR_RETIREMENTS = {
    "Indian Point 2": "2020-04-30",
    "Indian Point 3": "2021-04-30",
}
```

`FleetUpdater.update()` now accepts `sim_start_date`. When provided,
generators whose retirement date falls before the simulation start
are excluded.

### Result

| Scenario | Nuclear capacity |
|----------|----------------:|
| 2020 baseline (before fix) | 5,430 MW |
| 2020 Sept simulation (after fix) | **4,404 MW** |
| 2020 March simulation | 5,430 MW (IP2 still operating) |

The mechanism is general: any future mid-year retirement can be
added to `_NUCLEAR_RETIREMENTS`.


## A.5: Heat Rate Policy

**Decision**: **A — Freeze at 2019 values**

See `docs/heat_rate_policy.md` for full rationale:

- Heat rates change <1%/year (physical properties)
- Fuel prices change 10-30%/year (market dynamics)
- Heat rate drift contributes <3% of LMP error budget
- EIA-923 data exists but matching infrastructure would take 1-2
  weeks to build with minimal accuracy improvement

This is now an explicit documented decision, not inertia.


## What Is Now Validated vs. Documented-Limited

### Validated

| Aspect | Evidence |
|--------|----------|
| Kron reduction arithmetic | Exact match (10⁻¹² degrees) |
| Multi-bus import distribution | Interface flows within 2.8% |
| Bus-level spatial LMP patterns | Correct direction (downstate > upstate) |
| Year-specific import costs | Path B implemented, regression tested |
| Mid-year retirement logic | IP2 exclusion verified |
| Heat rate policy | Explicit Decision A documented |

### Documented-Limited

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Hourly LMP correlation 0.23-0.51 | Structural: cost-based ≠ market | None practical |
| 2.0x Kron scale factor | May be over-conservative now | Review in Phase B |
| Pmax at 2019 p95, not declared | Limits import flexibility | Requires Path B (done) |
| No zonal reserves | Understates downstate LMPs | Phase B |
| No BESS | Growing post-2022 | Phase B |


## Phase B Items (Out of Scope)

1. **Zonal reserve requirements** (SENY 1,200 MW + NYC 300 MW)
2. **Kron scale factor reduction** (from 2.0x to ~1.2x)
3. **Topology updates** (CHPE, Clean Path, Smart Path)
4. **Multi-bus import refinement** (add smaller entry points)
5. **BESS modeling** (Egret storage dict population)
6. **Pmax update to declared capability** (now safe with Path B)


## File Inventory

### New experiments
- `experiments/kron_fidelity/run.py` + `report.md`
- `experiments/per_bus_lmp_validation/run.py` + `report.md`
- `experiments/path_b_validation/report.md`
- `experiments/regression/test_path_b_costs.py`

### Modified source
- `Vatic/vatic/data/nyiso_loader.py` — multi-bus imports + Path B
- `Vatic/vatic/data/nyiso_fleet_updater.py` — mid-year retirements
- `third_party/NYgrid/nygrid_kron_reduced.json` — corrected impedances

### New documentation
- `docs/grid_model_validation_phase_a.md` (this file)
- `docs/path_b_import_pricing.md`
- `docs/heat_rate_policy.md`
- `docs/nygrid_to_nyiso_node_mapping.md`

### Updated documentation
- `docs/known_limitations.md` — items 2, 5, 6 updated
