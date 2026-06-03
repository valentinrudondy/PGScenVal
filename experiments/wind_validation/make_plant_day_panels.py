"""Panel grid: one panel = one plant, one day. Rows = plants (diverse hub
heights/sizes/zones), cols = days (diverse seasons, 2024). Each panel overlays
the v4 potential (actual), the v4 DA forecast (MOS-corrected), and the v3
potential — plus LPI metered where the plant is a single-plant LPI group.
Shows how the model tracks within a day and the v3->v4 difference per plant.
"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_per_plant_hourly import load_lpi_long  # noqa
from et_plot import to_et, HOUR_ET  # noqa  (ALL wind output in US/Eastern)
W = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
FIG = REPO / "docs" / "figures" / "wind_v3"
YEAR = 2024

# (site_id, short label, hub m, single-plant LPI group or None)
PLANTS = [
    ("wind_323753", "Copenhagen", 95, "copenhagen"),
    ("wind_323821", "Bluestone",  120, None),
    ("wind_323574", "Maple Ridge 1", 80, "maple_ridge"),
    ("wind_323673", "Hardscrabble", 100, None),
    ("wind_24204",  "Fenner",      66, None),
]
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

nr, nc = len(PLANTS), len(DAYS)
fig, ax = plt.subplots(nr, nc, figsize=(4.0 * nc, 2.5 * nr), sharex=True)

for i, (sid, lab, hub, grp) in enumerate(PLANTS):
    for jx, day in enumerate(DAYS):
        a = ax[i, jx]
        sl = slice(f"{day} 00:00", f"{day} 23:00")
        a4 = v4a[sid].loc[sl] if sid in v4a.columns else None
        a3 = v3a[sid].loc[sl] if sid in v3a.columns else None
        f4 = v4f[sid].loc[sl] if sid in v4f.columns else None
        hrs = lambda s: s.index.hour
        if a3 is not None:
            a.plot(hrs(a3), a3.values, color="#bdc3c7", lw=1.4, label="v3 potential")
        if a4 is not None:
            a.plot(hrs(a4), a4.values, color="#2471a3", lw=1.8, label="v4 potential")
        if f4 is not None:
            a.plot(hrs(f4), f4.values, color="#2471a3", lw=1.3, ls="--", label="v4 DA forecast")
        if grp:
            d = lpi[(lpi.group == grp)].set_index("ts")["delivered_mw"].tz_convert("US/Eastern").loc[sl]
            if len(d):
                a.plot(d.index.hour, d.values, "o", color="k", ms=3, label="LPI metered")
        if i == 0:
            a.set_title(day, fontsize=10)
        if jx == 0:
            a.set_ylabel(f"{lab}\n{hub} m\nMW", fontsize=8)
        a.grid(alpha=0.25)
        a.tick_params(labelsize=7)
        if i == nr - 1:
            a.set_xlabel(HOUR_ET, fontsize=8)

# one shared legend
h, l = ax[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=4, fontsize=10, bbox_to_anchor=(0.5, 1.005))
fig.suptitle("One panel = one plant, one day (2024, ET) — v4 potential, v4 DA forecast, v3 potential, LPI metered",
             fontsize=12, y=1.03)
fig.tight_layout()
out = FIG / "v4_plant_day_panels.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
