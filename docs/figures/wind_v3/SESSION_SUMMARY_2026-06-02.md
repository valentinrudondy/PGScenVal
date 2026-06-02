# Wind-model improvement session — 2026-06-02 summary

This document captures the work done in a single working session against
[WIND_POTENTIAL_IMPROVEMENT_PLAN.md](WIND_POTENTIAL_IMPROVEMENT_PLAN.md).
The plan targets the **pre-curtailment hourly per-plant potential** series
that Stage A / GEMINI consume — the v3 PLUSWIND-style output without the
EIA-923 loss correction.

## Where we ended up

| Plan task | Status | Outcome |
|---|---|---|
| 0.1 Per-plant hourly scorecard | ✅ committed `0723d4c` | Frozen v3 baseline; 37 rows × 26 cols |
| 0.2 Lat/lon fixes for 5 unverified plants | ✅ closed (no-op) | All 5 already match USWTDB centroids at 0 km; attribution corrected in script 12 + memory |
| 0.3 rtfuelmix fleet harness | ⏸ deferred | Less valuable now that NY_WindFarmGenData LPI covers 2022-2024 hourly |
| 1.1 Multi-cell aggregation A vs B | ✅ committed `60e32fe` | **Method A adopted** — wins every metric, every anchor |
| 1.2 Hub-height shear correction | ✅ committed `bb23264` | **Investigated, not adopted** — Copenhagen LPI bias regressed |
| 2.1 Archetype-learned power curve | ⏳ uncommitted | **Investigated, recommendation: not adopted** — within-noise improvements, regresses on PLUSWIND in-era |
| 3.1 Regime-conditioned MOS | ⏸ pending | Independent stream; lower value for the GEMINI/Stage A actuals series |
| Final pluswind_v4.csv full-fleet rebuild | ⏸ pending | Run multi-A on all 31 plants × 2018-2024 after 2.1 closes |

**Current production approach: multi-cell Method A (v4)**. v5hub and v6lrn are
documented investigations on the same branch but not adopted.

## What we built

### Phase 0 — measurement backbone

**Task 0.1 — per-plant hourly scorecard** ([experiments/wind_validation/score_per_plant_hourly.py](../../experiments/wind_validation/score_per_plant_hourly.py))

Consolidated v3 baseline against three reference classes, with `level_validatable`
flag so later improvements can only beat what is fair to measure:

- **vs PLUSWIND per plant, 2018-2021** (level + shape both meaningful — potential-grade reference)
- **vs Copenhagen LPI 2024** (clean single-plant anchor; raw bias −2.2%)
- **vs Maple Ridge / Marble agg / Noble agg LPI 2022-2024** (aged metered — shape-only via CF-normalised nMAE and ramp Pearson r)

Key extension during the session: the user added 8 new `NY_WindFarmGenData_*.xls`
files extending LPI coverage from 2024-only to **2022-09 → 2026-06**. The
scorecard was widened to use these (per-year + pooled breakdowns).

**Frozen baseline headlines:**
- Fleet vs PLUSWIND 22-plant overlap 2018-2021 pooled: nMAE **1.46%**, r **0.9996**, ramp_r **0.992**
- Copenhagen LPI 2024 bias: **−2.2%** of ref mean — matches plan's clean-anchor callout
- The top-nMAE-per-plant list surfaces Steel Wind (18%) and Erie Wind (15%) — flagging Task 0.2

Output: [per_plant_hourly_scorecard.csv](per_plant_hourly_scorecard.csv).

**Task 0.2 — surprising finding**

