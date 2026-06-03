# Handoff — Wind v4 freeze COMPLETE (2026-06-03)

Closes the work order `WIND_V4_FREEZE_workorder.md`. Production now consumes
`+wind v4` (multi-cell Method A + clip-0.25 hub-shear) for both the actuals and
the DA forecast, end-to-end through Stage A and the pgscen runner.

## What landed (7 commits, branch `valoche`)

| Commit | What |
|---|---|
| `ea652b2` | Task 1 — v4 actuals candidate (31 plants × 2018–2024) |
| `f1b6548` | Task 2 — fleet metadata consistency audit |
| `5a86281` | Task 3 — tall-tier α sensitivity |
| `416a2bc` | Task 4 — v4 DA forecast + MOS refit |
| `068254a` | Task 5 — Stage A + runner repoint (production flip) |

(Earlier same-session R0/R1 commits `77829b0`→`c6941d4` set up v4: learned-curve
closed, hub-shear calibrated to clip-0.25, rtfuelmix detector, Baron/Steel/Erie
triage, Canandaigua fix. See `SESSION_SUMMARY_2026-06-03.md`.)

## Metadata-audit outcome (Task 2)

Systematic goldbook × EIA-860 × USWTDB cross-check of all 31 plants closed the
EIA-860-join bug class. **26 PASS, 5 FLAG, zero new physics-affecting errors.**
The flags are all benign/known (operator-vs-project names; Maple Ridge's shared-
EIA split; South Fork offshore no-USWTDB), and the audit confirmed the R1.3 fixes
landed (Baron now 6% gap, Canandaigua coord 0 km). One documented limitation, not
a bug: Canandaigua's multi-cell footprint is Cohocton-only (Dutch Hill omitted) —
level correct, ramp variance slightly **over**-stated, common-mode across
actual/forecast. Deferred deliberately (a fleet-wide multi-EIA cell-mapping change
belongs off the freeze critical path). See `v4_known_limitations.md`.

## Tall-tier outcome (Task 3)

All 7 plants >95 m hub re-scored under clip-0.25 / clip-0.20 / day-night-split:
energy spread **1.2–2.9%** for every plant — far under the 10% rule. **Kept
clip-0.25 fleet-wide; no day/night-split, no flat cap, no rebuilds.** Documented
tall-tier uncertainty ±1–3% energy; 5 of 7 are 2023–24 commissions so the
unvalidated lift mostly touches the post-PLUSWIND window.

## Forecast + MOS outcome (Task 4)

v4 DA forecast rebuilt (single 18Z DAM issuance, f6–f29), MOS refit on v4 pairs
(in-sample + rolling 4-yr eval 2023). **Held-out 2023 quality check PASSED
decisively:** fleet nMAE v3-MOS 20.79% → v4-MOS **17.05%** (r 0.953 → 0.966); all
28 plants improved (median per-plant 38.4% → 31.0%). Better than the "≤ ≈ v3" bar
because the hub lift is common-mode (cancels in actual−forecast) while multi-cell
smoothing + complete morning-hour coverage actively improve skill.

Known forecast limitation: early-2018 afternoon hours (f19–f29) are unavailable
(HRRRv2→v3 archive boundary, ~July 2018) → 2018 forecast 25.7% NaN. NOT a
regression (v3 2018 was 53.4% NaN); 2019–2024 clean; 2023 eval + rolling prior
unaffected.

## Repoint status (Task 5) — DONE, verified

- `build_joint_inputs.py _wind_files()` → v4 for both series (atomic; the sole
  wind entry point for `run_stage_a.py`).
- `10_run_pgscen_wind.py --variant` default → `pluswind_v4` (closed the
  footing-inconsistency footgun).
- v3 files untouched on disk; reverting = same change back.
- Verified run-correct: `build_joint_inputs([2024])` → 8-dim joint vector,
  0 NaN, K excluded, corrected fleet; `run_stage_a.py` 1-day/50-scenario smoke
  fit GEMINI and generated (50, 192) scenarios with no errors.

## v4 series on disk (production)

- Actuals: `wind_actual_1h_site_{2018..2024}_utc.pluswind_v4.csv` (raw potential).
- DA forecast: `wind_day_ahead_forecast_site_{y}_utc.pluswind_v4.csv` (MOS-corrected;
  `.raw_backup` = raw; `.rolling.csv` = out-of-sample 2023).
- MOS params: `wind_mos_params.pluswind_v4.csv` + `.rolling_2023.csv`.
- Figures: `v4_summary.png`, `v4_copenhagen_bluestone.png`, `v4_vs_lpi_aged.png`.

## Still open (out of scope this round)

1. **R3.1 — regime-conditioned MOS** (condition on predicted power/WS band instead
   of pure hour-of-day). Post-freeze, runs on v4 actuals. Not started.
2. **NYISO MIS per-resource acquisition** (human decision). The only path to
   directly validate the >95 m hub lifts and the learned curve, and past the
   ~1.5% PLUSWIND ceiling. When greenlit, re-opens hub-shear / learned-curve as
   now-validatable, and is the natural place to do the Canandaigua multi-EIA
   cell-mapping enhancement (and any other split-location plants).

## Invariants honored throughout

I1 (ship uncorrected potential — no EIA-923 factor); I2 (no physics tuned to
metered — all fixes from EIA-860/USWTDB/goldbook); I3 (level validated only on
clean anchors, PLUSWIND ramp-only for hub-shear, aged metered shape-only);
I4 (v3 + `.raw_backup` never touched, v4 on its own suffix).
