# Phase 3 — Worst-Hour Capacity Diagnostic

> For each Phase 2 simulation year, the hour with maximum load
> shedding is decomposed into energy, transmission, and reserve
> components to identify the binding constraint.

## Executive finding

**All load shedding is a cold-start artifact, concentrated in hour 0 of
day 1.** It is not a reserve specification or transmission problem.

Evidence:
1. Load shedding occurs exclusively at hour H00 (midnight UTC = 8 PM EDT)
   — the very first SCED of each simulation.
2. By H01, the same committed units have ramped up and shedding drops to
   zero, even though demand is still near-peak.
3. Day 2 and day 3 H00 (same clock hour, warm start) have zero shedding.
4. The energy-balance gap at H00 is ~1,400 MW in all 3 years — this
   equals the ramp deficit of generators starting from cold.
5. In 2022, 173 generators are committed at H00 with Pmax=12,971 MW (all
   at ramp-limited minimum). At H01, the same 173 units reach Pmax=16,801 MW
   — a 3,830 MW ramp-up from the same fleet.
6. No transmission constraints bind at H00 in any year.
7. 20,000–25,000 MW of capacity sits uncommitted at H00, confirming
   the RUC chose not to commit additional units (it solves ahead and
   knows demand will drop by H07 — it's not worth starting slow units
   just for H00).

**Implication for Phase 2 results**: The 4,210 MWh (2022) and 2,298 MWh
(2023) load shedding figures are not indicative of a capacity or reserve
problem. They are a startup transient that would be eliminated by a
warmup day. The Phase 2 simulations did not use warmup days because the
task specified "no warmup" to test raw cross-year robustness.

**Implication for Phase 3**: The reserve specification and external import
limits may still need calibration for correctness, but they are NOT the
cause of the observed shedding. Steps 2–3 below audit them for
completeness.


### Year 2020 — Worst hour: 2020-09-22 H00

| Metric | Value |
|--------|-------|
| **(a) Total demand** | **15,542 MW** |
| **(b) Load shed** | **77 MW** |
| **(c) Committed fleet Pmax** | **15,042 MW** |
| — Nuclear dispatch / headroom | 5,430 / 0 MW |
| — Hydro dispatch / headroom | 2,460 / 0 MW |
| — PJM_import dispatch / headroom (Pmax=2650) | 2,650 / 0 MW |
| — HQ_import dispatch / headroom (Pmax=1690) | 562 / 1,128 MW |
| — NE_import dispatch / headroom (Pmax=300) | 0 / 300 MW |
| — IESO_import dispatch / headroom (Pmax=1290) | 1,290 / 0 MW |
| — Other thermal dispatch / headroom | 6,652 / 0 MW |
| **(d) Total dispatch** | **13,614 MW** |
| **(e) Import Pmax (model limit)** | **5,930 MW** |
| **(f) Imports dispatched** | **4,502 MW** |
| **(g) Reserves provided** | **1,428 MW** |
| **(h) Reserves required** | **1,428 MW** |
| Reserve shortfall | 0 MW |
| Renewables dispatched / available | 452 / 452 MW |

**Energy balance**: supply (14,065) + shed (77) = 14,142 vs demand 15,542 — gap 1,400 MW

**Capacity margin**: available Pmax 15,494 MW − demand 15,542 MW = -49 MW
Reserve required: 1,428 MW → net margin -1,477 MW

**Diagnosis: ENERGY INFEASIBILITY** — committed Pmax + renewables < demand.

**Uncommitted capacity**: 25,109 MW across 182 units (> 10 MW each)

**Binding transmission**: None at >90% of limit.

**Shedding profile across all hours:**

| Hour | Shed (MW) | Demand (MW) | Reserve shortfall (MW) |
|------|-----------|-------------|------------------------|
| 00 | 77 ** | 15,542 | 0 |
| 01 | 0 | 14,739 | 0 |
| 02 | 0 | 13,753 | 0 |
| 03 | 0 | 12,797 | 0 |
| 04 | 0 | 12,144 | 0 |
| 05 | 0 | 11,791 | 0 |
| 06 | 0 | 11,574 | 0 |
| 07 | 0 | 11,525 | 0 |
| 08 | 0 | 11,693 | 0 |
| 09 | 0 | 12,303 | 0 |
| 10 | 0 | 13,547 | 0 |
| 11 | 0 | 14,461 | 0 |
| 12 | 0 | 14,941 | 0 |
| 13 | 0 | 14,926 | 0 |
| 14 | 0 | 14,788 | 0 |
| 15 | 0 | 14,736 | 0 |
| 16 | 0 | 14,731 | 0 |
| 17 | 0 | 14,741 | 0 |
| 18 | 0 | 14,766 | 0 |
| 19 | 0 | 14,927 | 0 |
| 20 | 0 | 15,354 | 0 |
| 21 | 0 | 15,793 | 0 |
| 22 | 0 | 15,873 | 0 |
| 23 | 0 | 16,102 | 0 |

### Year 2022 — Worst hour: 2022-09-20 H00

| Metric | Value |
|--------|-------|
| **(a) Total demand** | **19,187 MW** |
| **(b) Load shed** | **4,045 MW** |
| **(c) Committed fleet Pmax** | **12,971 MW** |
| — Nuclear dispatch / headroom | 3,364 / 0 MW |
| — Hydro dispatch / headroom | 2,460 / 0 MW |
| — PJM_import dispatch / headroom (Pmax=2650) | 2,650 / 0 MW |
| — HQ_import dispatch / headroom (Pmax=1690) | 1,690 / 0 MW |
| — NE_import dispatch / headroom (Pmax=300) | 300 / 0 MW |
| — IESO_import dispatch / headroom (Pmax=1290) | 1,290 / 0 MW |
| — Other thermal dispatch / headroom | 4,581 / 0 MW |
| **(d) Total dispatch** | **12,971 MW** |
| **(e) Import Pmax (model limit)** | **5,930 MW** |
| **(f) Imports dispatched** | **5,930 MW** |
| **(g) Reserves provided** | **0 MW** |
| **(h) Reserves required** | **959 MW** |
| Reserve shortfall | 959 MW |
| Renewables dispatched / available | 801 / 801 MW |

