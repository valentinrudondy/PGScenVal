"""
Parse the NYISO Gold Book PDF (Tables III-2a and IV-1a) into clean CSVs of
existing and proposed wind / solar / storage resources.

Usage:
    python 01_parse_goldbook.py --pdf 2025-Gold-Book-Public.pdf --out data/NYISO_real/plant_metadata/

Output:
    goldbook_existing_generators.csv   (all existing units, all fuel types)
    goldbook_proposed_generators.csv   (all proposed units in IV-1a)
    goldbook_ny_wind.csv               (filtered: Unit Type WT, State NY)
    goldbook_ny_solar.csv              (filtered: Unit Type PV)
    goldbook_ny_storage.csv            (filtered: Unit Type ES, or Fuel BAT)

Notes
-----
The Gold Book PDF stores tables as fixed-position text. pypdf returns one
data row per line; we parse each row by anchoring on:
  - the in-service date (YYYY-MM-DD)
  - the 2-digit state FIPS code (36 = NY)
  - the 3-digit county FIPS code
  - the PTID (1-7 digit integer that NYISO assigns to each unit)
  - the load zone letter (A-K)
The text between the start of the line and the zone letter is
"Owner ... Station Unit"; we keep it as one string and split heuristically.

Numeric columns to the right of the date follow a fixed schema:
    Plate SUM WIN SUM WIN [DUAL?] UnitType Fuel1 [Fuel2] [GWh] [(Notes)]
"""

from __future__ import annotations
import argparse
import re
from pathlib import Path
import pandas as pd
import pypdf

# Vocabulary from Table III-1
UNIT_TYPES = {
    "CC", "CG", "CT", "CW", "ES", "FC", "GT", "HY", "IC", "JE",
    "NB", "NP", "PS", "PV", "ST", "WT",
}
FUEL_TYPES = {
    "BAT", "BUT", "FO2", "FO4", "FO6", "FW", "JF", "KER", "MTE", "NG",
    "OT", "REF", "SUN", "UR", "WAT", "WD", "LBW", "OSW",
}

# Match a Gold Book existing-generator data row.
# Captures, in order:
#   1: prefix (everything up to Zone letter)  -> Owner + Station + Unit
#   2: zone letter (A-K)
#   3: PTID (digits)
#   4: town (one or more words)
#   5: county FIPS (3 digits)
#   6: state FIPS (2 digits)
#   7: COD (YYYY-MM-DD)
#   8: rest of line (numeric cols + types + notes)
ROW_RE = re.compile(
    r"^(?P<prefix>.+?)\s"
    r"(?P<zone>[A-K])\s"
    r"(?P<ptid>\d{3,7})\s"
    r"(?P<town>.+?)\s"
    r"(?P<cnty>\d{3})\s"
    r"(?P<state>\d{2})\s"
    r"(?P<cod>\d{4}-\d{2}-\d{2})\s"
    r"(?P<rest>.+)$"
)

NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?")


def parse_rest(rest: str) -> dict:
    """
    Parse the right-hand side of a row:
        Plate SUM WIN SUM WIN [YES] UnitType Fuel1 [Fuel2] [GWh] [(Notes)]
    Returns dict with keys plate_mw, sum_cap, win_cap, dual, unit_type,
    fuel1, fuel2, energy_gwh, notes.
    """
    out = {
        "plate_mw": None, "cris_mw": None, "sum_cap": None, "win_cap": None,
        "sum_2024": None, "win_2024": None, "dual": False,
        "unit_type": None, "fuel1": None, "fuel2": None,
        "energy_gwh": None, "notes": None,
    }

    # Pull off any trailing parenthesised notes (may be multiple)
    notes = []
    while True:
        m = re.search(r"\s\([^)]+\)\s*$", rest)
        if not m:
            break
        notes.insert(0, m.group(0).strip())
        rest = rest[: m.start()].rstrip()
    if notes:
        out["notes"] = " ".join(notes)

    tokens = rest.split()

    # Find unit type position
    ut_idx = None
    for i, tok in enumerate(tokens):
        if tok in UNIT_TYPES:
            ut_idx = i
            break
    if ut_idx is None:
        return out

    out["unit_type"] = tokens[ut_idx]

    # Numeric columns are everything before unit type, optionally with "YES" right before it
    left = tokens[:ut_idx]
    if left and left[-1] == "YES":
        out["dual"] = True
        left = left[:-1]

    # Header schema (Table III-2a):
    #   Plate CRIS  SUM WIN  SUM WIN
    # i.e. 6 numeric columns. But many rows omit some (continuation rows for
    # multi-unit stations only show numeric for first unit). We accept 5-6.
    nums = []
    for tok in left:
        if NUM_RE.fullmatch(tok):
            nums.append(float(tok.replace(",", "")))
    if len(nums) >= 6:
        (out["plate_mw"], out["cris_mw"], out["sum_cap"], out["win_cap"],
         out["sum_2024"], out["win_2024"]) = nums[:6]
    elif len(nums) == 5:
        # No CRIS column
        (out["plate_mw"], out["sum_cap"], out["win_cap"],
         out["sum_2024"], out["win_2024"]) = nums

    # Right of unit type: fuel(s) then optional energy GWh
    right = tokens[ut_idx + 1:]
    fuels = []
    energy = None
    for tok in right:
        if tok in FUEL_TYPES:
            fuels.append(tok)
        elif NUM_RE.fullmatch(tok) and energy is None:
            energy = float(tok.replace(",", ""))
    if fuels:
        out["fuel1"] = fuels[0]
        if len(fuels) > 1:
            out["fuel2"] = fuels[1]
    out["energy_gwh"] = energy
    return out


