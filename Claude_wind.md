# Claude_wind.md — the NYISO wind project, consolidated

**READ THIS BEFORE DOING ANYTHING WIND-RELATED.** It is the single source of truth for the
NYISO wind work: the physics model, the scenario pipeline, the current ship config, every
approach tried (kept or abandoned, with *why*), the calibration nuances, the guardrails not to
re-litigate, and where everything lives. It supersedes the dated progress/handoff/session docs
(which were folded in here and then deleted). Living detail still lives in: `RESULTS.md`
(per-plant scenarios), `Per_Plant_Wind_Plan.md` (the decision), `docs/Wind_Physics_Model.tex`
(the physics paper), `Claude_load.md` (the abandoned joint load+wind Stage A/B experiment, and
why it was dropped).

Last consolidated 2026-06-09.

---

## 0. The project in one paragraph

We generate **day-ahead probabilistic scenarios (~1000/day) of per-plant NYISO wind**, which
feed a unit-commitment / security-constrained economic dispatch (UC/SCED) optimizer on a nodal
NYISO grid. Scenarios must be **pre-curtailment "potential"** (the optimizer curtails itself).
Two halves: **(1) the physics model** turns weather into per-plant hourly actuals + a day-ahead
forecast (the `pluswind_v4` series); **(2) the scenario engine** (PGScen / GEMINI) turns the
forecast + its error history into per-plant Monte-Carlo scenarios. The grid is per-plant (each
plant → a bus), so the deliverable is **per-plant**.

Fleet: **31 plants, 2018–2024**, across NYISO zones **A (6), C (9), D (6), E (9)** + **K (South
Fork, 1 offshore)**. The active fleet grows from 23 plants (2018) to 31 (2024).

---

## 1. Physics model — `pluswind_v4` (the actuals + forecast series)

**Pipeline** (`PGscen-2nd/pgscen/utils/wind_physics.py`): HRRR weather → map turbines to HRRR
cells (multi-cell **Method A**) → wind speed at hub height (power-law shear, **clip-0.25**) →
air-density correction → per-plant **NREL-SAM power curve** → wake/availability loss (~7% taper)
→ aggregate to the plant. Output: per-plant hourly **actuals** (F00) + a **MOS-corrected
day-ahead forecast** (18:00 UTC issuance, 24 lead-hours, rolling 4-yr MOS). Production suffix:
`.pluswind_v4`. v4 = multi-cell A + clip-0.25 hub-shear; fleet-sum lift **+4.8%** vs v3.

### Invariants — HARD constraints, do not violate
- **I1 — Ship *uncorrected* potential.** v4 = density + SAM + 7%-taper + hub-shear, **no
  EIA-923 factor**. Stage A / the scenario engine consume the uncorrected potential.
- **I2 — Never fit physics to metered.** EIA-923 / LPI are *shape / decomposition references
  only*. Metadata fixes come from EIA-860 / USWTDB / goldbook — **never** tune physics to reduce
  metered error.
- **I3 — Level is validatable only on clean anchors** (Copenhagen single-plant LPI; PLUSWIND
  *ramp-only* for any hub-height change). Aged/aggregated metered = **shape only**. PLUSWIND
  *level* is meaningless for any hub-height change.
- **I4 — Reproducibility.** Never touch v3 or the `.raw_backup` siblings. v4 lives on its own
  suffix.

### Decisions already made — do NOT re-litigate
- **Hub-shear adopted at clip-0.25** (`SHEAR_ALPHA_MAX = 0.25`). α diagnostic: daytime median
  0.143 (≈ 1/7 onshore climatology); night median 0.292 inflated by the stable boundary layer +
  HRRR's known 10 m weakness. If the tall tier proves α-fragile the answer is a **day/night-split
  α**, *never a flat cap*.
