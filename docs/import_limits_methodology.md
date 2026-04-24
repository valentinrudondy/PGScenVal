# External Import Limits — Methodology and Proposed Values

## Why p95 of actual flow is wrong

The Phase 3 audit used the 95th percentile of actual historical import
flows as the model's import Pmax. This conflates two things:

1. **Physical transfer capability** — the maximum MW that could flow
   across the interface (limited by thermal ratings, voltage stability,
   and contractual caps).
2. **Economic dispatch decisions** — how much was actually scheduled
   (limited by price differentials, available generation in the
   neighboring region, and NYISO dispatch optimization).

Using p95 of realized flow as Pmax hardcodes NYISO's dispatch decisions
into the model as a physical constraint. This is wrong: the model
should be free to dispatch more imports than historically observed if
the optimization finds it economic.

## Methodology: declared transfer capability (median)

NYISO publishes real-time interface flow data at mis.nyiso.com, which
includes a `Positive Limit (MWH)` column for each interface at each
5-minute interval. This represents the **declared transfer capability**
— the maximum scheduled flow allowed by NYISO's security-constrained
dispatch, accounting for:

- Thermal line ratings
- Voltage stability limits
- Contingency analysis (N-1 security)
- Contractual limitations (e.g., HQ HVDC scheduling rules)

The declared limit varies by hour due to:
- Seasonal derating (e.g., higher ambient temperature → lower thermal
  rating)
- Outages on parallel paths
- NYISO operator actions (interface limits adjusted for reliability)

**Approach**: For each external equivalent and target year, compute the
**median** of the declared positive limit across all hours of the year.
This represents the typical available capacity, robust to occasional
deratings or outages. The median is preferable to:
- Maximum (includes rare conditions, overstates normal capability)
- Minimum (includes outage periods, understates normal capability)
- p95 of flow (conflates economics with physics, as discussed above)

**Rule (c)**: Never use less than the 2019 model value, since 2019 is
the calibrated baseline and we have no evidence that physical capacity
has decreased.

## Data sources

- **Interface flow data**: NYISO MIS public data,
  `ExternalLimitsFlows` dataset, downloaded via `NyisoDownloader`.
  Contains 5-minute `Flow (MWH)` and `Positive Limit (MWH)` for each
  named interface.

- **Sub-interface mapping**: Each model equivalent aggregates multiple
  NYISO scheduled interfaces:

| Model equivalent | NYISO interfaces |
|------------------|------------------|
| PJM_import | `SCH - PJ - NY`, `SCH - PJM_HTP`, `SCH - PJM_NEPTUNE`, `SCH - PJM_VFT` |
| HQ_import | `SCH - HQ - NY`, `SCH - HQ_CEDARS`, `SCH - HQ_IMPORT_EXPORT` |
| NE_import | `SCH - NE - NY`, `SCH - NPX_1385`, `SCH - NPX_CSC` |
| IESO_import | `SCH - OH - NY` |

These are **parallel paths** — their flows and limits are summed to get
the aggregate interface capacity.

## Proposed values

### Per-year median declared limits (computed from NYISO interface flow data)

Aggregated `Positive Limit (MWH)` across all sub-interfaces per group,
then median across all 5-minute intervals in each year:

| Interface | Current model | 2019 | 2020 | 2022 | 2023 | Proposed |
|-----------|--------------|------|------|------|------|----------|
| PJM_import | 2,650 | 3,635 | 3,685 | 3,635 | 3,835 | **3,660** |
| HQ_import | 1,690 | 2,970 | 3,000 | 3,060 | 3,030 | **3,015** |
| NE_import | 300 | 1,930 | 1,600 | 1,730 | 1,630 | **1,680** |
| IESO_import | 1,290 | 1,500 | 1,900 | 1,500 | 1,750 | **1,625** |
| **Total** | **5,930** | **10,035** | **10,185** | **9,925** | **10,245** | **9,980** |

**Proposed value** = median of the 4 yearly medians, floored at the
current model value (rule c: never reduce capacity).

### Comparison to current model

| Interface | Current | Proposed | Change | % change |
|-----------|---------|----------|--------|----------|
| PJM_import | 2,650 MW | 3,660 MW | +1,010 MW | +38% |
| HQ_import | 1,690 MW | 3,015 MW | +1,325 MW | +78% |
| NE_import | 300 MW | 1,680 MW | +1,380 MW | +460% |
| IESO_import | 1,290 MW | 1,625 MW | +335 MW | +26% |
| **Total** | **5,930 MW** | **9,980 MW** | **+4,050 MW** | **+68%** |

The current model has **4,050 MW less external import capacity** than
the declared transfer capability. This is because the original 2019
calibration used p95 of *realized* flow, not physical capacity. Most
interfaces are routinely utilized below their declared limits due to
economic dispatch decisions, not physical constraints.

### Why NE_import jumps the most

The current NE_import limit of 300 MW was set as the 2019 p95 *import*
flow — but NY is typically a net *exporter* to New England. The 300 MW
reflects rare import events, not the interface's physical capacity of
~1,930 MW. The model should allow the optimizer to use the full
import capability when it's economic (e.g., when NE has surplus
nuclear/hydro).

## Cross-checks

**Maximum observed flow** (lower bound on physical capacity):

| Interface | Max flow (any year 2019–2023) | Proposed Pmax | Headroom |
|-----------|------------------------------|---------------|----------|
| PJM_import | 8,335 MW | 3,660 MW | 4,675 MW |
| HQ_import | 8,697 MW | 3,015 MW | 5,682 MW |
| NE_import | 3,118 MW | 1,680 MW | 1,438 MW |
| IESO_import | 3,499 MW | 1,625 MW | 1,874 MW |

The proposed values are conservative — all are well below the maximum
observed flow, confirming we're not overestimating physical capacity.

## Impact assessment

Adding ~4 GW of import capacity will:
- Increase available supply, reducing any residual load shedding
- Lower LMPs at hours when imports are marginal (imports are priced
  at neighboring-region LMPs: PJM $30, NE $35, HQ $5, IESO $15)
- Most impact from HQ (+1,325 MW at $5/MWh) — cheap hydro imports
  will displace expensive NY gas generation

**Risk to 2022 LMP match**: The 2022 average LMP match was -1.3%
without these import changes. Adding 1,325 MW of cheap HQ imports
could lower the model's average LMP by $2–5/MWh, potentially
worsening the match. This needs to be validated empirically.

## Status

**Awaiting approval.** No import limit changes will be applied until
reviewed. The values above are computed from NYISO published data
and can be reproduced by running the analysis in
`experiments/phase3_capacity_diagnostic/`.
