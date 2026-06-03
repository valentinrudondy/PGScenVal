"""Task 2 — fleet-wide metadata consistency audit.

Closes the EIA-860-join bug class that produced Baron (stale nameplate) and
Canandaigua (EIA-ID collision) — the latter caught only by a secondary hub-lift
signal. Cross-checks all 31 plants across goldbook x EIA-860 x USWTDB and flags:

  COORD     wind_meta coord vs USWTDB turbine-centroid for its eia_plant_id;
            flag > 3 km (Canandaigua was 10.3 km pre-fix).
  EIA_COLL  eia_plant_id shared by >1 wind_meta row (the Canandaigua/Baron 60596
            collision).
  NP_USWTDB |wind_meta NP - USWTDB turbine-sum capacity| / NP; flag > 30%
            (Baron was 1.96x; Maple Ridge's split is benign — handled).
  NP_EIA    |wind_meta NP - EIA-860 nameplate| / NP; flag > 30%.
  NAME      wind_meta site_name token-overlap vs EIA-860 plant_name; flag none.

Runs AFTER the R1.3 fixes, so it both verifies those and scans for any
remaining plant in the same class. Output:
docs/figures/wind_v3/metadata_consistency_audit.csv
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
PM = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
OUT = REPO / "docs" / "figures" / "wind_v3" / "metadata_consistency_audit.csv"

COORD_KM_FLAG = 3.0
NP_GAP_FLAG = 0.30

# EIA IDs that legitimately aggregate >1 wind_meta site (NOT collisions):
# Maple Ridge 1+2 share one EIA registration (56290) by design.
KNOWN_SHARED_EIA = {56290}


def hav(a, b, c, d):
    R = 6371.0
    p = np.radians
    return 2 * R * np.arcsin(np.sqrt(
        np.sin((p(c) - p(a)) / 2) ** 2
        + np.cos(p(a)) * np.cos(p(c)) * np.sin((p(d) - p(b)) / 2) ** 2))


def toks(s):
    return set(re.findall(r"[a-z]+", str(s).lower())) - {
        "llc", "wind", "power", "farm", "project", "energy", "the", "of",
        "partners", "windpark", "windpower", "ii", "i"}


def main():
    meta = pd.read_csv(PM / "wind_meta.csv")
    eia = pd.read_csv(PM / "eia860_ny_wind.csv")
    usw = pd.read_csv(PM / "uswtdb_ny_turbines.csv")

    eia_np = eia.dropna(subset=["eia_plant_id"]).groupby("eia_plant_id").agg(
        eia_name=("plant_name", "first"),
        eia_np=("nameplate_mw", "sum"),
        eia_lat=("latitude", "first"), eia_lon=("longitude", "first"))
    usw_g = usw.dropna(subset=["eia_id"]).groupby("eia_id").agg(
        usw_cap=("t_cap", lambda s: s.sum() / 1000.0),
        usw_lat=("ylat", "mean"), usw_lon=("xlong", "mean"),
        usw_hh=("t_hh", "mean"), usw_rd=("t_rd", "mean"),
        usw_n=("t_cap", "size"), usw_pname=("p_name", lambda s: s.mode().iloc[0]))

    # EIA-ID collisions (excluding known-shared)
    eia_counts = meta["eia_plant_id"].value_counts()
    collisions = {int(e) for e, c in eia_counts.items()
                  if c > 1 and int(e) not in KNOWN_SHARED_EIA}

    rows = []
    for _, m in meta.iterrows():
        eid = m["eia_plant_id"]
        flags = []
        usw_cap = usw_lat = usw_lon = usw_hh = np.nan
        eia_np_v = np.nan
        coord_km = np.nan
        eia_name = usw_pname = ""
        if pd.notna(eid) and eid in usw_g.index:
            g = usw_g.loc[eid]
            usw_cap, usw_lat, usw_lon = g.usw_cap, g.usw_lat, g.usw_lon
            usw_hh, usw_pname = g.usw_hh, g.usw_pname
            coord_km = hav(m["latitude"], m["longitude"], usw_lat, usw_lon)
            if coord_km > COORD_KM_FLAG:
                flags.append(f"COORD({coord_km:.1f}km)")
            if usw_cap > 0 and abs(m["nameplate_mw"] - usw_cap) / m["nameplate_mw"] > NP_GAP_FLAG:
                flags.append(f"NP_USWTDB({m['nameplate_mw']:.0f}vs{usw_cap:.0f})")
        elif pd.notna(eid):
            flags.append("NO_USWTDB")
        if pd.notna(eid) and eid in eia_np.index:
            eia_np_v = eia_np.loc[eid, "eia_np"]
            eia_name = eia_np.loc[eid, "eia_name"]
            if eia_np_v > 0 and abs(m["nameplate_mw"] - eia_np_v) / m["nameplate_mw"] > NP_GAP_FLAG:
                flags.append(f"NP_EIA({m['nameplate_mw']:.0f}vs{eia_np_v:.0f})")
            # name token overlap
            if eid not in KNOWN_SHARED_EIA:
                ov = toks(m["site_name"]) & toks(eia_name)
                if not ov:
                    flags.append(f"NAME(meta='{m['site_name'][:18]}'/eia='{str(eia_name)[:18]}')")
        if pd.notna(eid) and int(eid) in collisions:
            flags.append(f"EIA_COLL({int(eid)})")

        rows.append({
            "site_id": m["site_id"], "name": m["site_name"][:32],
            "eia_plant_id": eid, "meta_np": m["nameplate_mw"],
            "eia_np": round(eia_np_v, 1) if pd.notna(eia_np_v) else None,
            "uswtdb_cap": round(usw_cap, 1) if pd.notna(usw_cap) else None,
            "coord_km_to_uswtdb": round(coord_km, 2) if pd.notna(coord_km) else None,
            "uswtdb_hub_m": round(usw_hh, 0) if pd.notna(usw_hh) else None,
            "status": "FLAG" if flags else "PASS",
            "flags": ";".join(flags),
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    pd.set_option("display.width", 200, "display.max_colwidth", 60)
    print("=" * 100)
    print(f"Metadata consistency audit — {len(df)} plants")
    print("=" * 100)
    flagged = df[df.status == "FLAG"]
    print(f"\nPASS: {(df.status=='PASS').sum()}   FLAG: {len(flagged)}\n")
    if len(flagged):
        print(flagged[["site_id", "name", "eia_plant_id", "meta_np",
                       "coord_km_to_uswtdb", "flags"]].to_string(index=False))
    print(f"\n(known-shared EIA excluded from collision check: {KNOWN_SHARED_EIA})")
    print(f"Wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
