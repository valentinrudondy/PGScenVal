# Wind Model — Improvement Plan for Hourly Per-Plant **Potential** Generation

**Target:** best-estimate *pre-curtailment* hourly generation per plant (31 NYISO plants, 2018–2024), the series consumed by Stage A / GEMINI. This is the `+wind v3` physics output **without** the EIA-923 loss correction.

**Audience:** Claude Code, working in this repo. Read this top to bottom, then execute phase by phase.

---

## How to run this with Claude Code

1. **One task = one commit.** Each task below has a single, bounded scope and an explicit acceptance gate. Commit when the gate is green; do not bundle tasks.
2. **Phase 0 lands before anything else.** It builds the scoreboard. Every later task reports its acceptance number against the Phase 0 baseline — no measurement, no merge.
3. **Read before editing.** Before touching physics, `view` `PGscen-2nd/pgscen/utils/wind_physics.py` and `PGscen-2nd/scripts/05_build_hrrr_timeseries.py` in full. Do not assume signatures for `pluswind_v3_power_all_plants`, `build_sam_curves`, `wind_power_all_plants`, or `TURBINE_SPEC_OVERRIDES`; confirm them from the source.
4. **Stop at `🛑 DECISION` markers.** These are points where a modeling choice (not just code) is being made. Surface the numbers and wait for human sign-off before proceeding. Relevant because this repo runs Claude Code in `acceptEdits` — these markers are the manual checkpoints.
5. **Never delete the fallbacks.** v1 cubic, v2 cubic, and the year-gated `TURBINE_SPEC_OVERRIDES` stay in place.

---

## 0. Invariants (must stay true through every task)

These are not goals; they are constraints. A change that violates one is wrong even if a metric improves.

- **I1 — Ship uncorrected potential.** The Stage A / GEMINI feed is `+wind v3` with its *internal* density + SAM + 7%-taper loss, but **without** the per-plant EIA-923 loss factor (the 22–29%). "No loss correction" in §8 means *no EIA-923 factor* — not removal of the built-in taper. Do not change what Stage A consumes.
- **I2 — Never fit the physics to metered.** EIA-923 and NYPA LPI are post-curtailment metered, ~20% below potential by construction (availability + wake). They are **shape and decomposition references only.** No physics parameter, power curve, or correction may be tuned to minimize error against metered for aged plants. Doing so converts potential → metered estimate. (See Appendix A.)
- **I3 — Level is validatable only on clean anchors.** Potential *level* may be scored against: (a) Copenhagen (clean single 2018 plant, raw bias −2%), and (b) PLUSWIND on the 2018–2021 overlap (a potential-grade model). Everywhere else, only scale-invariant *shape* metrics are meaningful.
- **I4 — Reproducibility.** Outputs keep the `.pluswind_v3` lineage and the `.raw_backup` siblings so corrections can be refit. New outputs get a new suffix (e.g. `.v4`) and never overwrite v3 until v4 clears every Phase 0 gate.

---

## Phase 0 — Measurement backbone (do first)

Nothing here improves the model. It builds the instrument that makes every later improvement measurable, and clears two cheap blockers. Expect this phase to be fast.

### Task 0.1 — Per-plant hourly scorecard (the scoreboard)

**Why:** §7 has *no* per-plant hourly error anywhere — only monthly (EIA-923) and group-level mean-bias + 4 group Pearson values. You cannot optimize hourly per-plant accuracy without measuring it, and the metric must be designed correctly for a *potential* target (see I3).

**New file:** `experiments/wind_validation/score_per_plant_hourly.py`.

**Metrics — split by what each comparison can legitimately tell you:**

| Comparison | What's valid | Metrics |
|---|---|---|
| vs **PLUSWIND** per-plant, 2018–2021 | level + shape (both potential-grade) | nMAE, nRMSE, Pearson r, hourly-Δ (ramp) distribution |
| vs **Copenhagen** metered (clean anchor) | level + shape | nMAE, nRMSE, r |
| vs **EIA-923 / NYPA** (aged, metered) | **shape only** — level offset is definitional | r; mean-normalized diurnal & monthly profiles; **CF-normalized error** (divide both series by their own mean, then compare — removes the ~20% level offset, exposes timing/shape error); hourly-Δ distribution |

**Acceptance gate:** produces `docs/figures/wind_v3/per_plant_hourly_scorecard.csv` and freezes the **current v3 baseline** for every metric above. This frozen baseline is the number all later tasks beat. The script must label each plant `level_validatable: true/false` so no downstream step accidentally treats a metered level gap as model error.

### Task 0.2 — Fix the 5 lat/lon errors in `wind_meta`

**Why:** §4 + §10. Directly improves wind-field representativeness for those plants, closes the Noble +13% residual, and is a **prerequisite for multi-cell aggregation** (Task 1.1) — you can't map turbines to HRRR cells with wrong coordinates.

