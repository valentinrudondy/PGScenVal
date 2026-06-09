"""Short-history marginal regularizer for per-plant wind (Per_Plant_Wind_Plan.md s7).

The 52-day held-out calibration showed the per-plant fan is well-calibrated for
established plants (cov_80 0.80-0.87) but under-dispersed for the 2023-24
commissions (Bluestone 0.60, Ball Hill 0.63, Baron 0.66, Number Three 0.66, South
Fork 0.69). Cause: GEMINI fits each plant's conditional forecast-error marginal from
that plant's OWN deviation history, and a plant with <=2 years has a too-narrow
marginal. The zonal-sum design used to average this away; per-plant exposes it.

Fix (marginal-only, copula-preserving): for each young plant, rescale its scenario
deviations around the forecast so its capacity-normalized spread matches the pooled
mature-fleet spread. This widens only the magnitude of the per-plant deviation; it
leaves the temporal pattern and the inter-plant rank dependence (the geographic
copula) untouched. It is gated on evidence: we report young-plant coverage before
and after, and leave mature plants and the fleet sum unchanged.

Functions
---------
build_factors(pre, scen_day, ...) -> (factors: dict[site_id->float], diag: DataFrame)
widen(res, factors) -> None    # rescales res['mw_all'] in place, refreshes 'fleet'
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

WIND_META = Path("/Users/val/Desktop/Princeton/PGscen-2nd/data/NYISO_real/"
                 "plant_metadata/wind_meta.csv")


def _cap_norm_dev_std(actual_df, forecast_df, meta, site_id):
    """Capacity-normalized std of historical (actual - forecast) for one plant.

    Pools all hours where the plant is operating (excludes the exact-zero/zero
    pre-COD gated hours). Returns np.nan if too few samples.
    """
    if site_id not in actual_df.columns:
        return np.nan
    cap = float(meta.loc[site_id, "nameplate_mw"])
    fc = (forecast_df[["Forecast_time", site_id]]
          .drop_duplicates("Forecast_time", keep="last")
          .set_index("Forecast_time")[site_id])
    a = actual_df[site_id]
    common = a.index.intersection(fc.index)
    if len(common) == 0:
        return np.nan
    dev = (a.loc[common].values - fc.loc[common].values)
    f = fc.loc[common].values
    av = a.loc[common].values
    operating = ~((np.abs(f) < 1e-9) & (np.abs(av) < 1e-9))
    dev = dev[operating]
    if len(dev) < 200:
        return np.nan
    return float(np.std(dev) / cap)


def build_factors(pre, scen_day, young_max_years=2, mature_min_years=3,
                  cap_floor_factor=1.0, verbose=False):
    """Compute per-plant widening factors for plants with thin history.

    A plant is YOUNG if operating_year > scen_year - young_max_years (<=2 yr by
    default) and MATURE if operating_year <= scen_year - mature_min_years. The
    target capacity-normalized deviation spread is pooled (median) over mature
    plants; each young plant's factor = target / its_own_cap_norm_std (>= 1, i.e.
    only widen, never shrink).

    Returns (factors, diag): factors maps young site_id -> factor; diag is a per-
    plant DataFrame (cap_norm_std, class, factor).
    """
    actual_df, forecast_df, _ = pre
    meta = pd.read_csv(WIND_META).set_index("site_id")
    scen_year = pd.Timestamp(scen_day).year

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
        std = _cap_norm_dev_std(actual_df, forecast_df, meta, s)
        rows.append({"site_id": s, "operating_year": oy, "class": cls,
                     "cap_norm_std": std})
    diag = pd.DataFrame(rows)

    mature_std = diag.loc[diag["class"] == "mature", "cap_norm_std"].median()
    factors = {}
    fcol = []
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

    if verbose:
        print(f"  mature target cap-norm dev std = {mature_std:.4f}")
        print(diag[diag["class"] == "young"][
            ["site_id", "operating_year", "cap_norm_std", "factor"]]
            .round(3).to_string(index=False))
    return factors, diag


def widen(res, factors):
    """Rescale young-plant scenario deviations around the forecast, in place.

    For each young plant p with factor f: scen' = clip(fcst + f*(scen - fcst), 0, cap).
    Preserves the temporal shape and the inter-plant copula; only the per-plant
    deviation magnitude grows. Refreshes res['fleet'].
    """
    if not factors:
        return
    assets = res["assets"]
    mw = res["mw_all"]                    # (nscen, n_asset, 24)
    fc = res["forecast_today"]            # (n_asset, 24)
    cap = res["capacity"]
    for ai, a in enumerate(assets):
        f = factors.get(a)
        if f is None or f <= 1.0:
            continue
        dev = mw[:, ai, :] - fc[ai, :][None, :]
        mw[:, ai, :] = np.clip(fc[ai, :][None, :] + f * dev,
                               a_min=0.0, a_max=cap[ai])
    res["fleet"] = mw.sum(axis=1)
