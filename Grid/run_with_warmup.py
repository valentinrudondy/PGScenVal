#!/usr/bin/env python3
"""Run a chained two-day Vatic SCED: warmup day → target day.

Solves the P1.2 stale init_state problem from OPEN_ISSUES.md. The shipped
init_state.csv has every renewable flagged "on for 1000 hours" and every
thermal at ±1000h (max UC flexibility, no time-of-day awareness). A real
chained run produces a target-date init state that reflects the previous
day's commitment decisions.

Workflow:
  1. Compute warmup_date = target_date − 1
  2. Fetch warmup-day NYISO load if not cached
  3. Run SCED for warmup_date with LAST_CONDITIONS_FILE set
  4. Run SCED for target_date with INIT_STATE_OVERRIDE pointing to the
     warmup output

Both SCED runs use the same calibrated grid (`branch.csv` with our
ratings + ties). The warmup run gets EXPERIMENT_TAG=warmup_<date>; the
target run uses whatever EXPERIMENT_TAG the caller sets.

Usage:
    python run_with_warmup.py --date 2025-07-20 --tag chained
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date as date_cls, timedelta
from pathlib import Path

GRID = Path(__file__).resolve().parent
SCED_DIR = GRID / "grid_data/sced_inputs"
LOAD_DIR = GRID / "grid_data"


def _hourly_load_path(d: date_cls) -> Path:
    return LOAD_DIR / f"hourly_load_{d.strftime('%Y%m%d')}.csv"


def _warmup_conds_path(d: date_cls) -> Path:
    """Where the warmup run writes its end-of-day conditions."""
    return SCED_DIR / f"last_conditions_{d.strftime('%Y%m%d')}.csv"


def _ensure_load_csv(d: date_cls) -> Path:
    p = _hourly_load_path(d)
    if p.exists():
        return p
    print(f"[orchestrator] Fetching NYISO load for {d}...", flush=True)
    subprocess.run(
        [sys.executable, str(GRID / "fetch_nyiso_load.py"),
         "--date", d.isoformat()],
        check=True,
    )
    if not p.exists():
        raise RuntimeError(f"fetch_nyiso_load.py did not produce {p}")
    return p


def _run_sced(target_date: date_cls, tag: str,
              hourly_load: Path,
              init_state_override: Path | None = None,
              last_conditions_file: Path | None = None) -> int:
    env = dict(os.environ)
    env["SCED_DATE"] = target_date.isoformat()
    env["EXPERIMENT_TAG"] = tag
    env["HOURLY_LOAD_CSV"] = str(hourly_load)
    env["INIT_STATE_OVERRIDE"] = str(init_state_override) if init_state_override else ""
    env["LAST_CONDITIONS_FILE"] = str(last_conditions_file) if last_conditions_file else ""

    print(f"\n[orchestrator] === SCED for {target_date} (tag={tag}) ===", flush=True)
    print(f"[orchestrator]   HOURLY_LOAD_CSV    = {hourly_load.name}", flush=True)
    if init_state_override:
        print(f"[orchestrator]   INIT_STATE_OVERRIDE = {init_state_override.name}", flush=True)
    if last_conditions_file:
        print(f"[orchestrator]   LAST_CONDITIONS    = {last_conditions_file.name}", flush=True)
    proc = subprocess.run(
        [sys.executable, str(GRID / "run_sced.py")], env=env
    )
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", required=True, help="Target SCED date, ISO format")
    ap.add_argument("--tag", default="chained", help="EXPERIMENT_TAG for target run")
    ap.add_argument("--skip-warmup-if-cached", action="store_true",
                    help="Reuse last_conditions if it already exists")
    args = ap.parse_args()

    target = date_cls.fromisoformat(args.date)
    warmup = target - timedelta(days=1)

    target_load = _ensure_load_csv(target)
    warmup_load = _ensure_load_csv(warmup)

    warmup_conds = _warmup_conds_path(warmup)

    # ─── Step 1: warmup day ───────────────────────────────────────────
    if args.skip_warmup_if_cached and warmup_conds.exists():
        print(f"[orchestrator] Reusing cached warmup conditions at {warmup_conds.name}")
    else:
        rc = _run_sced(
            target_date=warmup,
            tag=f"warmup_{warmup.strftime('%Y%m%d')}",
            hourly_load=warmup_load,
            init_state_override=None,            # warmup starts from shipped init
            last_conditions_file=warmup_conds,    # … and writes here
        )
        if rc != 0:
            print(f"[orchestrator] Warmup SCED failed (rc={rc})", file=sys.stderr)
            return rc
        if not warmup_conds.exists():
            print(f"[orchestrator] Warmup completed but {warmup_conds} not written",
                  file=sys.stderr)
            return 1

    # ─── Step 2: target day with chained init ─────────────────────────
    rc = _run_sced(
        target_date=target,
        tag=args.tag,
        hourly_load=target_load,
        init_state_override=warmup_conds,
        last_conditions_file=None,                # don't need to chain further
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
