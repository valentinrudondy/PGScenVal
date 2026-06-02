"""Per-plant hourly scorecard — Phase 0 measurement backbone.

Freezes a single CSV at ``docs/figures/wind_v3/per_plant_hourly_scorecard.csv``
that every later improvement task reports against. The script intentionally
keeps three classes of comparison separate because they tell different things
about a *potential* target series:

1. vs PLUSWIND per plant, 2018–2021 (potential-grade reference, level + shape
   both meaningful, ``level_validatable=True``).

2. vs Copenhagen LPI hourly, 2024 (clean single-plant metered anchor, raw
   bias is small, ``level_validatable=True``).

3. vs Maple Ridge / Marble agg / Noble agg LPI hourly, 2024 (aged metered
   groups). The ~20% level offset is definitional (availability + wake),
   so only *shape* metrics are valid → CF-normalized error + ramp
   correlation + Pearson. ``level_validatable=False``.

Output CSV columns
------------------
scope, target, site_or_group, label, year, n_hours,
nameplate_mw, mean_modeled_mw, mean_ref_mw, mean_bias_mw,
cf_modeled_pct, cf_ref_pct, nmae_pct_mean, nrmse_pct_mean,
nmae_pct_cap, nrmse_pct_cap, pearson_r,
ramp_pearson_r, ramp_std_modeled, ramp_std_ref,
ramp_p95_modeled, ramp_p95_ref,
cf_norm_nmae_pct, cf_norm_nrmse_pct,
level_validatable, notes

Where ``nmae_pct_mean`` normalises by reference mean (the standard for
potential-grade comparisons) and ``cf_norm_nmae_pct`` divides each series
by its own mean before taking |Δ| — that's the shape-only metric to use
on aged metered groups where the level gap is definitional.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
WIND_DIR  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
META_CSV  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata" / "wind_meta.csv"
PLUSWIND_RAW = REPO_ROOT / "data" / "pluswind_raw"
LPI_DIR   = REPO_ROOT / "Verification files"
OUT_CSV   = REPO_ROOT / "docs" / "figures" / "wind_v3" / "per_plant_hourly_scorecard.csv"

PLUSWIND_YEARS = [2018, 2019, 2020, 2021]
# LPI overlap with v3 hourly: 2022-09-09 → 2024-12-31 (v3 has no 2025+).
LPI_YEARS = [2022, 2023, 2024]

# Prefer the `NY_WindFarmGenData_*` files (full 2022-09 → 2026-06 set, 4 LPI
# groups). The older `MapleRidgeWindFarm_*` files are byte-identical for their
# overlap window — same NYISO source — so we deliberately exclude them to
# avoid double-counting.
LPI_FILES = sorted(LPI_DIR.glob("NY_WindFarmGenData_*.xls"))

# LPI groups — keep in sync with score_vs_lpi.py (composition reconciled
# May 2026 against EIA-923 annual totals; 3/4 LPI titles mislabel contents).
LPI_GROUPS: dict[str, dict] = {
    "maple_ridge": {
        "label":        "Maple Ridge 1 (MR2 not in LPI)",
        "lpi_col":      "Maple Ridge Wind Farm (LPI_GEN) Average",
        "site_ids":     ["wind_323574"],
        "nameplate_mw": 231.0,
        "level_validatable": False,
        "notes":        "aged metered; shape-only",
    },
    "marble_agg": {
        "label":        "Marble River + Chateaugay + Clinton + Ellenburg (Jericho excl.)",
        "lpi_col":      ("Marble River / Chateaugay / Clinton / Ellenburg / "
                         "Jericho Rise Wind (LPI_GEN) Average"),
        "site_ids":     ["wind_323696", "wind_323614", "wind_323605", "wind_323604"],
        "nameplate_mw": 503.2,
        "level_validatable": False,
        "notes":        "aged metered agg (4 plants); shape-only",
    },
    "copenhagen": {
        "label":        "Copenhagen (clean anchor)",
        "lpi_col":      "Copenhagen Wind (LPI_GEN) Average",
        "site_ids":     ["wind_323753"],
        "nameplate_mw": 79.9,
        "level_validatable": True,
        "notes":        "clean single-plant anchor; raw bias small",
    },
    "noble_agg": {
        "label":        "Noble Wethersfield + High Sheldon + Stony Creek + Bliss",
        "lpi_col":      ("Noble Wethersfield  / High Sheldon / Stony Creek "
                         "Wind (LPI_GEN) Average"),
        "site_ids":     ["wind_323626", "wind_323625", "wind_323706", "wind_323608"],
        "nameplate_mw": 438.5,
        "level_validatable": False,
        "notes":        "aged metered agg (4 plants, includes Bliss); shape-only",
    },
}


# ---------- helpers ----------------------------------------------------------

def _skiprows_from_header(path: Path) -> int:
    with path.open() as fh:
        first = fh.readline().strip()
    if first.startswith("Headers="):
        return int(first.split("=", 1)[1])
    return 0


def load_pluswind_csv(path: Path) -> pd.Series:
    """Load one PLUSWIND per-plant CSV → hourly MW Series indexed by tz-naive UTC.

    Mirrors PGscen-2nd/scripts/09_build_pluswind_wide.py.
    """
    skip = _skiprows_from_header(path)
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
                val = c
                break
    ts = pd.to_datetime(df[tcol].astype(str), errors="coerce", utc=True)
    vals = pd.to_numeric(df[val], errors="coerce")
    vals = vals.where(vals > -9000, np.nan)
    s = pd.Series(vals.to_numpy(), index=ts).dropna()
    if s.index.tz is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    s = s[~s.index.duplicated(keep="first")].sort_index()
    return s


def discover_pluswind_files(year: int) -> dict[int, Path]:
    out: dict[int, Path] = {}
    for p in PLUSWIND_RAW.glob(f"modelpluswind.hr.c1.{year}.*.csv"):
        try:
            out[int(p.stem.split(".")[-1])] = p
        except ValueError:
            continue
    sub = PLUSWIND_RAW / str(year)
    if sub.is_dir():
        for p in sub.glob("*.csv"):
            try:
                out.setdefault(int(p.stem), p)
            except ValueError:
                continue
    return out


def load_v3_wide(years: list[int]) -> pd.DataFrame:
    frames = []
    for y in years:
        f = WIND_DIR / f"wind_actual_1h_site_{y}_utc.pluswind_v3.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        frames.append(df)
    return pd.concat(frames).sort_index() if frames else pd.DataFrame()


def load_pluswind_wide(years: list[int], meta: pd.DataFrame) -> pd.DataFrame:
    """Reshape raw PLUSWIND per-plant CSVs into a wide site_id table, applying
    the same EIA→site pro-rata split as build_pluswind_wide_year (script 09)."""
    out_cols: dict[str, list[pd.Series]] = {}
    for y in years:
        files = discover_pluswind_files(y)
        if not files:
            print(f"  WARNING: no PLUSWIND raw files for {y}")
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
                out_cols.setdefault(col, []).append(s)
            else:
                total = float(grp["nameplate_mw"].sum())
                for _, row in grp.iterrows():
                    col = str(row["site_id"])
                    share = float(row["nameplate_mw"]) / total
                    out_cols.setdefault(col, []).append(s * share)
    if not out_cols:
        return pd.DataFrame()
    wide = pd.concat({c: pd.concat(parts).sort_index()
                      for c, parts in out_cols.items()}, axis=1)
    return wide.sort_index()


def load_lpi_long() -> pd.DataFrame:
    """Returns: ts_utc, group, delivered_mw — 2024 only."""
    lpi_col_to_key = {g["lpi_col"]: k for k, g in LPI_GROUPS.items()}
    frames = []
    for f in LPI_FILES:
        if not f.exists():
            raise FileNotFoundError(f)
        df = pd.read_excel(f, sheet_name="Sheet0", header=0)
        rename = {"Date/Time": "ts"}
        for col in df.columns:
            if col in lpi_col_to_key:
                rename[col] = lpi_col_to_key[col]
        df = df.rename(columns=rename)
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.drop_duplicates("ts", keep="first")
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True).sort_values("ts")
    raw["ts_eastern"] = raw["ts"].dt.tz_localize(
        "US/Eastern", ambiguous="NaT", nonexistent="NaT")
    raw = raw.dropna(subset=["ts_eastern"]).copy()
    raw["ts_utc"] = raw["ts_eastern"].dt.tz_convert("UTC").dt.tz_localize(None)
    raw = raw[raw["ts_eastern"].dt.year.isin(LPI_YEARS)].copy()
    value_cols = [k for k in LPI_GROUPS if k in raw.columns]
    long = raw.melt(id_vars=["ts_utc"], value_vars=value_cols,
                    var_name="group", value_name="delivered_mw")
    long["delivered_mw"] = pd.to_numeric(long["delivered_mw"], errors="coerce")
    return long.dropna(subset=["delivered_mw"]).reset_index(drop=True)


# ---------- metric core -------------------------------------------------------

def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2:
        return float("nan")
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def hourly_metrics(modeled: pd.Series,
                   ref: pd.Series,
                   nameplate_mw: float) -> dict:
    """Compute the full metric pack on aligned hourly series.

    ``modeled`` and ``ref`` must share the same DatetimeIndex (we align here
    and drop NaN). All metrics are mean-of-pairs; ramp metrics use Δh on
    the joined index (so any drop creates a ramp gap which we discard).
    """
    j = pd.concat([modeled.rename("m"), ref.rename("r")], axis=1).dropna()
    if j.empty:
        return {"n_hours": 0}
    m = j["m"].to_numpy()
    r = j["r"].to_numpy()
    n = len(j)

    bias = float((m - r).mean())
    mae  = float(np.abs(m - r).mean())
    rmse = float(np.sqrt(((m - r) ** 2).mean()))
    mean_m = float(m.mean())
    mean_r = float(r.mean())

    # mean-normalised (potential-grade) — what nMAE means in the plan
    nmae_mean  = 100 * mae  / mean_r if mean_r > 0 else float("nan")
    nrmse_mean = 100 * rmse / mean_r if mean_r > 0 else float("nan")
    # capacity-normalised (alternative; ~matches the LPI scorecard)
    nmae_cap   = 100 * mae  / nameplate_mw if nameplate_mw > 0 else float("nan")
    nrmse_cap  = 100 * rmse / nameplate_mw if nameplate_mw > 0 else float("nan")
    pear = _pearson(m, r)

    # Ramp distribution — Δh on the joined index, skip gaps
    idx = j.index
    dt = pd.Series(idx).diff().dt.total_seconds().to_numpy()
    valid = (dt == 3600.0)  # consecutive hours only
    dm = np.diff(m); dr = np.diff(r); valid_r = valid[1:]
    if valid_r.any():
        dm_v = dm[valid_r]
        dr_v = dr[valid_r]
        ramp_r = _pearson(dm_v, dr_v)
        ramp_std_m = float(dm_v.std())
        ramp_std_r = float(dr_v.std())
        ramp_p95_m = float(np.percentile(np.abs(dm_v), 95))
        ramp_p95_r = float(np.percentile(np.abs(dr_v), 95))
    else:
        ramp_r = ramp_std_m = ramp_std_r = ramp_p95_m = ramp_p95_r = float("nan")

    # CF-normalised error: divide each side by its own mean before |Δ|.
    # Removes definitional level offset on aged metered groups; what survives
    # is timing/shape error. nMAE on the normalised series.
    if mean_m > 0 and mean_r > 0:
        mn = m / mean_m
        rn = r / mean_r
        cf_nmae  = 100 * float(np.abs(mn - rn).mean())   # both have mean 1
        cf_nrmse = 100 * float(np.sqrt(((mn - rn) ** 2).mean()))
    else:
        cf_nmae = cf_nrmse = float("nan")

    return {
        "n_hours":           n,
        "nameplate_mw":      nameplate_mw,
        "mean_modeled_mw":   mean_m,
        "mean_ref_mw":       mean_r,
        "mean_bias_mw":      bias,
        "cf_modeled_pct":    100 * mean_m / nameplate_mw if nameplate_mw > 0 else float("nan"),
        "cf_ref_pct":        100 * mean_r / nameplate_mw if nameplate_mw > 0 else float("nan"),
        "nmae_pct_mean":     nmae_mean,
        "nrmse_pct_mean":    nrmse_mean,
        "nmae_pct_cap":      nmae_cap,
        "nrmse_pct_cap":     nrmse_cap,
        "pearson_r":         pear,
        "ramp_pearson_r":    ramp_r,
        "ramp_std_modeled":  ramp_std_m,
        "ramp_std_ref":      ramp_std_r,
        "ramp_p95_modeled":  ramp_p95_m,
        "ramp_p95_ref":      ramp_p95_r,
        "cf_norm_nmae_pct":  cf_nmae,
        "cf_norm_nrmse_pct": cf_nrmse,
    }


# ---------- scoring loops -----------------------------------------------------

def score_vs_pluswind(v3: pd.DataFrame,
                      plus: pd.DataFrame,
                      meta: pd.DataFrame) -> list[dict]:
    rows = []
    common = sorted(set(v3.columns) & set(plus.columns))
    pooled = pd.concat(
        [v3.loc["2018":"2021", common].rename(columns=lambda c: c + "__m"),
         plus.loc["2018":"2021", common].rename(columns=lambda c: c + "__r")],
        axis=1)
    name_lookup = meta.set_index("site_id")["site_name"].to_dict()
    np_lookup   = meta.set_index("site_id")["nameplate_mw"].to_dict()

    for site in common:
        nameplate = float(np_lookup.get(site, np.nan))
        m = pooled[f"{site}__m"]; r = pooled[f"{site}__r"]
        mt = hourly_metrics(m, r, nameplate)
        if mt["n_hours"] == 0:
            continue
        rows.append({
            "scope":              "per_plant",
            "target":             "pluswind",
            "site_or_group":      site,
            "label":              name_lookup.get(site, site),
            "year":               "pooled_2018_2021",
            "level_validatable":  True,
            "notes":              "potential-grade reference",
            **mt,
        })

    # Fleet-sum row (across the 22-plant intersection) — handy headline metric
    m_sum = v3.loc["2018":"2021", common].sum(axis=1, min_count=1)
    r_sum = plus.loc["2018":"2021", common].sum(axis=1, min_count=1)
    fleet_np = float(meta[meta["site_id"].isin(common)]["nameplate_mw"].sum())
    mt = hourly_metrics(m_sum, r_sum, fleet_np)
    if mt["n_hours"] > 0:
        rows.append({
            "scope":              "fleet_intersection",
            "target":             "pluswind",
            "site_or_group":      "INTERSECTION_22",
            "label":              f"fleet sum on {len(common)}-plant PLUSWIND overlap",
            "year":               "pooled_2018_2021",
            "level_validatable":  True,
            "notes":              "headline fleet-level potential metric",
            **mt,
        })
    return rows


def score_vs_lpi(v3: pd.DataFrame, lpi_long: pd.DataFrame) -> list[dict]:
    """For each LPI group, sum modeled site columns → align to delivered →
    score per year and pooled across the v3 overlap (2022-09 → 2024-12).
    """
    rows = []
    for gkey, g in LPI_GROUPS.items():
        site_cols = [s for s in g["site_ids"] if s in v3.columns]
        if not site_cols:
            print(f"  WARNING group {gkey}: no modeled cols found")
            continue
        modeled_all = v3[site_cols].sum(axis=1, min_count=1)
        delivered_all = (lpi_long[lpi_long["group"] == gkey]
                         .set_index("ts_utc")["delivered_mw"]
                         .sort_index())
        # Per-year breakdown (use boolean mask, not .loc[str(year)], because
        # a group may have zero rows in a given year — KeyError otherwise).
        for year in LPI_YEARS:
            modeled = modeled_all[modeled_all.index.year == year]
            delivered = delivered_all[delivered_all.index.year == year]
            mt = hourly_metrics(modeled, delivered, float(g["nameplate_mw"]))
            if mt["n_hours"] == 0:
                continue
            rows.append({
                "scope":              "lpi_group",
                "target":             f"lpi_{year}",
                "site_or_group":      gkey,
                "label":              g["label"],
                "year":               str(year),
                "level_validatable":  g["level_validatable"],
                "notes":              g["notes"],
                **mt,
            })
        # Pooled across the full v3 overlap window
        in_pool = lambda idx: idx.year.isin(LPI_YEARS)
        first, last = str(LPI_YEARS[0]), str(LPI_YEARS[-1])
        mt = hourly_metrics(modeled_all[in_pool(modeled_all.index)],
                            delivered_all[in_pool(delivered_all.index)],
                            float(g["nameplate_mw"]))
        if mt["n_hours"] > 0:
            rows.append({
                "scope":              "lpi_group",
                "target":             "lpi_pooled",
                "site_or_group":      gkey,
                "label":              g["label"],
                "year":               f"pooled_{first}_{last}",
                "level_validatable":  g["level_validatable"],
                "notes":              g["notes"],
                **mt,
            })
    return rows


# ---------- main --------------------------------------------------------------

def main() -> int:
    meta = pd.read_csv(META_CSV)

    print("=" * 78)
    print("Phase 0 per-plant hourly scorecard — frozen v3 baseline")
    print("=" * 78)
    print(f"Repo root: {REPO_ROOT}")
    print()

    print("Loading v3 actuals 2018–2024…")
    v3 = load_v3_wide(list(range(2018, 2025)))
    print(f"  {v3.shape[0]} hours × {v3.shape[1]} site cols\n")

    print("Loading PLUSWIND truth 2018–2021…")
    plus = load_pluswind_wide(PLUSWIND_YEARS, meta)
    print(f"  {plus.shape[0]} hours × {plus.shape[1]} site cols\n")

    print("Loading LPI 2024 hourly…")
    lpi = load_lpi_long()
    print(f"  {len(lpi)} rows across {lpi['group'].nunique()} groups\n")

    rows = []
    rows += score_vs_pluswind(v3, plus, meta)
    rows += score_vs_lpi(v3, lpi)

    df = pd.DataFrame(rows)
    # Column order
    cols = [
        "scope", "target", "site_or_group", "label", "year",
        "n_hours", "nameplate_mw",
        "mean_modeled_mw", "mean_ref_mw", "mean_bias_mw",
        "cf_modeled_pct", "cf_ref_pct",
        "nmae_pct_mean", "nrmse_pct_mean",
        "nmae_pct_cap", "nrmse_pct_cap",
        "pearson_r",
        "ramp_pearson_r", "ramp_std_modeled", "ramp_std_ref",
        "ramp_p95_modeled", "ramp_p95_ref",
        "cf_norm_nmae_pct", "cf_norm_nrmse_pct",
        "level_validatable", "notes",
    ]
    df = df[cols]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, float_format="%.4f")

    # Headline summary table to stdout — fleet PLUSWIND + LPI per-year+pooled
    print("=" * 78)
    print("Headline rows")
    print("=" * 78)
    headline = df[df["scope"].isin(["fleet_intersection", "lpi_group"])].copy()
    headline["_year_sort"] = headline["year"].map(
        lambda v: f"z_{v}" if "pooled" in str(v) else f"a_{v}")
    headline = headline.sort_values(["scope", "site_or_group", "_year_sort"])
    headline = headline.drop(columns="_year_sort")
    show_cols = ["scope", "site_or_group", "year", "n_hours",
                 "nmae_pct_mean", "pearson_r", "ramp_pearson_r",
                 "cf_norm_nmae_pct", "level_validatable"]
    with pd.option_context("display.width", 200,
                           "display.max_colwidth", 60,
                           "display.float_format", lambda x: f"{x:.2f}"):
        print(headline[show_cols].to_string(index=False))
    print()

    print("Per-plant vs PLUSWIND pooled 2018–2021 (top 10 by nMAE):")
    pp = df[(df["scope"] == "per_plant") & (df["target"] == "pluswind")]
    pp = pp.sort_values("nmae_pct_mean", ascending=False)
    show_cols2 = ["site_or_group", "label", "n_hours",
                  "nmae_pct_mean", "pearson_r", "ramp_pearson_r",
                  "cf_norm_nmae_pct"]
    with pd.option_context("display.width", 200,
                           "display.max_colwidth", 50,
                           "display.float_format", lambda x: f"{x:.2f}"):
        print(pp[show_cols2].head(10).to_string(index=False))
    print()

    print(f"Wrote {OUT_CSV.relative_to(REPO_ROOT)}  ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
