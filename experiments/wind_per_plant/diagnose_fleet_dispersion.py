"""Decompose the fleet wind under-dispersion at asset_rho=0.5 into its two sources.

Motivation (RESULTS.md s4 + reviewer ask). At the cross-zone-corrected
`asset_rho=0.5`, per-plant and per-zone coverage are on target (per-zone cov_80
~0.75-0.83) but the FLEET-sum cov_80 falls to 0.72. A fleet that is more
under-dispersed than any of its component zones can only get that way from the
CROSS-ZONE COUPLING (the zone sums are individually well-sized but don't add up to
enough fleet spread), not from narrow per-plant/zone marginals. Before building any
global marginal widener we test that claim, because if the deficit is the copula a
marginal widen is the wrong tool (it would over-widen already-correct marginals).

Two independent decompositions, both at the 5-zone level (A,C,D,E,K):

  (1) ANALYTIC VARIANCE DECOMPOSITION (Pearson).
      Fleet deviation D = sum_z d_z. Var(D) = 1' [diag(sigma) C diag(sigma)] 1.
      - empirical  : sigma_e, C_e from the realized zonal ACTUAL deviations
      - scenario   : sigma_s, C_s from the pooled zonal SCENARIO deviations
      - CF-marginal: Var with empirical marginals but the SCENARIO copula -> how much
                     of the V_e - V_s gap closes if only marginals were fixed
      - CF-copula  : Var with scenario marginals but the EMPIRICAL copula -> how much
                     closes if only the cross-zone coupling were fixed
      Whichever closes more of the gap is the dominant lever.

  (2) COVERAGE COUNTERFACTUALS (the operational metric).
      - CF-copula : Iman-Conover re-couple each (day,hour) zone-sum ensemble to the
                    empirical cross-zone rank-correlation, marginals UNTOUCHED;
                    recompute fleet cov_80. If it recovers ~0.80 the copula is the cause.
      - CF-marginal: widen each zone-sum deviation by a global factor g (copula kept);
                    report fleet AND per-zone cov_80(g). If lifting the fleet to 0.80
                    forces the per-zone coverage to badly overshoot, marginals are the
                    wrong tool.

Caveat (Per_Plant_Wind_Plan.md s9): "actual" is the v4 modeled potential the engine
was fit on, so this is self-consistency, not metered truth -- same basis as RESULTS.

Run:
    python diagnose_fleet_dispersion.py --asset-rho 0.5
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from run_wind_per_plant import run_one_day, load_wind  # noqa: E402

WIND_META = Path("/Users/val/Desktop/Princeton/PGscen-2nd/data/NYISO_real/"
                 "plant_metadata/wind_meta.csv")
ZONES = ["A", "C", "D", "E", "K"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def cov_80(scen_col: np.ndarray, y: float) -> float:
    """1 if y in [p10,p90] of the ensemble, else 0 (NaN if y not finite)."""
    if not np.isfinite(y):
        return np.nan
    p10, p90 = np.quantile(scen_col, [0.10, 0.90])
    return float(p10 <= y <= p90)


def _nearest_pd(C: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """Symmetrize and floor eigenvalues so C is positive-definite (for Cholesky)."""
    C = 0.5 * (C + C.T)
    w, V = np.linalg.eigh(C)
    w = np.clip(w, eps, None)
    C2 = (V * w) @ V.T
    d = np.sqrt(np.diag(C2))
    return C2 / np.outer(d, d)


def iman_conover(X: np.ndarray, target_corr: np.ndarray, rng) -> np.ndarray:
    """Reorder the columns of X so their rank-correlation matches `target_corr`,
    leaving every column's marginal (its multiset of values) exactly unchanged."""
    n, k = X.shape
    vdw = np.sort(_norm_ppf((np.arange(1, n + 1)) / (n + 1)))
    M = np.empty((n, k))
    for j in range(k):
        M[:, j] = rng.permutation(vdw)
    M = (M - M.mean(0)) / M.std(0)
    T = np.corrcoef(M, rowvar=False)
    P = np.linalg.cholesky(_nearest_pd(target_corr))
    Q = np.linalg.cholesky(_nearest_pd(T))
    Mstar = M @ np.linalg.inv(Q.T) @ P.T
    Y = np.empty_like(X)
    for j in range(k):
        order = np.argsort(np.argsort(Mstar[:, j]))   # rank 0..n-1
        Y[:, j] = np.sort(X[:, j])[order]
    return Y


