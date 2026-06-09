#!/usr/bin/env python3
"""
NYISO DC-SCED Runner — adapted from ERCOT run_sced.py.

Loads the OSM-native bus/branch/gen/storage tables, distributes zonal load,
builds renewable timeseries, and runs the Vatic DC-SCED simulator.

Environment variables (all optional):
  SCED_DATE          — simulation date (default: 2025-07-20, summer peak)
  EXPERIMENT_TAG     — results directory suffix (default: "baseline")
  DARTBOARD_SCRATCH  — cluster scratch dir (triggers Gurobi solver)
  HOURLY_LOAD_CSV    — hourly zonal load CSV (zones A-K)
  HOURLY_CF_CSV      — hourly wind/solar CF CSV (overrides PGscen)
  PGSCEN_DIR         — PGscen-2nd/data/NYISO_real path. Auto-detected at
                       sibling ../PGscen-2nd/data/NYISO_real if unset.
                       Set to empty string to disable.
  BRANCH_SCALE       — multiply all branch ratings (0 = unconstrained)
  STORAGE_AGGREGATE  — "zone" (default), "bus", or "none"
  LOAD_NAMED_ONLY    — 1 to restrict load to named substations

Usage:
  python run_sced.py                    # local (CBC solver)
  sbatch run_sced_array.slurm           # cluster (Gurobi solver)
"""

import csv
import json
import math
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import numpy as np
import networkx as nx

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
SCED_DATE_STR  = os.environ.get("SCED_DATE", "2025-07-20")
EXPERIMENT_TAG = os.environ.get("EXPERIMENT_TAG",
                 os.environ.get("SCED_INSTANCE", "baseline"))
SCRATCH        = os.environ.get("DARTBOARD_SCRATCH", "")
BRANCH_SCALE   = float(os.environ.get("BRANCH_SCALE", "1"))
STORAGE_AGG    = os.environ.get("STORAGE_AGGREGATE", "zone")
LOAD_NAMED     = os.environ.get("LOAD_NAMED_ONLY", "0") == "1"
HOURLY_LOAD    = os.environ.get("HOURLY_LOAD_CSV", "")
HOURLY_CF      = os.environ.get("HOURLY_CF_CSV", "")
# Chained-init hooks: override the shipped init_state.csv with a previous
# day's last_conditions output (P1.2). LAST_CONDITIONS_FILE controls where
# this run writes its own end-of-day state.
INIT_STATE_OVERRIDE = os.environ.get("INIT_STATE_OVERRIDE", "")
LAST_CONDITIONS_FILE = os.environ.get("LAST_CONDITIONS_FILE", "")

# PGscen integration. When set (or auto-detected), per-site wind/solar
# actuals + day-ahead forecasts replace the constant-CF defaults. Solving
# the "solar=267 MW at midnight" bug. HOURLY_CF_CSV still wins if explicitly
# set.
_PGSCEN_ENV = os.environ.get("PGSCEN_DIR", None)
if _PGSCEN_ENV is None:
    _auto = Path(__file__).resolve().parent.parent / "PGscen-2nd" / "data" / "NYISO_real"
    PGSCEN_DIR = _auto if _auto.exists() else None
elif _PGSCEN_ENV == "":
    PGSCEN_DIR = None
else:
    PGSCEN_DIR = Path(_PGSCEN_ENV) if Path(_PGSCEN_ENV).exists() else None

SCED_DATE = date.fromisoformat(SCED_DATE_STR)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
if SCRATCH:
    BASE     = Path(SCRATCH)
    DATA     = BASE / "grid_data"
    SCED_DIR = BASE / f"sced_inputs_{EXPERIMENT_TAG}"
    SRC_DIR  = DATA / "sced_inputs" / "SourceData"     # read-only canonical
    RES_DIR  = SCED_DIR / f"results_{EXPERIMENT_TAG}"
    WORK_DIR = SCED_DIR / "work"                       # mutable per-run
    USE_GUROBI = True
    THREADS  = int(os.environ.get("SLURM_CPUS_PER_TASK", "8"))
else:
    NYISO_DIR = Path(__file__).resolve().parent
    DATA      = NYISO_DIR / "grid_data"
    SCED_DIR  = DATA / "sced_inputs"
    SRC_DIR   = SCED_DIR / "SourceData"                # read-only canonical
    RES_DIR   = SCED_DIR / f"results_{EXPERIMENT_TAG}"
    WORK_DIR  = RES_DIR / "work"                       # mutable per-run
    USE_GUROBI = True
    THREADS  = 4

# Source data is owned by calibrate_branches.py — run_sced.py must not
# mutate it. Copy CSVs to WORK_DIR on each run; all reads/writes below
# operate on WORK_DIR. (P2.5 fix.)
if not SRC_DIR.exists():
    raise FileNotFoundError(
        f"Source data not found: {SRC_DIR}. Run calibrate_branches.py first "
        f"or check Grid/grid_data layout."
    )
WORK_DIR.mkdir(parents=True, exist_ok=True)
RES_DIR.mkdir(parents=True, exist_ok=True)
for _name in ("branch.csv", "bus.csv", "gen.csv", "init_state.csv", "storage.csv"):
    _src = SRC_DIR / _name
    if _src.exists():
        shutil.copy(_src, WORK_DIR / _name)

# ---------------------------------------------------------------------------
# NYISO zone load distribution
# ---------------------------------------------------------------------------
# Gold Book 2025 summer coincident peak demands (MW)
# Zones H (Millwood) and I (Dunwoodie) are sub-county, merged into G at
# polygon level. For load distribution we allocate G+H+I as one block
# and the DC-SCED treats it as zone G buses.
ZONE_LOAD_MW = {
    "A": 2_864.0,   # West
    "B": 1_855.0,   # Genesee
    "C": 2_516.0,   # Central
    "D":   691.0,   # North
    "E": 1_310.0,   # Mohawk Valley
    "F": 2_269.0,   # Capital
    "G": 4_199.0,   # Hudson Valley + Millwood + Dunwoodie (2264+619+1316)
    "J": 10_764.0,  # New York City
    "K": 5_003.0,   # Long Island
}
# Total: ~31,471 MW

# Default renewable capacity factors (constant; overridden by HOURLY_CF_CSV)
DEFAULT_CF = {"Wind": 0.30, "Solar": 0.10, "Hydro": 0.50}

