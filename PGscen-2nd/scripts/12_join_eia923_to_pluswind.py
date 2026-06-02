"""Join EIA-923 monthly delivered generation to pluswind_v3 hourly modeled
potential, emitting a long-format table for the EIA-923 validation layer.

Pipeline
--------
1. Load all years (2018-2024) of pluswind_v3 hourly modeled-actual files.
2. Convert UTC → US/Eastern; aggregate to monthly per site (Eastern calendar
   months — matches EIA-923's monthly reporting convention).
3. Map site_id → effective EIA plant ID (applying join-side overrides; see
   ``EIA_ID_OVERRIDES`` below). Aggregate sites that share an EIA ID
   (Maple Ridge 1 + 2 → EIA 56290).
4. Outer-join against EIA-923 monthly per plant.
5. Tag each row with a bucket:
     - "matched"     plant verified on both sides; counts toward matched-fleet
                     scorecard statistics
     - "unverified"  plant present on both sides but with a known
                     location/identity issue (see ``UNVERIFIED``); excluded
                     from matched-fleet sums, reported separately
     - "eia_only"    plant in EIA-923 but absent from wind_meta (Dutch Hill,
                     small BTM turbines); used for fleet coverage analysis
6. Compute gap, gap percent, implied capacity factors. Capacities use
   wind_meta nameplate_mw for matched/unverified rows; eia_only rows have no
   modeled capacity and the CF columns are based on EIA-860 nameplate where
   available.

Join-side overrides
-------------------
The wind_meta.csv EIA mapping for ``wind_323617`` is wrong (it points at EIA
60596, which is Baron Winds Farm 12 km south); EIA-860 lat/lon confirms the
correct ID is 56634 (Cohocton Wind Project, 2.99 km from our lat/lon, same
operator history, same capacity vintage). This override is applied join-side
only; wind_meta is left untouched.

Unverified plants
-----------------
Four sites have known issues (see Task 1 checkpoint report):
    wind_323822  Baron Winds      - wind_meta lat/lon copied from Canandaigua
                                    (12 km north of real plant)
    wind_323825  Ball Hill        - 16.91 km from EIA-860 location; USWTDB
                                    cross-check pending
    wind_323706  Stony Creek /    - 14.50 km from EIA-860 location;
                 Orangeville Wind   single plant, two names (Invenergy SPV);
                                    physics computed at wrong HRRR cell
    wind_323839  South Fork Wind  - EIA 65561 not present in EIA-923 2024;
                                    suspected EIA-ID error (match_quality=2)

Output
------
PGscen-2nd/data/NYISO_real/eia923/eia923_vs_pluswind_v3_long.csv

Columns:
    year, month, eia_plant_id, plant_name, capacity_mw,
    modeled_potential_mwh, eia_delivered_mwh, gap_mwh, gap_pct,
    implied_capacity_factor_modeled, implied_capacity_factor_eia,
    bucket, bucket_reason, sites_aggregated, hours_in_month
"""

from __future__ import annotations

import calendar
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
META_CSV   = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata" / "wind_meta.csv"
EIA860_CSV = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata" / "eia860_ny_wind.csv"
WIND_DIR   = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
EIA923_DIR = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "eia923"
OUT_CSV    = EIA923_DIR / "eia923_vs_pluswind_v3_long.csv"

YEARS = list(range(2018, 2025))

MONTH_NAMES = ["january", "february", "march", "april", "may", "june",
               "july", "august", "september", "october", "november", "december"]

# Site_id → list of EIA plant IDs for the EIA-923 join. First entry is the
# "primary" ID used for matching; any additional entries are secondaries whose
# EIA-923 delivered MWh is summed into the primary before computing the gap
# (handles cases where one historical project later split into multiple EIA
# reporting plants — i.e. Cohocton + Dutch Hill). wind_meta is left untouched.
EIA_ID_OVERRIDES: dict[str, list[int]] = {
    "wind_323617": [56634, 56633],  # Cohocton (primary) + Dutch Hill (split)
}

