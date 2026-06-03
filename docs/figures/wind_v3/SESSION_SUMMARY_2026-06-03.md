# Wind-model improvement session — 2026-06-02/03 (Plan v2, Phases R0–R2.1)

Continuation of the wind potential-generation work, executing
[WIND_POTENTIAL_IMPROVEMENT_PLAN_v2_1.md](WIND_POTENTIAL_IMPROVEMENT_PLAN_v2_1.md).
Target unchanged: best-estimate **pre-curtailment hourly per-plant potential**
(31 NYISO plants, 2018–2024), the series Stage A / GEMINI consume — `+wind`
physics **without** the EIA-923 loss factor.

Branch: `valoche`. This doc is the handoff for the application-side Claude.

---

## TL;DR

- **Phase R0 + all of R1 are complete and committed** (5 commits, `77829b0`→`c6941d4`).
- **Hub-height shear correction is now ADOPTED** (clip α at 0.25) — it was deferred in the prior session; the new α-calibration + the Copenhagen EIA-923 reinterpretation justified adoption.
- **Two real data bugs fixed** (Baron Winds nameplate, Canandaigua EIA-ID); two "worst plants" (Steel/Erie) turned out **not** to be broken.
- **R2.1 (the v4 freeze) compute is DONE** — all 31 plants × 2018–2024 rebuilt with multi-cell Method A + clip-0.25 hub-shear. **Acceptance results are in and a 🛑 DECISION is pending human sign-off** (see §R2.1). v4 is **not yet committed** and Stage A is **not yet repointed**.
- **Not done:** forecast-series rebuild + MOS refit (R2.1 step 3), R3.1 regime-conditioned MOS.

| Task | Status | Commit |
|---|---|---|
| R0.1 — close Task 2.1 (learned curve, not adopted) | ✅ | `77829b0` |
| R1.1 — hub-shear α calibration → **adopt clip-0.25** | ✅ | `c6941d4` |
| R1.2 — rtfuelmix fleet regression detector | ✅ | `7a0c5ef` |
| R1.3 — data-integrity triage (Baron/Steel/Erie) | ✅ | `077a0aa` |
| R1.3 follow-up — Canandaigua EIA-ID fix | ✅ | `3344b68` |
| R2.1 — full-fleet v4 freeze + acceptance | ⏳ **compute done, DECISION pending, uncommitted** | — |
| R2.1 step 3 — forecast rebuild + MOS refit | ⬜ next phase | — |
| R3.1 — regime-conditioned MOS | ⬜ post-freeze | — |

---

## R0.1 — Closed Task 2.1 (learned archetype curve), not adopted

Committed the prior session's learned-curve experiment as **investigated /
not-adopted**, with the reasons recorded so a future revisit reads it right:
1. **Train/apply scale mismatch** — curve trained on plant-aggregate single-cell
   WS, applied per-cell in multi-A (a Jensen-inequality offset); the test does
   not cleanly isolate "do learned archetype curves help."
2. **Ceiling-bound** — trained on PLUSWIND, it can at best reproduce PLUSWIND
   (~1.5%); beating that needs truth better than PLUSWIND (clean metered /
   MIS-decomposed). Artifacts kept in tree (I4). Commit `77829b0`.

## R1.1 — Hub-shear α calibration → **adopt clip-0.25** (the headline result)

The prior session deferred hub-height shear because v5 "overshot" Copenhagen
metered by +6.5%. This session fetched HRRR **10 m + 80 m wind over all 180
fleet cells** for 2020 + 2024 and calibrated α properly.

