#!/usr/bin/env python3
"""Apply branch ratings + add missing branches identified by
match_flowgates.py (P0.1 from OPEN_ISSUES.md).

Source of decisions:
  - Existing branches we matched against frequently-binding flowgates get
    Method C ratings: max(observed_flow × 1.15, voltage_floor).
  - Friend's `ajoutmalin.md` calls out specific exceptions (e.g. L224_227
    must stay unconstrained or Zone D collapses).
  - Missing branches between buses already in bus.csv are added with R/X
    derived from haversine distance and typical line per-km impedance.

Always writes a backup of branch.csv to branch_backup_<timestamp>.csv
before mutating.
"""
from __future__ import annotations

import math
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

GRID = Path(__file__).resolve().parent
SD = GRID / "grid_data/sced_inputs/SourceData"

# ─── Existing branches: UID → calibrated rating MVA ──────────────────────
# Floor by voltage class is enforced separately. None = keep current value.
CALIBRATIONS = {
    # NYISO officially-published interface flowgates
    "LTP_K_Y50_SHR_DUN":   None,    # 1300 MVA, NYISO official, keep
    "LTP_K_Y49_EGC_SPR":   None,    # 1300 MVA, NYISO official, keep
    # New ratings from observed-flow method
    "L58_426":            1200.0,   # Cricket Valley ↔ Pleasant Valley 345 kV
    "OSM_J_345_0004":      900.0,   # Goethals ↔ Gowanus 345 kV
    "OSM_J_345_0003":      900.0,   # Farragut ↔ Gowanus 345 kV
    "L316_320":            850.0,   # Packard ↔ Sawyer 230 kV (Zone A).
                                    # Bumped 700 → 850: was 102% under
                                    # 2019 July loads, driving Zone A LMP
                                    # to $1.8k via PTDF amplification.
                                    # 850 fits friend's 230 kV typical
                                    # range and was the originally-shipped
                                    # 999,999 line we'd had to constrain
                                    # from observed flow × 1.15.
    "OSM_K_138_0026":      900.0,   # Oakwood ↔ Syosset 138 kV (LI double-ckt;
                                    # bumped from 600 → 900: was binding at
                                    # 100 % all 24 hours under correct loading,
                                    # producing $4k/MWh LMP spikes peak hours.
                                    # 900 is the upper end of friend's empirical
                                    # 138 kV double-circuit range 500–900 MVA.)
    "L399_400":           1000.0,   # Station_122 ↔ Clay_Station 345 kV
                                    # (Zone B ↔ C). Source shipped at 630 MVA
                                    # which is atypically low for 345 kV; was
                                    # 105 % loaded under correct ties. Bumped
                                    # to mid-range of friend's "345 kV: 800–
                                    # 1500 MVA" rule.
    # Explicitly DO NOT calibrate (friend's warning, would collapse Zone D)
    "L224_227":            None,    # Scriba ↔ Volney 345 kV — keep 999_999
}

# ─── New branches to add (missing in branch.csv, both buses already exist)
# Source: missing_branch entries from match_flowgates_results.csv plus
# friend's specific call-outs in ajoutmalin.md.
NEW_BRANCHES = [
    # (uid_suffix, bus_from, bus_to, kV, rating_MVA, reason)
    ("E179_HELLGATE_138", 10120, 10125, 138, 450, "E179THST↔HELLGATE 138 (12,980h)"),
    ("GREENWD_VERNON_138", 10124, 10134, 138, 450, "GREENWD↔VERNON 138 (9,909h, friend's #1)"),
    ("MOTTHAVN_DUNW_345_1", 10106, 451, 345, 1200, "MOTTHAVN↔DUNWODIE 345 ckt 1 (2,941h)"),
    ("MOTTHAVN_DUNW_345_2", 10106, 451, 345, 1200, "MOTTHAVN↔DUNWODIE 345 ckt 2 (799h)"),
    ("MOTTHAVN_RAINEY_345_1", 10106, 10107, 345, 1200, "MOTTHAVN↔RAINEY 345 ckt 1 (2,468h)"),
    ("MOTTHAVN_RAINEY_345_2", 10106, 10107, 345, 1200, "MOTTHAVN↔RAINEY 345 ckt 2 (1,252h)"),
    ("PLSNTVLY_LEEDS_345", 426, 359, 345, 1200, "PLSNTVLY↔LEEDS 345 (414h)"),
]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def line_pu(dist_km: float, kv: float, mva_base: float = 100.0):
    z_base = (kv ** 2) / mva_base
    if kv >= 300:
        r_per_km, x_per_km = 0.03, 0.30
    elif kv >= 100:
        r_per_km, x_per_km = 0.05, 0.40
    else:
        r_per_km, x_per_km = 0.08, 0.45
    return (r_per_km * dist_km / z_base,
            x_per_km * dist_km / z_base)


