"""Stage A scenario fan chart — the end product of the v4 pipeline.
Fleet wind total: the spread of day-ahead scenarios GEMINI draws (built on the
v4 forecast + the residual model), the central v4 forecast, and the realized
v4 actual — for one ET scenario day.
"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments" / "stage_a_joint_load_wind"))
from build_joint_inputs import build_joint_inputs  # noqa
FIG = REPO / "docs" / "figures" / "wind_v3"
SCEN_DIR = Path("/tmp/stage_a_v4_fan/stage_a_2024-01-20")
SCEN_DAY = "2024-01-20"          # ET calendar day
WIND_ZONES = ["A", "C", "D", "E"]

# --- scenarios: sum the 4 wind zones per scenario per ET hour -> (nscen, 24)
scen_total = None
for z in WIND_ZONES:
    s = pd.read_csv(SCEN_DIR / f"scenarios_WIND_{z}.csv", index_col="scenario_idx")
    scen_total = s.values if scen_total is None else scen_total + s.values
hours = list(range(24))   # ET hours 0..23 (columns are "HH:00 ET")

# --- forecast + actual (v4) summed over wind zones, aligned to the ET day
ja, jf, _ = build_joint_inputs([2024])
et = pd.date_range(f"{SCEN_DAY} 00:00", periods=24, freq="h", tz="US/Eastern")
utc = et.tz_convert("UTC")
wind_cols = [f"WIND_{z}" for z in WIND_ZONES]
actual_total = ja.reindex(utc)[wind_cols].sum(axis=1).values
issue = pd.Timestamp(f"{SCEN_DAY} 00:00", tz="US/Eastern").tz_convert("UTC") - pd.Timedelta(hours=6)
jf_day = jf[jf["Forecast_time"].isin(utc)].set_index("Forecast_time").reindex(utc)
fc_total = jf_day[wind_cols].sum(axis=1).values

# --- plot
fig, ax = plt.subplots(figsize=(11, 6))
p = lambda q: np.nanpercentile(scen_total, q, axis=0)
ax.fill_between(hours, p(5), p(95), color="#2471a3", alpha=0.15, label="scenarios 5-95%")
ax.fill_between(hours, p(25), p(75), color="#2471a3", alpha=0.30, label="scenarios 25-75%")
# a few individual scenario paths for texture
for i in range(0, scen_total.shape[0], max(1, scen_total.shape[0] // 15)):
    ax.plot(hours, scen_total[i], color="#2471a3", lw=0.4, alpha=0.25)
ax.plot(hours, p(50), color="#2471a3", lw=2.2, label="scenario median")
ax.plot(hours, fc_total, color="#e67e22", lw=2.2, ls="--", label="v4 DA forecast (central)")
ax.plot(hours, actual_total, color="k", lw=2.6, label="v4 actual (realized)")
ax.set_xlabel("hour of scenario day (ET)")
ax.set_ylabel("fleet wind MW (4 zones A/C/D/E)")
ax.set_title(f"Stage A day-ahead WIND scenario fan — {SCEN_DAY} ET ({scen_total.shape[0]} scenarios)\n"
             "the end product: v4 forecast + GEMINI residual model -> scenario spread; actual should sit within it")
ax.legend(fontsize=9, loc="upper left"); ax.grid(alpha=0.3)
# coverage stat
within = np.mean((actual_total >= p(5)) & (actual_total <= p(95))) * 100
ax.text(0.99, 0.02, f"actual within 5-95% band: {within:.0f}% of hours",
        transform=ax.transAxes, ha="right", fontsize=9,
        bbox=dict(boxstyle="round", fc="white", alpha=0.7))
fig.tight_layout()
out = FIG / "v4_scenario_fan.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print(f"wrote {out}")
print(f"actual within 5-95%: {within:.0f}% of hours; fc_total mean {np.nanmean(fc_total):.0f}, "
      f"actual mean {np.nanmean(actual_total):.0f}, scen median mean {np.nanmean(p(50)):.0f} MW")
