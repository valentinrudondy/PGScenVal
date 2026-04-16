"""
Download US Wind Turbine Database (USWTDB) NY entries via the USGS API,
and aggregate to per-project records (lat/lon centroid + total capacity).

Source: https://eerscmap.usgs.gov/uswtdb/

The USGS public API endpoint returns one row per turbine with:
  case_id, faa_ors, faa_asn, usgs_pr_id, eia_id, t_state, t_county,
  t_fips, p_name, p_year, p_tnum, p_cap, t_manu, t_model, t_cap,
  t_hh, t_rd, t_rsa, t_ttlh, retrofit, retrofit_year, t_conf_atr,
  t_conf_loc, t_img_date, t_img_srce, xlong, ylat

Each turbine has lat/lon (xlong, ylat) and an aggregator key p_name (project
name) that lets us group turbines into wind farms.

Usage:
    python 03_download_uswtdb.py --out data/NYISO_real/plant_metadata/

Outputs:
    uswtdb_ny_turbines.csv     — raw per-turbine table for NY
    uswtdb_ny_projects.csv     — aggregated to per-project (used downstream)
"""

from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
import requests

USWTDB_URL = "https://eersc.usgs.gov/api/uswtdb/v1/turbines"


def download_ny_turbines() -> pd.DataFrame:
    print(f"  GET {USWTDB_URL}?t_state=eq.NY")
    r = requests.get(
        USWTDB_URL,
        params={"t_state": "eq.NY"},
        headers={"Accept": "application/json"},
        timeout=120,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    print(f"  got {len(df)} NY turbines")
    return df


def aggregate_projects(turbines: pd.DataFrame) -> pd.DataFrame:
    """Group turbines by p_name, take centroid + sum capacity."""
    if turbines.empty:
        return turbines
    g = turbines.groupby("p_name", dropna=False)
    agg = g.agg(
        n_turbines=("case_id", "count"),
        latitude=("ylat", "mean"),
        longitude=("xlong", "mean"),
        total_capacity_kw=("t_cap", "sum"),
        project_capacity_mw=("p_cap", "first"),  # USWTDB also has p_cap, the
                                                  # nameplate at the project level
        project_year=("p_year", "first"),
        county=("t_county", lambda x: x.mode().iat[0] if len(x.mode()) else None),
        eia_plant_id=("eia_id", lambda x: x.dropna().iat[0]
                      if len(x.dropna()) else None),
    ).reset_index()
    # USWTDB t_cap is per-turbine in kW; sum/1000 = MW
    agg["sum_turbine_capacity_mw"] = agg["total_capacity_kw"] / 1000.0
    agg = agg.drop(columns=["total_capacity_kw"])
    # Prefer project_capacity_mw when present, else fallback to sum_turbines
    agg["nameplate_mw"] = agg["project_capacity_mw"].fillna(agg["sum_turbine_capacity_mw"])
    return agg.sort_values("nameplate_mw", ascending=False).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    turbines = download_ny_turbines()
    turbines.to_csv(args.out / "uswtdb_ny_turbines.csv", index=False)
    print(f"  wrote {args.out / 'uswtdb_ny_turbines.csv'}")

    projects = aggregate_projects(turbines)
    projects.to_csv(args.out / "uswtdb_ny_projects.csv", index=False)
    print(f"  wrote {args.out / 'uswtdb_ny_projects.csv'} "
          f"({len(projects)} projects, {projects['nameplate_mw'].sum():.0f} MW)")


if __name__ == "__main__":
    main()
