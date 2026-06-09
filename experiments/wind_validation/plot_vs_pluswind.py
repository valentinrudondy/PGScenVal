"""Plots that score the in-house HRRR pipelines (legacy + physics_v1) against
PLUSWIND on the 22-plant overlap, 2018-2021. PLUSWIND is the right target
for PGScen because it represents potential generation; downstream UC handles
curtailment.

Outputs (next to the script):
  vs_pluswind_01_two_weeks.png       — summer + winter week overlay, 2020
  vs_pluswind_02_diurnal.png         — mean by hour-of-day, summer/winter, 2020
  vs_pluswind_03_monthly.png         — monthly mean over 2018-2021
  vs_pluswind_04_scatter.png         — actual scatter, legacy vs physv1
  vs_pluswind_05_error_by_hour.png   — bias & MAE by hour of day, 2020
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
YEARS = [2018, 2019, 2020, 2021]

C_LEGACY = "#0e7490"   # teal
C_V1     = "#16a34a"   # green
C_PLUS   = "#7c3aed"   # violet — target
C_LEG_F  = "#7dd3fc"   # pale teal — legacy forecast
C_V1_F   = "#86efac"   # pale green — physv1 forecast


# ---------------------------------------------------------------------------
# Loaders — sum across the 22-plant overlap with PLUSWIND
# ---------------------------------------------------------------------------

def load_actual(suffix: str) -> pd.DataFrame:
    frames = []
    for y in YEARS:
        f = WIND / f"wind_actual_1h_site_{y}_utc{suffix}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        frames.append(df)
    return pd.concat(frames).sort_index()


def load_forecast(suffix: str, common: list[str]) -> pd.Series:
    frames = []
    for y in YEARS:
        f = WIND / f"wind_day_ahead_forecast_site_{y}_utc{suffix}.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Issue_time", "Forecast_time"])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    site_cols = [c for c in df.columns if c.startswith("wind_") and c in common]
    df["sys_mw"] = df[site_cols].sum(axis=1)
    s = df.set_index("Forecast_time")["sys_mw"].sort_index()
    if s.index.tz is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    return s


print("Loading...")
legacy_act = load_actual("")
v1_act     = load_actual(".pluswind_v1")
plus_act   = load_actual(".pluswind")

common = sorted(set(plus_act.columns)
                & set(legacy_act.columns)
                & set(v1_act.columns))
print(f"  common plants (PLUSWIND ∩ in-house): {len(common)}")

legacy = legacy_act[common].sum(axis=1).rename("legacy")
physv1 = v1_act[common].sum(axis=1).rename("physv1")
plus   = plus_act[common].sum(axis=1).rename("pluswind")

legacy_fc = load_forecast("", common).rename("legacy_fc")
physv1_fc = load_forecast(".pluswind_v1", common).rename("physv1_fc")

allf = pd.concat([legacy, physv1, plus, legacy_fc, physv1_fc], axis=1)
print(f"  joined frame: {allf.index.min()} → {allf.index.max()}  "
      f"({len(allf):,} h)")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def metrics(target: pd.Series, p: pd.Series) -> dict:
    df = pd.concat([target, p], axis=1).dropna()
    a = df.iloc[:, 0]; q = df.iloc[:, 1]
    e = q - a
    bias = float(e.mean()); mae = float(e.abs().mean())
    rmse = float(np.sqrt((e**2).mean()))
    am = float(a.mean()) if a.mean() > 0 else float("nan")
    bc_mae = float((e - bias).abs().mean())
    return {
        "n": len(df), "bias": bias, "mae": mae, "rmse": rmse,
        "nbias": 100 * bias / am, "nmae": 100 * mae / am,
        "bc_nmae": 100 * bc_mae / am, "amean": am,
    }


# ---------------------------------------------------------------------------
# Plot 1 — two-week overlay
# ---------------------------------------------------------------------------

def plot_two_weeks() -> None:
    weeks = [
        ("2020-07-13", "2020-07-19", "Summer week (Jul 13–19, 2020)"),
        ("2020-12-14", "2020-12-20", "Winter week (Dec 14–20, 2020)"),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)
    for ax, (start, end, title) in zip(axes, weeks):
        sub = allf.loc[start:f"{end} 23:59"]
        ax.plot(sub.index, sub["pluswind"], color=C_PLUS, lw=2.0,
                label="PLUSWIND (target)")
        ax.plot(sub.index, sub["legacy"], color=C_LEGACY, lw=1.4,
                label="HRRR (legacy)")
        ax.plot(sub.index, sub["physv1"], color=C_V1, lw=1.4,
                label="HRRR + physics_v1")
        ax.plot(sub.index, sub["legacy_fc"], color=C_LEG_F, lw=1.0,
                ls="--", label="legacy forecast")
        ax.plot(sub.index, sub["physv1_fc"], color=C_V1_F, lw=1.0,
                ls="--", label="physics_v1 forecast")
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_ylabel("Wind generation (MW, 22-plant fleet sum)")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.95)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    axes[1].set_xlabel("Time (UTC)")
    plt.suptitle(
        "In-house pipelines vs PLUSWIND target — 22 NY plants",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "vs_pluswind_01_two_weeks.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# Plot 2 — diurnal, summer/winter 2020
# ---------------------------------------------------------------------------

def plot_diurnal() -> None:
    yr = allf.loc["2020"].copy()
    yr["hour"] = yr.index.hour
    yr["month"] = yr.index.month
    seasons = [
        ("Summer (JJA 2020)", yr[yr["month"].isin([6, 7, 8])]),
        ("Winter (DJF 2020)", yr[yr["month"].isin([12, 1, 2])]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, (label, sub) in zip(axes, seasons):
        agg = sub.groupby("hour").mean(numeric_only=True)
        ax.plot(agg.index, agg["pluswind"], color=C_PLUS, lw=2.4,
                marker="o", ms=4, label="PLUSWIND (target)")
        ax.plot(agg.index, agg["legacy"], color=C_LEGACY, lw=2.0,
                marker="o", ms=4, label="HRRR (legacy)")
        ax.plot(agg.index, agg["physv1"], color=C_V1, lw=2.0,
                marker="o", ms=4, label="HRRR + physics_v1")
        ax.set_xlim(0, 23); ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("Hour of day (UTC)")
        ax.set_ylabel("Mean wind generation (MW)")
        ax.set_title(label, fontsize=11, loc="left")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    plt.suptitle(
        "Diurnal — in-house actuals vs PLUSWIND, 2020",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "vs_pluswind_02_diurnal.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# Plot 3 — monthly, full 2018-2021
# ---------------------------------------------------------------------------

def plot_monthly() -> None:
    cols = ["pluswind", "legacy", "physv1"]
    monthly = allf[cols].resample("MS").mean()
    fig, ax = plt.subplots(1, 1, figsize=(13, 5))
    ax.plot(monthly.index, monthly["pluswind"], color=C_PLUS, lw=2.0,
            label="PLUSWIND (target)")
    ax.plot(monthly.index, monthly["legacy"], color=C_LEGACY, lw=1.8,
            label="HRRR (legacy)")
    ax.plot(monthly.index, monthly["physv1"], color=C_V1, lw=1.8,
            label="HRRR + physics_v1")
    ax.set_ylabel("Monthly-mean wind (MW, 22-plant fleet sum)")
    ax.set_xlabel("Time (UTC)")
    ax.set_title(
        "Monthly mean — in-house pipelines vs PLUSWIND target, 2018-2021",
        fontsize=11, loc="left",
    )
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    out = OUT_DIR / "vs_pluswind_03_monthly.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# Plot 4 — scatter, 2020
# ---------------------------------------------------------------------------

def plot_scatter() -> None:
    yr = allf.loc["2020"].dropna()
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), sharex=True, sharey=True)
    panels = [
        (yr["pluswind"], yr["legacy"],
         "Legacy actual vs PLUSWIND", C_LEGACY),
        (yr["pluswind"], yr["physv1"],
         "physics_v1 actual vs PLUSWIND", C_V1),
    ]
    lim_max = max(yr[["pluswind", "legacy", "physv1"]].max().max() * 1.05,
                  1.0)
    for ax, (a, p, title, color) in zip(axes, panels):
        ax.scatter(a, p, s=3, alpha=0.25, color=color, rasterized=True)
        ax.plot([0, lim_max], [0, lim_max], "k--", lw=1, alpha=0.5,
                label="y = x")
        m = metrics(a, p)
        ax.set_xlabel("PLUSWIND (MW)")
        ax.set_ylabel("In-house pipeline (MW)")
        ax.set_xlim(0, lim_max); ax.set_ylim(0, lim_max)
        ax.set_title(title, fontsize=11, loc="left")
        ax.text(
            0.04, 0.96,
            (f"n      = {m['n']}\n"
             f"bias   = {m['bias']:+,.0f} MW ({m['nbias']:+.1f}%)\n"
             f"MAE    = {m['mae']:,.0f} MW\n"
             f"nMAE   = {m['nmae']:.1f}%\n"
             f"BC nMAE= {m['bc_nmae']:.1f}%"),
            transform=ax.transAxes, va="top", ha="left",
            fontsize=10, family="monospace",
            bbox=dict(boxstyle="round", fc="white", alpha=0.9),
        )
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=9)
    plt.suptitle(
        "Scatter — in-house pipelines vs PLUSWIND, 2020",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "vs_pluswind_04_scatter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# Plot 5 — error by hour of day, 2020
# ---------------------------------------------------------------------------

def plot_error_by_hour() -> None:
    yr = allf.loc["2020"].copy()
    yr["hour"] = yr.index.hour
    yr["leg_err"] = yr["legacy"] - yr["pluswind"]
    yr["v1_err"]  = yr["physv1"] - yr["pluswind"]

    bias = yr.groupby("hour")[["leg_err", "v1_err"]].mean()
    mae = yr.groupby("hour").apply(
        lambda g: pd.Series({
            "leg_mae": g["leg_err"].abs().mean(),
            "v1_mae":  g["v1_err"].abs().mean(),
        })
    )
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), sharex=True)
    ax1.axhline(0, color="k", lw=0.7)
    ax1.plot(bias.index, bias["leg_err"], color=C_LEGACY, lw=2.0,
             marker="o", ms=4, label="legacy − PLUSWIND")
    ax1.plot(bias.index, bias["v1_err"], color=C_V1, lw=2.0,
             marker="o", ms=4, label="physics_v1 − PLUSWIND")
    ax1.set_xlabel("Hour of day (UTC)")
    ax1.set_ylabel("Mean error (MW)")
    ax1.set_xticks(range(0, 24, 3))
    ax1.set_title("Bias by hour (2020)", fontsize=11, loc="left")
    ax1.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax1.grid(alpha=0.3)

    ax2.plot(mae.index, mae["leg_mae"], color=C_LEGACY, lw=2.0,
             marker="o", ms=4, label="legacy MAE")
    ax2.plot(mae.index, mae["v1_mae"], color=C_V1, lw=2.0,
             marker="o", ms=4, label="physics_v1 MAE")
    ax2.set_xlabel("Hour of day (UTC)")
    ax2.set_ylabel("MAE vs PLUSWIND (MW)")
    ax2.set_xticks(range(0, 24, 3))
    ax2.set_title("MAE by hour (2020)", fontsize=11, loc="left")
    ax2.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax2.grid(alpha=0.3)
    plt.tight_layout()
    out = OUT_DIR / "vs_pluswind_05_error_by_hour.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Plotting...")
    plot_two_weeks()
    plot_diurnal()
    plot_monthly()
    plot_scatter()
    plot_error_by_hour()
    print("done.")
