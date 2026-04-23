# NYISO Integration Status

Status of the NYISO grid adapter for Vatic, based on Cornell's NYgrid model
(Liu et al. 2023, IEEE Trans. Power Systems).

Last updated: 2026-04-20

## What's Done

### Static Grid Template
- [x] NYgrid cloned at `third_party/NYgrid/` with MIT license preserved
- [x] NPCC-140 bus/branch topology extracted from `npcc.mat`
- [x] `modifyMPC()` modifications applied in Python (bus types, branch
      deletions/additions, interface limits)
- [x] 227 thermal generators with $/MWh cost curves (heat rate × 2019
      zone-specific fuel prices)
- [x] 6 nuclear generators as ThermalGenerators with MustRun
- [x] Niagara + St. Lawrence as dispatchable ThermalGenerators with
      treaty-based Pmin/Pmax bounds and MustRun
- [x] 7 small run-of-river hydro as NondispatchableGenerators
- [x] Blenheim-Gilboa excluded (pending storage model)
- [x] Serialized to `third_party/NYgrid/nygrid_baseline.json`
- [x] `vatic/data/nygrid_reader.py` — loader + inspection functions
- [x] `vatic/data/nyiso_loader.py` — `NyisoLoader(GridLoader)` class
- [x] Registered in `load_input()` dispatcher (`grid="NYISO"`)
- [x] 17 baseline tests + 22 structural smoke tests passing
- [x] Shaped dummy data builder for testing (24h load profile + hydro)

### Current Template Statistics
| Component | Count | Capacity (MW) | Notes |
|-----------|-------|---------------|-------|
| Buses (total / NY) | 140 / 46 | — | 94 external for PTDF boundary |
| Branches | 226 | — | After modifyMPC modifications |
| Thermal generators | 227 | 27,064 | genParamAll.csv |
| Nuclear generators | 6 | 5,430 | MustRun, $7/MWh marginal |
| Dispatchable hydro | 2 | 3,316 | Niagara + StL, MustRun |
| Small hydro (non-disp) | 7 | 879 | Run-of-river, exogenous |
| **In template** | **242** | **36,689** | BG excluded |

## Decisions Made

### DECIDED: Hydro dispatch semantics
**Niagara (2460 MW) and St. Lawrence (856 MW) are ThermalGenerators with
MustRun**, not NondispatchableGenerators.

**Why**: They're operator-dispatched and bid into the NYISO market. As
non-dispatchable, they produce at forecast regardless of system conditions,
which distorts LMPs and reserve adequacy by ~3.3 GW. The treaty-based
operating range translates naturally to Pmin/Pmax:
- Niagara: Pmin=1560 MW (min monthly CF=0.635 from 2016-2021 data),
  Pmax=2460 MW (nameplate)
- St. Lawrence: Pmin=700 MW (min CF=0.82), Pmax=856 MW

**Limitation**: These bounds are static monthly averages. For hour-level
variation, wire USGS Niagara River flow data into time-varying Pmin/Pmax.

### DECIDED: Blenheim-Gilboa excluded
**BG is excluded from the template entirely**, pending storage model wiring.

**Why**: The 75.8 MW in `RenewableGen.csv` is a net-generation allocation to
bus 77, not the plant's 1160 MW capacity. It cannot be modeled as a generator.
Vatic/Egret has full storage support (SOC tracking, charge/discharge, efficiency)
via the `storage` dict in the model, but no loader populates it. BG should be
added as storage with ~1160 MW, ~8h duration, ~80% round-trip efficiency.

### DECIDED: Cost curves use 2019 fuel prices
Cost curves = heat_rate (MMBTU/MWh) × zone-specific fuel price ($/MMBTU).
Prices from `fuelPriceWeekly_2019.csv` annual averages:
- Gas: $3.63 (upstate) to $4.40 (downstate) → ~$30-40/MWh marginal
- Fuel Oil 2: $18.35 → ~$200-250/MWh marginal (peaker)
- Fuel Oil 6: $13.45 → ~$60-135/MWh marginal
- Coal: $3.10 → ~$23/MWh marginal
- Nuclear: $7/MWh flat (typical US nuclear fuel cost)

For time-varying studies, integrate the weekly prices per-simulation-week.

## Blocking Issues — Must Fix Before Research Results

### 1. UC parameters (GATING ITEM)
Without realistic min up/down times and startup costs, the MILP commits and
decommits generators freely every hour. This makes results structurally wrong.

