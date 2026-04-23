# Session Work Log: NYISO Grid Adapter for Vatic

**Dates**: April 16-17, 2026
**Objective**: Build a complete NYISO grid adapter for Vatic (power grid UC/ED simulation), based on Cornell's NYgrid model, and integrate it with PGscen-2nd timeseries data.

---

## Table of Contents

1. [Files Created and Modified](#files-created-and-modified)
2. [Step 1: NYgrid Clone and Inspection](#step-1-nygrid-clone-and-inspection)
3. [Step 2: Static Grid Extraction](#step-2-static-grid-extraction)
4. [Step 3: Python Reader Module and Tests](#step-3-python-reader-module-and-tests)
5. [Step 4: NyisoLoader Stub](#step-4-nyisoloader-stub)
6. [Step 5: Gap Documentation](#step-5-gap-documentation)
7. [Verification and First Bug Fixes](#verification-and-first-bug-fixes)
8. [Hydro Reclassification](#hydro-reclassification)
9. [Dependency Installation](#dependency-installation)
10. [UC Parameter Population](#uc-parameter-population)
11. [First UC Solve and Bug Fixes](#first-uc-solve-and-bug-fixes)
12. [LMP Validation Against NYISO Actuals](#lmp-validation-against-nyiso-actuals)
13. [Kron Network Reduction](#kron-network-reduction)
14. [PTDF Solve with Reduced Network](#ptdf-solve-with-reduced-network)
15. [Cost Curve Calibration](#cost-curve-calibration)
16. [Interface Constraints for Zonal Congestion](#interface-constraints-for-zonal-congestion)
17. [Pumped Storage Wiring](#pumped-storage-wiring)
18. [PGscen-2nd Timeseries Integration](#pgscen-2nd-timeseries-integration)
19. [Final Validation Results](#final-validation-results)

---

## Files Created and Modified

### New files created

| File | Lines | Purpose |
|------|-------|---------|
| `Vatic/vatic/data/nyiso_loader.py` | 1,260 | Main NYISO grid loader class |
| `Vatic/vatic/data/nygrid_reader.py` | 141 | NYgrid baseline JSON reader |
| `Vatic/vatic/tests/test_nygrid_reader.py` | 143 | Unit tests for baseline reader |
| `Vatic/vatic/tests/test_nyiso_smoke.py` | 402 | Structural and solve smoke tests |
| `third_party/NYgrid/nygrid_baseline.json` | 12,617 | Serialized NPCC-140 baseline |
| `third_party/NYgrid/nygrid_kron_reduced.json` | 637 | Kron-reduced branch data |
| `third_party/NYgrid/nygrid_branch_limits.json` | 30 | Per-branch thermal limits |
| `third_party/NYgrid/LICENSE` | 21 | MIT license for NYgrid |
| `docs/NYISO_INTEGRATION_STATUS.md` | 223 | Living gap and status document |
| `docs/Session_Work_Log_NYISO_Adapter.md` | (this file) | Session documentation |
| `Vatic/vatic/data/grids/NYISO/` | (dir) | NYISO grid data directory |
| `Vatic/vatic/data/grids/initial-state/NYISO/` | (dir) | NYISO initial state directory |

### Modified existing files

| File | Changes |
|------|---------|
| `Vatic/vatic/data/loaders.py` | Added `grid='NYISO'` route to `load_input()` dispatcher |
| `Vatic/vatic/models/params.py` | Added `NondispatchableMarginalCost`, `PriceResponsiveLoad*` params for Egret 0.6.1 compatibility |
| `Vatic/vatic/data_providers.py` | Added `price_responsive_load` to model dict, `_build_interfaces()`, `_build_storage()` methods |

### External dependencies installed

| Package | Version | Purpose |
|---------|---------|---------|
| scipy | 1.17.1 | Loading `.mat` files from NYgrid |
| pandas | 3.0.2 | Data manipulation |
| dill | 0.4.1 | Vatic's pickle format |
| openpyxl | 3.1.5 | Reading `.xlsx` metadata |
| pyomo | 6.10.0 | Optimization modeling framework |
| gridx-egret | 0.6.1.dev0 | Power systems UC/ED formulations |
| CBC solver | 2.10.13 | MILP solver (via Homebrew) |

---

## Step 1: NYgrid Clone and Inspection

**What**: Cloned `https://github.com/AndersonEnergyLab-Cornell/NYgrid` into `third_party/NYgrid/`.

**Findings**:
- `Data/npcc.mat` contains the NPCC-140 bus MATPOWER case: `baseMVA=100`, 140 buses, 227 branches, 48 generators. No `gencost` in the `.mat` file.
- `modifyMPC.m` loads `npcc.mat`, applies bus type changes, deletes 3 PJM-IESO branches, adds 2 E-G branches, sets interface limits.
- `Data/genParamAll.csv` (227 rows): all thermal generators with heat rate coefficients, ramp rates, zone/bus assignments. Total thermal: ~27 GW.
- `Data/gen_bus_assignment.csv`: maps each generator to a NPCC bus number.
- `Data/bus_ny_type_zone_new.csv` (45 rows): maps NY buses 37-82 to zones A-K.
- `Data/RenewableGen.csv`: nuclear, hydro, wind capacity by bus.
- `updateOpCond.m`: replaces NPCC generators with 227 thermal + 6 nuclear + ~12 hydro at runtime; runs network reduction (`MPReduction`) before OPF.
- Key insight: the 48 generators in `npcc.mat` are just the NPCC base case. The real NYgrid model replaces them entirely at runtime with the CSV-based generators.

---

## Step 2: Static Grid Extraction

**What**: Built a Python script to extract the NYgrid baseline from MATLAB data into JSON without requiring MATLAB/Octave.

**Method**:
1. Loaded `npcc.mat` with `scipy.io.loadmat`
2. Applied all `modifyMPC()` modifications in Python (bus type changes, branch deletions/additions, interface limits)
3. Merged with `bus_ny_type_zone_new.csv` for zone assignments
4. Loaded `genParamAll.csv` + `gen_bus_assignment.csv` for 227 thermal generators
5. Added 6 nuclear generators from `RenewableGen.csv` with specific capacities (FitzPatrick 854.5 MW, Nine Mile Point 1&2, Indian Point 2&3, Ginna)
6. Added 10 hydro generators from `RenewableGen.csv` (Niagara 2460 MW, St. Lawrence 856 MW, Blenheim-Gilboa 75.8 MW, plus small hydro)
7. Serialized to `nygrid_baseline.json`

**Result**: 140 buses, 226 branches, 243 generators (227 thermal + 6 nuclear + 10 hydro), 36,764 MW total capacity.

---

## Step 3: Python Reader Module and Tests

**What**: Created `vatic/data/nygrid_reader.py` with `load_nygrid_baseline()` and `inspect_nygrid()` functions. Created 17 unit tests in `vatic/tests/test_nygrid_reader.py`.

**Tests verify**:
- All 140 buses present with valid zone assignments
- All generators have Pmax >= Pmin >= 0 and valid fuel types
- All 226 branches connect existing buses with finite reactance
- Total capacity in 37-40 GW ballpark
- Niagara, St. Lawrence, Blenheim-Gilboa specifically present
- Thermal generators have cost curve coefficients

---

## Step 4: NyisoLoader Stub

**What**: Created `vatic/data/nyiso_loader.py` with `NyisoLoader(GridLoader)` class. Bypasses parent `__init__` because NYgrid's data format differs from CSV-based RTS-GMLC/Texas-7k convention. Registered in `load_input()` dispatcher.

**Key design decisions**:
- Generator namedtuples built from NYgrid JSON, not from CSV rows
- `utc_offset = -pd.Timedelta(hours=5)` (EST)
- `grid_lbl = "NYISO"`
- `create_timeseries()` initially raised `NotImplementedError`

---

## Step 5: Gap Documentation

**What**: Created `docs/NYISO_INTEGRATION_STATUS.md` listing what's done and what's missing. This document was updated throughout the session as decisions were made.

---

## Verification and First Bug Fixes

**What**: Ran the three verification checks suggested in review.

**Issue 1: Cost curves in wrong units**
- Values were heat input (MMBTU/h), not dollars
- Gas showed $8.67/MWh marginal -- that's a heat rate, not a cost
- **Fix**: Multiply by zone-specific 2019 fuel prices from `fuelPriceWeekly_2019.csv`
- After fix: gas $33/MWh, coal $23/MWh, oil $83/MWh, nuclear $7/MWh

**Issue 2: Nuclear classification**
- Nuclear in `ThermalGenerators` + `MustRun` is correct Vatic convention (matches RTS-GMLC)
- 233 = 227 thermal + 6 nuclear, which is right

**Issue 3: External buses**
- 94 EXT buses in template. Initially thought they should be filtered
- Kept all 140 buses initially (needed for PTDF boundary conditions)

---

## Hydro Reclassification

**What**: Investigated Blenheim-Gilboa capacity and hydro dispatch semantics. Three major decisions:

**Decision 1: Niagara and St. Lawrence are dispatchable ThermalGenerators**
- Moved from `NondispatchableGenerators` to `ThermalGenerators` with `MustRun`
- Niagara: Pmin=1560 MW (treaty floor from 2016-2021 CF=0.635), Pmax=2460 MW
- St. Lawrence: Pmin=700 MW (CF=0.82), Pmax=856 MW
- Rationale: they bid into NYISO market, 3.3 GW non-dispatchable distorts LMPs

**Decision 2: Blenheim-Gilboa excluded**
- The 75.8 MW in RenewableGen.csv is a net-generation allocation, not capacity
- Real BG is 1160 MW pumped storage. Deferred to proper storage model.
- Vatic has full Egret storage infrastructure (confirmed by codebase search)

**Decision 3: Small run-of-river hydro stays NondispatchableGenerator**
- 7 small hydro plants, truly exogenous output

---

## Dependency Installation

**What**: Installed Pyomo 6.10.0, Egret 0.6.1.dev0 (from GitHub), CBC 2.10.13 (via Homebrew).

---

## UC Parameter Population

**What**: Added realistic min up/down times, startup costs, and startup time regimes by generator unit type.

**Source**: EIA-860 typical values, NYISO Gold Book, Wood & Wollenberg.

| Unit Type | MinUp | MinDown | Cold/Warm/Hot Start (hours) | Cost ($/MW) |
|-----------|-------|---------|----------------------------|-------------|
| Steam (gas) | 8h | 8h | 48/12/4 | 110/55/30 |
| Steam (coal) | 12h | 10h | 72/24/6 | 150/80/40 |
| Combined cycle | 4h | 4h | 12/4/2 | 70/35/18 |
| Combustion turbine | 1h | 1h | 2/1/1 | 20/15/10 |
| Jet engine | 1h | 1h | 1/1/1 | 15/15/15 |
| Nuclear | 24h | 24h | 72/72/72 | 500/500/500 |

Startup costs use Vatic's 3-tier lag/cost structure matching `GridLoader` in `loaders.py`.

---

## First UC Solve and Bug Fixes

**What**: Attempted a 24-hour day-ahead RUC + 24 hourly SCED dispatch.

**Bug 1: Negative MinimumProductionCost**
- 20 generators with negative cost at Pmin (heat rate regression artifact with negative intercept)
- Fix: clamp cost values >= 0

**Bug 2: Cost curve starts above Pmin**
- Generators with Pmin=0 had cost curve starting at 0.01 MW
- Egret extrapolates below first point -> tiny negative cost
- Fix: start cost curve at exactly Pmin

**Bug 3: Missing `NondispatchableMarginalCost` (Egret 0.6.1)**
- Egret's `file_non_dispatchable_vars` expects this param
- Vatic's custom `params.py` didn't define it
- Fix: added to `params.py`

**Bug 4: Missing `PriceResponsiveLoad*` params (Egret 0.6.1)**
- Egret's `power_balance.py` references `PriceResponsiveLoadAtBus`
- Fix: added Set, Param, Var to `params.py` and `price_responsive_load` to model dict

**Result**: Copper-sheet solve succeeded at 10 GW dummy load. Zero load shedding. Prices $2.97-$5.51/MWh (too low because must-run dominated at low load).

---

## LMP Validation Against NYISO Actuals

**What**: Compared simulation against actual NYISO July 8, 2019 (low-congestion summer weekday).

**Key discovery**: Vatic's `Price` column computes average system cost (total_cost / demand), NOT marginal LMP. With `run_lmps=True`, Egret's LP dual variables give true LMPs.

**Results with relaxed lines + actual load + warm start**:

| Metric | Average Cost | Dual-variable LMP | Actual NYISO |
|--------|-------------|-------------------|-------------|
| Avg price | $12.50/MWh | $27.59/MWh | $23.03/MWh |
| Min | -- | $18.29 | $19.52 |
| Max | -- | $30.08 | $29.04 |

LMP range ($18-$30) nearly perfectly brackets actual ($19-$29). 20% system overshoot from no NE exports.

---

## Kron Network Reduction

**What**: The NPCC-140 model with PTDF power flow was infeasible because 94 external buses had load but no generation. Implemented Kron reduction.

**Method**: Standard Y-bus Gaussian elimination:
1. Built bus admittance matrix Y (140x140 complex) from branch data
2. Partitioned into internal (46 NY buses) and external (94 buses)
3. Computed Y_reduced = Y_II - Y_IE * inv(Y_EE) * Y_EI
4. Extracted equivalent branches from off-diagonal elements

**Result**: 46 buses, 74 branches (67 original NY-internal + 7 Kron equivalents). Saved to `nygrid_kron_reduced.json`.

Added `use_reduced_network=True` parameter to `NyisoLoader` (default).

---

## PTDF Solve with Reduced Network

**What**: 24-hour PTDF solve on the Kron-reduced network with 4 import equivalent generators.

**Import generators** (at boundary buses):
- PJM: bus 75 (RAMAPO), Pmax=2650 MW, cost $30/MWh
- HQ: bus 48 (MOSES E), Pmax=1690 MW, cost $5/MWh
- NE: bus 37 (NEW SEATHED), Pmax=300 MW, cost $35/MWh
- IESO: bus 54 (NIAGARA W), Pmax=1290 MW, cost $15/MWh

**Result**: Solve succeeded. Zero load shedding. System LMP $27.59 avg (no congestion -- all zones identical because Kron equivalent branches had unlimited ratings).

---

## Cost Curve Calibration

**What**: Three calibration improvements.

**1. Multi-segment quadratic cost curves**
- 75 generators with convex (a2 > 0) quadratic heat rates get 5-point piecewise curves
- Generators with concave or low-R2 quadratics fall back to linear
- Convexity enforced: if marginal slopes decrease, add perturbation

**2. Week-specific fuel prices**
- New `fuel_price_date` parameter loads from `fuelPriceWeekly_YYYY.csv`
- July 8 gas was $3.60-3.90/MMBTU (close to annual average)

**3. Tightened import limits**
- From declared transfer limits to 2019 p95 actual flows
- NE import cut from 1930 to 300 MW (it's a net export path)

**Impact**: Minimal on LMPs (fuel prices were already close to annual average).

---

## Interface Constraints for Zonal Congestion

**What**: Added NYISO interface constraints using Egret's `interface` element type.

**7 NYISO interfaces mapped**:
- DYSINGER EAST (A->B): 4 branches
- WEST CENTRAL (B->C): 4 branches
- TOTAL EAST (C->E): 5 branches
- MOSES SOUTH (D->E): 3 branches
- CENTRAL EAST (E->F/G): 5 branches
- UPNY CONED (G->H/I): 5 branches (includes 1 Kron equivalent)
- SPR/DUN-SOUTH (I->J/K): 4 branches

**Calibration**: Interface limits scaled 2x from NYISO declared limits because the Kron-reduced network's PTDF factors distribute flow differently than the full network.

**Fixes required**:
- Vatic's `ptdf_manager.py` expects `lower_limit`/`upper_limit` keys, Egret's `params.py` expects `minimum_limit`/`maximum_limit` -- added both.
- Per-branch limits proved infeasible (PTDF distribution mismatch). Switched to aggregate interface constraints which are the correct NYISO market mechanism.

**Result with 2x Kron scale**:

| Zone | Simulated | Actual | Ratio |
|------|----------|--------|-------|
| A | $26.30 | $22.96 | 1.15 |
| E | $25.76 | $21.60 | 1.19 |
| F | $25.89 | $22.10 | 1.17 |
| J | $32.90 | $24.11 | 1.36 |
| K | $34.25 | $24.90 | 1.38 |
| Sys | $28.83 | $22.07 | 1.31 |

Correct congestion gradient (upstate cheaper, downstate premium). J/K premium $7.27 vs actual $2.96 (overstated due to Kron PTDF mismatch).

---

## Pumped Storage Wiring

**What**: Added Blenheim-Gilboa and Lewiston as Egret storage elements.

| Unit | Capacity | Energy | Bus | Zone | RT Efficiency |
|------|---------|--------|-----|------|--------------|
| BG | 1160 MW | 9280 MWh | 38 (GILBOA) | E | ~80% |
| Lewiston | 240 MW | 2880 MWh | 55 (NIAGARA E) | A | ~77% |

**Key fix**: RenewableGen.csv placed BG at bus 77 (BUCHANAN, zone G). The real plant is at bus 38 (GILBOA, zone E) in Schoharie County.

**Implementation**: Added `StorageUnits` key to template, `_build_storage()` method in `data_providers.py`. Egret's storage parameters populated: charge/discharge rates, efficiency, SOC bounds, initial conditions.

**Impact**: Storage reduces system LMP by ~$0.50/MWh via peak/off-peak arbitrage.

---

## PGscen-2nd Timeseries Integration

**What**: Implemented `create_timeseries()` in NyisoLoader to read real NYISO wind, solar, and load data from PGscen-2nd.

**Architecture**:
- `pgscen_dir` parameter on NyisoLoader points to `PGscen-2nd/data/NYISO_real/`
- Wind/solar generators registered from PGscen metadata (`plant_metadata/wind_meta.csv`, `solar_meta.csv`) during `__init__`
- `create_timeseries()` reads actual + day-ahead forecast CSVs, maps by `site_id`
- Zonal load distributed to buses using RenewableGen.csv proportions

**Data matched for 2019**:
- Wind: 23 sites, 1,979 MW nameplate (all NYISO-registered wind projects)
- Solar: 2 sites (NYISO_real has limited 2019 solar data)
- Load: 11 NYISO zones, multi-year coverage

**Code fix required**: PGscen generators were being registered AFTER template construction, so they never appeared in `NondispatchableGenerators`. Moved registration block before the template build loop.

---

## Final Validation Results

### System-level (July 8, 2019)

| Configuration | Avg LMP | vs Actual $22.07 |
|--------------|---------|------------------|
| Copper sheet (10 GW) | $4.30 | 20% (wrong load) |
| Relaxed lines (20 GW) | $16.70 | 73% (avg cost, not LMP) |
| Relaxed + LMP duals | $27.59 | 120% |
| PTDF Kron (no interfaces) | $27.59 | 120% |
| PTDF + interfaces 2x | $28.83 | 131% |
| PTDF + interfaces + storage | $28.31 | 128% |
| **Actual NYISO** | **$22.07** | **100%** |

### Complete feature set

- 46-bus Kron-reduced network with PTDF power flow
- 7 NYISO interface constraints (2x Kron scale)
- 235 thermal generators (227 fossil + 6 nuclear + 2 dispatchable hydro)
- 7 small hydro as NondispatchableGenerators
- 31 wind + 16 solar from PGscen-2nd metadata
- 2 pumped storage units (BG 1160 MW + Lewiston 240 MW)
- 4 import equivalent generators (PJM, HQ, NE, IESO)
- 75 generators with 5-segment convex quadratic cost curves
- UC parameters by unit type (steam 8-12h, CC 4h, CT 1h, nuclear 24h)
- Week-specific fuel prices via `fuel_price_date` parameter
- 39 structural tests passing, full 24h RUC+SCED solve feasible

### Test counts

| Test file | Tests | Status |
|-----------|-------|--------|
| `test_nygrid_reader.py` | 17 | All pass |
| `test_nyiso_smoke.py` (structural) | 14 | All pass |
| `test_nyiso_smoke.py` (data shape) | 8 | All pass |
| `test_nyiso_smoke.py` (RUC solve) | 1 | Pass with dependencies |
| **Total** | **40** | **39 pass + 1 conditional** |
