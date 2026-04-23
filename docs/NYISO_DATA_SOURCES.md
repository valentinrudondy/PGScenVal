# NYISO Public Data Sources Survey

> Compiled 2026-04-17. Purpose: identify what NYISO and EIA publish that can
> feed a year-agnostic fleet/timeseries updater for the Vatic NyisoLoader.

---

## 1. Market & Operational Data — mis.nyiso.com

NYISO's bulk data archive lives at `http://mis.nyiso.com/public/`.
There is **no official REST API** — all access is via direct HTTP GET to CSV/ZIP
files. No authentication required.

### URL patterns

| Scope | Pattern | Example |
|-------|---------|---------|
| **Single day (recent ~7 days)** | `http://mis.nyiso.com/public/csv/{dataset}/{YYYYMMDD}{dataset}.csv` | `.../csv/pal/20260415pal.csv` |
| **Monthly archive (historical)** | `http://mis.nyiso.com/public/csv/{dataset}/{YYYYMM01}{dataset}_csv.zip` | `.../csv/damlbmp/20250101damlbmp_csv.zip` |
| **Current snapshot** | `http://mis.nyiso.com/public/csv/{dataset}/current{dataset}.csv` | `.../csv/ExternalLimitsFlows/currentExternalLimitsFlows.csv` |

Monthly ZIP archives contain one CSV per day of the month.

### Datasets relevant to the updater

| Dataset ID | Description | Granularity | History | Notes |
|------------|-------------|-------------|---------|-------|
| `pal` | Real-time actual load by zone | Hourly | ~2000 | All 11 zones (A-K) + NYCA total |
| `palIntegrated` | Time-weighted hourly load | Hourly | ~2001 | Preferred for energy accounting |
| `damlbmp` | Day-ahead zonal & nodal LBMPs | Hourly | ~2001 | Includes LBMP, congestion, losses |
| `realtime` | Real-time dispatch LBMPs | 5-min | ~2001 | Very large; aggregate to hourly |
| `rtlbmp` | Real-time hourly-averaged LBMPs | Hourly | ~2001 | Lighter than raw `realtime` |
| `rtfuelmix` | Generation by fuel type (system-wide) | 5-min | ~2015 | Wind, gas, nuclear, hydro, etc. — NOT by zone |
| `ExternalLimitsFlows` | Interface limits & actual flows | 5-min | ~2005 | Total East, Central East, UPNY-SENY, external ties |
| `btmactualforecast` | Behind-the-meter solar by zone | Hourly | ~2018 | Separate from grid-scale solar |
| `isolf` | Short-term load forecast | Hourly | ~2005 | Useful for forecast-vs-actual validation |

### What's NOT available publicly

- **Wind/solar generation by zone or by generator** — only system-wide fuel
  mix (which lumps "Wind" and "Other Renewables"). Individual plant output
  requires market participant access.
- **Generator-level dispatch or commitment** — only aggregate fuel mix.
- **Bid data** — available ~6 months lagged at
  `http://mis.nyiso.com/public/P-27list.htm` (gen bids, load bids, UC data).

### Publication lag

- Real-time data: posted within minutes.
- Day-ahead data: posted after market clears (~11 AM day-ahead).
- Monthly archives: appear to be generated on the 1st–3rd of the following month.
- Fuel mix data: available back to ~2015.

---

## 2. Planning Reports — nyiso.com

### Gold Book (Load & Capacity Data Report)

The **2025 Gold Book** is the most recent edition as of April 2026.

| Resource | Format | URL |
|----------|--------|-----|
| Full report | PDF | `https://www.nyiso.com/documents/20142/2226333/2025-Gold-Book-Public.pdf` |
| Baseline forecast tables | Excel | `https://www.nyiso.com/documents/20142/51231901/2025-Gold-Book-Baseline-Forecast-Tables.xlsx` |
| Lower-demand scenario | Excel | `https://www.nyiso.com/documents/20142/51231901/2025-Gold-Book-LowerDemand-Scenario-Tables.xlsx` |
| Resources page | HTML | `https://www.nyiso.com/gold-book-resources` |

**Key content for the updater:**

- **Section 4 / Table 4-1 / Appendices**: Complete generator list with installed
  capacity, fuel type, zone, in-service date, summer/winter ratings, commercial
  status for every unit in NYCA.
- **Excel appendices** are the structured/machine-readable versions of the PDF
  tables — **this is the primary input for the fleet updater**.
- Load forecasts by zone (10-year horizon).
- Transmission interface transfer limits.

**Gold Book cadence:** Published annually, typically in April. The "2025" edition
reflects the system as of early 2025. Prior editions follow the same URL
structure with different document IDs (search the NYISO library for older years).

### Interconnection Queue

| Resource | Format | URL |
|----------|--------|-----|
| Full queue spreadsheet | Excel | `https://www.nyiso.com/documents/20142/1407078/NYISO-Interconnection-Queue.xlsx` |
| Queue viewer | HTML | `https://www.nyiso.com/interconnections` |

Contains all active and completed interconnection requests: project name, MW,
fuel type, zone, status, milestone dates. Key for identifying new generators
(especially battery storage and offshore wind) entering the fleet.

### Other useful reports

| Report | Content | URL base |
|--------|---------|----------|
| **Power Trends** (annual) | State-of-grid summary, fuel mix charts, capacity margins | `https://www.nyiso.com/power-trends` |
| **State of the Market** | Annual market performance review by Potomac Economics | NYISO library |
| **RNA / CRP** | Reliability needs assessment, 10-year outlook | NYISO library |
| **NYISO Library** | Searchable doc repository | `https://www.nyiso.com/library` |

---

## 3. EIA Fuel Price Data

### Access methods

