"""Entire-fleet v4 potential vs NYISO rtfuelmix (statewide delivered wind), on
specific 2024 ET days spanning regimes (windiest / calmest / biggest-ramp).
rtfuelmix is post-curtailment system total -> sits ~30% below potential (the
loss); validate SHAPE + the scaled level, not raw level (I3). The only
independent 2024 signal that touches the whole fleet incl. the unanchored
tall plants. All times ET.
"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from et_plot import to_et, HOUR_ET           # noqa  (ALL wind output in US/Eastern)
from score_vs_rtfuelmix import load_rtfuelmix_wind  # noqa
W = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
FIG = REPO / "docs" / "figures" / "wind_v3"
YEAR = 2024


def fleet(suf):
    d = pd.read_csv(W / f"wind_actual_1h_site_{YEAR}_utc.pluswind_{suf}.csv",
                    parse_dates=["Time"])
    d["Time"] = pd.to_datetime(d["Time"], utc=True)
    site = [c for c in d.columns if c.startswith("wind_")]
    return to_et(d.set_index("Time")[site].sum(axis=1, min_count=1))


v4 = fleet("v4"); v3 = fleet("v3")
rt = load_rtfuelmix_wind(YEAR)                 # tz-naive UTC hourly
rt.index = rt.index.tz_localize("UTC").tz_convert("US/Eastern")

# pick regime days from v4 daily stats
day = v4.groupby(v4.index.normalize())
stats = pd.DataFrame({"mean": day.mean(), "rampstd": day.apply(lambda s: s.diff().std())})
stats = stats[stats.index.year == YEAR].dropna()
windy = stats.nlargest(3, "mean").index
calm = stats.nsmallest(3, "mean").index
rampy = stats.drop(list(windy) + list(calm)).nlargest(3, "rampstd").index
sel = [(d, "WINDIEST") for d in windy] + [(d, "CALMEST") for d in calm] + [(d, "BIGGEST RAMP") for d in rampy]
sel.sort(key=lambda x: x[0])

fig, ax = plt.subplots(3, 3, figsize=(16, 11), sharex=True)
for k, (d0, regime) in enumerate(sel):
    a = ax[k // 3, k % 3]
    sl = slice(d0, d0 + pd.Timedelta(hours=23))
    fv4, frt = v4.loc[sl], rt.loc[sl]
    j = pd.concat([fv4.rename("m"), frt.rename("r")], axis=1).dropna()
    loss = 100 * (j.m.mean() - j.r.mean()) / j.m.mean() if len(j) and j.m.mean() > 0 else float("nan")
    r = j.m.corr(j.r) if len(j) > 1 else float("nan")
    scalar = j.r.mean() / j.m.mean() if len(j) and j.m.mean() > 0 else float("nan")
    a.plot(fv4.index.hour, fv4.values, color="#2471a3", lw=2.0, label="v4 potential")
    a.plot(fv4.index.hour, fv4.values * scalar, color="#2471a3", lw=1.6, ls=":",
           label="v4 x loss-scalar (shape only)")
    a.plot(frt.index.hour, frt.values, color="k", lw=2.0, label="rtfuelmix delivered (NYISO)")
    a.set_title(f"{d0.strftime('%Y-%m-%d')} — {regime}\nloss {loss:.0f}%, shape r={r:.2f}", fontsize=10)
    a.grid(alpha=0.25); a.tick_params(labelsize=7)
    if k % 3 == 0:
        a.set_ylabel("fleet wind (MW)", fontsize=9)
    if k // 3 == 2:
        a.set_xlabel(HOUR_ET, fontsize=9)

h, l = ax[0, 0].get_legend_handles_labels()
fig.legend(h, l, loc="upper center", ncol=3, fontsize=11, bbox_to_anchor=(0.5, 1.005))
fig.suptitle("Entire NY wind fleet — v4 potential vs NYISO rtfuelmix delivered (2024 ET). "
             "Gap = real-world curtailment+availability; shape match = model fidelity.",
             fontsize=12, y=1.02)
fig.tight_layout()
out = FIG / "v4_fleet_vs_rtfuelmix_days.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
for d0, regime in sel:
    sl = slice(d0, d0 + pd.Timedelta(hours=23))
    j = pd.concat([v4.loc[sl].rename("m"), rt.loc[sl].rename("r")], axis=1).dropna()
    print(f"  {d0.date()} {regime:12s}: v4 {j.m.mean():.0f} MW, rt {j.r.mean():.0f} MW, "
          f"loss {100*(j.m.mean()-j.r.mean())/j.m.mean():.0f}%, r {j.m.corr(j.r):.2f}")
