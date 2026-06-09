"""Young-plant marginal handling for per-plant wind (production).

SHIPPED (RESULTS.md s9): ``restrict_marginals_to_operating`` -- the pre-COD
marginal fix. Plants commissioned inside the training window have forecast =
actual = 0 for every pre-commissioning hour (deviation = 0); at a LOW scenario
forecast the conditional-marginal bin sweeps in all those pre-COD zeros and the
scenario fan collapses to a point mass at the forecast. This drops each plant's
pre-commissioning rows from the conditional-marginal data (between ``engine.fit``
and ``engine.create_scenario``), which brings the whole young/new cohort -- and the
2021 Cassadaga/Roaring Brook pair -- onto target (cov_80 0.79-0.82). It is the
shipped young-plant treatment in ``scripts/10_run_pgscen_wind.py``
(``--precod-marginal-fix``) and in ``run_wind_per_plant.run_one_day``.

RETAINED BUT SUPERSEDED: the multiplicative widener below
(``build_factors`` + ``widen_engine_scenarios``) was the *original* young-plant
mitigation. It widened each young plant's deviation to the mature-fleet spread, but
it cannot fix a point mass (``f * 0 = 0``) and never saw the pollution (its target
is an operating-only std), so it was replaced by the pre-COD fix (RESULTS.md s5 ->
s9). The code is kept for the parity test
``experiments/wind_per_plant/check_short_history_parity.py`` and the experiments
prototype ``experiments/wind_per_plant/short_history_reg.py``; it is NOT in the
ship path.

NOTE on the global marginal widen: a *fleet-wide* widen was also considered and
REJECTED on evidence (RESULTS.md s7 / ``diagnose_fleet_dispersion.py``): the fleet
under-dispersion is heterogeneous in sign across zones (A/K too narrow, C/D/E
already wide) and is a cross-zone copula matter, not a uniform marginal deficit, so
a single global factor over-inflates the already-wide zones.
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


def restrict_marginals_to_operating(engine, eps=1e-6):
    """Drop each plant's PRE-COMMISSIONING history from the conditional-marginal
    data, in place, before scenario generation.

    Root cause this fixes (found 2026-06-09). ``fit_conditional_marginal_dist``
    builds a per-(plant, horizon) marginal by binning historical deviations whose
    *forecast* is within ``bin_width_ratio`` of the scenario-day forecast. For a
    plant commissioned inside the training window, every pre-COD hour has
    forecast = actual = 0 (the physics gates it off), so deviation = 0. At a LOW
    scenario forecast the bin ``[0, ~range*ratio]`` sweeps in all of those pre-COD
    zeros, so the marginal becomes a dominant point mass at 0 and the scenario fan
    collapses onto the forecast (zero width) at low-forecast hours -- e.g. a 2024
    plant whose history is ~89% pre-COD zeros emits ~90% of scenarios exactly at
    the forecast. This under-represents uncertainty exactly where the young/new
    plants are already weakest.

    The multiplicative widener below cannot fix this (it scales deviations, and
    ``f * 0 = 0``). The correct fix is to not let a plant's pre-existence define
    its uncertainty: restrict each plant's ``deviation_dict`` to rows at or after
    its first operating hour (first hour with non-zero forecast or actual). The
    joint copula (``gauss_df``, fit in the model constructor) is left untouched;
    only the back-transform marginal is cleaned.

    Call AFTER ``engine.fit()`` and BEFORE ``engine.create_scenario()``. Applies to
    every plant, so plants commissioned anywhere in the window (e.g. the 2021
    cohort) benefit, not only the youngest. Returns {asset: (n_before, n_after)}
    for the plants that were trimmed.
    """
    dd = engine.model.deviation_dict
    trimmed = {}
    for a, df in dd.items():
        df = df.sort_index()
        operating = (df["Actual"].abs() > eps) | (df["Forecast"].abs() > eps)
        if not operating.any():
            continue
        pos = int(np.argmax(operating.values))   # first operating row (first True)
        if pos == 0:
            dd[a] = df
            continue
        dd[a] = df.iloc[pos:]
        trimmed[a] = (len(df), len(dd[a]))
    return trimmed


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