# Site_id → reason. Rows whose modeled side includes any of these sites are
# tagged "unverified" (modeled series may be wrong) and excluded from
# matched-fleet scorecard sums.
#
# Distinct from DEGRADED (below), which is reserved for plants that are
# CORRECTLY matched and located but operate below registered nameplate due
# to physical degradation — a method limitation, not a model error.
#
# IMPORTANT (2026-06-02): the earlier "lat/lon error" attribution for
# wind_323822/323706/323825/323626 was incorrect. wind_meta lat/lon for all
# four matches the USWTDB turbine-field centroid (over 25-84 turbines each)
# at 0.00 km — those coords are authoritative for HRRR cell selection. The
# previous comparison used the EIA-860 plant-level lat/lon, which is the
# operator's office address, not the turbine field. The EIA-923 loss-fraction
# outlier symptoms are real (Wethersfield 51% in 2023, Orangeville 30-44%
# sustained, Baron Winds 49-140%, Ball Hill TBD), but the cause is NOT
# location — it is physics (power curve, hub height, real curtailment, or
# HRRR pocket-scale bias). The plants stay in this bucket while a root-cause
# fix is pursued via the wind-model improvement plan (Task 1.x / 2.x).
# R1.3 RESOLVED (2026-06-02): wind_323822 (Baron Winds) removed from UNVERIFIED.
# Root cause of the "49-140% loss" was a NAMEPLATE error, not physics: wind_meta
# carried goldbook plate_mw=238.4 MW (a stale CRIS/registration figure), but the
# as-built capacity is 130.0 MW (EIA-860) / 121.8 MW (USWTDB 32 turbines =
# goldbook sum_2024/win_2024). The 1.96x inflation produced the spurious loss.
# Fixed in wind_meta.csv (238.4 -> 130.0) + a NAMEPLATE_OVERRIDES guard in
# 04_build_plant_metadata.py. With the correct nameplate the loss collapses to
# ~6% (2024) / ~24% (2023, partial year from COD 2023-02-07) — in band. The
# partial-year flag below excludes the pre-COD months. This was the ONLY plant
# in the fleet with a >30% nameplate-vs-USWTDB-capability discrepancy (audited).
UNVERIFIED: dict[str, str] = {
    "wind_323825": ("Ball Hill (EIA 65495, NP 107.5 MW, op 2023): EIA-923 "
                    "loss-fraction in outlier band. Coord verified against "
                    "USWTDB centroid (25 turbines, 0.00 km). Cause TBD — "
                    "candidate: commissioning ramp + physics bias."),
    "wind_323706": ("Stony Creek / Orangeville Wind (EIA 58088, NP 93.9 MW, "
                    "op 2013): EIA-923 loss fraction 30-44% sustained vs "
                    "matched-fleet 22-29% band; modeled CF ~50% (above NY "
                    "land-based plausibility) while EIA-923 CF ~30%. Coord "
                    "verified against USWTDB centroid (58 turbines, 0.00 km). "
                    "Cause TBD — candidate: real curtailment (Wyoming County "
                    "transmission), power-curve overstatement, or wrong "
                    "nameplate."),
    "wind_323839": ("South Fork Wind (EIA 65561, offshore, op 7/2024): EIA-923 "
                    "absent for 2024 despite EIA-860 Status=OP — offshore "
                    "reporting lag, not an ID error. Stays unverified until "
                    "EIA-923 publishes. Coord = EIA-860 (no USWTDB offshore "
                    "entry)."),
    "wind_323626": ("Noble Wethersfield (EIA 56902, NP 126 MW, op 2008): "
                    "EIA-923 loss fraction 51% in 2023, ~2× the 22-29% band. "
                    "Coord verified against USWTDB centroid (84 turbines, "
                    "0.00 km). Cause TBD — candidate: real curtailment, "
                    "power-curve bias on terrain, or aged-fleet availability."),
}