# ---------------------------------------------------------------------------
# DC tie / interconnection injections (fixed MW imports)
#
# NYISO imports from: HQ (Zone D), PJM (Zones A, F, G, J), ISO-NE (Zones K, F)
# These are rough annual average scheduled interchanges.
# Positive = import into NYISO (reduces load at boundary bus).
# ---------------------------------------------------------------------------
# Explicit Bus ID targets (no keyword-search fallbacks). Bus Names alone are
# not unique — bus.csv has at least 4 rows whose Bus Name collides with
# another row (Goethals and East 36th Street each appear twice as draft
# CEII duplicates). Each entry: (Bus ID, import_MW, human-readable label).
DC_TIES = [
    (335,   1200.0, "HQ (Chateauguay+Phase II) @ Massena 765kV"),
    (390,    500.0, "Ontario @ Robert Moses 345kV"),
    (410,    600.0, "PJM Ramapo 500kV"),
    (10104,  300.0, "PJM Linden VFT @ Goethals 345kV"),
    (10153,  100.0, "ISO-NE Cross Sound Cable @ Shoreham"),
]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# PGscen helpers — site/load lookup, UTC→Eastern alignment
# ---------------------------------------------------------------------------
# PGscen-2nd ships UTC-timestamped CSVs; run_sced.py builds its dt_index from
# pd.Timestamp(SCED_DATE) + h, interpreted as Eastern wall time (same as
# fetch_nyiso_load.py output). Convert PGscen tz-aware UTC index to
# America/New_York (DST-aware) then strip tz so it aligns by label.

# Some 2018+ wind CSVs carry the `.pluswind_v3` infix (wind-model paper);
# accept both names.
def _find_pgscen_renew_csv(pgscen_dir, kind, series, year):
    """kind: 'wind'|'solar'   series: 'actual'|'day_ahead_forecast'"""
    sub = pgscen_dir / kind
    if not sub.exists():
        return None
    infix = "1h_site_" if series == "actual" else "site_"
    bare = f"{kind}_{series}_{infix}{year}_utc.csv"
    for cand in (sub / bare,
                 sub / f"{bare[:-4]}.pluswind_v3.csv"):
        if cand.exists():
            return cand
    return None


def _to_eastern_naive(idx):
    """Tz-aware → naive Eastern. Idempotent on already-naive index."""
    if idx.tz is None:
        return idx
    return idx.tz_convert("America/New_York").tz_localize(None)


def _load_pgscen_renew(pgscen_dir, year, dt_index):
    """Load wind+solar actuals + day-ahead forecasts for the year, slice to
    dt_index in Eastern naive time. Returns ``{"Wind": {...}, "Solar":
    {...}}`` with each inner dict carrying ``actl_site`` and ``fcst_site``
    DataFrames (MW per site) and ``actl_cf`` / ``fcst_cf`` 48h capacity-
    factor Series (system-aggregate output ÷ summed nameplate).

    Returns empty dict if no PGscen files exist for the year (e.g. SCED
    date past PGscen coverage).
    """
    out = {}
    for kind in ("Wind", "Solar"):
        kind_low = kind.lower()
        actual = _find_pgscen_renew_csv(pgscen_dir, kind_low, "actual", year)
        forecast = _find_pgscen_renew_csv(pgscen_dir, kind_low, "day_ahead_forecast", year)
        if actual is None or forecast is None:
            continue

        wa = pd.read_csv(actual, parse_dates=["Time"], index_col="Time")
        wa.index = _to_eastern_naive(wa.index)
        # DST fall-back makes two distinct UTC hours collapse to the same
        # naive Eastern label; keep the first to satisfy reindex.
        wa = wa[~wa.index.duplicated(keep="first")]
        wf = pd.read_csv(forecast, parse_dates=["Forecast_time"])
        if "Issue_time" in wf.columns:
            wf = wf.drop(columns=["Issue_time"])
        wf = wf.set_index("Forecast_time")
        wf.index = _to_eastern_naive(wf.index)
        wf = wf[~wf.index.duplicated(keep="first")]

        wa_slice = wa.reindex(dt_index).fillna(0).clip(lower=0)
        wf_slice = wf.reindex(dt_index).fillna(0).clip(lower=0)

        meta = pgscen_dir / "plant_metadata" / f"{kind_low}_meta.csv"
        nameplate_total = 0.0
        if meta.exists():
            md = pd.read_csv(meta)
            if "operating_year" in md.columns:
                md = md[md["operating_year"] <= year]
            covered = set(wa_slice.columns)
            nameplate_total = float(
                md[md["site_id"].isin(covered)]["nameplate_mw"].sum()
            )
        if nameplate_total <= 0:
            nameplate_total = max(wa_slice.sum(axis=1).max(), 1.0)

        actl_cf = wa_slice.sum(axis=1) / nameplate_total
        fcst_sum = wf_slice.sum(axis=1)
        fcst_cf = (fcst_sum / nameplate_total) if (fcst_sum > 0).any() else actl_cf

        out[kind] = {
            "actl_site": wa_slice,
            "fcst_site": wf_slice,
            "actl_cf":   actl_cf,
            "fcst_cf":   fcst_cf,
            "nameplate_total": nameplate_total,
        }
    return out


def _build_pgscen_site_map(gen_df, bus_df, pgscen_dir, year):
    """Map each PGscen wind/solar site to the nearest unused gen of the same
    fuel in the same zone (cross-zone fallback). Returns
    ``{site_id: gen_uid}``.

    "Unused" matters: with naive nearest-match, multiple sites collapsed
    onto the same gen (CHANGES.md notes 25 sites → 11 gens in an early
    pass), producing duplicate gen_data columns that crash Vatic.
    """
    meta_dir = pgscen_dir / "plant_metadata"
    bus_lookup = bus_df.set_index("Bus ID")[["Zone", "lat", "lng"]].to_dict("index")
    gens_by_fuel = defaultdict(list)
    for _, g in gen_df.iterrows():
        if g["Fuel"] not in ("Wind", "Solar"):
            continue
        bid = int(g["Bus ID"])
        info = bus_lookup.get(bid)
        if not info:
            continue
        gens_by_fuel[g["Fuel"]].append({
            "uid": g["GEN UID"], "zone": info["Zone"],
            "lat": float(info["lat"]), "lng": float(info["lng"]),
        })

    site_map = {}
    for kind, fname in [("Wind", "wind_meta.csv"), ("Solar", "solar_meta.csv")]:
        p = meta_dir / fname
        if not p.exists():
            continue
        meta = pd.read_csv(p)
        if "operating_year" in meta.columns:
            meta = meta[meta["operating_year"] <= year]
        used = set()
        for _, row in meta.iterrows():
            site_id = row["site_id"]
            zone = row.get("zone")
            try:
                lat = float(row["latitude"]); lon = float(row["longitude"])
            except (KeyError, ValueError, TypeError):
                continue
            best, best_d = None, float("inf")
            # Prefer unused gen in same zone
            for g in gens_by_fuel[kind]:
                if g["uid"] in used or g["zone"] != zone:
                    continue
                d = haversine_km(lat, lon, g["lat"], g["lng"])
                if d < best_d:
                    best_d, best = d, g["uid"]
            if best is None:
                # Cross-zone fallback
                for g in gens_by_fuel[kind]:
                    if g["uid"] in used:
                        continue
                    d = haversine_km(lat, lon, g["lat"], g["lng"])
                    if d < best_d:
                        best_d, best = d, g["uid"]
            if best is not None:
                site_map[site_id] = best
                used.add(best)
    return site_map