- **The PLUSWIND-nMAE "gate failure" (1.46% → 4.26%) is expected and benign, not a bug.**
  PLUSWIND is WS80-only and structurally blind to hub height, so any hub lift raises its *level*
  offset by construction (the +26 MW maps plant-by-plant onto the correct hub lift). Every
  *valid* gate passed/improved (Copenhagen CFnMAE 32.8→29.4, ramp_r, rtfuelmix). **Do not "fix"
  this.**
- **Do not cap the >95 m hub tier.** Capping a physically-real lift you can't yet validate biases
  those plants low. Tall-tier plants: Hardscrabble ~100 m (+10.5%), Eight Point ~109 m (+12%),
  Baron ~113 m (+13.8%), Bluestone ~120 m (+21.9%). They extrapolate the power law past
  Copenhagen's 95 m anchor; the documented uncertainty is a tall-tier sensitivity, not a cap.

### Metadata bug class (closed) + the lat/lon premise (FALSE)
Two serious bugs were the **same EIA-860-join root class**: **Baron** (stale goldbook 238.4 MW
nameplate vs as-built 130 MW) and **Canandaigua** (EIA-ID collision → mapped to Baron's 60596
instead of Cohocton's 56634 → wrong power curve, spurious +13.8% hub lift, coords 10.3 km off).
Fixes are enforced by override guards (`NAMEPLATE_OVERRIDES`, `EIA_ID_COORD_OVERRIDES`) in
`scripts/04_build_plant_metadata.py` so a rebuild preserves them. **The "5 plants with wrong
lat/lon" premise is FALSE** — all 5 flagged plants' coords match USWTDB turbine-field centroids
at **0.00 km** (the earlier "error" compared against EIA-860 *operator office address*). Maple
Ridge's 3.71 km offset is benign (handled by multi-cell aggregation). Residual per-plant loss is
**physics/availability/curtailment, not coordinates** — resolving it needs NYISO MIS data (§9).

### HRRR fetch (operational — reuse, don't reinvent)
One combined byte-range fetch for all 6 fields (80 m + 10 m wind, surface pressure, 2 m temp);
retry-on-timeout; crash-proof save-after loop; **sequential-solo** (parallel streams throttle
each other; `retries mode="adaptive"` made it ~4× worse — both reverted). ~37–47 min/year for
the F00 actuals; the DA forecast fetch (24 lead-hrs/issuance) is much larger.

### Validation (what it proves, per I3)
- **vs PLUSWIND** 22-plant overlap 2018–2021 pooled (v3): nMAE **1.46%**, r 0.9996, ramp_r 0.992.
  Top-nMAE plants flagged: Steel Wind (18%), Erie Wind (15%). PLUSWIND level invalid for v4 hub
  change (I3) → ramp-only.
- **Copenhagen** (single-plant metered, 95 m): the clean level anchor (CFnMAE 32.8→29.4 with v4).
- **EIA-923** per-plant annual: real *level*, annual-only, partly self-referential; matched-fleet
  22–29% loss, stable, no trend; NYISO transmission curtailment 1–3%; remaining ~20% not
  decomposed (awaits MIS). LPI 2024 hourly: Copenhagen ~0% loss; Maple Ridge 28%, Marble 30%,
  Noble+Bliss 39% (3/4 LPI titles mislabel their contents).
- **Fleet vs NYISO `rtfuelmix`**: real external coverage, aggregate only.

### Key physics files
`PGscen-2nd/pgscen/utils/wind_physics.py` (SAM curves, density, `estimate_shear_alpha` /
`extrapolate_to_hub` with `SHEAR_ALPHA_MAX=0.25`, loss; `pluswind_v4_*` / `pluswind_v5_*hubshear`
power fns). Build under `experiments/wind_validation/`: `fetch_alpha_raw.py`,
`build_v4_actuals.py`, `build_v4_forecast.py`; scoring `score_per_plant_hourly.py`,
`score_vs_rtfuelmix.py`, `metadata_audit.py`, `analyze_alpha.py`. MOS:
`scripts/06_mos_bias_correction.py --variant .pluswind_v4`. Data:
`PGscen-2nd/data/NYISO_real/wind/wind_{actual,day_ahead_forecast}_*_utc.pluswind_v4.csv`; metadata
`plant_metadata/wind_meta.csv` (cols incl. `site_id`, `zone`, `nameplate_mw`, `operating_year`,
lat/lon). On-disk index is **hourly UTC** (the computation zone); convert to **US/Eastern at the
presentation layer** (figures, prose) per the ET-output convention.

---

## 2. Scenario pipeline — the per-plant decision

**The grid is per-plant** (`renew_detail.csv` rows keyed by EIA gen; NYgrid assigns wind to
buses; `Grid/run_sced.py:_build_pgscen_site_map` maps plant→bus by lat/lon). So we model wind
**directly per plant** rather than René's original **zonal-first** design (fit 4 zonal wind sums
jointly with load = Stage A, then disaggregate back to plants = Stage C).