# Site_id → reason. "Degraded" plants are CORRECTLY matched and located, and
# the modeled potential generation is correct — but the real plant operates
# persistently below its EIA-860 registered nameplate due to physical
# degradation (turbine failures not replaced, etc.). Not a model error;
# affects any nameplate-driven potential model including PLUSWIND. Excluded
# from the matched-fleet headline but reported separately and for a different
# stated reason than UNVERIFIED.
DEGRADED: dict[str, str] = {
    "wind_24146": ("Madison Windpower LLC (EIA 55769, 11.5 MW, op 2000). "
                   "EIA-923 delivered output stepped down from CF~18% "
                   "(2018-2020) to CF~10% (2021-2022) and ~7-13% (2023-2024). "
                   "PLUSWIND raw matches pluswind_v3 within ~1% in every "
                   "overlap year, confirming this is a shared nameplate "
                   "assumption — not a v3-specific bug. EIA-860 still "
                   "reports the original 11.5 MW; real operating capacity is "
                   "lower without turbine-level reporting. 0.4% of fleet "
                   "nameplate; method limitation, not a defect."),
}

# Plants commissioned mid-year per EIA-860 'Operating Month' column. Long-table
# rows in months strictly before commissioning of the commission year are
# flagged partial_year=True. The scorecard excludes those rows from
# matched-fleet sums (model has output, plant didn't physically exist).
# Only listed here for plants whose commissioning month substantially affects
# the year's matched-bucket comparison; plants already in UNVERIFIED don't
# need a partial-year flag.
PARTIAL_YEAR_FIRST_OP_MONTH: dict[tuple[int, int], int] = {
    (2018, 58979): 12,  # Copenhagen Wind Farm — operating Dec 2018
    (2018, 61673): 8,   # Arkwright Summit Wind Farm — operating Aug 2018
    (2021, 58777): 7,   # Cassadaga Wind Farm — operating Jul 2021
    (2021, 61041): 10,  # Roaring Brook — operating Oct 2021
    (2023, 65522): 5,   # Number Three Wind Project — operating May 2023
    (2023, 66052): 2,   # Eight Point Wind — operating Feb 2023
    (2023, 60596): 2,   # Baron Winds — COD 2023-02-07 (EIA-923 Jan 2023 = 0);
                        #   added R1.3 after the nameplate fix moved it out of UNVERIFIED
}


# ---------- loaders ----------------------------------------------------------

def load_meta() -> pd.DataFrame:
    """Return wind_meta with the override applied as ``join_eia_id`` (the
    primary EIA ID from EIA_ID_OVERRIDES if present, else the wind_meta ID)."""
    meta = pd.read_csv(META_CSV)
    primary_map = {sid: ids[0] for sid, ids in EIA_ID_OVERRIDES.items()}
    meta["join_eia_id"] = (meta["site_id"].map(primary_map)
                           .fillna(meta["eia_plant_id"]).astype(int))
    def bucket_for(s):
        if s in UNVERIFIED: return "unverified"
        if s in DEGRADED:   return "degraded"
        return "matched"
    meta["site_bucket"] = meta["site_id"].apply(bucket_for)
    return meta


def get_eia_id_folds() -> dict[int, int]:
    """Return {secondary_eia_id: primary_eia_id} from EIA_ID_OVERRIDES."""
    folds: dict[int, int] = {}
    for ids in EIA_ID_OVERRIDES.values():
        primary = ids[0]
        for sec in ids[1:]:
            folds[sec] = primary
    return folds


def load_pluswind_v3_hourly() -> pd.DataFrame:
    """Concatenate all years of pluswind_v3 hourly actuals, tz-converted to
    US/Eastern. Site columns preserve their wind_<id> names; rows are hours."""
    frames = []
    for y in YEARS:
        f = WIND_DIR / f"wind_actual_1h_site_{y}_utc.pluswind_v3.csv"
        if not f.exists():
            print(f"  WARNING: missing {f}")
            continue
        df = pd.read_csv(f, parse_dates=["Time"])
        df["Time"] = df["Time"].dt.tz_convert("US/Eastern")
        frames.append(df)
    if not frames:
        raise RuntimeError("No pluswind_v3 hourly files found.")
    out = pd.concat(frames, axis=0, ignore_index=True, sort=False)
    return out.sort_values("Time").reset_index(drop=True)


