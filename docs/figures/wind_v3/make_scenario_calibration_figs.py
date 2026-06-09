"""Current-state per-plant wind SCENARIO calibration figures (ship config).

Ship config = per-plant GeminiEngine, asset_rho=0.5 (geographic), the pre-COD
conditional-marginal fix ON (restrict_marginals_to_operating, which replaced the
multiplicative young-plant widener), in_sample=False. Source of record:
experiments/wind_per_plant/{RESULTS.md, outputs/ship_artifact, outputs/diagnose}.

Six figures into docs/figures/wind_v3/:
  1. scenario_per_plant_coverage.png  - per-plant 80% coverage scorecard (by zone, young flagged)
  2. scenario_pit_histograms.png      - PIT uniformity: fleet / mature / young
  3. scenario_reliability.png         - empirical vs nominal central-interval coverage
  4. scenarios_fleet_fan_ship_2024.png- fleet fan over a 2024 week at the ship config
  5. scenario_cross_zone_corr.png     - cross-zone correlation: scenario vs empirical truth (s7)
  6. scenario_global_widen_rejected.png- the diagnostic that rejected a global marginal widen

Figs 1-3,5-6 read the committed artifact CSVs (no recompute). Fig 4 re-runs a
week through the shipped path. Run:
    python make_scenario_calibration_figs.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
ROOT = OUT_DIR.parents[2]
PGSCEN = ROOT / "PGscen-2nd"
WPP = ROOT / "experiments" / "wind_per_plant"
ART = WPP / "outputs" / "ship_artifact"
DIAG = WPP / "outputs" / "diagnose"
META = PGSCEN / "data" / "NYISO_real" / "plant_metadata" / "wind_meta.csv"
sys.path.insert(0, str(PGSCEN))
sys.path.insert(0, str(WPP))

warnings.filterwarnings("ignore")

# zone palette (consistent across figures)
ZONES = ["A", "C", "D", "E", "K"]
ZC = {"A": "#2563eb", "C": "#059669", "D": "#d97706", "E": "#7c3aed", "K": "#dc2626"}
C_ACT, C_FC = "#111111", "#1d4ed8"
YOUNG_FROM_YEAR = 2023   # operating_year >= 2023 -> <=2 yr history at 2024 (2023-24 commissions)

meta = pd.read_csv(META).set_index("site_id")
young_ids = set(meta.index[meta["operating_year"] >= YOUNG_FROM_YEAR])
mid_ids = set(meta.index[(meta["operating_year"] == 2021) | (meta["operating_year"] == 2022)])


# ---------------------------------------------------------------------------
# Fig 1 - per-plant coverage scorecard
# ---------------------------------------------------------------------------
def fig_coverage_scorecard():
    pp = pd.read_csv(ART / "per_plant_summary.csv")
    pp["young"] = pp["site_id"].isin(young_ids)
    pp = pp.sort_values(["zone", "cov_80"]).reset_index(drop=True)
    short = pp["name"].str.replace(r",.*", "", regex=True).str.slice(0, 22)

    fig, ax = plt.subplots(figsize=(9, 10))
    y = np.arange(len(pp))[::-1]
    for i, r in pp.iterrows():
        col = ZC[r["zone"]]
        ax.barh(y[i], r["cov_80"], color=col, alpha=0.55 if not r["young"] else 0.95,
                edgecolor="black" if r["young"] else "none",
                hatch="///" if r["young"] else None, height=0.72)
        ax.plot(r["cov_90"], y[i], "D", color="#374151", ms=4, zorder=5)
    ax.axvline(0.80, color="#111", ls="--", lw=1.3)
    ax.axvline(0.90, color="#6b7280", ls=":", lw=1.1)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{z}  {n}" for z, n in zip(pp["zone"], short)], fontsize=7.5)
    ax.set_xlim(0.45, 1.0)
    ax.set_xlabel("coverage (bars = central-80% cov$_{80}$; ◆ = central-90% cov$_{90}$)")
    ax.set_title("Per-plant scenario coverage, 52 held-out 2024 days (ship config: "
                 r"$\rho_{asset}{=}0.5$ + pre-COD marginal fix)", fontsize=11)
    from matplotlib.patches import Patch
    leg = [Patch(facecolor=ZC[z], alpha=0.6, label=f"zone {z}") for z in ZONES]
    leg += [Patch(facecolor="grey", hatch="///", edgecolor="black",
                  label="young (2023–24)"),
            plt.Line2D([], [], marker="D", color="#374151", ls="", label="cov$_{90}$")]
    ax.legend(handles=leg, fontsize=8, loc="lower right", ncol=2)
    ax.text(0.805, len(pp) - 0.5, "target 0.80", fontsize=8, color="#111")
    ax.grid(axis="x", alpha=0.25)
    plt.tight_layout()
    _save(fig, "scenario_per_plant_coverage.png")


# ---------------------------------------------------------------------------
# Fig 2 - PIT histograms
# ---------------------------------------------------------------------------
def fig_pit_histograms():
    pph = pd.read_csv(ART / "per_day_per_plant_per_hour.csv", usecols=["site_id", "pit"])
    fl = pd.read_csv(ART / "fleet_per_day_per_hour.csv", usecols=["pit"])
    pph = pph.dropna(subset=["pit"])
    young_pit = pph.loc[pph["site_id"].isin(young_ids), "pit"].values
    mature_pit = pph.loc[~pph["site_id"].isin(young_ids | mid_ids), "pit"].values

    panels = [("Fleet sum", fl["pit"].dropna().values, "#111827"),
              ("Mature plants (pre-2021)", mature_pit, "#2563eb"),
              ("Young plants (2023–24)", young_pit, "#dc2626")]
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), sharey=True)
    nb = 20
    for ax, (title, v, col) in zip(axes, panels):
        ax.hist(v, bins=nb, range=(0, 1), density=True, color=col, alpha=0.75,
                edgecolor="white")
        ax.axhline(1.0, color="#111", ls="--", lw=1.2)
        ax.set_title(f"{title}\n(n={len(v):,})", fontsize=10)
        ax.set_xlabel("PIT = rank of actual in ensemble")
        ax.set_xlim(0, 1)
    axes[0].set_ylabel("density")
    fig.suptitle("Probability Integral Transform — flat = calibrated; "
                 "∪-shape = under-dispersed", fontsize=11, y=1.02)
    plt.tight_layout()
    _save(fig, "scenario_pit_histograms.png")


# ---------------------------------------------------------------------------
# Fig 3 - reliability diagram (empirical vs nominal central-interval coverage)
# ---------------------------------------------------------------------------
def fig_reliability():
    pph = pd.read_csv(ART / "per_day_per_plant_per_hour.csv", usecols=["site_id", "pit"]).dropna()
    fl = pd.read_csv(ART / "fleet_per_day_per_hour.csv", usecols=["pit"]).dropna()
    young_pit = pph.loc[pph["site_id"].isin(young_ids), "pit"].values
    mature_pit = pph.loc[~pph["site_id"].isin(young_ids | mid_ids), "pit"].values

    cgrid = np.linspace(0.02, 0.98, 49)

    def emp(pit, c):
        lo, hi = (1 - c) / 2, (1 + c) / 2
        return np.mean((pit >= lo) & (pit <= hi))

    series = [("Fleet sum", fl["pit"].values, "#111827", "-"),
              ("Mature plants", mature_pit, "#2563eb", "-"),
              ("Young plants (2023–24)", young_pit, "#dc2626", "-")]
    fig, ax = plt.subplots(figsize=(6.2, 6))
    ax.plot([0, 1], [0, 1], color="#9ca3af", ls="--", lw=1.2, label="perfect calibration")
    for name, pit, col, ls in series:
        ax.plot(cgrid, [emp(pit, c) for c in cgrid], col, ls=ls, lw=2, label=name)
    for c in (0.5, 0.8, 0.9):
        ax.axvline(c, color="#e5e7eb", lw=0.8, zorder=0)
    ax.set_xlabel("nominal central-interval coverage")
    ax.set_ylabel("empirical coverage")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title("Reliability: below the diagonal = under-dispersed\n"
                 "(ship config, 52 held-out 2024 days)", fontsize=11)
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(alpha=0.25)
    plt.tight_layout()
    _save(fig, "scenario_reliability.png")


# ---------------------------------------------------------------------------
# Fig 5 - cross-zone correlation: scenario vs empirical truth
# ---------------------------------------------------------------------------
def fig_cross_zone():
    cz = pd.read_csv(DIAG / "cross_zone_corr.csv")
    # wind-zone pairs first (A,C,D,E), then K pairs
    order = ["A-C", "A-D", "A-E", "C-D", "C-E", "D-E", "A-K", "C-K", "D-K", "E-K"]
    cz = cz.set_index("pair").reindex(order).reset_index()
    x = np.arange(len(cz)); w = 0.38
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.bar(x - w / 2, cz["emp_pearson"], w, color="#111827", alpha=0.85,
           label="empirical truth (actual zonal deviations)")
    ax.bar(x + w / 2, cz["scen_pearson"], w, color="#2563eb", alpha=0.85,
           label="per-plant scenarios (ρ$_{asset}$=0.5)")
    ax.axhline(0, color="#111", lw=0.8)
    ax.axvline(5.5, color="#9ca3af", ls=":", lw=1)
    ax.text(2.5, ax.get_ylim()[1] * 0.92, "wind-zone pairs", ha="center", fontsize=9)
    ax.text(7.5, ax.get_ylim()[1] * 0.92, "offshore K pairs", ha="center", fontsize=9)
    for i, r in cz.iterrows():
        d = r["scen_pearson"] - r["emp_pearson"]
        if abs(d) >= 0.08:
            ax.annotate("over" if d > 0 else "under", (x[i] + w / 2, r["scen_pearson"]),
                        textcoords="offset points", xytext=(0, 3 if d > 0 else -10),
                        ha="center", fontsize=7, color="#b91c1c" if d > 0 else "#b45309")
    ax.set_xticks(x); ax.set_xticklabels(cz["pair"])
    ax.set_ylabel("cross-zone correlation (Pearson)")
    ax.set_title("Cross-zone coupling: a single distance kernel can't match every pair — "
                 "C–D/D–E under, C–E over.\nThey net out at the fleet level (§7).", fontsize=10.5)
    ax.legend(fontsize=9, loc="lower right")
    ax.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    _save(fig, "scenario_cross_zone_corr.png")


# ---------------------------------------------------------------------------
# Fig 6 - the global-widen diagnostic that was rejected
# ---------------------------------------------------------------------------
def fig_global_widen():
    sw = pd.read_csv(DIAG / "marginal_widen_sweep.csv").sort_values("g")
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    ax.axhspan(0.78, 0.82, color="#dcfce7", alpha=0.7, zorder=0)
    ax.axhline(0.80, color="#16a34a", lw=1.2, ls="--", label="target 0.80")
    ax.plot(sw["g"], sw["fleet_cov80"], "-o", color="#111827", lw=2.5, ms=5,
            label="FLEET", zorder=5)
    for z in ZONES:
        ax.plot(sw["g"], sw[f"zone_{z}"], "-", color=ZC[z], lw=1.6, alpha=0.9,
                label=f"zone {z}")
    ax.axvline(1.0, color="#2563eb", lw=1.2, ls=":")
    ax.annotate("ship (g=1.0)\nno global widen", (1.0, 0.50), fontsize=8.5,
                color="#2563eb", ha="center")
    # mark the g needed for fleet 0.80 and the D/E overshoot there
    gstar = sw.loc[(sw["fleet_cov80"] - 0.80).abs().idxmin(), "g"]
    row = sw.loc[sw["g"] == gstar].iloc[0]
    ax.annotate(f"to get FLEET→0.80 needs g≈{gstar:g}\n"
                f"→ D={row['zone_D']:.2f}, E={row['zone_E']:.2f} overshoot; "
                f"A={row['zone_A']:.2f} still short",
                (gstar, 0.93), fontsize=8.5, color="#b91c1c", ha="center",
                bbox=dict(boxstyle="round", fc="#fee2e2", ec="#b91c1c", alpha=0.9))
    ax.set_xlabel("global marginal-widen factor  g  (1.0 = ship, no widen)")
    ax.set_ylabel("cov$_{80}$")
    ax.set_title("Why a global marginal widen was REJECTED: it over-inflates the "
                 "already-wide zones\n(D,E) while A stays short — the deficit is "
                 "heterogeneous, not uniform (§7).", fontsize=10)
    ax.legend(fontsize=8.5, ncol=2, loc="lower right")
    ax.grid(alpha=0.25)
    plt.tight_layout()
    _save(fig, "scenario_global_widen_rejected.png")


# ---------------------------------------------------------------------------
# Fig 4 - fleet fan at the ship config (re-run a 2024 week)
# ---------------------------------------------------------------------------
def fig_fleet_fan(start="2024-10-07", n_days=7, n_scen=1000):
    from run_wind_per_plant import run_one_day, load_wind

    pre = load_wind()

    def ship_run(utc_day, cache):
        if utc_day in cache:
            return cache[utc_day]
        # run_one_day applies the pre-COD marginal fix (ship config) by default
        res = run_one_day(utc_day, nscen=n_scen, asset_rho=0.5, preloaded=pre,
                          seed=abs(hash(utc_day)) % 9999, verbose=False)
        on = res["online"]
        out = {"ts": pd.DatetimeIndex(res["scen_timesteps"]),
               "fleet": res["mw_all"][:, on, :].sum(axis=1),
               "act": np.nansum(res["actual_today"][on], axis=0),
               "fc": res["forecast_today"][on].sum(axis=0),
               "cap": float(res["capacity"][on].sum()), "nplant": int(on.sum())}
        cache[utc_day] = out
        return out

    def stitch_et(et_date, cache):
        w = pd.date_range(pd.Timestamp(et_date, tz="US/Eastern"), periods=24, freq="h",
                          tz="US/Eastern")
        wu = w.tz_convert("UTC")
        a = ship_run(wu[0].normalize().strftime("%Y-%m-%d"), cache)
        b = ship_run(wu[-1].normalize().strftime("%Y-%m-%d"), cache)
        ats = list(a["ts"]) + list(b["ts"])
        idx = {t: i for i, t in enumerate(ats)}
        ii = [idx[t] for t in wu]
        fleet = np.concatenate([a["fleet"], b["fleet"]], axis=1)[:, ii]
        act = np.concatenate([a["act"], b["act"]])[ii]
        fc = np.concatenate([a["fc"], b["fc"]])[ii]
        return fleet, act, fc, a["cap"], a["nplant"]

    et_days = [(pd.Timestamp(start) + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
               for d in range(n_days)]
    cache, runs, cap, npl = {}, [], np.nan, np.nan
    for k, d in enumerate(et_days, 1):
        fleet, act, fc, cap, npl = stitch_et(d, cache)
        runs.append((d, fleet, act, fc))
        print(f"  [{k}/{n_days}] {d}: actual peak {act.max():.0f} MW")

    ncols = 4; nrows = (n_days + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.5 * ncols, 2.8 * nrows),
                             sharey=True, squeeze=False)
    hours = np.arange(24)
    for i, (d, fleet, act, fc) in enumerate(runs):
        ax = axes[i // ncols, i % ncols]
        p5, p25, p75, p95 = np.percentile(fleet, [5, 25, 75, 95], axis=0)
        ax.fill_between(hours, p5, p95, color="#60a5fa", alpha=0.45, label="P5–P95")
        ax.fill_between(hours, p25, p75, color="#2563eb", alpha=0.55, label="P25–P75")
        ax.plot(hours, fc, color=C_FC, lw=1.5, label="day-ahead forecast (MOS)")
        ax.plot(hours, act, color=C_ACT, lw=1.8, label="actual (pluswind_v4)")
        ax.set_title(f"{d} ({pd.Timestamp(d).strftime('%a')})", fontsize=10)
        ax.set_xlim(0, 23); ax.set_xticks([0, 6, 12, 18]); ax.set_ylim(bottom=0)
        ax.grid(alpha=0.25)
    for j in range(n_days, nrows * ncols):
        axes[j // ncols, j % ncols].axis("off")
    for r in range(nrows):
        axes[r, 0].set_ylabel("Fleet MW")
    for c in range(ncols):
        axes[nrows - 1, c].set_xlabel("Hour (US/Eastern)")
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=4, fontsize=10, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle(f"NYISO wind fleet fan, {n_days} Eastern days from {start} — ship config "
                 f"(ρ$_{{asset}}$=0.5 + pre-COD marginal fix), {npl} plants, {cap:.0f} MW, "
                 f"{n_scen} scenarios/day", fontsize=12, y=1.005)
    plt.tight_layout()
    _save(fig, "scenarios_fleet_fan_ship_2024.png")


def fig_per_plant_panels(et_date="2024-10-12", n_scen=1000):
    """Every plant's scenario fan on one Eastern day, ship config — the per-plant
    analogue of the fleet fan (Fig 4). Panels grouped by zone, young plants flagged."""
    from run_wind_per_plant import run_one_day, load_wind

    pre = load_wind()

    def ship_run(utc_day, cache):
        if utc_day in cache:
            return cache[utc_day]
        # run_one_day applies the pre-COD marginal fix (ship config) by default
        res = run_one_day(utc_day, nscen=n_scen, asset_rho=0.5, preloaded=pre,
                          seed=abs(hash(utc_day)) % 9999, verbose=False)
        cache[utc_day] = res
        return res

    # ET window -> the two UTC engine days that cover it
    w = pd.date_range(pd.Timestamp(et_date, tz="US/Eastern"), periods=24, freq="h",
                      tz="US/Eastern")
    wu = w.tz_convert("UTC")
    cache: dict = {}
    ra = ship_run(wu[0].normalize().strftime("%Y-%m-%d"), cache)
    rb = ship_run(wu[-1].normalize().strftime("%Y-%m-%d"), cache)
    all_ts = list(ra["scen_timesteps"]) + list(rb["scen_timesteps"])
    ii = [{t: i for i, t in enumerate(all_ts)}[t] for t in wu]

    # align plants by name across the two runs, keep those online either day
    ia = {a: k for k, a in enumerate(ra["assets"])}
    ib = {a: k for k, a in enumerate(rb["assets"])}
    rows = []
    for a in ra["assets"]:
        if a not in ib:
            continue
        ka, kb = ia[a], ib[a]
        if not (ra["online"][ka] or rb["online"][kb]):
            continue
        mw = np.concatenate([ra["mw_all"][:, ka, :], rb["mw_all"][:, kb, :]], axis=1)[:, ii]
        act = np.concatenate([ra["actual_today"][ka], rb["actual_today"][kb]])[ii]
        fc = np.concatenate([ra["forecast_today"][ka], rb["forecast_today"][kb]])[ii]
        zone = meta.loc[a, "zone"]
        name = str(meta.loc[a, "site_name"]).split(",")[0][:20]
        cap = float(meta.loc[a, "Capacity"]) if "Capacity" in meta.columns \
            else float(meta.loc[a, "nameplate_mw"])
        rows.append({"a": a, "zone": zone, "name": name, "cap": cap,
                     "young": a in young_ids, "mw": mw, "act": act, "fc": fc})
    rows.sort(key=lambda r: (ZONES.index(r["zone"]), -r["cap"]))

    n = len(rows)
    ncols = 6
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(3.1 * ncols, 1.9 * nrows),
                             squeeze=False)
    hours = np.arange(24)
    for i, r in enumerate(rows):
        ax = axes[i // ncols, i % ncols]
        col = ZC[r["zone"]]
        p5, p25, p50, p75, p95 = np.percentile(r["mw"], [5, 25, 50, 75, 95], axis=0)
        ax.fill_between(hours, p5, p95, color=col, alpha=0.22)
        ax.fill_between(hours, p25, p75, color=col, alpha=0.40)
        ax.plot(hours, p50, color=col, lw=1.0)
        ax.plot(hours, r["fc"], color=C_FC, lw=1.0, ls="--")
        ax.plot(hours, r["act"], color=C_ACT, lw=1.3)
        ax.axhline(r["cap"], color="#9ca3af", ls=":", lw=0.7)
        tcol = "#b91c1c" if r["young"] else "#111827"
        ax.set_title(f"{r['zone']}  {r['name']}" + ("  ◦young" if r["young"] else ""),
                     fontsize=7.5, color=tcol)
        ax.set_xlim(0, 23); ax.set_xticks([0, 12]); ax.set_ylim(bottom=0)
        ax.tick_params(labelsize=6); ax.grid(alpha=0.2)
    for j in range(n, nrows * ncols):
        axes[j // ncols, j % ncols].axis("off")

    from matplotlib.patches import Patch
    leg = [Patch(facecolor="#6b7280", alpha=0.40, label="P25–P75"),
           Patch(facecolor="#6b7280", alpha=0.22, label="P5–P95"),
           plt.Line2D([], [], color=C_ACT, lw=1.3, label="actual (v4)"),
           plt.Line2D([], [], color=C_FC, lw=1.0, ls="--", label="forecast (MOS)"),
           plt.Line2D([], [], color="#9ca3af", ls=":", lw=0.7, label="nameplate")]
    fig.legend(handles=leg, loc="lower center", ncol=5, fontsize=9,
               bbox_to_anchor=(0.5, -0.012))
    fig.suptitle(f"Per-plant scenario fans, Eastern day {et_date} — ship config "
                 f"(ρ$_{{asset}}$=0.5 + pre-COD marginal fix), {n} plants online, "
                 f"{n_scen} scenarios/day. Fan color = zone; red title = young (2023–24).",
                 fontsize=11, y=1.003)
    plt.tight_layout()
    _save(fig, "scenario_per_plant_panels_ship_2024.png")


def _save(fig, name):
    out = OUT_DIR / name
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out.name}")


if __name__ == "__main__":
    print("Building scenario calibration figures (ship config) ...")
    fig_coverage_scorecard()
    fig_pit_histograms()
    fig_reliability()
    fig_cross_zone()
    fig_global_widen()
    fig_fleet_fan()
    fig_per_plant_panels()
    print("done.")
