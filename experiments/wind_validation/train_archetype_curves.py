"""Task 2.1 — train per-archetype power curves from PLUSWIND-overlap data.

Following Option A (decided 2026-06-02): 2 archetypes split by specific
power (cap_kw / swept_area_m^2) with threshold 285 W/m^2:

  A1 (legacy / high spec_pw):  GE1.5-77, V82-1.65, V112-3.075, MM92,
                                G90-2.0, N117/3675, V66-1.65, GE1.5-70.5
  A2 (modern large-rotor):    GE2.5-116, V110-2.0, GE1.62-100, GE1.62-103,
                                G114-2.1, V150-4.x, GE5.5-158, SG-4.44

Training inputs (per plant in PLUSWIND-overlap 2018-2021, hour by hour):
  - HRRR WS80 at plant centroid (single-cell, from npz cache)
  - Density correction from HRRR surface pres + 2 m temp at same cell
  - PLUSWIND truth power -> capacity factor (power / nameplate)

Pool by archetype, bin density-corrected WS in 0.25 m/s steps over
[0, 25] m/s, take **median** CF per bin (robust to outage hours).
Fit isotonic regression (monotone non-decreasing) per archetype.

Held-out validation strategy
----------------------------
- Train years: 2018, 2019, 2020.
- In-era held-out: PLUSWIND 2021.
- Hard held-out: 2024 LPI Copenhagen (different anchor, different year).

Outputs
-------
- docs/figures/wind_v3/archetype_curves.csv     (curve_ws, A1_cf, A2_cf)
- docs/figures/wind_v3/archetype_assignment.csv (per-plant archetype + SP)
- docs/figures/wind_v3/archetype_curves_fit.csv (per-archetype-bin median CF,
  count, P25, P75 — diagnostic for fit quality)
- docs/figures/wind_v3/archetype_curves.png     (plot vs SAM, vs training data)
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "PGscen-2nd"))
from pgscen.utils.wind_physics import (  # noqa: E402
    R_D, RHO_REF, density_correct_wind_speed, build_sam_curves,
)

PM_DIR        = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata"
WIND_DIR      = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
PLUSWIND_RAW  = REPO_ROOT / "data" / "pluswind_raw"
NPZ_DIR       = REPO_ROOT / "PGscen-2nd" / "data" / "cache" / "hrrr" / "npz_v2"
OUT_DIR       = REPO_ROOT / "docs" / "figures" / "wind_v3"

TRAIN_YEARS = [2018, 2019, 2020]   # 2021 reserved as in-era held-out
SP_SPLIT_W_PER_M2 = 285.0          # bimodal-gap threshold from probe (Option A)
WS_BINS = np.arange(0.0, 25.0 + 0.25, 0.25)
WS_BIN_CENTERS = (WS_BINS[:-1] + WS_BINS[1:]) / 2.0
MIN_HOURS_PER_BIN = 30             # below this, mark bin "thin" but keep it

# ---------- PLUSWIND truth loader (mirror script 09) ----------

def _skiprows(p: Path) -> int:
    with p.open() as fh:
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


# ---------- npz cache loader ----------

def _ts_from_npz_filename(name: str):
    """hrrr.20200615_conus_hrrr.t12z.wrfsfcf00.grib2.wind.npz
    → pd.Timestamp(2020-06-15 12:00:00, tz=None)."""
    # split on '_' or '.' to get the date+hour parts
    head = name.split("_")[0]              # hrrr.20200615
    date_str = head.split(".")[1]
    after = name.split("_")[2]             # hrrr.t12z.wrfsfcf00.grib2.wind.npz
    hour = int(after.split(".")[1][1:3])
    return pd.Timestamp(f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} "
                        f"{hour:02d}:00:00")


def load_cache_actuals(years: list[int]) -> pd.DataFrame:
    """Load wind + density npz files for the F00 actuals of the given years.
    Returns a long DataFrame (n_hours × 31_plants × 3_fields).

    Stored as wide table: index = UTC timestamp, columns are MultiIndex
    (plant_idx, field) where field in {ws80, pres, t2m}.

    Only HRRR analysis files (wrfsfcf00) are loaded — forecast leadtime
    files are skipped.
    """
    print(f"  scanning {NPZ_DIR} for wrfsfcf00 actuals in {years}…", flush=True)
    rows = []
    for p in NPZ_DIR.iterdir():
        n = p.name
        if "wrfsfcf00" not in n:
            continue
        if not (n.endswith(".wind.npz") or n.endswith(".density.npz")):
            continue
        head = n.split("_")[0]
        try:
            y = int(head.split(".")[1][:4])
        except (IndexError, ValueError):
            continue
        if y not in years:
            continue
        rows.append((n, p))
    print(f"  found {len(rows)} candidate npz files (wind+density mixed)")

    # Group by stem: file pair → (wind_path, density_path)
    pairs: dict[str, dict[str, Path]] = {}
    for n, p in rows:
        if n.endswith(".wind.npz"):
            stem = n[: -len(".wind.npz")]
            pairs.setdefault(stem, {})["wind"] = p
        else:
            stem = n[: -len(".density.npz")]
            pairs.setdefault(stem, {})["density"] = p

    # Build per-hour rows
    times = []
    ws_rows = []
    pres_rows = []
    t2m_rows = []
    skipped = 0
    for stem, dd in sorted(pairs.items()):
        if "wind" not in dd or "density" not in dd:
            skipped += 1
            continue
        wd = np.load(dd["wind"])
        dn = np.load(dd["density"])
        ts = _ts_from_npz_filename(stem + ".wind.npz")
        times.append(ts)
        ws_rows.append(wd["ws"])
        pres_rows.append(dn["pres"])
        t2m_rows.append(dn["t2m"])
    print(f"  loaded {len(times)} paired hours; skipped {skipped} unpaired")
    idx = pd.DatetimeIndex(times, name="Time")
    n_plants = ws_rows[0].shape[0]
    ws = pd.DataFrame(ws_rows, index=idx,
                      columns=[f"plant_{i}" for i in range(n_plants)])
    pres = pd.DataFrame(pres_rows, index=idx, columns=ws.columns)
    t2m  = pd.DataFrame(t2m_rows, index=idx, columns=ws.columns)
    return ws.sort_index(), pres.sort_index(), t2m.sort_index()


# ---------- archetype assignment ----------

def compute_specific_power(meta: pd.DataFrame,
                           turbines: pd.DataFrame) -> pd.DataFrame:
    """Per-plant specific power (W/m^2): mean cap_kw / mean swept area."""
    t = turbines.dropna(subset=["eia_id", "t_cap", "t_rsa"])
    by_eia = t.groupby("eia_id").agg(cap_kw=("t_cap", "mean"),
                                      rsa_m2=("t_rsa", "mean"),
                                      top_model=("t_model",
                                                 lambda s: s.mode().iloc[0]))
    df = meta.merge(by_eia, left_on="eia_plant_id", right_index=True, how="left")
    df["spec_pw"] = 1000 * df["cap_kw"] / df["rsa_m2"]
    return df


def assign_archetype(spec_pw: float | np.ndarray) -> str | np.ndarray:
    if isinstance(spec_pw, np.ndarray):
        return np.where(np.isnan(spec_pw), "unknown",
                        np.where(spec_pw >= SP_SPLIT_W_PER_M2, "A1", "A2"))
    if pd.isna(spec_pw):
        return "unknown"
    return "A1" if spec_pw >= SP_SPLIT_W_PER_M2 else "A2"


# ---------- main ----------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("Task 2.1 — train archetype power curves")
    print("=" * 78)

    print("[1/5] Loading metadata + USWTDB + archetype assignment")
    meta = pd.read_csv(PM_DIR / "wind_meta.csv")
    turbines = pd.read_csv(PM_DIR / "uswtdb_ny_turbines.csv")
    meta_sp = compute_specific_power(meta, turbines)
    meta_sp["archetype"] = meta_sp["spec_pw"].map(assign_archetype)

    arch_df = meta_sp[["site_id", "site_name", "nameplate_mw", "operating_year",
                       "eia_plant_id", "cap_kw", "rsa_m2", "spec_pw",
                       "top_model", "archetype"]].copy()
    arch_df.to_csv(OUT_DIR / "archetype_assignment.csv",
                   index=False, float_format="%.4f")
    print(f"  Wrote {OUT_DIR/'archetype_assignment.csv'}")
    arch_counts = arch_df["archetype"].value_counts()
    print(f"  Archetype counts: {arch_counts.to_dict()}")

    print(f"\n[2/5] Loading npz cache actuals for training years {TRAIN_YEARS}")
    ws_wide, pres_wide, t2m_wide = load_cache_actuals(TRAIN_YEARS)
    print(f"  WS frame: {ws_wide.shape}  ({ws_wide.index.min()} -> {ws_wide.index.max()})")

    # plant column names follow wind_meta row order (0..30); confirm
    assert ws_wide.shape[1] == len(meta), \
        f"npz width {ws_wide.shape[1]} != n_plants {len(meta)}"

    print(f"\n[3/5] Loading PLUSWIND truth for training years")
    # PLUSWIND overlap = 22 plants; identify via wind_meta order
    all_site_ids = meta["site_id"].tolist()
    plus = load_pluswind_for_sites(TRAIN_YEARS, all_site_ids, meta)
    print(f"  PLUSWIND truth frame: {plus.shape}; sites: {list(plus.columns)}")

    # Assemble per-archetype training pool
    print(f"\n[4/5] Pooling per-plant-hour (WS_corrected, CF) tuples by archetype")
    pool = {"A1": [], "A2": []}
    plant_stats = []
    for i, sid in enumerate(all_site_ids):
        if sid not in plus.columns:
            continue
        arch = arch_df.iloc[i]["archetype"]
        if arch not in ("A1", "A2"):
            continue
        nameplate = float(arch_df.iloc[i]["nameplate_mw"])
        ws_i   = ws_wide[f"plant_{i}"]
        pres_i = pres_wide[f"plant_{i}"]
        t2m_i  = t2m_wide[f"plant_{i}"]
        ws_corr = density_correct_wind_speed(
            ws_i.to_numpy(), pres_i.to_numpy(), t2m_i.to_numpy())
        ws_corr_s = pd.Series(ws_corr, index=ws_i.index, name="ws_corr")
        truth = plus[sid] / nameplate
        truth = truth.rename("cf")
        j = pd.concat([ws_corr_s, truth], axis=1).dropna()
        pool[arch].append(j.assign(site_id=sid, archetype=arch))
        plant_stats.append({
            "site_id": sid, "archetype": arch, "n_hours": int(len(j)),
            "mean_ws_corr": float(j["ws_corr"].mean()),
            "mean_cf": float(j["cf"].mean()),
            "p_in_pool_pct": 100 * len(j) / max(1, len(ws_i)),
        })

    stats_df = pd.DataFrame(plant_stats)
    print("  Per-plant training contribution:")
    print(stats_df.sort_values(["archetype", "site_id"]).to_string(index=False))

    print(f"\n[5/5] Fitting isotonic curves per archetype")
    arch_curves: dict[str, np.ndarray] = {}
    fit_diag_rows = []
    for a, parts in pool.items():
        if not parts:
            print(f"  {a}: no plant-hour data, skipping")
            continue
        d = pd.concat(parts, ignore_index=True)
        # Bin and compute robust median (and percentiles) per bin
        d["bin"] = np.digitize(d["ws_corr"], WS_BINS) - 1
        d["bin"] = d["bin"].clip(0, len(WS_BIN_CENTERS) - 1)
        agg = d.groupby("bin")["cf"].agg(["count", "median", "mean",
                                          lambda s: s.quantile(0.25),
                                          lambda s: s.quantile(0.75)])
        agg.columns = ["count", "median", "mean", "p25", "p75"]
        agg = agg.reindex(range(len(WS_BIN_CENTERS)), fill_value=np.nan)
        agg["ws_bin"] = WS_BIN_CENTERS
        agg["archetype"] = a

        # Fit isotonic on bins with enough data
        ok = agg["count"] >= MIN_HOURS_PER_BIN
        if not ok.any():
            print(f"  {a}: no bins meet min count {MIN_HOURS_PER_BIN}")
            continue
        x = WS_BIN_CENTERS[ok]
        y = agg.loc[ok, "median"].to_numpy()
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True,
                                 out_of_bounds="clip")
        iso.fit(x, y)
        # Evaluate at all bin centers
        cf_fit = iso.predict(WS_BIN_CENTERS)
        # Force 0 below cut-in (3 m/s) and at cut-out (≥25)
        cf_fit[WS_BIN_CENTERS < 3.0] = 0.0
        arch_curves[a] = cf_fit

        agg["isotonic"] = cf_fit
        agg["used_in_fit"] = ok
        fit_diag_rows.append(agg.reset_index(drop=True))
        n_train_hours = int(agg["count"].sum())
        print(f"  {a}: trained on {n_train_hours} plant-hours across "
              f"{ok.sum()} bins (>{MIN_HOURS_PER_BIN} hrs each); "
              f"max CF in fit = {cf_fit.max():.3f}")

    fit_diag = pd.concat(fit_diag_rows, ignore_index=True)
    fit_diag.to_csv(OUT_DIR / "archetype_curves_fit.csv",
                    index=False, float_format="%.4f")
    print(f"\nWrote {OUT_DIR/'archetype_curves_fit.csv'} (per-bin diagnostic)")

    # Curves CSV — WS grid + CF per archetype
    cdf = pd.DataFrame({"ws": WS_BIN_CENTERS})
    for a in ["A1", "A2"]:
        if a in arch_curves:
            cdf[a] = arch_curves[a]
    cdf.to_csv(OUT_DIR / "archetype_curves.csv", index=False, float_format="%.4f")
    print(f"Wrote {OUT_DIR/'archetype_curves.csv'} (curve grid)")

    # ---------- Plot ----------
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)
    sam_curve_ws, sam_curve_cf, _ = build_sam_curves(meta, turbines)
    for ax, a in zip(axes, ["A1", "A2"]):
        # Per-plant binned scatter (in archetype)
        if pool.get(a):
            d = pd.concat(pool[a], ignore_index=True)
            ax.scatter(d["ws_corr"], d["cf"], s=2, alpha=0.02,
                       color="grey", label=f"{a} training pts")
        # Per-bin median + IQR
        diag = fit_diag[fit_diag["archetype"] == a]
        ax.errorbar(diag["ws_bin"], diag["median"],
                    yerr=[diag["median"] - diag["p25"],
                          diag["p75"] - diag["median"]],
                    fmt="o", markersize=3, color="C0", ecolor="C0", alpha=0.6,
                    label=f"{a} bin median + IQR")
        # Isotonic curve
        if a in arch_curves:
            ax.plot(WS_BIN_CENTERS, arch_curves[a], color="C3", linewidth=2,
                    label=f"{a} isotonic fit")
        # Reference SAM curves for plants in this archetype
        in_a = arch_df["archetype"] == a
        for j in np.where(in_a.to_numpy())[0]:
            if j < sam_curve_cf.shape[0]:
                ax.plot(sam_curve_ws, sam_curve_cf[j],
                        color="C2", alpha=0.15, linewidth=0.8)
        ax.plot([], [], color="C2", linewidth=0.8, label="SAM curves (per plant)")
        ax.set_xlabel("Density-corrected WS80 (m/s)")
        ax.set_ylabel("Capacity factor")
        ax.set_xlim(0, 25)
        ax.set_ylim(0, 1.0)
        ax.grid(alpha=0.3)
        ax.set_title(f"Archetype {a}  (training years {TRAIN_YEARS})")
        ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "archetype_curves.png", dpi=130)
    print(f"Wrote {OUT_DIR/'archetype_curves.png'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