EIA offers **both** downloadable Excel files and a **REST API (v2)**.

- **API base**: `https://api.eia.gov/v2/`
- **Auth**: Free API key — register at `https://www.eia.gov/opendata/`
- **Response**: JSON (max 5,000 rows per request) or XML (max 300 rows)
- **Browser**: `https://www.eia.gov/opendata/browser/` — interactive explorer

### Natural gas

| Series | Web page | Direct XLS | API route |
|--------|----------|-----------|-----------|
| Henry Hub spot (monthly) | `https://www.eia.gov/dnav/ng/hist/rngwhhdm.htm` | `.../hist_xls/RNGWHHDm.xls` | `natural-gas/pri/sum` |
| Henry Hub spot (daily) | `https://www.eia.gov/dnav/ng/hist/rngwhhdD.htm` | `.../hist_xls/RNGWHHDD.xls` | `natural-gas/pri/sum` |
| NYMEX futures (monthly) | `https://www.eia.gov/dnav/ng/ng_pri_fut_s1_m.htm` | `.../xls/NG_PRI_FUT_S1_M.xls` | `natural-gas/pri/fut` |

History: monthly spot back to January 1997.

**Note:** NYMEX futures data after April 2024 may be unavailable due to CME
licensing changes. Use Henry Hub spot as fallback.

### Petroleum (distillate / residual fuel oil)

| Series | Web page | API route |
|--------|----------|-----------|
| WTI crude spot | `https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm` | `petroleum/pri/spt` |
| No. 2 distillate (heating oil) | `https://www.eia.gov/dnav/pet/pet_pri_gnd_dcus_nus_w.htm` | `petroleum/pri/gnd` |
| Residual fuel oil | `https://www.eia.gov/petroleum/data.php` → refiner prices | `petroleum/pri/refoth` |

For the Vatic updater, we need:
- **Natural gas**: Henry Hub spot or NYMEX futures → proxy for NG generation
- **No. 2 fuel oil (FO2)**: proxy for oil/distillate peakers
- **Residual fuel oil (FO6)**: proxy for old oil steam units
- **Kerosene/jet fuel**: use No. 2 distillate as proxy

Zone-specific basis differentials (Transco Zone 6 NY vs. Henry Hub) can be
derived from NYISO LBMP-to-fuel-cost ratios if needed, but a flat NY adder
(typically $0.50–1.50/MMBTU above Henry Hub) is a reasonable first pass.

---

## 4. Third-Party Tools

| Library | Install | Notes |
|---------|---------|-------|
| **gridstatus** | `pip install gridstatus` | Wraps all mis.nyiso.com URLs, returns DataFrames. Actively maintained. [Docs](https://opensource.gridstatus.io/en/latest/autoapi/gridstatus/nyiso/) |
| **NYISOToolkit** | GitHub: `m4rz910/NYISOToolkit` | Similar, 14+ dataset types |

`gridstatus` handles ZIP download, extraction, CSV parsing, and column renaming.
Could use it internally, but for control and caching we'll write our own
downloader that mimics its URL patterns.

---

## 5. Data gap analysis for year-agnostic updater

| Need | Best source | Gap / risk |
|------|-------------|------------|
| Generator fleet (capacity, fuel, zone) | Gold Book Excel appendix | Published annually; need parser for each edition's layout |
| Generator retirements & additions | Gold Book + Interconnection Queue | Queue has projects in development, not all will complete |
| Hourly zonal load | `pal` or `palIntegrated` CSV | Clean, reliable, back to 2000 |
| Hourly DA LMPs (validation) | `damlbmp` CSV | Clean, reliable |
| Interface flows (external equiv.) | `ExternalLimitsFlows` CSV | 5-min → aggregate to hourly; ties to PJM, HQ, NE, IESO |
| Wind/solar by zone | **Gap** — only system-wide fuel mix public | Must rely on PGscen (if available for year) or NYISO BTM solar + fuel-mix wind column |
| Fuel prices (NG, FO2, FO6) | EIA API or XLS | Straightforward; need to handle zone basis |
| Unit commitment params | Carry from 2019 baseline | No public source for heat rates, min up/down — reasonable to reuse |
| Cost curves (heat rates) | Carry from 2019 baseline for existing units | New units: assign by class defaults |
| Bus assignments for new units | Zone centroid heuristic | No public bus-level data (CEII); zone → nearest NYgrid bus mapping needed |

### Biggest risks

1. **Gold Book Excel layout changes year to year** — parser must be defensive,
   with column-name matching rather than positional indexing.
2. **No per-zone renewable generation** — wind and solar can only be validated
   at the system level unless PGscen covers the target year.
3. **NYISO portal URL structure changes** — they've redesigned before; keep
   URLs in a YAML config file.
4. **EIA NYMEX data gap** — post-April 2024 futures may be missing; fall back
   to spot prices.

---

## 6. Recommended download priority for the updater

For a given target year Y:

1. **Gold Book Excel** (year Y or Y+1 edition) — generator fleet
2. **`pal` monthly ZIPs** (Jan–Dec year Y) — zonal load timeseries
3. **`ExternalLimitsFlows` monthly ZIPs** (Jan–Dec year Y) — interface flows
4. **`rtfuelmix` monthly ZIPs** (Jan–Dec year Y) — fuel mix for validation
5. **`damlbmp` monthly ZIPs** (Jan–Dec year Y) — LMPs for validation
6. **EIA natural gas + petroleum prices** (year Y) — fuel cost update
7. **Interconnection Queue Excel** — new projects (battery, offshore wind)
8. **`btmactualforecast` monthly ZIPs** — BTM solar (supplementary)

Total download size estimate: ~200–400 MB per year (mostly the 5-min datasets;
hourly datasets are ~50 MB/year).
