"""Comprehensive v3 plots covering all 7 years (2018-2024).

For 2018-2021 (PLUSWIND coverage): v3 vs PLUSWIND scoring plots.
For 2018-2024 (full coverage):     fleet output, capacity factors, year totals.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
WIND = OUT_DIR.parents[1] / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
META = OUT_DIR.parents[1] / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata" / "wind_meta.csv"

YEARS_PLUS = [2018, 2019, 2020, 2021]
YEARS_FULL = [2018, 2019, 2020, 2021, 2022, 2023, 2024]

C_V1   = "#16a34a"
C_V3   = "#ea580c"
C_PLUS = "#7c3aed"
C_NYISO = "#d97706"


def load_act(suffix: str, year: int) -> pd.DataFrame:
    f = WIND / f"wind_actual_1h_site_{year}_utc{suffix}.csv"
    if not f.exists():
        return pd.DataFrame()
    df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def metrics(target: pd.Series, p: pd.Series) -> dict:
    df = pd.concat([target, p], axis=1).dropna()
    a, q = df.iloc[:, 0], df.iloc[:, 1]
    e = q - a
    bias = float(e.mean()); mae = float(e.abs().mean())
    am = float(a.mean())
    bc_mae = float((e - bias).abs().mean())
    return {"n": len(df), "nbias": 100 * bias / am,
            "nmae": 100 * mae / am, "bc_nmae": 100 * bc_mae / am,
            "amean": am}


# ---------------------------------------------------------------------------
# Build the master frame for 2018-2021 (PLUSWIND era)
# ---------------------------------------------------------------------------

print("Loading 2018-2021 (PLUSWIND era) on 22-plant intersection...")
v1_y = {y: load_act(".pluswind_v1", y) for y in YEARS_PLUS}
v3_y = {y: load_act(".pluswind_v3", y) for y in YEARS_PLUS}
pl_y = {y: load_act(".pluswind",    y) for y in YEARS_PLUS}

# Common plants intersection across all 4 years
common = None
for y in YEARS_PLUS:
    cols = set(v1_y[y].columns) & set(v3_y[y].columns) & set(pl_y[y].columns)
    common = cols if common is None else common & cols
common = sorted(common)
print(f"  common plants: {len(common)}")

# Per-year fleet sums (PLUSWIND-era frame)
def fleet_sum(d, year):
    return d[year][common].sum(axis=1)

frames_pe = []
for y in YEARS_PLUS:
    df = pd.concat([
        fleet_sum(v1_y, y).rename("v1"),
        fleet_sum(v3_y, y).rename("v3"),
        fleet_sum(pl_y, y).rename("pl"),
    ], axis=1)
    frames_pe.append(df)
pe = pd.concat(frames_pe).sort_index()
pe = pe.dropna()
print(f"  joined frame (2018-2021): {len(pe):,} h")

# ---------------------------------------------------------------------------
# Full 7-year frame (active plants per year, fleet-summed)
# ---------------------------------------------------------------------------

print("Loading 2018-2024 (full v3 series)...")
meta = pd.read_csv(META)
v3_full_frames = []
for y in YEARS_FULL:
    df = load_act(".pluswind_v3", y)
    active = sorted(set(df.columns) & set(meta[meta["operating_year"] <= y]["site_id"]))
    s = df[active].sum(axis=1)
    v3_full_frames.append(s)
v3_full = pd.concat(v3_full_frames).sort_index()
print(f"  v3 full-year frame: {v3_full.index.min()} → {v3_full.index.max()}, {len(v3_full):,} h")


# ===========================================================================
# Plot 1 — year-by-year nMAE bars (v1 vs v3) vs PLUSWIND
# ===========================================================================

def plot_nmae_bars():
    rows = []
    for y in YEARS_PLUS:
        sub = pe.loc[str(y)]
        rows.append({"year": y, "label": "v1",
                     **metrics(sub["pl"], sub["v1"])})
        rows.append({"year": y, "label": "v3",
                     **metrics(sub["pl"], sub["v3"])})
    df = pd.DataFrame(rows)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    width = 0.4
    years = YEARS_PLUS
    x = np.arange(len(years))

    # nMAE
    ax = axes[0]
    v1 = df[df.label == "v1"]["nmae"].values
    v3 = df[df.label == "v3"]["nmae"].values
    ax.bar(x - width/2, v1, width, color=C_V1, label="v1 (cubic curve)")
    ax.bar(x + width/2, v3, width, color=C_V3, label="v3 (SAM + density)")
    for xi, h in zip(x - width/2, v1):
        ax.text(xi, h + 0.3, f"{h:.1f}", ha="center", fontsize=9)
    for xi, h in zip(x + width/2, v3):
        ax.text(xi, h + 0.3, f"{h:.2f}", ha="center", fontsize=9, color="black")
    ax.set_xticks(x); ax.set_xticklabels(years)
    ax.set_ylabel("nMAE (%) — lower is better")
    ax.set_title("nMAE vs PLUSWIND, 22-plant fleet, 2018-2021",
                 fontsize=11, loc="left")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(alpha=0.3, axis="y")

    # bias
    ax = axes[1]
    v1b = df[df.label == "v1"]["nbias"].values
    v3b = df[df.label == "v3"]["nbias"].values
    ax.axhline(0, color="k", lw=0.7)
    ax.bar(x - width/2, v1b, width, color=C_V1, label="v1")
    ax.bar(x + width/2, v3b, width, color=C_V3, label="v3")
    for xi, h in zip(x - width/2, v1b):
        ax.text(xi, h - 0.6, f"{h:+.1f}", ha="center", fontsize=9)
    for xi, h in zip(x + width/2, v3b):
        ax.text(xi, h + 0.4 if h >= 0 else h - 0.6, f"{h:+.2f}",
                ha="center", fontsize=9, color="black")
    ax.set_xticks(x); ax.set_xticklabels(years)
    ax.set_ylabel("Bias (%)")
    ax.set_title("Bias vs PLUSWIND",
                 fontsize=11, loc="left")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(alpha=0.3, axis="y")

    plt.suptitle(
        "v3 collapses the gap to PLUSWIND — nMAE 16-18% → 1.5-3.2%",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "v3_all_01_nmae_bars.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


# ===========================================================================
# Plot 2 — pooled scatter, all 4 PLUSWIND years
# ===========================================================================

def plot_pooled_scatter():
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), sharex=True, sharey=True)
    lim = pe[["v1", "v3", "pl"]].max().max() * 1.05

    panels = [(pe["pl"], pe["v1"], "v1 (cubic curve)", C_V1),
              (pe["pl"], pe["v3"], "v3 (SAM + density)", C_V3)]
    for ax, (a, p, title, color) in zip(axes, panels):
        ax.scatter(a, p, s=2, alpha=0.15, color=color, rasterized=True)
        ax.plot([0, lim], [0, lim], "k--", lw=1, alpha=0.5, label="y = x")
        m = metrics(a, p)
        ax.set_xlim(0, lim); ax.set_ylim(0, lim)
        ax.set_xlabel("PLUSWIND (MW)")
        ax.set_ylabel("In-house pipeline (MW)")
        ax.set_title(title, fontsize=11, loc="left")
        ax.text(0.04, 0.96,
                (f"n      = {m['n']:,}\n"
                 f"bias   = {m['nbias']:+.2f}%\n"
                 f"nMAE   = {m['nmae']:.2f}%\n"
                 f"BC nMAE= {m['bc_nmae']:.2f}%"),
                transform=ax.transAxes, va="top", ha="left",
                fontsize=10, family="monospace",
                bbox=dict(boxstyle="round", fc="white", alpha=0.9))
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=9)
    plt.suptitle("Scatter — all 2018-2021 hours pooled (35k samples)",
                 fontsize=13, x=0.06, ha="left")
    plt.tight_layout()
    out = OUT_DIR / "v3_all_02_pooled_scatter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


# ===========================================================================
# Plot 3 — monthly mean over 2018-2021, all three series
# ===========================================================================

def plot_monthly_4year():
    monthly = pe[["v1", "v3", "pl"]].resample("MS").mean()
    fig, ax = plt.subplots(1, 1, figsize=(13, 5))
    ax.plot(monthly.index, monthly["pl"], color=C_PLUS, lw=2.4,
            label="PLUSWIND")
    ax.plot(monthly.index, monthly["v3"], color=C_V3, lw=2.0,
            label="physics_v3")
    ax.plot(monthly.index, monthly["v1"], color=C_V1, lw=1.4, ls=":",
            alpha=0.8, label="physics_v1 (legacy)")
    ax.set_ylabel("Monthly-mean wind (MW, 22-plant fleet)")
    ax.set_xlabel("Month")
    ax.set_title("Monthly fleet mean — v3 lies on PLUSWIND, 2018-2021",
                 fontsize=11, loc="left")
    ax.legend(loc="upper left", fontsize=10, framealpha=0.95)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    out = OUT_DIR / "v3_all_03_monthly_4yr.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


# ===========================================================================
# Plot 4 — diurnal, pooled across 2018-2021, summer/winter
# ===========================================================================

def plot_diurnal_pooled():
    df = pe.copy()
    df["hour"] = df.index.hour
    df["month"] = df.index.month
    seasons = [
        ("Summer (JJA, 2018-2021)", df[df["month"].isin([6, 7, 8])]),
        ("Winter (DJF, 2018-2021)", df[df["month"].isin([12, 1, 2])]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, (label, sub) in zip(axes, seasons):
        agg = sub.groupby("hour").mean(numeric_only=True)
        ax.plot(agg.index, agg["pl"], color=C_PLUS, lw=2.4, marker="o",
                ms=4, label="PLUSWIND")
        ax.plot(agg.index, agg["v3"], color=C_V3, lw=2.0, marker="o",
                ms=4, label="physics_v3")
        ax.plot(agg.index, agg["v1"], color=C_V1, lw=1.4, ls=":",
                marker="s", ms=3, alpha=0.7, label="physics_v1")
        ax.set_xlim(0, 23); ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("Hour of day (UTC)")
        ax.set_ylabel("Mean wind generation (MW)")
        ax.set_title(label, fontsize=11, loc="left")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    plt.suptitle("Diurnal pattern — pooled 2018-2021",
                 fontsize=13, x=0.06, ha="left")
    plt.tight_layout()
    out = OUT_DIR / "v3_all_04_diurnal_pooled.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


# ===========================================================================
# Plot 5 — full 7-year fleet output time series (monthly)
# ===========================================================================

def plot_full_7yr():
    monthly = v3_full.resample("MS").mean().rename("v3_full")
    # Total active nameplate per month for capacity factor curve
    nameplate_series = []
    for ts in monthly.index:
        active = meta[meta["operating_year"] <= ts.year]["nameplate_mw"].sum()
        nameplate_series.append(active)
    nameplate = pd.Series(nameplate_series, index=monthly.index, name="nameplate_mw")
    cf = monthly / nameplate

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    ax = axes[0]
    ax.plot(monthly.index, monthly, color=C_V3, lw=2.0, label="v3 fleet sum")
    ax.fill_between(monthly.index, 0, monthly, alpha=0.10, color=C_V3)
    ax2 = ax.twinx()
    ax2.plot(monthly.index, nameplate, color="grey", lw=1.0, ls="--",
             label="active nameplate")
    ax2.set_ylabel("Active fleet nameplate (MW)", color="grey")
    ax2.tick_params(axis="y", colors="grey")
    ax.set_ylabel("Monthly-mean wind generation (MW)")
    ax.set_title("v3 monthly fleet output 2018-2024 (all active NY plants)",
                 fontsize=11, loc="left")
    ax.legend(loc="upper left", fontsize=10)
    ax.grid(alpha=0.3)

    ax = axes[1]
    ax.plot(cf.index, cf * 100, color=C_V3, lw=2.0, marker="o", ms=3,
            label="monthly capacity factor")
    ax.axhspan(28, 38, alpha=0.05, color="grey", label="typical NY range 28–38 %")
    ax.set_ylabel("Capacity factor (%)")
    ax.set_xlabel("Time")
    ax.set_title("Monthly capacity factor — sanity check",
                 fontsize=11, loc="left")
    ax.set_ylim(0, 60)
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    out = OUT_DIR / "v3_all_05_full_7yr.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


# ===========================================================================
# Plot 6 — week-long zooms across years (one row per year, summer & winter)
# ===========================================================================

def plot_year_zooms():
    """Pick the same week each summer (Jul 13-19) for the 2018-2021 PLUSWIND
    period — show v3 vs PLUSWIND tracking."""
    fig, axes = plt.subplots(len(YEARS_PLUS), 1, figsize=(13, 9), sharex=False)
    for ax, y in zip(axes, YEARS_PLUS):
        start, end = f"{y}-07-13", f"{y}-07-19"
        sub = pe.loc[start:f"{end} 23:59"]
        ax.plot(sub.index, sub["pl"], color=C_PLUS, lw=2.0,
                label="PLUSWIND" if y == YEARS_PLUS[0] else None)
        ax.plot(sub.index, sub["v3"], color=C_V3, lw=1.6,
                label="physics_v3" if y == YEARS_PLUS[0] else None)
        ax.plot(sub.index, sub["v1"], color=C_V1, lw=1.0, ls=":",
                alpha=0.7,
                label="physics_v1" if y == YEARS_PLUS[0] else None)
        ax.set_title(f"{y} — Jul 13-19 (summer)",
                     fontsize=10, loc="left")
        ax.set_ylabel("MW")
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
        if y == YEARS_PLUS[0]:
            ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    plt.suptitle(
        "Same summer week each year — v3 (orange) tracks PLUSWIND (purple) "
        "across all 4 years",
        fontsize=12, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "v3_all_06_year_zooms.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


print("\nPlotting...")
plot_nmae_bars()
plot_pooled_scatter()
plot_monthly_4year()
plot_diurnal_pooled()
plot_full_7yr()
plot_year_zooms()
print("done.")