# ---------------------------------------------------------------------------
# Step 1: Apply branch rating modifications
# ---------------------------------------------------------------------------
print(f"=== NYISO SCED — {SCED_DATE_STR} (tag: {EXPERIMENT_TAG}) ===")
print(f"  Solver: {'Gurobi' if USE_GUROBI else 'CBC'}")

branch_path = WORK_DIR / "branch.csv"
branch = pd.read_csv(branch_path)
print(f"\nStep 1: Branch ratings ({len(branch)} branches)")

if BRANCH_SCALE != 1.0:
    if BRANCH_SCALE == 0:
        branch["Cont Rating"] = 999_999.0
        print(f"  BRANCH_SCALE=0 → all branches unconstrained")
    else:
        branch["Cont Rating"] *= BRANCH_SCALE
        print(f"  BRANCH_SCALE={BRANCH_SCALE} applied")

branch.to_csv(branch_path, index=False)

# ---------------------------------------------------------------------------
# Step 2: Distribute zonal load to buses
# ---------------------------------------------------------------------------
print("\nStep 2: Load distribution")

bus_path = WORK_DIR / "bus.csv"
bus = pd.read_csv(bus_path)

# Area/Sub Area follow zone letter (A=1 … K=9). A few NYC ConEd buses
# (Newtown, Goethals, Willowbrook, Woodrow) ship with NaN — the README
# flags this as draft CEII-not-public topology. We fill from the zone
# letter so Vatic's parse_bus (int cast) doesn't crash, but the
# underlying data should be reconciled with the grid maintainer.
_zone_to_area = {z: i for i, z in enumerate("ABCDEFGHIJK", start=1)}
_zone_area = bus["Zone"].map(_zone_to_area)
_nan_mask = bus["Area"].isna() | bus["Sub Area"].isna()
if _nan_mask.any():
    print(f"  Filled Area/Sub Area for {_nan_mask.sum()} NaN buses (Zone-derived): "
          + ", ".join(bus.loc[_nan_mask, "Bus Name"].tolist()))
bus["Area"] = bus["Area"].fillna(_zone_area)
bus["Sub Area"] = bus["Sub Area"].fillna(_zone_area)

# Uniquify Bus Name. Vatic dedupes buses by name when building the
# template, so duplicate names silently collapse load onto one bus. The
# current grid has at least 2 collision pairs (Goethals 10104/10197 and
# East_36th_Street 10121/10206); for the duplicate, append "__busN" so
# every bus survives into the template.
_dup_mask = bus["Bus Name"].duplicated(keep="first")
if _dup_mask.any():
    bus.loc[_dup_mask, "Bus Name"] = (
        bus.loc[_dup_mask, "Bus Name"].astype(str)
        + "__bus"
        + bus.loc[_dup_mask, "Bus ID"].astype(str)
    )
    print(f"  Uniquified {_dup_mask.sum()} duplicate Bus Names: "
          + ", ".join(bus.loc[_dup_mask, "Bus Name"].tolist()))

# Census 2020 NY county population for weighting
# (top counties only — the rest get equal weight)
NY_COUNTY_POP = {
    "Kings": 2736074, "Queens": 2405464, "New York": 1694251,
    "Suffolk": 1525920, "Bronx": 1472654, "Nassau": 1395774,
    "Westchester": 1004457, "Erie": 954236, "Monroe": 759443,
    "Richmond": 495747, "Onondaga": 476516, "Orange": 401310,
    "Rockland": 338329, "Albany": 314848, "Dutchess": 295911,
    "Saratoga": 235509, "Oneida": 232125, "Niagara": 212666,
    "Broome": 198683, "Ulster": 181851, "Rensselaer": 161130,
    "Schenectady": 158061, "Chautauqua": 127657, "Oswego": 117525,
    "Jefferson": 116721, "Ontario": 112458, "St. Lawrence": 108505,
    "Tompkins": 105740, "Steuben": 95379, "Cattaraugus": 77042,
    "Chemung": 84148, "Livingston": 62914, "Clinton": 79843,
    "Washington": 63216, "Columbia": 61570, "Madison": 68470,
    "Warren": 65737, "Cayuga": 76576, "Herkimer": 61319,
    "Genesee": 58388, "Wayne": 89918, "Putnam": 97714,
    "Sullivan": 78624, "Montgomery": 49532, "Otsego": 59493,
    "Tioga": 48455, "Allegany": 46091, "Greene": 47188,
    "Schoharie": 30999, "Delaware": 44135, "Cortland": 47581,
    "Seneca": 33814, "Chenango": 47220, "Franklin": 50692,
    "Wyoming": 40531, "Orleans": 40343, "Fulton": 53383,
    "Essex": 37381, "Schuyler": 17807, "Lewis": 26296,
    "Yates": 24774, "Hamilton": 4836,
}

# For each bus, find nearest county centroid and get population weight
# Simple approach: use bus lat/lon to assign approximate population weight
# based on zone. Distribute within zone proportional to kV tier
# (higher kV substations serve larger load areas).

# Filter eligible load buses
# All real substations (not split points) at transmission voltage are eligible.
# Bus ID >= 10100 are OSM J/K substations; they now carry real loads directly
# (virtual aggregate buses 10001-10015 were eliminated in v29).
load_mask = (
    (bus["is_split"].astype(str).str.lower().isin(["false", "0", "nan"])) &
    (bus["BaseKV"] >= 69) & (bus["BaseKV"] < 400)
)
if LOAD_NAMED:
    load_mask &= ~bus["Bus Name"].str.startswith("OSM_")

eligible = bus[load_mask].copy()
print(f"  Eligible load buses: {len(eligible)} / {len(bus)}")

