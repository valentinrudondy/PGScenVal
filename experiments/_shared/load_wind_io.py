"""Shared load+wind data alignment for diagnostics/validation.

Reads the NYISO load and wind CSVs and aligns them into matched actuals +
forecast frames. Used by the cross-group dependency diagnostic
(`three_way_dependency_graph/`) and the per-plant wind validation/figures
(`wind_per_plant/validate_cross_block.py`, `wind_validation/make_scenario_fan.py`).

NOTE: this is a data aligner, NOT a model. It was originally written for the
abandoned two-stage joint load+wind experiment (see `Claude_load.md` for why that
was dropped) and relocated here because the join is reused by the keepers above;
no production code depends on it.

The 8-dim joint vector per hour is:
    [LOAD_A, LOAD_C, LOAD_D, LOAD_E, WIND_A, WIND_C, WIND_D, WIND_E]
where LOAD_X is the zone load and WIND_X is the sum of all wind plants in
zone X. Zones are NYISO letter codes (A,C,D,E are the four wind-bearing
load zones in the metadata). Zone K (offshore South Fork, 1 plant) is
excluded.

Time convention
---------------
- A "scenario day" is an Eastern calendar day (00:00 ET .. 23:00 ET, 24h).
- Internally timestamps stay tz-aware UTC (what the engine consumes).
- Forecast Issue_time is the NYISO day-ahead market clearing convention:
  18:00:00 UTC = 13:00 ET (EST) / 14:00 ET (EDT) of the day before the
  scenario day. The 24 hourly Forecast_times under each Issue_time span
  the full Eastern day they target. The load CSV already follows this
  convention natively; wind Issue_time is rejoined onto load's via a
  merge on Forecast_time so both share grouping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

PGSCEN_ROOT = Path("/Users/val/Desktop/Princeton/PGscen-2nd")
DATA = PGSCEN_ROOT / "data" / "NYISO_real"

# NYISO letter zone -> load CSV column name
LOAD_ZONE_COL = {
    "A": "WEST",
    "C": "CENTRL",
    "D": "NORTH",
    "E": "MHK VL",
}
WIND_ZONES = ["A", "C", "D", "E"]
ET = "US/Eastern"


def eastern_day_to_scen_start_utc(eastern_date: str | pd.Timestamp) -> pd.Timestamp:
    """Return 00:00 of the given ET calendar date as a UTC tz-aware timestamp."""
    d = pd.Timestamp(eastern_date)
    if d.tz is None:
        d = d.tz_localize(ET)
    else:
        d = d.tz_convert(ET)
    d = d.normalize()  # 00:00 ET
    return d.tz_convert("UTC")


def _load_wind_meta() -> pd.DataFrame:
    return pd.read_csv(DATA / "plant_metadata" / "wind_meta.csv")


def _zone_to_plant_ids(meta: pd.DataFrame) -> dict[str, list[str]]:
    return {
        z: meta.loc[meta["zone"] == z, "site_id"].tolist()
        for z in WIND_ZONES
    }


def _read_load_actuals() -> pd.DataFrame:
    df = pd.read_csv(
        DATA / "load_actual_1h_zone_2018_2019_2020_2021_2022_2023_2024_2025_utc.csv",
        parse_dates=["Time"],
        index_col="Time",
    )
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def _read_load_forecast() -> pd.DataFrame:
    """Load DA forecast in its NATIVE NYISO convention.

    Issue_time is 18:00 UTC on the day before each Eastern scenario day;
    each Issue_time has 24 Forecast_times covering 00:00..23:00 ET.
    """
    df = pd.read_csv(
        DATA / "load_day_ahead_forecast_zone_2018_2019_2020_2021_2022_2023_2024_2025_utc.csv",
        parse_dates=["Issue_time", "Forecast_time"],
    )
    for col in ("Issue_time", "Forecast_time"):
        if df[col].dt.tz is None:
            df[col] = df[col].dt.tz_localize("UTC")
    return df


def _wind_files(kind: str, years: Iterable[int]) -> list[Path]:
    if kind == "actual":
        pat = "wind_actual_1h_site_{y}_utc.pluswind_v4.csv"
    else:
        pat = "wind_day_ahead_forecast_site_{y}_utc.pluswind_v4.csv"
    return [DATA / "wind" / pat.format(y=y) for y in years]


def _read_wind_actuals(years: Iterable[int]) -> pd.DataFrame:
    dfs = []
    for fp in _wind_files("actual", years):
        if not fp.exists():
            continue
        d = pd.read_csv(fp, parse_dates=["Time"], index_col="Time")
        dfs.append(d)
    out = pd.concat(dfs).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    out = out.fillna(0.0)
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    return out


def _read_wind_forecast(years: Iterable[int]) -> pd.DataFrame:
    """Wind forecast in raw form (its Issue_time will be replaced below)."""
    dfs = []
    for fp in _wind_files("forecast", years):
        if not fp.exists():
            continue
        d = pd.read_csv(fp, parse_dates=["Issue_time", "Forecast_time"])
        dfs.append(d)
    out = pd.concat(dfs, ignore_index=True).fillna(0.0)
    out = out.drop_duplicates(subset=["Issue_time", "Forecast_time"], keep="first")
    for col in ("Issue_time", "Forecast_time"):
        if out[col].dt.tz is None:
            out[col] = out[col].dt.tz_localize("UTC")
    return out


def _aggregate_wind_actuals_by_zone(
    wide: pd.DataFrame, zone_plants: dict[str, list[str]]
) -> pd.DataFrame:
    cols_out = {}
    for z, plants in zone_plants.items():
        present = [p for p in plants if p in wide.columns]
        cols_out[f"WIND_{z}"] = wide[present].sum(axis=1) if present else 0.0
    return pd.DataFrame(cols_out, index=wide.index)


def _aggregate_wind_forecast_by_zone(
    wide: pd.DataFrame, zone_plants: dict[str, list[str]]
) -> pd.DataFrame:
    out = wide[["Issue_time", "Forecast_time"]].copy()
    for z, plants in zone_plants.items():
        present = [p for p in plants if p in wide.columns]
        out[f"WIND_{z}"] = wide[present].sum(axis=1) if present else 0.0
    return out


def build_joint_inputs(
    years: Iterable[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (joint_actuals, joint_forecast, wind_meta).

    joint_actuals : DatetimeIndex (UTC), columns [LOAD_A..E, WIND_A..E]
    joint_forecast : columns ['Issue_time','Forecast_time', LOAD_A..E, WIND_A..E],
                     Issue_time in load's native NYISO DA convention (18Z prior day)
    wind_meta : wind_meta rows for the 4 retained zones (excludes K)
    """
    wind_meta = _load_wind_meta()
    wind_meta = wind_meta[wind_meta["zone"].isin(WIND_ZONES)].copy()
    zone_plants = _zone_to_plant_ids(wind_meta)

    # ----- load
    la = _read_load_actuals()
    lf = _read_load_forecast()
    load_cols = [LOAD_ZONE_COL[z] for z in WIND_ZONES]
    rename = {LOAD_ZONE_COL[z]: f"LOAD_{z}" for z in WIND_ZONES}
    la4 = la[load_cols].rename(columns=rename)
    lf4 = lf[["Issue_time", "Forecast_time"] + load_cols].rename(columns=rename)

    # ----- wind
    wa = _read_wind_actuals(years)
    wf = _read_wind_forecast(years)
    wa_z = _aggregate_wind_actuals_by_zone(wa, zone_plants)
    wf_z = _aggregate_wind_forecast_by_zone(wf, zone_plants)

    # ----- align actuals on Time (inner join, UTC index)
    joint_actuals = la4.join(wa_z, how="inner").sort_index()

    # ----- align forecasts: rejoin wind onto load by Forecast_time so wind
    #       inherits load's Issue_time (NYISO 18Z prior-ET-day convention).
    wf_only = wf_z[["Forecast_time"] + [f"WIND_{z}" for z in WIND_ZONES]]
    joint_forecast = (
        lf4.merge(wf_only, on="Forecast_time", how="inner")
        .sort_values(["Issue_time", "Forecast_time"])
        .reset_index(drop=True)
    )

    return joint_actuals, joint_forecast, wind_meta


