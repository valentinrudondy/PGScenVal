# SUPERSEDED: the WIND half of Stage A (and Stage C) — retained, not deleted

**Status:** the wind portion of Stage A and the (never-built) Stage C are **superseded by
the per-plant wind pipeline** in [`../wind_per_plant/`](../wind_per_plant/). The code here is
**retained intact and reversible** — nothing is deleted — pending René's sign-off, because
dropping these is a spec amendment that is his decision to make (see
[`../../Per_Plant_Wind_Plan.md`](../../Per_Plant_Wind_Plan.md) §8).

## What is superseded

- **The `WIND_A..WIND_E` half of Stage A** — the 4 zonal-wind-sum columns of the 8-dim joint
  fit in `build_joint_inputs.py` / `run_stage_a.py`. The grid ingests wind **per plant**, so
  the plant → zonal-sum → plant round-trip is lossy; the per-plant model fits the ~31 plants
  directly with a geographic `asset_rho`.
- **Stage C** (per-plant disaggregation of the zonal wind sums). **Never built.** Its only
  artifact is the unused primitive `pgscen/model.py:conditional_multivar_normal_aggregation`
  (latent-sum conditioning — see plan §4 for the open coherence problem it carries). With no
  zonal wind sum to disaggregate, there is nothing for it to do.

## What is NOT superseded (keep using Stage A here)

- **The entire LOAD side.** Stage A's 4 load zones + Stage B's conditional 7 zones = the
  11-zone joint load model, done and calibrated. Load is intrinsically zonal (reported and
  dispatched by zone), so the zonal fit is correct there. With wind dropped, Stage A is simply
  the 4-load-zone block of that model; the two-stage load structure stays.

## The replacement (shipped)

Per-plant wind: [`../wind_per_plant/`](../wind_per_plant/), production runner
`PGscen-2nd/scripts/10_run_pgscen_wind.py` with the shipped config **`asset_rho=0.5` +
young-plant regularizer**, `in_sample=False` (leakage fixed). Evidence:
[`../wind_per_plant/RESULTS.md`](../wind_per_plant/RESULTS.md) (calibration, the §6 decision
gate, the §7 fleet-dispersion diagnostic, and §8 known limitations).

## The honest qualification

The per-plant *deliverable* (per-plant injections) is sound and well-calibrated. The genuine
trade vs Stage A is at the **aggregate/cross-zone** level: a single distance-scaled
`asset_rho` cannot reproduce the full cross-zone correlation matrix that Stage A fits each
pair directly (RESULTS.md §7/§8). This is the strongest remaining argument for retaining some
zonal structure — hence "retained, reversible," not deleted.
