# Reserve Specification Audit

## 1. How Vatic models reserves

Vatic uses a single system-wide reserve requirement set as a **fraction
of total forecasted load**:

```
reserve_requirement[t] = reserve_factor × Σ(bus_load[t])
```

- **Parameter**: `reserve_factor` (default 0.05 = 5%)
- **Set in**: `VaticModelData.honor_reserve_factor()` at
  [model_data.py:291](../Vatic/vatic/model_data.py#L291)
- **Called from**: `PickleProvider` during both RUC and SCED construction
  at [data_providers.py:381](../Vatic/vatic/data_providers.py#L381) and
  [data_providers.py:465](../Vatic/vatic/data_providers.py#L465)
- **Initialized to**: 0 MW for all time periods at
  [data_providers.py:783](../Vatic/vatic/data_providers.py#L783), then
  overwritten by `honor_reserve_factor`

The reserve is enforced as a **single constraint** on total committed
thermal headroom. There is no distinction between spinning and
non-spinning reserves. The formulation used is
`garver_power_avail_vars` (RUC) / `MLR_reserve_vars` (SCED), which
defines reserve as the gap between committed Pmax and dispatched power.

**Penalty for shortfall**: `reserve_shortfall_penalty` = $1,000/MWh
(set in experiment 001's `run.py`). This is 10× lower than the load
shedding penalty ($10,000/MWh), so the solver will always prefer to
shortfall reserves before shedding load.

### Reserve requirement values at typical loads

| Year | Peak demand (MW) | Reserve at 5% | Off-peak demand (MW) | Reserve at 5% |
|------|-------------------|---------------|----------------------|---------------|
| 2019 | ~32,000 | 1,600 MW | ~14,000 | 700 MW |
| 2020 | ~15,500 | 775 MW | ~11,500 | 575 MW |
| 2022 | ~19,500 | 975 MW | ~13,800 | 690 MW |
| 2023 | ~17,000 | 850 MW | ~12,100 | 605 MW |

## 2. NYISO actual ancillary service requirements

Sources: NYISO Ancillary Services Manual (rev. 2019), NYISO Tariff
Section 15.2, NYISO Operating Reserve Demand Curve (ORDC).

### Reserve products

| Product | Requirement | Scaling | Notes |
|---------|-------------|---------|-------|
| **Regulation Service** | ~275 MW (2019 avg) | Set by NYISO hourly based on load variability | Not modeled in Vatic |
| **10-min Spinning Reserve** | ~655 MW | Fixed: largest single contingency (Nine Mile Point 2 = 1,299 MW shared with 10-min total) | Half of 10-min total |
| **10-min Non-Synchronized Reserve** | ~655 MW | Fixed: remainder of largest contingency | Combined spinning + non-sync = ~1,310 MW |
| **30-min Operating Reserve** | ~1,310 MW | Fixed: second-largest contingency or 50% of largest single contingency × 2 | Total operating reserves ≈ 2,620 MW |

### Total operating reserve requirement

- **10-minute total**: ~1,310 MW (spinning + non-sync)
- **30-minute total**: ~2,620 MW (10-min + 30-min)
- **Full operating reserves**: ~2,620 MW (this is the commonly-cited
  number)

The requirement is **fixed in MW**, not load-proportional. It's based
on the largest single contingency (the loss of the largest generating
unit or transmission element), which is typically Nine Mile Point Unit 2
at 1,299 MW.

### Zonal requirements

NYISO also enforces locational reserves:
- **SENY (Southeast NY)**: Zones G–K must carry ~1,200 MW of 10-minute
  reserves (NYISO ICAP Demand Curve)
- **NYC (Zone J)**: ~300 MW of local 10-minute reserves

These zonal requirements are NOT modeled in Vatic (Vatic uses a single
system-wide constraint).

## 3. Comparison

| Aspect | Vatic (current) | NYISO actual |
|--------|-----------------|--------------|
| Reserve type | Single aggregate headroom | 4 products (reg, spin, non-sync, 30-min) |
| Scaling | 5% of load (proportional) | Fixed MW (~2,620 total operating) |
| At 15,000 MW load | 750 MW | 2,620 MW |
| At 20,000 MW load | 1,000 MW | 2,620 MW |
| At 30,000 MW load | 1,500 MW | 2,620 MW |
| Zonal requirements | None | SENY ~1,200 MW, NYC ~300 MW |
| Regulation | Not modeled | ~275 MW |

### Key finding

**Vatic's reserve requirement is LOWER than NYISO's at all load levels
below ~52,000 MW** (which never occurs). At the shoulder-season loads in
Phase 2 (14,000–19,000 MW), Vatic requires 700–975 MW vs. NYISO's
2,620 MW. The model is under-reserving, not over-reserving.

This means the Phase 2 load shedding is NOT caused by excessive reserve
requirements. If anything, raising the reserve requirement to NYISO's
actual level would make the system tighter and potentially increase
shedding (on the cold-start hour where the real problem lies).

## 4. Implications

1. The reserve specification is a secondary issue. The primary cause of
   Phase 2 shedding is the cold-start transient at H00 (see
   `worst_hour_report.md`).

2. For future calibration: switching from 5% of load to a fixed 2,620 MW
   would slightly increase reserve requirements at low load and
   significantly increase them at high load. This is more realistic but
   will not fix the cold-start problem.

3. The absence of zonal reserve requirements means the model can satisfy
   reserves from anywhere in NY, including cheap upstate hydro/nuclear.
   This is optimistic — real NYISO must hold some reserves in SENY/NYC.
   Adding zonal reserves would increase LMPs in downstate zones.