**What to do**: Pull from EIA-860 Schedule 3 (generator characteristics) matched
by PTID. NYgrid's `thermalGenMatched_2019.xlsx` may have partial matches.
Alternatively, use PowerGenome default parameters by unit type:
- Nuclear: MinUp=24h, MinDown=24h, startup=$100k+
- Large steam (coal, oil): MinUp=8-24h, MinDown=6-12h
- Combined cycle: MinUp=4-8h, MinDown=4-6h
- Combustion turbine: MinUp=1-2h, MinDown=1h
- Jet engine/peaker: MinUp=0, MinDown=0

**Priority**: Do this BEFORE PGscen integration. Incorrect commitment logic
contaminates every downstream analysis.

### 2. End-to-end UC solve test — DONE (copper sheet)
24-hour RUC + 24 hourly SCED solved in 45 seconds on copper sheet (no
transmission constraints) at 10 GW peak. Results:
- Zero load shedding, zero reserve shortfall
- Prices $2.97–$5.51/MWh (low because 8.7 GW must-run hydro+nuclear meets
  most of 10 GW peak — realistic for low-load summer)
- 27 commitment events: 21 at startup, 3 morning ramp, 3 evening ramp-down
- Coal/nuclear committed all day, gas cycling for peak

**PTDF solve with Kron-reduced network: DONE** (2026-04-17)
- Kron reduction eliminates 94 external buses → 46-bus, 74-branch NY network
  stored in `third_party/NYgrid/nygrid_kron_reduced.json`
- 4 import equivalent generators (PJM, HQ, NE, IESO) at boundary buses
- `NyisoLoader(use_reduced_network=True)` is the default
- 24h RUC+SCED solves with PTDF power flow, zero load shedding
- Prices at 53% of actual ($12.28 vs $23.03 avg) — import limits too generous
  and 2-point cost curves understate marginal cost

**Calibration completed** (2026-04-17):
- Import Pmax tightened to 2019 p95 actual flows (not declared limits)
- 75 generators use 5-segment piecewise curves from quadratic heat rates
- `fuel_price_date` parameter loads week-specific prices from CSV
- Key finding: Vatic's `Price` column is average cost, not marginal LMP.
  With `run_lmps=True`, Egret's dual variables give true LMPs.

**LMP validation against July 8, 2019 (low-congestion day)**:
| Metric | Simulation | Actual NYISO | Ratio |
|--------|-----------|-------------|-------|
| Avg bus LMP | $27.59 | $23.03 | 1.20 |
| Min LMP | $18.29 | $19.52 | 0.94 |
| Max LMP | $30.08 | $29.04 | 1.04 |

20% overpricing. Cause: model has no NE exports (real NY→NE avg -656 MW).
Zonal prices are uniform (no congestion) because Kron equivalent branches
have unlimited ratings.

**Zonal congestion via NYISO interface constraints: DONE** (2026-04-17)
- 7 NYISO interfaces (DYSINGER EAST, WEST CENTRAL, TOTAL EAST, MOSES SOUTH,
  CENTRAL EAST, UPNY CONED, SPR/DUN-SOUTH) mapped to Kron-reduced branches
- Interface limits from 2019 declared capacities, scaled 2x to compensate
  for PTDF factor differences between Kron-reduced and full network
- Produces correct congestion gradient (upstate cheaper, downstate premium)
- J/K premium: $7.27/MWh simulated vs $2.96 actual on low-congestion July 8

**Final validation against July 8, 2019 (with interface constraints)**:
| Zone | Simulated | Actual | Ratio |
|------|----------|--------|-------|
| A (West) | $26.30 | $22.96 | 1.15 |
| C (Central) | $26.74 | $21.22 | 1.26 |
| D (North) | $25.76 | $18.19 | 1.42 |
| E (Mohawk) | $25.76 | $21.60 | 1.19 |
| F (Capital) | $25.89 | $22.10 | 1.17 |
| J (NYC) | $32.90 | $24.11 | 1.36 |
| K (Long Is) | $34.25 | $24.90 | 1.38 |
| **System** | **$28.83** | **$22.07** | **1.31** |

31% system overshoot. Sources: no NE exports (~$3-4/MWh effect), 2x Kron
scale factor slightly over-constrains interfaces, and linear cost curves
overstate marginal cost at partial load for some generators.

**Egret compatibility fixes made**: Added `NondispatchableMarginalCost`,
`PriceResponsiveLoad*` params to `models/params.py`, and
`price_responsive_load` to `data_providers.py` model dict.