def main() -> int:
    branch = pd.read_csv(SD / "branch.csv")
    bus = pd.read_csv(SD / "bus.csv")
    bus_xy = {int(r["Bus ID"]): (r["lat"], r["lng"]) for _, r in bus.iterrows()}
    bus_kv = {int(r["Bus ID"]): float(r["BaseKV"]) for _, r in bus.iterrows()}

    # Backup
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = SD / f"branch_backup_{stamp}.csv"
    shutil.copy(SD / "branch.csv", backup)
    print(f"Backup → {backup.name}")

    # ── Calibrations on existing branches
    n_cal = 0
    for uid, new_rating in CALIBRATIONS.items():
        if new_rating is None:
            continue
        mask = branch["UID"] == uid
        if not mask.any():
            print(f"  WARN: branch {uid} not found in branch.csv")
            continue
        old = float(branch.loc[mask, "Cont Rating"].iloc[0])
        branch.loc[mask, "Cont Rating"] = float(new_rating)
        print(f"  Calibrated {uid}: {old:>10,.0f} → {new_rating:>6,.0f} MVA")
        n_cal += 1
    print(f"Total calibrations applied: {n_cal}")

    # ── New branches. Idempotency is by UID, not bus-pair, so parallel
    # circuits (same endpoints, different UID) are allowed but the same
    # UID is never added twice on re-runs.
    existing_uids = set(branch["UID"].astype(str).tolist())

    new_rows = []
    for suffix, bf, bt, kv, rating, reason in NEW_BRANCHES:
        if bf not in bus_xy or bt not in bus_xy:
            print(f"  WARN: skipping {suffix} — bus IDs not in bus.csv")
            continue
        uid = f"NYISO_{suffix}"
        if uid in existing_uids:
            print(f"  Skipping {uid} — already in branch.csv")
            continue
        lat1, lon1 = bus_xy[bf]
        lat2, lon2 = bus_xy[bt]
        dist = haversine_km(lat1, lon1, lat2, lon2)
        if dist > 150:
            print(f"  WARN: skipping {suffix} — distance {dist:.0f} km implausible for {kv} kV")
            continue
        r_pu, x_pu = line_pu(dist, kv)
        new_rows.append({
            "UID": uid,
            "From Bus": bf,
            "To Bus": bt,
            "R": round(r_pu, 6),
            "X": round(x_pu, 6),
            "B": 0.0,
            "Cont Rating": float(rating),
            "Short Term Rating": float(rating) * 1.2,
            "Emergency Rating": float(rating) * 1.4,
            "In Service": True,
            "Branch Type": "Line",
        })
        print(f"  Added {uid}: {bf}↔{bt} {kv} kV, {dist:.0f} km, {rating} MVA — {reason}")

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        # Pad missing cols
        for c in branch.columns:
            if c not in new_df.columns:
                new_df[c] = None
        new_df = new_df[branch.columns]
        branch = pd.concat([branch, new_df], ignore_index=True)
    print(f"Total branches added: {len(new_rows)}")

    branch.to_csv(SD / "branch.csv", index=False)
    print(f"\nbranch.csv: {len(branch)} branches written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
