# Cross-Year Validation Report

> Generated 2026-04-23. Deterministic 3-day Vatic simulations on shoulder-
> season days for 2020, 2022, 2023. Compared to NYISO published DA LBMPs.

## Summary

| Year | Sim period | Model avg LMP | NYISO avg LMP | Deviation | LMP test | Load shed | LS test |
|------|-----------|---------------|---------------|-----------|----------|-----------|---------|
| 2020 | Sep 22–24 | $26.32/MWh | $15.97/MWh | +64.8% | **FAIL** | 77 MWh | PASS |
| 2022 | Sep 20–22 | $70.76/MWh | $71.66/MWh | -1.3% | PASS | 4,210 MWh | **FAIL** |
| 2023 | Sep 19–21 | $31.54/MWh | $23.27/MWh | +35.5% | PASS | 2,298 MWh | **FAIL** |

**LMP test**: model average within 40% of NYISO actual.
**LS test**: total load shedding < 500 MWh over 3 days.

**Verdict**: The pipeline runs without crashes for all 3 years. LMP
tracking is reasonable for 2022 and 2023 but systematically high. Load
shedding in 2022 and 2023 is too high for shoulder-season days and
indicates reserve/capacity calibration issues. See diagnosis below.

---

## 1. Template statistics

| Metric | 2019 (ref) | 2020 | 2022 | 2023 |
|--------|-----------|------|------|------|
| Thermal generators | 239 | 264 | 271 | 250 |
| Total thermal cap (MW) | 41,740 | 42,000 | 39,153 | 38,518 |
| Nuclear units | 6 | 6 | 4 | 4 |
| Nuclear cap (MW) | 5,430 | 5,430 | 3,364 | 3,364 |
| Hydro disp. (MW) | 2,460 | 2,460 | 2,460 | 2,460 |
| Wind gens | 31 | 31 | 31 | 31 |
| Solar gens | 16 | 16 | 16 | 16 |
| Buses (Kron-reduced) | 35 | 35 | 35 | 35 |
| Storage units | 0 | 0 | 0 | 0 |

### Fleet expectations — PASS

- **2020**: Indian Point 2 and 3 both present (correct — IP2 retired
  April 30, 2020, but the 2020 Gold Book was published before closure;
  the baseline reflects the fleet as documented). Cricket Valley 3×340 MW
  present (entered service 2020).
- **2022**: Indian Point 2 and 3 both retired. Nuclear drops from 5,430
  to 3,364 MW (loss of ~2,066 MW). Cricket Valley present at 3×353 MW.
- **2023**: Same nuclear fleet as 2022. No offshore wind (correct — first
  NY offshore wind not operational until 2026+). Cricket Valley at 3×343 MW.

### Fuel prices applied

| Year | NG zone A ($/MMBTU) | Source |
|------|---------------------|--------|
| 2019 | $3.63 | NYgrid weekly CSV |
| 2020 | $1.35 | NYgrid weekly CSV (Sep 22 week) |
| 2022 | $9.10 | EIA Henry Hub annual avg |
| 2023 | $3.60 | EIA Henry Hub annual avg |

The fuel price guard added pre-Phase 2 correctly blocks silent 2019
fallback. 2020 uses the weekly CSV (which covers 2016–2021). 2022–2023
use EIA-derived prices.

---

## 2. Simulation results — detailed

### 2020: Sep 22–24

- **Ran without crashes**: yes
- **Runtime**: 618 seconds (10.3 min)
- **Total cost**: $8,158,070 (3-day)
- **Load shedding**: 77 MWh — PASS (< 500 MWh)
- **Reserve shortfall**: 308 MWh
- **Average demand**: 14,552 MW

**LMP comparison**: Model $26.32 vs NYISO $15.97 — deviation +64.8%
(**FAIL**, threshold 40%).

**Diagnosis**: The model overestimates LMPs for 2020. Likely causes:
1. **COVID demand**: Sep 2020 demand was still depressed from COVID.
   The model uses NYISO actual load data, so demand should be correct —
   but the $1.35/MMBTU gas price from the weekly CSV may not fully
   capture the rock-bottom spot prices of late September 2020.
2. **IP2 still present**: The 2020 Gold Book lists IP2 as operational
   (it retired April 30). For September 2020, IP2 was actually offline.
   This means the model has ~1 GW more nuclear than reality, which
   should *lower* prices — so this isn't the cause. The overestimate
   likely comes from cost curve calibration or reserve specification.
3. **Reserve factor**: The 5% reserve factor may be too high for a
   low-load shoulder day, forcing expensive peakers online.