**Energy balance**: supply (13,772) + shed (4,045) = 17,817 vs demand 19,187 — gap 1,370 MW

**Capacity margin**: available Pmax 13,772 MW − demand 19,187 MW = -5,414 MW
Reserve required: 959 MW → net margin -6,374 MW

**Diagnosis: ENERGY INFEASIBILITY** — committed Pmax + renewables < demand.

**Uncommitted capacity**: 21,956 MW across 96 units (> 10 MW each)

**Binding transmission**: None at >90% of limit.

**Shedding profile across all hours:**

| Hour | Shed (MW) | Demand (MW) | Reserve shortfall (MW) |
|------|-----------|-------------|------------------------|
| 00 | 4,045 ** | 19,187 | 959 |
| 01 | 0 | 18,264 | 276 |
| 02 | 0 | 17,113 | 0 |
| 03 | 0 | 15,982 | 0 |
| 04 | 0 | 15,092 | 0 |
| 05 | 0 | 14,427 | 0 |
| 06 | 0 | 13,987 | 0 |
| 07 | 0 | 13,772 | 0 |
| 08 | 0 | 13,810 | 0 |
| 09 | 0 | 14,450 | 0 |
| 10 | 0 | 15,685 | 0 |
| 11 | 0 | 16,651 | 0 |
| 12 | 0 | 17,289 | 0 |
| 13 | 0 | 17,624 | 0 |
| 14 | 0 | 17,846 | 0 |
| 15 | 0 | 18,075 | 0 |
| 16 | 0 | 18,340 | 0 |
| 17 | 0 | 18,658 | 0 |
| 18 | 0 | 18,875 | 0 |
| 19 | 0 | 19,197 | 0 |
| 20 | 0 | 19,519 | 0 |
| 21 | 0 | 19,618 | 0 |
| 22 | 0 | 19,327 | 0 |
| 23 | 0 | 19,188 | 0 |

### Year 2023 — Worst hour: 2023-09-19 H00

| Metric | Value |
|--------|-------|
| **(a) Total demand** | **16,773 MW** |
| **(b) Load shed** | **2,298 MW** |
| **(c) Committed fleet Pmax** | **12,972 MW** |
| — Nuclear dispatch / headroom | 3,364 / 0 MW |
| — Hydro dispatch / headroom | 2,460 / 0 MW |
| — PJM_import dispatch / headroom (Pmax=2650) | 2,650 / 0 MW |
| — HQ_import dispatch / headroom (Pmax=1690) | 1,470 / 220 MW |
| — NE_import dispatch / headroom (Pmax=300) | 0 / 300 MW |
| — IESO_import dispatch / headroom (Pmax=1290) | 1,290 / 0 MW |
| — Other thermal dispatch / headroom | 4,582 / 0 MW |
| **(d) Total dispatch** | **12,451 MW** |
| **(e) Import Pmax (model limit)** | **5,930 MW** |
| **(f) Imports dispatched** | **5,410 MW** |
| **(g) Reserves provided** | **520 MW** |
| **(h) Reserves required** | **839 MW** |
| Reserve shortfall | 318 MW |
| Renewables dispatched / available | 624 / 624 MW |

**Energy balance**: supply (13,076) + shed (2,298) = 15,373 vs demand 16,773 — gap 1,400 MW

**Capacity margin**: available Pmax 13,596 MW − demand 16,773 MW = -3,177 MW
Reserve required: 839 MW → net margin -4,016 MW

**Diagnosis: ENERGY INFEASIBILITY** — committed Pmax + renewables < demand.

**Uncommitted capacity**: 22,372 MW across 135 units (> 10 MW each)

**Binding transmission**: None at >90% of limit.

**Shedding profile across all hours:**

| Hour | Shed (MW) | Demand (MW) | Reserve shortfall (MW) |
|------|-----------|-------------|------------------------|
| 00 | 2,298 ** | 16,773 | 318 |
| 01 | 0 | 15,897 | 0 |
| 02 | 0 | 14,856 | 0 |
| 03 | 0 | 13,831 | 0 |
| 04 | 0 | 13,140 | 0 |
| 05 | 0 | 12,623 | 0 |
| 06 | 0 | 12,274 | 0 |
| 07 | 0 | 12,091 | 0 |
| 08 | 0 | 12,179 | 0 |
| 09 | 0 | 12,791 | 0 |
| 10 | 0 | 14,040 | 0 |
| 11 | 0 | 14,860 | 0 |
| 12 | 0 | 15,098 | 0 |
| 13 | 0 | 15,162 | 0 |
| 14 | 0 | 15,171 | 0 |
| 15 | 0 | 15,166 | 0 |
| 16 | 0 | 15,274 | 0 |
| 17 | 0 | 15,481 | 0 |
| 18 | 0 | 15,698 | 0 |
| 19 | 0 | 16,041 | 0 |
| 20 | 0 | 16,468 | 0 |
| 21 | 0 | 16,948 | 0 |
| 22 | 0 | 17,013 | 0 |
| 23 | 0 | 17,080 | 0 |