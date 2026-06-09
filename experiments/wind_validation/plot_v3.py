"""Plots showing pluswind_v3 (SAM curves + density correction) against the
earlier physics variants and PLUSWIND target. Scope: 2020 (only year v3
has been run for so far)."""
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
C_V2   = "#1d4ed8"   # blue
C_V3   = "#ea580c"   # orange — full PLUSWIND recipe
C_PLUS = "#7c3aed"   # violet — target


def load(suffix: str, year: int = YEAR) -> pd.DataFrame:
    f = WIND / f"wind_actual_1h_site_{year}_utc{suffix}.csv"
    df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def metrics(target: pd.Series, p: pd.Series) -> dict:
    e = p - target
    bias = float(e.mean()); mae = float(e.abs().mean())
    am = float(target.mean())
    bc_mae = float((e - bias).abs().mean())
    return {"n": len(target), "nbias": 100 * bias / am,
            "nmae": 100 * mae / am, "bc_nmae": 100 * bc_mae / am}


print("Loading...")
v1 = load(".pluswind_v1");  v2 = load(".pluswind_v2")
v3 = load(".pluswind_v3");  pl = load(".pluswind")
common = sorted(set(v1.columns) & set(v2.columns) & set(v3.columns) & set(pl.columns))
print(f"  common plants: {len(common)}")

allf = pd.concat([
    v1[common].sum(axis=1).rename("v1"),
    v2[common].sum(axis=1).rename("v2"),
    v3[common].sum(axis=1).rename("v3"),
    pl[common].sum(axis=1).rename("pl"),
], axis=1).dropna()


def plot_two_weeks():
    weeks = [
        ("2020-07-13", "2020-07-19", "Summer week (Jul 13–19, 2020)"),
        ("2020-12-14", "2020-12-20", "Winter week (Dec 14–20, 2020)"),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)
    for ax, (start, end, title) in zip(axes, weeks):
        sub = allf.loc[start:f"{end} 23:59"]
        ax.plot(sub.index, sub["pl"], color=C_PLUS, lw=2.4,
                label="PLUSWIND (target)")
        ax.plot(sub.index, sub["v3"], color=C_V3, lw=1.6,
                label="physics_v3 (SAM + density)")
        ax.plot(sub.index, sub["v2"], color=C_V2, lw=1.0, ls="--",
                alpha=0.6, label="physics_v2 (cubic + density)")
        ax.plot(sub.index, sub["v1"], color=C_V1, lw=1.0, ls=":",
                alpha=0.6, label="physics_v1 (cubic only)")
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_ylabel("Wind generation (MW, 22-plant fleet)")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    axes[1].set_xlabel("Time (UTC)")
    plt.suptitle(
        "Option C — physics_v3 (SAM curves + density) overlays PLUSWIND",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "v3_01_two_weeks.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


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
        ax.plot(agg.index, agg["pl"], color=C_PLUS, lw=2.6, marker="o",
                ms=4, label="PLUSWIND")
        ax.plot(agg.index, agg["v3"], color=C_V3, lw=2.0, marker="o",
                ms=4, label="physics_v3")
        ax.plot(agg.index, agg["v2"], color=C_V2, lw=1.4, ls="--",
                alpha=0.7, label="physics_v2")
        ax.plot(agg.index, agg["v1"], color=C_V1, lw=1.4, ls=":",
                alpha=0.7, label="physics_v1")
        ax.set_xlim(0, 23); ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("Hour of day (UTC)")
        ax.set_ylabel("Mean wind generation (MW)")
        ax.set_title(label, fontsize=11, loc="left")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    plt.suptitle("Diurnal — v3 sits on PLUSWIND, 2020",
                 fontsize=13, x=0.06, ha="left")
    plt.tight_layout()
    out = OUT_DIR / "v3_02_diurnal.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


def plot_monthly():
    monthly = allf.resample("MS").mean()
    fig, ax = plt.subplots(1, 1, figsize=(13, 5))
    ax.plot(monthly.index, monthly["pl"], color=C_PLUS, lw=2.4,
            label="PLUSWIND")
    ax.plot(monthly.index, monthly["v3"], color=C_V3, lw=2.0,
            label="physics_v3")
    ax.plot(monthly.index, monthly["v2"], color=C_V2, lw=1.4,
            ls="--", alpha=0.7, label="physics_v2")
    ax.plot(monthly.index, monthly["v1"], color=C_V1, lw=1.4,
            ls=":", alpha=0.7, label="physics_v1")
    ax.set_ylabel("Monthly mean wind (MW, 22-plant fleet)")
    ax.set_xlabel("Month, 2020")
    ax.set_title("Monthly mean — physics_v3 lies on PLUSWIND",
                 fontsize=11, loc="left")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    plt.tight_layout()
    out = OUT_DIR / "v3_03_monthly.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


def plot_scatter():
    panels = [
        (allf["pl"], allf["v1"], "v1: cubic curve only",            C_V1),
        (allf["pl"], allf["v2"], "v2: + density correction",        C_V2),
        (allf["pl"], allf["v3"], "v3: + SAM smooth curves",         C_V3),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5), sharex=True, sharey=True)
    lim_max = max(allf[["v1", "v2", "v3", "pl"]].max().max() * 1.05, 1.0)
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
                 f"bias   = {m['nbias']:+.2f}%\n"
                 f"nMAE   = {m['nmae']:.2f}%\n"
                 f"BC nMAE= {m['bc_nmae']:.2f}%"),
                transform=ax.transAxes, va="top", ha="left",
                fontsize=10, family="monospace",
                bbox=dict(boxstyle="round", fc="white", alpha=0.9))
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=9)
    plt.suptitle("Scatter — physics evolution, 2020",
                 fontsize=13, x=0.06, ha="left")
    plt.tight_layout()
    out = OUT_DIR / "v3_04_scatter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


