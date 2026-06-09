#!/usr/bin/env python3
"""Match NYISO binding-constraint facility names to grid branches.

For each flowgate in binding_constraints_7y.csv with >= MIN_HOURS_7Y binding
hours, parse the two endpoint substation names and kV, then look for buses
in bus.csv that match and a branch in branch.csv that connects them. Writes
match_flowgates_results.csv with: facility, hours_7y, mean_cost, status
(matched / missing_branch / unmatched_name), branch UID if matched, etc.

Usage:
    python match_flowgates.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

GRID = Path(__file__).resolve().parent
SD = GRID / "grid_data/sced_inputs/SourceData"

MIN_HOURS_7Y = 200  # friend's threshold

# Manual abbrev → list of bus-name substrings to try, in priority order.
# Substrings are case-insensitive; first hit wins. The "_" in bus names is
# treated as " " before matching.
ABBREV = {
    "DUNWODIE":  ["dunwoodie"],
    "SHORE_RD":  ["shore road", "shore_rd"],
    "FRESHKLS":  ["fresh kills", "freshkills"],
    "WILLWBRK":  ["willowbrook"],
    "SPRNBRK":   ["sprain brook", "sprainbrook", "sprbrk"],
    "EGRDNCTR":  ["east garden city"],
    "EGRDNCTY":  ["east garden city"],
    "E179THST":  ["east 179th"],
    "HELLGATE":  ["hell gate", "hellgate"],
    "RAINEY":    ["rainey"],
    "VERNON":    ["vernon"],
    "VALLYSTR":  ["valley stream", "valleystream"],
    "GREENWD":   ["greenwood"],
    "ADIRNDCK":  ["adirondack"],
    "MOSES":     ["robert moses", "moses"],
    "NIAGB130":  ["niagara"],  # NB substation at 115 kV
    "PACKARD":   ["packard"],
    "GOWANUS":   ["gowanus"],
    "ASTANNEX":  ["astoria annex", "ast annex", "astoria"],
    "ASTORIAE":  ["astoria east", "astoria"],
    "ASTORIAW":  ["astoria west", "astoria"],
    "NIAGARA":   ["niagara"],
    "BUFALO78":  ["buffalo"],
    "HUNTLEY":   ["huntley"],
    "SCRIBA":    ["scriba"],
    "VOLNEY":    ["volney"],
    "CRICKVLY":  ["cricket valley", "crickvly"],
    "PLSNTVLY":  ["pleasant valley", "plsntvly"],
    "GOETHALS":  ["goethals"],
    "MOTTHAVN":  ["mott haven", "motthavn"],
    "GLENWOOD":  ["glenwood"],
    "LAKSUCSS":  ["lake success"],
    "FOXHILLS":  ["fox hills"],
    "HAUPPAUG":  ["hauppauge"],
    "PILGRIM":   ["pilgrim"],
    "BRENTWOD":  ["brentwood"],
    "ELWOOD":    ["elwood"],
    "NRTHPORT":  ["northport"],
    "GORDONRD":  ["gordon road"],
    "ROTTRDAM":  ["rotterdam"],
    "DEPOSIT":   ["deposit"],
    "INDIANHD":  ["indian head"],
    "PULASKLI":  ["pulaski"],
    "E13THSTA":  ["east 13th", "13th street"],
}

# Facility names that are zone-level interfaces, not single branches.
# These are flagged separately — they need interface constraints, not
# per-branch ratings.
INTERFACE_KEYWORDS = (
    "CENTRAL EAST", "TOTAL EAST", "UPNY", "WEST CENTRAL", "MOSES SOUTH",
    "DYSINGER", "VC", "SCH -", "INTERFACE",
)

FACILITY_RE = re.compile(
    r"^(?P<n1>\S+)\s+(?P<kv1>\d+)\s+(?P<n2>\S+)\s+(?P<kv2>\d+)\s+(?P<n>\d+)$"
)


def is_interface(name: str) -> bool:
    return any(kw in name.upper() for kw in INTERFACE_KEYWORDS)


def parse_facility(name: str) -> dict | None:
    m = FACILITY_RE.match(name.strip())
    if not m:
        return None
    return {
        "name1": m.group("n1"),
        "kv1": int(m.group("kv1")),
        "name2": m.group("n2"),
        "kv2": int(m.group("kv2")),
        "circuit": int(m.group("n")),
    }


def find_buses(abbrev: str, kv: int, bus_df: pd.DataFrame) -> pd.DataFrame:
    """Return bus rows whose name matches any candidate substring AND kV
    is within ±15 % of the requested level (transformers can shift one
    side, so we tolerate)."""
    candidates = ABBREV.get(abbrev, [abbrev.lower()])
    bnames = bus_df["Bus Name"].fillna("").str.lower().str.replace("_", " ")
    snames = bus_df["Sub Name"].fillna("").str.lower()
    mask = False
    for sub in candidates:
        mask = mask | bnames.str.contains(sub, regex=False) | snames.str.contains(sub, regex=False)
    hits = bus_df[mask]
    if len(hits) == 0:
        return hits
    # voltage filter
    target = float(kv)
    return hits[(hits["BaseKV"] >= 0.85 * target) & (hits["BaseKV"] <= 1.15 * target)]


def find_branch(bus_ids_from: set, bus_ids_to: set,
                branch_df: pd.DataFrame) -> pd.DataFrame:
    return branch_df[
        (branch_df["From Bus"].astype(int).isin(bus_ids_from)
         & branch_df["To Bus"].astype(int).isin(bus_ids_to))
        | (branch_df["From Bus"].astype(int).isin(bus_ids_to)
           & branch_df["To Bus"].astype(int).isin(bus_ids_from))
    ]


def main() -> int:
    bc = pd.read_csv(GRID / "binding_constraints_7y.csv")
    bus_df = pd.read_csv(SD / "bus.csv")
    branch_df = pd.read_csv(SD / "branch.csv")
    print(f"Loaded {len(bc):,} BC rows, {len(bus_df)} buses, {len(branch_df)} branches")

    agg = (
        bc.groupby("Limiting Facility")
        .agg(hours_7y=("Interval Start", "count"),
             mean_cost=("Constraint Cost", "mean"),
             total_cost=("Constraint Cost", "sum"))
        .reset_index()
        .sort_values("hours_7y", ascending=False)
    )
    agg = agg[agg["hours_7y"] >= MIN_HOURS_7Y]
    print(f"{len(agg)} facilities with >= {MIN_HOURS_7Y} hours")

    results = []
    for _, row in agg.iterrows():
        name = row["Limiting Facility"]
        rec = {
            "facility": name,
            "hours_7y": int(row["hours_7y"]),
            "mean_cost": round(row["mean_cost"], 2),
            "total_cost": round(row["total_cost"], 0),
        }
        if is_interface(name):
            rec.update(status="interface_constraint", branch_uid=None)
            results.append(rec)
            continue

        parsed = parse_facility(name)
        if parsed is None:
            rec.update(status="unparsable", branch_uid=None)
            results.append(rec)
            continue

        b1 = find_buses(parsed["name1"], parsed["kv1"], bus_df)
        b2 = find_buses(parsed["name2"], parsed["kv2"], bus_df)
        if len(b1) == 0 or len(b2) == 0:
            rec.update(
                status="unmatched_name",
                branch_uid=None,
                n1=parsed["name1"], kv1=parsed["kv1"],
                n2=parsed["name2"], kv2=parsed["kv2"],
                hits1=len(b1), hits2=len(b2),
            )
            results.append(rec)
            continue

        ids1 = set(b1["Bus ID"].astype(int))
        ids2 = set(b2["Bus ID"].astype(int))
        br = find_branch(ids1, ids2, branch_df)
        if len(br) > 0:
            uid = br.iloc[0]["UID"]
            rec.update(
                status="matched",
                branch_uid=uid,
                cur_rating=float(br.iloc[0]["Cont Rating"]),
                n1=parsed["name1"], n2=parsed["name2"],
                kv=parsed["kv1"],
            )
        else:
            rec.update(
                status="missing_branch",
                branch_uid=None,
                bus1=sorted(ids1)[0],
                bus2=sorted(ids2)[0],
                n1=parsed["name1"], n2=parsed["name2"],
                kv=parsed["kv1"],
            )
        results.append(rec)

    out = pd.DataFrame(results)
    out_path = GRID / "match_flowgates_results.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")

    print("\n=== Status breakdown ===")
    print(out["status"].value_counts().to_string())

    print("\n=== Top matched (existing branches to calibrate) ===")
    mtc = out[out["status"] == "matched"].sort_values("hours_7y", ascending=False)
    print(mtc.head(20).to_string(index=False))

    print("\n=== Top missing_branch (add these if confident) ===")
    miss = out[out["status"] == "missing_branch"].sort_values("hours_7y", ascending=False)
    print(miss.head(15).to_string(index=False))

    print("\n=== Top unmatched (need manual abbrev lookup) ===")
    unm = out[out["status"] == "unmatched_name"].sort_values("hours_7y", ascending=False)
    print(unm.head(15).to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
