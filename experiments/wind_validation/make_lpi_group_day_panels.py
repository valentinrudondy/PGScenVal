"""Panel grid, every panel metered-anchored: rows = the 4 NYISO LPI groups
(group sums), cols = diverse 2024 days. Each panel overlays the v4 group-sum
potential, the v4 group-sum DA forecast (MOS-corrected), the v3 group-sum
potential, and the group's LPI metered (black dots) — so every panel has a
real-world comparison. 2024 = the LPI/v4 overlap.
"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_per_plant_hourly import load_lpi_long, LPI_GROUPS  # noqa
from et_plot import to_et, HOUR_ET  # noqa  (ALL wind output in US/Eastern)
W = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
FIG = REPO / "docs" / "figures" / "wind_v3"
YEAR = 2024

GROUPS = ["copenhagen", "maple_ridge", "marble_agg", "noble_agg"]
DAYS = ["2024-01-20", "2024-04-15", "2024-07-15", "2024-10-20"]


def load_act(suf):
    d = pd.read_csv(W / f"wind_actual_1h_site_{YEAR}_utc.pluswind_{suf}.csv",
                    parse_dates=["Time"])
    d["Time"] = pd.to_datetime(d["Time"], utc=True)
    return to_et(d.set_index("Time"))


def load_fc(suf):
    d = pd.read_csv(W / f"wind_day_ahead_forecast_site_{YEAR}_utc.pluswind_{suf}.csv",
                    parse_dates=["Forecast_time"])
    d["Forecast_time"] = pd.to_datetime(d["Forecast_time"], utc=True)
    return to_et(d.drop_duplicates("Forecast_time").set_index("Forecast_time"))


v4a, v3a, v4f = load_act("v4"), load_act("v3"), load_fc("v4")
lpi = load_lpi_long(); lpi["ts"] = pd.to_datetime(lpi.ts_utc, utc=True)


def gsum(df, sites):
    cols = [s for s in sites if s in df.columns]
    return df[cols].sum(axis=1, min_count=1)


nr, nc = len(GROUPS), len(DAYS)
fig, ax = plt.subplots(nr, nc, figsize=(4.0 * nc, 2.6 * nr), sharex=True)

for i, gk in enumerate(GROUPS):
    g = LPI_GROUPS[gk]
    sites = g["site_ids"]
    v4s, v3s, v4fs = gsum(v4a, sites), gsum(v3a, sites), gsum(v4f, sites)
    deliv = lpi[lpi.group == gk].set_index("ts")["delivered_mw"].tz_convert("US/Eastern")
    for jx, day in enumerate(DAYS):
        a = ax[i, jx]
        sl = slice(f"{day} 00:00", f"{day} 23:00")
        for s, c, lw, ls, lab in [
            (v3s, "#bdc3c7", 1.4, "-", "v3 potential"),
            (v4s, "#2471a3", 1.9, "-", "v4 potential"),
            (v4fs, "#2471a3", 1.3, "--", "v4 DA forecast"),
        ]:
            seg = s.loc[sl]
            if len(seg):
                a.plot(seg.index.hour, seg.values, color=c, lw=lw, ls=ls, label=lab)
        d = deliv.loc[sl]
        if len(d):
            a.plot(d.index.hour, d.values, "-", color="k", lw=2.0, label="LPI metered")
        if i == 0:
            a.set_title(day, fontsize=10)
        if jx == 0:
            a.set_ylabel(f"{gk}\n({g['nameplate_mw']:.0f} MW)\nMW", fontsize=8)
        a.grid(alpha=0.25); a.tick_params(labelsize=7)
        if i == nr - 1:
            a.set_xlabel(HOUR_ET, fontsize=8)

h, l = ax[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=4, fontsize=10, bbox_to_anchor=(0.5, 1.005))
fig.suptitle("One panel = one LPI group, one day (2024, ET) — every panel metered-anchored "
             "(v4 potential / v4 forecast / v3 potential / LPI metered)", fontsize=12, y=1.03)
fig.tight_layout()
out = FIG / "v4_lpi_group_day_panels.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
