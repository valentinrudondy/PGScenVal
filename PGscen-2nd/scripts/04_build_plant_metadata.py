"""
Merge Gold Book + EIA-860 + USWTDB into final per-plant metadata files
that PGScen can consume (wind_meta.csv, solar_meta.csv).

Strategy
--------
The Gold Book is the authoritative list of "what's actually on the NYISO
grid" (PTID, zone, town, MW, COD). It does NOT have lat/lon.
EIA-860 has lat/lon at the plant level for every utility-scale generator.
USWTDB has lat/lon at the turbine level for every wind farm.

We use the Gold Book row as the anchor and try to find the corresponding
EIA-860 (and USWTDB, for wind) entry by:
  1. fuzzy name match on the station/plant name
  2. county agreement (after FIPS → county-name lookup)
  3. capacity within ±15% (sanity check)

Output match_quality:
  3 = matched in all three sources (wind) or both available (solar/storage)
  2 = Gold Book + one external source
  1 = Gold Book only (no lat/lon — will need manual geocoding)

Usage:
    python 04_build_plant_metadata.py --in data/NYISO_real/plant_metadata/

Outputs (in same dir):
    wind_meta.csv
    solar_meta.csv
    storage_meta.csv
    metadata_merge_report.txt
"""

from __future__ import annotations
import argparse
import re
from pathlib import Path
import pandas as pd
from difflib import SequenceMatcher

# NY county FIPS → name (subset; full list is in Gold Book Table III-1)
NY_COUNTY_FIPS = {
    "001": "Albany", "003": "Allegany", "005": "Bronx", "007": "Broome",
    "009": "Cattaraugus", "011": "Cayuga", "013": "Chautauqua",
    "015": "Chemung", "017": "Chenango", "019": "Clinton",
    "021": "Columbia", "023": "Cortland", "025": "Delaware",
    "027": "Dutchess", "029": "Erie", "031": "Essex", "033": "Franklin",
    "035": "Fulton", "037": "Genesee", "039": "Greene", "041": "Hamilton",
    "043": "Herkimer", "045": "Jefferson", "047": "Kings", "049": "Lewis",
    "051": "Livingston", "053": "Madison", "055": "Monroe",
    "057": "Montgomery", "059": "Nassau", "061": "New York",
    "063": "Niagara", "065": "Oneida", "067": "Onondaga", "069": "Ontario",
    "071": "Orange", "073": "Orleans", "075": "Oswego", "077": "Otsego",
    "079": "Putnam", "081": "Queens", "083": "Rensselaer",
    "085": "Richmond", "087": "Rockland", "089": "St Lawrence",
    "091": "Saratoga", "093": "Schenectady", "095": "Schoharie",
    "097": "Schuyler", "099": "Seneca", "101": "Steuben",
    "103": "Suffolk", "105": "Sullivan", "107": "Tioga", "109": "Tompkins",
    "111": "Ulster", "113": "Warren", "115": "Washington",
    "117": "Wayne", "119": "Westchester", "121": "Wyoming", "123": "Yates",
}

NOISE_TOKENS = {
    # generic
    "wind", "power", "energy", "solar", "farm", "park", "llc", "lp",
    "ltd", "inc", "the", "of", "and", "&", "project", "facility",
    "center", "plant", "co", "corp", "company", "ny", "ii", "iii",
    "iv", "1", "2", "3",
    # composite words PDF→text gives us mashed together
    "windpark", "windpower", "windfarm",
    # operator/owner brand names that get prepended in Gold Book but not
    # in EIA-860 / USWTDB (which use the bare project name)
    "noble", "valcour", "galt", "nextera", "marketing", "renewables",
    "avangrid", "edf", "constellation", "iberdrola",
    # status/region tags
    "lessee", "owner", "operator", "new", "york",
}


