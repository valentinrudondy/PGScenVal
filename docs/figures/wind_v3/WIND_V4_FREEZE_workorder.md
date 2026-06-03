# Claude Code Work Order — Wind v4 Freeze: commit, validate, forecast rebuild, repoint

You are continuing the wind potential-generation project on branch `valoche`. Full context is in `SESSION_SUMMARY_2026-06-03.md` and `WIND_POTENTIAL_IMPROVEMENT_PLAN_v2.md`; this work order is self-contained — read those only for detail.

## Situation

The **v4 actuals series is built** — multi-cell Method A + clip-0.25 hub-shear, all 31 plants × 2018–2024 — and its acceptance has been reviewed and the direction approved by the human. v4 is **uncommitted**; Stage A still reads **v3**.

## Decisions already made — do NOT re-litigate

- **Hub-shear is adopted at clip-0.25** (`SHEAR_ALPHA_MAX = 0.25`). The α diagnostic justified it: daytime median 0.143 = the 1/7 onshore climatology; night median 0.292 inflated by the stable boundary layer + HRRR's known 10 m weakness. Don't revisit the clip except as the bounded tall-tier sensitivity in Task 3.
- **The PLUSWIND-nMAE "gate failure" (1.46% → 4.26%) is expected and benign, not a bug.** PLUSWIND is WS80-only and structurally blind to hub height, so any hub lift raises its *level* offset by construction. The +26 MW was verified to map plant-by-plant onto the correct hub lift. Every *valid* gate passed/improved (Copenhagen CFnMAE 32.8→29.4, ramp_r, rtfuelmix r/ramp/scaled-nMAE). **Do not "fix" this.**
- **Do not cap the >95 m hub tier.** Capping a physically-real lift you can't yet validate biases those plants low — the same error as no-correction, relocated. If the tall tier proves α-fragile, the response is a **day/night-split α** (Task 3), never a flat cap.
- **The plan is: commit v4 now, but HOLD the Stage A repoint** until the forecast series is rebuilt on v4 and the MOS refit. The repoint flips **both** series to v4 atomically.

## Invariants (hard constraints)

- **I1 — Ship uncorrected potential.** v4 = internal density + SAM + 7%-taper + hub-shear, **no** EIA-923 factor. Don't change what Stage A consumes until the repoint.
- **I2 — Never fit physics to metered.** EIA-923 / LPI are shape/decomposition references only. Metadata fixes are corrections sourced from EIA-860 / USWTDB / goldbook — never tuning to reduce metered error.
- **I3 — Level validatable only on clean anchors** (Copenhagen; PLUSWIND ramp-only for hub-shear). Aged metered = shape only. PLUSWIND *level* is meaningless for any hub-height change.
- **I4 — Reproducibility.** Never touch v3 or the `.raw_backup` siblings. v4 stays on its own suffix.

## Working rules

- **One task = one commit**, each with its acceptance check.
- **Stop at every 🛑 and surface the numbers for human sign-off before proceeding.** These are the manual checkpoints under `acceptEdits`.
- `view` `PGscen-2nd/pgscen/utils/wind_physics.py` and `05_build_hrrr_timeseries.py` / `06_mos_bias_correction.py` before editing physics.
- **Reuse the hardened HRRR fetch — do not reinvent it:** one combined byte-range fetch for all 6 fields (80 m + 10 m wind, surface pressure, 2 m temp); retry-on-timeout; crash-proof save-after loop; **sequential-solo** (parallel streams throttle each other; `retries mode="adaptive"` made it ~4× worse — both already reverted). ~37–47 min/year for the F00 actuals.
- **If Task 2 or Task 3 changes any plant's metadata or adopted α, that plant's v4 actuals are stale → rebuild and re-score it before the forecast rebuild.** The forecast must be built on the *final* actuals physics (footing consistency).

## Task order — dependencies matter

The forecast rebuild (Task 4) is the long, expensive step and must run on **final** physics. So settle metadata (Task 2) and the tall-tier α (Task 3) first — both are cheap and may trigger small targeted actuals rebuilds — then rebuild the forecast, then repoint. Tasks 2 and 3 can run in parallel with each other.

---

### Task 1 — Commit the v4 actuals candidate (now)

Commit the uncommitted v4 artifacts: the 7 `wind_actual_1h_site_{year}_utc.pluswind_v4.csv`, `per_plant_hourly_scorecard_v4.csv`, `rtfuelmix_fleet_scorecard_v4.csv`, and `build_v4_actuals.py`. Reversible — v3 + `.raw_backup` untouched, Stage A keeps reading v3.

Commit message records: multi-cell A + clip-0.25 hub-shear; the acceptance read (PLUSWIND *level* gate invalid per I3 → disregarded; all valid gates pass/improve); fleet-sum lift +4.8%; and that this is a **candidate pending the metadata audit, tall-tier sensitivity, and forecast rebuild** before the Stage A repoint.

**Gate:** clean working tree; commit message states candidate status + acceptance reasoning.

---

### Task 2 — Fleet-wide metadata consistency audit (close the bug class)

Two serious bugs this session were the **same EIA-860-join root class**: Baron (stale goldbook 238.4 MW nameplate vs as-built 130 MW) and Canandaigua (EIA-ID collision — mapped to Baron's 60596 instead of Cohocton's 56634, giving a wrong power curve, a spurious +13.8% hub lift, and coords 10.3 km off). **Canandaigua was caught only by a secondary hub-lift signal and was NOT in the original UNVERIFIED-5.** Close the class instead of waiting for the next anomalous lift.