### 3. Storage model for BG + Lewiston — DONE (2026-04-17)
Both NYISO pumped storage plants wired via Egret's storage framework:
- **Blenheim-Gilboa**: 1160 MW, 9280 MWh, bus 38 (GILBOA, zone E),
  charge eff 87%, discharge eff 92%
- **Lewiston**: 240 MW, 2880 MWh, bus 55 (NIAGARA E, zone A),
  charge eff 85%, discharge eff 90%

Note: RenewableGen.csv placed BG at bus 77 (BUCHANAN, zone G) — that was
wrong. The real plant is at GILBOA (bus 38, zone E). Corrected.

Storage reduces system LMP by ~$0.50/MWh (arbitrage between peak/off-peak).

## Timeseries Integration — DONE (2026-04-17)

`NyisoLoader.create_timeseries()` implemented. Reads from PGscen-2nd
`data/NYISO_real/` directory.

**Usage**:
```python
loader = NyisoLoader(
    use_reduced_network=True,
    fuel_price_date='2019-07-08',
    pgscen_dir='path/to/PGscen-2nd/data/NYISO_real'
)
gen_data, load_data = loader.create_timeseries(
    start_date=pd.Timestamp('2019-07-08', tz='utc'),
    end_date=pd.Timestamp('2019-07-10', tz='utc'),
)
```

**Data sources**:
- Wind: 23 NYISO-registered sites (1,979 MW nameplate) from NYISO_real
  actual + day-ahead forecast CSVs, mapped by site_id to generators
- Solar: 2 sites for 2019 (NYISO_real has limited historical solar)
- Load: 11 NYISO zones from multi-year zonal load CSV, distributed to
  buses using `RenewableGen.csv` load proportions
- Hydro: 7 small run-of-river at 50% constant (no PGscen data)

**Limitations**:
- NYISO_real solar has only 2 sites for 2019 (more available for 2020+)
- Wind/solar sites added as NondispatchableGenerators by site (not
  aggregated by zone), so the template grows by ~50 generators
- The HRRR-based `data/NYISO/` dataset has more sites (80 wind, 314 solar)
  but uses simulated (not observed) output values

## Not In 2019 Baseline (Future Work)

| Element | Details | Impact |
|---------|---------|--------|
| Indian Point retirement | IP2 (2020) + IP3 (2021), ~2 GW nuclear in zone H | Remove for 2021+ sims |
| Offshore wind | South Fork 130 MW, Sunrise 924 MW, Empire 810 MW, Beacon 1230 MW | 3+ GW in zone K/J |
| CHPE HVDC | 1250 MW Québec→NYC, expected 2026 | Major zone J import path |
| Clean Path NY | 1300 MW upstate→zone J, proposed | Changes congestion patterns |
| Smart Path | 345 kV rebuild zones D-E | Increases north-south transfer |
| Batteries | Ravenswood BESS 316 MW, others in queue | Populate via storage dict |
| Data centers | Multiple GW in zones F, G queue | Significant load growth |
| Micron fab | Zone E industrial load | Significant load growth |

## Updating to a New Year

The year-agnostic updater (added 2026-04-20) allows simulating any year from
2020 onwards by refreshing the generator fleet, fuel prices, and timeseries
from public NYISO data.

### Supported years

| Year | Gold Book | Baseline | Status |
|------|-----------|----------|--------|
| 2019 | (original NYgrid) | `third_party/NYgrid/nygrid_baseline.json` | Reference |
| 2020 | Available | Generate via FleetUpdater | IP2 retired Apr 2020 |
| 2021 | Available | Generate via FleetUpdater | IP3 retired Apr 2021 |
| 2022 | Available | Generate via FleetUpdater | Post-Indian Point |
| 2023 | Available | `data/nyiso_cache/2023/nygrid_baseline_2023.json` | Validated |
| 2024 | Available | Generate via FleetUpdater | — |
| 2025 | Available | Generate via FleetUpdater | Latest Gold Book |

### How to add support for year N

```python
from vatic.data.nyiso_downloader import NyisoDownloader
from vatic.data.nyiso_fleet_updater import FleetUpdater

# Step 1: Download data
dl = NyisoDownloader()
dl.download_generators(N)       # Gold Book generator list
dl.download_zonal_load(N)       # hourly load (needed for timeseries)
dl.download_fuel_mix(N)         # fuel mix (wind data + validation)
dl.download_interface_flows(N)  # external tie flows
dl.download_eia_ng_prices()     # EIA fuel prices (covers all years)

# Step 2: Generate updated baseline
updater = FleetUpdater()
updater.update(year=N)
# Produces: data/nyiso_cache/N/nygrid_baseline_N.json
#           docs/fleet_changes_N.md

# Step 3: Use it
from vatic.data.nyiso_loader import NyisoLoader
loader = NyisoLoader(year=N)
gen_data, load_data = loader.create_timeseries(
    start_date='YYYY-MM-DD', end_date='YYYY-MM-DD'
)
```

