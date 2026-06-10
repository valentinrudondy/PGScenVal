# SUPERSEDED: the two-stage load pipeline (Stage A load + Stage B) — retained, not deleted

**Status:** the two-stage NYISO load scenario pipeline — **Stage A's load half** (the 4
wind-bearing zones, jointly fit with wind) + **Stage B** (conditional simulation of the other
7 zones) — is **superseded by a single-stage 11-zone load model**, shipped as the production
runner. The code here is **retained intact and reversible** — nothing is deleted — pending
René's sign-off, because collapsing his named A+B stages is his call (same posture as the
per-plant wind amendment; see `../stage_a_joint_load_wind/SUPERSEDED_WIND.md`).

## What ships instead

A single `GeminiEngine` fit over all **11 NYISO load zones**, scenarios drawn directly (the
natural PGScen usage):
- Engine/runner module: `PGscen-2nd/pgscen/load_scenarios.py:run_load_one_day`
- Package data loader: `PGscen-2nd/pgscen/utils/data_utils.py:load_ny_real_load_data`
- Production CLI: `PGscen-2nd/scripts/12_run_pgscen_load.py` (writes per-zone CSVs to
  `<out>/<YYYYMMDD>/load/`, the same `engine.write_to_csv` schema as wind)
- Ship config: `asset_rho=0.002` (confirmed optimal for the 11-zone load-only fit),
  `horizon_rho=0.05`, `in_sample=False` (leakage-safe).

## Why it's justified (the evidence)

1. **Cross-group independence.** Load↔wind/solar/BTM forecast-error correlation is ~0
   (graphical-LASSO partial corr 0.004; wind/solar form their own components — see
   `experiments/three_way_dependency_graph/`). So the only reason Stage A modelled load
   *jointly with wind*, and Stage B conditioned the rest onto it, is gone.
2. **Load↔load is what mattered, and the single fit keeps it.** Empirical cross-zone load
   |corr| ≈ 0.30 (all 11 zones one glasso component); the single 11-zone fit's `asset_cov`
   reproduces it (mean abs diff vs empirical 0.04). Verified:
   `outputs/load_zone_corr_fitted.csv`.
3. **Calibration-equivalent + simpler + faster.** 52 held-out 2024 days: per-zone all-11
   cov_80 **0.765 vs 0.767**; fleet cov_80 **0.797 vs 0.795** — identical within noise — while
   the single fit is **~3.6× faster** (2.2 vs ~8 s/day), one fit instead of two, and removes
   Stage B's conditional sampler *and* its marginal-inconsistency caveat. Evidence:
   `single_stage_load.py`, `outputs/single_stage/`.

The single-stage runner is byte-for-byte identical to the validated experiments path
(`single_stage_load.run_one_day_single`) — parity checked at 0.0 MW over 79,200 values.

## Known load limitation (NOT fixed by this; orthogonal)

Zone **E (MHK VL, Mohawk Valley)** stays under-calibrated (cov_80 ~0.55, ~−55 MW model bias).
The **data is correct** (official NYISO MIS feed, verified). The cause is a genuine, *declining*
NYISO DA-forecast bias for Mohawk Valley (under-forecast ~107 MW pooled → ~69 MW in 2024,
data-center load growth) that the pooled-history marginal centers too high on — a recency /
non-stationarity issue, the same class as the wind year-effect. Fix candidate: recency-weighted
or trend-detrended marginal for high-drift zones. Present in *both* the two-stage and single-stage
models.