**Why per-plant over zonal+Stage C:** for a per-plant deliverable the plant→zonal-sum→plant
round-trip is lossy, and **Stage C carried an unsolved coherence problem** — its primitive
(`pgscen/model.py:conditional_multivar_normal_aggregation`) conditions on the sum of the *latent
Gaussian* variables, not the sum of *MW*, so per-plant MW would not sum back to the Stage-A zonal
MW. The load side stays zonal (load is intrinsically zonal; Stage A's 4 load zones + Stage B's 7
= the 11-zone load model, unchanged).

**Status: the wind half of Stage A and Stage C are DROPPED.** The whole two-stage joint load+wind
experiment (Stage A + Stage B) was abandoned and removed from the tracked tree — the cross-group
diagnostic showed load↔wind/solar/BTM forecast-error correlation ≈ 0, so fitting wind *jointly
with load* bought nothing (see `Claude_load.md`). Wind ships per-plant; load ships as an
independent single-stage 11-zone fit. Stage C was never built; its primitive docstring
(`pgscen/model.py:conditional_multivar_normal_aggregation`) is flagged unused. The old Stage A/B
scripts remain only as a local, untracked record (gitignored); the one shared data aligner they
used now lives at `experiments/_shared/load_wind_io.py`.

**The engine (PGScen / GEMINI).** `GeminiEngine(asset_type='wind')`. Per-plant **ECDF marginals**
(handles zeros) + a **Gaussian copula** fit by graphical-LASSO on Gaussianised forecast-error
deviations, Kronecker-separable **asset ⊗ horizon** covariance. `engine.fit(asset_rho_matrix,
time_rho)` then `engine.create_scenario(nscen, forecast_future)`. The asset penalty is
**geographic**: `2·ρ·dist/dist.max()` from `engine.asset_distance()` (lat/lon). Marginals are
**conditional on forecast level** (`model.py:fit_conditional_marginal_dist`, bins history within
±`bin_width_ratio=0.05` of the day's forecast, `min_sample_size=200`). The latent Gaussian draws
are stored on `model.scen_gauss_df` / `scen_gauss_bias_df`; the per-plant deviation history is
`model.deviation_dict[asset]` (cols Actual/Forecast/Deviation). **Gaussian copula ⇒ zero tail
dependence by construction.**

**Day convention: UTC scenario days** (the loader organizes the forecast by UTC day; an ET day
straddles two forecast blocks). ET-day alignment to the load Stage A/B days is a known
integration follow-up, not a calibration blocker.

---

## 3. SHIP CONFIG (current production)

> **`asset_rho = 0.5`  +  pre-COD marginal fix (`restrict_marginals_to_operating`)  +
> `in_sample = False`** (leakage-fixed; history strictly before the scenario start).

- Wired into the Grid-consumed **production runner** `PGscen-2nd/scripts/10_run_pgscen_wind.py`
  (`--precod-marginal-fix` on by default; `--asset-rho` default 0.5) and the leakage-fixed
  callable `experiments/wind_per_plant/run_wind_per_plant.py:run_one_day` (`restrict_precod=True`
  default). Same per-plant CSV schema → the Grid bridge (`Grid/run_sced.py`) is unaffected.
- `asset_rho=0.5` is the **cross-zone-corrected** default; the old 0.05 over-coupled distant
  zones ~10× (§6). Energy-score tuning is **flat** (can't discriminate `asset_rho`) → tune
  against a *correlation target*, not the score.

**Calibration (52 held-out 2024 days, weekly stride, 1000 scen; recorded artifact at
`experiments/wind_per_plant/outputs/ship_artifact/`):**
- Per-plant: mature plants cov_80 **0.80–0.87**; the young/new cohort brought **onto target
  (0.79–0.82)** by the pre-COD fix (§4).
- Per-zone (plant-pooled) cov_80: **A .81, C .84, D .83, E .83, K .80**.
- **Fleet-sum cov_80 = 0.721, cov_90 = 0.812, bias ≈ 4 MW.** This ~0.72 is the documented
  limitation — **cross-zone structural, NOT marginal** (§5, §6).
- **Caveat:** "actual" = the v4 modeled potential the engine was fit on → these measure
  **self-consistency**, not metered truth (no hourly per-plant metered truth for ~28/31 plants).

---

## 4. The pre-COD marginal fix (RESULTS.md §9) — the important recent finding

**Symptom:** young plants' fans collapsed to a **point mass exactly at the forecast** at
low-forecast hours (e.g. Ball Hill 2024-10-12 h14: forecast 5 MW, fan width 0, actual 10.7 MW —
a guaranteed miss).

**Root cause:** `fit_conditional_marginal_dist` bins history by forecast level. A plant
commissioned *inside* the training window has forecast = actual = 0 for every pre-COD hour →
deviation = 0; at a **low** scenario forecast the bin `[0, ~range·ratio]` sweeps in all those
pre-COD zeros. For a 2024 plant that is ~89% of its history (Ball Hill: 6,629 operating hours vs
52,795 pre-COD zero hours) → ~90% of scenarios drawn at deviation 0 = the forecast.

**Fix:** `pgscen/short_history.py:restrict_marginals_to_operating(engine)` — drop each plant's
pre-commissioning rows (everything before its first operating hour) from `deviation_dict`,
**between `engine.fit` and `engine.create_scenario`**. The joint copula (`gauss_df`) is untouched;
applies to every plant by its own COD.

**Before → after cov_80** (rho=0.5; before = old multiplicative widener): Cassadaga .66→**.80**,
Roaring Brook .69→**.82**, Baron .73→**.81**, Eight Point .76→**.81**, Number Three .69→**.82**,
Ball Hill .69→**.79**, Bluestone .68→**.79**, South Fork .69→**.80**. Whole cohort onto target.
**Fleet 0.731→0.721 (≈ unchanged)** — confirms §5: the fleet residual is cross-zone structural,
not marginal, so a marginal fix correctly doesn't move it.

---

## 5. Calibration nuances worth knowing (don't be surprised by these)

- **Fleet cov_80 ≈ 0.72 is a cross-zone STRUCTURAL limitation, not a marginal deficit.** The
  `diagnose_fleet_dispersion.py` evidence: (a) re-coupling zone sums to the *exact* empirical
  cross-zone correlation (Iman–Conover, marginals untouched) moves fleet cov_80 by only **+0.004**
  → the copula is the lever, not marginals; (b) the deficit is **heterogeneous in sign** across
  zones (zone-sum σ ratios A 0.81 / K 0.95 too narrow, C/D/E 1.09–1.14 already wide), so a single
  global factor can't fix it. A **structured / block asset covariance** is the principled next
  lever (§7). **Do NOT try a global marginal widen** — it was tested and rejected (§6).
- **Per-plant fans are mildly OVER-conservative — and that's fine, leave it.** Mean cov_80 ≈ 0.826
  (vs 0.80), cov_90 ≈ 0.927, bias ≈ 0. Spread-skill check (`spread_skill_check.py`): ratio (fan
  std / realized error) ≈ **1.06**; the driver is a **year effect** — 2024 forecast errors were
  ~20% smaller than the 2018–2024 pool the marginals are built from (`year_ratio` ≈ 1.20, 28/31
  plants). It is **NOT bin-pooling** (the forecast-conditioning *narrows* the marginal, residual
  0.885 — it helps). This is **climatological robustness**: each fan is sized to the multi-year
  error, so it over-covers in a calm year and is correctly sized in a stormy one — the honest
  choice for a forward forecast. **Decision: leave the marginals as-is; do not narrow them.**
- **The genuinely under-dispersed group is the young cohort** (spread-skill ratio < 1, cov_80
  0.79–0.82) — a residual thin-history effect that self-corrects as their own multi-year pool
  accrues.
- **Load↔wind independence holds in the tail.** λ = P(total wind bottom 5% & total load top 5%) =
  0.79× independence (joint stress *less* frequent than independent). Pair load-scenario i with
  wind-scenario i (independent draws); the Gaussian copula never encoded load↔wind tail coupling
  anyway.

---

## 6. Approaches tried and SET ASIDE (with why — so we don't re-try them)

1. **Zonal Stage A wind + Stage C disaggregation** — *set aside for per-plant-direct.* Lossy
   round-trip + Stage C's latent-sum coherence problem (§2). Retained, pending René sign-off.
2. **Global marginal widen** (lift fleet cov_80 0.72→0.80) — **tested and REJECTED** (§5). The
   deficit is heterogeneous in sign; a global g≈1.25 over-inflates D/E (~0.90) while A stays short
   (~0.72); the copula nets out (+0.004). Structurally the wrong tool. Figure:
   `scenario_global_widen_rejected.png`.
3. **Multiplicative young-plant widener** (`short_history_reg` / `widen_engine_scenarios`) —
   *shipped first, then SUPERSEDED by the pre-COD fix* (§4). It widened young deviations to the
   mature-fleet spread but **cannot fix a point mass** (`f·0 = 0`) and never saw the pollution (its
   target was an operating-only std). Code retained only for the parity test
   (`check_short_history_parity.py`); NOT in the ship path.
4. **GPD heavy-tail hypothesis for Cassadaga / Roaring Brook** — *proposed, then DISPROVEN* (§4).
   We thought their ~3.5-yr history undersampled the tails; wrong — same pre-COD pollution, fixed
   by the pre-COD fix. No heavy-tail correction needed.

---

## 7. Key concepts + the next lever

- **Cross-plant / cross-zone coupling** = the correlation between different plants' (or zones')
  forecast-error deviations — the off-diagonal of the asset covariance. It governs the *fleet*
  band: independent plants diversify (tight sum), correlated plants reinforce (wide sum). You can
  have every plant calibrated and still get the fleet wrong if the coupling is wrong (exactly our
  case: per-plant fine, fleet under).
- **Structured asset covariance (the next lever for the fleet residual).** Today the 31×31 asset
  covariance is *one knob* (`asset_rho`) × a distance matrix — it forces "correlation falls off
  with distance," but reality doesn't (C–D moderate-distance is correlated 0.17; A–E far is ~0).
  At rho=0.5 the moderate pairs C–D/D–E **under-couple** (0.06/0.08 vs 0.18/0.14) and C–E/A–C
  over-couple. A **block covariance** (separate within-/between-zone blocks) or a **factor model**
  (shared weather factors × per-plant loadings + idiosyncratic noise) has more shape but stays
  estimable — that's what the fleet residual needs. **Deferred until validatable out-of-sample.**

---

## 8. Known limitations & open items
- **Fleet/aggregate residual** cov_80 ≈ 0.72 — structured asset covariance is the next lever (§7),
  deferred.
- **Cross-zone per-pair coupling** — one distance kernel can't reproduce the full matrix; the
  pairs net out at the fleet level but a zonal *fit* would represent each directly (the strongest
  remaining argument for some zonal structure).
- **ET-day alignment** — scenario engine runs UTC days; align the wind day boundary to the load
  Stage A/B ET days (integration follow-up).
- **Self-consistency, not metered truth** — per-plant PIT/coverage are vs v4 potential; only the
  fleet (`rtfuelmix`) and 2 single-plant LPI groups are externally validated.
- **NYISO MIS per-resource data** (human decision) — the only path to validate the >95 m hub lifts
  and the learned curve directly, and to push past the ~1.5% PLUSWIND ceiling and decompose the
  ~20% residual loss (availability vs curtailment). Leave a note; act on nothing without sign-off.
- **Stage A wind / Stage C** — superseded but retained pending René's sign-off (deletion is his
  call).
