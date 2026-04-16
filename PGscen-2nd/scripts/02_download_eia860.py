"""
Download EIA Form 860 (annual generator inventory) and extract NY wind, solar,
and battery storage plants with lat/lon and nameplate capacity.

Source: https://www.eia.gov/electricity/data/eia860/

EIA-860 is published annually, usually in September for the prior year. The
file is a ZIP containing several Excel sheets; we need:
  - 2___Plant_Y<YYYY>.xlsx       — one row per plant, has lat/lon
  - 3_1_Generator_Y<YYYY>.xlsx   — one row per generator, has technology + MW
  - 3_3_Solar_Y<YYYY>.xlsx       — solar-specific details (optional)
  - 3_4_Wind_Y<YYYY>.xlsx        — wind-specific details (optional)
  - 3_5_Multifuel_Y<YYYY>.xlsx, etc.

Usage:
    python 02_download_eia860.py --year 2023 --out data/NYISO_real/plant_metadata/

Outputs:
    eia860_ny_wind.csv
    eia860_ny_solar.csv
    eia860_ny_storage.csv
"""

from __future__ import annotations
import argparse
import io
import zipfile
from pathlib import Path
import pandas as pd
import requests

EIA860_URLS = [
    # current year lives at xls/, older years at archive/xls/
    "https://www.eia.gov/electricity/data/eia860/xls/eia860{year}.zip",
    "https://www.eia.gov/electricity/data/eia860/archive/xls/eia860{year}.zip",
]

# Technology strings used by EIA-860 (column "Technology" in Generator sheet)
WIND_TECHS = {"Onshore Wind Turbine", "Offshore Wind Turbine"}
SOLAR_TECHS = {"Solar Photovoltaic", "Solar Thermal without Energy Storage",
               "Solar Thermal with Energy Storage"}
STORAGE_TECHS = {"Batteries", "Flywheels"}


def download_eia860(year: int, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"eia860{year}.zip"
    # Validate any existing cache: must start with ZIP magic bytes "PK"
    if cached.exists():
        with open(cached, "rb") as fh:
            magic = fh.read(2)
        if magic == b"PK":
            print(f"  using cached {cached}")
            return cached
        else:
            print(f"  cached file is not a valid zip (got {magic!r}); re-downloading")
            cached.unlink()
    last_err = None
    for url_tpl in EIA860_URLS:
        url = url_tpl.format(year=year)
        print(f"  trying {url}")
        try:
            r = requests.get(
                url,
                timeout=180,
                headers={"User-Agent": "Mozilla/5.0 (PGScen-NYISO research script)"},
                allow_redirects=True,
            )
            r.raise_for_status()
            if r.content[:2] == b"PK":
                cached.write_bytes(r.content)
                return cached
            last_err = f"non-ZIP from {url} (Content-Type={r.headers.get('Content-Type')})"
            print(f"    {last_err}")
        except requests.HTTPError as e:
            last_err = f"HTTP {e.response.status_code} from {url}"
            print(f"    {last_err}")
    err_path = cache_dir / f"eia860{year}.error.html"
    if 'r' in dir() and r is not None:
        err_path.write_bytes(r.content[:4000])
    raise RuntimeError(
        f"All EIA-860 URLs failed for year={year}. Last error: {last_err}. "
        f"Saved last response to {err_path}. Check "
        f"https://www.eia.gov/electricity/data/eia860/ for the current "
        f"download link and confirm the year is published."
    )


def find_sheet(zf: zipfile.ZipFile, prefix: str) -> str | None:
    """Find a member like '3_1_Generator_Y2023.xlsx' regardless of subdir."""
    for name in zf.namelist():
        base = Path(name).name
        if base.startswith(prefix) and base.endswith(".xlsx"):
            return name
    return None


def read_eia_sheet(zf: zipfile.ZipFile, member: str, header_row: int = 1) -> pd.DataFrame:
    """EIA-860 sheets typically have a 1-row title above the real header."""
    with zf.open(member) as fh:
        data = fh.read()
    return pd.read_excel(io.BytesIO(data), header=header_row)


def extract_ny_generators(zip_path: Path, year: int) -> dict[str, pd.DataFrame]:
    with zipfile.ZipFile(zip_path) as zf:
        plant_member = find_sheet(zf, "2___Plant")
        gen_member = find_sheet(zf, "3_1_Generator")
        if plant_member is None or gen_member is None:
            raise RuntimeError(
                f"Could not find expected sheets in {zip_path}. "
                f"Members: {zf.namelist()[:10]}"
            )
        plants = read_eia_sheet(zf, plant_member)
        gens = read_eia_sheet(zf, gen_member)

    # Normalize column names
    plants.columns = [c.strip() for c in plants.columns]
    gens.columns = [c.strip() for c in gens.columns]

    # Filter NY
    plants_ny = plants[plants["State"] == "NY"].copy()
    gens_ny = gens[gens["State"] == "NY"].copy()
    print(f"  EIA-860 {year}: {len(plants_ny)} NY plants, {len(gens_ny)} NY generators")

    # Join generators to plants on Plant Code (= Plant ID)
    keep_plant_cols = ["Plant Code", "Plant Name", "City", "County",
                       "Latitude", "Longitude", "Balancing Authority Code"]
    plant_subset = plants_ny[[c for c in keep_plant_cols if c in plants_ny.columns]]
    merged = gens_ny.merge(plant_subset, on="Plant Code", how="left",
                           suffixes=("", "_plant"))

    # Resolve plant-name column collision
    if "Plant Name_plant" in merged.columns:
        merged["Plant Name"] = merged["Plant Name_plant"].fillna(merged.get("Plant Name"))
        merged = merged.drop(columns=["Plant Name_plant"])

    # Filter to operational + planned + standby
    op_status_keep = {"OP", "SB", "OS", "OA", "OZ", "TS",  # operating-ish
                      "P", "L", "T", "U", "V"}              # planned-ish
    if "Status" in merged.columns:
        merged = merged[merged["Status"].isin(op_status_keep)]

    out = {}
    for kind, techs in [("wind", WIND_TECHS),
                        ("solar", SOLAR_TECHS),
                        ("storage", STORAGE_TECHS)]:
        sub = merged[merged["Technology"].isin(techs)].copy()
        # Build a tidy frame
        cols = {
            "Plant Code": "eia_plant_id",
            "Plant Name": "plant_name",
            "Generator ID": "generator_id",
            "County": "county",
            "Latitude": "latitude",
            "Longitude": "longitude",
            "Nameplate Capacity (MW)": "nameplate_mw",
            "Technology": "technology",
            "Status": "status",
            "Operating Year": "operating_year",
            "Balancing Authority Code": "ba_code",
        }
        present = {k: v for k, v in cols.items() if k in sub.columns}
        tidy = sub[list(present.keys())].rename(columns=present)
        out[kind] = tidy.reset_index(drop=True)
        print(f"    {kind}: {len(tidy)} generators, "
              f"{tidy['nameplate_mw'].sum():.0f} MW total")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2024,
                    help="EIA-860 reporting year (current latest: 2024, "
                         "released Sep 2025)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--cache", type=Path, default=Path("data/cache"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    zip_path = download_eia860(args.year, args.cache)
    tables = extract_ny_generators(zip_path, args.year)
    for kind, df in tables.items():
        out_path = args.out / f"eia860_ny_{kind}.csv"
        df.to_csv(out_path, index=False)
        print(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