For **all 31 plants**, cross-check goldbook × EIA-860 × USWTDB and flag:

1. **Coord-in-hull** — plant coord lies within (or acceptably near) its USWTDB turbine convex hull / centroid. Flag any plant >~3 km from its USWTDB centroid (Canandaigua was 10.3 km; Maple Ridge ~3.7 km was previously noted — confirm it's benign).
2. **EIA-ID consistency** — the mapped `eia_plant_id` resolves to a single plant whose **name, nameplate, turbine model/rotor/hub, and coords** are mutually consistent across all three sources. Flag: ID collisions (two `wind_meta` rows → same EIA ID), name mismatches, nameplate gaps >~30% (Baron was the only one — verify none others), hub/rotor disagreements.

Fix only genuine metadata/coverage errors (I2). For each fix, add the override guard following the existing pattern (`NAMEPLATE_OVERRIDES` / `EIA_ID_COORD_OVERRIDES` in `04_build_plant_metadata.py`) and document it.

**🛑 If the audit finds any physics-affecting error** (curve, coords, nameplate): surface it — that plant's v4 actuals must be rebuilt before the forecast step.

**Output:** `metadata_consistency_audit.csv` (per-plant flags) + a short triage note for any new anomaly.
**Gate:** every plant passes or has a documented fix-or-known-issue; affected plants rebuilt + re-scored.

---

### Task 3 — Tall-tier (>95 m) hub-lift sensitivity

The hub lift is validated only up to Copenhagen's **95 m** anchor. Every plant above that extrapolates the power law beyond clean ground truth, in exactly the stable night hours where α is most inflated, with partial-load cubing amplifying any wind error. Bound the risk.

Identify all plants with hub > 95 m from `fleet_hub_lift_clip025.csv` — at minimum **Hardscrabble ~100 m (+10.5%), Eight Point ~109 m (+12%), Baron ~113 m (+13.8%), Bluestone ~120 m (+21.9%)** (confirm the full list).

For each, re-score annual energy / capacity factor under three α treatments (post-processing on already-fetched wind — no big re-fetch):
- **clip-0.25** (current adopted),
- **clip-0.20** (tighter),
- **day/night-split** — daytime α as-is (trustworthy, ~0.143); night-hour α capped at climatology (~0.15), since the inflation lives in the night tail. Reuse the day/night classification already in `analyze_alpha.py`.

Report, per tall plant: the **energy spread across the three treatments**, and a **per-year exposure** figure (what fraction of the plant's lift-affected generation falls in 2023–2024 — most are recent commissions, so this bounds how much of the v4 series the unvalidated lift actually touches).

**Decision rule:**
- Stable across treatments (swing ≲10%) → keep clip-0.25; the lift is robust.
- Swings >~10% → switch **that plant** (or the whole >105 m tier) to the **day/night-split α**. **Never a flat cap.**
- Emit the per-plant treatment spread as a documented **uncertainty estimate for the tall tier**, so Stage A / GEMINI can optionally widen those plants' scenario spread rather than truncating the lift. Don't wire it into GEMINI yourself unless the interface is obvious — leave it as a documented output.

**🛑** Surface the table + per-plant recommendation before changing any adopted physics. Any plant whose α treatment changes → rebuild + re-score its v4 actuals.

**Output:** `tall_tier_alpha_sensitivity.csv` + recommendation.
**Gate:** explicit per-plant α decision; affected plants rebuilt.

---

### Task 4 — Forecast-series rebuild + MOS refit on v4 (the gating step)

Runs only after Tasks 2 + 3 settle (final actuals physics). **Mandatory before the repoint:** a v4-actuals / v3-forecast mismatch leaks the ~5% hub-lift delta into the residual distribution GEMINI fits.

1. Rebuild the **DA forecast** for all 31 plants through the final v4 physics (multi-cell A + clip-0.25 hub-shear + any Task 2/3 fixes), 2018–2024, at the DAM issuance (18:00 UTC, **24 lead-hours per issuance**). This is a much larger HRRR fetch than the F00 actuals — budget the wall-clock and use the hardened sequential fetch.
2. **Refit the MOS** (`06_mos_bias_correction.py`) on v4 `(actual, forecast)` pairs — both sides on v4 footing. Keep the rolling 4-year prior; keep `.raw_backup`.
3. Quick **MOS-quality check**: v4-MOS vs the existing v3-MOS forecast nMAE on a held-out window (sanity that the refit didn't regress).

**Gate:** v4 forecast series + refit MOS committed; both series confirmed on v4 footing; MOS-quality check reported.

---

### Task 5 — Atomic Stage A repoint 🛑

Only after Tasks 1–4 are green (v4 actuals committed + any rebuilds, tall-tier resolved, metadata clean, forecast + MOS rebuilt on v4).

Repoint Stage A to consume **v4 for BOTH series simultaneously** (actuals + DA forecast) — never one without the other.

**🛑 Final human sign-off before this commit.** This is the production flip.

---

## Out of scope this round

- **R3.1 — regime-conditioned MOS:** post-freeze, on v4 actuals. Not now.
- **NYISO MIS per-resource acquisition:** human decision. It's the only path to validate the >95 m lifts and the learned curve directly, and past the ~1.5% PLUSWIND ceiling. Leave a note; act on nothing.

## When done

Write a short handoff (extend the session summary): what landed, the metadata-audit and tall-tier outcomes, the repoint status, and the two out-of-scope items still open.