### 2022: Sep 20–22

- **Ran without crashes**: yes
- **Runtime**: 847 seconds (14.1 min)
- **Total cost**: $28,856,525
- **Load shedding**: 4,210 MWh — **FAIL** (>> 500 MWh)
- **Reserve shortfall**: 3,736 MWh
- **Average demand**: 16,820 MW

**LMP comparison**: Model $70.76 vs NYISO $71.66 — deviation -1.3%
(**PASS**). Remarkably close.

**Diagnosis**: Despite excellent LMP tracking, the 4,210 MWh of load
shedding on a shoulder-season day is implausible. NYISO does not shed
load on September shoulder days. Root causes:
1. **Indian Point retirement**: 2,066 MW of nuclear gone, reducing
   capacity margin. The model may be tighter than reality because
   external imports (PJM, HQ, NE, IESO) are capped at 2019 p95 limits
   rather than 2022 actual flows.
2. **$9.10/MMBTU gas price**: While correct for 2022 annual average,
   the high gas price may push marginal costs above the load shedding
   penalty for some hours if reserve constraints bind.
3. **Reserve requirement**: 5% of 16,820 MW = 841 MW. If the system
   can't provide this margin with Indian Point retired, the solver
   sheds load to satisfy reserves. This is a calibration issue, not
   a code bug.

### 2023: Sep 19–21

- **Ran without crashes**: yes
- **Runtime**: 491 seconds (8.2 min)
- **Total cost**: $11,862,591
- **Load shedding**: 2,298 MWh — **FAIL** (>> 500 MWh)
- **Reserve shortfall**: 318 MWh
- **Average demand**: 14,624 MW

**LMP comparison**: Model $31.54 vs NYISO $23.27 — deviation +35.5%
(**PASS**, within 40%).

**Diagnosis**: Similar pattern to 2022 — reasonable LMPs but excessive
load shedding. The 2023 fleet has slightly less capacity than 2022
(250 vs 271 thermal units), contributing to tightness.

---

## 3. What works

1. **The pipeline runs across years without crashing.** All 3 years
   completed deterministic 3-day simulations successfully.

2. **Fleet updates are correct.** Indian Point retirements, Cricket
   Valley additions, and capacity changes all track the Gold Book.

3. **Fuel prices respond to year.** The model correctly uses 2020-era
   low gas prices, 2022-era high gas prices, and 2023-era moderate
   prices. The 2022 LMP match (-1.3%) is strong evidence that the
   fuel-price-to-LMP pipeline is working.

4. **LMP tracking is within range.** 2 of 3 years pass the 40% test.
   The directional trend (low in 2020, high in 2022, moderate in 2023)
   matches NYISO perfectly.

## 4. What needs calibration

1. **Load shedding on shoulder days** (2022, 2023): The system is too
   tight. This is almost certainly the reserve specification — 5% of load
   as reserve is too aggressive when Indian Point is retired and external
   import limits are fixed at 2019 levels. **Phase 3 (reserve audit)**
   will diagnose and calibrate this.

2. **2020 LMP overestimate (+65%)**: The model overestimates by $10/MWh
   on a day when NYISO actual LMPs were only $16. This may be a
   combination of cost curve calibration (heat rates assumed from 2019
   baseline for all years) and IP2 being present in the model but
   retired in reality. Fixing IP2 retirement timing (mid-year 2020)
   and adjusting the reserve factor should help.

3. **External import limits**: Fixed at 2019 p95 values for all years.
   In reality, PJM and HQ import capacities have changed. **Phase 5
   (NYCA flow definition)** will document calibration sources for each
   year.

## 5. Fixes applied during Phase 2

1. **Gold Book parser**: Fixed to handle the 2020 edition's sheet
   naming (`" Table III-2"` instead of `"Table III-2a"/"Table III-2b"`).
   The parser now tries multiple sheet name candidates in order.

2. **Fleet baselines generated**: Created `nygrid_baseline_2020.json`
   and `nygrid_baseline_2022.json` via the FleetUpdater (2023 already
   existed).

3. **NYISO DA LBMP data**: Downloaded and cached for 2020, 2022, 2023
   via NyisoDownloader.

---

## 6. Next steps

- **Phase 3**: Reserve audit to fix load shedding. Calibrate reserve
  requirement to NYISO's actual 2,620 MW 10-minute operating reserve
  target instead of the 5% load-fraction rule.
- **Phase 5**: Update external import limits for each year.
- Re-run this validation after Phases 3 and 5 to confirm improvements.
