# v4 known limitations (as of the 2026-06-03 freeze)

Documented, accepted-and-deferred limitations of the `+wind v4` series
(multi-cell Method A + clip-0.25 hub-shear). None block the freeze; each has a
deliberate deferral rationale.

## 1. Canandaigua multi-cell footprint covers Cohocton only (not Dutch Hill)

**What.** Canandaigua (wind_323617) is mapped to its primary EIA 56634
(Cohocton Wind Project, 87.5 MW, 35 turbines). Its real generation is
Cohocton + Dutch Hill (56633, 37.5 MW, 15 turbines, ~4 km W) = 125 MW. The
multi-cell weight matrix keys on a single EIA ID, so Canandaigua's footprint is
Cohocton's 8 HRRR cells; Dutch Hill's cells are not included.

**Effect.**
- **Level: correct.** Right power curve (GE2.5-116/C96), right hub (80 m), right
  nameplate (125 MW). The energy Stage A consumes as potential is right.
- **Ramp variance: slightly OVER-stated** (sign verified 2026-06-03). Concentrating
  all 125 MW on Cohocton's single, tighter wind field gives *less* spatial
  decorrelation than the real Cohocton+Dutch Hill split 4 km apart — so the model
  runs marginally choppier than reality for this one plant.
  *(Note: an earlier commit message, f1b6548, said "understated" — that sign was
  wrong; this doc is authoritative.)*
- **Net on GEMINI scenarios: smaller still.** The footprint approximation is
  common-mode in the actuals and the DA forecast (same physics module), so it
  largely cancels in the actual−forecast residual GEMINI fits.

**Why deferred (not "it's small").** The proper fix is **multi-EIA cell mapping**
in `build_plant_cell_weights` / `build_sam_curves` — a **fleet-wide physics-module
change** that puts all 30 other plants in the blast radius and would warrant fleet
re-validation. Inserting that onto the critical path right before the expensive
forecast fetch is exactly what the task sequencing was built to avoid. Do it
deliberately later, with its own validation — the natural place to also revisit
any other split-location plants, and a candidate for the MIS-era pass.

**Scope.** One 125 MW plant out of 31; second-order variance effect; common-mode
cancellation in scenarios.

## 2. >95 m hub lift validated only by physics + the Copenhagen (95 m) analogy

The 7 plants above 95 m (Hardscrabble 100 m … Bluestone 120 m) extrapolate the
hub-shear power law beyond the highest clean anchor (Copenhagen, 95 m). Task 3
showed the lift is robust to the α treatment (1–3% spread across
clip-0.25 / clip-0.20 / day-night-split), so clip-0.25 is kept fleet-wide, but
the absolute lift on these plants has no direct ground truth. Documented
tall-tier uncertainty: ±1–3% energy. 5 of 7 are 2023–2024 commissions, so the
unvalidated lift mostly touches the post-PLUSWIND window. **MIS per-resource data
is the only direct validator** (strategic, out of scope this round).

## 3. Early-2018 afternoon DA-forecast hours unavailable (HRRR archive boundary)

The v4 DA forecast uses a single 18:00 UTC DAM issuance, fhours f6-f29 (next UTC
day's 24 hours). HRRR's 18Z **extended** forecast (f19-f48) only exists in the
NOAA archive from the HRRRv3 transition (~July 2018). So for **Jan-mid-Jul 2018**,
the afternoon/evening forecast hours (H13-23 = f19-f29) genuinely do not exist
and come out NaN. Verified directly: 2018-01 t18z f25 MISSING; 2018-08, 2019,
2023 all EXIST.

Scope: 2018 v4 forecast is 25.7% all-NaN (the early-year afternoons). **This is
NOT a v4 regression** — v3's 2018 forecast was 53.4% NaN (its 06Z/12Z lead-18-36
construction hit the same boundary AND lost morning hours too). v4 is *more*
complete in 2018 (morning f6-18 always available). 2019-2024 are clean for both.
There is no fix/fallback — the extended forecast was never archived pre-July-2018.

Impact: the rolling-MOS held-out eval (2023) and its 4-year prior (2019-2022) are
unaffected; the in-sample MOS fit simply has fewer 2018-afternoon pairs. Stage A
/ GEMINI training on 2019+ is unaffected.

## 4. PLUSWIND level is not a valid gate for v4

PLUSWIND is WS80-only and hub-blind; v4's hub lift necessarily raises its level
offset vs PLUSWIND (fleet nMAE 1.46% → 4.26%). This is structural, not a
regression (decomposed plant-by-plant onto the correct hub lift). Validate v4
level only on clean metered anchors (Copenhagen) and shape on PLUSWIND ramp_r.