def hourly_to_monthly_per_site(hourly: pd.DataFrame) -> pd.DataFrame:
    """Return long-format (year, month, site_id, modeled_potential_mwh)."""
    site_cols = [c for c in hourly.columns if c.startswith("wind_")]
    long = hourly.melt(id_vars=["Time"], value_vars=site_cols,
                       var_name="site_id", value_name="mw")
    long = long.dropna(subset=["mw"])
    long["year"]  = long["Time"].dt.year
    long["month"] = long["Time"].dt.month
    # hourly MW × 1 h = MWh
    monthly = (long.groupby(["year", "month", "site_id"], as_index=False,
                            observed=True)["mw"].sum()
                   .rename(columns={"mw": "modeled_potential_mwh"}))
    return monthly


def load_eia923_long() -> pd.DataFrame:
    """Reshape per-year EIA-923 NY wind CSVs to (year, month, eia_plant_id,
    plant_name, eia_delivered_mwh)."""
    frames = []
    month_cols = [f"netgen_mwh_{m}" for m in MONTH_NAMES]
    month_map  = {f"netgen_mwh_{m}": i + 1 for i, m in enumerate(MONTH_NAMES)}
    for y in YEARS:
        f = EIA923_DIR / f"eia923_ny_wind_{y}.csv"
        if not f.exists():
            print(f"  WARNING: missing {f}")
            continue
        df = pd.read_csv(f)
        long = df.melt(id_vars=["year", "eia_plant_id", "plant_name",
                                "operator_name", "nerc_region"],
                       value_vars=month_cols,
                       var_name="month_col", value_name="eia_delivered_mwh")
        long["month"] = long["month_col"].map(month_map)
        long = long.drop(columns=["month_col"])
        frames.append(long)
    out = pd.concat(frames, axis=0, ignore_index=True)
    out["eia_plant_id"] = out["eia_plant_id"].astype("Int64")
    # Fold secondaries into their primary (Dutch Hill 56633 → Cohocton 56634).
    # Sort rows so the primary precedes secondaries inside each (year, month)
    # group; the "first" name aggregator then deterministically picks the
    # primary's plant_name (avoids cosmetic flicker between e.g. Cohocton /
    # Dutch Hill labels in the long table).
    folds = get_eia_id_folds()
    if folds:
        out["_is_secondary"] = out["eia_plant_id"].isin(set(folds.keys())).astype(int)
        out["eia_plant_id"] = (out["eia_plant_id"].map(folds)
                               .fillna(out["eia_plant_id"]).astype("Int64"))
        out = out.sort_values(["year", "month", "eia_plant_id", "_is_secondary"])
        out = (out.groupby(["year", "month", "eia_plant_id"], as_index=False,
                           dropna=False)
                  .agg(plant_name=("plant_name", "first"),
                       operator_name=("operator_name", "first"),
                       nerc_region=("nerc_region", "first"),
                       eia_delivered_mwh=("eia_delivered_mwh", "sum")))
    return out


def load_eia860_capacity() -> pd.DataFrame:
    """EIA-860 plant-level capacity (sum across generators) — used for
    eia_only rows where wind_meta has no entry."""
    df = pd.read_csv(EIA860_CSV)
    grp = (df.groupby("eia_plant_id", as_index=False)
             .agg(eia860_nameplate_mw=("nameplate_mw", "sum"),
                  eia860_plant_name=("plant_name", "first")))
    grp["eia_plant_id"] = grp["eia_plant_id"].astype("Int64")
    return grp


# ---------- aggregation ------------------------------------------------------

