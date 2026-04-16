# `scripts/` — real NYISO plant metadata pipeline

Run these in order from the project root. The first script needs the
Gold Book PDF; the others fetch from public APIs/URLs.

```bash
# 1. Parse the Gold Book PDF (already done if you have the CSVs)
python scripts/01_parse_goldbook.py \
    --pdf 2025-Gold-Book-Public.pdf \
    --out data/NYISO_real/plant_metadata/

# 2. Download EIA Form 860 (latest published year is usually current_year - 2)
python scripts/02_download_eia860.py \
    --year 2023 \
    --out data/NYISO_real/plant_metadata/ \
    --cache data/cache/

# 3. Download US Wind Turbine Database for NY
python scripts/03_download_uswtdb.py \
    --out data/NYISO_real/plant_metadata/

# 4. Merge all three sources into PGScen-compatible meta files
python scripts/04_build_plant_metadata.py \
    --in data/NYISO_real/plant_metadata/
```

After step 4, you'll have:

```
data/NYISO_real/plant_metadata/
├── wind_meta.csv       ← consume this from data_utils.py
├── solar_meta.csv      ← consume this from data_utils.py
├── storage_meta.csv
└── metadata_merge_report.txt   ← sanity-check matches here
```

## Dependencies

```
pip install requests pypdf pandas openpyxl
```

(`openpyxl` is needed by pandas to read EIA-860 .xlsx files.)

## What to check after running

Open `metadata_merge_report.txt` and look for:

1. **`match_quality` distribution.** A `q=3` row matched all three sources
   (wind only). `q=2` matched Gold Book + one external source. `q=1` is
   Gold Book only — no lat/lon. Anything `q=1` will need either manual
   geocoding or to be excluded from the scenario pipeline.

2. **Unmatched EIA-860 / USWTDB entries.** These are plants in the
   federal databases that the matcher didn't pair with a Gold Book row.
   Causes:
   - Plant is too small for the NYISO market (< some MW threshold)
   - Plant is BTM (behind-the-meter) — not on the NYISO Gold Book
   - Name normalization missed a match → tweak `NOISE_TOKENS` in
     `04_build_plant_metadata.py` or raise the matcher's `name_threshold`

3. **MW agreement.** The matcher applies an MW penalty if Gold Book
   nameplate disagrees with EIA/USWTDB by >25%. Big disagreements
   usually mean the matcher paired the wrong rows.

## Known issues / v2 work

- **Proposed plants (queue).** Table IV-1a has no town/county, only zone.
  Geocoding the queue plants needs project-name matching against
  NYSERDA's awarded-contracts database (data.ny.gov). Defer to v2.
- **Storage in PGScen.** Batteries don't have a "forecast" the way wind
  and solar do, so the GEMINI/forecast-deviation framework doesn't
  directly apply. The storage_meta.csv is built for downstream use
  (e.g., dispatch awareness), not for scenario generation in v1.
- **EIA-860 year lag.** EIA publishes annually with a ~9 month lag.
  As of 2026, EIA-860 2024 is the latest. New plants commissioned in
  2025 will be in the Gold Book but not yet in EIA-860 — those will
  end up `match_quality=1` (Gold Book only) until the next EIA release.
