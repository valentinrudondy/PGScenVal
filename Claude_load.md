# Claude_load.md — the NYISO load model, consolidated

**READ THIS BEFORE DOING ANYTHING LOAD-RELATED.** Single source of truth for the NYISO load
scenario work: what ships, the one calibration caveat, and the Stage A/B experiment we tried and
abandoned (with *why*). Mirrors `Claude_wind.md` for the wind side.

Last consolidated 2026-06-10.

---

## 1. What ships — single-stage 11-zone load (production)

We generate **day-ahead probabilistic scenarios (~1000/day) of NYISO zonal load**, one fit over
all **11 load zones**, drawn directly. This is the natural PGScen usage and the entire model.

- **Engine/runner:** `PGscen-2nd/pgscen/load_scenarios.py:run_load_one_day` — one
  `GeminiEngine(asset_type="load")` fit over the 11 zones; ECDF/GPD marginals + Gaussian copula
  (graphical-LASSO), Kronecker-separable asset⊗horizon covariance; scenarios drawn directly.
- **Data loader:** `PGscen-2nd/pgscen/utils/data_utils.py:load_ny_real_load_data` → `(actual_df,
  forecast_df)` with `LOAD_A..K` columns, from the official NYISO MIS feed (palIntegrated actuals
  + isolf day-ahead forecast). **Data verified correct** against NYISO MIS.
- **Production CLI:** `PGscen-2nd/scripts/12_run_pgscen_load.py` — loops ET days, writes per-zone
  scenario CSVs to `<out>/<YYYYMMDD>/load/` (same `engine.write_to_csv` schema the grid bridge
  consumes for wind). Mirrors `10_run_pgscen_wind.py`.
- **Ship config:** `asset_rho=0.002` (optimal for the 11-zone load-only fit: per-zone cov is
  rho-insensitive / marginal-driven, fleet cov is best at the lowest rho), `horizon_rho=0.05`,
  `in_sample=False` (leakage-safe: history strictly before each scenario day), NYISO DA issue
  convention 18:00 UTC the prior ET day.

**The 11 NYISO load zones** (letter → MIS name): A=WEST, B=GENESE, C=CENTRL, D=NORTH,
E=MHK VL (Mohawk Valley), F=CAPITL, G=HUD VL, H=MILLWD, I=DUNWOD, J=N.Y.C., K=LONGIL.

**Why load is modelled on its own** (not jointly with wind/solar/BTM): cross-group
forecast-error correlation is ~0 (partial corr 0.004; the `three_way_dependency_graph` diagnostic
puts wind and solar in their own glasso components). The correlation that *does* matter is
**load↔load** across zones (empirical |corr| ≈ 0.30, all 11 zones one glasso component) — and the
single 11-zone fit captures it directly in `asset_cov` (mean abs diff vs empirical ≈ 0.04;
`outputs/load_zone_corr_fitted.csv` in the local stage_b record).

### The one calibration caveat — zone E (MHK VL / Mohawk Valley)

Zone E stays under-calibrated (cov_80 ~0.55, model bias ~−55 MW). **The data is correct.** The
cause is a genuine, *declining* NYISO DA-forecast bias for Mohawk Valley (under-forecast ~107 MW
pooled → ~69 MW in 2024, driven by data-center load growth) that the pooled-history marginal
centers too high on — a recency / non-stationarity issue (same class as the wind "year effect").
Present in *both* the abandoned two-stage and the shipped single-stage models, so it is **not** a
single-stage artifact. Fix candidate (not done): recency-weighted or trend-detrended marginal for
high-drift zones.

---

## 2. What we tried and dropped — Stage A + Stage B (joint load+wind)

**We tried it, it turned out there was no cross-group correlation, so it was moot.** Recorded
here so it is not re-attempted.

**What it was.** René's original load design was two stages:
- **Stage A** — an 8-dim joint fit of `[LOAD_A, LOAD_C, LOAD_D, LOAD_E, WIND_A, WIND_C, WIND_D,
  WIND_E]`: the 4 wind-bearing load zones fit *jointly with* the zonal wind sums, on the
  assumption that load and wind forecast errors co-move.
- **Stage B** — a conditional Gaussian simulation of the other **7** load zones (B, F, G, H, I,
  J, K) conditioned on the 4 Stage-A zones, to recover all 11.

**Why it's moot.** The premise — that load co-moves with wind — is false in the data. The
`three_way_dependency_graph` cross-group diagnostic gives load↔wind/solar/BTM forecast-error
**partial correlation ≈ 0.004**, with wind and solar forming their own separate glasso
components. So fitting load *jointly with* wind (Stage A) and conditioning the rest onto the
wind-bearing zones (Stage B) buys nothing over a single load-only fit. The only real structure,
load↔load (~0.30), is captured directly by the single 11-zone `asset_cov`.

**It was also calibration-equivalent but worse engineering.** On 52 held-out 2024 days (weekly
stride, nscen=1000, `in_sample=False`):

| metric | single-stage (ships) | Stage A+B |
|---|---|---|
| per-zone all-11 cov_80 | 0.765 | 0.767 |
| fleet cov_80 | 0.797 | 0.795 |
| speed | ~2.2 s/day | ~8 s/day (~3.6× slower) |
| structure | one fit | two fits + conditional sampler + marginal-inconsistency caveat |

Identical calibration within noise; the single fit is ~3.6× faster and far simpler. The
production runner was parity-checked byte-for-byte against the validated experiments path
(`single_stage_load.run_one_day_single`): **0.0 MW difference over 79,200 values**.

**Note on Stage A's wind half.** Stage A also carried the 4 zonal wind *sums*; those are
superseded separately by the **per-plant wind** pipeline (the grid is per-plant), for a different
reason — see `Claude_wind.md` §2. Stage C (per-plant disaggregation of the zonal sums) was never
built.

---

## 3. Where things live

- **Production load:** `PGscen-2nd/pgscen/load_scenarios.py`,
  `PGscen-2nd/pgscen/utils/data_utils.py:load_ny_real_load_data`,
  `PGscen-2nd/scripts/12_run_pgscen_load.py` — independent of Stage A/B, on GitHub.
- **No-correlation evidence:** `experiments/three_way_dependency_graph/` (the cross-group
  glasso diagnostic; local).
- **Shared load+wind data aligner:** `experiments/_shared/load_wind_io.py` (the old Stage A
  `build_joint_inputs`, relocated — a data join, not a model; still used by the wind diagnostics).
- **Abandoned Stage A/B code:** `experiments/stage_a_joint_load_wind/` +
  `experiments/stage_b_conditional_loads/` — kept only as a **local, untracked, gitignored**
  record (the calibration/parity scripts and their outputs). Never on GitHub.