def aggregate_modeled_per_eia_id(site_monthly: pd.DataFrame,
                                 meta: pd.DataFrame) -> pd.DataFrame:
    """Roll site-monthly to (year, month, join_eia_id), summing modeled MWh
    and modeled nameplate. If any contributing site is unverified the group is
    tagged unverified; else if any is degraded it's tagged degraded; else
    matched. Captures contributing site_ids in ``sites_aggregated``."""
    site_to_eia = meta.set_index("site_id")["join_eia_id"]
    site_to_cap = meta.set_index("site_id")["nameplate_mw"]
    site_to_bkt = meta.set_index("site_id")["site_bucket"]
    sm = site_monthly.copy()
    sm["eia_plant_id"]   = sm["site_id"].map(site_to_eia)
    sm["nameplate_mw"]   = sm["site_id"].map(site_to_cap)
    sm["site_bucket"]    = sm["site_id"].map(site_to_bkt)
    sm = sm.dropna(subset=["eia_plant_id"])
    sm["eia_plant_id"]   = sm["eia_plant_id"].astype("Int64")

    def combine_buckets(x):
        s = set(x)
        if "unverified" in s: return "unverified"
        if "degraded"   in s: return "degraded"
        return "matched"

    agg = (sm.groupby(["year", "month", "eia_plant_id"], as_index=False)
             .agg(modeled_potential_mwh=("modeled_potential_mwh", "sum"),
                  modeled_capacity_mw=("nameplate_mw", "sum"),
                  sites_aggregated=("site_id", lambda x: ",".join(sorted(set(x)))),
                  model_bucket=("site_bucket", combine_buckets)))
    return agg