**Files:** `PGscen-2nd/data/NYISO_real/plant_metadata/wind_meta.csv` (+ the metadata build in `04_build_plant_metadata.py` if the error originates upstream). Cross-check corrected coordinates against USWTDB turbine coordinates and Gold Book. Memory ref: `project_wind_meta_lat_lon_issues`.

**Acceptance gate:** all 5 plants move from `unverified` to `matched`/`degraded` with verified coordinates; rerun Task 0.1 and confirm the Noble group shape metrics move; document each fix (old → new, source).

### Task 0.3 — rtfuelmix fleet-sum hourly harness

**Why:** §9 #6 + §10 — this is the **only independent hourly signal for 2022–2024**, exactly the window Stage A runs and PLUSWIND no longer covers. §10 itself calls it "the number every later improvement has to beat."

**New file:** `experiments/wind_validation/score_vs_rtfuelmix.py`. Source: `data/nyiso_cache/{y}/fuel_mix/` (5-min system-total wind; resample to hourly).

**Caveat baked into the output (I2/I3):** rtfuelmix is post-curtailment system total, so it sits ~20% below fleet potential. Report **(a) correlation and ramp-distribution match** (valid directly) and **(b) nMAE only after applying a single fleet-level loss scalar** — never raw nMAE of potential vs rtfuelmix. The output must state this so the number isn't misread as model error.

**Acceptance gate:** a 2018–2024 fleet-sum hourly comparison CSV with correlation + scaled-nMAE per year, baseline frozen.

---

## Phase 1 — Physics levers (the real potential gains)

These improve the potential series at the resource level. They are unambiguous for a potential target — no interaction with curtailment or metered fitting.

### Task 1.1 — Multi-cell spatial aggregation 🛑 DECISION

**Why (highest-impact physical lever):** §9 #2 names the single-grid-point assumption as a known limit, and USWTDB gives per-turbine coordinates — so the data is already in hand. A single HRRR cell produces too much high-frequency variance because real farms smooth spatially across multiple 3 km cells. This is the one lever that fixes the **ramp and variance distribution**, not just point error — and since GEMINI fits residuals for *scenarios*, getting hourly variance/ramps right is as valuable as point accuracy.

**Approach:**
1. Map each plant's USWTDB turbine coordinates → HRRR 3 km cells (requires Task 0.2 done).
2. Two aggregation methods to trial:
   - **A (preferred):** run the v3 power curve per cell-subset (turbines in each cell), then sum to plant MW. Correct when turbines span cells with different wind.
   - **B (fallback):** average the WS field over the plant footprint, then one curve evaluation. Cheaper, slightly less correct.
3. Compare A vs B against PLUSWIND/Copenhagen on point error **and** the hourly-Δ distribution.

**🛑 DECISION:** present A-vs-B numbers on the anchors before committing a method.

**Files:** `PGscen-2nd/pgscen/utils/wind_physics.py` (curve evaluation over a cell set) and `PGscen-2nd/scripts/05_build_hrrr_timeseries.py` (cell mapping + extraction).

**Acceptance gate:** hourly-Δ variance moves toward PLUSWIND/clean-truth (over-variance reduced); point error on level-validatable plants holds or improves; no regression on Task 0.1 shape metrics.

### Task 1.2 — Hub-height shear correction

**Why:** §5 uses WS80, but hub heights vary across the fleet (USWTDB has them). Extrapolating to each plant's *actual* hub height removes a per-plant systematic error you're currently eating. Cheap, free data.

**Approach:** estimate local shear exponent from HRRR 10 m and 80 m wind, extrapolate to per-plant hub height via power/log law, feed the hub-height WS into the existing density correction → curve chain. Respect `TURBINE_SPEC_OVERRIDES` hub heights for repowered-plant years.

**Files:** `wind_physics.py` (shear step before density correction); `05_build_hrrr_timeseries.py` (pull the 10 m level).

**Acceptance gate:** net improvement on level-validatable plants; per-plant systematic shifts documented; no shape regression.

---

## Phase 2 — Transfer function (carefully bounded)

### Task 2.1 — Learned empirical power curve, anchored on potential-grade truth only 🛑 DECISION

**Why:** the SAM curve (§5 stage 2) is the *generic* curve for the turbine model, not the measured curve of that farm. An empirical monotonic WS→power fit can absorb site terrain, turbulence, **and** systematic HRRR WS bias together, in the 5–9 m/s band where the error concentrates. This is the cleanest route to beating the ~1.5% PLUSWIND ceiling.