# Load EIA 861 county-based weights if available, else fall back to BaseKV^1.5
_weights_csv = DATA / "bus_county_weights.csv"
if _weights_csv.exists():
    print(f"  Using EIA 861 county weights: {_weights_csv.name}")
    _wdf = pd.read_csv(_weights_csv)[["Bus Name", "weight_fraction"]].dropna()
    _wdf = _wdf[_wdf["weight_fraction"] > 0]
    _weight_map = dict(zip(_wdf["Bus Name"], _wdf["weight_fraction"]))
    eligible["_weight"] = eligible["Bus Name"].map(_weight_map).fillna(0)
    # Buses absent from weight file get a small default (BaseKV^0.5) so they
    # still receive some load rather than being silently zeroed out.
    fallback_mask = eligible["_weight"] == 0
    if fallback_mask.any():
        eligible.loc[fallback_mask, "_weight"] = (
            eligible.loc[fallback_mask, "BaseKV"].astype(float) ** 0.5 * 0.01
        )
        print(f"  {fallback_mask.sum()} buses used BaseKV fallback weight")
else:
    print("  EIA 861 weights not found — using BaseKV^1.5 proxy")
    eligible["_weight"] = eligible["BaseKV"].astype(float) ** 1.5

bus["MW Load"] = 0.0

for zone, zone_mw in ZONE_LOAD_MW.items():
    zone_buses = eligible[eligible["Zone"] == zone]
    if len(zone_buses) == 0:
        print(f"  WARNING: No eligible buses in zone {zone}, skipping {zone_mw:.0f} MW")
        continue
    total_weight = zone_buses["_weight"].sum()
    if total_weight == 0:
        continue
    for idx in zone_buses.index:
        frac = zone_buses.loc[idx, "_weight"] / total_weight
        bus.loc[idx, "MW Load"] = round(zone_mw * frac, 2)

total_load = bus["MW Load"].sum()
print(f"  Total load distributed: {total_load:,.0f} MW")

# Apply DC tie injections — each entry must resolve to exactly one bus by
# Bus ID. No fallbacks: a missing target means the grid is wrong, not the
# script.
print("  Recording DC tie injections (applied as constants in timeseries)...")
# Keep tie injections separate from the zonal-load-share that lands in
# bus.csv. Folding them into bus["MW Load"] would mean create_timeseries
# scales the constant tie imports by hourly/peak when HOURLY_LOAD_CSV is
# set — that was the P2.4 ~628 MW gap. Apply ties as constant per-hour
# offsets instead.
DC_TIE_INJECTIONS = {}  # bus_name -> -MW (negative = import = subtracts from load)
bus_id_to_idx = {int(bid): idx for idx, bid in zip(bus.index, bus["Bus ID"])}
for bid, import_mw, label in DC_TIES:
    if bid not in bus_id_to_idx:
        raise RuntimeError(
            f"DC tie target Bus ID {bid} ({label}) not found in bus.csv. "
            f"Either the grid was updated or the tie pin needs revisiting."
        )
    idx = bus_id_to_idx[bid]
    bn = bus.loc[idx, "Bus Name"]
    DC_TIE_INJECTIONS[bn] = DC_TIE_INJECTIONS.get(bn, 0.0) - float(import_mw)
    print(f"    {label}: -{import_mw:.0f} MW at {bn} (Zone {bus.loc[idx, 'Zone']})")

total_load = bus["MW Load"].sum()
total_ties = sum(DC_TIE_INJECTIONS.values())
print(f"  Load (Gold Book peak share): {total_load:,.0f} MW")
print(f"  DC tie injections (constant): {total_ties:,.0f} MW")
print(f"  Net (= load + ties): {total_load + total_ties:,.0f} MW")

bus.to_csv(bus_path, index=False)

# ---------------------------------------------------------------------------
# Step 2b: Remove buses not connected to the main network component
# ---------------------------------------------------------------------------
# The OSM substation set is a superset of the OSM branch endpoints: many
# substations have no transmission lines in OSM and form isolated singletons.
# The PTDF formulation requires a connected network, so we drop isolated buses
# and redistribute their load to the nearest connected bus in the same zone.
print("\nStep 2b: Checking network connectivity...")
branch_df = pd.read_csv(branch_path)
G = nx.Graph()
G.add_nodes_from(bus["Bus ID"].astype(int).tolist())
for _, br in branch_df.iterrows():
    G.add_edge(int(br["From Bus"]), int(br["To Bus"]))

components = sorted(nx.connected_components(G), key=len, reverse=True)
main_component = components[0]
isolated = [c for c in components[1:] if len(c) == 1]
small = [c for c in components[1:] if len(c) > 1]
print(f"  Components: {len(components)} total, largest={len(main_component)} buses")
print(f"  Isolated singletons: {len(isolated)}, small clusters: {len(small)}")

if len(components) > 1:
    drop_ids = set()
    for comp in components[1:]:
        drop_ids.update(comp)
    dropped = bus[bus["Bus ID"].astype(int).isin(drop_ids)]
    dropped_load = dropped["MW Load"].sum()
    print(f"  Dropping {len(drop_ids)} disconnected buses ({dropped_load:,.1f} MW load)")
    # Write the dropped list to a sidecar for reproducibility — names alone
    # were previously lost to stdout.
    dropped_path = RES_DIR / "dropped_topology.csv"
    dropped[["Bus ID", "Bus Name", "Zone", "BaseKV", "MW Load"]].to_csv(
        dropped_path, index=False
    )
    print(f"  Wrote dropped bus list to {dropped_path}")
    bus = bus[bus["Bus ID"].astype(int).isin(main_component)].copy()
    bus.to_csv(bus_path, index=False)
    print(f"  bus.csv filtered to {len(bus)} connected buses")

# Filter branch.csv to only branches where both endpoints are in the main
# component. Branches referencing dropped buses crash the Vatic loader.
valid_bus_ids = set(bus["Bus ID"].astype(int).tolist())
branch_full = pd.read_csv(branch_path)
branch_filt = branch_full[
    branch_full["From Bus"].astype(int).isin(valid_bus_ids) &
    branch_full["To Bus"].astype(int).isin(valid_bus_ids)
].copy()
n_dropped_br = len(branch_full) - len(branch_filt)
if n_dropped_br:
    dropped_br = branch_full[
        ~branch_full["From Bus"].astype(int).isin(valid_bus_ids)
        | ~branch_full["To Bus"].astype(int).isin(valid_bus_ids)
    ]
    print(f"  branch.csv: {len(branch_filt)} retained, {n_dropped_br} dropped (endpoint outside main component)")
    dropped_br[["UID", "From Bus", "To Bus", "Cont Rating"]].to_csv(
        RES_DIR / "dropped_branches.csv", index=False
    )
    branch_filt.to_csv(branch_path, index=False)