def parse_existing(pdf_path: Path, page_range=range(85, 105)) -> pd.DataFrame:
    """Parse Table III-2a (existing market generators) and III-2b (non-market).

    Default range covers pages 86-105 (1-indexed) which holds both tables in
    the 2025 Gold Book. Adjust if using a different year.
    """
    reader = pypdf.PdfReader(str(pdf_path))
    rows = []
    for page_idx in page_range:
        if page_idx >= len(reader.pages):
            break
        text = reader.pages[page_idx].extract_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = ROW_RE.match(line)
            if not m:
                continue
            parsed = parse_rest(m.group("rest"))
            if parsed["unit_type"] is None:
                continue  # not a real data row
            # Heuristic split of prefix into Owner/Station/Unit:
            # Station is usually the last 1-3 tokens; we just store the
            # whole prefix and let downstream code use it as a free-text key.
            rows.append({
                "owner_station_unit": m.group("prefix").strip(),
                "zone": m.group("zone"),
                "ptid": int(m.group("ptid")),
                "town": m.group("town").strip(),
                "county_fips": m.group("cnty"),
                "state_fips": m.group("state"),
                "cod": m.group("cod"),
                **parsed,
            })
    return pd.DataFrame(rows)


# Table IV-1a (proposed) layout (2025 Gold Book):
#   Q#  Developer  ProjectName  Zone  MMM-YY  Plate  SumCRIS  WinCRIS  SumERIS  WinERIS  ProjectType  [ClassYear]  [MinDur]  Notes
# Project type is a text label like "Solar", "Land-Based Wind", "Offshore Wind",
# "Energy Storage", "Combined Cycle", etc. Notes are parenthesised.
PROPOSED_ROW_RE = re.compile(
    r"^(?P<qpos>\d{2,4})\s"
    r"(?P<prefix>.+?)\s"
    r"(?P<zone>[A-K])\s"
    r"(?P<cod>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2})\s"
    r"(?P<rest>.+)$"
)

PROJECT_TYPES = [
    "Land-Based Wind", "Offshore Wind", "Solar", "Energy Storage",
    "Combined Cycle", "Combustion Turbine", "Hydro", "Pumped Storage",
    "Fuel Cell", "Methane", "Other",
]


def parse_proposed_rest(rest: str) -> dict:
    """Parse the right-hand side of a Table IV-1a row."""
    out = {
        "plate_mw": None, "sum_cris": None, "win_cris": None,
        "sum_eris": None, "win_eris": None,
        "project_type": None, "class_year": None,
        "min_duration_hr": None, "notes": None,
    }
    # Strip trailing parenthesised notes
    notes = []
    while True:
        m = re.search(r"\s\([^)]+\)\s*$", rest)
        if not m:
            break
        notes.insert(0, m.group(0).strip())
        rest = rest[: m.start()].rstrip()
    if notes:
        out["notes"] = " ".join(notes)

    # Find the project-type label by longest match
    pt_match = None
    pt_start = -1
    for label in sorted(PROJECT_TYPES, key=len, reverse=True):
        idx = rest.find(" " + label)
        if idx >= 0:
            pt_match = label
            pt_start = idx + 1
            break
    if pt_match is None:
        return out
    out["project_type"] = pt_match

    left = rest[:pt_start].strip().split()
    right = rest[pt_start + len(pt_match):].strip().split()

    nums_left = [float(t.replace(",", "")) for t in left if NUM_RE.fullmatch(t)]
    if len(nums_left) >= 5:
        (out["plate_mw"], out["sum_cris"], out["win_cris"],
         out["sum_eris"], out["win_eris"]) = nums_left[:5]
    elif len(nums_left) >= 1:
        out["plate_mw"] = nums_left[0]

    # Right side: optional class year (4-digit) and min duration (small int)
    for tok in right:
        if re.fullmatch(r"\d{4}", tok):
            out["class_year"] = int(tok)
        elif re.fullmatch(r"\d{1,2}", tok) and out["min_duration_hr"] is None:
            out["min_duration_hr"] = int(tok)
    return out