**Hard guardrail (I2):** train the curve **only** against potential-grade references — Copenhagen (clean) and PLUSWIND per-plant where it exists. **Do not** fit against EIA-923/NYPA metered for aged plants; that would bake availability + wake into the "curve" and corrupt the potential target. Because clean per-plant truth is scarce (~2 plants), learn **archetype** curves by turbine class / terrain class and transfer to like turbines — not per-plant curves for all 31.

**Approach:** isotonic regression or a monotone spline on density-corrected-WS-binned power, per archetype, against PLUSWIND/Copenhagen. Keep SAM as the fallback where no archetype match exists.

**🛑 DECISION:** present archetype definitions + per-archetype fit quality on the PLUSWIND overlap before adopting.

**Files:** `wind_physics.py` (`build_sam_curves` neighborhood — add a learned-curve path with SAM fallback).

**Acceptance gate:** improves anchors and PLUSWIND-overlap nMAE **without** metered as a fit target; archetype assignment documented per plant.

---

## Phase 3 — Forecast side (parallelizable, separate series)

Independent of Phases 1–2 (different output series). Can run concurrently.

### Task 3.1 — Regime-conditioned MOS

**Why:** the §6 MOS is per-(plant, month, hour) — 288 cells per plant on limited data. Wind-power bias is usually a stronger function of *predicted power/WS level* than of clock hour (it peaks in the steep part of the curve). Conditioning on predicted band, or pooling hours via the existing smoother, typically beats hour-of-day alone.

**Approach:** add a predicted-power/WS-band conditioning axis to the correction (or replace hour-of-day with it), keep the rolling 4-year prior window so reported numbers stay operationally honest. Keep `.raw_backup` siblings (I4).

**Files:** `PGscen-2nd/scripts/06_mos_bias_correction.py`.

**Acceptance gate:** forecast nMAE (and a CRPS-style proxy if available) improves vs the current hour-of-day MOS on a held-out window.

> **Later, heavier:** NWP blending (HRRR + RAP / HRRRE / ECMWF) is the most reliable way to cut forecast wind error, but it's a real build and only helps the DA series (actuals already use F00 analysis). Out of scope for this pass; note as a future lever.

---

## Strategic (flag, do not block)

- **NYISO MIS per-resource** (§10): the only path to validating potential *level* on aged plants directly — it lets you reconstruct potential ≈ metered + curtailment (+ outage flags) and split availability from curtailment cleanly. **Open question for the human:** is acquisition on the table? If yes, it becomes Phase 4 and upgrades I3 (level becomes validatable fleet-wide). The plan above is built to stand without it.

---

## Task summary

| ID | Phase | Touches | Depends on | Acceptance gate | Decision? |
|---|---|---|---|---|:--:|
| 0.1 | Backbone | new `score_per_plant_hourly.py` | — | per-plant hourly baseline frozen | |
| 0.2 | Backbone | `wind_meta.csv`, `04_*` | — | 5 plants verified; Noble shape moves | |
| 0.3 | Backbone | new `score_vs_rtfuelmix.py` | — | 2018–24 fleet correlation + scaled-nMAE frozen | |
| 1.1 | Physics | `wind_physics.py`, `05_*` | 0.1, 0.2 | ramp variance ↓; anchor level holds/↑ | 🛑 |
| 1.2 | Physics | `wind_physics.py`, `05_*` | 0.1 | anchor level ↑; no shape regression | |
| 2.1 | Transfer fn | `wind_physics.py` | 0.1, 1.x | anchor + PLUSWIND nMAE ↑, no metered fit | 🛑 |
| 3.1 | Forecast | `06_mos_bias_correction.py` | 0.1 | forecast nMAE ↑ on held-out | |

**Recommended order:** 0.1 → 0.2 → 0.3 → 1.1 → 1.2 → 2.1, with 3.1 in parallel any time after 0.1. The 0.2 + 0.3 pair and 3.1 can run concurrently with the 1.x physics work.

---

## Appendix A — Why level is only checkable on clean anchors (for the agent)

Do **not** "fix" the gap where modeled potential sits above metered. That gap is real and expected:

```
metered = potential − availability − wake − curtailment
```

The EIA-923 layer (§7) measures `potential − metered` at **22–29%**, stable across 2018–2024. Of that, NYISO economic/transmission curtailment is only **1–3%** — the rest is **availability + wake (~20%)** plus residual bias. Because Stage A consumes *uncorrected* potential (I1), that ~20% is never subtracted from the product, so it is not an error to remove — it is the definitional distance between a potential series and a metered series.

Consequence: any nMAE of potential vs metered for an aged plant contains a ~20% definitional term and is **not** a model-quality signal. Score level only against Copenhagen (clean) and PLUSWIND (potential-grade); score everyone else on scale-invariant shape (correlation, ramp distribution, mean-normalized profiles, CF-normalized error). This is the single most important rule in the plan.