# Always filter gen.csv and init_state.csv to bus IDs present in bus.csv.
# This is necessary because gen.csv bus assignments use the HTML visualizer's
# node IDs, which may differ from the current bus.csv after re-runs of
# build_osm_bus_table.py.
gen_full = pd.read_csv(WORK_DIR / "gen.csv")
init_full = pd.read_csv(WORK_DIR / "init_state.csv")
gen_filt = gen_full[gen_full["Bus ID"].astype(int).isin(valid_bus_ids)].copy()

# Populate PMin where it ships as 0. The gen.csv `Output_pct_1` column
# carries the real per-unit elbow / part-load fraction — 16 distinct
# values for Gas (0.10 peaker, 0.15 small CT, 0.30 mid, 0.40 CC), 3 for
# Oil, 0.90 Nuclear, 0.30 Biomass. Use it directly. Only fall back to a
# fuel-type default when Output_pct_1 itself is 0 / NaN, which happens
# for renewables and a handful of thermal rows.
_PMIN_FRAC_FALLBACK = {"Gas": 0.30, "Oil": 0.30, "Biomass": 0.30, "Nuclear": 0.95}
_thermal_mask = gen_filt["Fuel"].isin(_PMIN_FRAC_FALLBACK) & (gen_filt["PMin MW"] == 0)
if _thermal_mask.any():
    pct = gen_filt.loc[_thermal_mask, "Output_pct_1"].astype(float)
    # Use Output_pct_1 where it has a meaningful value; else fuel fallback
    fallback = gen_filt.loc[_thermal_mask, "Fuel"].map(_PMIN_FRAC_FALLBACK)
    fracs = pct.where(pct > 0, fallback)
    gen_filt.loc[_thermal_mask, "PMin MW"] = (
        gen_filt.loc[_thermal_mask, "PMax MW"].astype(float) * fracs
    ).round(2)
    n_from_data = ((_thermal_mask) & (gen_filt["Output_pct_1"].fillna(0) > 0)).sum()
    n_fallback = _thermal_mask.sum() - n_from_data
    print(f"  gen.csv: populated PMin for {_thermal_mask.sum()} thermal units "
          f"({n_from_data} from Output_pct_1, {n_fallback} from fuel-type fallback)")

init_filt = init_full[init_full["GEN"].isin(gen_filt["GEN UID"])].copy()
gen_filt.to_csv(WORK_DIR / "gen.csv", index=False)
init_filt.to_csv(WORK_DIR / "init_state.csv", index=False)
n_dropped_gen = len(gen_full) - len(gen_filt)
if n_dropped_gen:
    print(f"  gen.csv: {len(gen_filt)} generators retained, {n_dropped_gen} dropped (bus ID mismatch)")

# ---------------------------------------------------------------------------
# Step 3: Load Vatic and create RealistLoader
# ---------------------------------------------------------------------------
print("\nStep 3: Loading Vatic framework...")

try:
    from vatic.data.loaders import GridLoader
    from vatic.engines import Simulator
except ImportError:
    print("ERROR: vatic not importable. The Vatic package lives at "
          "../Vatic/ (sibling of this directory) and is not pip-installable. "
          "Run with:")
    print("  PYTHONPATH=../Vatic:../PGscen-2nd python run_sced.py")
    sys.exit(1)