def parse_proposed(pdf_path: Path, page_range=range(121, 133)) -> pd.DataFrame:
    """Parse Table IV-1a (proposed generator additions / CRIS requests).

    NB: column layout in IV-1a varies by Gold Book year; this parser targets
    the 2025 Gold Book layout. Validate visually against the PDF if using
    a different year.
    """
    reader = pypdf.PdfReader(str(pdf_path))
    rows = []
    for page_idx in page_range:
        if page_idx >= len(reader.pages):
            break
        text = reader.pages[page_idx].extract_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            m = PROPOSED_ROW_RE.match(line)
            if not m:
                continue
            parsed = parse_proposed_rest(m.group("rest"))
            if parsed["project_type"] is None:
                continue
            # Split prefix into Developer / Project Name heuristically:
            # the project name is typically the last 1-5 tokens. We just
            # store the whole prefix; downstream geocoding handles it.
            rows.append({
                "queue_pos": int(m.group("qpos")),
                "developer_project": m.group("prefix").strip(),
                "zone": m.group("zone"),
                "cod": m.group("cod"),
                **parsed,
            })
    return pd.DataFrame(rows)


def filter_renewables_proposed(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split a parsed proposed-generator table into wind/solar/storage."""
    if df.empty:
        return {"wind": df, "solar": df, "storage": df}
    wind = df[df.project_type.isin(["Land-Based Wind", "Offshore Wind"])].copy()
    solar = df[df.project_type == "Solar"].copy()
    storage = df[df.project_type == "Energy Storage"].copy()
    return {"wind": wind, "solar": solar, "storage": storage}


def filter_renewables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split a parsed generator table into wind / solar / storage subsets."""
    wind = df[(df.unit_type == "WT") & (df.state_fips == "36")].copy()
    solar = df[df.unit_type == "PV"].copy()
    storage = df[
        (df.unit_type == "ES") | (df.fuel1 == "BAT") | (df.fuel2 == "BAT")
    ].copy()
    return {"wind": wind, "solar": solar, "storage": storage}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--existing-pages", default="85,105",
                    help="0-indexed page range for Table III-2a/b (start,stop)")
    ap.add_argument("--proposed-pages", default="121,133",
                    help="0-indexed page range for Table IV-1a (start,stop)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    es = tuple(int(x) for x in args.existing_pages.split(","))
    ps = tuple(int(x) for x in args.proposed_pages.split(","))

    existing = parse_existing(args.pdf, range(es[0], es[1]))
    print(f"Parsed {len(existing)} existing generator rows")
    existing.to_csv(args.out / "goldbook_existing_generators.csv", index=False)

    proposed = parse_proposed(args.pdf, range(ps[0], ps[1]))
    print(f"Parsed {len(proposed)} proposed generator rows")
    proposed.to_csv(args.out / "goldbook_proposed_generators.csv", index=False)

    for kind, df in filter_renewables(existing).items():
        path = args.out / f"goldbook_ny_{kind}_existing.csv"
        df.to_csv(path, index=False)
        print(f"  existing {kind}: {len(df)} units, "
              f"{df.plate_mw.sum():.0f} MW nameplate -> {path.name}")

    if not proposed.empty:
        for kind, df in filter_renewables_proposed(proposed).items():
            path = args.out / f"goldbook_ny_{kind}_proposed.csv"
            df.to_csv(path, index=False)
            print(f"  proposed {kind}: {len(df)} units, "
                  f"{df.plate_mw.sum():.0f} MW nameplate -> {path.name}")


if __name__ == "__main__":
    main()
