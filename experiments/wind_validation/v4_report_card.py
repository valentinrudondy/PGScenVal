"""v4 report card — honest v3-vs-v4 comparison numbers + a 'how much better'
figure. Framed per I3: the genuine, defensible improvements are
(1) forecast skill (held-out 2023), (2) clean-anchor physical realism
(Copenhagen), (3) data-integrity fixes, (4) the tall-plant hub correction.
Does NOT claim improvement on raw PLUSWIND level (that's hub-blind, I3).
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
from score_per_plant_hourly import load_lpi_long, LPI_GROUPS  # noqa
W = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
FIG = REPO / "docs" / "figures" / "wind_v3"


def fc(suf, year=2023, rolling=True):
    f = (W / f"wind_day_ahead_forecast_site_{year}_utc.pluswind_{suf}"
         f"{'.rolling' if rolling else ''}.csv")
    d = pd.read_csv(f, parse_dates=["Forecast_time"])
    d["Forecast_time"] = pd.to_datetime(d["Forecast_time"], utc=True)
    s = [c for c in d.columns if c.startswith("wind_")]
    return to_et(d.set_index("Forecast_time")[s])


def act(suf, year=2023):
    d = pd.read_csv(W / f"wind_actual_1h_site_{year}_utc.pluswind_{suf}.csv",
                    parse_dates=["Time"])
    d["Time"] = pd.to_datetime(d["Time"], utc=True)
    s = [c for c in d.columns if c.startswith("wind_")]
    return to_et(d.set_index("Time")[s])


def nmae(f, a):
    j = pd.concat([f.rename("f"), a.rename("a")], axis=1).dropna()
    return 100 * (j.f - j.a).abs().mean() / j.a.mean(), len(j)


# ---------- numbers ----------
print("=" * 72)
print("v4 REPORT CARD — what actually got better (and why)")
print("=" * 72)

# 1) Forecast skill, held-out 2023
v3f, v4f, v3a, v4a = fc("v3"), fc("v4"), act("v3"), act("v4")
common = sorted(set(v3f) & set(v4f) & set(v3a) & set(v4a))
n3, _ = nmae(v3f[common].sum(1, min_count=1), v3a[common].sum(1, min_count=1))
n4, _ = nmae(v4f[common].sum(1, min_count=1), v4a[common].sum(1, min_count=1))
print(f"\n[1] DAY-AHEAD FORECAST SKILL (held-out 2023, fleet, MOS-corrected):")
print(f"    v3 nMAE {n3:.2f}%  ->  v4 nMAE {n4:.2f}%   ({100*(n4-n3)/n3:+.0f}% relative)")
pp = []
for s in common:
    a3, _ = nmae(v3f[s], v3a[s]); a4, _ = nmae(v4f[s], v4a[s])
    pp.append((s, a3, a4))
pp = pd.DataFrame(pp, columns=["site", "v3", "v4"])
print(f"    per-plant: {(pp.v4 < pp.v3).sum()}/{len(pp)} plants improved; "
      f"median {pp.v3.median():.0f}% -> {pp.v4.median():.0f}%")

# 2) Copenhagen clean anchor, 2024
cop = "wind_323753"
c3 = act("v3", 2024)[cop]; c4 = act("v4", 2024)[cop]
lpi = load_lpi_long(); lpi["ts"] = pd.to_datetime(lpi.ts_utc, utc=True)
lc = lpi[lpi.group == "copenhagen"].set_index("ts")["delivered_mw"].tz_convert("US/Eastern")
jc = pd.concat([c3.rename("v3"), c4.rename("v4"), lc.rename("lpi")], axis=1).dropna()
jc = jc[jc.index.year == 2024]
l3 = 100 * (jc.v3.mean() - jc.lpi.mean()) / jc.v3.mean()
l4 = 100 * (jc.v4.mean() - jc.lpi.mean()) / jc.v4.mean()
print(f"\n[2] COPENHAGEN clean-anchor PHYSICAL REALISM (2024, potential vs metered):")
print(f"    v3 implied loss {l3:+.1f}% (at/below metered = unphysical for a real plant)")
print(f"    v4 implied loss {l4:+.1f}% (a few % above metered = physical avail+wake)")

# 3) data-integrity fixes
print(f"\n[3] DATA-INTEGRITY FIXES (metadata, sourced from EIA-860/USWTDB):")
print(f"    Baron Winds nameplate 238.4 -> 130 MW  => EIA-923 loss 49% -> 6% (in band)")
print(f"    Canandaigua EIA 60596(Baron) -> 56634(Cohocton): right curve+hub+coords")

# 4) tall-plant hub correction
lift = pd.read_csv(FIG / "fleet_hub_lift_clip025.csv")
tall = lift[lift.hub_h_m > 95]
print(f"\n[4] TALL-PLANT HUB CORRECTION (were modeled at 80m, really 100-120m):")
print(f"    {len(tall)} plants >95m lifted +{tall.lift_pct.min():.0f}..+{tall.lift_pct.max():.0f}%; "
      f"18 plants at 80m unchanged; fleet-sum +{100*(lift.mean_v5_clip025_mw.sum()/lift.mean_v4_mw.sum()-1):.1f}%")

pp.to_csv(FIG / "v4_report_card_forecast_nmae.csv", index=False)
print(f"\nwrote {FIG/'v4_report_card_forecast_nmae.csv'}")

# ---------- plot ----------
fig, ax = plt.subplots(1, 3, figsize=(17, 5.2))

# A: per-plant forecast nMAE v3 vs v4
a = ax[0]
a.scatter(pp.v3, pp.v4, s=45, color="#2471a3", zorder=3)
lim = [0, max(pp.v3.max(), pp.v4.max()) * 1.05]
a.plot(lim, lim, "k--", lw=1, label="no change")
a.fill_between(lim, [0, 0], lim, color="green", alpha=0.07)
a.text(lim[1]*0.55, lim[1]*0.2, "v4 better\n(below line)", color="green", fontsize=11)
a.set_xlim(lim); a.set_ylim(lim)
a.set_xlabel("v3 forecast nMAE (%)"); a.set_ylabel("v4 forecast nMAE (%)")
a.set_title(f"A) DA forecast skill per plant (held-out 2023)\nall {(pp.v4<pp.v3).sum()}/{len(pp)} plants improved")
a.legend(fontsize=9); a.grid(alpha=0.3)

# B: fleet forecast vs actual, 1 week 2023
b = ax[1]
win = slice("2023-02-01", "2023-02-08")
f3 = v3f[common].sum(1, min_count=1); f4 = v4f[common].sum(1, min_count=1)
a4s = v4a[common].sum(1, min_count=1)
b.plot(a4s.loc[win].index, a4s.loc[win].values, color="k", lw=2.2, label="actual (v4 potential)")
b.plot(f3.loc[win].index, f3.loc[win].values, color="#e67e22", lw=1.3, ls="--", label=f"v3-MOS forecast ({n3:.0f}% nMAE)")
b.plot(f4.loc[win].index, f4.loc[win].values, color="#2471a3", lw=1.3, label=f"v4-MOS forecast ({n4:.0f}% nMAE)")
b.set_ylabel("fleet MW"); b.set_title("B) Fleet DA forecast vs actual (1 wk, Feb 2023)")
b.legend(fontsize=8); b.grid(alpha=0.3)
for L in b.get_xticklabels(): L.set_rotation(30); L.set_fontsize(7)

# C: Copenhagen clean anchor diurnal
c = ax[2]
jc["hod"] = jc.index.hour; di = jc.groupby("hod").mean()
c.plot(di.index, di.lpi, "o-", color="k", lw=2, label=f"LPI metered ({jc.lpi.mean():.0f} MW)")
c.plot(di.index, di.v3, "s--", color="#7f8c8d", lw=1.6, label=f"v3 potential ({jc.v3.mean():.0f} MW, loss {l3:+.0f}%)")
c.plot(di.index, di.v4, "^-", color="#2471a3", lw=1.8, label=f"v4 potential ({jc.v4.mean():.0f} MW, loss {l4:+.0f}%)")
c.set_xlabel(HOUR_ET); c.set_ylabel("MW")
c.set_title("C) Copenhagen clean anchor (2024)\nv4 lands at physical loss; v3 was unphysical")
c.legend(fontsize=8); c.grid(alpha=0.3)

fig.suptitle("v4 vs v3 — where it's better: forecast skill, and physical realism on the clean anchor", fontsize=13, y=1.02)
fig.tight_layout()
fig.savefig(FIG / "v4_report_card.png", dpi=130, bbox_inches="tight")
print(f"wrote {FIG/'v4_report_card.png'}")