class NYISOLoader(GridLoader):
    """NYISO grid loader for Vatic DC-SCED."""

    grid_lbl = "NYISO"
    _data_dir = "SourceData"

    thermal_gen_types = {
        "Nuclear": "N", "Coal": "C", "Gas": "G", "Oil": "O",
        "Biomass": "B",
    }
    renew_gen_types = {"Wind": "W", "Solar": "S", "Hydro": "H"}

    @property
    def data_path(self):
        return SCED_DIR

    @property
    def init_state_file(self):
        original = WORK_DIR / "init_state.csv"
        if not INIT_STATE_OVERRIDE:
            return original
        # init_state.csv doubles as the generator roster in parent
        # GridLoader.__init__ — gens absent from it are dropped from the
        # template even if they're in gen.csv. The warmup's
        # last_conditions output only contains THERMAL gens (renewables
        # are non-dispatchable), so feeding it directly drops every
        # hydro/wind/solar from the template and breaks data_providers
        # when gen_data references them. Merge: warmup thermal states +
        # original renewable rows.
        override = Path(INIT_STATE_OVERRIDE)
        if not override.exists():
            raise FileNotFoundError(
                f"INIT_STATE_OVERRIDE='{override}' does not exist. "
                f"Run the warmup day first or clear the env var."
            )
        merged_path = RES_DIR / "init_state_merged.csv"
        orig_df = pd.read_csv(original).set_index("GEN")
        ovr_df = pd.read_csv(override).set_index("GEN")
        # Override rows where the warmup has them; keep original otherwise.
        merged = orig_df.copy()
        common = merged.index.intersection(ovr_df.index)
        merged.loc[common, "UnitOnT0State"] = ovr_df.loc[common, "UnitOnT0State"]
        merged.loc[common, "PowerGeneratedT0"] = ovr_df.loc[common, "PowerGeneratedT0"]
        merged.reset_index().to_csv(merged_path, index=False)
        print(f"  init_state_file: merged warmup overrides "
              f"({len(common)} gens) with original ({len(merged)} total) → "
              f"{merged_path.name}")
        return merged_path

    @property
    def utc_offset(self):
        return -pd.Timedelta(hours=5)  # EST = UTC-5

    @property
    def timeseries_cohorts(self):
        return {"Wind", "Solar", "Hydro"}

    @staticmethod
    def get_dispatch_types(renew_types):
        return {
            "DispatchRenewables": renew_types,
            "NondispatchRenewables": {},
            "ForecastRenewables": renew_types,
        }

    @staticmethod
    def process_actuals(actuals_file, start_date, end_date):
        return pd.DataFrame()

    @staticmethod
    def must_gen_run(gen):
        return gen.Fuel == "Nuclear"

    def get_generator_type(self, gen_uid):
        fuel = self._gen_df.loc[
            self._gen_df["GEN UID"] == gen_uid, "Fuel"
        ].iloc[0]
        if fuel == "Wind":
            return "WIND"
        elif fuel == "Solar":
            return "PV"
        elif fuel == "Hydro":
            return "HYDRO"
        return "G"

    def get_generator_zone(self, gen_uid):
        bus_id = self._gen_df.loc[
            self._gen_df["GEN UID"] == gen_uid, "Bus ID"
        ].iloc[0]
        zone = self._bus_df.loc[
            self._bus_df["Bus ID"] == bus_id, "Zone"
        ]
        return zone.iloc[0] if len(zone) > 0 else "C"

    @classmethod
    def parse_generator(cls, gen_info):
        pmax = float(gen_info["PMax MW"])
        pmin = float(gen_info["PMin MW"])
        # HR_incr_1 stores the flat marginal cost in $/MWh directly.
        # gen.csv ships with HR_incr_1 == HR_incr_2 and HR_avg_0 == 0 for
        # every unit, so the curve is effectively linear at mc $/MWh.
        mc = float(gen_info["HR_incr_1"])
        # Fixed Cost($/hr) is the no-load operating cost — paid whenever
        # the unit is committed, regardless of output. The old code
        # ignored it; including it lets UC weigh keeping a unit on at
        # PMin vs cycling it.
        fixed = float(gen_info.get("Fixed Cost($/hr)", 0.0) or 0.0)
        # Two-point linear curve defined on [PMin, PMax]. UC enforces
        # PMin ≤ p ≤ PMax when committed, so we don't need a (0,0) anchor.
        lo = max(pmin, 0.0)
        hi = max(pmax, lo + 0.01)
        cost_points = [round(lo, 2), round(hi, 2)]
        cost_vals = [round(fixed + mc * lo, 4),
                     round(fixed + mc * hi, 4)]
        # Vatic requires strict monotonicity
        if cost_vals[1] <= cost_vals[0]:
            cost_vals[1] = cost_vals[0] + 0.01
        return cls.Generator(
            gen_info["GEN UID"], int(gen_info["Bus ID"]),
            gen_info["Unit Group"], gen_info["Unit Type"], gen_info["Fuel"],
            pmin, pmax,
            int(math.ceil(float(gen_info["Min Down Time Hr"]))),
            int(math.ceil(float(gen_info["Min Up Time Hr"]))),
            float(gen_info["Ramp Rate MW/Min"]),
            int(float(gen_info["Start Time Cold Hr"])),
            int(float(gen_info["Start Time Warm Hr"])),
            int(float(gen_info["Start Time Hot Hr"])),
            float(gen_info["Start Heat Cold MBTU"]),
            float(gen_info["Start Heat Warm MBTU"]),
            float(gen_info["Start Heat Hot MBTU"]),
            float(gen_info["Fuel Price $/MMBTU"]),
            cost_points, cost_vals
        )

    def create_timeseries(self, start_date=None, end_date=None):
        """Build 48-hour timeseries for generators and loads."""
        gen = self._gen_df
        bus_df = self._bus_df

        # Load hourly CF if provided
        hourly_cf = {}
        if HOURLY_CF:
            cf_df = pd.read_csv(HOURLY_CF)
            for fuel in ("Wind", "Solar", "Hydro"):
                if fuel in cf_df.columns:
                    hourly_cf[fuel] = cf_df[fuel].tolist()[:24]

        # Load hourly zonal load if provided. NYISO MIS pal data carries all
        # 11 zones (A–K); ZONE_LOAD_MW merges H and I into G per the README.
        # When reading the CSV we add H and I onto G to match.
        hourly_zone_load = {}
        if HOURLY_LOAD:
            load_df = pd.read_csv(HOURLY_LOAD)
            def _col(z):
                c1, c2 = f"Zone_{z}", z
                return c1 if c1 in load_df.columns else (c2 if c2 in load_df.columns else None)
            for zone in ZONE_LOAD_MW:
                col = _col(zone)
                if col is None:
                    continue
                series = pd.Series(load_df[col].tolist()[:24], dtype=float)
                if zone == "G":
                    for extra in ("H", "I"):
                        extra_col = _col(extra)
                        if extra_col is not None:
                            series = series + pd.Series(
                                load_df[extra_col].tolist()[:24], dtype=float)
                hourly_zone_load[zone] = series.tolist()

        # --- Generator timeseries ---
        hours_48 = list(range(48))
        dt_base = pd.Timestamp(SCED_DATE)
        dt_index = pd.DatetimeIndex([dt_base + pd.Timedelta(hours=h) for h in hours_48])

        # PGscen wind/solar (per-site actuals + day-ahead forecasts). When
        # HOURLY_CF_CSV is set it takes precedence; otherwise PGscen drives
        # the diurnal pattern. Hydro keeps the 50 % CF — no per-plant data.
        pgscen = getattr(self, "_pgscen_data", None) or {}
        gen_to_site = getattr(self, "_pgscen_gen_to_site", {})

        # Vatic gen_data must contain ONLY non-dispatchable (renewable) generators.
        # Thermal dispatch is handled by the optimizer, not by timeseries.
        RENEW_FUELS = {"Wind", "Solar", "Hydro"}
        gen_data_actl = {}
        gen_data_fcst = {}
        for _, g in gen.iterrows():
            uid = g["GEN UID"]
            fuel = g["Fuel"]
            pmax = float(g["PMax MW"])

            if fuel not in RENEW_FUELS:
                continue  # skip thermal generators

            if fuel in hourly_cf:
                cf_24 = hourly_cf[fuel]
                vals_a = [pmax * cf_24[h % 24] for h in hours_48]
                vals_f = vals_a
            elif fuel in pgscen:
                d = pgscen[fuel]
                site = gen_to_site.get(uid)
                if site and site in d["actl_site"].columns:
                    vals_a = d["actl_site"][site].tolist()
                    vals_f = (d["fcst_site"][site].tolist()
                              if site in d["fcst_site"].columns else vals_a)
                else:
                    # Unmapped wind/solar gen → system-aggregate CF profile
                    vals_a = [pmax * cf for cf in d["actl_cf"].tolist()]
                    vals_f = [pmax * cf for cf in d["fcst_cf"].tolist()]
            else:
                cf = DEFAULT_CF.get(fuel, 0.3)
                vals_a = [pmax * cf] * 48
                vals_f = vals_a

            gen_data_actl[uid] = vals_a
            gen_data_fcst[uid] = vals_f

        fcst_df = pd.DataFrame(gen_data_fcst, index=dt_index)
        fcst_df.columns = pd.MultiIndex.from_tuples(
            [("fcst", c) for c in fcst_df.columns]
        )
        actl_df = pd.DataFrame(gen_data_actl, index=dt_index)
        actl_df.columns = pd.MultiIndex.from_tuples(
            [("actl", c) for c in actl_df.columns]
        )
        gen_df = pd.concat([fcst_df, actl_df], axis=1)

        # --- Load timeseries ---
        # Scale each bus's load by hourly/peak ratio per zone, then ADD the
        # DC tie injection as a constant (not scaled). Folding the tie into
        # bus["MW Load"] before scaling caused the P2.4 load gap because
        # the constant import got rescaled with the hourly profile.
        load_data = {}
        tie_inj = DC_TIE_INJECTIONS  # module-level, set in Step 2
        for _, b in bus_df.iterrows():
            bus_name = b["Bus Name"]
            ref_mw = float(b["MW Load"])
            zone = b["Zone"]

            if zone in hourly_zone_load and ref_mw != 0:
                ref_zone_mw = ZONE_LOAD_MW.get(zone, 1)
                hourly = hourly_zone_load[zone]
                vals = [ref_mw * (hourly[h % 24] / ref_zone_mw) for h in hours_48]
            else:
                vals = [ref_mw] * 48

            # Constant tie injection (negative = import = subtracts from load)
            tie = tie_inj.get(bus_name, 0.0)
            if tie != 0.0:
                vals = [v + tie for v in vals]

            load_data[bus_name] = vals

        load_df = pd.DataFrame(load_data, index=dt_index)
        load_df.columns = pd.MultiIndex.from_tuples(
            [("fcst", c) for c in load_df.columns]
        )
        actl_load = load_df.copy()
        actl_load.columns = pd.MultiIndex.from_tuples(
            [("actl", c[1]) for c in actl_load.columns]
        )
        load_df = pd.concat([load_df, actl_load], axis=1)

        return gen_df, load_df


