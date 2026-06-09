# Plan: model NYISO wind per-plant directly (drop the zonal wind round-trip)

**Status:** proposed — *requires René's sign-off* (it amends his stated spec; see §8).
**Audience:** this is written to be self-contained for an external reviewer with no repo access.
**Purpose:** I want a second opinion on whether this is the right call and where it's weak.

---

## 0. TL;DR

The end product the grid optimizer consumes is **per-plant** wind injections. René's
design produces wind as **zonal sums** (Stage A) and then disaggregates back to plants
(Stage C, not yet built). For a per-plant deliverable, that plant → zonal-sum → plant
round-trip is lossy and unnecessary.

**Recommendation:** model wind **directly per plant** using the PGScen `GeminiEngine`
path that *already exists and already runs on the frozen v4 data*. **Drop** the wind half
of Stage A and **drop** Stage C entirely. **Keep** the load side zonal (load is
intrinsically zonal). Combine load and per-plant wind scenarios as **independent draws** —
justified not by a bare correlation number but by a structural fact about the engine (§5).

This is a **spec amendment**, not a fait accompli. It needs René's decision because it
reverses a methodological choice he defended to the client. My recommendation is: proceed,
**contingent on one validation check passing** (§6) — but the call is his.

---

## 0b. Implementation status — BUILT AND MEASURED (not just proposed)