def normalize_name(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t and t not in NOISE_TOKENS]
    return " ".join(tokens)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def best_match(target_name: str, target_county: str, target_mw: float,
               candidates: pd.DataFrame, name_col: str,
               county_col: str = "county", mw_col: str = "nameplate_mw",
               name_threshold: float = 0.55) -> tuple[int | None, float]:
    """Return (index, score) of best candidate row, or (None, 0).

    Scoring:
        score = name_similarity + county_bonus - mw_penalty
    where county_bonus is large (0.30) when the county agrees, because
    in our use case it's a very strong signal: there are typically only
    1-3 wind farms per NY county. We also use a *lower* effective threshold
    when county agrees (0.35 instead of 0.55) so that name-mangled but
    location-correct matches still get accepted.
    """
    if candidates.empty:
        return None, 0.0
    best_idx = None
    best_score = 0.0
    best_county_agrees = False
    for idx, row in candidates.iterrows():
        name_sim = similarity(target_name, str(row.get(name_col, "")))
        county_bonus = 0.0
        county_agrees = False
        if target_county and county_col in row.index:
            cand_cty = str(row[county_col]).strip().lower()
            tgt_cty = target_county.lower()
            if cand_cty and (tgt_cty in cand_cty or cand_cty in tgt_cty):
                county_bonus = 0.30
                county_agrees = True
        mw_penalty = 0.0
        cand_mw = row.get(mw_col)
        if pd.notna(target_mw) and pd.notna(cand_mw) and target_mw > 0:
            ratio = abs(cand_mw - target_mw) / target_mw
            if ratio > 0.25:
                mw_penalty = min(0.3, ratio - 0.25)
        score = name_sim + county_bonus - mw_penalty
        if score > best_score:
            best_score = score
            best_idx = idx
            best_county_agrees = county_agrees
    # Effective threshold: lower if county agrees
    effective = 0.35 if best_county_agrees else name_threshold
    if best_score < effective:
        return None, best_score
    return best_idx, best_score


