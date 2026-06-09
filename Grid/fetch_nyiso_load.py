#!/usr/bin/env python3
"""Fetch NYISO MIS Integrated Real-Time Actual Load (palIntegrated) for one
day and write a 24-row hourly CSV in the format ``run_sced.py`` expects.

Output columns: Zone_A, Zone_B, ..., Zone_K (one column per NYISO zone),
24 rows ordered hour 0..23 local time of the requested date.

Usage:
    python fetch_nyiso_load.py --date 2025-07-20
    python fetch_nyiso_load.py --year 2025 --month 7 --day 20

Cached files land under ``grid_data/hourly_load_YYYYMMDD.csv``; the URL we
hit is the monthly ZIP at
``http://mis.nyiso.com/public/csv/palIntegrated/YYYYMM01palIntegrated_csv.zip``.
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from datetime import date as date_cls
from pathlib import Path
from urllib.request import urlopen, Request

import pandas as pd

NYISO_ZONES = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"]
NYISO_ZONE_NAMES = {
    "WEST": "A", "GENESE": "B", "CENTRL": "C", "NORTH": "D",
    "MHK VL": "E", "CAPITL": "F", "HUD VL": "G", "MILLWD": "H",
    "DUNWOD": "I", "N.Y.C.": "J", "LONGIL": "K",
}

GRID_DIR = Path(__file__).resolve().parent
OUT_DIR = GRID_DIR / "grid_data"


def _fetch_month_zip(year: int, month: int) -> bytes:
    url = (
        f"http://mis.nyiso.com/public/csv/palIntegrated/"
        f"{year:04d}{month:02d}01palIntegrated_csv.zip"
    )
    print(f"  GET {url}", file=sys.stderr)
    req = Request(url, headers={"User-Agent": "grid-fetch/1.0"})
    with urlopen(req, timeout=60) as resp:
        return resp.read()


def _parse_zip_to_day(zip_bytes: bytes, target: date_cls) -> pd.DataFrame:
    target_csv = f"{target.year:04d}{target.month:02d}{target.day:02d}palIntegrated.csv"
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if target_csv not in names:
            raise FileNotFoundError(
                f"{target_csv} not in zip; available: {names[:5]}..."
            )
        with zf.open(target_csv) as f:
            df = pd.read_csv(f)
    df["Time Stamp"] = pd.to_datetime(df["Time Stamp"])
    df["zone"] = df["Name"].map(NYISO_ZONE_NAMES)
    df = df.dropna(subset=["zone"])
    df["hour"] = df["Time Stamp"].dt.hour
    hourly = (
        df.groupby(["hour", "zone"])["Integrated Load"]
        .mean()
        .unstack("zone")
        .reindex(columns=NYISO_ZONES)
        .reindex(range(24))
    )
    hourly.columns = [f"Zone_{z}" for z in hourly.columns]
    hourly.index.name = "hour"
    return hourly


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--date", help="ISO date, e.g. 2025-07-20")
    g.add_argument("--year", type=int, help="Year (with --month --day)")
    ap.add_argument("--month", type=int)
    ap.add_argument("--day", type=int)
    args = ap.parse_args()

    if args.date:
        target = date_cls.fromisoformat(args.date)
    else:
        if args.month is None or args.day is None:
            ap.error("--year requires --month and --day")
        target = date_cls(args.year, args.month, args.day)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fetching NYISO palIntegrated for {target}", file=sys.stderr)
    zip_bytes = _fetch_month_zip(target.year, target.month)
    hourly = _parse_zip_to_day(zip_bytes, target)

    out_path = OUT_DIR / f"hourly_load_{target.strftime('%Y%m%d')}.csv"
    hourly.to_csv(out_path)
    print(f"Wrote {out_path}", file=sys.stderr)
    print(f"Daily peak: {hourly.sum(axis=1).max():,.0f} MW at hour "
          f"{hourly.sum(axis=1).idxmax()}", file=sys.stderr)
    print(f"Daily mean: {hourly.sum(axis=1).mean():,.0f} MW", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