# ---------------------------------------------------------------------------
# Step 4: Instantiate loader
# ---------------------------------------------------------------------------
print("\nStep 4: Building RealistLoader template...")

loader = NYISOLoader()
loader._gen_df = pd.read_csv(WORK_DIR / "gen.csv")
loader._bus_df = pd.read_csv(bus_path)

# PGscen wiring. Builds the site→gen map (nearest unused gen of same fuel
# in same zone), loads per-site actuals + day-ahead forecasts aligned to
# Eastern naive time. Skipped silently if PGSCEN_DIR unset or no CSVs
# exist for SCED_DATE.year (e.g. 2025 is past wind/solar coverage).
loader._pgscen_data = {}
loader._pgscen_gen_to_site = {}
if PGSCEN_DIR is not None:
    print(f"  PGscen: {PGSCEN_DIR}")
    _dt_index = pd.DatetimeIndex([
        pd.Timestamp(SCED_DATE) + pd.Timedelta(hours=h) for h in range(48)
    ])
    loader._pgscen_data = _load_pgscen_renew(PGSCEN_DIR, SCED_DATE.year, _dt_index)
    if loader._pgscen_data:
        site_map = _build_pgscen_site_map(
            loader._gen_df, loader._bus_df, PGSCEN_DIR, SCED_DATE.year
        )
        loader._pgscen_gen_to_site = {gid: sid for sid, gid in site_map.items()}
        for fuel, d in loader._pgscen_data.items():
            n_sites = d["actl_site"].shape[1]
            n_mapped = sum(1 for sid in site_map if sid.startswith(fuel.lower()))
            print(f"    {fuel}: {n_sites} sites, {n_mapped} mapped to gens, "
                  f"actl CF range {d['actl_cf'].min():.3f}–{d['actl_cf'].max():.3f}")
    else:
        print(f"    No PGscen wind/solar CSVs for year {SCED_DATE.year} "
              f"— falling back to DEFAULT_CF")
elif HOURLY_CF:
    print(f"  HOURLY_CF_CSV: {HOURLY_CF}")
else:
    print("  No PGscen / HOURLY_CF_CSV — flat CFs (solar=10 %, wind=30 %, hydro=50 %)")

gen_df, load_df = loader.create_timeseries()
print(f"  Generator timeseries: {gen_df.shape}")
print(f"  Load timeseries:      {load_df.shape}")

# P2.4 instrumentation: account for total system load at each hour and
# compare to the raw NYISO zonal totals. Closes the 628 MW load gap.
_actl_load = load_df.xs("actl", axis=1, level=0)
_total_per_hour = _actl_load.sum(axis=1)
print(f"  System load (actl) hour-0 / hour-18 / peak: "
      f"{_total_per_hour.iloc[0]:,.0f} / {_total_per_hour.iloc[18]:,.0f} / "
      f"{_total_per_hour.max():,.0f} MW")
if HOURLY_LOAD:
    _raw = pd.read_csv(HOURLY_LOAD)
    _raw_total_peak = _raw[[c for c in _raw.columns if c.startswith("Zone_")]].sum(axis=1).max()
    _tie_total = sum(DC_TIE_INJECTIONS.values())
    _expected_peak = _raw_total_peak + _tie_total
    _gap = _total_per_hour.max() - _expected_peak
    print(f"  Raw NYISO peak: {_raw_total_peak:,.0f} MW + ties {_tie_total:,.0f} "
          f"= expected {_expected_peak:,.0f} MW;  gap to actual: {_gap:+,.0f} MW")

