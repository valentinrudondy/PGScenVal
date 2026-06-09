"""Option E — single multiplicative scaling of physics_v1 to match PLUSWIND.

Computes one number from the 2018-2021 overlap on the 22-NY-plant intersection:

    scale = mean(PLUSWIND) / mean(physics_v1)

Applies it everywhere. Reports the new scorecard and refreshes the
vs-PLUSWIND comparison plots so the new (scaled) curves are visible alongside
the unscaled physics_v1 and PLUSWIND.
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

C_LEGACY = "#0e7490"
C_V1     = "#16a34a"
C_V1_E   = "#ca8a04"   # gold — physics_v1 × E scaling
C_PLUS   = "#7c3aed"


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


def metrics(target: pd.Series, p: pd.Series) -> dict:
    df = pd.concat([target, p], axis=1).dropna()
    a, q = df.iloc[:, 0], df.iloc[:, 1]
    e = q - a
    bias, mae = float(e.mean()), float(e.abs().mean())
    am = float(a.mean()) if a.mean() > 0 else float("nan")
    bc_mae = float((e - bias).abs().mean())
    return {
        "n": len(df),
        "nbias": 100 * bias / am,
        "nmae": 100 * mae / am,
        "bc_nmae": 100 * bc_mae / am,
        "amean": am,
    }


print("Loading 2018-2021 actuals on the 22-plant overlap...")
legacy_act = load_actual("")
v1_act     = load_actual(".pluswind_v1")
plus_act   = load_actual(".pluswind")

common = sorted(set(plus_act.columns)
                & set(legacy_act.columns)
                & set(v1_act.columns))
print(f"  common plants: {len(common)}")

legacy = legacy_act[common].sum(axis=1).rename("legacy")
physv1 = v1_act[common].sum(axis=1).rename("physv1")
plus   = plus_act[common].sum(axis=1).rename("pluswind")

allf = pd.concat([legacy, physv1, plus], axis=1).dropna()
print(f"  joined: {len(allf):,} h")

# --- Compute the scaling factor and additive offset on 2018-2021 ----------
scale_E = float(plus.dropna().mean() / physv1.dropna().mean())
offset_E = float(plus.dropna().mean() - physv1.dropna().mean())  # MW
allf["physv1_E"]      = allf["physv1"] * scale_E      # Option E (multiplicative)
allf["physv1_Eprime"] = (allf["physv1"] + offset_E).clip(lower=0)  # Option E' (additive)
print()
print(f"Option E  (multiplicative) = mean(PLUS) / mean(v1) = {scale_E:.4f}")
print(f"Option E' (additive)       = mean(PLUS) − mean(v1) = +{offset_E:.1f} MW")
print(f"  mean(PLUSWIND)   = {plus.dropna().mean():.1f} MW")
print(f"  mean(physics_v1) = {physv1.dropna().mean():.1f} MW")

# --- Scorecard --------------------------------------------------------------
print()
print("=" * 80)
print("Vs PLUSWIND on the 22-plant overlap, 2018-2021")
print("=" * 80)
print(f"{'year':>6}  {'series':>14} | {'n':>6} {'bias%':>7} {'nMAE%':>7} "
      f"{'BC nMAE%':>9}")
for label, col in [("legacy", "legacy"), ("physics_v1", "physv1"),
                   ("physics_v1 × E", "physv1_E"),
                   ("physics_v1 + E'", "physv1_Eprime")]:
    for y in YEARS:
        sub = allf.loc[str(y)]
        m = metrics(sub["pluswind"], sub[col])
        print(f"{y:>6}  {label:>14} | {m['n']:>6} {m['nbias']:>6.1f}% "
              f"{m['nmae']:>6.1f}% {m['bc_nmae']:>8.1f}%")
    m = metrics(allf["pluswind"], allf[col])
    print(f"  pool  {label:>14} | {m['n']:>6} {m['nbias']:>6.1f}% "
          f"{m['nmae']:>6.1f}% {m['bc_nmae']:>8.1f}%")
    print("-" * 60)

# --- Plots ------------------------------------------------------------------
print()
print("Plotting comparison (option_E_*.png) ...")


def plot_two_weeks():
    weeks = [
        ("2020-07-13", "2020-07-19", "Summer week (Jul 13–19, 2020)"),
        ("2020-12-14", "2020-12-20", "Winter week (Dec 14–20, 2020)"),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)
    for ax, (start, end, title) in zip(axes, weeks):
        sub = allf.loc[start:f"{end} 23:59"]
        ax.plot(sub.index, sub["pluswind"], color=C_PLUS, lw=2.0,
                label="PLUSWIND (target)")
        ax.plot(sub.index, sub["physv1"], color=C_V1, lw=1.4,
                label="physics_v1 (raw)")
        ax.plot(sub.index, sub["physv1_E"], color=C_V1_E, lw=1.4,
                ls="--",
                label=f"physics_v1 × {scale_E:.3f} (Option E)")
        ax.plot(sub.index, sub["physv1_Eprime"], color="#dc2626", lw=1.6,
                label=f"physics_v1 + {offset_E:.0f} MW (Option E')")
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_ylabel("Wind generation (MW, 22-plant fleet)")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    axes[1].set_xlabel("Time (UTC)")
    plt.suptitle(
        f"Option E — physics_v1 × {scale_E:.3f} vs PLUSWIND target",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "option_E_01_two_weeks.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_diurnal():
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
        ax.plot(agg.index, agg["physv1"], color=C_V1, lw=2.0,
                marker="o", ms=4, label="physics_v1 (raw)")
        ax.plot(agg.index, agg["physv1_E"], color=C_V1_E, lw=1.8, ls="--",
                marker="s", ms=3, label=f"physics_v1 × {scale_E:.3f} (E)")
        ax.plot(agg.index, agg["physv1_Eprime"], color="#dc2626", lw=2.0,
                marker="o", ms=4,
                label=f"physics_v1 + {offset_E:.0f} MW (E')")
        ax.set_xlim(0, 23); ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("Hour of day (UTC)")
        ax.set_ylabel("Mean wind generation (MW)")
        ax.set_title(label, fontsize=11, loc="left")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    plt.suptitle(
        f"Option E diurnal — 2020. Scale factor {scale_E:.3f}",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "option_E_02_diurnal.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_monthly():
    monthly = allf[["pluswind", "physv1", "physv1_E",
                    "physv1_Eprime"]].resample("MS").mean()
    fig, ax = plt.subplots(1, 1, figsize=(13, 5))
    ax.plot(monthly.index, monthly["pluswind"], color=C_PLUS, lw=2.0,
            label="PLUSWIND (target)")
    ax.plot(monthly.index, monthly["physv1"], color=C_V1, lw=1.8,
            label="physics_v1 (raw)")
    ax.plot(monthly.index, monthly["physv1_E"], color=C_V1_E, lw=1.6,
            ls="--", label=f"physics_v1 × {scale_E:.3f} (E)")
    ax.plot(monthly.index, monthly["physv1_Eprime"], color="#dc2626",
            lw=1.8, label=f"physics_v1 + {offset_E:.0f} MW (E')")
    ax.set_ylabel("Monthly-mean wind (MW, 22-plant fleet)")
    ax.set_xlabel("Time (UTC)")
    ax.set_title(
        f"Option E monthly — physics_v1 × {scale_E:.3f} vs PLUSWIND, 2018-2021",
        fontsize=11, loc="left",
    )
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    out = OUT_DIR / "option_E_03_monthly.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_scatter():
    yr = allf.loc["2020"].dropna()
    panels = [
        (yr["pluswind"], yr["physv1"],
         "physics_v1 (raw)", C_V1),
        (yr["pluswind"], yr["physv1_E"],
         f"× {scale_E:.3f} (Option E, multiplicative)", C_V1_E),
        (yr["pluswind"], yr["physv1_Eprime"],
         f"+ {offset_E:.0f} MW (Option E', additive)", "#dc2626"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5),
                             sharex=True, sharey=True)
    lim_max = max(yr[["pluswind", "physv1", "physv1_E",
                      "physv1_Eprime"]].max().max() * 1.05, 1.0)
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
             f"bias   = {m['nbias']:+.1f}%\n"
             f"nMAE   = {m['nmae']:.1f}%\n"
             f"BC nMAE= {m['bc_nmae']:.1f}%"),
            transform=ax.transAxes, va="top", ha="left",
            fontsize=10, family="monospace",
            bbox=dict(boxstyle="round", fc="white", alpha=0.9),
        )
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=9)
    plt.suptitle(
        "Option E scatter — 2020",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "option_E_04_scatter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


plot_two_weeks()
plot_diurnal()
plot_monthly()
plot_scatter()
print("done.")