- **Post-freeze ideas** (not now): regime-conditioned MOS; richer per-plant asset covariance.

---

## 9. File / artifact map
- **Physics:** `PGscen-2nd/pgscen/utils/wind_physics.py`; `scripts/{04_build_plant_metadata,
  05_build_hrrr_timeseries,06_mos_bias_correction}.py`; `experiments/wind_validation/*`. Data:
  `PGscen-2nd/data/NYISO_real/wind/*.pluswind_v4.csv`, `plant_metadata/wind_meta.csv`.
- **Scenario engine:** `PGscen-2nd/pgscen/{engine.py, model.py}`;
  `pgscen/short_history.py` (the pre-COD fix `restrict_marginals_to_operating`; the retired widener
  `build_factors`/`widen_engine_scenarios` kept for the parity test).
- **Production runner:** `PGscen-2nd/scripts/10_run_pgscen_wind.py`.
- **Per-plant experiments:** `experiments/wind_per_plant/` — `run_wind_per_plant.py` (callable),
  `calibration.py` (PIT/coverage/CRPS sweep), `diagnose_fleet_dispersion.py` (the §5 diagnostic),
  `record_ship_artifact.py` (the ship coverage artifact), `spread_skill_check.py` (the §5
  over-conservatism diagnostic), `check_short_history_parity.py`, `validate_cross_block.py`,
  `tune_rho.py`, `short_history_reg.py` (superseded), and **`RESULTS.md`** (the detailed record).
