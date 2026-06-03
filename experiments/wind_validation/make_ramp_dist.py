"""Ramp / hourly-change realism — the variance GEMINI cares about.
A) Copenhagen hourly-Delta distribution: v4 potential vs LPI metered (2024).
B) ramp std (MW/h) by LPI group: v4 vs metered (2024).
C) fleet hourly-Delta distribution: v4 vs v3 (2024) — the freeze's variance effect.
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
from score_per_plant_hourly import load_lpi_long, LPI_GROUPS  # noqa
W = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"
FIG = REPO / "docs" / "figures" / "wind_v3"
GROUPS = ["copenhagen", "maple_ridge", "marble_agg", "noble_agg"]


def act(suf, year=2024):
    d = pd.read_csv(W / f"wind_actual_1h_site_{year}_utc.pluswind_{suf}.csv",
                    parse_dates=["Time"])
    d["Time"] = pd.to_datetime(d["Time"], utc=True)
    return d.set_index("Time")


v4, v3 = act("v4"), act("v3")
lpi = load_lpi_long(); lpi["ts"] = pd.to_datetime(lpi.ts_utc, utc=True)


def gsum(df, sites):
    return df[[s for s in sites if s in df.columns]].sum(axis=1, min_count=1)


def ramps(s):  # consecutive-hour deltas
    s = s.sort_index()
    d = s.diff()
    dt = s.index.to_series().diff().dt.total_seconds()
    return d[dt == 3600].dropna().values


fig, ax = plt.subplots(1, 3, figsize=(17, 5))

# A) Copenhagen hourly-delta dist: v4 vs metered
cop_sites = LPI_GROUPS["copenhagen"]["site_ids"]
cop_v4 = ramps(gsum(v4, cop_sites))
cop_met = ramps(lpi[lpi.group == "copenhagen"].set_index("ts")["delivered_mw"])
bins = np.linspace(-30, 30, 41)
ax[0].hist(cop_v4, bins=bins, density=True, alpha=0.5, color="#2471a3", label=f"v4 potential (std {cop_v4.std():.1f})")
ax[0].hist(cop_met, bins=bins, density=True, alpha=0.5, color="k", label=f"LPI metered (std {cop_met.std():.1f})")
ax[0].set_xlabel("hourly change (MW/h)"); ax[0].set_ylabel("density")
ax[0].set_title("A) Copenhagen hourly-ramp distribution (2024)\nv4 variability vs real delivered")
ax[0].legend(fontsize=9); ax[0].grid(alpha=0.3)

# B) ramp std by LPI group: v4 vs metered
rows = []
for gk in GROUPS:
    g = LPI_GROUPS[gk]
    rv4 = ramps(gsum(v4, g["site_ids"]))
    rmet = ramps(lpi[lpi.group == gk].set_index("ts")["delivered_mw"])
    rows.append((gk, rv4.std(), rmet.std()))
r = pd.DataFrame(rows, columns=["g", "v4", "met"])
x = np.arange(len(r)); w = 0.38
ax[1].bar(x - w/2, r.v4, w, color="#2471a3", label="v4 potential")
ax[1].bar(x + w/2, r.met, w, color="k", label="LPI metered")
ax[1].set_xticks(x); ax[1].set_xticklabels(r.g, fontsize=8, rotation=15)
ax[1].set_ylabel("ramp std (MW/h)")
ax[1].set_title("B) Hourly-ramp magnitude by group (2024)\nv4 vs metered (metered lower: curtailment caps peaks)")
ax[1].legend(fontsize=9); ax[1].grid(axis="y", alpha=0.3)

# C) fleet hourly-delta: v4 vs v3
site = [c for c in v4.columns if c.startswith("wind_")]
fv4 = ramps(v4[site].sum(axis=1, min_count=1))
fv3 = ramps(v3[[c for c in site if c in v3.columns]].sum(axis=1, min_count=1))
bins2 = np.linspace(-300, 300, 61)
ax[2].hist(fv3, bins=bins2, density=True, alpha=0.5, color="#bdc3c7", label=f"v3 (std {fv3.std():.0f})")
ax[2].hist(fv4, bins=bins2, density=True, alpha=0.5, color="#2471a3", label=f"v4 (std {fv4.std():.0f})")
ax[2].set_xlabel("fleet hourly change (MW/h)"); ax[2].set_ylabel("density")
ax[2].set_title("C) Fleet hourly-ramp distribution (2024)\nv4 vs v3 — freeze's effect on variability")
ax[2].legend(fontsize=9); ax[2].grid(alpha=0.3)

fig.suptitle("Ramp / hourly-variability realism (the variance GEMINI fits)", fontsize=13, y=1.02)
fig.tight_layout()
out = FIG / "v4_ramp_distribution.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
print(r.to_string(index=False))
print(f"fleet ramp std: v3 {fv3.std():.0f}, v4 {fv4.std():.0f} MW/h")
