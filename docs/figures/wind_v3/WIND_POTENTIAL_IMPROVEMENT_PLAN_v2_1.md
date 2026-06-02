# Wind Model — Improvement Plan v2 (post-2026-06-02 session)

**Supersedes** `WIND_POTENTIAL_IMPROVEMENT_PLAN.md`. Same target: best-estimate **pre-curtailment hourly per-plant potential** (31 NYISO plants, 2018–2024), the series Stage A / GEMINI consume — `+wind` physics without the EIA-923 loss factor.

**Audience:** Claude Code, working in this repo on branch `valoche`. Read top to bottom, execute phase by phase.

---

## Current state (context, not tasks)

- **Production approach: multi-cell Method A** (`pluswind_v4_power_multicell_A`), committed `60e32fe`. This is the baseline every candidate must beat.
- **Frozen v3 baseline:** `docs/figures/wind_v3/per_plant_hourly_scorecard.csv` (Task 0.1, committed `0723d4c`). Headlines: fleet vs PLUSWIND 22-plant overlap 2018–2021 nMAE **1.46%**, r 0.9996, ramp_r 0.992; Copenhagen LPI 2024 bias **−2.2%**; worst per-plant nMAE Steel Wind **18%**, Erie Wind **15%**.
- **Closed:** Task 0.2 (lat/lon) — coords were always correct; the "errors" were measured against EIA-860 operator office, not the turbine field. No edits. UNVERIFIED bucket retained for *physics* reasons, not location.
- **Investigated, not adopted:** Task 1.2 hub-shear (`bb23264`, deferred), Task 2.1 learned curve (uncommitted). Both died in the same validation blind spot (no per-plant potential ground truth).

**What changed vs v1.** The lever-exploration phase is done; the remaining work is finalization before the v4 freeze. Three items still move the v4 numbers (hub-α, post-2021 fleet coverage, data-integrity on the worst plants). Everything else is sequenced around the rebuild-as-acceptance and the strategic MIS decision.

---

## How to run this with Claude Code

1. **One task = one commit**, with an acceptance gate. No bundling.
2. **Stop at `🛑 DECISION`** — surface numbers, wait for human sign-off. These are the manual checkpoints under `acceptEdits`.
3. **Read before editing.** `view` `PGscen-2nd/pgscen/utils/wind_physics.py` and `05_build_hrrr_timeseries.py` before touching physics; confirm `pluswind_v4_power_multicell_A`, `pluswind_v5_power_multicell_A_hubshear`, `estimate_shear_alpha`, `extrapolate_to_hub`, `TURBINE_SPEC_OVERRIDES`.
4. **Phases R0–R1 land before R2 (the freeze).** R2 bakes numbers for 31 plants; R1 decides whether they're right.

---

## Invariants (constraints, not goals)

- **I1 — Ship uncorrected potential.** Stage A consumes `+wind` multi-A with its *internal* density + SAM + 7%-taper loss, **no** EIA-923 factor. Don't change what Stage A consumes.
- **I2 — Never fit physics to metered.** EIA-923 / LPI are post-curtailment, ~20% below potential (availability + wake). Shape/decomposition references only. **Data-integrity fixes in R1.3 are metadata/coverage corrections, never loss-tuning to metered.**
- **I3 — Level is validatable only on clean anchors** (Copenhagen, PLUSWIND). Aged metered → shape only (CF-normalized nMAE, ramp_r). **New this session, now an explicit rule: PLUSWIND is WS80-only, so it is structurally blind to hub height. Never treat a PLUSWIND *level* change as evidence for or against a hub-height change.** Only ramp_r on PLUSWIND and the Copenhagen EIA-923 bound can speak to hub-shear.
- **I4 — Reproducibility.** v4/v5/v6 keep distinct suffixes; never overwrite v3 or the `.raw_backup` siblings until a candidate clears every gate fleet-wide.

---

## Phase R0 — Close the session (fast)

### Task R0.1 — Commit Task 2.1 as investigated / not-adopted

**Why:** keep the record (I4), same posture as 1.2. But the commit message must record *why the test was inconclusive*, not just "deferred," so a future revisit reads it correctly:

1. **Train/apply scale mismatch** — curve trained on plant-aggregate single-cell WS, applied per-cell in multi-A (a Jensen-inequality offset). The result does **not** cleanly test "do learned archetype curves help."
2. **Ceiling-bound by construction** — trained on PLUSWIND, so it can at best reproduce PLUSWIND (~1.5%); it could never beat its own teacher on this data. Beating the ceiling needs truth better than PLUSWIND (clean metered potential, or MIS-decomposed).

Keep `train_archetype_curves.py`, the v6 physics function, and the archetype CSVs/PNG in tree.

**Gate:** clean working tree; commit message documents reasons 1–2; v6 artifacts preserved.

---

## Phase R1 — Resolve the three things that change the v4 freeze

### Task R1.1 — Hub-shear: α calibration + adopt/clip decision 🛑 DECISION

**This is the priority.** It is the only open decision that changes v4 numbers for the 13 plants at 91–120 m hubs (the newer/larger 2023–2024 commissions — the growing share of the fleet). Modeling a 100 m turbine at 80 m wind biases its potential low; the smoke test showed Copenhagen 95 m → +8.2% power, Marble River 94 m → +13.8%.

**Framing — read carefully.** The session deferred hub-shear because v5 overshot Copenhagen LPI by +6.5% (−0.31 → +1.81 MW). But that test assumes Copenhagen metered ≈ potential, which is exactly what's in question at the 6% level: a real operating farm has some availability + wake, so a correct *potential* model **should** sit above metered. The Copenhagen-metered bias therefore cannot, by itself, reject hub-shear. **The decision space is {full-α, clipped-α, climatology-blended-α} — NOT {hub-correction, no-hub-correction}. "No correction" is off the table; it is known-wrong physics for a third of the fleet.** The only real question is the *magnitude* of α.

**Steps:**

1. **α-distribution diagnostic (primary, model-independent signal).** Over the existing pilot HRRR cells (and a fleet sample if cheap), compute per-hour `α = ln(ws80/ws10) / ln(80/10)`. Report median, P10/P90, split day vs night and by season. Compare median to onshore climatology (~0.14–0.20). HRRR 10 m winds are a known weak spot; stable nocturnal boundary layers inflate α, and the current clip ceiling of 0.40 lets extreme hours through. **If HRRR median α ≫ climatology, the lift is inflated regardless of any loss bookkeeping — that is the finding, and the fix is clip/blend toward climatology.**

2. **α sensitivity on the pilot.** Re-run the multi-cell pilot (Copenhagen + Marble agg, 2020 + 2024) with: full α; clipped α at {0.20, 0.25}; and a climatology blend `α_eff = w·α_HRRR + (1−w)·(1/7)`. Track how the Copenhagen overshoot and ramp_r move.

3. **Copenhagen EIA-923 bound (interpretive cross-check, not the mechanical gate).** Pull Copenhagen's pooled EIA-923 loss fraction (already in script 12 / the scorecard). A clean plant with ~5–8% real losses makes a few-percent potential-over-metered *expected*; use this to read step 2, not to decide alone.

**🛑 DECISION** — present the α distribution, the {0.20 / 0.25 / blend} sensitivity numbers, and the Copenhagen bound, then pick the α treatment. Decision rule:

- Adopt the most physically-honest α that (a) is climatology-consistent, (b) does not overshoot Copenhagen beyond its plausible real-loss band, and (c) preserves ramp_r.
- **Ignore PLUSWIND *level* entirely** (WS80-blind, I3) — any hub lift "regresses" PLUSWIND nMAE structurally; that is meaningless. Only PLUSWIND ramp_r and Copenhagen matter.
- If genuinely ambiguous, adopt a **conservative climatology-blended α** rather than zero correction, and document the residual uncertainty. Zero correction is not a valid outcome.

**Files:** `wind_physics.py` (clip/blend in `estimate_shear_alpha`; the v5 function becomes the v4-with-hub candidate), `run_multicell_pilot.py`, `score_multicell_pilot.py`.

**Gate:** an explicit α treatment chosen and backed by the diagnostic + sensitivity + Copenhagen bound; the chosen treatment is what enters the R2 rebuild; ramp_r not regressed on the pilot.

### Task R1.2 — rtfuelmix zonal-sum coverage check (lightweight)

