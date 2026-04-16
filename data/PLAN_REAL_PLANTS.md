# Real NYISO Plants — Implementation Plan

This document tracks the migration from NREL/PERFORM synthetic wind/solar
data to real NYISO plants for the PGScen scenario generation pipeline.

## Decisions made (per user)

- **Path D**: build the metadata pipeline first; defer the time-series
  sourcing decision until we see what the real plant universe looks like.
- **Scope**: wind + solar + battery storage.
- **Granularity**: every individual plant. No clustering or capacity threshold
  in v1 — we'll see if PGScen can handle ~50 wind + ~100 solar plants. If
  GEMINI fitting is too slow, we revisit and either threshold or cluster.

## Folder layout (added)

```
PGscen-main/
├── scripts/                         NEW
│   ├── 01_parse_goldbook.py         ✅ DONE
│   ├── 02_download_eia860.py        TODO
│   ├── 03_download_uswtdb.py        TODO
│   ├── 04_build_plant_metadata.py   TODO  (merge → wind_meta.csv, solar_meta.csv)
│   ├── 05_fetch_actuals.py          TODO  (after time-series decision)
│   └── 06_fetch_forecasts.py        TODO  (after time-series decision)
├── notebooks/                       NEW
│   └── 00_explore_real_plant_data.ipynb   TODO
└── data/NYISO_real/plant_metadata/  NEW
    ├── goldbook_existing_generators.csv   ✅ DONE  (689 units)
    ├── goldbook_proposed_generators.csv   ✅ DONE  (103 units)
    ├── goldbook_ny_wind_existing.csv      ✅ DONE  (31 units, ~3.0 GW plate)
    ├── goldbook_ny_solar_existing.csv     ✅ DONE  (16 units, 598 MW plate)
    ├── goldbook_ny_storage_existing.csv   ✅ DONE  (9 units, 115 MW plate)
    ├── goldbook_ny_wind_proposed.csv      ✅ DONE  (11 units, 4.6 GW plate)
    ├── goldbook_ny_solar_proposed.csv     ✅ DONE  (69 units, 6.4 GW plate)
    └── goldbook_ny_storage_proposed.csv   ✅ DONE  (23 units, 2.3 GW plate)
```

## Step 1 — Gold Book parser ✅

`scripts/01_parse_goldbook.py` parses Tables III-2a, III-2b (existing) and
IV-1a (proposed) from the 2025 Gold Book PDF.

**Validation against Gold Book Overview (page 4):**

| Resource | Parser sum_cap | Gold Book stated | Match |
|---|---|---|---|
| Solar (grid-connected) | 573.4 MW | 573 MW | ✅ exact |
| Wind (LBW + OSW) | 2716 MW | 2454 + 132 = 2586 MW | ≈ (newly online plants) |
| Storage | 23 MW summer cap | not stated | n/a |

**What the existing tables give us per plant:**
- Owner / Station / Unit name (free text — useful as a fuzzy join key)
- NYISO load zone (A–K)
- PTID (NYISO unit ID — unique)
- Town name + county FIPS + state FIPS
- COD (commercial operation date)
- Nameplate, summer & winter capability, 2024 net energy generation
- Unit type (WT, PV, ES) + fuel (LBW, OSW, SUN, BAT, FW)

**What's missing:** lat/lon. Town + county is enough to disambiguate against
EIA-860 / USWTDB (which both have lat/lon).

**Known limitations:**
- Storage: existing list is small; the queue shows 2.3 GW proposed.
- Proposed table has no town/county — only zone. To geocode proposed plants
  we'll need the project name → match to NYSERDA awarded contracts list
  (data.ny.gov) which includes town. Defer until v2.

## Step 2 — EIA Form 860 download (next)

Will fetch the latest annual file from
`https://www.eia.gov/electricity/data/eia860/` (typically `eia8602023.zip`),
extract `3_1_Generator_Y*.xlsx` and `2___Plant_Y*.xlsx`, filter to:
- `State == "NY"`
- `Technology in ("Onshore Wind Turbine", "Offshore Wind Turbine",
   "Solar Photovoltaic", "Batteries")`

Output: `eia860_ny_wind.csv`, `eia860_ny_solar.csv`, `eia860_ny_storage.csv`
with columns: plant_id, plant_name, generator_id, county, latitude, longitude,
nameplate_mw, technology, status, operating_year.

## Step 3 — USWTDB download

Will fetch from USGS API: `https://eersc.usgs.gov/api/uswtdb/v1/turbines?t_state=eq.NY`
(returns JSON of every turbine with lat/lon, hub height, rotor diameter,
project name, capacity). Aggregate by `p_name` to get per-project lat/lon
(centroid) and total capacity. This is more accurate than EIA-860 for wind,
because EIA-860 lists one lat/lon per *plant* but USWTDB has every turbine.

## Step 4 — Merge → final PGScen metadata

`04_build_plant_metadata.py` will fuzzy-join the three sources and produce:

```
data/NYISO_real/plant_metadata/wind_meta.csv
data/NYISO_real/plant_metadata/solar_meta.csv
data/NYISO_real/plant_metadata/storage_meta.csv
```

Schema (PGScen-compatible, mirrors `data/NYISO/MetaData/wind_meta.csv`):

```
site_id,site_name,zone,county,latitude,longitude,nameplate_mw,
operating_year,goldbook_ptid,eia_plant_id,uswtdb_project_name,
match_quality
```

`match_quality` flags whether all 3 sources agree, only 2, or only Gold Book
(so we can decide whether to drop low-quality entries from scenario gen).

## Step 5 — Time-series decision point

Once we see the merged metadata (number of plants, geographic spread,
capacity distribution), revisit the actuals + forecasts question. The
options remain:

- **A**: ERA5/MERRA-2 + power-curve / PVlib at each plant location for
  actuals; HRRR archive (AWS Open Data) for day-ahead forecasts. Most
  rigorous, ~1–2 weeks of work.
- **B**: NYISO zonal wind/solar totals (real, published) — abandons
  per-plant granularity but very fast.
- **C**: Renewables.ninja for actuals + persistence forecast as baseline.
  Middle ground.

After Step 4 is done we'll know whether per-plant is even sensible
(e.g., if there are 100+ proposed solar plants, modeling each one
separately probably isn't useful — capacity-weighted clusters would be
cleaner).
