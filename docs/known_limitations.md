# Known Limitations

## 1. Import cost / Pmax coupling

### Problem

External import equivalents (PJM, HQ, NE, IESO) have two parameters:
Pmax (maximum import capacity in MW) and cost (offer price in $/MWh).
These are coupled: if Pmax is set to physical transfer capability
(~10,000 MW total) but cost remains fixed at low values ($5/MWh for
HQ), the optimizer imports as much cheap power as possible, displacing
internal NY generation and crashing LMPs.

### Evidence

Phase 3 Change 2 testing (see
[report_calibrated_v2.md](../experiments/cross_year_validation/report_calibrated_v2.md)):

| Config | 2022 LMP deviation |
|--------|-------------------|
| v1: Pmax = 2019 p95, HQ cost = $5 | +10.8% |
| v2: Pmax = declared capability, HQ cost = $5 | **-59.9%** |

HQ dispatched at 3,015 MW (74% of hours at Pmax) at $5/MWh, displacing
gas units costing $50–90/MWh.

### Three paths forward

**Path A (current)**: Keep 2019 p95 as Pmax. This uses realized flow
as a quantity cap, effectively embedding the economics of 2019 into
the import limit. Simple, works for 2019–2020, overestimates for 2022.

**Path B (recommended future work)**: Set Pmax to declared physical
capability (~10,000 MW) AND implement year-specific import costs.
HQ cost would be set to a fraction of the annual average Zone D
day-ahead LMP:
- 2019: ~$30 × 0.8 = ~$24/MWh
- 2020: ~$18 × 0.8 = ~$14/MWh
- 2022: ~$60 × 0.8 = ~$48/MWh
- 2023: ~$25 × 0.8 = ~$20/MWh

The 0.8 factor reflects the discount for firm bilateral contracts vs
spot prices. This requires a lookup table in NyisoLoader keyed by year
and import source. It does not require modifying Vatic core.

**Path C (out of scope)**: Endogenous pricing where import cost is
determined by the neighboring region's marginal cost. This requires
co-optimizing NY and neighboring regions simultaneously, which is a
multi-region dispatch problem far beyond the current model scope.

## 2. Kron reduction import distribution approximation

The 46-bus Kron-reduced network models external imports as generators
at NY boundary buses. Each import is distributed across 2-3 buses
using DC power flow distribution factors computed from the full 140-bus
model (see `experiments/kron_fidelity/`). This introduces up to 2.8%
error on interface flows compared to the full model.

The remaining error comes from secondary power distribution paths
through the external network that cannot be captured by a finite set
of boundary bus injections. For example, HQ import splits 50/50
between Moses E (Zone D) and Niagara W (Zone A), but small fractions
also leak through Watercure (Zone C, -16%) and Goethals (Zone J, +13%).

Impact: negligible for stochastic UC dispatch decisions. Interface flow
reporting may show 1-3% deviation from a full-network solution.

The 2.0x Kron scale factor on interface limits may now be larger than
necessary (it was originally set to compensate for the single-bus
approximation which caused 28-47% errors). Consider reducing to
1.2-1.3x after Phase A.2 LMP validation.

## 3. No zonal reserve requirements

NYISO enforces locational reserves: ~1,200 MW of 10-minute reserves
must be held in SENY (zones G–K), and ~300 MW in NYC (zone J). The
model uses a single system-wide constraint. This means reserves can
be provided entirely from cheap upstate resources, understating
downstate LMPs. Implementing zonal reserves requires populating
Egret's `EnforceZonalSpinningReserveRequirement` constraints, which
is supported in the formulation but not wired by any loader.

## 4. No battery energy storage (BESS)

The template includes pumped storage (Blenheim-Gilboa 1,160 MW,
Lewiston 240 MW) via `_PUMPED_STORAGE` in NyisoLoader, but the
Egret storage dict is not populated by the runner. Battery storage
(growing rapidly in NY post-2022) is not modeled. Phase 4 addresses
this.

## 5. Static heat rates (explicit policy decision)

Generator heat rate curves come from the 2019 NYgrid baseline and
are not updated for other years. This is an explicit policy decision
(Decision A), not an oversight. See `docs/heat_rate_policy.md` for
the full rationale.

Key points: heat rates are physical properties that change <1%/year,
while fuel prices change 10-30%/year. The fuel price update (via
`fuelPriceWeekly_{year}.csv`) captures the dominant cost variation.
Heat rate drift contributes <3% of the LMP error budget.

## 6. IP2 mid-2020 retirement (FIXED)

~~The 2020 Gold Book was published before Indian Point Unit 2 retired
(April 30, 2020).~~

**Fixed in Phase A.4**: `_NUCLEAR_RETIREMENTS` in
`nyiso_fleet_updater.py` now tracks mid-year retirement dates.
When `sim_start_date` is provided to `FleetUpdater.update()`, IP2
is excluded for any simulation starting after April 30, 2020.
Nuclear capacity for September 2020 drops from 5,430 MW to 4,404 MW.

## 7. Solar capacity too small to validate

NYISO's grid-scale solar in the 2019 baseline is only 2 generators
totaling ~4 MW. PGscen solar scenarios are applied as a system-level
ratio to these generators. With only 4 MW of solar, the spatial
variance regression test cannot meaningfully assess solar scenario
quality. This will change as NY's solar fleet grows (several GW of
distributed and utility-scale solar expected by 2025–2027).

## 8. Fuel price guard edge case

The fuel price staleness guard (added pre-Phase 2) checks whether
the loaded NG zone-A price matches the 2019 hardcoded default. If a
non-2019 year happens to have the same NG price as 2019, the guard
would be a false positive. This is unlikely but theoretically
possible. A more robust check would verify the year of the source
data, not just the price value.
