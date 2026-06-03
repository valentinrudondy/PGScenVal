"""R1.1 step 2 — alpha distribution diagnostic + offline alpha-sensitivity sweep.

Reads the raw HRRR ws80/ws10/pres/t2m dumped by fetch_alpha_raw.py and:

  1. ALPHA DISTRIBUTION (primary, model-independent signal). Per-cell-hour
     alpha = ln(ws80/ws10)/ln(8) over all ~180 fleet cells. Median, P10/P50/P90,
     fraction above 0.20/0.25/0.40, split day vs night and by season, compared
     to onshore climatology (~0.14-0.20). If HRRR median alpha >> climatology,
     the hub-lift is inflated regardless of loss bookkeeping.

  2. SENSITIVITY SWEEP on the pilot plants (Copenhagen + Marble agg). Recompute
     hub-shear power under {v4 no-hub, full alpha, clip 0.20, clip 0.25,
     climatology blend w=0.5} and score vs PLUSWIND 2020 (potential-grade) and
     Copenhagen LPI 2024 (clean metered anchor). Tracks how the Copenhagen
     overshoot and ramp_r move with the treatment.

  3. COPENHAGEN EIA-923 BOUND (interpretive). Pull Copenhagen's pooled EIA-923
     loss fraction — a clean plant with a few-% real loss makes a few-% potential-
     over-metered EXPECTED, so the Copenhagen LPI bias must be read against it,
     not used as a mechanical reject of hub-shear.

Output: docs/figures/wind_v3/alpha_diagnostic.csv (distribution),
        docs/figures/wind_v3/alpha_sensitivity.csv (sweep),
        prints the DECISION-ready tables.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "PGscen-2nd"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pgscen.utils.wind_physics import (  # noqa: E402
    build_sam_curves,
    pluswind_v4_power_multicell_A,
    pluswind_v5_power_multicell_A_hubshear,
)
from score_multicell_pilot import (  # noqa: E402
    load_pluswind_for_sites, load_lpi_groups, metrics, LPI_GROUPS,
)

PM_DIR  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
EIA_DIR = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "eia923"
OUT_DIR = REPO_ROOT / "docs" / "figures" / "wind_v3"

PILOT_SITES = ["wind_323753",                                    # Copenhagen (A2, 95 m)
               "wind_323696", "wind_323614", "wind_323605", "wind_323604"]  # Marble agg
COPENHAGEN_EIA = 58979

ALPHA_CLIMATOLOGY = (0.14, 0.20)   # onshore power-law reference band

TREATMENTS = {
    "v4_nohub":  None,                              # multi-A, no shear (baseline)
    "full":      {},                                # pure HRRR alpha, clip [-0.10,0.40]
    "clip0.20":  {"alpha_max": 0.20},
    "clip0.25":  {"alpha_max": 0.25},
    "blend0.5":  {"blend_weight": 0.5},             # 50% toward 1/7
}


def load_raw(year: int):
    f = OUT_DIR / f"alpha_raw_{year}.npz"
    if not f.exists():
        return None
    d = np.load(f, allow_pickle=True)
    return {
        "ws80": d["ws80"], "ws10": d["ws10"], "pres": d["pres"], "t2m": d["t2m"],
        "times": pd.to_datetime(d["times"], unit="s", utc=True).tz_convert("UTC").tz_localize(None),
        "W": d["W"], "site_ids": [str(s) for s in d["site_ids"]],
        "nameplate_mw": d["nameplate_mw"], "hub_h": d["hub_h"],
        "dominant_cell_col": d["dominant_cell_col"],
    }


def raw_alpha(ws80, ws10):
    """Unclipped alpha (ws10>=1 guard -> NaN, excluded from the distribution)."""
    a = np.full_like(ws80, np.nan)
    ok = (ws10 >= 1.0) & (ws80 > 0)
    a[ok] = np.log(ws80[ok] / ws10[ok]) / np.log(8.0)
    return a


def alpha_distribution(raws: dict) -> pd.DataFrame:
    rows = []
    for year, R in raws.items():
        if R is None:
            continue
        a = raw_alpha(R["ws80"], R["ws10"])            # (n_hours, n_cells)
        times = R["times"]
        local_hour = (times.hour - 5) % 24             # EST local
        is_day   = (local_hour >= 10) & (local_hour <= 15)
        is_night = (local_hour >= 22) | (local_hour <= 4)
        month = times.month
        season = pd.Series(np.select(
            [month.isin([12, 1, 2]), month.isin([3, 4, 5]),
             month.isin([6, 7, 8]), month.isin([9, 10, 11])],
            ["DJF", "MAM", "JJA", "SON"], default=""), index=range(len(times)))

        def stat(mask_hours, label):
            sub = a[mask_hours.to_numpy(), :].ravel() if hasattr(mask_hours, "to_numpy") else a[mask_hours, :].ravel()
            sub = sub[~np.isnan(sub)]
            if sub.size == 0:
                return None
            return {
                "year": year, "subset": label, "n": int(sub.size),
                "alpha_p10": float(np.percentile(sub, 10)),
                "alpha_median": float(np.median(sub)),
                "alpha_mean": float(sub.mean()),
                "alpha_p90": float(np.percentile(sub, 90)),
                "frac_gt_0.20": float((sub > 0.20).mean()),
                "frac_gt_0.25": float((sub > 0.25).mean()),
                "frac_gt_0.40": float((sub > 0.40).mean()),
            }

        allmask = np.ones(len(times), dtype=bool)
        for r in [stat(allmask, "all"),
                  stat(is_day, "day(10-15 EST)"),
                  stat(is_night, "night(22-04 EST)")]:
            if r:
                rows.append(r)
        for s in ["DJF", "MAM", "JJA", "SON"]:
            r = stat((season == s).to_numpy(), f"season:{s}")
            if r:
                rows.append(r)
    return pd.DataFrame(rows)


def sensitivity(raws: dict) -> pd.DataFrame:
    meta = pd.read_csv(PM_DIR / "wind_meta.csv")
    turbines = pd.read_csv(PM_DIR / "uswtdb_ny_turbines.csv")
    meta_sub = meta[meta["site_id"].isin(PILOT_SITES)].reset_index(drop=True)

    rows = []
    for year, R in raws.items():
        if R is None:
            continue
        # Build SAM curves for the pilot plants (year-aware), and subset W.
        curve_ws, curve_cf, rated_ws = build_sam_curves(meta_sub, turbines, year=year)
        nameplate = meta_sub["nameplate_mw"].to_numpy(float)
        # Map pilot site_ids -> rows in the full-fleet W stored in npz.
        full_ids = R["site_ids"]
        plant_rows = [full_ids.index(s) for s in meta_sub["site_id"]]
        W_sub = R["W"][plant_rows, :]                  # (5, n_cells)
        hub_h = np.array([R["hub_h"][i] for i in plant_rows])
        ws80 = R["ws80"]; ws10 = R["ws10"]; pres = R["pres"]; t2m = R["t2m"]
        n_hours = ws80.shape[0]
        times = R["times"]

        # Reference series for scoring.
        if 2018 <= year <= 2021:
            ref_wide = load_pluswind_for_sites([year], list(meta_sub["site_id"]), meta)
            ref_kind = "pluswind"
        else:
            ref_wide = None
        lpi = load_lpi_groups([year]) if year >= 2022 else None

        # Compute power per treatment (loop hours; v5 is per-hour).
        for tname, akw in TREATMENTS.items():
            P = np.full((n_hours, len(meta_sub)), np.nan)
            for h in range(n_hours):
                if np.isnan(ws80[h]).all():
                    continue
                if tname == "v4_nohub":
                    P[h] = pluswind_v4_power_multicell_A(
                        ws80[h], pres[h], t2m[h], W_sub, nameplate,
                        curve_ws, curve_cf, rated_ws)
                else:
                    P[h] = pluswind_v5_power_multicell_A_hubshear(
                        ws80[h], ws10[h], pres[h], t2m[h], W_sub, hub_h,
                        nameplate, curve_ws, curve_cf, rated_ws,
                        alpha_kwargs=akw)
            Pdf = pd.DataFrame(P, index=times, columns=list(meta_sub["site_id"]))

            # Score vs PLUSWIND (per-plant + Marble agg + fleet) for 2018-2021.
            if ref_wide is not None:
                # Copenhagen single
                if "wind_323753" in ref_wide.columns:
                    m = metrics(Pdf["wind_323753"], ref_wide["wind_323753"], tname)
                    rows.append({"year": year, "ref": "pluswind", "target": "copenhagen",
                                 "treatment": tname, **m})
                # Marble agg (sum of 4)
                marble = [s for s in ["wind_323696","wind_323614","wind_323605","wind_323604"]
                          if s in ref_wide.columns]
                if marble:
                    m = metrics(Pdf[marble].sum(axis=1), ref_wide[marble].sum(axis=1), tname)
                    rows.append({"year": year, "ref": "pluswind", "target": "marble_agg",
                                 "treatment": tname, **m})

            # Score vs LPI 2024 (Copenhagen clean + Marble agg shape-only).
            if lpi is not None and not lpi.empty:
                for gkey, g in LPI_GROUPS.items():
                    site_cols = [s for s in g["site_ids"] if s in Pdf.columns]
                    if not site_cols:
                        continue
                    delivered = (lpi[lpi["group"] == gkey]
                                 .set_index("ts_utc")["delivered_mw"].sort_index())
                    m = metrics(Pdf[site_cols].sum(axis=1), delivered, tname)
                    rows.append({"year": year, "ref": "lpi", "target": gkey,
                                 "treatment": tname, **m})
    return pd.DataFrame(rows)


def copenhagen_eia923_bound() -> str:
    """Pull Copenhagen (EIA 58979) pooled EIA-923 loss vs modeled, if present."""
    sc = OUT_DIR / "eia923_scorecard.csv"
    if not sc.exists():
        return "eia923_scorecard.csv not found"
    df = pd.read_csv(sc)
    sub = df[df["eia_plant_id"] == COPENHAGEN_EIA]
    if sub.empty:
        return "Copenhagen (58979) not in eia923_scorecard"
    cols = [c for c in ["year", "loss_fraction_pct", "gap_pct", "mod_eia_ratio",
                        "modeled_cf", "eia_cf"] if c in sub.columns]
    return sub[cols].to_string(index=False)


def main():
    raws = {2020: load_raw(2020), 2024: load_raw(2024)}
    have = [y for y, r in raws.items() if r is not None]
    print(f"Loaded alpha_raw for years: {have}")
    if not have:
        print("No alpha_raw_*.npz yet — run fetch_alpha_raw.py first.")
        return 1

    print("\n" + "=" * 80)
    print("1. ALPHA DISTRIBUTION (raw HRRR, unclipped; ws10>=1)")
    print("=" * 80)
    dist = alpha_distribution(raws)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dist.to_csv(OUT_DIR / "alpha_diagnostic.csv", index=False, float_format="%.4f")
    with pd.option_context("display.width", 200, "display.max_rows", 60,
                           "display.float_format", lambda x: f"{x:.3f}"):
        print(dist.to_string(index=False))
    print(f"\n  Onshore climatology band: {ALPHA_CLIMATOLOGY[0]}-{ALPHA_CLIMATOLOGY[1]}")
    allrows = dist[dist["subset"] == "all"]
    for _, r in allrows.iterrows():
        verdict = "ABOVE" if r["alpha_median"] > ALPHA_CLIMATOLOGY[1] else "in/below"
        print(f"  {r['year']} fleet median alpha = {r['alpha_median']:.3f} ({verdict} climatology); "
              f"{100*r['frac_gt_0.40']:.1f}% of hours hit the 0.40 clip ceiling")

    print("\n" + "=" * 80)
    print("2. ALPHA SENSITIVITY SWEEP (pilot plants)")
    print("=" * 80)
    sens = sensitivity(raws)
    sens.to_csv(OUT_DIR / "alpha_sensitivity.csv", index=False, float_format="%.4f")
    show = ["year", "ref", "target", "treatment", "n", "mean_mod", "mean_ref",
            "bias_mw", "nmae_pct", "pearson_r", "ramp_r", "cf_norm_nmae_pct"]
    show = [c for c in show if c in sens.columns]
    with pd.option_context("display.width", 220, "display.max_rows", 200,
                           "display.float_format", lambda x: f"{x:.3f}"):
        # Headline: Copenhagen, both refs
        for tgt in ["copenhagen", "marble_agg"]:
            sub = sens[sens["target"] == tgt]
            if not sub.empty:
                print(f"\n--- target={tgt} ---")
                print(sub[show].to_string(index=False))

    print("\n" + "=" * 80)
    print("3. COPENHAGEN EIA-923 LOSS BOUND (interpretive)")
    print("=" * 80)
    print(copenhagen_eia923_bound())
    print("\nWrote alpha_diagnostic.csv + alpha_sensitivity.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
