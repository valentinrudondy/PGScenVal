"""Steps 1–2 — Validation harness.

Compare the in-house HRRR-derived wind series (site-level actuals + day-ahead
forecast, from PGscen-2nd) AND the PLUSWIND-derived site-level series, both
summed to system, against NYISO's published system-wide wind total
(rtfuelmix, 5-min, system level).

PLUSWIND inputs are included automatically when present — if no
``wind_actual_1h_site_<year>_utc.pluswind.csv`` files exist, only the HRRR
baseline is reported.

Inputs
------
- PGscen-2nd/data/NYISO_real/wind/wind_actual_1h_site_<year>_utc.csv
- PGscen-2nd/data/NYISO_real/wind/wind_day_ahead_forecast_site_<year>_utc.csv
- PGscen-2nd/data/NYISO_real/wind/wind_actual_1h_site_<year>_utc.pluswind.csv
  (optional — produced by PGscen-2nd/scripts/09_build_pluswind_wide.py)
- data/nyiso_cache/<year>/fuel_mix/<yyyymm>/<yyyymmdd>rtfuelmix.csv
  (download with experiments/wind_validation/_download_rtfuelmix.py if missing)

Outputs
-------
experiments/wind_validation/wind_01_two_weeks.png
experiments/wind_validation/wind_02_diurnal.png
experiments/wind_validation/wind_03_monthly.png
experiments/wind_validation/wind_04_scatter.png
experiments/wind_validation/wind_05_error_by_hour.png
experiments/wind_validation/scorecard.csv
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(exist_ok=True)

WIND_DIR = PROJECT_ROOT / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
FUEL_MIX_DIR = PROJECT_ROOT / "data" / "nyiso_cache"

YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024]

# HRRR version transitions:
#   v2 → v3: 2018-07-12  (older, but our window starts 2018 so essentially v3)
#   v3 → v4: 2020-12-02
HRRR_V4_START = pd.Timestamp("2020-12-02")

C_HRRR_A = "#0e7490"   # teal: legacy HRRR actual
C_HRRR_F = "#7dd3fc"   # light blue: legacy HRRR forecast
C_NYISO  = "#d97706"   # orange: NYISO rtfuelmix system Wind
C_PLUS   = "#7c3aed"   # violet: PLUSWIND
C_V1     = "#16a34a"   # green: physics_v1 (in-house PLUSWIND-style)
C_V1F    = "#86efac"   # pale green: physics_v1 forecast


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_hrrr_actuals(years: list[int]) -> pd.Series:
    frames = []
    for y in years:
        f = WIND_DIR / f"wind_actual_1h_site_{y}_utc.csv"
        if not f.exists():
            print(f"  warn: missing {f.name}")
            continue
        df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
        frames.append(df)
    out = pd.concat(frames).sort_index()
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    return out.sum(axis=1).rename("hrrr_actual")


def load_physv1_actuals(years: list[int]) -> pd.Series | None:
    """Load in-house physics_v1 actuals (PLUSWIND recipe applied to HRRR)."""
    frames = []
    for y in years:
        f = WIND_DIR / f"wind_actual_1h_site_{y}_utc.pluswind_v1.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
        frames.append(df)
    if not frames:
        return None
    out = pd.concat(frames).sort_index()
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    return out.sum(axis=1).rename("physv1_actual")


def load_physv1_forecasts(years: list[int]) -> pd.Series | None:
    """Load in-house physics_v1 day-ahead forecasts."""
    frames = []
    for y in years:
        f = WIND_DIR / f"wind_day_ahead_forecast_site_{y}_utc.pluswind_v1.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Issue_time", "Forecast_time"])
        frames.append(df)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    site_cols = [c for c in df.columns if c.startswith("wind_")]
    df["sys_mw"] = df[site_cols].sum(axis=1)
    s = df.set_index("Forecast_time")["sys_mw"].sort_index()
    if s.index.tz is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    return s.rename("physv1_forecast")


def load_pluswind_actuals(years: list[int]) -> pd.Series | None:
    """Load PLUSWIND-derived site-level actuals (one wide CSV per year),
    sum across columns. Returns None if no files are present yet."""
    frames = []
    for y in years:
        f = WIND_DIR / f"wind_actual_1h_site_{y}_utc.pluswind.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f, parse_dates=["Time"], index_col="Time")
        frames.append(df)
    if not frames:
        return None
    out = pd.concat(frames).sort_index()
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    return out.sum(axis=1).rename("pluswind_actual")


def load_hrrr_forecasts(years: list[int]) -> pd.Series:
    frames = []
    for y in years:
        f = WIND_DIR / f"wind_day_ahead_forecast_site_{y}_utc.csv"
        if not f.exists():
            print(f"  warn: missing {f.name}")
            continue
        df = pd.read_csv(f, parse_dates=["Issue_time", "Forecast_time"])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    site_cols = [c for c in df.columns if c.startswith("wind_")]
    df["sys_mw"] = df[site_cols].sum(axis=1)
    s = df.set_index("Forecast_time")["sys_mw"].sort_index()
    if s.index.tz is not None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    return s.rename("hrrr_forecast")


def load_rtfuelmix_wind(years: list[int]) -> pd.Series:
    """Load the 'Wind' fuel category from rtfuelmix CSVs and resample to hourly
    UTC mean MW. NYISO timestamps are local time (EST/EDT, both winter clocks
    plus summer DST). The 'Time Zone' column distinguishes them."""
    frames = []
    for y in years:
        fm_year = FUEL_MIX_DIR / str(y) / "fuel_mix"
        if not fm_year.exists():
            print(f"  warn: no rtfuelmix cache for {y}")
            continue
        for csv in sorted(fm_year.rglob("*rtfuelmix.csv")):
            try:
                df = pd.read_csv(csv)
            except Exception as exc:
                print(f"  warn: could not read {csv.name}: {exc}")
                continue
            df = df[df["Fuel Category"] == "Wind"]
            if df.empty:
                continue
            # Localize naive timestamps with their published TZ. EST=UTC-5,
            # EDT=UTC-4. Use the offset directly to dodge DST ambiguities.
            ts = pd.to_datetime(df["Time Stamp"], errors="coerce")
            tz = df["Time Zone"].astype(str).str.upper()
            offset = np.where(tz == "EDT", 4, 5)  # hours to add to reach UTC
            utc = ts + pd.to_timedelta(offset, unit="h")
            sub = pd.DataFrame({"Time": utc, "mw": df["Gen MW"].astype(float)})
            sub = sub.dropna(subset=["Time"])
            frames.append(sub)
    if not frames:
        raise RuntimeError("No rtfuelmix data found in cache.")
    raw = pd.concat(frames).set_index("Time").sort_index()
    raw = raw[~raw.index.duplicated(keep="first")]
    # 5-min instantaneous MW → hourly average MW
    hourly = raw["mw"].resample("1h").mean()
    return hourly.rename("nyiso_actual")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def fleet_metrics(actual: pd.Series, predicted: pd.Series) -> dict:
    df = pd.concat([actual, predicted], axis=1).dropna()
    a = df.iloc[:, 0]
    p = df.iloc[:, 1]
    err = p - a
    bias = err.mean()
    mae = err.abs().mean()
    rmse = float(np.sqrt((err**2).mean()))
    a_mean = a.mean() if a.mean() > 0 else np.nan
    nmae = mae / a_mean
    nbias = bias / a_mean
    return {
        "n": int(len(df)),
        "bias_mw": float(bias),
        "mae_mw": float(mae),
        "rmse_mw": float(rmse),
        "nbias": float(nbias),
        "nmae": float(nmae),
        "actual_mean_mw": float(a_mean),
    }


def hrrr_version_label(idx: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(
        np.where(idx < HRRR_V4_START, "v3", "v4"), index=idx, name="hrrrv",
    )


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_two_weeks(allf: pd.DataFrame, has_pluswind: bool,
                   has_physv1: bool = False) -> None:
    """One summer week and one winter week. Use 2020 (PLUSWIND coverage) when
    PLUSWIND is available so all three series can be compared on the same
    week; otherwise use 2024 like the solar plots."""
    if has_pluswind:
        weeks = [
            ("2020-07-13", "2020-07-19", "Summer week (Jul 13–19, 2020)"),
            ("2020-12-14", "2020-12-20", "Winter week (Dec 14–20, 2020)"),
        ]
    else:
        weeks = [
            ("2024-07-15", "2024-07-21", "Summer week (Jul 15–21, 2024)"),
            ("2024-12-16", "2024-12-22", "Winter week (Dec 16–22, 2024)"),
        ]
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)
    for ax, (start, end, title) in zip(axes, weeks):
        sub = allf.loc[start:f"{end} 23:59"]
        ax.plot(sub.index, sub["nyiso_actual"], color=C_NYISO, lw=1.8,
                label="NYISO rtfuelmix Wind (system actual)")
        ax.plot(sub.index, sub["hrrr_actual"], color=C_HRRR_A, lw=1.4,
                label="HRRR (legacy) actual")
        if has_physv1 and "physv1_actual" in sub.columns:
            ax.plot(sub.index, sub["physv1_actual"], color=C_V1, lw=1.4,
                    label="HRRR + physics_v1 actual")
        if has_pluswind and "pluswind_actual" in sub.columns:
            ax.plot(sub.index, sub["pluswind_actual"], color=C_PLUS, lw=1.4,
                    label="PLUSWIND actual")
        ax.plot(sub.index, sub["hrrr_forecast"], color=C_HRRR_F, lw=1.2,
                ls="--", label="HRRR (legacy) forecast")
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_ylabel("Wind generation (MW, system)")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.95)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    axes[1].set_xlabel("Time (UTC)")
    plt.suptitle(
        "Wind — HRRR fleet sum vs NYISO rtfuelmix system total",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "wind_01_two_weeks.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_diurnal(allf: pd.DataFrame, has_pluswind: bool,
                 has_physv1: bool = False) -> None:
    base_year = "2020" if has_pluswind else "2024"
    yr = allf.loc[base_year].copy()
    yr["hour"] = yr.index.hour
    yr["month"] = yr.index.month
    seasons = [
        (f"Summer (JJA {base_year})", yr[yr["month"].isin([6, 7, 8])]),
        (f"Winter (DJF {base_year})", yr[yr["month"].isin([12, 1, 2])]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, (label, sub) in zip(axes, seasons):
        agg = sub.groupby("hour").mean(numeric_only=True)
        ax.plot(agg.index, agg["nyiso_actual"], color=C_NYISO, lw=2.4,
                marker="o", ms=4, label="NYISO actual")
        ax.plot(agg.index, agg["hrrr_actual"], color=C_HRRR_A, lw=2.0,
                marker="o", ms=4, label="HRRR (legacy)")
        if has_physv1 and "physv1_actual" in agg.columns:
            ax.plot(agg.index, agg["physv1_actual"], color=C_V1, lw=2.0,
                    marker="o", ms=4, label="HRRR + physics_v1")
        if has_pluswind and "pluswind_actual" in agg.columns:
            ax.plot(agg.index, agg["pluswind_actual"], color=C_PLUS, lw=2.0,
                    marker="o", ms=4, label="PLUSWIND")
        ax.plot(agg.index, agg["hrrr_forecast"], color=C_HRRR_F, lw=1.6,
                ls="--", marker="s", ms=3, label="HRRR (legacy) forecast")
        ax.set_xlim(0, 23)
        ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("Hour of day (UTC)")
        ax.set_ylabel("Mean wind generation (MW)")
        ax.set_title(label, fontsize=11, loc="left")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.95)
    plt.suptitle(
        f"Wind diurnal — HRRR{' / PLUSWIND' if has_pluswind else ''} "
        f"vs NYISO, {base_year}",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "wind_02_diurnal.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_monthly_aggregates(allf: pd.DataFrame, has_pluswind: bool,
                            has_physv1: bool = False) -> None:
    cols = ["nyiso_actual", "hrrr_actual", "hrrr_forecast"]
    if has_pluswind:
        cols.insert(2, "pluswind_actual")
    if has_physv1:
        cols.insert(2, "physv1_actual")
    monthly_mean = allf[cols].resample("MS").mean()

    fig, ax = plt.subplots(1, 1, figsize=(13, 5))
    ax.plot(monthly_mean.index, monthly_mean["nyiso_actual"],
            color=C_NYISO, lw=2.0, label="NYISO actual")
    ax.plot(monthly_mean.index, monthly_mean["hrrr_actual"],
            color=C_HRRR_A, lw=2.0, label="HRRR (legacy)")
    if has_physv1:
        ax.plot(monthly_mean.index, monthly_mean["physv1_actual"],
                color=C_V1, lw=2.0, label="HRRR + physics_v1")
    if has_pluswind:
        ax.plot(monthly_mean.index, monthly_mean["pluswind_actual"],
                color=C_PLUS, lw=2.0, label="PLUSWIND")
    ax.plot(monthly_mean.index, monthly_mean["hrrr_forecast"],
            color=C_HRRR_F, lw=1.6, ls="--", label="HRRR (legacy) forecast")
    # HRRR v3/v4 shading
    ax.axvspan(allf.index.min(), HRRR_V4_START, alpha=0.05, color="grey",
               label="HRRR v3")
    ax.set_ylabel("Monthly-mean wind (MW, system)")
    ax.set_xlabel("Time (UTC)")
    ax.set_title(
        "Monthly mean wind — HRRR fleet sum vs NYISO system total",
        fontsize=11, loc="left",
    )
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    out = OUT_DIR / "wind_03_monthly.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_scatter(allf: pd.DataFrame, has_pluswind: bool) -> None:
    base_year = "2020" if has_pluswind else "2024"
    yr = allf.loc[base_year].dropna()
    n_panels = 3 if has_pluswind else 2
    fig, axes = plt.subplots(1, n_panels, figsize=(6.5 * n_panels, 6),
                             sharex=True, sharey=True)
    if n_panels == 1:
        axes = [axes]

    panels = [
        (yr["nyiso_actual"], yr["hrrr_actual"],
         "Actuals: HRRR site-sum vs NYISO", C_HRRR_A),
    ]
    if has_pluswind:
        panels.append(
            (yr["nyiso_actual"], yr["pluswind_actual"],
             "Actuals: PLUSWIND site-sum vs NYISO", C_PLUS),
        )
    panels.append(
        (yr["nyiso_actual"], yr["hrrr_forecast"],
         "Forecast: HRRR day-ahead vs NYISO", C_HRRR_F),
    )
    cols = (["nyiso_actual", "hrrr_actual", "hrrr_forecast"]
            + (["pluswind_actual"] if has_pluswind else []))
    lim_max = max(yr[cols].max().max() * 1.05, 1.0)
    for ax, (a, p, title, color) in zip(axes, panels):
        ax.scatter(a, p, s=3, alpha=0.25, color=color, rasterized=True)
        ax.plot([0, lim_max], [0, lim_max], "k--", lw=1, alpha=0.5,
                label="y = x")
        m = fleet_metrics(a, p)
        ax.set_xlabel("NYISO actual (MW)")
        ax.set_ylabel("HRRR (MW)")
        ax.set_xlim(0, lim_max)
        ax.set_ylim(0, lim_max)
        ax.set_title(title, fontsize=11, loc="left")
        ax.text(
            0.04, 0.96,
            (f"n      = {m['n']}\n"
             f"bias   = {m['bias_mw']:+,.0f} MW\n"
             f"MAE    = {m['mae_mw']:,.0f} MW\n"
             f"RMSE   = {m['rmse_mw']:,.0f} MW\n"
             f"nMAE   = {m['nmae']:.1%}\n"
             f"nBias  = {m['nbias']:+.1%}"),
            transform=ax.transAxes, va="top", ha="left",
            fontsize=10, family="monospace",
            bbox=dict(boxstyle="round", fc="white", alpha=0.9),
        )
        ax.grid(alpha=0.3)
        ax.legend(loc="lower right", fontsize=9)
    plt.suptitle(
        f"Wind scatter — fleet sum vs NYISO rtfuelmix, {base_year}",
        fontsize=13, x=0.06, ha="left",
    )
    plt.tight_layout()
    out = OUT_DIR / "wind_04_scatter.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


def plot_error_by_hour(allf: pd.DataFrame, has_pluswind: bool) -> None:
    base_year = "2020" if has_pluswind else "2024"
    yr = allf.loc[base_year].copy()
    yr["hour"] = yr.index.hour
    yr["hrrr_act_err"]  = yr["hrrr_actual"]   - yr["nyiso_actual"]
    yr["hrrr_fcst_err"] = yr["hrrr_forecast"] - yr["nyiso_actual"]
    if has_pluswind:
        yr["plus_act_err"] = yr["pluswind_actual"] - yr["nyiso_actual"]

    cols = ["hrrr_act_err", "hrrr_fcst_err"] + (["plus_act_err"] if has_pluswind else [])
    bias = yr.groupby("hour")[cols].mean()

    def _mae(g):
        out = {
            "hrrr_act_mae":  g["hrrr_act_err"].abs().mean(),
            "hrrr_fcst_mae": g["hrrr_fcst_err"].abs().mean(),
        }
        if has_pluswind:
            out["plus_act_mae"] = g["plus_act_err"].abs().mean()
        return pd.Series(out)
    mae = yr.groupby("hour").apply(_mae)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), sharex=True)
    ax1.axhline(0, color="k", lw=0.7)
    ax1.plot(bias.index, bias["hrrr_act_err"], color=C_HRRR_A, lw=2.0,
             marker="o", ms=4, label="HRRR actual − NYISO")
    if has_pluswind:
        ax1.plot(bias.index, bias["plus_act_err"], color=C_PLUS, lw=2.0,
                 marker="o", ms=4, label="PLUSWIND actual − NYISO")
    ax1.plot(bias.index, bias["hrrr_fcst_err"], color=C_HRRR_F, lw=2.0,
             marker="o", ms=4, label="HRRR forecast − NYISO")
    ax1.set_xlabel("Hour of day (UTC)")
    ax1.set_ylabel("Mean error (MW)")
    ax1.set_xticks(range(0, 24, 3))
    ax1.set_title(f"Bias by hour ({base_year})", fontsize=11, loc="left")
    ax1.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax1.grid(alpha=0.3)

    ax2.plot(mae.index, mae["hrrr_act_mae"], color=C_HRRR_A, lw=2.0,
             marker="o", ms=4, label="HRRR actual MAE")
    if has_pluswind:
        ax2.plot(mae.index, mae["plus_act_mae"], color=C_PLUS, lw=2.0,
                 marker="o", ms=4, label="PLUSWIND actual MAE")
    ax2.plot(mae.index, mae["hrrr_fcst_mae"], color=C_HRRR_F, lw=2.0,
             marker="o", ms=4, label="HRRR forecast MAE")
    ax2.set_xlabel("Hour of day (UTC)")
    ax2.set_ylabel("MAE (MW)")
    ax2.set_xticks(range(0, 24, 3))
    ax2.set_title(f"MAE by hour ({base_year})", fontsize=11, loc="left")
    ax2.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax2.grid(alpha=0.3)
    plt.tight_layout()
    out = OUT_DIR / "wind_05_error_by_hour.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  wrote {out.name}")


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

def build_scorecard(allf: pd.DataFrame, has_pluswind: bool) -> pd.DataFrame:
    rows = []
    for year, sub in allf.groupby(allf.index.year):
        for split, mask in [
            ("all",          slice(None)),
            ("HRRR_v3",      sub.index < HRRR_V4_START),
            ("HRRR_v4",      sub.index >= HRRR_V4_START),
        ]:
            s = sub.loc[mask] if not isinstance(mask, slice) else sub
            if s.empty:
                continue
            series_to_score = [
                ("hrrr_actual",   s["hrrr_actual"]),
                ("hrrr_forecast", s["hrrr_forecast"]),
            ]
            if has_pluswind and "pluswind_actual" in s.columns:
                series_to_score.append(("pluswind_actual", s["pluswind_actual"]))
            if "physv1_actual" in s.columns:
                series_to_score.append(("physv1_actual", s["physv1_actual"]))
            if "physv1_forecast" in s.columns:
                series_to_score.append(("physv1_forecast", s["physv1_forecast"]))
            for label, pred in series_to_score:
                if pred.dropna().empty:
                    continue
                m = fleet_metrics(s["nyiso_actual"], pred)
                rows.append({"year": year, "split": split,
                             "series": label, **m})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Loading HRRR site-level series ...")
    hrrr_act = load_hrrr_actuals(YEARS)
    hrrr_fct = load_hrrr_forecasts(YEARS)
    print(f"  HRRR actual:   {hrrr_act.index.min()} → {hrrr_act.index.max()}"
          f"  ({len(hrrr_act):,} h)")
    print(f"  HRRR forecast: {hrrr_fct.index.min()} → {hrrr_fct.index.max()}"
          f"  ({len(hrrr_fct):,} h)")

    print("Loading PLUSWIND site-level series (if present) ...")
    pluswind = load_pluswind_actuals(YEARS)
    has_pluswind = pluswind is not None
    if has_pluswind:
        print(f"  PLUSWIND:    {pluswind.index.min()} → {pluswind.index.max()}"
              f"  ({len(pluswind):,} h)")
    else:
        print("  PLUSWIND files not found.")

    print("Loading physics_v1 series (if present) ...")
    physv1 = load_physv1_actuals(YEARS)
    physv1_fct = load_physv1_forecasts(YEARS)
    has_physv1 = physv1 is not None
    if has_physv1:
        print(f"  physics_v1 actual:   {physv1.index.min()} → "
              f"{physv1.index.max()}  ({len(physv1):,} h)")
        if physv1_fct is not None:
            print(f"  physics_v1 forecast: {physv1_fct.index.min()} → "
                  f"{physv1_fct.index.max()}  ({len(physv1_fct):,} h)")
    else:
        print("  physics_v1 files not found.")

    print("Loading NYISO rtfuelmix Wind ...")
    nyiso = load_rtfuelmix_wind(YEARS)
    print(f"  NYISO actual:  {nyiso.index.min()} → {nyiso.index.max()}"
          f"  ({len(nyiso):,} h)")

    parts = [hrrr_act, hrrr_fct, nyiso]
    if has_pluswind:
        parts.append(pluswind)
    if has_physv1:
        parts.append(physv1)
        if physv1_fct is not None:
            parts.append(physv1_fct)
    allf = pd.concat(parts, axis=1)
    allf = allf.dropna(subset=["nyiso_actual"])  # require ground truth

    print(f"Joined frame: {allf.index.min()} → {allf.index.max()}"
          f"  ({len(allf):,} h, {allf.dropna().shape[0]:,} fully populated)")

    print("Plotting ...")
    plot_two_weeks(allf, has_pluswind, has_physv1)
    plot_diurnal(allf, has_pluswind, has_physv1)
    plot_monthly_aggregates(allf, has_pluswind, has_physv1)
    plot_scatter(allf, has_pluswind)
    plot_error_by_hour(allf, has_pluswind)

    print("Scorecard ...")
    sc = build_scorecard(allf, has_pluswind)
    out = OUT_DIR / "scorecard.csv"
    sc.to_csv(out, index=False)
    print(f"  wrote {out.name}")
    with pd.option_context("display.max_rows", None, "display.width", 140):
        cols = ["year", "split", "series", "n", "actual_mean_mw",
                "bias_mw", "mae_mw", "rmse_mw", "nbias", "nmae"]
        print(sc[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
