"""16 panels, all Copenhagen (wind_323753), one day each, spread across 2024.
Per panel: v4 potential, v3 potential, v4 DA forecast, LPI metered.
"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_per_plant_hourly import load_lpi_long  # noqa
from et_plot import to_et, HOUR_ET  # noqa  (ALL wind output in US/Eastern)
W = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
FIG = REPO / "docs" / "figures" / "wind_v3"
YEAR = 2024
SID = "wind_323753"   # Copenhagen (LPI group 'copenhagen' = this single plant)


def load_act(suf):
    d = pd.read_csv(W / f"wind_actual_1h_site_{YEAR}_utc.pluswind_{suf}.csv",
                    parse_dates=["Time"])
    d["Time"] = pd.to_datetime(d["Time"], utc=True)
    return to_et(d.set_index("Time")[SID])


def load_fc(suf):
    d = pd.read_csv(W / f"wind_day_ahead_forecast_site_{YEAR}_utc.pluswind_{suf}.csv",
                    parse_dates=["Forecast_time"])
    d["Forecast_time"] = pd.to_datetime(d["Forecast_time"], utc=True)
    return to_et(d.drop_duplicates("Forecast_time").set_index("Forecast_time")[SID])


v4a, v3a, v4f = load_act("v4"), load_act("v3"), load_fc("v4")
lpi = load_lpi_long(); lpi["ts"] = pd.to_datetime(lpi.ts_utc, utc=True)
deliv = lpi[lpi.group == "copenhagen"].set_index("ts")["delivered_mw"].tz_convert("US/Eastern")

# Pick 16 ET days that actually have FULL Copenhagen metered coverage (NYISO LPI
# has gaps; a fixed date list left some panels without the black curve). Keep
# 2024 ET-days with >=24 metered hours, then take 16 evenly spaced.
d24 = deliv[deliv.index.year == 2024]
cov = d24.groupby(d24.index.normalize()).size()
full = cov[cov >= 24].index
DAYS = [full[i].strftime("%Y-%m-%d")
        for i in np.linspace(0, len(full) - 1, 16).round().astype(int)]
print(f"{len(full)} fully-metered Copenhagen days in 2024; chose 16: {DAYS}")

fig, ax = plt.subplots(4, 4, figsize=(16, 11), sharex=True)
for k, day in enumerate(DAYS):
    a = ax[k // 4, k % 4]
    sl = slice(f"{day} 00:00", f"{day} 23:00")
    for s, c, lw, ls, lab in [
        (v3a, "#bdc3c7", 1.4, "-", "v3 potential"),
        (v4a, "#2471a3", 1.9, "-", "v4 potential"),
        (v4f, "#2471a3", 1.3, "--", "v4 DA forecast"),
        (deliv, "#000000", 1.9, "-", "LPI metered"),
    ]:
        seg = s.loc[sl]
        if len(seg):
            a.plot(seg.index.hour, seg.values, color=c, lw=lw, ls=ls, label=lab)
    a.set_title(day, fontsize=10)
    a.grid(alpha=0.25); a.tick_params(labelsize=7)
    a.set_ylim(0, 80)   # Copenhagen nameplate 79.9 MW — common y-axis
    if k % 4 == 0:
        a.set_ylabel("MW", fontsize=9)
    if k // 4 == 3:
        a.set_xlabel(HOUR_ET, fontsize=9)

h, l = ax[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=4, fontsize=11, bbox_to_anchor=(0.5, 1.005))
fig.suptitle("Copenhagen Wind (79.9 MW, 95 m hub) — 16 days across 2024 (ET), one panel each",
             fontsize=13, y=1.02)
fig.tight_layout()
out = FIG / "v4_copenhagen_16days.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
