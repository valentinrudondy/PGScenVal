"""v4 potential vs LPI metered for the three AGED groups (not Copenhagen).
These are post-curtailment metered: the ~20-40% level gap below v4 potential is
DEFINITIONAL (availability + wake + curtailment), not model error (plan I3). So
the valid read is SHAPE — diurnal + ramp + CF-normalised — not level. Each panel
overlays the raw diurnal (showing the definitional loss gap) and annotates the
shape agreement (Pearson r, CF-normalised nMAE). 2024.
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
from score_per_plant_hourly import load_lpi_long, LPI_GROUPS  # noqa: E402

FIG = REPO / "docs" / "figures" / "wind_v3"
WIND = REPO / "PGscen-2nd" / "data" / "NYISO_real" / "wind"

GROUPS = ["maple_ridge", "marble_agg", "noble_agg"]   # the aged groups


def v4_wide(year=2024):
    d = pd.read_csv(WIND / f"wind_actual_1h_site_{year}_utc.pluswind_v4.csv",
                    parse_dates=["Time"])
    d["Time"] = pd.to_datetime(d["Time"], utc=True)
    return to_et(d.set_index("Time"))


v4 = v4_wide()
lpi = load_lpi_long()
lpi["ts"] = pd.to_datetime(lpi["ts_utc"], utc=True)

fig, axes = plt.subplots(1, 3, figsize=(17, 5.2))
for ax, gk in zip(axes, GROUPS):
    g = LPI_GROUPS[gk]
    sites = [s for s in g["site_ids"] if s in v4.columns]
    mod = v4[sites].sum(axis=1, min_count=1).rename("v4")
    deliv = (lpi[lpi.group == gk].set_index("ts")["delivered_mw"].tz_convert("US/Eastern").rename("lpi"))
    j = pd.concat([mod, deliv], axis=1).dropna()
    j = j[j.index.year == 2024]
    j["hod"] = j.index.hour
    diur = j.groupby("hod").mean()
    # metrics
    loss = 100 * (j.v4.mean() - j.lpi.mean()) / j.v4.mean()
    r = j.v4.corr(j.lpi)
    cf_nmae = 100 * (np.abs(j.v4 / j.v4.mean() - j.lpi / j.lpi.mean())).mean()
    ax.plot(diur.index, diur.lpi, "o-", color="#000", lw=2,
            label=f"LPI metered ({j.lpi.mean():.0f} MW)")
    ax.plot(diur.index, diur.v4, "^-", color="#2471a3", lw=2,
            label=f"v4 potential ({j.v4.mean():.0f} MW)")
    ax.fill_between(diur.index, diur.lpi, diur.v4, color="#e74c3c", alpha=0.12)
    ax.set_title(f"{g['label'][:38]}\n"
                 f"definitional loss {loss:.0f}%  |  shape: r={r:.2f}, "
                 f"CF-norm nMAE={cf_nmae:.0f}%", fontsize=10)
    ax.set_xlabel(HOUR_ET)
    ax.set_ylabel("MW")
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(alpha=0.3)

fig.suptitle("v4 potential vs LPI metered — aged groups (2024, ET). Red = definitional "
             "loss (availability+wake+curtailment), NOT model error (I3); validate SHAPE.",
             fontsize=12, y=1.03)
fig.tight_layout()
out = FIG / "v4_vs_lpi_aged.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
for gk in GROUPS:
    g = LPI_GROUPS[gk]; sites = [s for s in g["site_ids"] if s in v4.columns]
    mod = v4[sites].sum(axis=1, min_count=1); deliv = lpi[lpi.group == gk].set_index("ts")["delivered_mw"].tz_convert("US/Eastern")
    j = pd.concat([mod.rename("v4"), deliv.rename("lpi")], axis=1).dropna()
    j = j[j.index.year == 2024]
    print(f"  {gk}: v4 {j.v4.mean():.1f} MW, LPI {j.lpi.mean():.1f} MW, "
          f"loss {100*(j.v4.mean()-j.lpi.mean())/j.v4.mean():.0f}%, r {j.v4.corr(j.lpi):.3f}")