# ---------------------------------------------------------------------------
# Step 4b: Storage injection
# ---------------------------------------------------------------------------
storage_path = WORK_DIR / "storage.csv"
if storage_path.exists():
    print("\nStep 4b: Loading storage...")
    stor_df = pd.read_csv(storage_path)
    print(f"  {len(stor_df)} storage units, {stor_df['Discharge Rate MW'].sum():,.0f} MW total")

    # Bus name lookup
    bus_name_map = loader._bus_df.set_index("Bus ID")["Bus Name"].to_dict()
    bus_zone_map = loader._bus_df.set_index("Bus ID")["Zone"].to_dict()

    # Aggregation. Split battery and pumped_hydro into separate units so
    # we don't blend lithium round-trip efficiency (~92%) with pumped
    # hydro (~80%) or co-locate them at the same bus.
    if STORAGE_AGG == "zone":
        if "_stor_type" not in stor_df.columns:
            stor_df = stor_df.assign(_stor_type="battery")

        n_batt = (stor_df["_stor_type"] == "battery").sum()
        n_pump = (stor_df["_stor_type"] == "pumped_hydro").sum()
        print(f"  Source: {n_batt} battery + {n_pump} pumped_hydro units")

        # Flag missing-zone diagnostics — Zone J/K should have BESS in
        # real NYISO fleet (Ravenswood, BQDM, LI projects) but may be
        # absent in this grid version.
        zones_with_storage = set(
            bus_zone_map.get(int(b), "?") for b in stor_df["Bus ID"]
        )
        for z in ("J", "K"):
            if z not in zones_with_storage:
                print(f"  WARNING: Zone {z} has zero storage units (expected "
                      f"BESS in NYISO fleet — data gap, not modeling choice)")

        prefix_by_type = {"battery": "BESS", "pumped_hydro": "PH"}
        storage_elements = {}

        for stype, prefix in prefix_by_type.items():
            sub = stor_df[stor_df["_stor_type"] == stype]
            if sub.empty:
                continue
            agg = defaultdict(lambda: {
                "discharge": 0.0, "charge": 0.0, "energy": 0.0,
                "soc": 0.0, "eff_wt": 0.0, "bus_id": None, "max_disch": 0.0,
            })
            for _, s in sub.iterrows():
                bid = int(s["Bus ID"])
                zone = bus_zone_map.get(bid, "C")
                d = float(s["Discharge Rate MW"])
                agg[zone]["discharge"] += d
                agg[zone]["charge"] += float(s["Charge Rate MW"])
                agg[zone]["energy"] += float(s["Energy Capacity MWh"])
                agg[zone]["soc"] += float(s["Initial SOC MWh"])
                agg[zone]["eff_wt"] += d * float(s.get("Charge Efficiency", 0.92))
                if d > agg[zone]["max_disch"]:
                    agg[zone]["max_disch"] = d
                    agg[zone]["bus_id"] = bid

            for zone, a in agg.items():
                if a["discharge"] == 0:
                    continue
                bus_id = a["bus_id"]
                bname = bus_name_map.get(bus_id, f"Bus_{bus_id}")
                eff = a["eff_wt"] / a["discharge"] if a["discharge"] else 0.92
                uid = f"{prefix}_{zone}"
                storage_elements[uid] = {
                    "bus": bname,
                    "min_discharge_rate": 0.0,
                    "max_discharge_rate": a["discharge"],
                    "min_charge_rate": 0.0,
                    "max_charge_rate": a["charge"],
                    "energy_capacity": a["energy"],
                    "initial_state_of_charge": a["soc"] / a["energy"] if a["energy"] else 0.5,
                    "minimum_state_of_charge": 0.1 if stype == "pumped_hydro" else 0.0,
                    "end_state_of_charge": 0.0,
                    "charge_efficiency": round(eff, 4),
                    "discharge_efficiency": round(eff, 4),
                    "initial_status": 1,
                    "ramp_up_output_60min": a["discharge"],
                    "ramp_down_output_60min": a["discharge"],
                    "ramp_up_input_60min": a["charge"],
                    "ramp_down_input_60min": a["charge"],
                }
        print(f"  Aggregated to {len(storage_elements)} zone-level storage units")
        for uid, se in storage_elements.items():
            print(f"    {uid}: {se['max_discharge_rate']:.0f} MW / "
                  f"{se['energy_capacity']:.0f} MWh @ {se['bus']}")
    else:
        storage_elements = {}
        print(f"  Storage aggregation '{STORAGE_AGG}' — {len(stor_df)} individual units")
else:
    storage_elements = {}
    print("\nNo storage.csv found, skipping storage.")

# ---------------------------------------------------------------------------
# Step 5: Run Vatic Simulator
# ---------------------------------------------------------------------------
print(f"\nStep 5: Running Vatic SCED (date={SCED_DATE_STR})...")

solver = "gurobi" if USE_GUROBI else "cbc"
solver_opts = {"Threads": THREADS} if USE_GUROBI else {}

try:
    # Patch create_vatic_model_dict BEFORE Simulator init so that init_model
    # also gets storage elements (needed for copy_elements consistency).
    if storage_elements:
        from vatic.data_providers import PickleProvider
        _orig_create = PickleProvider.create_vatic_model_dict

        def _patched_create(self, *args, **kwargs):
            md = _orig_create(self, *args, **kwargs)
            # md is a plain dict with keys: 'system', 'elements'
            bus_dict = md.get("elements", {}).get("bus", {})
            for uid, se in storage_elements.items():
                if se["bus"] in bus_dict:
                    if "storage" not in md["elements"]:
                        md["elements"]["storage"] = {}
                    md["elements"]["storage"][uid] = se
            return md

        PickleProvider.create_vatic_model_dict = _patched_create
        print(f"  Storage monkey-patch applied: {len(storage_elements)} units")

        # Clip storage SOC to [0, 1] between SCED iterations. Vatic stores
        # the solved SOC verbatim and the next step's StorageSocOnT0 is a
        # Pyomo PercentFraction — a tiny FP overshoot (e.g. 1.0000001) on
        # a fully-charged unit raises InvalidValue. Clip on write.
        from vatic.simulation_state import VaticSimulationState
        _orig_apply_sced = VaticSimulationState.apply_sced

        def _safe_apply_sced(self, sced):
            _orig_apply_sced(self, sced)
            for s, v in list(self._init_soc.items()):
                if v > 1.0:
                    self._init_soc[s] = 1.0
                elif v < 0.0:
                    self._init_soc[s] = 0.0

        VaticSimulationState.apply_sced = _safe_apply_sced

    sim = Simulator(
        template_data=loader.template,
        gen_data=gen_df,
        load_data=load_df,
        out_dir=RES_DIR,
        start_date=SCED_DATE,
        num_days=1,
        solver=solver,
        solver_options=solver_opts,
        run_lmps=True,
        mipgap=0.01,
        load_shed_penalty=1e4,
        reserve_shortfall_penalty=1e3,
        reserve_factor=0.05,
        output_detail=3,
        prescient_sced_forecasts=False,
        ruc_prescience_hour=0,
        ruc_execution_hour=16,
        ruc_every_hours=24,
        ruc_horizon=48,
        sced_horizon=4,
        lmp_shortfall_costs=False,
        enforce_sced_shutdown_ramprate=False,
        no_startup_shutdown_curves=False,
        init_ruc_file=None,
        verbosity=1,
        output_max_decimals=4,
        create_plots=False,
        renew_costs=None,
        save_to_csv=True,
        last_conditions_file=(LAST_CONDITIONS_FILE or None),
    )

    sim.simulate()
    print(f"\nResults written to: {RES_DIR}")

except Exception as e:
    print(f"\nSCED FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ---------------------------------------------------------------------------
# Step 6: Quick summary
# ---------------------------------------------------------------------------
print("\n=== Quick Summary ===")
summary_files = list(RES_DIR.glob("*hourly*summary*"))
if summary_files:
    summary = pd.read_csv(summary_files[0])
    print(summary.to_string(index=False))
else:
    print("  No hourly summary found — check results directory")