**Why:** LPI covers ~10 plants (the 4 NYPA groups). After the v4 freeze ships all 31, the **other ~20 plants have zero post-2021 validation of any kind** — including Steel Wind (18%) and Erie Wind (15%), the two worst. rtfuelmix is the only post-2021 signal touching them. This is a cheap regression-detector for the unanchored fleet, not a level harness.

**Steps:** build/scope `experiments/wind_validation/score_vs_rtfuelmix.py` to compare hourly **fleet-sum and per-zone (A/C/D/E) sums** of multi-A v4 vs rtfuelmix wind, 2018–2024. Source `data/nyiso_cache/{y}/fuel_mix/` (5-min → hourly). Report **correlation + ramp_r + scaled-nMAE** (single fleet loss scalar). **Never raw nMAE of potential vs rtfuelmix** — it's post-curtailment system total, ~20% below potential (I3); the output must state this is shape/coverage only.

**Gate:** 2018–2024 fleet + per-zone correlation/ramp series frozen; explicitly surface whether the zones containing Steel Wind / Erie Wind track rtfuelmix, so R2 can check the rebuild against it.

### Task R1.3 — Data-integrity triage on the worst plants

**Why:** Baron Winds at 49–140% "loss" is not loss — availability + wake + curtailment + bias cannot produce 140% under any honest decomposition; it's a metadata/nameplate/coverage artifact. Steel Wind (18%) and Erie Wind (15%) are the per-plant worst. All three ship in v4 and currently sit in UNVERIFIED without a named cause.

**Steps:**

1. **Baron Winds** — verify nameplate, PTID↔EIA-860 join, USWTDB turbine count/spec, and EIA-923 monthly coverage (partial-year / commissioning months). A 140% figure points to a denominator/coverage problem. Fix metadata if wrong; else mark "EIA-923 unreliable for this plant" with the reason.
2. **Steel Wind** — has the Dec-2019 repower `TURBINE_SPEC_OVERRIDES`. Check whether the 18% nMAE **concentrates at the 2019/2020 override boundary** (year-gating seam) vs uniform. Seam-concentrated → override window/spec issue; uniform → spec/hub/site.
3. **Erie Wind** — same spec/hub-tier checks (coords already verified).

**Gate:** each of the 3 has a named root cause (metadata bug vs genuine physics vs EIA-923 coverage), with a fix committed **or** a documented known-issue + reason in script 12 / the scorecard. No silent UNVERIFIED bucketing. **Guardrail (I2):** fixes are metadata/coverage corrections only — never tune to metered.

**Files:** `12_join_eia923_to_pluswind.py`, `wind_meta.csv` (only if a real metadata error is found — no coord edits otherwise), `wind_physics.py` (`TURBINE_SPEC_OVERRIDES` only if the Steel Wind seam is the cause).

---

## Phase R2 — The v4 freeze (this is the acceptance measurement) 🛑 DECISION

### Task R2.1 — Full-fleet multi-A v4 rebuild + acceptance + consistent series

**Why:** the multi-A win (4.49% → 2.86% nMAE) is a **5-plant-pilot, 2020-only** number. The full-fleet multi-A figure against the frozen **1.46%** baseline is still unmeasured. The rebuild is therefore the real acceptance test, not just production. Do not let "ship v4" and "measure v4" collapse into one step.

**Steps:**

1. Run multi-A (with the **R1.1-decided hub treatment**) on all 31 plants × 2018–2024. ~2–3 h HRRR re-download — multi-cell needs `.subset` cells the existing npz cache lacks. Write to `.pluswind_v4`; keep v3 + `.raw_backup` (I4).
2. **Acceptance:** rerun Task 0.1 (`score_per_plant_hourly.py`) on v4. Gate = full-fleet v4 PLUSWIND nMAE ≤ the 1.46% baseline (expect improvement from spatial averaging), **and** no per-plant catastrophic regressions, **and** the R1.2 rtfuelmix zonal check does not regress on the unanchored zones.
3. **Rebuild both series consistently.** The DA forecast runs the same physics (§6/§8). When actuals change v3→v4, the MOS bias correction is fit on (actual, forecast) pairs — so the forecast must be rebuilt through v4 physics **and the MOS refit on v4 pairs**. Otherwise the forecast sits on a v3 footing while actuals are v4, biasing the residual distribution GEMINI learns. Keep `.raw_backup`.