- **Stage A/B (dropped):** the joint load+wind experiment — abandoned, kept only as a local,
  untracked/gitignored record under `experiments/stage_{a,b}_*/`. Its shared data aligner is now
  `experiments/_shared/load_wind_io.py`. Full story: `Claude_load.md`.
- **Grid bridge:** `Grid/run_sced.py` (`_load_pgscen_renew`, `_build_pgscen_site_map`).
- **Paper:** `docs/Wind_Physics_Model.tex`; figures `docs/figures/wind_v3/` (the current
  scenario-calibration set is `scenario_*.png` + `scenarios_fleet_fan_ship_2024.png`, generated by
  `make_scenario_calibration_figs.py`).
- **Plan / decision doc:** `Per_Plant_Wind_Plan.md`.
- **Relevant memories:** `project_per_plant_wind`, `project_pgscen_nyiso`,
  `reference_nyiso_wind_data`, `project_wind_meta_lat_lon_issues`, `project_eia923_validation_residual`,
  `project_lpi_2024_validation`, `project_per_plant_loss_correction`, `reference_untracked_experiments`,
  `feedback_eastern_time_output`.

---

## 10. Caveats about the repo (so you don't lose work)
- **`PGscen-2nd/experiments/` is UNTRACKED by git** and holds real work (e.g. the solar failure
  characterization). git can't restore it. **Never `rm -rf` it or its parents**; delete only the
  specific leaf you created after `ls`-ing the target. (See `reference_untracked_experiments`.)
- **Data conventions:** all on-disk series are **UTC**; convert to **US/Eastern only at the
  presentation layer**. Wind actuals are **pre-curtailment potential** (the grid curtails).
- **Git:** the wind ship-state was committed at `fee7d17` ("ship per-plant wind…"); the pre-COD
  fix + figures + paper updates were pending in the working tree on `valoche` as of 2026-06-09.
  Stage everything by **explicit path** — the working tree carries many unrelated changes.
