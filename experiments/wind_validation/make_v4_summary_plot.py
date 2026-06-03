"""Four-panel summary of the v4 freeze story:
  A) per-plant hub-shear lift (clip-0.25) sorted by hub height
  B) HRRR shear-exponent alpha: day vs night vs climatology, with the clip
  C) fleet-sum v3 -> v4 actuals over a 2-week window (the lift in context)
  D) tall-tier (>95m) alpha robustness: energy spread across treatments
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
FIG = REPO / "docs" / "figures" / "wind_v3"
WIND = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"

fig, ax = plt.subplots(2, 2, figsize=(15, 10))

# ---- A: per-plant hub lift ----
lift = pd.read_csv(FIG / "fleet_hub_lift_clip025.csv").sort_values("hub_h_m")
colors = ["#c0392b" if h < 79 else ("#95a5a6" if h <= 81 else "#2471a3")
          for h in lift.hub_h_m]
a = ax[0, 0]
a.bar(range(len(lift)), lift.lift_pct, color=colors)
a.axhline(0, color="k", lw=0.6)
a.set_xticks(range(len(lift)))
a.set_xticklabels([f"{h:.0f}" for h in lift.hub_h_m], fontsize=7)
a.set_xlabel("plant hub height (m)")
a.set_ylabel("v4 hub-shear lift vs no-hub (%)")
a.set_title("A) Per-plant clip-0.25 hub-shear lift\n"
            "red=sub-80m (down-correct), grey=80m (invariant), blue=tall (lift)")
a.grid(axis="y", alpha=0.3)

# ---- B: alpha day vs night ----
adf = pd.read_csv(FIG / "alpha_diagnostic.csv")
adf = adf[adf.year == 2020]
order = ["day(10-15 EST)", "all", "night(22-04 EST)"]
sub = adf[adf.subset.isin(order)].set_index("subset").loc[order]
b = ax[0, 1]
xpos = np.arange(len(sub))
b.errorbar(xpos, sub.alpha_median,
           yerr=[sub.alpha_median - sub.alpha_p10, sub.alpha_p90 - sub.alpha_median],
           fmt="o", ms=9, capsize=6, color="#2471a3", lw=2, label="median (P10-P90)")
b.axhspan(0.14, 0.20, color="green", alpha=0.15, label="onshore climatology 0.14-0.20")
b.axhline(0.25, color="#c0392b", ls="--", lw=2, label="adopted clip 0.25")
b.axhline(1/7, color="green", ls=":", lw=1)
b.set_xticks(xpos); b.set_xticklabels(["day\n(well-mixed)", "all hours", "night\n(stable BL)"])
b.set_ylabel("HRRR shear exponent alpha")
b.set_title("B) Why clip-0.25: night alpha (0.29) inflated by stable BL\n"
            "day alpha (0.14) = climatology; clip trims the inflated tail")
b.legend(fontsize=8, loc="upper left"); b.grid(axis="y", alpha=0.3)

# ---- C: fleet-sum v3 -> v4, 2-week window 2020 ----
def fleet(suf, year=2020):
    d = pd.read_csv(WIND / f"wind_actual_1h_site_{year}_utc.pluswind_{suf}.csv",
                    parse_dates=["Time"])
    d["Time"] = pd.to_datetime(d["Time"], utc=True)
    site = [c for c in d.columns if c.startswith("wind_")]
    return d.set_index("Time")[site].sum(axis=1, min_count=1)
v3 = fleet("v3"); v4 = fleet("v4")
win = slice("2020-03-01", "2020-03-15")
c = ax[1, 0]
c.plot(v3.loc[win].index, v3.loc[win].values, lw=1.3, color="#7f8c8d", label="v3 (single-cell, no hub)")
c.plot(v4.loc[win].index, v4.loc[win].values, lw=1.3, color="#2471a3", label="v4 (multi-cell + clip-0.25 hub)")
c.set_ylabel("fleet potential (MW)")
c.set_title("C) Fleet-sum potential v3 -> v4 (2 weeks, Mar 2020)")
c.legend(fontsize=9); c.grid(alpha=0.3)
for lab in c.get_xticklabels():
    lab.set_rotation(30); lab.set_fontsize(7)

# ---- D: tall-tier robustness ----
tt = pd.read_csv(FIG / "tall_tier_alpha_sensitivity.csv").sort_values("hub_m")
d = ax[1, 1]
x = np.arange(len(tt)); w = 0.26
d.bar(x - w, tt["GWh_clip0.25"], w, label="clip-0.25 (adopted)", color="#2471a3")
d.bar(x,     tt["GWh_clip0.20"], w, label="clip-0.20", color="#5dade2")
d.bar(x + w, tt["GWh_daynight"], w, label="day/night-split", color="#aed6f1")
ymax = tt[["GWh_clip0.25", "GWh_clip0.20", "GWh_daynight"]].max(axis=1).to_numpy()
for i, sp in enumerate(tt["spread_pct"].to_numpy()):
    d.text(i, ymax[i] * 1.01, f"{sp:.1f}%", ha="center", fontsize=8)
d.set_xticks(x)
d.set_xticklabels([f"{n.split()[0][:8]}\n{h:.0f}m" for n, h in zip(tt.name, tt.hub_m)], fontsize=7)
d.set_ylabel("annual-mean energy (GWh, pooled 2018-24)")
d.set_title("D) Tall-tier (>95m) robustness: 1-3% spread across alpha treatments\n"
            "=> keep clip-0.25 (lift is robust, not alpha-fragile)")
d.legend(fontsize=8); d.grid(axis="y", alpha=0.3)

fig.suptitle("Wind v4 freeze — multi-cell Method A + clip-0.25 hub-shear", fontsize=14, y=1.0)
fig.tight_layout()
out = FIG / "v4_summary.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