### When NYISO publishes the year N+1 Gold Book

1. Find the new Gold Book generator Excel URL on the NYISO gold-book-resources
   page (typically published in April).
2. Add the URL to `vatic/data/nyiso_endpoints.yaml` under
   `nyiso.planning.generators.editions`.
3. Run `dl.download_generators(N+1)` and `updater.update(year=N+1)`.
4. Review `docs/fleet_changes_{N+1}.md` for sanity (major retirements,
   new plants, capacity changes).
5. Run `pytest vatic/tests/test_nyiso_year_updater.py` — all should pass.

### Manual sanity checks

After generating a new year's baseline, verify:

- [ ] Total thermal capacity within 10% of published NYISO total
- [ ] Known retirements are absent (Indian Point for year >= 2022, etc.)
- [ ] Known additions are present (Cricket Valley for year >= 2020, etc.)
- [ ] Nuclear fleet matches (4 units post-2022: Ginna, NMP1, NMP2, Fitz)
- [ ] 24-hour UC solves feasibly on a test day
- [ ] System-average LMP is within 30% of actual NYISO for that day

### Validation metrics (2023 reference)

| Metric | Expected | Actual |
|--------|----------|--------|
| Total thermal capacity | 25-30 GW | 25.9 GW |
| Nuclear capacity | ~3.3 GW | 3.4 GW |
| Generators (thermal) | 250-280 | 258 |
| Indian Point absent | Yes | Yes |
| Cricket Valley present | Yes | 3 units, 1,029 MW |
| Winter load (Jan 15) | 15-20 GW | 15-20 GW |
| NG price zone A | $2-5/MMBTU | $3.60 |

### Known limitations

- **Topology is frozen at 2019.** Line-level NY transmission data is CEII-
  protected. Major new transmission (CHPE, Clean Path NY, Smart Path) will
  need manual topology additions when commissioned.
- **No per-zone renewable generation** from NYISO public data. Wind/solar
  are handled via PGscen (2019) or system-wide fuel mix scaling (other years).
- **Cost curves for new generators** use class-based defaults, not unit-
  specific heat rates. For high-fidelity studies, manually update heat rates
  from EIA-923 when available.
- **Bus assignments for new generators** use zone-representative buses,
  not actual electrical connection points.
- **Hydro fleet is static** — Niagara and St. Lawrence bounds don't change
  by year (they're treaty-driven, not fleet changes).
- **Storage** (batteries) are recorded in the fleet report but NOT added
  to the generator list — they go through Egret's storage dict, which
  requires separate parameterization.

### Architecture

```
vatic/data/
  nyiso_endpoints.yaml     — URL config (update when NYISO redesigns)
  nyiso_downloader.py      — Idempotent data fetcher + Gold Book parser
  nyiso_fleet_updater.py   — 2019 → year N baseline generator
  nyiso_timeseries.py      — NYISO-data-based timeseries builder
  nyiso_loader.py          — NyisoLoader(year=N) entry point

data/nyiso_cache/          — Downloaded/generated data (gitignored)
  {year}/
    gold_book/nyca_generators_{year}.xlsx
    zonal_load/{yyyymm}/...csv
    fuel_mix/{yyyymm}/...csv
    interface_flows/{yyyymm}/...csv
    nygrid_baseline_{year}.json
  eia/
    ng_henry_hub_spot_monthly.xls

docs/
  NYISO_DATA_SOURCES.md    — Survey of available public data
  fleet_changes_{year}.md  — Diff report for each generated year
```

## References

- Liu, V. et al. (2023). "Baseline Power Grid Model for New York." IEEE
  Transactions on Power Systems.
- NYgrid repository: https://github.com/AndersonEnergyLab-Cornell/NYgrid
- NYISO Gold Book (2025): system capacity and demand forecasts
- NYISO market data: http://mis.nyiso.com/public/
- EIA Henry Hub spot: https://www.eia.gov/dnav/ng/hist/rngwhhdm.htm
- EIA-860/923: generator characteristics and fuel consumption
