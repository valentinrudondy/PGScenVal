"""Two-panel drill-down:
  A) Copenhagen 2024 — v3 vs v4 modeled potential vs LPI metered (the clean
     anchor). v4's hub-shear puts potential a physical few-% above metered;
     v3 sat AT metered (implying impossible ~0% loss).
  B) Bluestone (120 m hub, biggest tall-tier lift) 2024 — v3 vs v4 time series.
"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sys as _s; _s.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from et_plot import to_et, HOUR_ET  # ALL wind output in US/Eastern


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_multicell_pilot import load_lpi_groups  # noqa: E402

FIG = REPO / "docs" / "figures" / "wind_v3"
WIND = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"


def modeled(suf, sid, year=2024):
    d = pd.read_csv(WIND / f"wind_actual_1h_site_{year}_utc.pluswind_{suf}.csv",
                    parse_dates=["Time"])
    d["Time"] = pd.to_datetime(d["Time"], utc=True)
    return to_et(d.set_index("Time")[sid])


fig, ax = plt.subplots(1, 2, figsize=(16, 5.5))

# ---- A: Copenhagen 2024 diurnal — v3, v4, LPI metered ----
cop = "wind_323753"
v3 = modeled("v3", cop); v4 = modeled("v4", cop)
lpi = load_lpi_groups([2024])
lpi_cop = (lpi[lpi.group == "copenhagen"].assign(
    ts=lambda x: pd.to_datetime(x.ts_utc, utc=True))
    .set_index("ts")["delivered_mw"].tz_convert("US/Eastern"))
j = pd.concat({"v3": v3, "v4": v4, "lpi": lpi_cop}, axis=1).dropna()
j["hod"] = j.index.hour
diur = j.groupby("hod").mean()
a = ax[0]
a.plot(diur.index, diur.lpi, "o-", color="#000000", lw=2, label=f"LPI metered (mean {j.lpi.mean():.1f} MW)")
a.plot(diur.index, diur.v3, "s--", color="#7f8c8d", lw=1.6, label=f"v3 potential (mean {j.v3.mean():.1f} MW)")
a.plot(diur.index, diur.v4, "^-", color="#2471a3", lw=1.8, label=f"v4 potential (mean {j.v4.mean():.1f} MW)")
a.set_xlabel(HOUR_ET); a.set_ylabel("MW")
loss_v3 = 100 * (j.v3.mean() - j.lpi.mean()) / j.v3.mean()
loss_v4 = 100 * (j.v4.mean() - j.lpi.mean()) / j.v4.mean()
a.set_title(f"A) Copenhagen 2024 diurnal (clean anchor, {len(j)} hrs)\n"
            f"implied loss: v3 {loss_v3:+.1f}% (at metered, unphysical), "
            f"v4 {loss_v4:+.1f}% (physical)")
a.legend(fontsize=9); a.grid(alpha=0.3)

# ---- B: Bluestone (120m) 2024 v3 vs v4 time series ----
bs = "wind_323821"
b3 = modeled("v3", bs); b4 = modeled("v4", bs)
win = slice("2024-11-01", "2024-11-14")
b = ax[1]
b.plot(b3.loc[win].index, b3.loc[win].values, lw=1.4, color="#7f8c8d", label=f"v3 (no hub, mean {b3.mean():.1f} MW)")
b.plot(b4.loc[win].index, b4.loc[win].values, lw=1.4, color="#c0392b", label=f"v4 (120 m hub, mean {b4.mean():.1f} MW, +{100*(b4.mean()/b3.mean()-1):.0f}%)")
b.set_ylabel("potential (MW)")
b.set_title("B) Bluestone Wind (120 m hub, biggest tall-tier lift)\n"
            "2 weeks Nov 2024 — v3 vs v4")
b.legend(fontsize=9); b.grid(alpha=0.3)
for lab in b.get_xticklabels():
    lab.set_rotation(30); lab.set_fontsize(7)

fig.suptitle("v4 drill-down: Copenhagen validation (clean anchor) + tallest-plant lift", fontsize=13, y=1.02)
fig.tight_layout()
out = FIG / "v4_copenhagen_bluestone.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
print(f"Copenhagen 2024: v3 mean {j.v3.mean():.2f}, v4 mean {j.v4.mean():.2f}, LPI {j.lpi.mean():.2f} MW")
print(f"  implied loss v3 {loss_v3:+.1f}%  v4 {loss_v4:+.1f}%")
print(f"Bluestone 2024: v3 {b3.mean():.2f} -> v4 {b4.mean():.2f} MW (+{100*(b4.mean()/b3.mean()-1):.1f}%)")
