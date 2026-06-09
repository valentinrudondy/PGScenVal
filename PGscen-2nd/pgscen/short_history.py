"""Short-history marginal regularizer for per-plant wind (production).

Canonical implementation of the young-plant marginal widener validated in
``experiments/wind_per_plant/`` (see ``RESULTS.md`` s5 and
``Per_Plant_Wind_Plan.md`` s7). The 2023-24 commissions have <=2 yr of deviation
history, so GEMINI fits each a too-narrow conditional forecast-error marginal and
its scenario fan under-disperses (cov_80 ~0.60-0.70). This widens each young
plant's scenario deviation around its day-ahead forecast so its
capacity-normalized spread matches the pooled mature-fleet spread.

Marginal-only and copula-preserving: only the per-plant deviation MAGNITUDE grows;
the temporal shape and the inter-plant (geographic) rank dependence are untouched.
It is surgical -- it touches only the young plants, so mature-plant, per-zone and
fleet aggregates move negligibly.

Two appliers share one factor-builder:
  - ``widen_engine_scenarios`` -- production: rescales ``engine.scenarios['wind']``
    in place, before ``engine.write_to_csv`` (what the grid ingests).
  - the experiments prototype ``experiments/wind_per_plant/short_history_reg.py``
    rescales the ``run_one_day`` result tensor (calibration path).

Parity between the two is asserted by
``experiments/wind_per_plant/check_short_history_parity.py``.

NOTE on the global marginal widen: a *fleet-wide* widen was considered and
REJECTED on evidence (``RESULTS.md`` s4 / ``diagnose_fleet_dispersion.py``). The
fleet under-dispersion is heterogeneous in sign across zones (A/K too narrow,
C/D/E already wide) and the cross-zone copula -- not a uniform marginal deficit --
so a single global factor over-inflates the already-wide zones. Only this
targeted young-plant widener ships.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

WIND_META = (Path(__file__).resolve().parents[1] / "data" / "NYISO_real"
             / "plant_metadata" / "wind_meta.csv")


def _cap_norm_dev_std(actual_df, forecast_df, nameplate_mw, site_id):
    """Capacity-normalized std of historical (actual - forecast) for one plant.

    Pools all hours where the plant is operating (excludes the exact-zero/zero
    pre-COD gated hours). Returns np.nan if too few samples (<200).
    """
    if site_id not in actual_df.columns:
        return np.nan
    fc = (forecast_df[["Forecast_time", site_id]]
          .drop_duplicates("Forecast_time", keep="last")
          .set_index("Forecast_time")[site_id])
    a = actual_df[site_id]
    common = a.index.intersection(fc.index)
    if len(common) == 0:
        return np.nan
    f = fc.loc[common].values
    av = a.loc[common].values
    dev = av - f
    operating = ~((np.abs(f) < 1e-9) & (np.abs(av) < 1e-9))
    dev = dev[operating]
    if len(dev) < 200 or not np.isfinite(nameplate_mw) or nameplate_mw <= 0:
        return np.nan
    return float(np.std(dev) / nameplate_mw)


def build_factors(actual_df, forecast_df, scen_year, meta_path=WIND_META,
                  young_max_years=2, mature_min_years=3, cap_floor_factor=1.0):
    """Compute per-plant widening factors for plants with thin history.

    A plant is YOUNG if ``operating_year > scen_year - young_max_years`` (<=2 yr
    by default) and MATURE if ``operating_year <= scen_year - mature_min_years``.
    The target capacity-normalized deviation spread is the median over mature
    plants; each young plant's factor = max(1, target / its_own_cap_norm_std) *
    ``cap_floor_factor`` (>= 1, i.e. only widen, never shrink).

    ``actual_df`` / ``forecast_df`` should be HISTORY (strictly before the
    scenario day) for a leakage-safe estimate; for a forward production run the
    loaded series is naturally history.

    Returns (factors, diag): factors maps young site_id -> factor (>1 only);
    diag is a per-plant DataFrame (operating_year, class, cap_norm_std, factor).
    """
    meta = pd.read_csv(meta_path).set_index("site_id")
    rows = []
    for s in meta.index:
        oy = meta.loc[s, "operating_year"]
        if not np.isfinite(oy):
            cls = "unknown"
        elif oy > scen_year - young_max_years:
            cls = "young"
        elif oy <= scen_year - mature_min_years:
            cls = "mature"
        else:
            cls = "mid"
        std = _cap_norm_dev_std(actual_df, forecast_df,
                                float(meta.loc[s, "nameplate_mw"]), s)
        rows.append({"site_id": s, "operating_year": oy, "class": cls,
                     "cap_norm_std": std})
    diag = pd.DataFrame(rows)

    mature_std = diag.loc[diag["class"] == "mature", "cap_norm_std"].median()
    factors, fcol = {}, []
    for _, r in diag.iterrows():
        if r["class"] == "young" and np.isfinite(r["cap_norm_std"]) \
                and r["cap_norm_std"] > 1e-6:
            f = max(1.0, float(mature_std / r["cap_norm_std"]) * cap_floor_factor)
            factors[r["site_id"]] = f
            fcol.append(f)
        else:
            fcol.append(np.nan)
    diag["factor"] = fcol
    diag["mature_target_std"] = mature_std
    return factors, diag


def widen_engine_scenarios(engine, forecast_future, scen_timesteps, factors):
    """Rescale young-plant scenario deviations in ``engine.scenarios['wind']``.

    For each young plant p with factor f and each scenario-day hour t:
        scen' = clip(fcst_pt + f * (scen - fcst_pt), 0, capacity_p)
    Modifies ``engine.scenarios['wind']`` in place so a subsequent
    ``engine.write_to_csv`` emits the widened per-plant scenarios. No-op if
    ``factors`` is empty.
    """
    if not factors:
        return
    scen = engine.scenarios["wind"]
    issue = engine.forecast_issue_time
    fcb = (forecast_future[forecast_future["Issue_time"] == issue]
           .drop(columns="Issue_time")
           .set_index("Forecast_time").reindex(scen_timesteps))
    cap = engine.meta_df["Capacity"]
    top_assets = set(scen.columns.get_level_values(0))
    for a, f in factors.items():
        if f <= 1.0 or a not in top_assets:
            continue
        capa = float(cap[a])
        for t in scen_timesteps:
            key = (a, t)
            if key not in scen.columns:
                continue
            fc = float(fcb.loc[t, a])
            scen[key] = np.clip(fc + f * (scen[key].values - fc), 0.0, capa)
