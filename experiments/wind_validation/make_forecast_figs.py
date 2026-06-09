"""Day-ahead forecast figures for the wind doc (production pluswind_v4).

Writes three figures into docs/figures/wind_v3/ and prints the fleet-aggregate
skill table (raw / in-sample MOS / rolling-window MOS) used in the forecast
section:

  forecast_fleet_2023.png    fleet actual vs raw vs rolling-MOS, two ET weeks
  forecast_diurnal_2023.png  mean diurnal by season (ET hour)
  forecast_scatter_2023.png  hexbin actual-vs-forecast, raw (left) / MOS (right)

All time axes are US/Eastern (the ET output convention). Skill is normalised to
fleet nameplate, matching the forecast-skill table in the document.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from et_plot import to_et, HOUR_ET  # noqa: E402  (all wind output in US/Eastern)

REPO = HERE.parents[1]
WIND = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
META = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "plant_metadata" / "wind_meta.csv"
FIG = REPO / "docs" / "figures" / "wind_v3"
YEAR = 2023
VAR = "pluswind_v4"

C_ACT, C_RAW, C_MOS = "#111111", "#e67e22", "#1d4ed8"


def _read_actual():
    d = pd.read_csv(WIND / f"wind_actual_1h_site_{YEAR}_utc.{VAR}.csv",
                    parse_dates=["Time"], index_col="Time")
    d.index = pd.to_datetime(d.index, utc=True)
    return d


def _read_forecast(path):
    d = pd.read_csv(path, parse_dates=["Forecast_time"])
    if "Issue_time" in d.columns:
        d = d.drop(columns="Issue_time")
    d = d.drop_duplicates("Forecast_time").set_index("Forecast_time")
    d.index = pd.to_datetime(d.index, utc=True)
    return d


def _skill(act_sum, fc_sum, cap):
    e = (fc_sum - act_sum).dropna()
    bias, mae = e.mean(), e.abs().mean()
    rmse = np.sqrt((e ** 2).mean())
    return (100 * bias / cap, 100 * mae / cap, 100 * rmse / cap)


def main():
    act = _read_actual()
    raw = _read_forecast(WIND / f"wind_day_ahead_forecast_site_{YEAR}_utc.{VAR}.csv.raw_backup")
    insamp = _read_forecast(WIND / f"wind_day_ahead_forecast_site_{YEAR}_utc.{VAR}.csv")
    roll = _read_forecast(WIND / f"wind_day_ahead_forecast_site_{YEAR}_utc.{VAR}.rolling.csv")

    sites = sorted(set(act.columns) & set(raw.columns) & set(insamp.columns)
                   & set(roll.columns))
    meta = pd.read_csv(META).set_index("site_id")
    cap = float(meta.loc[[s for s in sites if s in meta.index], "nameplate_mw"].sum())

    idx = act.index
    for f in (raw, insamp, roll):
        idx = idx.intersection(f.index)
    a = act.loc[idx, sites]
    a_sum = a.sum(axis=1)
    raw_sum = raw.loc[idx, sites].sum(axis=1)
    ins_sum = insamp.loc[idx, sites].sum(axis=1)
    roll_sum = roll.loc[idx, sites].sum(axis=1)

    print("=" * 64)
    print(f"FORECAST SKILL {YEAR} ({VAR}) — fleet aggregate, % of nameplate")
    print(f"  plants={len(sites)}  fleet_cap={cap:.0f} MW  hours={len(idx)}")
    print(f"  {'variant':<28}{'bias%':>8}{'nMAE%':>8}{'nRMSE%':>8}")
    for name, s in [("raw physics", raw_sum),
                    ("in-sample MOS (full pool)", ins_sum),
                    ("rolling-window MOS", roll_sum)]:
        b, m, r = _skill(a_sum, s, cap)
        print(f"  {name:<28}{b:>+8.2f}{m:>8.2f}{r:>8.2f}")
    print("=" * 64)

    # ET views
    a_et = to_et(a_sum); raw_et = to_et(raw_sum); roll_et = to_et(roll_sum)

    # ---- Figure 1: two ET weeks (mid-Jan, mid-Jul) ----
    fig, axes = plt.subplots(2, 1, figsize=(12, 6))
    for ax, wk in zip(axes, [f"{YEAR}-01-15", f"{YEAR}-07-15"]):
        sl = slice(f"{wk} 00:00", None)
        end = pd.Timestamp(wk, tz="US/Eastern") + pd.Timedelta(days=7)
        seg = lambda s: s.loc[(s.index >= pd.Timestamp(wk, tz="US/Eastern")) & (s.index < end)]
        ax.plot(seg(a_et).index, seg(a_et).values, color=C_ACT, lw=1.7, label="actual (v4)")
        ax.plot(seg(raw_et).index, seg(raw_et).values, color=C_RAW, lw=1.0, alpha=0.85, label="raw forecast")
        ax.plot(seg(roll_et).index, seg(roll_et).values, color=C_MOS, lw=1.3, label="rolling-window MOS")
        ax.set_ylabel("fleet MW"); ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_title(f"week of {wk} (ET)", fontsize=10, loc="left")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d", tz="US/Eastern"))
    fig.suptitle(f"NY wind fleet day-ahead forecast vs actual — {YEAR} (pluswind_v4)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(FIG / "forecast_fleet_2023.png", dpi=130, bbox_inches="tight")
    plt.close(fig); print("  wrote forecast_fleet_2023.png")

    # ---- Figure 2: mean diurnal by season (ET hour) ----
    season = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
              6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}
    df = pd.DataFrame({"actual": a_et, "raw": raw_et, "mos": roll_et})
    df["hour"] = df.index.hour
    df["season"] = df.index.month.map(season)
    fig, axes = plt.subplots(1, 4, figsize=(15, 4), sharey=True)
    for ax, s in zip(axes, ["DJF", "MAM", "JJA", "SON"]):
        sub = df[df["season"] == s].groupby("hour").mean(numeric_only=True)
        ax.plot(sub.index, sub["actual"], color=C_ACT, lw=1.7, label="actual")
        ax.plot(sub.index, sub["raw"], color=C_RAW, lw=1.1, label="raw")
        ax.plot(sub.index, sub["mos"], color=C_MOS, lw=1.3, label="MOS")
        ax.set_title(s); ax.set_xlabel(HOUR_ET); ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    axes[0].set_ylabel("mean fleet MW")
    fig.suptitle(f"Mean diurnal cycle by season — {YEAR} fleet (pluswind_v4, ET)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(FIG / "forecast_diurnal_2023.png", dpi=130, bbox_inches="tight")
    plt.close(fig); print("  wrote forecast_diurnal_2023.png")

    # ---- Figure 3: hexbin actual vs forecast (raw / rolling-MOS) ----
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), sharex=True, sharey=True)
    for ax, s, label in [(axes[0], raw_sum, "raw physics"),
                         (axes[1], roll_sum, "rolling-window MOS")]:
        v = (~a_sum.isna()) & (~s.isna())
        hb = ax.hexbin(a_sum[v].values, s[v].values, gridsize=60, mincnt=1,
                       cmap="viridis", bins="log")
        lim = max(a_sum.max(), s.max()) * 1.05
        ax.plot([0, lim], [0, lim], "k--", lw=0.8)
        ax.set_xlim(0, lim); ax.set_ylim(0, lim)
        ax.set_xlabel("actual fleet MW"); ax.set_title(label)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("forecast fleet MW")
    fig.suptitle(f"Fleet forecast vs actual, full year {YEAR} (pluswind_v4)",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(FIG / "forecast_scatter_2023.png", dpi=130, bbox_inches="tight")
    plt.close(fig); print("  wrote forecast_scatter_2023.png")


if __name__ == "__main__":
    main()
