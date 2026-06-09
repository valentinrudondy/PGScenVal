"""Score pluswind_v3 hourly modeled potential against NYISO LPI_GEN hourly
delivered generation, for the four plant-groups exported in
``Verification files/MapleRidgeWindFarm_Hourly_*.xls``.

LPI ("Limited-Penetration Information") is a NYISO operator-portal product.
The xls bundle gives **hourly** delivered MW for four pre-aggregated plant
groups:

    Maple Ridge                        — 1 plant   (323574 + 323611, EIA 56290)
    Marble River / Chateaugay /        — 5 plants
        Clinton / Ellenburg /
        Jericho Rise
    Copenhagen                         — 1 plant
    Noble Wethersfield / High Sheldon  — 3 plants
        / Stony Creek (Orangeville)

This is the first hourly delivered series we have for specific NY wind sites
(EIA-923 was monthly per plant; rtfuelmix/EIA-930 are hourly but system-total).
Maple Ridge and Copenhagen are clean single-plant tests; the other two are
sums forced by the source (NYISO publishes them pre-aggregated, no per-plant
column).

Constraints
-----------
* xls coverage:        2024-01-01 → 2026-01-01 (Eastern hour-ending)
* pluswind_v3 coverage: through 2024 only (no 2025 modeled file yet)
* Overlap window:      2024 only — 8760 hours per group

Timezone
--------
The xls is in US/Eastern wall-clock (hour-ending). The export contains
DST quirks (~4 hours/yr): spring-forward duplicates 03:00, fall-back skips
01:00. We localize with ``ambiguous='NaT', nonexistent='NaT'`` and drop the
~4 NaT rows. Modeled side is UTC; both are converted to UTC for the join,
then back to Eastern for reporting (per the repo's "compute UTC, present
Eastern" convention).

Outputs
-------
* PGscen-2nd/data/NYISO_real/lpi/lpi_vs_pluswind_v3_long.csv
      (group, ts_utc, ts_eastern, modeled_mw, delivered_mw)
* docs/figures/wind_v3/lpi_hourly_scorecard.csv
      per-group hourly skill: n, nMAE, rRMSE, Pearson r, mean bias, CF
* docs/figures/wind_v3/lpi_monthly_scorecard.csv
      per-group per-month modeled/delivered/gap/loss
* docs/figures/wind_v3/lpi_annual_scorecard.csv
      per-group annual modeled/delivered/gap/loss, with EIA-923 cross-check
      where the group is a single plant
* docs/figures/wind_v3/lpi_monthly_ts.png      — 4-panel monthly TS
* docs/figures/wind_v3/lpi_hourly_scatter.png  — 4-panel hourly scatter
* docs/figures/wind_v3/lpi_diurnal.png         — 4-panel diurnal (Eastern HoD)
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
LPI_XLS_DIR = REPO_ROOT / "Verification files"
WIND_DIR    = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
EIA923_DIR  = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "eia923"
OUT_LONG    = REPO_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "lpi" / "lpi_vs_pluswind_v3_long.csv"
FIG_DIR     = REPO_ROOT / "docs" / "figures" / "wind_v3"

OUT_HOURLY_SCORE  = FIG_DIR / "lpi_hourly_scorecard.csv"
OUT_MONTHLY_SCORE = FIG_DIR / "lpi_monthly_scorecard.csv"
OUT_ANNUAL_SCORE  = FIG_DIR / "lpi_annual_scorecard.csv"
OUT_MONTHLY_PNG   = FIG_DIR / "lpi_monthly_ts.png"
OUT_SCATTER_PNG   = FIG_DIR / "lpi_hourly_scatter.png"
OUT_DIURNAL_PNG   = FIG_DIR / "lpi_diurnal.png"

OVERLAP_YEARS = [2024]

LPI_FILES = [
    LPI_XLS_DIR / "MapleRidgeWindFarm_Hourly_20240101-20240630.xls",
    LPI_XLS_DIR / "MapleRidgeWindFarm_Hourly_20240701-20241231.xls",
    LPI_XLS_DIR / "MapleRidgeWindFarm_Hourly_20250101-20250630.xls",
    LPI_XLS_DIR / "MapleRidgeWindFarm_Hourly_20250701-20251231.xls",
]

# (lpi_xls_column_name) → (group_key, label, site_ids, nameplate_mw,
#                          eia_ids for EIA-923 cross-check if applicable).
# Note the double space in the Noble column name — preserved from the source.
#
# IMPORTANT: title-vs-content inference (verified May 2026)
# --------------------------------------------------------
# Three of the four LPI columns have titles that don't match their actual
# content. We inferred the true composition by reconciling LPI per-covered-hour
# MW against EIA-923 annual totals, then verified by peak observed MW:
#
#   * "Maple Ridge Wind Farm"  — MR1 ONLY, not MR1+MR2.
#       LPI peak = 225 MW. MR1 nameplate = 231 MW (97% utilization, OK).
#       MR1+MR2 combined nameplate = 321.8 MW (would imply only 70% peak).
#
#   * "Marble River / Chateaugay / Clinton / Ellenburg / Jericho Rise"
#       — 4 PLANTS, JERICHO RISE EXCLUDED despite being named.
#       LPI per-hour 94.6 MW vs EIA-923 all-5 120.5 MW (-21%);
#       vs EIA-923 4-plant-minus-Jericho 96.9 MW (-2.3%, best match).
#
#   * "Noble Wethersfield / High Sheldon / Stony Creek" — actually 4 PLANTS,
#       ALSO INCLUDES NOBLE BLISS (not named in title).
#       LPI annual 811,725 vs EIA-923 named-3 652,783 (+24%);
#       vs EIA-923 named-3 + Bliss 823,499 (-1.4%, best match).
#       Plausible operationally: all 4 are Valcour-LLC ("Noble") plants.
#
# Mapped accordingly below. The labels record the *actual* composition.
LPI_GROUPS: dict[str, dict] = {
    "maple_ridge": {
        "label":        "Maple Ridge 1 (MR2 not in LPI)",
        "lpi_col":      "Maple Ridge Wind Farm (LPI_GEN) Average",
        "site_ids":     ["wind_323574"],          # MR1 only
        "nameplate_mw": 231.0,
        "eia_ids":      [56290],                  # MR1+MR2 share one EIA registration
        # MR1+MR2 share EIA ID 56290, so the EIA-923 cross-check on this
        # group is intentionally apples-to-oranges (covers both registrations).
        "eia923_cross_caveat": "EIA-923 56290 covers MR1+MR2; LPI = MR1 only",
        "is_single":    True,
    },
    "marble_agg": {
        "label":        "Marble River + Chateaugay + Clinton + Ellenburg (Jericho excl.)",
        "lpi_col":      ("Marble River / Chateaugay / Clinton / Ellenburg / "
                         "Jericho Rise Wind (LPI_GEN) Average"),
        # 4 plants — Jericho Rise (wind_323719, EIA 59629) excluded per
        # title-vs-content reconciliation; despite being named in the title.
        "site_ids":     ["wind_323696", "wind_323614", "wind_323605", "wind_323604"],
        "nameplate_mw": 503.2,
        "eia_ids":      [56857, 56904, 56618, 56619],
        "is_single":    False,
    },
    "copenhagen": {
        "label":        "Copenhagen",
        "lpi_col":      "Copenhagen Wind (LPI_GEN) Average",
        "site_ids":     ["wind_323753"],
        "nameplate_mw": 79.9,
        "eia_ids":      [58979],
        "is_single":    True,
    },
    "noble_agg": {
        "label":        "Noble Wethersfield + High Sheldon + Stony Creek + Bliss",
        # NOTE: double space between "Wethersfield" and "/" in the source file.
        "lpi_col":      ("Noble Wethersfield  / High Sheldon / Stony Creek "
                         "Wind (LPI_GEN) Average"),
        # 4 plants — Noble Bliss (wind_323608, EIA 56620) included per
        # reconciliation; not named in title but matches LPI annual to within
        # -1.4% (vs +24% for named-3-only).
        "site_ids":     ["wind_323626", "wind_323625", "wind_323706", "wind_323608"],
        "nameplate_mw": 438.5,
        "eia_ids":      [56902, 56953, 58088, 56620],
        "is_single":    False,
        "note":         ("contains 2 unverified-bucket plants (Wethersfield, "
                         "Stony Creek/Orangeville) — aggregate may partly "
                         "cancel single-plant lat/lon biases"),
    },
}

LPI_COL_TO_KEY = {g["lpi_col"]: k for k, g in LPI_GROUPS.items()}


# ---------- LPI loader -------------------------------------------------------

def load_lpi_long() -> pd.DataFrame:
    """Stack the 4 half-year xls into one long table:
        ts_eastern (tz-aware US/Eastern), group, delivered_mw

    Drops:
      - DST-artifact rows (spring-forward duplicates, fall-back gaps) by
        localizing with ambiguous='NaT', nonexistent='NaT' and dropping NaT
      - rows outside the overlap window (years not in OVERLAP_YEARS)
      - rows with NaN delivered_mw
    """
    frames = []
    for f in LPI_FILES:
        if not f.exists():
            raise FileNotFoundError(f)
        df = pd.read_excel(f, sheet_name="Sheet0", header=0)
        # Rename to canonical group keys, keep only known columns
        rename = {"Date/Time": "ts"}
        for col in df.columns:
            if col in LPI_COL_TO_KEY:
                rename[col] = LPI_COL_TO_KEY[col]
        df = df.rename(columns=rename)
        unknown = [c for c in df.columns
                   if c not in ("ts",) and c not in LPI_GROUPS]
        if unknown:
            print(f"  WARNING: unrecognized columns in {f.name}: {unknown}")
        df["ts"] = pd.to_datetime(df["ts"])
        # Drop spring-forward duplicate rows (two 03:00s on the same date):
        # keep the first occurrence — it's the "lost 02 EST" misfiled at 03
        # and roughly equals the prior hour anyway. We then drop the entire
        # transition day's metrics from any per-day stats; for hourly metrics
        # the 1-2 affected rows are noise vs 8760.
        df = df.drop_duplicates("ts", keep="first")
        frames.append(df)
    raw = pd.concat(frames, axis=0, ignore_index=True).sort_values("ts")

    # Localize Eastern with strict DST handling; drop NaT rows.
    raw["ts_eastern"] = raw["ts"].dt.tz_localize(
        "US/Eastern", ambiguous="NaT", nonexistent="NaT")
    n_before = len(raw)
    raw = raw.dropna(subset=["ts_eastern"]).copy()
    n_dst_drop = n_before - len(raw)
    if n_dst_drop:
        print(f"  dropped {n_dst_drop} DST-ambiguous/nonexistent rows")
    raw["ts_utc"] = raw["ts_eastern"].dt.tz_convert("UTC")

    # Restrict to overlap years (Eastern calendar)
    raw = raw[raw["ts_eastern"].dt.year.isin(OVERLAP_YEARS)].copy()

    # Melt to long
    value_cols = [k for k in LPI_GROUPS if k in raw.columns]
    long = raw.melt(id_vars=["ts_utc", "ts_eastern"], value_vars=value_cols,
                    var_name="group", value_name="delivered_mw")
    long = long.dropna(subset=["delivered_mw"])
    long["delivered_mw"] = pd.to_numeric(long["delivered_mw"], errors="coerce")
    long = long.dropna(subset=["delivered_mw"])
    return long.reset_index(drop=True)


# ---------- modeled loader ---------------------------------------------------

def load_modeled_groups() -> pd.DataFrame:
    """For each overlap year, load pluswind_v3 hourly (UTC), sum the
    constituent site columns into per-group modeled MW. Return long form:
        ts_utc, group, modeled_mw
    """
    frames = []
    for y in OVERLAP_YEARS:
        f = WIND_DIR / f"wind_actual_1h_site_{y}_utc.pluswind_v3.csv"
        if not f.exists():
            print(f"  WARNING: missing modeled file {f}")
            continue
        df = pd.read_csv(f, parse_dates=["Time"])
        ts = df["Time"]  # already tz-aware UTC
        for gkey, gspec in LPI_GROUPS.items():
            site_cols = [s for s in gspec["site_ids"] if s in df.columns]
            missing = [s for s in gspec["site_ids"] if s not in df.columns]
            if missing:
                print(f"  WARNING {y} group {gkey}: missing modeled cols {missing}")
            if not site_cols:
                continue
            modeled = df[site_cols].sum(axis=1, skipna=False)
            frames.append(pd.DataFrame({
                "ts_utc": ts, "group": gkey, "modeled_mw": modeled,
            }))
    long = pd.concat(frames, axis=0, ignore_index=True)
    long = long.dropna(subset=["modeled_mw"])
    return long


# ---------- join + metrics ---------------------------------------------------

def join_long(lpi: pd.DataFrame, mod: pd.DataFrame) -> pd.DataFrame:
    j = pd.merge(lpi, mod, on=["ts_utc", "group"], how="inner")
    # Reorder columns
    j = j[["group", "ts_utc", "ts_eastern", "modeled_mw", "delivered_mw"]]
    return j.sort_values(["group", "ts_utc"]).reset_index(drop=True)


def hourly_scorecard(joined: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for gkey, g in LPI_GROUPS.items():
        sub = joined[joined["group"] == gkey]
        if sub.empty:
            continue
        m = sub["modeled_mw"].to_numpy()
        d = sub["delivered_mw"].to_numpy()
        n = len(sub)
        nameplate = g["nameplate_mw"]
        mae   = float(np.mean(np.abs(m - d)))
        rmse  = float(np.sqrt(np.mean((m - d) ** 2)))
        nmae_cap  = 100 * mae  / nameplate
        rrmse_cap = 100 * rmse / nameplate
        d_mean = float(d.mean())
        m_mean = float(m.mean())
        bias  = m_mean - d_mean
        r = float(np.corrcoef(m, d)[0, 1]) if n > 1 else float("nan")
        cf_eia  = 100 * d_mean / nameplate
        cf_mod  = 100 * m_mean / nameplate
        # annual loss fraction = (modeled - delivered) / modeled
        loss = 100 * (m.sum() - d.sum()) / m.sum() if m.sum() > 0 else float("nan")
        rows.append({
            "group":           gkey,
            "label":           g["label"],
            "n_hours":         n,
            "nameplate_mw":    nameplate,
            "cf_delivered_pct": cf_eia,
            "cf_modeled_pct":  cf_mod,
            "mean_delivered_mw": d_mean,
            "mean_modeled_mw": m_mean,
            "mean_bias_mw":    bias,
            "mae_mw":          mae,
            "rmse_mw":         rmse,
            "nmae_pct_cap":    nmae_cap,
            "rrmse_pct_cap":   rrmse_cap,
            "pearson_r":       r,
            "annual_loss_pct": loss,
        })
    return pd.DataFrame(rows)


def monthly_scorecard(joined: pd.DataFrame) -> pd.DataFrame:
    j = joined.copy()
    j["year"]  = j["ts_eastern"].dt.year
    j["month"] = j["ts_eastern"].dt.month
    agg = (j.groupby(["group", "year", "month"], as_index=False)
             .agg(modeled_mwh=("modeled_mw", "sum"),
                  delivered_mwh=("delivered_mw", "sum"),
                  n_hours=("modeled_mw", "size")))
    agg["gap_pct"]  = 100 * (agg["modeled_mwh"] - agg["delivered_mwh"]) / agg["delivered_mwh"]
    agg["loss_pct"] = 100 * (agg["modeled_mwh"] - agg["delivered_mwh"]) / agg["modeled_mwh"]
    agg["label"] = agg["group"].map({k: g["label"] for k, g in LPI_GROUPS.items()})
    return agg


def annual_scorecard(joined: pd.DataFrame) -> pd.DataFrame:
    j = joined.copy()
    j["year"] = j["ts_eastern"].dt.year
    agg = (j.groupby(["group", "year"], as_index=False)
             .agg(modeled_mwh=("modeled_mw", "sum"),
                  delivered_mwh=("delivered_mw", "sum"),
                  n_hours=("modeled_mw", "size")))
    agg["gap_pct"]  = 100 * (agg["modeled_mwh"] - agg["delivered_mwh"]) / agg["delivered_mwh"]
    agg["loss_pct"] = 100 * (agg["modeled_mwh"] - agg["delivered_mwh"]) / agg["modeled_mwh"]
    agg["label"] = agg["group"].map({k: g["label"] for k, g in LPI_GROUPS.items()})

    # EIA-923 cross-check: for each (group, year) sum EIA-923 delivered across
    # the constituent EIA IDs; lets us check whether LPI ≈ EIA-923 at the
    # group-year level (sanity check on the LPI export).
    eia_long_path = EIA923_DIR / "eia923_vs_pluswind_v3_long.csv"
    if eia_long_path.exists():
        eia_long = pd.read_csv(eia_long_path)
        eia_an = (eia_long.groupby(["year", "eia_plant_id"], as_index=False)
                          .agg(eia_mwh=("eia_delivered_mwh", "sum")))
        rows = []
        for gkey, g in LPI_GROUPS.items():
            for y in agg.loc[agg["group"] == gkey, "year"].unique():
                eia_sum = eia_an[(eia_an["year"] == y)
                                 & (eia_an["eia_plant_id"].isin(g["eia_ids"]))
                                 ]["eia_mwh"].sum()
                rows.append({"group": gkey, "year": int(y),
                             "eia923_mwh": float(eia_sum)})
        eia_cross = pd.DataFrame(rows)
        agg = agg.merge(eia_cross, on=["group", "year"], how="left")
        agg["lpi_vs_eia923_pct"] = 100 * (agg["delivered_mwh"] - agg["eia923_mwh"]) / agg["eia923_mwh"]
    return agg


# ---------- plots ------------------------------------------------------------

def _panel_grid_ax():
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    return fig, axes.flatten()


def plot_monthly_ts(monthly: pd.DataFrame) -> None:
    fig, axes = _panel_grid_ax()
    for ax, (gkey, g) in zip(axes, LPI_GROUPS.items()):
        sub = monthly[monthly["group"] == gkey].copy()
        if sub.empty:
            ax.set_title(f"{g['label']} (no data)"); ax.axis("off"); continue
        sub["date"] = pd.to_datetime(dict(year=sub["year"], month=sub["month"], day=1))
        ax.plot(sub["date"], sub["modeled_mwh"]   / 1e3, "-o",
                color="#ea580c", label="pluswind_v3 modeled", linewidth=2)
        ax.plot(sub["date"], sub["delivered_mwh"] / 1e3, "-s",
                color="#0369a1", label="LPI delivered", linewidth=2)
        ax.set_title(f"{g['label']}\nnameplate {g['nameplate_mw']:.1f} MW",
                     fontsize=10)
        ax.set_ylabel("Monthly energy (GWh)", fontsize=9)
        ax.tick_params(axis="x", labelrotation=30, labelsize=8)
        ax.grid(alpha=0.3)
        ax.legend(loc="best", fontsize=8)
    fig.suptitle("LPI delivered vs pluswind_v3 potential — monthly (2024)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT_MONTHLY_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_hourly_scatter(joined: pd.DataFrame, hourly: pd.DataFrame) -> None:
    fig, axes = _panel_grid_ax()
    score_by_g = hourly.set_index("group").to_dict("index")
    for ax, (gkey, g) in zip(axes, LPI_GROUPS.items()):
        sub = joined[joined["group"] == gkey]
        if sub.empty:
            ax.set_title(f"{g['label']} (no data)"); ax.axis("off"); continue
        m = sub["modeled_mw"].to_numpy()
        d = sub["delivered_mw"].to_numpy()
        hb = ax.hexbin(d, m, gridsize=60, cmap="viridis", mincnt=1,
                       bins="log")
        lim = max(g["nameplate_mw"], m.max(), d.max()) * 1.05
        ax.plot([0, lim], [0, lim], "--", color="black", lw=0.7, alpha=0.6)
        ax.set_xlim(0, lim); ax.set_ylim(0, lim)
        s = score_by_g.get(gkey, {})
        ax.set_title(f"{g['label']}\n"
                     f"r={s.get('pearson_r', 0):.3f}  "
                     f"nMAE={s.get('nmae_pct_cap', 0):.1f}%  "
                     f"loss={s.get('annual_loss_pct', 0):.1f}%",
                     fontsize=10)
        ax.set_xlabel("LPI delivered (MW)", fontsize=9)
        ax.set_ylabel("pluswind_v3 modeled (MW)", fontsize=9)
        fig.colorbar(hb, ax=ax, label="log(N hours)", shrink=0.7)
    fig.suptitle("LPI delivered vs pluswind_v3 potential — hourly (2024)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT_SCATTER_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_diurnal(joined: pd.DataFrame) -> None:
    fig, axes = _panel_grid_ax()
    j = joined.copy()
    j["hour_e"] = j["ts_eastern"].dt.hour
    for ax, (gkey, g) in zip(axes, LPI_GROUPS.items()):
        sub = j[j["group"] == gkey]
        if sub.empty:
            ax.set_title(f"{g['label']} (no data)"); ax.axis("off"); continue
        diurnal = (sub.groupby("hour_e")
                      [["modeled_mw", "delivered_mw"]].mean())
        cf_mod = diurnal["modeled_mw"]   / g["nameplate_mw"] * 100
        cf_del = diurnal["delivered_mw"] / g["nameplate_mw"] * 100
        ax.plot(diurnal.index, cf_mod, "-o",
                color="#ea580c", label="modeled", linewidth=2)
        ax.plot(diurnal.index, cf_del, "-s",
                color="#0369a1", label="delivered", linewidth=2)
        ax.set_title(g["label"], fontsize=10)
        ax.set_xlabel("Hour of day (US/Eastern)", fontsize=9)
        ax.set_ylabel("Mean CF (%)", fontsize=9)
        ax.set_xticks(range(0, 24, 3))
        ax.grid(alpha=0.3)
        ax.legend(loc="best", fontsize=8)
    fig.suptitle("Mean diurnal CF — LPI delivered vs pluswind_v3 potential (2024)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT_DIURNAL_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------- main -------------------------------------------------------------

def main() -> None:
    OUT_LONG.parent.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading LPI xls × {len(LPI_FILES)} …")
    lpi = load_lpi_long()
    print(f"  LPI long rows: {len(lpi):,}, "
          f"groups present: {sorted(lpi['group'].unique())}")

    print(f"Loading pluswind_v3 modeled for {OVERLAP_YEARS} …")
    mod = load_modeled_groups()
    print(f"  modeled long rows: {len(mod):,}")

    print("Joining …")
    joined = join_long(lpi, mod)
    print(f"  joined rows: {len(joined):,} "
          f"({len(joined) // 4} hours × 4 groups, expected ~8784)")

    joined.to_csv(OUT_LONG, index=False)
    print(f"  wrote {OUT_LONG}")

    hourly  = hourly_scorecard(joined)
    monthly = monthly_scorecard(joined)
    annual  = annual_scorecard(joined)

    hourly.to_csv(OUT_HOURLY_SCORE, index=False)
    monthly.to_csv(OUT_MONTHLY_SCORE, index=False)
    annual.to_csv(OUT_ANNUAL_SCORE, index=False)
    print(f"  wrote {OUT_HOURLY_SCORE}")
    print(f"  wrote {OUT_MONTHLY_SCORE}")
    print(f"  wrote {OUT_ANNUAL_SCORE}")

    print("Plotting …")
    plot_monthly_ts(monthly)
    plot_hourly_scatter(joined, hourly)
    plot_diurnal(joined)
    print(f"  wrote {OUT_MONTHLY_PNG}")
    print(f"  wrote {OUT_SCATTER_PNG}")
    print(f"  wrote {OUT_DIURNAL_PNG}")

    print()
    print("=== Hourly scorecard ===")
    cols = ["label", "n_hours", "cf_delivered_pct", "cf_modeled_pct",
            "mean_bias_mw", "nmae_pct_cap", "rrmse_pct_cap",
            "pearson_r", "annual_loss_pct"]
    print(hourly[cols].to_string(index=False))

    print()
    print("=== Annual scorecard ===")
    cols = ["label", "year", "modeled_mwh", "delivered_mwh",
            "gap_pct", "loss_pct"]
    if "eia923_mwh" in annual.columns:
        cols += ["eia923_mwh", "lpi_vs_eia923_pct"]
    print(annual[cols].to_string(index=False))


if __name__ == "__main__":
    main()