def _norm_ppf(p):
    """Inverse standard-normal CDF (scipy if present, else Acklam approximation)."""
    try:
        from scipy.stats import norm
        return norm.ppf(p)
    except Exception:
        p = np.asarray(p, dtype=float)
        a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
        d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
             3.754408661907416e+00]
        plow, phigh = 0.02425, 1 - 0.02425
        x = np.empty_like(p)
        lo, hi = p < plow, p > phigh
        mid = ~(lo | hi)
        q = np.sqrt(-2 * np.log(p[lo]))
        x[lo] = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        q = np.sqrt(-2 * np.log(1 - p[hi]))
        x[hi] = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                 ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        q = p[mid] - 0.5
        r = q * q
        x[mid] = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
                 (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
        return x


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default="2024-01-03")
    p.add_argument("--end", default="2024-12-25")
    p.add_argument("--step-days", type=int, default=7)
    p.add_argument("--nscen", type=int, default=1000)
    p.add_argument("--asset-rho", type=float, default=0.5)
    p.add_argument("--time-rho", type=float, default=0.05)
    p.add_argument("--nearest-days", type=int, default=None)
    p.add_argument("--years", type=int, nargs="+",
                   default=[2018, 2019, 2020, 2021, 2022, 2023, 2024])
    p.add_argument("--g-grid", type=float, nargs="+",
                   default=[1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.4, 1.5])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", default=str(THIS_DIR / "outputs" / "diagnose"))
    args = p.parse_args()

    days = [d.strftime("%Y-%m-%d")
            for d in pd.date_range(args.start, args.end, freq=f"{args.step_days}D")]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = pd.read_csv(WIND_META).set_index("site_id")
    zone_of = meta["zone"].to_dict()

    print("=== Fleet-dispersion decomposition (asset_rho="
          f"{args.asset_rho}) ===")
    print(f"days: {len(days)} ({days[0]} -> {days[-1]}, every {args.step_days}d, UTC)"
          f"   nscen={args.nscen}")

    print("\npre-loading wind data once ...")
    t0 = time.time()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = load_wind(years=args.years)
    print(f"  actuals {pre[0].shape}, {len(pre[2])} plants ({time.time()-t0:.1f}s)")

    # per-(day,hour) stores, zone order = ZONES
    Z_list = []          # each (nscen, 5) zone-sum scenario MW
    za_list = []         # each (5,) zone-sum actual MW
    zf_list = []         # each (5,) zone-sum forecast MW
    t_loop = time.time()
    for i, day in enumerate(days):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = run_one_day(day, nscen=args.nscen, asset_rho=args.asset_rho,
                                  time_rho=args.time_rho, nearest_days=args.nearest_days,
                                  preloaded=pre, seed=args.seed + i, verbose=False)
        except Exception as e:
            print(f"  [{i+1}/{len(days)}] {day}: FAILED {type(e).__name__}: {e}")
            continue

        assets = res["assets"]
        mw = res["mw_all"]            # (nscen, n_asset, 24)
        act = res["actual_today"]     # (n_asset, 24) NaN offline
        fc = res["forecast_today"]    # (n_asset, 24)
        online = res["online"]
        zidx = {z: [ai for ai, a in enumerate(assets)
                    if zone_of.get(a) == z and online[ai]] for z in ZONES}

        for h in range(24):
            Zh = np.empty((args.nscen, len(ZONES)))
            zah = np.empty(len(ZONES))
            zfh = np.empty(len(ZONES))
            ok = True
            for zj, z in enumerate(ZONES):
                idx = zidx[z]
                if not idx:
                    Zh[:, zj] = 0.0
                    zah[zj] = np.nan
                    zfh[zj] = 0.0
                    continue
                Zh[:, zj] = mw[:, idx, h].sum(axis=1)
                zah[zj] = np.nansum(act[idx, h])
                zfh[zj] = fc[idx, h].sum()
            Z_list.append(Zh)
            za_list.append(zah)
            zf_list.append(zfh)

        if (i + 1) % 10 == 0 or i == len(days) - 1:
            el = time.time() - t_loop
            eta = el / (i + 1) * (len(days) - i - 1)
            print(f"  [{i+1}/{len(days)}] {day}  ({el/60:.1f}m, eta {eta/60:.1f}m)")

    nrec = len(Z_list)
    za = np.array(za_list)            # (nrec, 5)
    zf = np.array(zf_list)            # (nrec, 5)
    # keep only records where every zone has a finite actual (apples-to-apples fleet)
    keep = np.isfinite(za).all(axis=1)
    Z_list = [Z_list[k] for k in range(nrec) if keep[k]]
    za, zf = za[keep], zf[keep]
    print(f"\nrecords (day-hours): {len(Z_list)} kept of {nrec} "
          f"({100*keep.mean():.0f}% all-zones-online)")

    # ---- pooled deviations -------------------------------------------------
    act_dev = za - zf                                    # (nrec, 5)
    scen_dev = np.concatenate([Z_list[k] - zf[k][None, :]
                               for k in range(len(Z_list))], axis=0)  # (nrec*nscen, 5)
    fleet_act_dev = act_dev.sum(axis=1)                  # (nrec,)
    fleet_scen_dev = scen_dev.sum(axis=1)               # (nrec*nscen,)

    sigma_e = act_dev.std(axis=0)                        # (5,)
    sigma_s = scen_dev.std(axis=0)                       # (5,)
    C_e = np.corrcoef(act_dev, rowvar=False)             # Pearson, empirical
    C_s = np.corrcoef(scen_dev, rowvar=False)            # Pearson, scenario
    C_e_spear = pd.DataFrame(act_dev, columns=ZONES).corr("spearman").values

    def fleet_var(sigma, C):
        S = np.outer(sigma, sigma) * C
        return float(np.ones(len(sigma)) @ S @ np.ones(len(sigma)))

    V_e = float(np.var(fleet_act_dev))
    V_s = float(np.var(fleet_scen_dev))
    V_e_analytic = fleet_var(sigma_e, C_e)              # == V_e (check)
    V_cf_marg = fleet_var(sigma_e, C_s)                # empirical marg, scen copula
    V_cf_cop = fleet_var(sigma_s, C_e)                 # scen marg, empirical copula
    gap = V_e - V_s
    frac_marg = (V_cf_marg - V_s) / gap if gap else np.nan
    frac_cop = (V_cf_cop - V_s) / gap if gap else np.nan

    print("\n=== (1) ANALYTIC VARIANCE DECOMPOSITION (zone-level Pearson) ===")
    print(f"  fleet Var  empirical(realized) = {V_e:,.0f}   "
          f"analytic = {V_e_analytic:,.0f}")
    print(f"  fleet Var  scenario           = {V_s:,.0f}   "
          f"(ratio scen/emp = {V_s/V_e:.3f}; <1 => fan too narrow)")
    print(f"  CF fix MARGINALS only (emp sigma, scen copula): Var={V_cf_marg:,.0f}"
          f"  -> closes {100*frac_marg:.0f}% of the gap")
    print(f"  CF fix COPULA   only (scen sigma, emp copula): Var={V_cf_cop:,.0f}"
          f"  -> closes {100*frac_cop:.0f}% of the gap")

    sig_tab = pd.DataFrame({"zone": ZONES, "sigma_emp": sigma_e.round(1),
                            "sigma_scen": sigma_s.round(1),
                            "sigma_ratio_scen_emp": (sigma_s / sigma_e).round(3)})
    print("\n  per-zone marginal std (MW): scenario vs empirical")
    print(sig_tab.to_string(index=False))
    print("    ratio ~1 => zone marginal correctly sized")

    pairs = [(a, b) for ia, a in enumerate(ZONES) for b in ZONES[ia+1:]]
    corr_rows = [{"pair": f"{a}-{b}",
                  "emp_pearson": round(C_e[ZONES.index(a), ZONES.index(b)], 3),
                  "scen_pearson": round(C_s[ZONES.index(a), ZONES.index(b)], 3),
                  "emp_spearman": round(C_e_spear[ZONES.index(a), ZONES.index(b)], 3)}
                 for a, b in pairs]
    corr_tab = pd.DataFrame(corr_rows)
    print("\n  cross-zone correlation: scenario vs empirical")
    print(corr_tab.to_string(index=False))

    # ---- baseline coverage -------------------------------------------------
    def zone_cov(zsel):
        c = [cov_80(Z_list[k][:, zsel], za[k, zsel]) for k in range(len(Z_list))]
        return float(np.nanmean(c))

    def fleet_cov(Zmats):
        c = [cov_80(Zmats[k].sum(axis=1), za[k].sum()) for k in range(len(Zmats))]
        return float(np.nanmean(c))

    base_zone = {z: zone_cov(j) for j, z in enumerate(ZONES)}
    base_fleet = fleet_cov(Z_list)
    print("\n=== (2) COVERAGE COUNTERFACTUALS ===")
    print(f"  baseline per-zone cov_80: "
          + "  ".join(f"{z}={base_zone[z]:.3f}" for z in ZONES))
    print(f"  baseline FLEET cov_80   : {base_fleet:.3f}   (target 0.80)")

    # CF-copula: Iman-Conover re-couple each ensemble to empirical rank-corr
    rng = np.random.default_rng(args.seed)
    try:
        Z_recoupled = [iman_conover(Z_list[k], C_e_spear, rng)
                       for k in range(len(Z_list))]
        cop_fleet = fleet_cov(Z_recoupled)
        cop_zone = {z: float(np.nanmean(
            [cov_80(Z_recoupled[k][:, j], za[k, j]) for k in range(len(Z_list))]))
            for j, z in enumerate(ZONES)}
        print(f"\n  CF-COPULA (re-couple zone sums to empirical corr; marginals fixed):")
        print(f"    FLEET cov_80 {base_fleet:.3f} -> {cop_fleet:.3f}"
              f"   per-zone unchanged: "
              + "  ".join(f"{z}={cop_zone[z]:.3f}" for z in ZONES))
    except Exception as e:
        cop_fleet = np.nan
        print(f"\n  CF-COPULA failed: {type(e).__name__}: {e}")

    # CF-marginal: widen each zone-sum deviation by global g (copula kept)
    print(f"\n  CF-MARGINAL (widen zone-sum deviations by global g; copula fixed):")
    print(f"    {'g':>5} {'fleet':>7} " + " ".join(f"{z:>6}" for z in ZONES))
    marg_rows = []
    for g in args.g_grid:
        Zg = [np.clip(zf[k][None, :] + g * (Z_list[k] - zf[k][None, :]), 0, None)
              for k in range(len(Z_list))]
        fcov = fleet_cov(Zg)
        zcov = {z: float(np.nanmean(
            [cov_80(Zg[k][:, j], za[k, j]) for k in range(len(Z_list))]))
            for j, z in enumerate(ZONES)}
        marg_rows.append({"g": g, "fleet_cov80": fcov,
                          **{f"zone_{z}": zcov[z] for z in ZONES}})
        print(f"    {g:>5.2f} {fcov:>7.3f} " + " ".join(f"{zcov[z]:>6.3f}" for z in ZONES))

    # ---- save --------------------------------------------------------------
    sig_tab.to_csv(out_dir / "zone_marginal_std.csv", index=False)
    corr_tab.to_csv(out_dir / "cross_zone_corr.csv", index=False)
    pd.DataFrame([{
        "V_emp": V_e, "V_scen": V_s, "V_cf_marginal": V_cf_marg,
        "V_cf_copula": V_cf_cop, "gap_frac_marginal": frac_marg,
        "gap_frac_copula": frac_cop, "base_fleet_cov80": base_fleet,
        "cf_copula_fleet_cov80": cop_fleet,
    }]).to_csv(out_dir / "variance_decomposition.csv", index=False)
    pd.DataFrame(marg_rows).to_csv(out_dir / "marginal_widen_sweep.csv", index=False)
    print(f"\nwrote {out_dir}")


if __name__ == "__main__":
    main()
