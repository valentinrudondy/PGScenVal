"""Plots comparing pluswind_v1 (no density correction) vs pluswind_v2
(with HRRR density correction) against PLUSWIND on the 22-plant overlap, 2020.
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
YEAR = 2020

C_V1   = "#16a34a"   # green
C_V2   = "#1d4ed8"   # blue — density-corrected
C_PLUS = "#7c3aed"   # violet — target


def load(suffix: str, year: int = YEAR) -> pd.DataFrame:
    f = WIND / f"wind_actual_1h_site_{year}_utc{suffix}.csv"
    df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


print("Loading...")
v1 = load(".pluswind_v1")
v2 = load(".pluswind_v2")
pl = load(".pluswind")
common = sorted(set(v1.columns) & set(v2.columns) & set(pl.columns))
print(f"  common plants: {len(common)}")

allf = pd.concat([
    v1[common].sum(axis=1).rename("v1"),
    v2[common].sum(axis=1).rename("v2"),
    pl[common].sum(axis=1).rename("pl"),
], axis=1).dropna()


def metrics(target: pd.Series, p: pd.Series) -> dict:
    e = p - target
    bias = float(e.mean()); mae = float(e.abs().mean())
    am = float(target.mean())
    bc_mae = float((e - bias).abs().mean())
    return {"n": len(target), "nbias": 100 * bias / am,
            "nmae": 100 * mae / am, "bc_nmae": 100 * bc_mae / am}


# ---------------------------------------------------------------------------
# Plot 1 — summer + winter weeks
# ---------------------------------------------------------------------------

def plot_two_weeks():
    weeks = [
        ("2020-07-13", "2020-07-19", "Summer week (Jul 13–19, 2020) — warm thin air"),
        ("2020-12-14", "2020-12-20", "Winter week (Dec 14–20, 2020) — cold dense air"),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)
    for ax, (start, end, title) in zip(axes, weeks):
        sub = allf.loc[start:f"{end} 23:59"]
        ax.plot(sub.index, sub["pl"], color=C_PLUS, lw=2.0,
                label="PLUSWIND (target)")
        ax.plot(sub.index, sub["v1"], color=C_V1, lw=1.4,
                label="physics_v1 (no density correction)")
        ax.plot(sub.index, sub["v2"], color=C_V2, lw=1.4, ls="-",
                label="physics_v2 (HRRR density correction)")
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_ylabel("Wind generation (MW, 22-plant fleet)")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    axes[1].set_xlabel("Time (UTC)")
    plt.suptitle(
        "Option B — adding density correction (v1 → v2)",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "v2_01_two_weeks.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# Plot 2 — diurnal summer/winter
# ---------------------------------------------------------------------------

def plot_diurnal():
    yr = allf.copy()
    yr["hour"] = yr.index.hour
    yr["month"] = yr.index.month
    seasons = [
        ("Summer (JJA 2020)", yr[yr["month"].isin([6, 7, 8])]),
        ("Winter (DJF 2020)", yr[yr["month"].isin([12, 1, 2])]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, (label, sub) in zip(axes, seasons):
        agg = sub.groupby("hour").mean(numeric_only=True)
        ax.plot(agg.index, agg["pl"], color=C_PLUS, lw=2.4, marker="o",
                ms=4, label="PLUSWIND")
        ax.plot(agg.index, agg["v1"], color=C_V1, lw=2.0, marker="o",
                ms=4, label="physics_v1")
        ax.plot(agg.index, agg["v2"], color=C_V2, lw=2.0, marker="o",
                ms=4, label="physics_v2")
        ax.set_xlim(0, 23); ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("Hour of day (UTC)")
        ax.set_ylabel("Mean wind generation (MW)")
        ax.set_title(label, fontsize=11, loc="left")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    plt.suptitle("Diurnal — v1 vs v2 vs PLUSWIND, 2020",
                 fontsize=13, x=0.06, ha="left")
    plt.tight_layout()
    out = OUT_DIR / "v2_02_diurnal.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# Plot 3 — monthly bars: gap to PLUSWIND, v1 vs v2
# ---------------------------------------------------------------------------

def plot_monthly_gap():
    monthly = allf.resample("MS").mean()
    gap_v1 = monthly["v1"] - monthly["pl"]
    gap_v2 = monthly["v2"] - monthly["pl"]
    delta  = monthly["v2"] - monthly["v1"]   # density correction effect

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    months = monthly.index
    width = pd.Timedelta(days=12)

    ax1.bar(months - width/2, gap_v1, width=width, color=C_V1, alpha=0.85,
            label="physics_v1 − PLUSWIND")
    ax1.bar(months + width/2, gap_v2, width=width, color=C_V2, alpha=0.85,
            label="physics_v2 − PLUSWIND")
    ax1.axhline(0, color="k", lw=0.7)
    ax1.set_ylabel("Monthly gap to PLUSWIND (MW)")
    ax1.set_title("Gap to PLUSWIND, monthly — v2 should be flatter than v1",
                  fontsize=11, loc="left")
    ax1.legend(loc="lower right", fontsize=9, framealpha=0.95)
    ax1.grid(alpha=0.3, axis="y")

    ax2.bar(months, delta, width=width*1.6, color=C_V2, alpha=0.85,
            label="physics_v2 − physics_v1 (density correction effect)")
    ax2.axhline(0, color="k", lw=0.7)
    ax2.set_ylabel("Δ MW (v2 − v1)")
    ax2.set_xlabel("Month, 2020")
    ax2.set_title(
        "Density correction effect — positive in winter (cold dense air), "
        "negative in summer", fontsize=11, loc="left",
    )
    ax2.legend(loc="lower right", fontsize=9, framealpha=0.95)
    ax2.grid(alpha=0.3, axis="y")
    ax2.xaxis.set_major_locator(mdates.MonthLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))

    plt.tight_layout()
    out = OUT_DIR / "v2_03_monthly_gap.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# Plot 4 — scatter
# ---------------------------------------------------------------------------

def plot_scatter():
    panels = [
        (allf["pl"], allf["v1"], "physics_v1 vs PLUSWIND", C_V1),
        (allf["pl"], allf["v2"], "physics_v2 vs PLUSWIND", C_V2),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), sharex=True, sharey=True)
    lim_max = max(allf[["v1", "v2", "pl"]].max().max() * 1.05, 1.0)
    for ax, (a, p, title, color) in zip(axes, panels):
        ax.scatter(a, p, s=3, alpha=0.25, color=color, rasterized=True)
        ax.plot([0, lim_max], [0, lim_max], "k--", lw=1, alpha=0.5,
                label="y = x")
        m = metrics(a, p)
        ax.set_xlabel("PLUSWIND (MW)")
        ax.set_ylabel("In-house pipeline (MW)")
        ax.set_xlim(0, lim_max); ax.set_ylim(0, lim_max)
        ax.set_title(title, fontsize=11, loc="left")
        ax.text(0.04, 0.96,
                (f"n      = {m['n']}\n"
                 f"bias   = {m['nbias']:+.1f}%\n"
                 f"nMAE   = {m['nmae']:.1f}%\n"
                 f"BC nMAE= {m['bc_nmae']:.1f}%"),
                transform=ax.transAxes, va="top", ha="left",
                fontsize=10, family="monospace",
                bbox=dict(boxstyle="round", fc="white", alpha=0.9))
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=9)
    plt.suptitle("Scatter — physics_v1 vs physics_v2, 2020",
                 fontsize=13, x=0.06, ha="left")
    plt.tight_layout()
    out = OUT_DIR / "v2_04_scatter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# Plot 5 — partial-load curve diagnostic (the smoking gun)
# ---------------------------------------------------------------------------

def plot_curve_comparison():
    """For a representative plant, scatter (HRRR WS) → (PLUSWIND power).
    Overlay our parametric cubic. The gap shows where the curve mismatch is."""
    # Reuse cached HRRR WS at one plant. Pick Maple Ridge 1 (wind_323574, EIA 56290).
    site = "wind_323574"
    v1_p = pd.read_csv(WIND / f"wind_actual_1h_site_{YEAR}_utc.pluswind_v1.csv",
                       parse_dates=["Time"], index_col="Time")[site]
    v2_p = pd.read_csv(WIND / f"wind_actual_1h_site_{YEAR}_utc.pluswind_v2.csv",
                       parse_dates=["Time"], index_col="Time")[site]
    pl_p = pd.read_csv(WIND / f"wind_actual_1h_site_{YEAR}_utc.pluswind.csv",
                       parse_dates=["Time"], index_col="Time")[site]

    # Use v1's output as a deterministic function of WS to back-solve WS.
    # Plant nameplate from wind_meta.csv
    meta = pd.read_csv(
        WIND.parents[0] / "plant_metadata" / "wind_meta.csv"
    )
    np_mw = float(meta.loc[meta["site_id"] == site, "nameplate_mw"].iloc[0])
    # USWTDB → specific power → rated WS, same as wind_physics
    import sys
    sys.path.insert(0, str(WIND.parents[2] / "pgscen"))
    from utils.wind_physics import (
        specific_power_per_plant, rated_ws_from_specific_power, CUT_IN_MS, CUT_OUT_MS,
    )
    turb = pd.read_csv(WIND.parents[0] / "plant_metadata" / "uswtdb_ny_turbines.csv")
    sp = specific_power_per_plant(meta[meta["site_id"] == site].reset_index(drop=True), turb)
    rs = rated_ws_from_specific_power(sp)[0]
    print(f"  {site}: σ={sp[0]:.0f} W/m², RS={rs:.2f} m/s, nameplate={np_mw} MW")

    # Generate a curve over WS for plotting
    ws = np.linspace(0, 25, 200)
    p_cubic = np.where(
        ws < CUT_IN_MS, 0.0,
        np.where(ws < rs,
                 np_mw * ((ws - CUT_IN_MS) / (rs - CUT_IN_MS)) ** 3 * (1 - 0.07),
                 np.where(ws <= CUT_OUT_MS, np_mw, 0.0))
    )

    # Now find what PLUSWIND power is at each "reverse-solved" WS for v1
    # Simpler: directly plot (v1 power) vs (PLUSWIND power) per hour
    df = pd.concat([v1_p.rename("v1"), v2_p.rename("v2"),
                    pl_p.rename("pl")], axis=1).dropna()

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax = axes[0]
    ax.scatter(df["v1"], df["pl"], s=3, alpha=0.3, color=C_V1, rasterized=True,
               label="physics_v1 vs PLUSWIND")
    ax.plot([0, np_mw], [0, np_mw], "k--", lw=1, alpha=0.5, label="y = x")
    ax.set_xlabel(f"physics_v1 power (MW), {site}")
    ax.set_ylabel("PLUSWIND power (MW)")
    ax.set_title(f"v1 vs PLUSWIND (one plant: {site})", fontsize=11, loc="left")
    ax.set_xlim(0, np_mw * 1.05); ax.set_ylim(0, np_mw * 1.05)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)

    ax = axes[1]
    ax.scatter(df["v2"], df["pl"], s=3, alpha=0.3, color=C_V2, rasterized=True,
               label="physics_v2 vs PLUSWIND")
    ax.plot([0, np_mw], [0, np_mw], "k--", lw=1, alpha=0.5, label="y = x")
    ax.set_xlabel(f"physics_v2 power (MW), {site}")
    ax.set_ylabel("PLUSWIND power (MW)")
    ax.set_title(f"v2 vs PLUSWIND (one plant: {site})", fontsize=11, loc="left")
    ax.set_xlim(0, np_mw * 1.05); ax.set_ylim(0, np_mw * 1.05)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)

    plt.suptitle(
        f"Per-plant scatter — Maple Ridge ({site}, σ={sp[0]:.0f} W/m², "
        f"RS={rs:.1f} m/s). The bend shows where the cubic curve "
        f"underpredicts vs SAM's smooth curve.",
        fontsize=11, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "v2_05_per_plant_scatter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


print("Plotting...")
plot_two_weeks()
plot_diurnal()
plot_monthly_gap()
plot_scatter()
plot_curve_comparison()
print("done.")
