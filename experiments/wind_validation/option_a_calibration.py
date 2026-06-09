"""Option A — per-(month, hour-of-day) additive calibration of physics_v1
to PLUSWIND.

Switched from the multiplicative form in the design doc to additive after
the Option E run showed the gap to PLUSWIND is dominated by a constant
~106 MW offset, not a proportional scaling.

Recipe
------
1. On the 2018-2021 overlap (where both PLUSWIND and physics_v1 exist),
   bin both fleet-sum series by (month-of-year, hour-of-day) — 12 × 24 = 288
   bins. In each bin, compute:
       offset[m, h] = mean(PLUSWIND[m, h]) − mean(physics_v1[m, h])     (MW)
2. Apply forward to every hour of every year in [2018, 2024]:
       physv1_calA[t] = physv1[t] + offset[month(t), hour(t)]
3. For per-plant output, distribute the (m, h) offset proportionally to
   each plant's nameplate share of the active fleet at that hour, then clip
   each plant to [0, nameplate_mw].

Outputs
-------
- experiments/wind_validation/option_A_*.png         — comparison plots
- experiments/wind_validation/option_A_offsets.csv   — the 288-row table
- PGscen-2nd/data/NYISO_real/wind/wind_actual_1h_site_<year>_utc.pluswind_v1_calA.csv
- PGscen-2nd/data/NYISO_real/wind/wind_day_ahead_forecast_site_<year>_utc.pluswind_v1_calA.csv

Calibration is fit on actuals (physics_v1 actuals vs PLUSWIND actuals) and
applied to BOTH actuals and forecasts. Forecasts already have MOS bias
correction; this layer corrects the residual physics_v1 → PLUSWIND gap.
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
FIT_YEARS = [2018, 2019, 2020, 2021]
APPLY_YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024]

C_LEGACY = "#0e7490"
C_V1     = "#16a34a"
C_V1_E   = "#dc2626"   # red — Option E' (constant +106 MW)
C_V1_A   = "#ca8a04"   # gold — Option A
C_PLUS   = "#7c3aed"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_actual_wide(year: int, suffix: str) -> pd.DataFrame | None:
    f = WIND / f"wind_actual_1h_site_{year}_utc{suffix}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def load_forecast_wide(year: int, suffix: str) -> pd.DataFrame | None:
    f = WIND / f"wind_day_ahead_forecast_site_{year}_utc{suffix}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, parse_dates=["Issue_time", "Forecast_time"])
    return df


def metrics(target: pd.Series, p: pd.Series) -> dict:
    df = pd.concat([target, p], axis=1).dropna()
    a, q = df.iloc[:, 0], df.iloc[:, 1]
    e = q - a
    bias, mae = float(e.mean()), float(e.abs().mean())
    am = float(a.mean()) if a.mean() > 0 else float("nan")
    bc_mae = float((e - bias).abs().mean())
    return {
        "n": len(df), "nbias": 100 * bias / am, "nmae": 100 * mae / am,
        "bc_nmae": 100 * bc_mae / am,
    }


# ---------------------------------------------------------------------------
# Fit calibration on 2018-2021
# ---------------------------------------------------------------------------

print("Loading FIT period actuals on the 22-plant overlap...")
fit_v1 = pd.concat([load_actual_wide(y, ".pluswind_v1") for y in FIT_YEARS]).sort_index()
fit_pl = pd.concat([load_actual_wide(y, ".pluswind") for y in FIT_YEARS]).sort_index()
common = sorted(set(fit_v1.columns) & set(fit_pl.columns))
print(f"  common plants: {len(common)}")

fit_v1_sys = fit_v1[common].sum(axis=1)
fit_pl_sys = fit_pl[common].sum(axis=1)
fit = pd.concat([fit_v1_sys.rename("v1"), fit_pl_sys.rename("pl")],
                axis=1).dropna()
fit["month"] = fit.index.month
fit["hour"]  = fit.index.hour

offsets = (fit.groupby(["month", "hour"])
           .apply(lambda g: g["pl"].mean() - g["v1"].mean()))
offsets.name = "offset_mw"
print(f"\nFitted {len(offsets)} per-(month, hour) offsets:")
print(f"  mean   {offsets.mean():+.1f} MW")
print(f"  median {offsets.median():+.1f} MW")
print(f"  range  [{offsets.min():+.1f}, {offsets.max():+.1f}] MW")
print(f"  std    {offsets.std():.1f} MW (across 288 bins)")

# Save the offset table for documentation
offsets_df = offsets.reset_index()
offsets_df.to_csv(OUT_DIR / "option_A_offsets.csv", index=False)
print(f"  saved offset table → option_A_offsets.csv")


# ---------------------------------------------------------------------------
# Apply calibration: write per-plant calibrated actuals + forecasts
# ---------------------------------------------------------------------------

meta = pd.read_csv(META)
plant_nameplate = dict(zip(meta["site_id"].astype(str),
                            meta["nameplate_mw"].astype(float)))


def apply_calibration_to_wide(df: pd.DataFrame, time_col: str | None
                              ) -> pd.DataFrame:
    """Add per-(month, hour) offset to a wide CSV, distributed proportionally
    to per-plant nameplate. Clip each plant to [0, nameplate]. ``time_col``
    is None for actuals (use the index) or 'Forecast_time' for forecasts."""
    out = df.copy()
    if time_col is None:
        ts = out.index
    else:
        ts = pd.to_datetime(out[time_col], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
    months = ts.month if time_col is None else ts.dt.month
    hours = ts.hour if time_col is None else ts.dt.hour
    mh_offset = pd.Series(
        [offsets.loc[(int(m), int(h))] for m, h in zip(months, hours)],
        index=out.index, name="offset_mw",
    )
    site_cols = [c for c in out.columns
                 if c not in ("Issue_time", "Forecast_time")
                 and c.startswith("wind_")]
    # Sum nameplate across plants present in this file
    np_sum = sum(plant_nameplate.get(c, 0.0) for c in site_cols)
    if np_sum <= 0:
        return out
    for c in site_cols:
        share = plant_nameplate.get(c, 0.0) / np_sum
        out[c] = (out[c] + share * mh_offset).clip(lower=0.0,
                                                   upper=plant_nameplate.get(c))
    return out


print("\nWriting calibrated CSVs...")
for y in APPLY_YEARS:
    # Actuals
    src = load_actual_wide(y, ".pluswind_v1")
    if src is not None:
        out = apply_calibration_to_wide(src, time_col=None)
        path = WIND / f"wind_actual_1h_site_{y}_utc.pluswind_v1_calA.csv"
        out.to_csv(path)
        print(f"  wrote {path.name}")
    # Forecasts
    src = load_forecast_wide(y, ".pluswind_v1")
    if src is not None:
        out = apply_calibration_to_wide(src, time_col="Forecast_time")
        path = WIND / f"wind_day_ahead_forecast_site_{y}_utc.pluswind_v1_calA.csv"
        out.to_csv(path, index=False)
        print(f"  wrote {path.name}")


# ---------------------------------------------------------------------------
# Score: legacy / physv1 / physv1+106 (E') / physv1+A on 2018-2021
# ---------------------------------------------------------------------------

print("\nLoading all series for scoring...")
legacy_act = pd.concat([load_actual_wide(y, "") for y in FIT_YEARS]).sort_index()
v1_act     = fit_v1
plus_act   = fit_pl
calA_act   = pd.concat([load_actual_wide(y, ".pluswind_v1_calA")
                        for y in FIT_YEARS]).sort_index()

legacy = legacy_act[common].sum(axis=1).rename("legacy")
physv1 = v1_act[common].sum(axis=1).rename("physv1")
plus   = plus_act[common].sum(axis=1).rename("pluswind")
calA   = calA_act[common].sum(axis=1).rename("calA")

const_offset = float(plus.dropna().mean() - physv1.dropna().mean())
calE_prime = (physv1 + const_offset).clip(lower=0).rename("calEprime")

allf = pd.concat([legacy, physv1, calE_prime, calA, plus], axis=1).dropna()
print(f"  joined: {len(allf):,} h")

print()
print("=" * 80)
print("Vs PLUSWIND on 22-plant overlap, 2018-2021")
print("=" * 80)
print(f"{'year':>6}  {'series':>22} | {'n':>6} {'bias%':>7} {'nMAE%':>7} "
      f"{'BC nMAE%':>9}")
for label, col in [("legacy",                "legacy"),
                   ("physics_v1 (raw)",      "physv1"),
                   ("physics_v1 + 106 MW (E')", "calEprime"),
                   ("physics_v1 + A (per-m,h)", "calA")]:
    for y in FIT_YEARS:
        sub = allf.loc[str(y)]
        m = metrics(sub["pluswind"], sub[col])
        print(f"{y:>6}  {label:>22} | {m['n']:>6} {m['nbias']:>6.1f}% "
              f"{m['nmae']:>6.1f}% {m['bc_nmae']:>8.1f}%")
    m = metrics(allf["pluswind"], allf[col])
    print(f"  pool  {label:>22} | {m['n']:>6} {m['nbias']:>6.1f}% "
          f"{m['nmae']:>6.1f}% {m['bc_nmae']:>8.1f}%")
    print("-" * 70)


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

print("\nPlotting (option_A_*.png)...")


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
        ax.plot(sub.index, sub["physv1"], color=C_V1, lw=1.2,
                label="physics_v1 (raw)")
        ax.plot(sub.index, sub["calEprime"], color=C_V1_E, lw=1.4, ls="--",
                label=f"+ {const_offset:.0f} MW (Option E')")
        ax.plot(sub.index, sub["calA"], color=C_V1_A, lw=1.6,
                label="+ per-(m, h) offset (Option A)")
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_ylabel("Wind generation (MW, 22-plant fleet)")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    axes[1].set_xlabel("Time (UTC)")
    plt.suptitle(
        "Option A — per-(month, hour) additive calibration",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "option_A_01_two_weeks.png"
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
        ax.plot(agg.index, agg["physv1"], color=C_V1, lw=1.6,
                marker="o", ms=4, label="physics_v1 (raw)")
        ax.plot(agg.index, agg["calEprime"], color=C_V1_E, lw=1.6,
                marker="s", ms=3, ls="--", label="+ 106 MW (E')")
        ax.plot(agg.index, agg["calA"], color=C_V1_A, lw=2.0,
                marker="o", ms=4, label="+ per-(m, h) (A)")
        ax.set_xlim(0, 23); ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("Hour of day (UTC)")
        ax.set_ylabel("Mean wind generation (MW)")
        ax.set_title(label, fontsize=11, loc="left")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    plt.suptitle(
        "Option A diurnal — 2020 — per-(month, hour) calibration",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "option_A_02_diurnal.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_monthly():
    monthly = allf[["pluswind", "physv1", "calEprime", "calA"]].resample("MS").mean()
    fig, ax = plt.subplots(1, 1, figsize=(13, 5))
    ax.plot(monthly.index, monthly["pluswind"], color=C_PLUS, lw=2.0,
            label="PLUSWIND (target)")
    ax.plot(monthly.index, monthly["physv1"], color=C_V1, lw=1.4,
            label="physics_v1 (raw)")
    ax.plot(monthly.index, monthly["calEprime"], color=C_V1_E, lw=1.4,
            ls="--", label=f"+ {const_offset:.0f} MW (E')")
    ax.plot(monthly.index, monthly["calA"], color=C_V1_A, lw=1.8,
            label="+ per-(m, h) (A)")
    ax.set_ylabel("Monthly-mean wind (MW, 22-plant fleet)")
    ax.set_xlabel("Time (UTC)")
    ax.set_title(
        "Option A monthly — fit on 2018-2021, applied 2018-2024",
        fontsize=11, loc="left",
    )
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    out = OUT_DIR / "option_A_03_monthly.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_scatter():
    yr = allf.loc["2020"].dropna()
    panels = [
        (yr["pluswind"], yr["physv1"],     "physics_v1 (raw)",       C_V1),
        (yr["pluswind"], yr["calEprime"],  f"+ {const_offset:.0f} MW (E')",  C_V1_E),
        (yr["pluswind"], yr["calA"],       "+ per-(m, h) offset (A)", C_V1_A),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5), sharex=True, sharey=True)
    lim_max = max(yr[["pluswind", "physv1", "calEprime", "calA"]
                     ].max().max() * 1.05, 1.0)
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
    plt.suptitle("Option A scatter — 2020", fontsize=13, x=0.06, ha="left")
    plt.tight_layout()
    out = OUT_DIR / "option_A_04_scatter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_offset_heatmap():
    table = offsets.unstack("hour")
    fig, ax = plt.subplots(1, 1, figsize=(10, 5))
    im = ax.imshow(table.values, aspect="auto", cmap="RdBu_r",
                   vmin=-abs(table.values).max(),
                   vmax=abs(table.values).max())
    ax.set_xticks(range(0, 24, 3))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 3)])
    ax.set_yticks(range(12))
    ax.set_yticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_xlabel("Hour of day (UTC)")
    ax.set_ylabel("Month")
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("PLUSWIND − physics_v1  (MW, fleet sum)")
    ax.set_title(
        "Option A — fitted per-(month, hour) additive offsets",
        fontsize=11, loc="left",
    )
    # Annotate cells
    for m in range(12):
        for h in range(24):
            v = table.iloc[m, h]
            ax.text(h, m, f"{int(round(v))}", ha="center", va="center",
                    fontsize=6,
                    color="white" if abs(v) > 80 else "black")
    plt.tight_layout()
    out = OUT_DIR / "option_A_05_offset_heatmap.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


plot_two_weeks()
plot_diurnal()
plot_monthly()
plot_scatter()
plot_offset_heatmap()
print("done.")
