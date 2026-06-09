"""Score pluswind_v3 against EIA-923 operator-reported delivered generation,
expanded scorecard structure per the validation spec.

Inputs
------
- PGscen-2nd/data/NYISO_real/eia923/eia923_vs_pluswind_v3_long.csv  (from
  scripts/12_join_eia923_to_pluswind.py)
- PGscen-2nd/data/NYISO_real/plant_metadata/wind_meta.csv

Outputs
-------
- docs/figures/wind_v3/eia923_scorecard.csv         per-plant per-year
- docs/figures/wind_v3/eia923_fleet_scorecard.csv   per-year fleet rollups
                                                   incl. sensitivity subsets
- docs/figures/wind_v3/eia923_zone_era_decomp.csv   zone × commissioning era
- docs/figures/wind_v3/eia923_cf_vs_loss.csv        per-plant scatter data

Metrics
-------
The wind document expects 20-30% loss fraction for NY wind (curtailment +
availability + wake). The scorecard reports three related metrics so the
"loss fraction" vs "gap percent" distinction is unambiguous:

  gap_pct          = (modeled - EIA) / EIA × 100      (modeled-over-EIA)
  loss_fraction_pct = (modeled - EIA) / modeled × 100  (curtailment+availability)
  mod_eia_ratio    = modeled / EIA                    (raw ratio)

Outlier rules (per spec, applied to annual matched-bucket rows only):
  - annual_gap_pct < 0   model below EIA (suspect modeled potential)
  - annual_gap_pct > 25  model far above EIA (heavy curtailment / repower
                          / model bug); equivalent to loss_fraction > 20%
  - monthly_gap_pct_std > 15 pp  inconsistent curtailment / availability

NYISO curtailment cross-reference
---------------------------------
``NYISO_WIND_CURTAILMENT_PCT`` is hand-transcribed from Potomac Economics
State-of-the-Market reports (annual NYISO market monitor). These are
approximate first-pass values; verify against the PDFs before quoting in
external writeups. The "residual loss" column reports loss_fraction minus
NYISO curtailment — the part that's NOT explained by reported curtailment
(availability + wake + model bias). Should sit around 5-10%.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

# Physics variant. Default 'v4' (production); set PLUSWIND_VARIANT=v3 to
# reproduce the single-cell scorecard. Input long-table and all output
# scorecards carry the variant suffix so v3 and v4 coexist on disk.
VARIANT = os.environ.get("PLUSWIND_VARIANT", "v4")
_SUF = f"_{VARIANT}"

REPO_ROOT = Path(__file__).resolve().parents[2]
LONG_CSV  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "eia923" / f"eia923_vs_pluswind_{VARIANT}_long.csv"
META_CSV  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata" / "wind_meta.csv"
OUT_DIR   = REPO_ROOT / "docs" / "figures" / "wind_v3"

OUT_SCORECARD   = OUT_DIR / f"eia923_scorecard{_SUF}.csv"
OUT_FLEET       = OUT_DIR / f"eia923_fleet_scorecard{_SUF}.csv"
OUT_DECOMP      = OUT_DIR / f"eia923_zone_era_decomp{_SUF}.csv"
OUT_CF_VS_LOSS  = OUT_DIR / f"eia923_cf_vs_loss{_SUF}.csv"

YEARS = list(range(2018, 2025))

# NYISO transmission/economic wind curtailment from NYISO Power Trends 2024
# (https://www.nyiso.com/documents/20142/2223020/2024-Power-Trends.pdf,
#  Figure 18 "Wind Generation and Curtailment (GWh): 2004-2023", p. 47).
# Values are curtailment GWh / wind generation GWh × 100. Note these reflect
# NYISO's reported economic+transmission curtailment ONLY — they exclude:
#   - reliability-driven OOM commitments that reduce wind output (the 2022
#     NYISO SOM explicitly called this out for the North Country load pocket)
#   - self-curtailment for negative prices outside the NYISO signal
#   - wake losses inside wind farms
#   - availability (mechanical / electrical downtime)
# So the "residual" reported in the scorecard (loss_fraction - this number) is
# wake + availability + uncounted curtailment + model bias combined, not
# pure availability+wake. Expect a residual of 15-25%.
# 2024: not in Power Trends 2024 (covers through 2023); will appear in
# Power Trends 2025 published mid-2026.
NYISO_WIND_CURTAILMENT_PCT: dict[int, float | None] = {
    2018: 1.1,   # 43 / 3985 GWh
    2019: 1.6,   # 70 / 4454
    2020: 1.5,   # 63 / 4162
    2021: 2.0,   # 84 / 4111
    2022: 3.4,   # 162 / 4825
    2023: 3.4,   # 162 / 4816
    2024: None,  # unpublished as of May 2026
}

# Plants the user wants to test sensitivity on (unverified-bucket + Number
# Three Wind, the partial-year matched plant). Identifiers below are EIA IDs
# after the Cohocton+Dutch Hill fold.
SENS_PLANTS: dict[str, int] = {
    "Wethersfield (56902)":              56902,
    "Stony Creek / Orangeville (58088)": 58088,
    "Baron Winds (60596)":               60596,
    "Number Three (65522)":              65522,
}

OUTLIER_RULES = {
    "flag_low_gap":         "annual gap_pct < 0  (modeled below EIA)",
    "flag_high_gap":        "annual gap_pct > 25 (modeled far above EIA)",
    "flag_high_monthly_std": "monthly gap_pct std > 15 pp",
}


# ---------- loaders / helpers ------------------------------------------------

def load_long() -> pd.DataFrame:
    df = pd.read_csv(LONG_CSV)
    df["eia_plant_id"] = df["eia_plant_id"].astype("Int64")
    return df


def load_meta_aux() -> pd.DataFrame:
    """Per-eia_id auxiliary metadata: zone, op_year (min across rows sharing
    an EIA ID, e.g. Maple Ridge 1/2)."""
    meta = pd.read_csv(META_CSV)
    aux = (meta.groupby("eia_plant_id", as_index=False)
                .agg(zone=("zone", "first"),
                     op_year=("operating_year", "min")))
    aux["eia_plant_id"] = aux["eia_plant_id"].astype("Int64")
    # Apply EIA-ID override from join script: wind_323617's "true" EIA ID is 56634
    aux_override = (meta[meta["site_id"] == "wind_323617"]
                    .assign(eia_plant_id=56634)
                    .groupby("eia_plant_id", as_index=False)
                    .agg(zone=("zone", "first"),
                         op_year=("operating_year", "min")))
    aux_override["eia_plant_id"] = aux_override["eia_plant_id"].astype("Int64")
    aux = pd.concat([aux, aux_override], ignore_index=True)
    aux = aux.drop_duplicates("eia_plant_id", keep="last")
    return aux


def loss_fraction(mod: float, eia: float) -> float:
    if mod == 0 or pd.isna(mod) or pd.isna(eia):
        return float("nan")
    return 100.0 * (mod - eia) / mod


def annual_rollup(df: pd.DataFrame, group_keys: list[str]) -> pd.DataFrame:
    """Aggregate monthly rows to annual sums per group, computing all three
    metrics. Excludes rows flagged partial_year_modeled."""
    sub = df[~df["partial_year_modeled"].fillna(False)]
    agg = (sub.groupby(group_keys, as_index=False, dropna=False)
              .agg(plant_name=("plant_name", "first"),
                   capacity_mw=("capacity_mw", "first"),
                   modeled_mwh=("modeled_potential_mwh", "sum"),
                   eia_mwh=("eia_delivered_mwh", "sum"),
                   bucket=("bucket", "first"),
                   sites_aggregated=("sites_aggregated", "first"),
                   monthly_gap_pct_mean=("gap_pct", "mean"),
                   monthly_gap_pct_std=("gap_pct", "std"),
                   monthly_gap_pct_min=("gap_pct", "min"),
                   monthly_gap_pct_max=("gap_pct", "max"),
                   monthly_loss_frac_mean=("loss_fraction_pct", "mean"),
                   monthly_loss_frac_std=("loss_fraction_pct", "std"),
                   n_months=("month", "size")))
    agg["gap_mwh"] = agg["modeled_mwh"] - agg["eia_mwh"]
    agg["gap_pct"] = 100 * agg["gap_mwh"] / agg["eia_mwh"]
    agg["loss_fraction_pct"] = 100 * agg["gap_mwh"] / agg["modeled_mwh"]
    agg["mod_eia_ratio"] = agg["modeled_mwh"] / agg["eia_mwh"]
    return agg


def hours_in_year(y: int) -> int:
    return 8784 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 8760


# ---------- builders ---------------------------------------------------------

def build_per_plant_scorecard(long: pd.DataFrame, aux: pd.DataFrame) -> pd.DataFrame:
    """Per-plant annual scorecard for matched + unverified + degraded buckets
    (excludes eia_only). Partial-year first-months are excluded from the
    annual sums."""
    relevant = long[long["bucket"].isin(["matched", "unverified", "degraded"])]
    per_plant = annual_rollup(relevant, ["year", "eia_plant_id"])
    per_plant = per_plant.merge(aux, on="eia_plant_id", how="left")
    per_plant["modeled_cf"] = per_plant.apply(
        lambda r: r["modeled_mwh"] / (r["capacity_mw"] * hours_in_year(int(r["year"])))
                  if r["capacity_mw"] > 0 else float("nan"), axis=1)
    per_plant["eia_cf"] = per_plant.apply(
        lambda r: r["eia_mwh"] / (r["capacity_mw"] * hours_in_year(int(r["year"])))
                  if r["capacity_mw"] > 0 else float("nan"), axis=1)

    # Outlier flags — only meaningful for matched plants (unverified/degraded
    # have their own explanatory reasons; flagging them via these rules is
    # redundant)
    is_matched = per_plant["bucket"] == "matched"
    per_plant["flag_low_gap"]         = (per_plant["gap_pct"] < 0) & is_matched
    per_plant["flag_high_gap"]        = (per_plant["gap_pct"] > 25) & is_matched
    per_plant["flag_high_monthly_std"] = (per_plant["monthly_gap_pct_std"] > 15) & is_matched
    per_plant["flag_count"] = (per_plant["flag_low_gap"].astype(int)
                               + per_plant["flag_high_gap"].astype(int)
                               + per_plant["flag_high_monthly_std"].astype(int))

    # Also flag partial-year for transparency: count how many rows excluded
    partial_count = (long[(long["partial_year_modeled"].fillna(False))
                          & (long["bucket"].isin(["matched", "unverified", "degraded"]))]
                     .groupby(["year", "eia_plant_id"]).size()
                     .rename("partial_months_excluded").reset_index())
    partial_count["eia_plant_id"] = partial_count["eia_plant_id"].astype("Int64")
    per_plant = per_plant.merge(partial_count, on=["year", "eia_plant_id"], how="left")
    per_plant["partial_months_excluded"] = per_plant["partial_months_excluded"].fillna(0).astype(int)

    cols = ["year", "eia_plant_id", "plant_name", "zone", "op_year",
            "capacity_mw", "modeled_mwh", "eia_mwh", "gap_mwh",
            "gap_pct", "loss_fraction_pct", "mod_eia_ratio",
            "modeled_cf", "eia_cf",
            "monthly_gap_pct_mean", "monthly_gap_pct_std",
            "monthly_gap_pct_min", "monthly_gap_pct_max",
            "monthly_loss_frac_mean", "monthly_loss_frac_std",
            "bucket", "n_months", "partial_months_excluded",
            "flag_low_gap", "flag_high_gap", "flag_high_monthly_std", "flag_count",
            "sites_aggregated"]
    return per_plant[cols].sort_values(["year", "eia_plant_id"]).reset_index(drop=True)


def build_fleet_scorecard(long: pd.DataFrame) -> pd.DataFrame:
    """Per-year fleet rollups under multiple plant-subset definitions.
    Reports both gap and loss fraction, plus NYISO curtailment cross-reference
    and residual loss (loss_fraction - NYISO_curtailment).
    """
    # Subsets: each is (label, predicate on row → bool)
    matched_ids   = set(long.loc[long["bucket"] == "matched", "eia_plant_id"].dropna().astype(int))
    unverified_ids = set(long.loc[long["bucket"] == "unverified", "eia_plant_id"].dropna().astype(int))

    subsets: dict[str, set[int]] = {}
    subsets["matched_baseline"]                  = matched_ids
    subsets["matched_minus_NumberThree"]         = matched_ids - {65522}
    for name, pid in SENS_PLANTS.items():
        if pid in matched_ids:
            subsets[f"matched_minus_{name}"]    = matched_ids - {pid}
        else:
            subsets[f"matched_plus_{name}"]     = matched_ids | {pid}
    # Combined: matched with all four unverified-and-NT removed
    subsets["matched_minus_all_four"]            = matched_ids - set(SENS_PLANTS.values())
    # And the inverse: matched plus all three unverified (treat unverified as
    # if matched, see how much they inflate the gap)
    subsets["matched_plus_three_unverified_with_EIA"] = matched_ids | (set(SENS_PLANTS.values()) & unverified_ids)

    rows = []
    for label, ids in subsets.items():
        sub = long[(long["eia_plant_id"].astype("Int64").isin(ids))
                   & (~long["partial_year_modeled"].fillna(False))]
        per_year = (sub.groupby("year", as_index=False)
                       .agg(n_plants=("eia_plant_id", "nunique"),
                            capacity_mw_sum=("capacity_mw", "sum"),
                            modeled_mwh=("modeled_potential_mwh", "sum"),
                            eia_mwh=("eia_delivered_mwh", "sum")))
        for _, r in per_year.iterrows():
            y = int(r["year"])
            mod, eia = r["modeled_mwh"], r["eia_mwh"]
            gap_pct  = 100 * (mod - eia) / eia if eia > 0 else float("nan")
            loss_pct = 100 * (mod - eia) / mod if mod > 0 else float("nan")
            curt = NYISO_WIND_CURTAILMENT_PCT.get(y)
            residual = (loss_pct - curt) if (curt is not None and not pd.isna(loss_pct)) else float("nan")
            rows.append({
                "subset":            label,
                "year":              y,
                "n_plants":          int(r["n_plants"]),
                "modeled_twh":       mod / 1e6,
                "eia_twh":           eia / 1e6,
                "gap_pct":           gap_pct,
                "loss_fraction_pct": loss_pct,
                "mod_eia_ratio":     mod / eia if eia > 0 else float("nan"),
                "nyiso_curt_pct":    curt,
                "residual_loss_pct": residual,
            })
    return pd.DataFrame(rows)


def build_zone_era_decomp(long: pd.DataFrame, aux: pd.DataFrame) -> pd.DataFrame:
    """Mean loss fraction binned by (zone, commissioning era). Matched bucket
    only, partial-year rows excluded. Eras: pre-2010, 2010-2014, 2015-2019,
    2020+."""
    matched_annual = annual_rollup(long[long["bucket"] == "matched"],
                                   ["year", "eia_plant_id"])
    matched_annual = matched_annual.merge(aux, on="eia_plant_id", how="left")

    def era(y):
        if pd.isna(y): return "unknown"
        y = int(y)
        if y < 2010:  return "pre-2010"
        if y < 2015:  return "2010-2014"
        if y < 2020:  return "2015-2019"
        return "2020+"
    matched_annual["era"] = matched_annual["op_year"].apply(era)

    decomp = (matched_annual.groupby(["zone", "era"], as_index=False)
                            .agg(n_plant_years=("eia_plant_id", "size"),
                                 n_plants=("eia_plant_id", "nunique"),
                                 modeled_twh=("modeled_mwh", lambda x: x.sum() / 1e6),
                                 eia_twh=("eia_mwh", lambda x: x.sum() / 1e6)))
    decomp["loss_fraction_pct"] = 100 * (decomp["modeled_twh"] - decomp["eia_twh"]) / decomp["modeled_twh"]
    decomp["mod_eia_ratio"] = decomp["modeled_twh"] / decomp["eia_twh"]
    return decomp.sort_values(["zone", "era"]).reset_index(drop=True)


def build_cf_vs_loss_table(per_plant: pd.DataFrame) -> pd.DataFrame:
    """Per-plant table for the CF-vs-loss scatter. Aggregates across years,
    matched bucket only — unverified and degraded plants have known
    non-curtailment explanations that would obscure the scatter."""
    matched_only = per_plant[per_plant["bucket"] == "matched"]
    cf_loss = (matched_only.groupby(["eia_plant_id", "plant_name", "zone", "op_year"],
                                  as_index=False)
                        .agg(modeled_twh=("modeled_mwh", lambda x: x.sum() / 1e6),
                             eia_twh=("eia_mwh", lambda x: x.sum() / 1e6),
                             capacity_mw=("capacity_mw", "first"),
                             n_years=("year", "size")))
    cf_loss["modeled_cf_mean"] = (cf_loss["modeled_twh"] * 1e6
        / (cf_loss["capacity_mw"] * cf_loss["n_years"] * 8766))  # avg 8766 h/yr incl leaps
    cf_loss["eia_cf_mean"]     = (cf_loss["eia_twh"] * 1e6
        / (cf_loss["capacity_mw"] * cf_loss["n_years"] * 8766))
    cf_loss["loss_fraction_pct"] = 100 * (cf_loss["modeled_twh"] - cf_loss["eia_twh"]) / cf_loss["modeled_twh"]
    return cf_loss.sort_values("modeled_cf_mean", ascending=False).reset_index(drop=True)


# ---------- printing ---------------------------------------------------------

def print_per_year_fleet(fleet: pd.DataFrame) -> None:
    print("=" * 100)
    print("Annual fleet rollup — MATCHED bucket (current scorecard headline)")
    print("=" * 100)
    base = fleet[fleet["subset"] == "matched_baseline"].sort_values("year")
    print(f"{'year':>5} {'n':>3} {'mod_TWh':>8} {'EIA_TWh':>8} {'gap%':>7} "
          f"{'loss%':>7} {'NYISO_curt%':>11} {'residual%':>10}")
    for _, r in base.iterrows():
        curt = "—" if r["nyiso_curt_pct"] is None or pd.isna(r["nyiso_curt_pct"]) else f"{r['nyiso_curt_pct']:.1f}"
        resid = "—" if pd.isna(r["residual_loss_pct"]) else f"{r['residual_loss_pct']:.1f}"
        print(f"{int(r['year']):>5} {r['n_plants']:>3} {r['modeled_twh']:>8.2f} "
              f"{r['eia_twh']:>8.2f} {r['gap_pct']:>6.1f}% {r['loss_fraction_pct']:>6.1f}% "
              f"{curt:>10}% {resid:>9}%")


def print_sensitivity(fleet: pd.DataFrame) -> None:
    print()
    print("=" * 100)
    print("Sensitivity to bucketed/problematic plants — pooled 2018-2024 loss fraction")
    print("=" * 100)
    pooled = (fleet.groupby("subset", as_index=False)
                   .agg(modeled_twh=("modeled_twh", "sum"),
                        eia_twh=("eia_twh", "sum")))
    pooled["loss_fraction_pct"] = 100 * (pooled["modeled_twh"] - pooled["eia_twh"]) / pooled["modeled_twh"]
    pooled["mod_eia_ratio"] = pooled["modeled_twh"] / pooled["eia_twh"]
    # Order: baseline first, then named removals, then aggregates
    order = ["matched_baseline",
             "matched_minus_NumberThree",
             "matched_minus_Wethersfield (56902)",
             "matched_plus_Stony Creek / Orangeville (58088)",
             "matched_plus_Baron Winds (60596)",
             "matched_minus_all_four",
             "matched_plus_three_unverified_with_EIA"]
    pooled["sort_key"] = pooled["subset"].apply(lambda s: order.index(s) if s in order else 999)
    pooled = pooled.sort_values("sort_key").drop(columns=["sort_key"])
    print(f"{'subset':<55} {'mod_TWh':>8} {'EIA_TWh':>8} {'loss%':>7} {'ratio':>6}")
    for _, r in pooled.iterrows():
        print(f"{r['subset']:<55} {r['modeled_twh']:>8.2f} {r['eia_twh']:>8.2f} "
              f"{r['loss_fraction_pct']:>6.1f}% {r['mod_eia_ratio']:>5.2f}")


def print_zone_era(decomp: pd.DataFrame) -> None:
    print()
    print("=" * 100)
    print("Loss fraction decomposition by (zone, commissioning era) — matched bucket only")
    print("=" * 100)
    pivot = decomp.pivot_table(index="zone", columns="era",
                                values="loss_fraction_pct", aggfunc="first")
    print(pivot.to_string(float_format=lambda x: f"{x:>6.1f}%" if pd.notna(x) else "    —"))
    print()
    print(f"{'zone':>5} {'era':>10} {'n_plt-yr':>9} {'n_plt':>5} {'mod_TWh':>8} {'EIA_TWh':>8} {'loss%':>7}")
    for _, r in decomp.iterrows():
        print(f"{r['zone']:>5} {r['era']:>10} {r['n_plant_years']:>9} {r['n_plants']:>5} "
              f"{r['modeled_twh']:>8.3f} {r['eia_twh']:>8.3f} {r['loss_fraction_pct']:>6.1f}%")


def print_non_matched(per_plant: pd.DataFrame) -> None:
    """Print unverified + degraded plants separately from the matched headline.
    These don't count toward the fleet number but each carries its own
    diagnostic story (errors vs method limitations)."""
    print()
    print("=" * 100)
    print("Non-matched bucket — UNVERIFIED (fixable errors) and DEGRADED "
          "(method limitations) plants")
    print("=" * 100)
    for bkt in ["unverified", "degraded"]:
        sub = per_plant[per_plant["bucket"] == bkt]
        if len(sub) == 0:
            continue
        print()
        print(f"{bkt.upper()}:")
        print(f"  {'year':>5} {'eia_id':>6} {'plant_name':<32} "
              f"{'mod_GWh':>8} {'EIA_GWh':>8} {'loss%':>7} {'ratio':>6}")
        for _, r in sub.sort_values(["eia_plant_id", "year"]).iterrows():
            print(f"  {int(r['year']):>5} {int(r['eia_plant_id']):>6} "
                  f"{str(r['plant_name'])[:32]:<32} "
                  f"{r['modeled_mwh']/1000:>8.1f} {r['eia_mwh']/1000:>8.1f} "
                  f"{r['loss_fraction_pct']:>6.1f}% {r['mod_eia_ratio']:>5.2f}x")


def print_outliers(per_plant: pd.DataFrame) -> None:
    print()
    print("=" * 100)
    print("Outlier plants (matched bucket) — per spec rules")
    print("=" * 100)
    flagged = per_plant[per_plant["flag_count"] > 0].sort_values(
        ["flag_count", "year", "eia_plant_id"], ascending=[False, True, True])
    if len(flagged) == 0:
        print("(none)")
        return
    cols_show = ["year","eia_plant_id","plant_name","zone","op_year",
                 "capacity_mw","modeled_cf","eia_cf","gap_pct","loss_fraction_pct",
                 "monthly_gap_pct_std",
                 "flag_low_gap","flag_high_gap","flag_high_monthly_std","partial_months_excluded"]
    print(flagged[cols_show].to_string(index=False, float_format=lambda x: f"{x:.2f}"))


def print_cf_vs_loss(cf_loss: pd.DataFrame) -> None:
    print()
    print("=" * 100)
    print("Per-plant pooled (modeled CF, loss fraction) — matched bucket")
    print("=" * 100)
    cl = cf_loss.dropna(subset=["modeled_cf_mean", "loss_fraction_pct"])
    corr = cl["modeled_cf_mean"].corr(cl["loss_fraction_pct"])
    print(f"Pearson corr (modeled_cf, loss_fraction_pct): {corr:+.3f}")
    print(f"  >0 means high-CF plants have higher loss fraction "
          f"(curtailment-driven story)")
    print(f"  <0 means high-CF plants have lower loss fraction "
          f"(physics-bias-driven story)")
    print()
    print(cl[["eia_plant_id","plant_name","zone","op_year",
              "capacity_mw","modeled_cf_mean","eia_cf_mean",
              "loss_fraction_pct"]].to_string(index=False,
                                                float_format=lambda x: f"{x:.3f}"))


# ---------- main -------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    long = load_long()
    aux  = load_meta_aux()

    per_plant = build_per_plant_scorecard(long, aux)
    fleet     = build_fleet_scorecard(long)
    decomp    = build_zone_era_decomp(long, aux)
    cf_loss   = build_cf_vs_loss_table(per_plant)

    print_per_year_fleet(fleet)
    print_sensitivity(fleet)
    print_zone_era(decomp)
    print_non_matched(per_plant)
    print_outliers(per_plant)
    print_cf_vs_loss(cf_loss)

    per_plant.to_csv(OUT_SCORECARD, index=False)
    fleet.to_csv(OUT_FLEET, index=False)
    decomp.to_csv(OUT_DECOMP, index=False)
    cf_loss.to_csv(OUT_CF_VS_LOSS, index=False)

    print()
    print(f"Wrote {OUT_SCORECARD}")
    print(f"Wrote {OUT_FLEET}")
    print(f"Wrote {OUT_DECOMP}")
    print(f"Wrote {OUT_CF_VS_LOSS}")


if __name__ == "__main__":
    main()
