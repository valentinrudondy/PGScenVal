import bz2
import os
import pickle
import sys
from pathlib import Path
from datetime import datetime

# ─── PARAMETERS ───────────────────────────────────────────
date  = "2018-06-15"              # ← change this date
types = ["load", "wind", "solar"] # ← keep what you need
out_dir = "/Users/val/Desktop/Princeton"
# ──────────────────────────────────────────────────────────

os.chdir(out_dir)


def _ensure_local_pgscen_on_path() -> None:
    root = Path(out_dir).resolve()
    for candidate in (root / "PGscen-new", root / "PGscen-main"):
        if candidate.is_dir():
            sys.path.insert(0, str(candidate))
            return
    raise ModuleNotFoundError(
        f"Could not find a local PGscen package in {root}."
    )


def _run_pgscen(asset_type: str, scenario_date: str) -> None:
    _ensure_local_pgscen_on_path()
    from pgscen import command_line

    command_map = {
        "load": command_line.create_load_scenarios,
        "wind": command_line.create_wind_scenarios,
        "solar": command_line.create_solar_scenarios,
    }
    if asset_type not in command_map:
        raise ValueError(f"Unsupported asset type: {asset_type}")

    old_argv = sys.argv[:]
    try:
        sys.argv = [f"pgscen-{asset_type}", scenario_date, "1", "-p"]
        command_map[asset_type]()
    finally:
        sys.argv = old_argv

for t in types:
    print(f"\nGenerating {t} scenarios for {date}...")
    _run_pgscen(t, date)

    d = datetime.strptime(date, "%Y-%m-%d")
    pkl = f"{out_dir}/scens_{d.year}-{str(d.month).zfill(2)}-{str(d.day).zfill(2)}.p.gz"

    with bz2.open(pkl, "rb") as f:
        data = pickle.load(f)

    for key, df in data.items():
        out = f"{out_dir}/{t}_{key.lower()}_{date}.csv"
        df.to_csv(out)
        print(f"Done: {out}")

print("\nAll CSV files created successfully!")