**🛑 DECISION** — present the full-fleet v4-vs-baseline scorecard + the rtfuelmix zonal comparison before blessing v4 as production and before Stage A is repointed.

**Gate:** v4 scorecard committed and clears the baseline gate fleet-wide; both series rebuilt and MOS refit on v4; Stage A repointed only after the gate is green.

**Files:** `05_build_hrrr_timeseries.py` (fleet run), `06_mos_bias_correction.py` (refit on v4), `score_per_plant_hourly.py` (rerun), data outputs.

---

## Phase R3 — Lower-priority / strategic (after the freeze)

### Task R3.1 — Regime-conditioned MOS (forecast side)

Lower priority for the actuals/GEMINI goal, **but not dropped** — GEMINI fits actual−forecast residuals, so forecast bias shapes scenario realism. Schedule after R2. Condition the §6 correction on predicted power/WS band (or pool hours) instead of pure hour-of-day; keep the rolling 4-year prior and `.raw_backup`. **Must run on v4 actuals** (after R2.1).

**Gate:** forecast nMAE (and a CRPS-style proxy if available) improves vs the hour-of-day MOS on a held-out window.

**Files:** `06_mos_bias_correction.py`.

### Strategic decision (human, not a code task) — NYISO MIS per-resource

Now the **highest-leverage open item.** Hub-shear (R1.1) and the learned curve (2.1) both died in the same blind spot: no per-plant potential ground truth. MIS per-resource is the only signal that decomposes `potential − availability − wake − curtailment` per plant per hour, which (a) lets you *validate* hub-shear and the learned curve properly, and (b) is the only path past the ~1.5% PLUSWIND ceiling. If acquisition is greenlit it becomes Phase R4 and re-opens R1.1 / 2.1 as now-validatable. **Flag for decision; do not block the v4 freeze on it.**

---

## Task summary

| ID | Phase | Touches | Depends on | Gate | Decision? |
|---|---|---|---|---|:--:|
| R0.1 | Close | commit only | — | tree clean; reasons 1–2 in message | |
| R1.1 | Pre-freeze | `wind_physics.py`, pilot scripts | — | α treatment chosen on diagnostic + sensitivity + Copenhagen bound | 🛑 |
| R1.2 | Pre-freeze | `score_vs_rtfuelmix.py` (new/scope) | — | fleet + per-zone corr/ramp frozen; Steel/Erie zones surfaced | |
| R1.3 | Pre-freeze | `12_*`, maybe `wind_meta.csv` / overrides | — | each worst plant has a named cause + fix-or-documented | |
| R2.1 | Freeze | `05_*`, `06_*`, scorecard | R1.1, R1.2, R1.3 | full-fleet v4 ≤ 1.46%; both series rebuilt + MOS refit | 🛑 |
| R3.1 | Post | `06_*` | R2.1 | forecast nMAE ↑ on held-out | |

**Order:** R0.1 → R1.1 / R1.2 / R1.3 (parallelizable among themselves) → R2.1 → R3.1. MIS decision runs alongside, blocking nothing.

---

## Appendix A — Validation philosophy (for the agent)

Do **not** "fix" the gap where modeled potential sits above metered. `metered = potential − availability − wake − curtailment`; the EIA-923 layer measures `potential − metered` at 22–29% (curtailment only 1–3% of it), and Stage A consumes *uncorrected* potential (I1), so that ~20% is never subtracted from the product. Any nMAE of potential vs metered for an aged plant contains a ~20% definitional term and is **not** model quality.

Two refinements this session added:

- **Hub height is in a validation blind spot.** PLUSWIND is WS80-only (can't see hub) and metered can't distinguish potential from loss at the few-percent level. So hub-shear cannot be adjudicated by either anchor's *level* — decide it on physics (the correction is mandatory for high-hub plants), on α-vs-climatology, and on shape (ramp_r). This is why R1.1's decision space excludes "no correction."
- **A curve trained on PLUSWIND cannot beat PLUSWIND.** Learned-curve gains are capped at the ~1.5% ceiling until trained on better truth. Revisit only with per-cell training or MIS-decomposed potential.

The recurring conclusion: existing anchors resolve to ~1pp, and sub-1pp refinements can't be distinguished from anchor noise. **MIS per-resource is the only thing that moves that floor.**
