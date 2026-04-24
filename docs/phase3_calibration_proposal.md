# Phase 3 — Calibration Proposal

> Based on the capacity diagnostic (Step 1), reserve audit (Step 2),
> and external import audit (Step 3). To be reviewed before any
> parameters are changed.

## Diagnosis summary

**The dominant failure mode is COLD-START ENERGY INFEASIBILITY.**

All observed load shedding in Phase 2 (2020: 77 MWh, 2022: 4,210 MWh,
2023: 2,298 MWh) occurs exclusively at hour 0 of day 1 — the first
SCED of the simulation. The RUC commits generators that have startup
ramp constraints: at H00 they produce only their minimum power (total
committed Pmax = 12,971 MW in 2022), but by H01 the same units have
ramped up (Pmax = 16,801 MW) and shedding drops to zero. Days 2 and 3
(warm start) have zero shedding even at the same clock hour.

**Neither reserves nor import limits are the binding constraint.**
- Reserve requirement (5% of load = 700–975 MW) is well below NYISO's
  actual 2,620 MW. Under-reserving, not over-reserving.
- No transmission lines reach 90% of limit at the worst hour.
- External import Pmax varies by year but is not systematically
  undersized relative to actual flows.

## Proposed changes (in priority order)

### Change 1: Always use a warmup day (CRITICAL)

**What**: Every simulation must be preceded by a warmup day whose
results are discarded. The warmup day's final generator states
(`last_conditions_file`) seed the target day's initial conditions.

**Where**: This is an operational requirement, not a code change. The
experiment runner already supports warmup days (experiment 001 uses
them). Phase 2's cross-year validation deliberately omitted warmup to
test raw robustness — and found it doesn't work without warmup.

**Expected impact**: Eliminates all H00 load shedding. Based on 2022
day-2/day-3 behavior (zero shedding at the same demand levels), adding
a warmup day should reduce total shedding from 4,210 MWh to ~0 MWh.

**Risk**: None. The warmup day is excluded from analysis. This is
standard practice in production unit commitment simulators.

**Validation plan**: Re-run each Phase 2 year with a warmup day
prepended (Sep 21→22–24 for 2020, Sep 19→20–22 for 2022,
Sep 18→19–21 for 2023). Confirm H00 shedding drops to <10 MWh.

### Change 2: Year-specific external import limits (RECOMMENDED)

**What**: Replace the fixed 2019 p95 import Pmax values with
year-specific values computed from NYISO's published interface flow
data for the simulation year.

**Parameters to change** (in `_EXTERNAL_EQUIVALENTS` or a year-indexed
lookup):

| Interface | Current (2019 p95) | 2020 p95 | 2022 p95 | 2023 p95 |
|-----------|-------------------|----------|----------|----------|
| PJM_import | 2,650 MW | 1,681 MW | 1,958 MW | 2,756 MW |
| HQ_import | 1,690 MW | 2,698 MW | 2,890 MW | 693 MW |
| NE_import | 300 MW | 0 MW | 554 MW | 664 MW |
| IESO_import | 1,290 MW | 995 MW | 1,396 MW | 260 MW |

**Implementation**: Add a method to `NyisoLoader.__init__` that reads
interface flow data from the cache and computes p95 import values for
the simulation year, overriding `_EXTERNAL_EQUIVALENTS` defaults.

**Expected impact**: Changes dispatch of external equivalents at
high-import hours. Most significant for HQ in 2022 (+1,200 MW vs
current) and HQ/IESO in 2023 (-997/-1,030 MW vs current). This won't
fix cold-start shedding but will improve LMP accuracy at hours when
imports are binding.

**Risk**: HQ import limit increase in 2022 would provide more cheap
capacity ($5/MWh), which could lower the model's 2022 average LMP
below the current $70.76 — potentially worsening the excellent -1.3%
match against NYISO's $71.66. Need to verify.

**Validation plan**: Re-run 2022 with updated HQ limit and compare
LMPs. If the match degrades beyond 15%, investigate whether the cost
parameter for HQ imports ($5/MWh) needs adjustment.

### Change 3: Fixed-MW reserve requirement (DEFERRED)

**What**: Replace `reserve_factor=0.05` (load-proportional) with a
fixed 2,620 MW system-wide operating reserve requirement matching
NYISO's actual level.

**Why deferred**: The current 5%-of-load reserve is actually *lower*
than NYISO's actual requirement at the load levels we're simulating.
Increasing it would make the system tighter and could increase shedding
(though only on the cold-start hour). This change is correct for
realism but should be applied AFTER Change 1 (warmup) eliminates the
cold-start problem.

**Parameters to change**:
- `reserve_factor`: set to 0 (disable load-proportional)
- Add fixed MW reserve: set
  `reserve_requirement['values'][t] = 2620.0` for all t
- Or compute as: max(1310, largest_online_unit_Pmax) for 10-min,
  doubled for 30-min

**Expected impact**: At 15,000 MW load, reserve goes from 750 MW to
2,620 MW (+1,870 MW). This would commit more units for headroom,
slightly increasing startup costs and potentially LMPs. More realistic.

**Risk**: Without warmup, this would worsen H00 shedding. With warmup,
it should be fine — the RUC will commit more units but still have
adequate capacity.

**Validation plan**: Apply after Change 1. Re-run Phase 2 years and
confirm shedding remains <10 MWh while reserve shortfall drops to ~0.

### Change 4: Zonal reserve requirements (FUTURE)

**What**: Add SENY (zones G–K) and NYC (zone J) locational reserve
constraints matching NYISO's ancillary service requirements (~1,200 MW
SENY, ~300 MW NYC).

**Why future**: Requires Vatic to support zonal reserve formulations.
The current Egret model has `EnforceZonalSpinningReserveRequirement`
constraints available but they are not populated by any loader. This
needs investigation of the Egret API.

**Expected impact**: Would increase LMPs in downstate zones (J, K)
by forcing local reserves, improving spatial price accuracy.

## Sequencing

1. **Immediate**: Apply Change 1 (warmup). Re-run Phase 2 validation.
   Expected: shedding → ~0, LMPs unchanged.
2. **Next**: Apply Change 2 (year-specific imports). Re-run Phase 2.
   Expected: modest LMP adjustments, especially for 2022 HQ.
3. **After Phase 5**: Apply Change 3 (fixed-MW reserve). Re-run.
   Expected: more realistic reserves, slight cost increase.
4. **Future work**: Investigate Change 4 (zonal reserves) for spatial
   price accuracy.

## What not to change

- **Load shedding penalty** ($10,000/MWh): Appropriate as an economic
  penalty for involuntary curtailment.
- **Reserve shortfall penalty** ($1,000/MWh): Appropriate relative to
  the load shedding penalty (10:1 ratio ensures load service priority).
- **Transmission limits**: No lines were binding. The Kron reduction
  appears adequate.
- **Generator cost curves**: The 2022 LMP match (-1.3%) suggests fuel
  price → cost curve → LMP pipeline is working correctly. Do not
  adjust heat rates or startup costs without new evidence.