def plot_curve_comparison():
    """Compare the three curve shapes (cubic v1, cubic v2, SAM v3) at a
    representative plant, plus the cloud of (HRRR WS, plant power) hours."""
    site = "wind_323574"  # Maple Ridge 1
    v1_p = pd.read_csv(WIND / f"wind_actual_1h_site_{YEAR}_utc.pluswind_v1.csv",
                       parse_dates=["Time"], index_col="Time")[site]
    v3_p = pd.read_csv(WIND / f"wind_actual_1h_site_{YEAR}_utc.pluswind_v3.csv",
                       parse_dates=["Time"], index_col="Time")[site]
    pl_p = pd.read_csv(WIND / f"wind_actual_1h_site_{YEAR}_utc.pluswind.csv",
                       parse_dates=["Time"], index_col="Time")[site]
    meta = pd.read_csv(WIND.parents[0] / "plant_metadata" / "wind_meta.csv")
    np_mw = float(meta.loc[meta["site_id"] == site, "nameplate_mw"].iloc[0])

    df = pd.concat([v1_p.rename("v1"), v3_p.rename("v3"),
                    pl_p.rename("pl")], axis=1).dropna()

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax = axes[0]
    ax.scatter(df["v1"], df["pl"], s=3, alpha=0.3, color=C_V1, rasterized=True,
               label="physics_v1 vs PLUSWIND")
    ax.plot([0, np_mw], [0, np_mw], "k--", lw=1, alpha=0.5, label="y = x")
    ax.set_xlabel(f"physics_v1 power (MW), {site}")
    ax.set_ylabel("PLUSWIND power (MW)")
    ax.set_title(f"v1 (cubic) vs PLUSWIND — {site}",
                 fontsize=11, loc="left")
    ax.set_xlim(0, np_mw * 1.05); ax.set_ylim(0, np_mw * 1.05)
    ax.grid(alpha=0.3); ax.legend(loc="lower right", fontsize=9)

    ax = axes[1]
    ax.scatter(df["v3"], df["pl"], s=3, alpha=0.3, color=C_V3, rasterized=True,
               label="physics_v3 vs PLUSWIND")
    ax.plot([0, np_mw], [0, np_mw], "k--", lw=1, alpha=0.5, label="y = x")
    ax.set_xlabel(f"physics_v3 power (MW), {site}")
    ax.set_ylabel("PLUSWIND power (MW)")
    ax.set_title(f"v3 (SAM + density) vs PLUSWIND — {site}",
                 fontsize=11, loc="left")
    ax.set_xlim(0, np_mw * 1.05); ax.set_ylim(0, np_mw * 1.05)
    ax.grid(alpha=0.3); ax.legend(loc="lower right", fontsize=9)
    plt.suptitle(
        f"Per-plant scatter (Maple Ridge): v3 collapses on y=x; v1 sat below it",
        fontsize=11, x=0.06, ha="left")
    plt.tight_layout()
    out = OUT_DIR / "v3_05_per_plant_scatter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