if __name__ == "__main__":
    import sys

    years = list(range(2019, 2025))
    if len(sys.argv) > 1:
        years = [int(x) for x in sys.argv[1:]]

    ja, jf, wm = build_joint_inputs(years)
    print(f"years requested: {years}")
    print(f"\njoint_actuals: {ja.shape}, "
          f"UTC span {ja.index.min()} -> {ja.index.max()}")
    et_min = ja.index.min().tz_convert(ET)
    et_max = ja.index.max().tz_convert(ET)
    print(f"  ET span  {et_min} -> {et_max}")
    print(ja.head(3))
    print(ja.describe().round(1))

    print(f"\njoint_forecast: {jf.shape}, "
          f"Issue_time UTC span {jf.Issue_time.min()} -> {jf.Issue_time.max()}")
    grp_sizes = jf.groupby("Issue_time").size()
    print(f"  Issue_time groups: {len(grp_sizes)} unique, "
          f"min/median/max rows per group = "
          f"{grp_sizes.min()}/{int(grp_sizes.median())}/{grp_sizes.max()}")
    print(jf.head(3))

    print(f"\nwind_meta retained: {len(wm)} plants across {wm.zone.nunique()} zones")
    print(wm.groupby("zone").agg(n=("site_id", "count"),
                                  cap_mw=("nameplate_mw", "sum")))