The plan has been implemented **additively** in
[`experiments/wind_per_plant/`](experiments/wind_per_plant/) (Stage A/C code untouched, so
this is fully reversible). Full numbers:
[`experiments/wind_per_plant/RESULTS.md`](experiments/wind_per_plant/RESULTS.md). All runs
are held-out (the existing runner's `in_sample=True` **data-leakage was found and fixed**),
on v4 data, 52 days of 2024. Headline measured results:

- **Per-plant and per-zone calibration is good and rho-robust.** Established (pre-2022)
  plants cov_80 **0.80–0.87**; per-plant mean **0.79**; per-zone **0.75–0.83** — all
  essentially unchanged between `asset_rho` 0.05 and 0.5. The product works at the
  per-plant/per-zone level the grid consumes it. *Caveat (§9): this is self-consistency vs
  v4 potential, not metered truth.*
- **§5 holds empirically.** Direct load↔wind tail co-occurrence λ = **0.79×** independence
  (joint high-load/low-wind is *less* frequent than independent) — independence is safe,
  even slightly conservative, for the UC. Closes the tail-dependence gap the bare 0.008
  correlation left open.
- **§6 surfaced the most important finding — and it's a genuine qualification, not a clean
  pass.** At the default `asset_rho=0.05` the geographic kernel **over-couples zones** (A–D
  scenarios 0.43 vs truth ~0; D–E 0.73 vs 0.13). Raising to `asset_rho≈0.5` pulls the
  strong/far pairs into line — **but a single distance-scaled `asset_rho` cannot reproduce
  the full cross-zone matrix** (correlations don't follow distance: C–D at moderate distance
  is 0.16 but under-couples to 0.03 at rho=0.5). And critically, the default-rho **fleet
  cov_80 of 0.85 was an artifact** — the cross-zone over-coupling was inflating the fleet
  spread and masking a mild marginal under-dispersion; at the corrected rho the fleet drops
  to **0.72**. The follow-up diagnostic (RESULTS.md §7) showed this residual is **not** closable
  by a global marginal widen (heterogeneous per-zone sign) **nor** by the cross-zone copula
  (re-coupling to empirical correlation moves the fleet +0.004); it ships as a documented
  limitation. **This is a modest point in favour of the zonal
  approach** (Stage A fits each cross-zone pair directly) — answering open question #3 with a
  real trade, not a clean win.
- **The young-plant risk (§7) is confirmed and partially mitigated.** The only
  systematically under-dispersed plants are the 2023–24 commissions (cov_80 0.60–0.70,
  exactly as predicted). The short-history regularizer widens them (+0.03–0.08 cov_80,
  e.g. Baron 0.66→0.73) while leaving mature plants untouched (0.822→0.820) — it helps but
  doesn't fully close; a known low-confidence bucket that self-corrects as history accrues.

**Net effect on the recommendation:** the per-plant *deliverable* (what the grid ingests —
per-plant injections) is sound and well-calibrated. The honest qualification is at the
**aggregate/cross-zone** level: the one-parameter geographic kernel can't fully reproduce
the zonal correlation structure that Stage A fits directly, and the headline fleet number
was flattered by error cancellation. **Final ship recipe (see RESULTS.md §7, which tested and
*rejected* the global widen): (1) `asset_rho=0.5`; (2) the young-plant regularizer only —
no global marginal widen; (3) fleet cov_80 ships at ≈0.73 as a documented known limitation.**
The global widen was rejected on evidence: the fleet deficit is heterogeneous in sign across
zones (A/K too narrow, C/D/E already wide) and the cross-zone copula nets out at the fleet
level, so a uniform factor over-inflates D/E while leaving A under. A *structured* asset
covariance (not a one-parameter distance kernel) is the principled next lever, deferred until
out-of-sample validation. Zone/fleet fidelity is the strongest remaining argument a reviewer
could make for retaining some zonal structure (open question #3) — answered as a real trade,
not a clean win.

---

## 1. Background (self-contained)

**The project.** We generate day-ahead probabilistic *scenarios* (≈1000 per day) of NYISO
load, wind, and solar, which feed a unit-commitment / security-constrained economic
dispatch (UC/SCED) optimizer on a **nodal** NYISO grid model. The grid dispatches and
curtails; therefore our scenarios must be **pre-curtailment "potential"** generation — the
optimizer applies curtailment itself.

**The engine (PGScen / GEMINI).** For a set of assets over a 24-hour horizon, the pipeline:
(1) takes day-ahead forecast errors (`actual − forecast` deviations), (2) removes heavy
tails and maps each asset's marginal to a Gaussian via ECDF/GPD ("gaussianize"),
(3) fits a sparse covariance with graphical lasso, (4) draws from a Kronecker-separable
multivariate Gaussian (asset ⊗ horizon), (5) inverts the marginals back to MW.
**This is a Gaussian copula** with non-Gaussian marginals — a fact that turns out to be
load-bearing for the decision (§5).

**René's 4-stage plan** (the "core deliverable"):

| Stage | What | Status |
|---|---|---|
| A | Joint load+wind in the 4 wind-bearing zones (8-dim vector: 4 load zones + **4 wind zonal sums**) | done, calibrated |
| B | Conditional simulation for the other 7 load zones | done, calibrated |
| C | Disaggregate each **wind zonal sum** back to individual farms | **not started** |
| D | Solar (PCA basis), incl. behind-the-meter | partial |

**Wind physics.** "+wind v4" (frozen, production): HRRR weather → air-density correction →
per-plant NREL-SAM power curve → wake/availability loss. Per-plant hourly actuals + a
MOS-corrected day-ahead forecast, ~31 plants, 2018–2024. The 4 modeled wind zones hold
**30 plants** (A:6, C:9, D:6, E:9). Zone K (one offshore plant, South Fork) is excluded.

---

## 2. The core observation

**The grid is per-plant.** The optimizer's renewable output is keyed by individual
generator (`renew_detail.csv` rows are `EIA_88_1`, …); NYgrid assigns wind capacity to
specific **buses**; and the PGScen→grid bridge (`run_sced.py:_build_pgscen_site_map`) maps
each plant to its nearest bus by lat/lon. A *zonal* scenario cannot be ingested without a
per-plant disaggregation step — which is exactly what Stage C is for.

So in the zonal-first design, **something must turn a zonal scenario into per-plant
injections.** Stage C is that step. But if you never aggregate to a zonal sum in the first
place, there is nothing to disaggregate. For a per-plant deliverable:

> plant → plant **dominates** plant → zonal-sum → plant.

The round-trip throws away per-plant identity, then reconstructs it under an extra
modeling assumption (the within-zone disaggregation covariance), and introduces a
**coherence problem** (§4). Direct per-plant modeling has none of these.

---

## 3. The recommendation, precisely

Three distinct decisions — kept separate on purpose, because they rest on different
evidence:

1. **Combine load and wind as independent draws** (pair load-scenario *i* with
   wind-scenario *i*). Justified structurally in §5.
2. **Drop the wind zonal-fit layer** (the `WIND_A..WIND_E` half of Stage A) and **drop
   Stage C.** Justified by the per-plant/per-bus deliverable + the lossy round-trip + the
   fact that zonal wind sums are *not independently observed* (NYISO publishes no per-zone
   wind; the "zonal sum" is itself just a sum of our per-plant v4 series).
3. **Model wind directly per plant** via the existing `GeminiEngine(asset_type='wind')`
   path (`scripts/10_run_pgscen_wind.py`), which fits all 30 plants with a **geographic**
   `asset_rho` (penalty scaled by a pairwise lat/lon distance matrix) and emits one
   scenario series per plant.

**Keep unchanged:** the entire **load** side. Stage A's 4 load zones + Stage B's
conditional 7 zones = an 11-zone joint load model, done and calibrated (coverage within
±0.05 of target on 10/11 zones; train on 2022–2024 to avoid COVID contamination in zone E).
Load is reported and dispatched zonally, so zonal is correct there. With wind removed,
Stage A simply becomes the 4-load-zone block of that model; the two-stage structure stays
(a single 11-zone+30-plant+solar joint fit would be too high-dimensional for the available
history — the team's own rationale).

---

## 4. What already exists (verified against the code)

Every claim below was checked against the repo.

- **The per-plant path is built and on v4.** `10_run_pgscen_wind.py` instantiates
  `GeminiEngine(..., asset_type='wind')`, computes `asset_rho = 2·ρ·dist/dist.max()` from
  `engine.asset_distance()` (lat/lon Euclidean), writes one CSV per plant, and its
  `--variant` default is already `pluswind_v4`. **It is a CLI script, not a library
  callable** — the multi-day loop lives in `main()`, there's no `run_one_day()`, and
  (important) it currently splits history with **`in_sample=True`**, i.e. the scenario day
  is *in* the training window. That's data leakage and must be fixed before any honest
  calibration (§7).

- **Load↔wind coupling is genuinely ~0 in the modeled space.** Cross-block mean |corr|:
  **0.088 raw levels → 0.0076 forecast-deviations → 0.0078 gaussianized** (max 0.244 →
  0.031; glasso-fitted 0.011). The collapse happens at *forecast subtraction*: ~91% of the
  raw load–wind co-movement lives in the predictable diurnal/seasonal signal the day-ahead
  forecast already captures; the *surprises* are essentially uncorrelated. At raw signed
  levels the correlation is −0.13 (windy fronts → milder temps → slightly lower load) —
  the right physical sign, and deliberately discarded with the forecast.

- **Within-block structure is real and must be preserved.** Within-wind mean |corr| 0.216,
  with **WIND_A↔WIND_C = 0.62**. This inter-plant spatial coupling is what the geographic
  `asset_rho` carries in the per-plant model — it is *not* discarded by dropping the zonal
  layer (§6 verifies this).

- **Stage C has an unsolved coherence problem.** Its primitive
  (`model.py:566 conditional_multivar_normal_aggregation`) conditions on the sum of the
  **latent Gaussian** variables, not the sum of **MW**. Because the per-plant marginals are
  non-linear, the per-plant MW scenarios would **not** sum back to the Stage-A zonal MW
  scenario without extra handling. (Stage B got bit-exact agreement only because it
  conditions on the *same assets'* values, not on a sum — a genuinely easier problem.) So
  Stage C is not just "wiring"; it carries an open methodological question that the
  per-plant path sidesteps.

- **Wind uses ECDF marginals + a Gaussian copula, with no short-history guard.** Wind
  assets get empirical-CDF marginals (handles zeros), and there is **no per-plant
  eligibility filter or minimum-sample guard.** Plants commissioned in 2023–24 have thin
  history → noisier marginals and a risk of ill-conditioned covariance (§7, mitigation).

---

## 5. Why "independent draws" is defensible (the structural argument)

A reviewer will rightly object that a near-zero **Pearson/rank correlation cannot detect
tail dependence** — and that we have a worked example (solar) where cross-plant lower-tail
dependence is real despite small linear correlation. So I do **not** rest the case on the
0.008 number. The real argument is structural:

> **The production engine is a Gaussian copula.** It draws `sqrt_cov · randn`, maps through
> `Φ`, and inverts per-asset marginals — the *only* inter-asset dependence channel is the
> linear `asset_cov`. A Gaussian copula has **zero tail dependence** for every off-diagonal
> |ρ| < 1.

Therefore the rejected joint Stage-A model **also encoded zero load↔wind tail dependence**
(its cross cells were 0.005–0.03). Dropping it and drawing independently forgoes *no
tail-coupling capability the design ever had* — it replaces a ρ≈0.01 Gaussian link with a
ρ=0 Gaussian link. The solar tail-dependence finding **cuts the other way** here: it is
*cross-plant* (within-wind) dependence, which lives inside the wind block (corr up to 0.62)
and is **preserved** by the per-plant geographic `asset_rho` — arguably *better* preserved
than by the lossy zonal round-trip. And the team already adjudicated that a tail-bearing
t-copula is statistically indistinguishable from the Gaussian on proper scores in this
pipeline, so chasing tail dependence buys nothing measurable.

**One cheap check closes the residual gap (≈1 hour):** measure the empirical lower-tail
co-occurrence λ = P(zonal wind in bottom 5% | net load in top 5%) over 2018–2024 and
compare to the 0.0025 independence implies. If it's within sampling noise, independence is
defended *in the tail*, not just the mean. We should include this in the doc, not assert it.

---

## 6. The one validation that gates the decision

The honest weak point of "drop the zonal layer" is that the geographic distance kernel has
**not been shown** to reproduce the calibrated zonal cross-block (WIND_A↔WIND_C = 0.62). So
before flipping, run a **back-to-back check**:

1. Generate per-plant scenarios with the geographic `asset_rho`.
2. **Sum them to zones.**
3. Confirm the zone-sum cross-block correlations reproduce the Stage-A glasso values, and
   that zone-sum interval coverage matches Stage A's.

If it passes, the per-plant model carries the zonal structure for free and Stage C is
strictly redundant. If it *fails* (the geo-kernel underfits the 0.62 coupling), that is a
real finding — it's the one result that would legitimately rescue the zonal+Stage-C route,
and René needs to see it either way. **We present this comparison; we do not assert "strictly
better."**

---

## 7. Scope of work, honestly itemized

The earlier "~½–1 day" estimate was wrong — it was the cost of *one* of these tasks. Real
critical path and effort (with maximal reuse of existing templates):

| Task | Effort | Notes |
|---|---|---|
| **Runner refactor** → production `run_one_day()` callable; **fix the `in_sample=True` leakage**; add a preloaded-data path | ~0.5–1 day | **On the critical path** — blocks the two below. Target parity with `btm_solar_zonal/run_btm_solar.py` (368 lines, structured return, leakage-safe split). |
| **Per-plant calibration harness** (PIT / interval coverage / CRPS, multi-day stride) | ~1 day | Depends on the runner. Adapts `stage_b_conditional_loads/multi_day_calibration.py` (loads) + `btm_solar_zonal/calibration.py`. |
| **Held-out rho tuning** (energy score over the plant geography) | ~0.25 day | Near-drop-in reuse of `stage_a_joint_load_wind/tune_rho.py` (292 lines, already leakage-safe). |
| **Short-history marginal regularizer** (see below) | ~0.5 day | Named deliverable, gated on the calibration evidence. |
| **Cross-block validation** (§6) + tail-co-occurrence check (§5) | ~0.5 day | The decision gate. |

**Honest total: ~2–3 focused days**, sequential (calibration and tuning are blocked on the
runner refactor, not parallel). This is *modestly larger* than the scope dropped by killing
Stage C — I'm not claiming a free lunch.

**Struck from the earlier plan — a correction:** "fix 5 plants' lat/lon errors" is removed.
The project's own verification (2026-06-02) found all 5 flagged plants' coordinates already
match the USWTDB turbine-field centroids at **0.00 km**; the earlier "error" was an artifact
of comparing against EIA-860's *operator office address*. The residual per-plant loss is
**physics/availability/curtailment**, not coordinates, and resolving it needs **NYISO MIS
per-resource data** — a separate, unbounded epic, explicitly out of scope here. (Baron Winds
was a *nameplate* error, already fixed; Maple Ridge's 3.71 km offset is already handled by v4
multi-cell aggregation.)

**Short-history risk + mitigation.** ~5 modeled plants (~600 MW, mostly Zones C/E 2023–24
commissions) have ≤2 years of deviation history. Per-plant marginals there will be noisy —
the zonal sum used to average this out. The mitigation (a named deliverable, not an
afterthought): for any plant with < ~3 years of residuals, **shrink its conditional
marginal toward a pooled zone/fleet deviation distribution**, or borrow an older co-located
plant's marginal weighted by the geographic `asset_rho` we already compute. Gate it on the
PIT evidence (show the new-plant tails are mis-dispersed *before* and corrected *after*).
Caveat: Stage C never solved this either — it would have needed the same thin within-zone
correlations — so this cohort is a known low-confidence bucket in *both* designs.

---

## 8. Where this diverges from René's spec, and what we owe him

This is the part I most want a second opinion on, because it's a governance issue as much
as a technical one.

René called the joint load+wind procedure **"the core deliverable,"** and he **defended
zonal-first to Rana** when she challenged it ("In Texas you did it per plant; here you're
doing it by zone?"). Deleting two of his four named stages — and reverting toward the
plant-direct approach he consciously moved away from — is **his decision to make**, not
something to execute as a done deal. The doc must:

- **Concede ownership up front.** Present this as a *recommended amendment requiring his
  sign-off*, quoting his original framing so it's clear we understood the intent.
- **Separate the two decisions** (independent draws ≠ dropping the zonal layer), so one
  correlation number doesn't appear to license both.
- **Address the non-coupling motivations** for zonal-first, not pretend coupling was the
  only one:
  - *Estimation stability* — a 4-dim zonal glasso is better-conditioned than a 30-dim
    per-plant one. **Response:** real, but mitigable with the same rho machinery + the
    short-history regularizer; and the zonal sum is itself a derived artifact of the
    per-plant series, not a cleaner measurement.
  - *Operations / curtailment narrative* — NYISO curtails and reports by zone. **Response:**
    zonal *reporting* is preserved by post-hoc summation of per-plant scenarios; we lose no
    zonal story by dropping the zonal *fit*.
  - *Framework consistency with Stage D* — **Response:** solar stays zonal-first (PCA basis;
    BTM is intrinsically zonal), so this is a *wind-specific, data-justified exception*, not
    an abandonment of the A→D framework.
- **Offer a reversible path.** Keep the joint infrastructure and the load zonal model
  intact; per-plant wind is a swap that reverts to zonal-sum + Stage C if the §6 validation
  shows the geo-kernel misses the cross-block. Low-regret.
- **State the cost plainly.** The cost is *not* accuracy; it's (i) René re-explaining a
  changed method to NYPA after presenting the 4-stage framing, and (ii) trading the clean
  sum-conditioning coherence guarantee for a geo-rho approximation that must be validated.
  If NYPA optics or his research-contribution framing weigh heavily, he may prefer the
  zonal scaffold even at the round-trip cost. **That trade is his.**

---

## 9. Acceptance gates — and the limits of what we can prove

A reviewer will (correctly) note that **per-plant calibration is largely unfalsifiable**:
there is no hourly per-plant *metered* truth for ~28 of 31 plants. The only hourly metered
data is NYISO LPI for 4 groups, of which **only 2 are single plants** (Copenhagen, 2024
only; Maple Ridge MR1, 2022–24) — the other two are 4-plant aggregates. And LPI is
*post-curtailment* while our scenarios are *pre-curtailment*, so even those checks need the
EIA-923 loss factor applied (a *level-anchored*, not clean, test). So I'm explicit about
what each gate proves:

| Gate | What it actually tests |
|---|---|
| Fleet-sum coverage vs NYISO `rtfuelmix` | **Real** external coverage, but only at the aggregate. |
| Per-plant PIT / coverage / CRPS vs **v4 modeled actuals** | **Self-consistency** — does GEMINI reproduce the per-plant deviation distribution it was fit on. *Not* real-world coverage. |
| 2 single-plant LPI groups (Copenhagen, MR1) | Real per-plant interval coverage — but level-anchored via the loss factor, and a thin window. |
| EIA-923 per-plant annual | Real per-plant **level**, but annual-only and partly self-referential. |
| §6 zone-sum reconstruction | Confirms per-plant model reproduces the calibrated zonal coupling. |

**Honest framing:** the per-plant deliverable is "self-consistency + level-anchoring," not
"every plant is interval-validated." Crucially, this is **not worse than the zonal route** —
Stage C's plant outputs would face the *identical* truth vacuum, plus the round-trip error.
Per-plant is no worse on falsifiability and strictly better on round-trip fidelity. We just
shouldn't oversell it as independently per-plant-validated.

---

## 10. Open questions for the reviewer

1. Is the **Gaussian-copula structural argument** (§5) sufficient to justify independent
   load/wind draws, or do you want the empirical tail-co-occurrence check as a hard gate?
2. Is dropping the zonal *fit* (while preserving zonal *reporting* by summation) a sound way
   to honor the operational/curtailment motivation, or is there a reason the fit itself must
   be zonal that I'm missing?
3. Is the **§6 cross-block reconstruction** the right gate, or is there a stronger test that
   the geographic `asset_rho` faithfully carries the within-zone coupling?
4. Given per-plant calibration is mostly self-consistency (§9), is that an acceptable
   acceptance bar for a pre-curtailment scenario product feeding a UC optimizer, or does the
   thin falsifiable surface argue for keeping the zonal scaffold until MIS data lands?
5. Governance: is "recommend the amendment, implement reversibly, let René decide" the right
   posture, or should nothing be built until he signs off?

---

### Appendix — key file references (for anyone with repo access)

- Per-plant runner: `PGscen-2nd/scripts/10_run_pgscen_wind.py` (leakage at the `in_sample=True` split)
- Engine / Gaussian-copula draw: `PGscen-2nd/pgscen/engine.py`, `PGscen-2nd/pgscen/model.py:441`
- Stage C primitive (latent-sum conditioning): `PGscen-2nd/pgscen/model.py:566`
- Load↔wind correlation evidence: `experiments/stage_a_joint_load_wind/outputs/correlation/cross_block_summary.csv`
- Rho-tuning template: `experiments/stage_a_joint_load_wind/tune_rho.py`
- Calibration templates: `experiments/stage_b_conditional_loads/multi_day_calibration.py`, `experiments/btm_solar_zonal/{run_btm_solar,calibration}.py`
- Grid bridge (per-plant mapping): `Grid/run_sced.py:_build_pgscen_site_map`
- lat/lon re-verification: memory `project_wind_meta_lat_lon_issues` (coords correct at 0.00 km)