def plot_curves_overlay():
    """The actual power curves: cubic vs SAM, for two representative plants.
    This is the 'why v3 works' picture."""
    import sys
    sys.path.insert(0, str(WIND.parents[2] / "pgscen"))
    from utils.wind_physics import (
        build_sam_curves, rated_ws_from_specific_power,
        specific_power_per_plant, CUT_IN_MS, CUT_OUT_MS,
    )

    meta = pd.read_csv(WIND.parents[0] / "plant_metadata" / "wind_meta.csv")
    turb = pd.read_csv(WIND.parents[0] / "plant_metadata" / "uswtdb_ny_turbines.csv")
    sam_ws, sam_cf, sam_rs = build_sam_curves(meta, turb)
    sp = specific_power_per_plant(meta, turb)
    iec_rs = rated_ws_from_specific_power(sp)

    # Pick two plants: low-σ (modern) and high-σ (older)
    sites = ["wind_24146", "wind_323706"]  # Madison 2000, Stony Creek 2013
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, site in zip(axes, sites):
        i = meta.index[meta["site_id"] == site].item()
        rs_i = iec_rs[i]
        rs_sam = sam_rs[i]
        # Cubic curve
        ws = np.linspace(0, 25, 200)
        cubic = np.where(ws < CUT_IN_MS, 0,
                  np.where(ws < rs_i, ((ws - CUT_IN_MS) / (rs_i - CUT_IN_MS)) ** 3,
                  np.where(ws <= CUT_OUT_MS, 1.0, 0)))
        # SAM curve (interpolate to same grid)
        sam_at_ws = np.interp(ws, sam_ws, sam_cf[i], left=0, right=0)
        ax.plot(ws, cubic, color=C_V1, lw=2.0, ls=":",
                label=f"v1/v2 cubic (RS={rs_i:.1f})")
        ax.plot(ws, sam_at_ws, color=C_V3, lw=2.4,
                label=f"v3 SAM smooth (RS={rs_sam:.1f})")
        ax.set_xlim(0, 25); ax.set_ylim(0, 1.05)
        ax.set_xlabel("Wind speed (m/s)")
        ax.set_ylabel("Capacity factor")
        ax.set_title(f"{site}  σ={sp[i]:.0f} W/m²",
                     fontsize=11, loc="left")
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=9, framealpha=0.95)
        # Shade the partial-load region where the curves differ most
        ax.axvspan(5, 9, color="grey", alpha=0.06, zorder=0)
    plt.suptitle(
        "Power curves — cubic vs SAM. Grey band = partial-load region "
        "(5–9 m/s) where NY plants spend most operating hours.",
        fontsize=11, x=0.06, ha="left")
    plt.tight_layout()
    out = OUT_DIR / "v3_06_curve_shapes.png"
    plt.savefig(out, dpi=150, bbox_inches="tight"); plt.close()
    print(f"  wrote {out.name}")


print("Plotting...")
plot_two_weeks()
plot_diurnal()
plot_monthly()
plot_scatter()
plot_curve_comparison()
plot_curves_overlay()
print("done.")
