# Step 2 — PLUSWIND download instructions

The Wind Data Hub (WDH) requires a free account (email-only) to access PLUSWIND
files. All anonymous endpoints redirect to `/profile?redirect=...` (verified).
Once you're registered the rest of the pipeline runs end-to-end.

## What you need to download

PLUSWIND HRRR per-plant hourly power, dataset id `nwpdb/modelpluswind.hr.c1`,
years 2018–2021, restricted to the 21 NY EIA plant IDs that appear in PLUSWIND:

```
55769  55790  56290  56575  56594  56618  56619  56620
56857  56901  56902  56904  56953  57078  57287  57867
58088  58768  58979  59629  61673
```

(Generated from the intersection of
[PGscen-2nd/data/NYISO_real/plant_metadata/wind_meta.csv](../../PGscen-2nd/data/NYISO_real/plant_metadata/wind_meta.csv)
and the PLUSWIND plant-list PDF. Coverage by year:
2018-2020 → 22/23 plants, 1854/1979 MW (94%); 2021 → 22/25 plants, 1854/2185 MW (85%).)

Total files: **84** (21 plants × 4 years), ~few MB each.

## Path A — programmatic (preferred)

1. Register: <https://wdh.energy.gov/register>. Email-only, no other info needed.
2. Log in at <https://wdh.energy.gov/>.
3. Install a "Get cookies.txt" browser extension (Chrome or Firefox).
4. Visit any WDH page while logged in, click the extension, **export cookies
   for `wdh.energy.gov`** in **Netscape format** to `~/.wdh_cookies.txt`.
5. Run the downloader:
   ```bash
   python PGscen-2nd/scripts/08_download_pluswind.py \
       --cookies ~/.wdh_cookies.txt \
       --years 2018 2019 2020 2021
   ```
   Files land in `data/pluswind_raw/<year>/<eia_id>.csv`. Idempotent.

If the script fails with "no URL template returned 200" your cookies are
either missing the `XSRF-TOKEN`/`wdh_session` pair or expired — re-export
and try again.

## Path B — browser DAP order (fallback)

If the cookie-based flow doesn't work, the WDH UI has a bulk-order tool:

1. Browse <https://wdh.energy.gov/ds/nwpdb/modelpluswind.hr.c1#data>.
2. Click "Download" → select years 2018–2021 → in the plant filter paste
   the 21 IDs above → submit.
3. WDH emails a download link for a single ZIP. Extract it to
   `data/pluswind_raw/` such that the layout is
   `data/pluswind_raw/<year>/<eia_id>.csv`. (If WDH's ZIP layout differs,
   `09_build_pluswind_wide.py` only requires per-year subfolders with
   `<eia_id>.csv` inside.)

## Once files are in place

```bash
# 1. Reshape PLUSWIND → wide format used by the validation script
python PGscen-2nd/scripts/09_build_pluswind_wide.py --years 2018 2019 2020 2021

# 2. Re-run the validation harness (will auto-detect PLUSWIND files)
python experiments/wind_validation/validate_hrrr_vs_nyiso.py
```

Output:
- `PGscen-2nd/data/NYISO_real/wind/wind_actual_1h_site_<year>_utc.pluswind.csv`
- Updated [scorecard.csv](scorecard.csv) and 5 plots, now with a PLUSWIND row alongside HRRR
- 2-week, diurnal, scatter, error-by-hour plots switch to 2020 (PLUSWIND coverage window) when PLUSWIND files are present, fall back to 2024 otherwise

## Step 2 success criterion

PLUSWIND fleet sum has strictly lower nMAE vs `rtfuelmix` than the in-house
HRRR-derived series **in every year of overlap (2018–2021)**. Baseline numbers
to beat (from Step 1 scorecard):

| Year | HRRR actual nMAE | HRRR actual nBias |
|-----:|-----------------:|------------------:|
| 2018 |              47% |              +25% |
| 2019 |              34% |               +6% |
| 2020 |              34% |               +6% |
| 2021 |              39% |              +15% |

PLUSWIND's published nMAE-vs-ISO numbers are ~7–9% on similar scoring,
so we should expect a 4–5× lift if everything is plumbed correctly. If
PLUSWIND comes in worse than HRRR somewhere, suspect plant-ID mapping
or the year filter rather than PLUSWIND itself.
