"""Score the multicell pilot outputs vs PLUSWIND truth.

Reads single/multiA/multiB CSVs written by ``run_multicell_pilot.py`` and
compares each per plant against PLUSWIND on the overlap window. Reports
nMAE, Pearson r, ramp-Pearson r, and ramp-std for the three methods so
the Task 1.1 🛑 DECISION can be made on numbers.

Per the plan (I3): PLUSWIND is potential-grade, so both level and shape
are valid metrics here — no need for the CF-normalised escape hatch.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

REPO_ROOT  = Path(__file__).resolve().parents[2]
OUT_DIR    = REPO_ROOT / "docs" / "figures" / "wind_v3"
PM_DIR     = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
PLUSWIND_RAW = REPO_ROOT / "data" / "pluswind_raw"
LPI_DIR    = REPO_ROOT / "Verification files"

# LPI groups that overlap with the pilot plant set (Copenhagen + Marble agg).
# Coordinates with LPI_GROUPS in score_per_plant_hourly.py; kept inline so
# this script is self-contained.
LPI_GROUPS = {
    "marble_agg": {
        "label":   "Marble River + Chateaugay + Clinton + Ellenburg",
        "lpi_col": ("Marble River / Chateaugay / Clinton / Ellenburg / "
                    "Jericho Rise Wind (LPI_GEN) Average"),
        "site_ids":     ["wind_323696", "wind_323614", "wind_323605", "wind_323604"],
        "nameplate_mw": 503.2,
        "level_validatable": False,
    },
    "copenhagen": {
        "label":   "Copenhagen",
        "lpi_col": "Copenhagen Wind (LPI_GEN) Average",
        "site_ids":     ["wind_323753"],
        "nameplate_mw": 79.9,
        "level_validatable": True,
    },
}


# ---------- helpers (lifted from score_per_plant_hourly.py) ------------------

def _skiprows(path: Path) -> int:
    with path.open() as fh:
        first = fh.readline().strip()
    if first.startswith("Headers="):
        return int(first.split("=", 1)[1])
    return 0


def load_pluswind_csv(path: Path) -> pd.Series:
    skip = _skiprows(path)
    df = pd.read_csv(path, skiprows=skip)
    cols_lower = {c.lower(): c for c in df.columns}
    tcol = cols_lower.get("time") or cols_lower.get("gmt") or df.columns[0]
    val = (cols_lower.get("capacity") or cols_lower.get("power")
           or cols_lower.get("mw"))
    if val is None:
        for c in df.columns:
            if c == tcol:
                continue
            if pd.api.types.is_numeric_dtype(df[c]):
                val = c; break
    ts = pd.to_datetime(df[tcol].astype(str), errors="coerce", utc=True)
    vals = pd.to_numeric(df[val], errors="coerce")
    vals = vals.where(vals > -9000, np.nan)
    s = pd.Series(vals.to_numpy(), index=ts).dropna()
    if s.index.tz is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    return s[~s.index.duplicated(keep="first")].sort_index()


def load_pluswind_for_sites(years: list[int], site_ids: list[str],
                            meta: pd.DataFrame) -> pd.DataFrame:
    """Per-site PLUSWIND truth with EIA→site pro-rata split (script 09 logic)."""
    out_cols: dict[str, list[pd.Series]] = {}
    for y in years:
        files = {}
        for p in PLUSWIND_RAW.glob(f"modelpluswind.hr.c1.{y}.*.csv"):
            try:
                files[int(p.stem.split(".")[-1])] = p
            except ValueError:
                continue
        active = meta[meta["operating_year"] <= y]
        for eia, grp in active.groupby("eia_plant_id"):
            p = files.get(int(eia))
            if p is None:
                continue
            s = load_pluswind_csv(p)
            s = s[(s.index >= f"{y}-01-01") & (s.index < f"{y+1}-01-01")]
            if s.empty:
                continue
            if len(grp) == 1:
                col = str(grp.iloc[0]["site_id"])
                if col in site_ids:
                    out_cols.setdefault(col, []).append(s)
            else:
                total = float(grp["nameplate_mw"].sum())
                for _, row in grp.iterrows():
                    col = str(row["site_id"])
                    if col in site_ids:
                        out_cols.setdefault(col, []).append(
                            s * float(row["nameplate_mw"]) / total)
    if not out_cols:
        return pd.DataFrame()
    return pd.concat(
        {c: pd.concat(parts).sort_index() for c, parts in out_cols.items()},
        axis=1).sort_index()


def load_lpi_groups(years: list[int]) -> pd.DataFrame:
    """Load NY_WindFarmGenData_*.xls in long form. Returns ts_utc, group,
    delivered_mw filtered to the requested years."""
    files = sorted(LPI_DIR.glob("NY_WindFarmGenData_*.xls"))
    lpi_col_to_key = {g["lpi_col"]: k for k, g in LPI_GROUPS.items()}
    frames = []
    for f in files:
        df = pd.read_excel(f, sheet_name="Sheet0", header=0)
        rename = {"Date/Time": "ts"}
        for col in df.columns:
            if col in lpi_col_to_key:
                rename[col] = lpi_col_to_key[col]
        df = df.rename(columns=rename)
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.drop_duplicates("ts", keep="first")
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True).sort_values("ts")
    raw["ts_eastern"] = raw["ts"].dt.tz_localize(
        "US/Eastern", ambiguous="NaT", nonexistent="NaT")
    raw = raw.dropna(subset=["ts_eastern"]).copy()
    raw["ts_utc"] = raw["ts_eastern"].dt.tz_convert("UTC").dt.tz_localize(None)
    raw = raw[raw["ts_eastern"].dt.year.isin(years)].copy()
    value_cols = [k for k in LPI_GROUPS if k in raw.columns]
    long = raw.melt(id_vars=["ts_utc"], value_vars=value_cols,
                    var_name="group", value_name="delivered_mw")
    long["delivered_mw"] = pd.to_numeric(long["delivered_mw"], errors="coerce")
    return long.dropna(subset=["delivered_mw"]).reset_index(drop=True)


def metrics(modeled: pd.Series, ref: pd.Series, name: str) -> dict:
    j = pd.concat([modeled.rename("m"), ref.rename("r")], axis=1).dropna()
    if j.empty:
        return {"name": name, "n": 0}
    m = j["m"].to_numpy(); r = j["r"].to_numpy()
    err = m - r
    mae = float(np.abs(err).mean())
    rmse = float(np.sqrt((err**2).mean()))
    bias = float(err.mean())
    rm = r.mean()
    nmae = 100 * mae / rm if rm > 0 else float("nan")
    nrmse = 100 * rmse / rm if rm > 0 else float("nan")
    pear = float(np.corrcoef(m, r)[0, 1]) if len(j) > 1 else float("nan")
    # Ramps — consecutive hours only
    idx = j.index
    dt = pd.Series(idx).diff().dt.total_seconds().to_numpy()
    valid = (dt == 3600.0)
    dm = np.diff(m); dr = np.diff(r); v = valid[1:]
    if v.any():
        dm_v, dr_v = dm[v], dr[v]
        ramp_r = float(np.corrcoef(dm_v, dr_v)[0, 1])
        ramp_std_m = float(dm_v.std())
        ramp_std_r = float(dr_v.std())
        ramp_p95_m = float(np.percentile(np.abs(dm_v), 95))
        ramp_p95_r = float(np.percentile(np.abs(dr_v), 95))
    else:
        ramp_r = ramp_std_m = ramp_std_r = ramp_p95_m = ramp_p95_r = float("nan")
    # CF-normalised error: shape-only metric for aged-metered references
    # (Marble agg, Noble agg LPI). Divide each side by its own mean before
    # taking |Δ|. Plan §I3.
    mean_m = float(m.mean())
    if mean_m > 0 and rm > 0:
        cf_nmae = 100 * float(np.abs(m / mean_m - r / rm).mean())
    else:
        cf_nmae = float("nan")
    return {
        "name": name, "n": int(len(j)),
        "mean_mod": mean_m, "mean_ref": float(rm),
        "bias_mw": bias, "nmae_pct": nmae, "nrmse_pct": nrmse,
        "pearson_r": pear,
        "ramp_r": ramp_r,
        "ramp_std_mod": ramp_std_m, "ramp_std_ref": ramp_std_r,
        "ramp_p95_mod": ramp_p95_m, "ramp_p95_ref": ramp_p95_r,
        "cf_norm_nmae_pct": cf_nmae,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True,
                    help="The pilot tag (e.g. 2020-06-01_2020-06-08)")
    args = ap.parse_args()

    meta = pd.read_csv(PM_DIR / "wind_meta.csv")

    paths = {n: OUT_DIR / f"multicell_pilot_{args.tag}_{n}.csv"
             for n in ["single", "multiA", "multiB", "v5hub", "v6lrn"]}
    paths = {n: p for n, p in paths.items() if p.exists()}
    if not paths:
        raise FileNotFoundError(
            f"No pilot CSVs found for tag {args.tag} in {OUT_DIR}")

    modeled = {}
    for n, p in paths.items():
        df = pd.read_csv(p, parse_dates=["Time"], index_col="Time")
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        modeled[n] = df

    site_ids = list(modeled["single"].columns)
    start_year = modeled["single"].index.min().year
    end_year   = modeled["single"].index.max().year
    years = list(range(start_year, end_year + 1))
    print(f"Loaded pilot tag '{args.tag}', sites: {site_ids}, years: {years}")

    pluswind_years = [y for y in years if 2018 <= y <= 2021]
    lpi_years      = [y for y in years if 2022 <= y <= 2024]

    plus = (load_pluswind_for_sites(pluswind_years, site_ids, meta)
            if pluswind_years else pd.DataFrame())
    print(f"PLUSWIND truth loaded: {plus.shape} (years {pluswind_years})")

    lpi = load_lpi_groups(lpi_years) if lpi_years else pd.DataFrame()
    print(f"LPI long loaded: {len(lpi)} rows across "
          f"{lpi['group'].nunique() if not lpi.empty else 0} groups "
          f"(years {lpi_years})\n")

    common_sites = sorted(set(site_ids) & set(plus.columns)) if not plus.empty else []
    if not common_sites and plus.empty and lpi.empty:
        print("No reference data available for this window — nothing to score.")
        return

    print("=" * 100)
    print(f"PER-PLANT METRICS vs PLUSWIND — pilot {args.tag}")
    print("=" * 100)
    header = (f"{'plant':<12} {'method':<8} {'n':>5} {'mean_mod':>8} "
              f"{'mean_ref':>8} {'bias':>7} {'nMAE%':>7} {'r':>6} {'ramp_r':>7} "
              f"{'rstd_m':>7} {'rstd_r':>7} {'CFnMAE':>7}")
    print(header); print("-" * len(header))

    def _print(prefix, mt):
        print(f"{prefix:<12} {mt['name']:<8} {mt['n']:>5} "
              f"{mt['mean_mod']:>8.2f} {mt['mean_ref']:>8.2f} "
              f"{mt['bias_mw']:>7.2f} {mt['nmae_pct']:>6.2f}% "
              f"{mt['pearson_r']:>6.3f} {mt['ramp_r']:>7.3f} "
              f"{mt['ramp_std_mod']:>7.2f} {mt['ramp_std_ref']:>7.2f} "
              f"{mt['cf_norm_nmae_pct']:>6.2f}%")

    all_rows = []
    for site in common_sites:
        ref = plus[site]
        for method, df in modeled.items():
            if site not in df.columns:
                continue
            mt = metrics(df[site], ref, method)
            mt["site_id"] = site; mt["reference"] = "pluswind"
            all_rows.append(mt)
            _print(site, mt)
        print()

    # Fleet sum across the pilot plants — vs PLUSWIND
    if common_sites:
        print("=" * 100)
        print("FLEET SUM ACROSS PILOT PLANTS vs PLUSWIND")
        print("=" * 100)
        ref_sum = plus[common_sites].sum(axis=1, min_count=1)
        print(header); print("-" * len(header))
        for method, df in modeled.items():
            mod_sum = df[common_sites].sum(axis=1, min_count=1)
            mt = metrics(mod_sum, ref_sum, method)
            mt["site_id"] = "FLEET"; mt["reference"] = "pluswind"
            all_rows.append(mt)
            _print("FLEET", mt)

    # LPI scoring — per group (sum modeled site columns → compare to delivered)
    if not lpi.empty:
        print()
        print("=" * 100)
        print("LPI GROUP METRICS — pilot " + args.tag)
        print("  (aged-metered → CFnMAE / ramp_r are the valid metrics; nMAE")
        print("   includes the definitional ~20% loss offset for Marble agg.)")
        print("=" * 100)
        print(header); print("-" * len(header))
        for gkey, g in LPI_GROUPS.items():
            modeled_in = [s for s in g["site_ids"] if s in site_ids]
            if not modeled_in:
                continue
            delivered = (lpi[lpi["group"] == gkey]
                         .set_index("ts_utc")["delivered_mw"]
                         .sort_index())
            for method, df in modeled.items():
                mod_sum = df[modeled_in].sum(axis=1, min_count=1)
                mt = metrics(mod_sum, delivered, method)
                if mt["n"] == 0:
                    continue
                mt["site_id"] = gkey; mt["reference"] = "lpi"
                mt["level_validatable"] = g["level_validatable"]
                all_rows.append(mt)
                _print(gkey, mt)
            print()

    out_csv = OUT_DIR / f"multicell_pilot_{args.tag}_scorecard.csv"
    pd.DataFrame(all_rows).to_csv(out_csv, index=False, float_format="%.4f")
    print(f"\nWrote {out_csv.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