Memory file ([project_wind_meta_lat_lon_issues.md](file:///Users/val/.claude/projects/-Users-val-Desktop-Princeton/memory/project_wind_meta_lat_lon_issues.md))
flagged 5 plants as having "lat/lon errors" (Baron Winds, Stony Creek/Orangeville,
Ball Hill, Noble Wethersfield, South Fork). Cross-check against USWTDB:

| Plant | wind_meta vs USWTDB centroid | wind_meta vs EIA-860 office |
|---|---|---|
| Baron Winds | **0.00 km** | 12.00 km |
| Stony Creek/Orangeville | **0.00 km** | 14.50 km |
| Ball Hill | **0.00 km** | 16.91 km |
| Noble Wethersfield | **0.00 km** | 5.86 km |
| South Fork (offshore) | n/a — coord = EIA-860 | 0.00 km |

The "lat/lon errors" were measured against **EIA-860 plant-office**, which is
the operator address, not the turbine field. USWTDB centroids over 25-84 turbines
per project are the authoritative HRRR-relevant locations, and they all match
wind_meta exactly. **No lat/lon edits needed**.

The plants stay in the `UNVERIFIED` bucket of `12_join_eia923_to_pluswind.py`
because their EIA-923 loss-fraction outliers are real (Wethersfield 51% in 2023,
Orangeville 30-44% sustained, Baron Winds 49-140%), but the cause is NOT
location — it's physics (power curve, hub height, real curtailment, or HRRR
pocket-scale bias). The reason strings in script 12 were rewritten to reflect
this. Memory updated accordingly.

### Phase 1 — physics levers

**Task 1.1 — multi-cell spatial aggregation**

Probe of USWTDB turbine distribution showed: median NY plant spans **7 HRRR cells**
(max 17, Maple Ridge with 195 turbines over 15.8 × 14.1 km). Only 4/31 plants
have >70% of turbines in their dominant cell. Single-cell sampling loses real
spatial spread for 27/31 plants.

Two methods implemented in [PGscen-2nd/pgscen/utils/wind_physics.py](../../PGscen-2nd/pgscen/utils/wind_physics.py):
- `pluswind_v4_power_multicell_A`: per-cell SAM curve eval, then nameplate-weighted sum to plant. Density + loss applied cell-local.
- `pluswind_v4_power_multicell_B`: weight-average WS over cells first, then one curve eval. Cheaper but loses curve nonlinearity in the 5-9 m/s band.

Pilot ([experiments/wind_validation/run_multicell_pilot.py](../../experiments/wind_validation/run_multicell_pilot.py)):
Copenhagen + Marble agg (5 plants), full year 2020 (PLUSWIND truth) + 2024 (LPI).
Multi-cell requires re-downloading HRRR `.subset` files from S3 (existing npz
cache stores only single-cell plant-centroid positions).

**Headline numbers:**

| Anchor | single | multiA | multiB |
|---|---|---|---|
| 2020 fleet vs PLUSWIND nMAE | 4.49% | **2.86%** | 2.95% |
| 2020 fleet ramp_r | 0.976 | **0.990** | 0.989 |
| 2024 Copenhagen LPI bias | −1.51 MW | **−0.31** | −0.37 |
| 2024 Copenhagen CFnMAE | 38.5% | **31.0%** | 32.0% |
| 2024 Marble agg CFnMAE | 41.1% | **40.3%** | 40.8% |

**Method A wins on every metric on every anchor.** A vs B margins small (typically
<1pp CFnMAE) but consistent — and A is the principled choice because per-cell
curve evaluation respects the cubic partial-load nonlinearity.

**Decision: adopt Method A.** Full-fleet pluswind_v4.csv generation deferred
until Tasks 1.2 and 2.1 close so we rebuild only once.

**Task 1.2 — hub-height shear correction**

NY fleet hub-height distribution is mostly bimodal: 15 plants at 80 m baseline
(unchanged), 2 plants at 66-67 m (Madison, Fenner — small/old), 13 plants at
91-120 m (newer, mostly 2023-2024 commissions). For α=1/7, a 100 m hub gets
+10% partial-load power vs 80 m baseline.

Added in [wind_physics.py](../../PGscen-2nd/pgscen/utils/wind_physics.py):
- `estimate_shear_alpha(ws80, ws10)`: per-hour power-law α from HRRR 10 m and 80 m wind, clipped to [−0.10, 0.40].
- `extrapolate_to_hub(ws80, alpha, hub_h_m)`: standard power-law lift.
- `pluswind_v5_power_multicell_A_hubshear`: A with per-(plant, cell) hub extrapolation.

Pilot extended to fetch HRRR WS10 (UGRD/VGRD at 10 m). Smoke test confirmed:
- 3 Marble satellite plants at 80 m hub: zero change (invariant verified)
- Marble River 94 m: +13.8% lift
- Copenhagen 95 m: +8.2% lift

**Verdict against plan acceptance gate** ("net improvement on level-validatable
plants; no shape regression"):

| Anchor | multiA | v5hub | Direction |
|---|---|---|---|
| 2020 fleet PLUSWIND nMAE | 2.86% | 3.86% | **worse** (I3 trap — PLUSWIND is WS80-only too, so this is structurally meaningless) |
| 2024 Copenhagen LPI bias | −0.31 MW | **+1.81 MW** | **regresses** (overshoots metered by ~6.5%) |
| 2024 Copenhagen CFnMAE | 31.02% | 29.24% | improves marginally |
| Ramp_r | 0.990 | 0.987 | flat |

The HRRR-derived α over-lifts Copenhagen. Two readings:
1. **α is systematically high** (stable-BL nights, WS10 under-estimation in HRRR) — fix would be tighter clipping (e.g., α ≤ 0.20) or blend with α=1/7 climatology
2. **α is right; the ~6.5% is real Copenhagen losses** not captured by the 7% base loss

Either way, current clipping is too generous for level-anchored adoption.

**Decision: defer hub-shear adoption.** Task 2.1 (learned curve) might absorb
some high-hub effect via archetype-level fitting; revisit hub-shear with
tighter clipping if it still adds value after 2.1.

### Phase 2 — learned curve (Task 2.1)

**Archetype design — Option A adopted**

Probe of USWTDB turbine specs showed the NY fleet's specific power
(cap_kW / swept_area_m²) is **bimodal** with a clear cluster gap at 268-304 W/m².
Five archetype options were laid out; the user picked **Option A (2 archetypes by SP)**:

- **A1 (SP ≥ 285 W/m²)** — 16 plants. Legacy GE1.5-77 / V82-1.65 / V66 / GE1.5-70.5 / V112-3.075 / G90 / MM92 / N117.
- **A2 (SP < 285 W/m²)** — 14 plants. Modern large-rotor: GE2.5-116 / V110 / V112 / V150 / G114 / GE1.62-100/103 / SG-4.44 / GE5.5-158.
- 1 plant unknown (South Fork offshore — no USWTDB).

**Curve training** ([experiments/wind_validation/train_archetype_curves.py](../../experiments/wind_validation/train_archetype_curves.py))

Held-out strategy: train on PLUSWIND 2018-2020, hold out 2021 (in-era) + 2024 LPI
Copenhagen (hard held-out).

For each PLUSWIND-overlap plant (22 plants × 2018-2020 = ~26k hours), load
HRRR WS80 + density at the plant-centroid cell from the existing npz cache,
compute density-corrected WS, pair with PLUSWIND truth power → CF.
Pool by archetype, bin density-corrected WS in 0.25 m/s steps, take **median**
CF per bin (robust to outage hours), fit **isotonic regression** per archetype.

Training pool: A1 = 389k plant-hours across 15 PLUSWIND plants;
A2 = 181k plant-hours across 7 PLUSWIND plants.

Outputs:
- [archetype_curves.csv](archetype_curves.csv) — final CF curves
- [archetype_assignment.csv](archetype_assignment.csv) — per-plant archetype + spec_pw
- [archetype_curves_fit.csv](archetype_curves_fit.csv) — per-bin diagnostic (count, P25, median, P75, fit)
- [archetype_curves.png](archetype_curves.png) — visualization vs SAM curves

The curves look clean — both archetypes show tight binned medians with isotonic
fits riding the IQR centers; A2 saturates ~1 m/s earlier than A1 (expected for
lower specific power).

**v6 physics + pilot** — added `pluswind_v6_power_multicell_A_learned` to
wind_physics.py. Same multi-cell A logic but using per-plant archetype curves
(SAM fallback for "unknown"). No separate loss step — the learned curve already
absorbs PLUSWIND's 7% loss via training.

Pilot run: same 5 plants, full year 2020 + 2024.

**Verdict** (multi-A v4 = baseline; v6lrn = candidate):

| Anchor | multiA | v6lrn | Delta |
|---|---|---|---|
| 2020 fleet PLUSWIND nMAE | **2.86%** | 3.12% | **−0.26pp regress** |
| 2020 fleet CFnMAE | **2.67%** | 2.78% | −0.11pp regress |
| 2024 Copenhagen LPI bias | **−0.31** | −0.70 | −0.39 MW worse |
| 2024 Copenhagen LPI nMAE | 30.52% | **30.48%** | +0.04pp (noise) |
| 2024 Copenhagen LPI CFnMAE | **31.02%** | 31.58% | −0.56pp regress |
| 2024 Marble agg CFnMAE | **40.31%** | 40.36% | flat |
| Ramp_r everywhere | identical | identical | flat |

**v6 does NOT clear the plan's acceptance gate.** Improvements are within
noise (<0.1pp); regressions exceed 0.2pp on PLUSWIND in-era and Copenhagen
CFnMAE.

**Likely reasons v6 didn't deliver:**

1. **Train/apply scale mismatch**: trained on plant-aggregate single-cell WS,
   applied per-cell in multi-cell A. The pooling math creates systematic offsets.
2. **Archetype-pooling cost > terrain absorption benefit**: Marble River's
   V112-3.075 sits in A1 dominated by GE1.5-77 — loses its specific shape.
3. **Curve inherits PLUSWIND's biases**: training on PLUSWIND absorbs
   PLUSWIND's sampling choices, but those choices no longer apply per-cell.

**Recommendation: defer v6, same as v5hub.** Multi-A v4 stays as production.

## Reflection — what the anchors actually told us

The 30% Copenhagen LPI nMAE concerned the user; the explanation matters for
all of these tasks:

- **Potential vs potential (PLUSWIND fleet)**: multi-A nMAE **2.86%** in the
  5-plant pilot, **1.46%** in the full 22-plant Task 0.1 baseline.
  That's the closest thing to "model quality" we have.
- **Potential vs metered level (clean anchor)**: Copenhagen LPI 2024 bias
  **−0.31 MW = −1.1%** — essentially zero level offset.
- **Potential vs metered hourly**: nMAE 30% is mostly structural noise
  (outages, sub-hourly curtailment, ramp-timing slippage on a single 80 MW
  plant) — not model error. Plan §I3 / Appendix A is explicit about this.

The strategic note in the plan bears repeating: **NYISO MIS per-resource data
is the only signal that would let us decompose `potential − availability −
wake − curtailment` per plant per hour**. Without it, we're at the floor of
what existing anchors can resolve, and sub-1pp refinements (hub-shear,
learned curves) can't be distinguished from anchor noise.

## Files committed

Three commits land on the `valoche` branch:

- `0723d4c` — Add Phase 0 per-plant hourly scorecard freezing v3 baseline
- `60e32fe` — Task 1.1 multi-cell aggregation: Method A wins on every anchor
- `bb23264` — Task 1.2 hub-shear: investigated, not adopted; gate not met on Copenhagen

**Uncommitted (Task 2.1, current state):**

- `PGscen-2nd/pgscen/utils/wind_physics.py` (modified — added archetype shear functions and v6 learned-curve physics function)
- `experiments/wind_validation/run_multicell_pilot.py` (modified — added v6 pilot path)
- `experiments/wind_validation/score_multicell_pilot.py` (modified — recognizes v6lrn output)
- `experiments/wind_validation/train_archetype_curves.py` (new)
- `docs/figures/wind_v3/archetype_curves.csv`, `archetype_assignment.csv`, `archetype_curves_fit.csv`, `archetype_curves.png` (new)
- `docs/figures/wind_v3/multicell_pilot_2020_v6_*.csv`, `multicell_pilot_2024_v6_*.csv` (new pilot outputs)

Pending decision on whether to commit Task 2.1 as "investigated, not adopted"
(same posture as Task 1.2) before moving to the final full-fleet rebuild.

## Where to pick up next

1. **Close Task 2.1 with a commit** — same posture as Task 1.2: investigated, documented, deferred. Adopts multi-A v4 as the production approach.
2. **Task 3.1 (regime-conditioned MOS)** is independent of the actuals chain (it touches forecast bias correction). Lower value if the GEMINI/Stage A goal is the actuals series; skip or schedule for later.
3. **Final step**: run multi-A v4 on all 31 plants × 2018-2024 → ship a new
   `pluswind_v4.csv` series. Estimated compute: ~2-3 hours of HRRR re-download
   (multi-cell needs cells the existing npz cache doesn't have).
4. **Strategic open question**: is NYISO MIS data acquisition on the table?
   If yes, it becomes the only path past the ~1.5% PLUSWIND ceiling and
   unlocks proper validation of hub-shear / learned-curve at the per-plant level.

## Plan invariants honored throughout

- **I1** — Stage A / GEMINI consumes uncorrected potential (no EIA-923 layer). All work targets that series.
- **I2** — Never fit physics to metered. v6 curves trained only on PLUSWIND potential-grade truth, not LPI aged-metered.
- **I3** — Level is validatable only on clean anchors (Copenhagen + PLUSWIND). Aged metered scored shape-only via CFnMAE + ramp_r.
- **I4** — Reproducibility preserved. v4 / v5 / v6 outputs went to new suffixes (`.pluswind_v4`, etc.), never overwrote v3.

## Memory updated

- [project_lpi_2024_validation.md](file:///Users/val/.claude/projects/-Users-val-Desktop-Princeton/memory/project_lpi_2024_validation.md) — extended LPI window 2022-09 → 2026-06; per-year v3 skill table; reference to per_plant_hourly_scorecard.csv as the unified frozen baseline.
- [project_wind_meta_lat_lon_issues.md](file:///Users/val/.claude/projects/-Users-val-Desktop-Princeton/memory/project_wind_meta_lat_lon_issues.md) — coords are correct; attribution in script 12 reframed; Maple Ridge 3.71 km from USWTDB centroid noted as potential future fix (not in original UNVERIFIED-5).
