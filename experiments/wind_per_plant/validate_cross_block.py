"""Decision-gate validation for the per-plant wind plan (Per_Plant_Wind_Plan.md s5-s6).

The honest weak point of "drop the zonal layer" is that the geographic asset_rho
has not been *shown* to carry the within-/cross-zone coupling that Stage A fit
explicitly (WIND_A<->WIND_C = 0.62). Two checks:

  PART A (s6) -- cross-block reconstruction.
    Generate per-plant scenarios over a day sweep, SUM plants to their NYISO zone,
    and check the zonal fan: (i) is the zone-sum well-dispersed (coverage), and
    (ii) do the cross-zone correlations of the zonal scenario deviations reproduce
    the empirical cross-zone correlations of the zonal ACTUAL deviations, and Stage
    A's fitted values? If yes, per-plant carries the zonal structure for free and
    Stage C is redundant. If the per-plant scenarios are too independent (geo rho
    over-shrinks), the zone sums under-disperse and cross-zone corr collapses --
    which would be the one result that rescues the zonal+Stage-C route.

  PART B (s5) -- load<->wind tail co-occurrence.
    A near-zero linear correlation cannot see tail dependence. Measure the empirical
    joint-tail frequency lambda = P(total wind in bottom 5% AND total load in top 5%)
    on aligned forecast deviations, vs the 0.0025 independence implies. If lambda ~
    0.0025 (within sampling noise) independence is defended IN THE TAIL, not just the
    mean -- closing the gap the bare 0.008 correlation leaves open.

Correlations are reported as Spearman (rank) -- invariant to the marginal transform,
so directly comparable to Stage A's gaussianized-deviation correlations.

Run (after the calibration sweep, to avoid CPU contention):
    python validate_cross_block.py --part A
    python validate_cross_block.py --part B
    python validate_cross_block.py            # both
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

SHARED_DIR = Path("/Users/val/Desktop/Princeton/experiments/_shared")
WIND_META = Path("/Users/val/Desktop/Princeton/PGscen-2nd/data/NYISO_real/"
                 "plant_metadata/wind_meta.csv")
WIND_ZONES = ["A", "C", "D", "E"]   # Stage A wind-bearing zones (K handled separately)


# ---------------------------------------------------------------------------
# PART A -- cross-block reconstruction from per-plant scenarios
# ---------------------------------------------------------------------------

def part_a(days, nscen, asset_rho, time_rho, nearest_days, years, out_dir):
    meta = pd.read_csv(WIND_META).set_index("site_id")
    zone_of = meta["zone"].to_dict()

    print("pre-loading wind data ...")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pre = load_wind(years=years)
    assets_all = list(pre[2]["Facility.Name"])
    # plant index lists per zone (within the engine's asset order, resolved per day)

    # accumulators
    scen_dev_samples = {z: [] for z in WIND_ZONES}   # pooled (day*hour*scen) zonal scen deviations
    act_dev_rows = []                                 # one 4-vec per (day,hour): zonal actual deviation
    zonal_cov = {z: {"in80": [], "in90": [], "bias": []} for z in WIND_ZONES + ["K"]}

    t_loop = time.time()
    for i, day in enumerate(days):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = run_one_day(day, nscen=nscen, asset_rho=asset_rho,
                                  time_rho=time_rho, nearest_days=nearest_days,
                                  preloaded=pre, seed=i, verbose=False)
        except Exception as e:
            print(f"  [{i+1}/{len(days)}] {day}: FAILED {e}")
            continue

        assets = res["assets"]
        mw = res["mw_all"]            # (nscen, n_asset, 24)
        act = res["actual_today"]     # (n_asset, 24) NaN offline
        fc = res["forecast_today"]    # (n_asset, 24)
        online = res["online"]
        # zone -> indices of online plants in this day's asset order
        zidx = {z: [ai for ai, a in enumerate(assets)
                    if zone_of.get(a) == z and online[ai]]
                for z in WIND_ZONES + ["K"]}

        # zonal scenario / actual / forecast sums
        zscen = {z: mw[:, zidx[z], :].sum(axis=1) for z in zidx}            # (nscen,24)
        zact = {z: np.nansum(act[zidx[z], :], axis=0) for z in zidx}        # (24,)
        zfc = {z: fc[zidx[z], :].sum(axis=0) for z in zidx}                 # (24,)

        # coverage of the zone sum (is it well-dispersed?)
        for z in zidx:
            if not zidx[z]:
                continue
            for h in range(24):
                col = zscen[z][:, h]
                y = zact[z][h]
                p10, p50, p90, p05, p95 = np.quantile(col, [.1, .5, .9, .05, .95])
                zonal_cov[z]["in80"].append(float(p10 <= y <= p90))
                zonal_cov[z]["in90"].append(float(p05 <= y <= p95))
                zonal_cov[z]["bias"].append(float(y - p50))

        # deviation samples for cross-zone correlation (wind zones only)
        for h in range(24):
            act_dev_rows.append([zact[z][h] - zfc[z][h] for z in WIND_ZONES])
            for z in WIND_ZONES:
                scen_dev_samples[z].append(zscen[z][:, h] - zfc[z][h])

        if (i + 1) % 10 == 0 or i == len(days) - 1:
            el = time.time() - t_loop
            print(f"  [{i+1}/{len(days)}] {day}  ({el/60:.1f}m)")

    # --- assemble correlation matrices (Spearman)
    scen_dev = pd.DataFrame(
        {z: np.concatenate(scen_dev_samples[z]) for z in WIND_ZONES})
    act_dev = pd.DataFrame(act_dev_rows, columns=WIND_ZONES)
    scen_corr = scen_dev.corr(method="spearman")
    act_corr = act_dev.corr(method="spearman")

    # Stage A reference (gaussianized within-wind block)
    ref = pd.read_csv(STAGE_A_DIR / "outputs" / "correlation" /
                      "corr_gaussianized_deviations.csv", index_col=0)
    ref_wind = ref.loc[[f"WIND_{z}" for z in WIND_ZONES],
                       [f"WIND_{z}" for z in WIND_ZONES]]
    ref_wind.index = WIND_ZONES
    ref_wind.columns = WIND_ZONES

    out_dir.mkdir(parents=True, exist_ok=True)
    scen_corr.to_csv(out_dir / "zonal_scenario_dev_corr.csv")
    act_corr.to_csv(out_dir / "zonal_actual_dev_corr.csv")

    # coverage table
    cov_rows = []
    for z in WIND_ZONES + ["K"]:
        if not zonal_cov[z]["in80"]:
            continue
        cov_rows.append({
            "zone": z, "n": len(zonal_cov[z]["in80"]),
            "cov_80": float(np.mean(zonal_cov[z]["in80"])),
            "cov_90": float(np.mean(zonal_cov[z]["in90"])),
            "mean_bias_mw": float(np.mean(zonal_cov[z]["bias"])),
        })
    cov_df = pd.DataFrame(cov_rows)
    cov_df.to_csv(out_dir / "zonal_coverage.csv", index=False)

    # off-diagonal comparison
    pairs = [(a, b) for ii, a in enumerate(WIND_ZONES) for b in WIND_ZONES[ii+1:]]
    cmp_rows = []
    for a, b in pairs:
        cmp_rows.append({
            "pair": f"{a}-{b}",
            "stage_a_gaussianized": round(float(ref_wind.loc[a, b]), 3),
            "per_plant_actual_devs": round(float(act_corr.loc[a, b]), 3),
            "per_plant_scenario_devs": round(float(scen_corr.loc[a, b]), 3),
        })
    cmp = pd.DataFrame(cmp_rows)
    cmp.to_csv(out_dir / "cross_zone_corr_comparison.csv", index=False)

    print("\n=== PART A: zone-sum coverage (per-plant scenarios summed to zones) ===")
    print(cov_df.round(3).to_string(index=False))
    print("  (target cov_80=0.80, cov_90=0.90)")
    print("\n=== PART A: cross-zone wind correlation (Spearman) ===")
    print(cmp.to_string(index=False))
    print("  stage_a = Stage A's fitted gaussianized within-wind block")
    print("  per_plant_actual = empirical truth (zonal actual deviations)")
    print("  per_plant_scenario = what the per-plant fan reproduces")
    print(f"\nwrote {out_dir}")


# ---------------------------------------------------------------------------
# PART B -- load<->wind tail co-occurrence
# ---------------------------------------------------------------------------

def part_b(years, out_dir):
    sys.path.insert(0, str(SHARED_DIR))
    from load_wind_io import build_joint_inputs, WIND_ZONES as WZ  # noqa: E402

    print("building aligned 8-dim joint load+wind inputs ...")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ja, jf, _ = build_joint_inputs(years)

    # align forecast (one row per Forecast_time) to the actuals index
    fc = (jf.drop_duplicates("Forecast_time", keep="last")
          .set_index("Forecast_time"))
    if fc.index.tz is None:
        fc.index = fc.index.tz_localize("UTC")
    common = ja.index.intersection(fc.index)
    ja, fc = ja.loc[common], fc.loc[common]

    load_cols = [f"LOAD_{z}" for z in WZ]
    wind_cols = [f"WIND_{z}" for z in WZ]
    # total load / total wind day-ahead deviations
    dev_load = (ja[load_cols].sum(axis=1) - fc[load_cols].sum(axis=1)).values
    dev_wind = (ja[wind_cols].sum(axis=1) - fc[wind_cols].sum(axis=1)).values
    m = np.isfinite(dev_load) & np.isfinite(dev_wind)
    dev_load, dev_wind = dev_load[m], dev_wind[m]
    n = len(dev_load)

    # thresholds: load high tail (top 5%), wind low tail (bottom 5%)
    load_hi = np.quantile(dev_load, 0.95)
    wind_lo = np.quantile(dev_wind, 0.05)
    joint = np.mean((dev_load >= load_hi) & (dev_wind <= wind_lo))
    indep = 0.05 * 0.05

    # also the symmetric stress corner P(load top5 & wind top5) and overall corr
    pear = float(np.corrcoef(dev_load, dev_wind)[0, 1])
    spear = float(pd.Series(dev_load).corr(pd.Series(dev_wind), method="spearman"))

    out_dir.mkdir(parents=True, exist_ok=True)
    res = pd.DataFrame([{
        "n_hours": n,
        "pearson_total_dev": round(pear, 4),
        "spearman_total_dev": round(spear, 4),
        "lambda_empirical_windlow_loadhigh": round(float(joint), 5),
        "lambda_independence": indep,
        "ratio_emp_over_indep": round(float(joint) / indep, 2),
    }])
    res.to_csv(out_dir / "load_wind_tail_cooccurrence.csv", index=False)

    print("\n=== PART B: load<->wind total-deviation tail co-occurrence ===")
    print(res.to_string(index=False))
    print(f"\n  lambda = P(total wind in bottom 5%  AND  total load in top 5%)")
    print(f"  independence predicts 0.05 x 0.05 = 0.0025")
    print(f"  ratio ~1 => independence holds in the joint stress tail (UC-relevant)")
    print(f"\nwrote {out_dir}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--part", choices=["A", "B", "both"], default="both")
    p.add_argument("--start", default="2024-01-03")
    p.add_argument("--end", default="2024-12-25")
    p.add_argument("--step-days", type=int, default=7)
    p.add_argument("--nscen", type=int, default=1000)
    p.add_argument("--asset-rho", type=float, default=0.05)
    p.add_argument("--time-rho", type=float, default=0.05)
    p.add_argument("--nearest-days", type=int, default=None)
    p.add_argument("--years", type=int, nargs="+",
                   default=[2018, 2019, 2020, 2021, 2022, 2023, 2024])
    p.add_argument("--out-dir", default=str(THIS_DIR / "outputs" / "validation"))
    args = p.parse_args()
    out_dir = Path(args.out_dir)

    if args.part in ("A", "both"):
        days = [d.strftime("%Y-%m-%d")
                for d in pd.date_range(args.start, args.end,
                                       freq=f"{args.step_days}D")]
        print(f"=== Cross-block validation PART A ({len(days)} days) ===")
        part_a(days, args.nscen, args.asset_rho, args.time_rho,
               args.nearest_days, args.years, out_dir)
    if args.part in ("B", "both"):
        print(f"\n=== Tail co-occurrence PART B ===")
        part_b(args.years, out_dir)


if __name__ == "__main__":
    main()