def merge_one(kind: str, gb: pd.DataFrame, eia: pd.DataFrame,
              uswtdb: pd.DataFrame | None) -> tuple[pd.DataFrame, list[str]]:
    """Merge one resource type. Returns (final_df, log_lines)."""
    log = []
    rows = []
    eia_used = set()
    uswtdb_used = set()

    for _, gb_row in gb.iterrows():
        name = gb_row["owner_station_unit"]
        county = NY_COUNTY_FIPS.get(str(gb_row["county_fips"]).zfill(3), "")
        plate = gb_row["plate_mw"]

        eia_idx, eia_score = best_match(name, county, plate, eia, "plant_name")
        eia_match = eia.loc[eia_idx] if eia_idx is not None else None
        if eia_idx is not None:
            eia_used.add(eia_idx)

        uswtdb_idx = None
        uswtdb_match = None
        uswtdb_score = 0.0
        if uswtdb is not None and not uswtdb.empty:
            uswtdb_idx, uswtdb_score = best_match(
                name, county, plate, uswtdb, "p_name"
            )
            if uswtdb_idx is not None:
                uswtdb_used.add(uswtdb_idx)
                uswtdb_match = uswtdb.loc[uswtdb_idx]

        # Pick lat/lon: prefer USWTDB for wind, EIA for everything else
        lat = lon = None
        source = "none"
        if kind == "wind" and uswtdb_match is not None:
            lat, lon = uswtdb_match["latitude"], uswtdb_match["longitude"]
            source = "uswtdb"
        elif eia_match is not None and pd.notna(eia_match.get("latitude")):
            lat, lon = eia_match["latitude"], eia_match["longitude"]
            source = "eia860"
        elif uswtdb_match is not None:
            lat, lon = uswtdb_match["latitude"], uswtdb_match["longitude"]
            source = "uswtdb"

        n_sources = int(eia_match is not None) + int(uswtdb_match is not None)
        match_quality = 1 + n_sources  # 1 = goldbook only, 2 = +1 src, 3 = +2 src

        rows.append({
            "site_id": f"{kind}_{int(gb_row['ptid'])}",
            "site_name": name,
            "zone": gb_row["zone"],
            "county": county,
            "town": gb_row["town"],
            "latitude": lat,
            "longitude": lon,
            "nameplate_mw": plate,
            "operating_year": str(gb_row["cod"])[:4] if pd.notna(gb_row["cod"]) else None,
            "goldbook_ptid": int(gb_row["ptid"]),
            "eia_plant_id": (int(eia_match["eia_plant_id"])
                             if eia_match is not None and pd.notna(eia_match.get("eia_plant_id"))
                             else None),
            "uswtdb_project_name": (uswtdb_match["p_name"]
                                    if uswtdb_match is not None else None),
            "latlon_source": source,
            "match_quality": match_quality,
            "eia_match_score": round(eia_score, 3) if eia_score else None,
            "uswtdb_match_score": round(uswtdb_score, 3) if uswtdb_score else None,
        })
        log.append(
            f"  {name[:50]:50s}  q={match_quality}  src={source}  "
            f"eia={eia_score:.2f}  uswtdb={uswtdb_score:.2f}"
        )

    final = pd.DataFrame(rows)

    # Report unmatched EIA / USWTDB entries (might be plants Gold Book missed,
    # or aggregator-level vs unit-level mismatches)
    eia_unmatched = eia.drop(index=list(eia_used))
    log.append(f"\n  EIA-860 entries not matched to any Gold Book row: "
               f"{len(eia_unmatched)}")
    if not eia_unmatched.empty:
        for _, r in eia_unmatched.head(20).iterrows():
            log.append(f"    {r.get('plant_name', '?')[:50]:50s}  "
                       f"{r.get('nameplate_mw', 0):.1f} MW  "
                       f"{r.get('county', '?')}")
    if uswtdb is not None:
        uswtdb_unmatched = uswtdb.drop(index=list(uswtdb_used))
        log.append(f"  USWTDB projects not matched: {len(uswtdb_unmatched)}")
        for _, r in uswtdb_unmatched.head(10).iterrows():
            log.append(f"    {r.get('p_name', '?')[:50]:50s}  "
                       f"{r.get('nameplate_mw', 0):.1f} MW")
    return final, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", required=True, type=Path)
    args = ap.parse_args()
    d = args.indir

    log_lines = []

    # Load all sources
    gb_wind = pd.read_csv(d / "goldbook_ny_wind_existing.csv")
    gb_solar = pd.read_csv(d / "goldbook_ny_solar_existing.csv")
    gb_storage = pd.read_csv(d / "goldbook_ny_storage_existing.csv")

    eia_wind_p = d / "eia860_ny_wind.csv"
    eia_solar_p = d / "eia860_ny_solar.csv"
    eia_storage_p = d / "eia860_ny_storage.csv"
    uswtdb_p = d / "uswtdb_ny_projects.csv"

    if not eia_wind_p.exists():
        raise SystemExit(
            f"Missing {eia_wind_p}. Run scripts/02_download_eia860.py first."
        )
    eia_wind = pd.read_csv(eia_wind_p)
    eia_solar = pd.read_csv(eia_solar_p)
    eia_storage = pd.read_csv(eia_storage_p)
    # Aggregate EIA generators to plant level (one row per plant_id)
    for df in (eia_wind, eia_solar, eia_storage):
        if "eia_plant_id" not in df.columns:
            df["eia_plant_id"] = df.get("Plant Code")
    eia_wind_plant = (eia_wind.groupby("eia_plant_id", as_index=False)
                      .agg(plant_name=("plant_name", "first"),
                           county=("county", "first"),
                           latitude=("latitude", "first"),
                           longitude=("longitude", "first"),
                           nameplate_mw=("nameplate_mw", "sum")))
    eia_solar_plant = (eia_solar.groupby("eia_plant_id", as_index=False)
                       .agg(plant_name=("plant_name", "first"),
                            county=("county", "first"),
                            latitude=("latitude", "first"),
                            longitude=("longitude", "first"),
                            nameplate_mw=("nameplate_mw", "sum")))
    eia_storage_plant = (eia_storage.groupby("eia_plant_id", as_index=False)
                         .agg(plant_name=("plant_name", "first"),
                              county=("county", "first"),
                              latitude=("latitude", "first"),
                              longitude=("longitude", "first"),
                              nameplate_mw=("nameplate_mw", "sum")))

    uswtdb = pd.read_csv(uswtdb_p) if uswtdb_p.exists() else None
    if uswtdb is None:
        log_lines.append("WARNING: no USWTDB file; wind matching uses EIA-860 only.")

    # Run merges
    log_lines.append("\n=== WIND ===")
    wind_final, wlog = merge_one("wind", gb_wind, eia_wind_plant, uswtdb)
    log_lines.extend(wlog)

    log_lines.append("\n=== SOLAR ===")
    solar_final, slog = merge_one("solar", gb_solar, eia_solar_plant, None)
    log_lines.extend(slog)

    log_lines.append("\n=== STORAGE ===")
    storage_final, stlog = merge_one("storage", gb_storage, eia_storage_plant, None)
    log_lines.extend(stlog)

    # Write outputs
    wind_final.to_csv(d / "wind_meta.csv", index=False)
    solar_final.to_csv(d / "solar_meta.csv", index=False)
    storage_final.to_csv(d / "storage_meta.csv", index=False)

    # Summary
    summary = []
    for kind, df in [("wind", wind_final), ("solar", solar_final),
                     ("storage", storage_final)]:
        with_latlon = df["latitude"].notna().sum()
        summary.append(f"  {kind}: {len(df)} plants, {with_latlon} with lat/lon "
                       f"({with_latlon/max(len(df),1)*100:.0f}%), "
                       f"{df['nameplate_mw'].sum():.0f} MW total")
    print("\n".join(summary))
    log_lines.append("\n=== SUMMARY ===")
    log_lines.extend(summary)

    (d / "metadata_merge_report.txt").write_text("\n".join(log_lines))
    print(f"\n  wrote wind_meta.csv, solar_meta.csv, storage_meta.csv, "
          f"metadata_merge_report.txt to {d}")


if __name__ == "__main__":
    main()
