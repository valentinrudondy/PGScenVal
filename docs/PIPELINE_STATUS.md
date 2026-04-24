# Pipeline Status

> Last updated: 2026-04-23. Reflects state after Phase 3 calibration.

## Current calibration (v1 — production)

| Parameter | Value | Source |
|-----------|-------|--------|
| **Warmup day** | MANDATORY | Eliminates cold-start load shedding artifact at H00 |
| **Reserve requirement** | 2,620 MW fixed | NYISO Ancillary Services Manual: 10-min spin + non-sync + 30-min operating reserves, set by largest single contingency |
| **Reserve shortfall penalty** | $1,000/MWh | Below load shed penalty ($10k) to prioritize energy delivery |
| **Import limits** | 2019 p95 realized flows | PJM 2,650, HQ 1,690, NE 300, IESO 1,290 MW |
| **Import costs** | Fixed $/MWh | PJM $30, HQ $5, NE $35, IESO $15 |
| **Fuel prices** | Year-specific | Weekly CSV (2016–2021) or EIA Henry Hub annual average (2022+) |
| **Fleet baseline** | Year-specific | FleetUpdater from Gold Book NYCA Generators list |
| **Network** | Kron-reduced 35-bus | From NYgrid NPCC-140, NY-internal buses only |

### Known limitation: import pricing

Import Pmax and cost are coupled. The 2019 p95 Pmax values understate
physical transfer capability (~5,930 MW total vs ~10,000 MW declared),
but raising Pmax without adjusting HQ cost crashes 2022 LMPs from
+10.8% to -59.9% because $5/MWh HQ displaces all gas generation. See
[known_limitations.md](known_limitations.md) and
[report_calibrated_v2.md](../experiments/cross_year_validation/report_calibrated_v2.md).

## What works and is trusted

| Capability | Status | Evidence |
|------------|--------|----------|
| Multi-year fleet updates (2019–2023) | Trusted | IP2/IP3 retirements, Cricket Valley additions tracked correctly |
| Year-specific fuel prices | Trusted | EIA-derived prices match gas price trends; fuel price guard prevents silent fallback |
| Warmup + condition chaining | Trusted | Zero load shedding on all shoulder-season validation days |
| Fixed-MW reserve requirement | Trusted | More realistic than 5% of load; matches NYISO specification |
| LMP tracking (2020) | Good | -5.0% deviation vs NYISO actual (with v2 imports); +38.8% with v1 |
| LMP tracking (2022) | Good | +10.8% deviation with v1 calibration |
| LMP tracking (2023) | Good | +17.4% deviation with v1 calibration |
| PGscen scenario generation | Trusted | Regression tests confirm spatial variance, no compression |
| Scenario application | Trusted | Regression tests confirm timezone alignment, load/wind changes |

## What's known-limited

| Limitation | Impact | Future fix |
|------------|--------|------------|
| Import Pmax = 2019 p95, not physical | Understates import capacity by ~4 GW | Requires year-specific import costs (Path B) |
| HQ cost fixed at $5/MWh | Correct for 2019–2020; too cheap for 2022 | Year-specific cost from Zone D LMP |
| No zonal reserves | SENY/NYC reserve requirements not modeled | Requires Egret zonal reserve formulation |
| No storage dispatch (BESS) | Pumped hydro modeled but no batteries | Phase 4 |
| Solar only 2 generators, ~4 MW | Cannot validate solar spatial variance | Awaits NYISO distributed solar growth |
| IP2 in 2020 model | Gold Book 2020 predates April 2020 IP2 retirement | Manual override for mid-year retirements |

## External data sources

| Source | Data | Cache location | Update frequency |
|--------|------|----------------|------------------|
| NYISO MIS | Interface flows, zonal load, fuel mix, DA LBMPs | `data/nyiso_cache/{year}/` | Annual download |
| EIA | Henry Hub NG spot monthly | `data/nyiso_cache/eia/` | Annual download |
| NYISO Gold Book | NYCA Generators (fleet composition) | `data/nyiso_cache/{year}/gold_book/` | Annual download |
| NYgrid (Cornell) | NPCC-140 bus model, branch limits, fuel prices | `third_party/NYgrid/` | Static (2019 baseline) |
| PGscen-2nd | Wind/solar/load timeseries (HRRR-derived) | `PGscen-2nd/data/NYISO_real/` | Per-year CSV files |

## How to run the pipeline from scratch

```bash
conda activate vatic-test

# 1. Download data for target year Y
python -c "
from vatic.data.nyiso_downloader import NyisoDownloader
dl = NyisoDownloader()
dl.download_generators(Y)
dl.download_zonal_lmps(Y, market='da')
dl.download_interface_flows(Y)
"

# 2. Generate fleet baseline
python -c "
from vatic.data.nyiso_fleet_updater import FleetUpdater
FleetUpdater().update(year=Y)
"

# 3. Run validation
python experiments/cross_year_validation/run.py --year Y
```

## How to add a new year

1. Download Gold Book generators Excel for the year via
   `NyisoDownloader.download_generators(year)`. Add the URL to
   `nyiso_endpoints.yaml` if not already configured.
2. Run `FleetUpdater().update(year)` to generate the fleet baseline.
3. Ensure PGscen timeseries exist for the year under
   `PGscen-2nd/data/NYISO_real/{wind,solar}/`.
4. Ensure EIA NG prices are cached (automatic if the XLS covers
   the year; re-download if not).
5. If `fuelPriceWeekly_{year}.csv` exists in `third_party/NYgrid/Data/`,
   it will be used for week-specific prices. Otherwise, EIA annual
   average is used.
6. Add the year to `YEAR_CONFIGS` in `experiments/cross_year_validation/run.py`.
7. Run validation and compare LMPs to NYISO published DA LBMPs.

## Regression test coverage

21 fast tests + 2 slow tests covering 6 historical bug classes:
- Scenario compression, timezone alignment, cold-start, multi-day RUC,
  load diversity, per-plant wind variance
- 8 mutation tests confirming each regression test catches injected bugs
- See `experiments/regression/README.md` for details
