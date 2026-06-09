"""Populate data/nyiso_cache/<year>/fuel_mix/ for 2018-2024 using the existing
NyisoDownloader. Idempotent — skips months already cached.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Vatic"))

from vatic.data.nyiso_downloader import NyisoDownloader  # noqa: E402

YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024]


def main() -> None:
    d = NyisoDownloader()
    for year in YEARS:
        print(f"=== fuel_mix {year} ===", flush=True)
        try:
            path = d.download_fuel_mix(year)
            print(f"  ok → {path}", flush=True)
        except Exception as exc:
            print(f"  FAIL {year}: {exc}", flush=True)


if __name__ == "__main__":
    main()