def build_long_table() -> pd.DataFrame:
    print("Loading wind_meta...")
    meta = load_meta()
    print(f"  {len(meta)} sites, {meta['join_eia_id'].nunique()} unique join_eia_ids")
    print(f"  override applied: wind_323617 → 56634")
    n_unv = (meta['site_bucket'] == 'unverified').sum()
    n_deg = (meta['site_bucket'] == 'degraded').sum()
    print(f"  unverified bucket: {n_unv} sites — "
          f"{meta[meta['site_bucket'] == 'unverified']['site_id'].tolist()}")
    print(f"  degraded bucket:   {n_deg} sites — "
          f"{meta[meta['site_bucket'] == 'degraded']['site_id'].tolist()}")

    print("Loading pluswind_v3 hourly (all years) and tz-converting to US/Eastern...")
    hourly = load_pluswind_v3_hourly()
    print(f"  {len(hourly):,} rows, "
          f"{sum(1 for c in hourly.columns if c.startswith('wind_'))} site columns")

    print("Aggregating hourly → monthly per site...")
    site_monthly = hourly_to_monthly_per_site(hourly)

    print("Rolling site-monthly → (year, month, eia_plant_id)...")
    modeled_agg = aggregate_modeled_per_eia_id(site_monthly, meta)
    print(f"  {len(modeled_agg):,} modeled rows")

    print("Loading EIA-923 long format...")
    eia923 = load_eia923_long()
    print(f"  {len(eia923):,} EIA-923 rows")

    print("Outer-joining modeled vs EIA-923...")
    joined = modeled_agg.merge(
        eia923[["year", "month", "eia_plant_id", "plant_name", "eia_delivered_mwh"]],
        on=["year", "month", "eia_plant_id"], how="outer")

    # Tag bucket
    eia860 = load_eia860_capacity()
    joined = joined.merge(eia860, on="eia_plant_id", how="left")

    # Bucket logic
    def bucket(row):
        if pd.isna(row["modeled_potential_mwh"]):
            return "eia_only"
        return row["model_bucket"]
    joined["bucket"] = joined.apply(bucket, axis=1)

    # Bucket reason — distinguish degraded (method limitation) from
    # unverified (fixable data error) explicitly.
    def reason(row):
        if row["bucket"] == "eia_only":
            return "not in wind_meta (fleet coverage gap or BTM/small-turbine plant)"
        sites = row["sites_aggregated"] if isinstance(row["sites_aggregated"], str) else ""
        for s in sites.split(","):
            if s in UNVERIFIED:
                return UNVERIFIED[s]
        for s in sites.split(","):
            if s in DEGRADED:
                return DEGRADED[s]
        return ""
    joined["bucket_reason"] = joined.apply(reason, axis=1)

    # plant_name: prefer EIA-923 (more authoritative), fall back to EIA-860,
    # fall back to sites_aggregated.
    joined["plant_name"] = (joined["plant_name"]
                            .fillna(joined["eia860_plant_name"])
                            .fillna(joined["sites_aggregated"]))

    # capacity_mw: prefer modeled capacity (relevant for assessing OUR model);
    # fall back to EIA-860 capacity for eia_only rows.
    joined["capacity_mw"] = joined["modeled_capacity_mw"].fillna(
        joined["eia860_nameplate_mw"])

    # Gap (NaN where either side missing)
    joined["gap_mwh"] = joined["modeled_potential_mwh"] - joined["eia_delivered_mwh"]
    joined["gap_pct"] = 100 * joined["gap_mwh"] / joined["eia_delivered_mwh"]

    # Hours in month — Eastern calendar; tz-DST shifts are <1 h, ignored.
    joined["hours_in_month"] = joined.apply(
        lambda r: calendar.monthrange(int(r["year"]), int(r["month"]))[1] * 24,
        axis=1)
    joined["implied_capacity_factor_modeled"] = (
        joined["modeled_potential_mwh"]
        / (joined["capacity_mw"] * joined["hours_in_month"]))
    joined["implied_capacity_factor_eia"] = (
        joined["eia_delivered_mwh"]
        / (joined["capacity_mw"] * joined["hours_in_month"]))

    # Loss fraction = (modeled - EIA) / modeled — the metric used in the wind
    # document; expected 20-30% for NY wind (curtailment + availability + wake).
    joined["loss_fraction_pct"] = 100 * joined["gap_mwh"] / joined["modeled_potential_mwh"]

    # Partial-year flag (modeled output exists but plant hadn't commissioned)
    def _partial(row):
        op_month = PARTIAL_YEAR_FIRST_OP_MONTH.get(
            (int(row["year"]), int(row["eia_plant_id"]))
            if pd.notna(row["eia_plant_id"]) else (None, None))
        if op_month is None:
            return False
        return int(row["month"]) < op_month
    joined["partial_year_modeled"] = joined.apply(_partial, axis=1)

    cols = ["year", "month", "eia_plant_id", "plant_name",
            "capacity_mw", "modeled_potential_mwh", "eia_delivered_mwh",
            "gap_mwh", "gap_pct", "loss_fraction_pct",
            "implied_capacity_factor_modeled", "implied_capacity_factor_eia",
            "bucket", "bucket_reason", "sites_aggregated",
            "partial_year_modeled", "hours_in_month"]
    # Drop UTC→Eastern boundary fragments (Dec 2017, Jan 2025): only a handful
    # of hours of modeled data per plant, no EIA side, no monthly meaning.
    joined = joined[joined["year"].isin(YEARS)]
    out = (joined[cols]
           .sort_values(["year", "month", "eia_plant_id"])
           .reset_index(drop=True))
    return out


def main() -> None:
    EIA923_DIR.mkdir(parents=True, exist_ok=True)
    long_df = build_long_table()
    long_df.to_csv(OUT_CSV, index=False)
    print()
    print(f"=== wrote {OUT_CSV} ({len(long_df):,} rows) ===")
    print()
    print("Bucket counts:")
    print(long_df["bucket"].value_counts().to_string())
    print()
    print("Per-bucket coverage summary:")
    summary = (long_df.groupby("bucket")
                    .agg(rows=("year", "size"),
                         n_plants=("eia_plant_id", "nunique"),
                         modeled_twh=("modeled_potential_mwh",
                                      lambda x: x.sum() / 1e6),
                         eia_twh=("eia_delivered_mwh",
                                  lambda x: x.sum() / 1e6)))
    print(summary.to_string())


if __name__ == "__main__":
    main()
