# External Import Limit Audit

> Comparing model's 2019 p95 import limits to actual NYISO interface
> flows during the Phase 2 validation windows.

## Model limits (from 2019 p95 actual flows)

| Interface | Model Pmax (MW) |
|-----------|-----------------|
| PJM_import | 2,650 |
| HQ_import | 1,690 |
| NE_import | 300 |
| IESO_import | 1,290 |
| **Total** | **5,930** |

## Year 2020: 2020-09-22 to 2020-09-25

| Interface | Model Pmax | Actual p95 | Actual mean | Actual max | Gap (p95 - model) |
|-----------|-----------|------------|-------------|------------|-------------------|
| PJM_import | 2,650 | 1,681 | 1,194 | 3,116 | -969 |
| HQ_import | 1,690 | 2,698 | 1,816 | 5,100 | +1,008 |
| NE_import | 300 | 0 | -804 | -131 | -300 |
| IESO_import | 1,290 | 995 | 463 | 1,180 | -295 |
| **Total** | **5,930** | **5,374** | **2,670** | **9,265** | **-556** |

### Actual imports during worst-shedding hour (2020-09-22 H00 UTC = 8 PM EDT):

- PJM_import: 1,033 MW actual (model limit: 2,650 MW)
- HQ_import: 1,515 MW actual (model limit: 1,690 MW)
- NE_import: -717 MW actual (model limit: 300 MW)
- IESO_import: 848 MW actual (model limit: 1,290 MW)

## Year 2022: 2022-09-20 to 2022-09-23

| Interface | Model Pmax | Actual p95 | Actual mean | Actual max | Gap (p95 - model) |
|-----------|-----------|------------|-------------|------------|-------------------|
| PJM_import | 2,650 | 1,958 | 1,471 | 3,925 | -692 |
| HQ_import | 1,690 | 2,890 | 2,593 | 5,716 | +1,200 |
| NE_import | 300 | 554 | 163 | 604 | +254 |
| IESO_import | 1,290 | 1,396 | 1,011 | 2,645 | +106 |
| **Total** | **5,930** | **6,798** | **5,238** | **12,890** | **+868** |

### Actual imports during worst-shedding hour (2022-09-20 H00 UTC = 8 PM EDT):

- PJM_import: 1,636 MW actual (model limit: 2,650 MW)
- HQ_import: 2,883 MW actual (model limit: 1,690 MW)
- NE_import: 103 MW actual (model limit: 300 MW)
- IESO_import: 1,088 MW actual (model limit: 1,290 MW)

## Year 2023: 2023-09-19 to 2023-09-22

| Interface | Model Pmax | Actual p95 | Actual mean | Actual max | Gap (p95 - model) |
|-----------|-----------|------------|-------------|------------|-------------------|
| PJM_import | 2,650 | 2,756 | 2,175 | 2,892 | +106 |
| HQ_import | 1,690 | 693 | 302 | 757 | -997 |
| NE_import | 300 | 664 | -103 | 904 | +364 |
| IESO_import | 1,290 | 260 | 39 | 274 | -1,030 |
| **Total** | **5,930** | **4,373** | **2,413** | **4,827** | **-1,557** |

### Actual imports during worst-shedding hour (2023-09-19 H00 UTC = 8 PM EDT):

- PJM_import: 1,769 MW actual (model limit: 2,650 MW)
- HQ_import: 391 MW actual (model limit: 1,690 MW)
- NE_import: 133 MW actual (model limit: 300 MW)
- IESO_import: 61 MW actual (model limit: 1,290 MW)

## Key findings

1. **HQ import limit is too low for 2022**: Actual HQ imports reached
   2,883 MW at the worst hour, but the model caps at 1,690 MW. The 2019
   p95 value underestimates HQ capacity available in 2022 by ~1,200 MW.
   However, this did NOT cause the observed load shedding — the model
   dispatched all 1,690 MW available and still shed load due to the
   cold-start transient.

2. **NE is a net exporter in most periods**: The NE_import limit of
   300 MW is rarely binding because NY is typically exporting to New
   England (negative flows). The model's 300 MW import Pmax with
   Pmin=0 is reasonable — NE imports are rare and small.

3. **Import limits vary substantially by year**: The 2019 p95 values
   are a poor approximation for some years. HQ in particular shows
   large variation (p95 of 693 MW in 2023 vs 2,890 MW in 2022).

4. **Total import capacity is not the binding constraint**: In the
   worst shedding hours, actual total imports were 2,679 MW (2020),
   5,710 MW (2022), and 2,354 MW (2023) — all well below or near the
   model's 5,930 MW total limit. The cold-start commitment failure, not
   import caps, drives the shedding.

5. **For future calibration**: Each year should use its own p95 import
   values derived from that year's interface flow data, or at minimum
   from the most recent available year. This matters most for HQ and
   IESO, which show the largest year-to-year variation.