**α distribution (2020, ~1.5M cell-hours):**
- Daytime (well-mixed) median **0.143** = the 1/7 onshore climatology exactly.
- Nighttime (stable boundary layer) median **0.292** (~2× climatology); 12.7%
  of all hours exceed 0.40. So the raw-α lift is **inflated by the night tail**
  (stable BL + HRRR's known 10 m weakness).

**Copenhagen EIA-923 bound (the reinterpretation that flipped the decision):**
Copenhagen's metered output ≈ modeled potential to within −4.8%…+2% across
2019–2024 → essentially **0% real loss**. But a clean plant has 5–10%
availability+wake loss, so **v4-no-hub (sitting at metered) actually
*under*-estimates potential**. A hub lift that puts potential a few % *above*
metered is physically *correct*, not an overshoot. → "no correction" is
off the table; the question is only the α magnitude.

**Sensitivity sweep {full / clip0.20 / clip0.25 / blend0.5}** scored vs
PLUSWIND 2020 + Copenhagen LPI 2024. **clip-0.25 chosen** (human-approved):
keeps daytime α untouched, trims the inflated night tail, lands Copenhagen at
**+5.3% over 2024 LPI metered (~5–6% implied loss)**, *improves* Copenhagen
LPI CFnMAE **31.0 → 29.4**, holds ramp_r. Baked in as `SHEAR_ALPHA_MAX = 0.25`
(was 0.40) in `wind_physics.py`.

**Fleet-wide lift (clip-0.25, all 31 plants — `fleet_hub_lift_clip025.csv`):**
- 18 plants at **≤80 m: exactly 0%** (invariant verified).
- 2 old sub-80 m plants (Fenner 66 m, Madison 67 m): correct **down**-correction (−7 to −9%).
- **82–100 m: +5–10%**, **>100 m: +10–22%**, fleet-sum **+4.8%**.
- Copenhagen (95 m, +6%) is the one anchored high-hub plant → validates the magnitude.

Commit `c6941d4`. Scripts: `fetch_alpha_raw.py`, `analyze_alpha.py`,
`fleet_hub_lift.py`; outputs `alpha_diagnostic.csv`, `alpha_sensitivity.csv`,
`fleet_hub_lift_clip025.csv`.

## R1.2 — rtfuelmix fleet-sum regression detector

`score_vs_rtfuelmix.py` compares the in-house fleet-sum vs NYISO rtfuelmix
(statewide system total, 5-min→hourly, 2018–2024). Per I3 it reports only
correlation + ramp_r (valid directly) and scaled-nMAE after a single per-year
fleet loss_scalar — **never raw nMAE** (rtfuelmix is ~31% below potential by
construction). **Frozen v3 baseline:** r 0.94–0.96, loss_scalar 0.64–0.76,
scaled-nMAE 17–24%.

**Honest scope limit (documented):** rtfuelmix has no zonal breakdown (system
total only), and Steel+Erie are ~1.35% of fleet energy / ~17× below the
residual noise floor — so this harness can only catch **fleet-wide drift**, not
per-plant regressions. Commit `7a0c5ef`.

## R1.3 — Data-integrity triage on the three worst plants

Run as a 4-agent workflow (3 plant investigations + rtfuelmix scoping) with
adversarial verification.

- **Baron Winds (wind_323822) — FIXED.** The "49–140% loss vs EIA-923" was a
  **nameplate error**: wind_meta carried goldbook `plate_mw`=238.4 MW (a stale
  CRIS/registration figure) but as-built is **130 MW** (EIA-860) / 121.8 MW
  (USWTDB 32 turbines = goldbook `sum_2024`). A fleet-wide audit confirmed Baron
  is the **only** plant with a >30% nameplate-vs-capability gap (Maple Ridge's
  apparent gap is the correct shared-EIA prorata split). Since v3 power is
  exactly linear in nameplate, 238.4→130 takes 2024 loss **49%→6%** (in band).
  Fixed wind_meta + `NAMEPLATE_OVERRIDES` guard in script 04 + removed from
  UNVERIFIED + partial-year flag in script 12.

- **Steel Wind (wind_323596) + Erie Wind (wind_323693) — DOCUMENTED, not broken.**
  Their 18%/15% nMAE-vs-PLUSWIND is a **stale-PLUSWIND-truth seam**: both
  repowered Clipper-C93 → GE2.5-116 in Dec 2019; the model correctly switches to
  the 116 m rotor from 2020 (TURBINE_SPEC_OVERRIDES), but PLUSWIND truth is built
  from the 2018 pre-repower spec for **all** years. 2018–19 nMAE ~2.4% (r 0.9997),
  2020–21 ~27% (the 1.56× swept-area mismatch). **The model is right; PLUSWIND is
  stale.** Validation window for EIA 56575/57078 = 2018–19 only. A skeptic agent
  reproduced every number independently. Recorded as `STALE_PLUSWIND_TRUTH_2018_SPEC`.

  Commit `077a0aa`.

- **Canandaigua (wind_323617) — FIXED (follow-up `3344b68`).** Surfaced by the
  R1.1 fleet hub-lift scan (it showed +13.8% at a 113 m hub for a 2008 plant).
  Same EIA-ID-collision class as Baron: wind_meta mapped it to EIA 60596
  (= Baron Winds I, 113 m V150-4.0) instead of its real Cohocton Wind Project
  (EIA 56634; 80 m GE2.5-116/C96; 87.5+37.5 = 125 MW = its NP). This baked a
  wrong power curve + a spurious +13.8% hub lift + a location 10.3 km off
  (Canandaigua's coords were literally Baron's centroid). Script 12 already fixed
  the metered side; this fixes the modeled side. Fixed eia_plant_id 60596→56634,
  coords→Cohocton, + `EIA_ID_COORD_OVERRIDES` guard in script 04. Resolved the
  60596 collision (now Baron-only).

## R2.1 — v4 freeze (compute DONE, 🛑 DECISION PENDING, uncommitted)

Re-fetched **all 7 years (2018–2024) with the corrected metadata** (the prior
2020/2024 raw dumps predated the Canandaigua fix and were stale), then built
`wind_actual_1h_site_{year}_utc.pluswind_v4.csv` for all 31 plants with
**multi-cell Method A + clip-0.25 hub-shear**. v3 + `.raw_backup` untouched (I4).

### Acceptance results

**The literal PLUSWIND-nMAE gate fails — but it is the wrong gate, by the plan's own I3:**

| Fleet vs PLUSWIND (22-plant, 2018–2021) | v3 | v4 |
|---|---|---|
| nMAE | 1.46% | **4.26%** ❌ literal |
| bias | −0.27 MW | +26 MW |
| ramp_r | 0.992 | 0.988 ✓ |

PLUSWIND is WS80-only → structurally blind to hub height, so any hub lift
"regresses" its *level* by construction (I3 / R1.1 say to disregard PLUSWIND
level for hub-shear). **Verified the +26 MW is benign, not a bug** by decomposing
every plant's v4-vs-PLUSWIND offset against its hub-lift: sub-80 m plants show
the correct down-correction (−7 to −8%), 80 m plants ≈ v3 (±multi-cell), and
high-hub plants sit above PLUSWIND by ≈ their lift_pct (Marble +6.3 vs lift 7.7,
Copenhagen +5.9 vs 6.0, Hardscrabble +11.5 vs 10.5). Every deviation maps to a
correct hub correction.

**Every *valid* gate passes or improves:**

| Gate (valid for hub-shear) | v3 | v4 |
|---|---|---|
| PLUSWIND ramp_r | 0.992 | 0.988 ✓ |
| Copenhagen LPI 2024 CFnMAE | 32.8% | **29.4%** ✓ |
| Copenhagen LPI bias | −0.60 MW | +1.48 MW (+5.3%, physical) ✓ |
| Copenhagen LPI ramp_r | 0.261 | 0.276 ✓ |
| rtfuelmix all-fleet r | 0.947 | 0.949 ✓ |
| rtfuelmix ramp_r | 0.477 | 0.491 ✓ |
| rtfuelmix scaled-nMAE | 20.0% | 19.5% ✓ |

**Recommendation given to the user: bless v4 as production.** The only failing
gate is PLUSWIND *level*, which the plan rules out for hub-shear; all valid
signals hold or improve.

**Honest caveat raised:** the **>105 m tier is validated only by physics + the
Copenhagen (95 m) analogy** — Hardscrabble (100 m) and the unanchored 2023–24
plants (Bluestone 120 m +21.9%, Baron 113 m +13.8%, Eight Point 109 m +12%)
extrapolate beyond the highest clean anchor. Per the plan, shipping the physics
lift is correct; MIS per-resource data is the eventual validator.

**Pending the user's 🛑 DECISION:** (1) bless v4 + proceed to forecast/MOS;
(2) bless v4 actuals but hold the Stage A repoint until forecast+MOS done;
(3) revisit first (e.g., cap the >105 m tier). **Nothing committed; Stage A not
repointed.**

Outputs (uncommitted): the 7 `*.pluswind_v4.csv`, `per_plant_hourly_scorecard_v4.csv`,
`rtfuelmix_fleet_scorecard_v4.csv`. Builder: `build_v4_actuals.py`.

---

## Infrastructure notes (HRRR fetching)

A meaningful chunk of wall-clock went to making the multi-cell fetch fast +
robust (needed because multi-cell requires re-downloading HRRR — the npz cache
only stores single-cell plant centroids):
- **One combined byte-range fetch** for all 6 fields (80 m + 10 m wind, surface
  pressure, 2 m temp) instead of 3 separate — verified the shortNames don't
  collide; ~3× fewer S3 GETs.
- **Crash hardening:** retry-on-timeout, catch-all per hour, save-after a
  crash-proof loop (an early run died on an unhandled S3 read-timeout at the very
  end, losing 40 min).
- **Sequential solo is fastest** (~37–47 min/year at 240 hr/min). Parallel
  streams *throttle each other* (shared S3/local limit) and `retries
  mode="adaptive"` made it ~4× worse — both reverted.
Raw npzs are gitignored (regenerable, ~29 MB each).

## Plan invariants honored

- **I1** — v4 ships uncorrected potential (internal density+SAM+7%-taper+hub-shear; no EIA-923 factor). Stage A feed unchanged until the repoint decision.
- **I2** — no physics tuned to metered. All R1.3 fixes are metadata/coverage corrections from EIA-860/USWTDB; clip-0.25 chosen from the α-vs-climatology + EIA-923-bound, not to minimize metered error.
- **I3** — level validated only on clean anchors (Copenhagen, PLUSWIND ramp-only for hub-shear); aged metered scored shape-only. This is the crux of the R2.1 acceptance read.
- **I4** — v3 + `.raw_backup` untouched; v4 on its own suffix; raw dumps reproducible.

## Open items / next steps

1. **Human 🛑 DECISION on v4** (bless / hold / revisit) — then commit the v4 artifacts.
2. **R2.1 step 3 — forecast rebuild + MOS refit on v4** (separate, longer HRRR fetch; needed so the DA forecast isn't on a v3 footing while actuals are v4, which would bias the residual distribution GEMINI learns).
3. **R3.1 — regime-conditioned MOS** (post-freeze, on v4 actuals).
4. **Strategic (human):** NYISO MIS per-resource acquisition — the only path to validate the >105 m hub lifts and the learned curve directly, and past the ~1.5% PLUSWIND ceiling. Flagged, blocks nothing.

## Key files

- Physics: [PGscen-2nd/pgscen/utils/wind_physics.py](../../PGscen-2nd/pgscen/utils/wind_physics.py) — multicell A/B, v5 hub-shear (`SHEAR_ALPHA_MAX=0.25`), v6 learned (not adopted).
- Metadata fixes: [wind_meta.csv](../../PGscen-2nd/data/NYISO_real/plant_metadata/wind_meta.csv) (Baron 130 MW, Canandaigua→56634), [04_build_plant_metadata.py](../../PGscen-2nd/scripts/04_build_plant_metadata.py) (override guards), [12_join_eia923_to_pluswind.py](../../PGscen-2nd/scripts/12_join_eia923_to_pluswind.py) (buckets/partial-year).
- R1.1: `fetch_alpha_raw.py`, `analyze_alpha.py`, `fleet_hub_lift.py` + the `alpha_*` / `fleet_hub_lift_clip025.csv`.
- R1.2: `score_vs_rtfuelmix.py` + `rtfuelmix_fleet_scorecard_v3.csv`.
- R2.1: `build_v4_actuals.py`, `score_per_plant_hourly.py` (now `MODEL_SUFFIX`-aware), the 7 `*.pluswind_v4.csv`, `per_plant_hourly_scorecard_v4.csv`, `rtfuelmix_fleet_scorecard_v4.csv`.
- Prior session: [SESSION_SUMMARY_2026-06-02.md](SESSION_SUMMARY_2026-06-02.md).
