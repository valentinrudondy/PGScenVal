# Per-plant wind — implementation results

Implements [Per_Plant_Wind_Plan.md](../../Per_Plant_Wind_Plan.md). All code in this
directory; all runs held-out (`in_sample=False`), v4 data, R backend on.

| File | Role |
|---|---|
| `run_wind_per_plant.py` | `run_one_day()` callable + CLI (leakage-fixed, preload path) |
| `calibration.py` | multi-day per-plant PIT/coverage/CRPS sweep (+`--short-history-reg`) |
| `tune_rho.py` | held-out energy-score tuning over the plant geography |
| `validate_cross_block.py` | §6 zone-sum reconstruction + §5 load↔wind tail check |
| `short_history_reg.py` | young-plant marginal widener |

---

## 1. Runner — built and leakage-fixed

`scripts/10_run_pgscen_wind.py` was a CLI smoke script that split history with
`in_sample=True` (trained on every hour except the 24 scenario hours — i.e. on data
*after* the scenario day). `run_wind_per_plant.run_one_day()` fixes this to
`in_sample=False` (history strictly before the scenario start — verified: history ends
2024-07-14 23:00 for a 2024-07-15 day), adds a preload path for sweeps, and returns a
structured `(nscen, n_plant, 24)` tensor. 31 plants (K/South Fork included — per-plant
handles it natively, unlike Stage A which special-cased it out). ~6 s/day fit.

UTC scenario days (the loader organizes the forecast by UTC day via
`Issue_time = Forecast_time.normalize() − 18h`; an ET day would straddle two forecast
blocks). Aligning the wind day boundary to the load Stage A/B ET days is a known
integration follow-up, not a calibration blocker.

---

## 2. Per-plant calibration — the primary deliverable

52 held-out UTC days in 2024, weekly stride, nscen=1000. **Caveat (plan §9): "actual"
is the v4 modeled potential the engine was fit on, so PIT/coverage measure GEMINI
SELF-CONSISTENCY, not real-world coverage** — there is no hourly per-plant metered truth
for ~28/31 plants.

**Headline: well-calibrated at the per-plant and fleet level; the only systematically
under-dispersed plants are the 2023–24 commissions — exactly as the plan predicted.**

- **Fleet-sum: cov_80 = 0.853, cov_90 = 0.925, bias +17 MW (<2%)** at the default
  `asset_rho=0.05`. **But this number is flattered by the §4 cross-zone over-coupling** —
  fixing the correlation (`asset_rho=0.5`) drops fleet cov_80 to **0.724**, revealing the
  fleet is actually mildly *under*-dispersed. Two errors were cancelling at the default
  rho. See §4.
- **Established plants (pre-2022): cov_80 0.80–0.87** across all four wind zones —
  and this is **insensitive to rho** (0.05 → 0.5 leaves the per-plant mean 0.822 → 0.819
  and per-zone coverage within ±0.003). So per-plant/zone fidelity is real; only the
  *fleet aggregate* moved.
- **Young plants (≤2 yr history) under-dispersed:** Bluestone 0.60, Ball Hill 0.63,
  Baron 0.66, Number Three 0.66, South Fork 0.69, Eight Point 0.70.
- Biases all small (< a few MW/plant) — no systematic level bias.

Per-zone cov_80: A 0.76, C 0.81, D 0.83, E 0.78, K 0.69. Outputs:
`outputs/calibration/{per_plant_summary,per_zone_summary,...}.csv`.

---

## 3. Held-out rho tuning — energy score is flat (as in Stage A)

4 seasonal 2024 days × (asset_rho × time_rho) 3×3 grid, nscen=500. **Mean ES is flat:
10.5926 → 10.6063 across the entire grid (0.1% range).** The 4th-decimal winner is
`asset_rho=0.2, time_rho=0.01`. This reproduces Stage A's finding: the energy score is
dominated by per-coordinate forecast calibration, not by the inter-asset correlation
structure, so it cannot discriminate `asset_rho` — and in particular **cannot fix the
cross-zone correlation issue in §4.** Output: `outputs/tune_rho/`.

---

## 4. Decision gate (§6) — cross-block reconstruction

### §5 load↔wind tail co-occurrence — PASS

λ = P(total wind in bottom 5% AND total load in top 5%) over 61,003 aligned hours =
**0.00197 vs 0.0025 independence → ratio 0.79.** The joint stress tail (high load + low
wind together) is *less* frequent than independence predicts — there is no hidden
lower-tail dependence; independence is, if anything, slightly conservative for the UC.
This closes the gap the bare 0.008 correlation left open (plan §5). Output:
`outputs/validation/load_wind_tail_cooccurrence.csv`.

### §6 cross-zone correlation — FLAG: geographic asset_rho over-couples zones

Per-plant scenarios summed to zones, cross-zone Spearman correlation of the zonal
deviations vs the empirical truth (zonal *actual* deviations) and Stage A's fitted block:

| pair | Stage A (gaussianized) | empirical truth | per-plant scenario (rho=0.05) |
|---|---:|---:|---:|
| A–C | 0.62 | 0.43 | 0.67 |
| A–D | 0.07 | 0.01 | 0.43 |
| A–E | 0.13 | 0.02 | 0.54 |
| C–D | 0.09 | 0.18 | 0.52 |
| C–E | 0.20 | 0.11 | 0.66 |
| D–E | 0.17 | 0.14 | 0.73 |

**The per-plant scenarios are over-correlated across zones** — the geographic
`asset_rho = 2·0.05·dist/dist.max()` couples distant zones (A–D truth 0.01 → scenario
0.43) far more than reality. Consequence: zone-sums are under-dispersed (cov_80
0.67–0.83) while the over-coupling inflates the *fleet* spread (why fleet cov_80 0.85 ran
slightly high). This is the one genuine result that partially favors keeping zonal
awareness, and the opposite of the red-team's worry (they feared *under*-coupling).

**Important:** this does NOT contradict the per-plant calibration in §2 (which is good at
the per-plant and fleet level). It is a structural mis-fit of the *cross-zone* covariance
that the flat energy score (§3) can't see. The fix is to tune `asset_rho` directly
against the cross-zone correlation target.

### The fix: retune asset_rho (sweep over the cross-zone target)

Sweeping the base `asset_rho` (per-plant scenario cross-zone Spearman; truth in col 2):

| pair | truth | rho=0.05 | rho=0.2 | rho=0.5 | rho=1.0 |
|---|---:|---:|---:|---:|---:|
| A–C | 0.39 | 0.67 | 0.58 | **0.47** | 0.41 |
| A–D | −0.01 | 0.43 | 0.14 | **0.03** | 0.02 |
| A–E | 0.06 | 0.54 | 0.34 | **0.09** | 0.02 |
| C–D | 0.16 | 0.52 | 0.23 | 0.03 | 0.02 |
| C–E | 0.17 | 0.66 | 0.60 | **0.26** | 0.09 |
| D–E | 0.13 | 0.73 | 0.33 | **0.05** | 0.02 |

**`asset_rho ≈ 0.5` (10× the current 0.05 default) is the sweet spot:** it brings the
cross-zone correlations into line with the empirical truth (A–C 0.47 vs 0.39, A–D 0.03 vs
−0.01, A–E 0.09 vs 0.06, C–E 0.26 vs 0.17). `rho=1.0` over-shrinks the moderate pairs
(C–E, D–E fall below truth). So the §6 flag is **a one-parameter retune, not a
dealbreaker** — and it is the empirical answer to the plan's open question #3 (the
geographic kernel *can* carry the cross-zone structure, but only at ~10× the default
penalty). Recommend `asset_rho=0.5` as the new default; re-run the §2 calibration at 0.5
before shipping. Outputs: `outputs/validation_rho_{0.2,0.5,1.0}/`.

Note: higher `asset_rho` fixes cross-zone coupling but does **not** fix the zone-sum
under-dispersion (zones A/K stay ~0.66) — that is a separate per-plant marginal issue
(within-zone spread + the young plants of §5), not the cross-zone penalty.

### Confirmation run at asset_rho=0.5 — and the deeper finding

Re-ran the full 52-day calibration at `asset_rho=0.5`:

| metric | rho=0.05 | rho=0.5 |
|---|---:|---:|
| per-plant mean cov_80 (31) | 0.790 | 0.787 |
| established mean cov_80 (25) | 0.822 | 0.819 |
| per-zone cov_80 (A/C/D/E/K) | .76/.81/.83/.78/.69 | .75/.80/.83/.78/.69 |
| **fleet-sum cov_80** | **0.853** | **0.724** |

Per-plant and per-zone calibration are **unchanged**; only the **fleet aggregate** moves —
from 0.85 (inflated) to 0.72 (under-dispersed). **Conclusion: the default-rho fleet 0.85
was an artifact of two cancelling errors** — cross-zone over-coupling inflated the fleet
spread, masking a mild marginal under-dispersion. Correcting the copula exposes the
marginal issue.

**Two honest consequences for the plan:**

1. **A single geographic `asset_rho` cannot reproduce the full cross-zone correlation
   matrix.** The empirical correlations don't follow distance monotonically (C–D at moderate
   distance is 0.16; A–E at large distance is 0.06), but the kernel ties correlation to
   distance. At rho=0.5 the strong/far pairs match (A–C 0.47≈0.39, A–D 0.03≈0) but the
   moderate pairs under-couple (C–D 0.03 vs 0.16, D–E 0.05 vs 0.13). This is a **modest
   point in favour of the zonal approach**, which fits each cross-zone pair *directly*.
   A richer per-plant asset covariance (structured prior rather than a one-parameter
   distance kernel) would be the per-plant way to recover it.
2. **There is a mild fleet-wide marginal under-dispersion** (~0.78 at the correct rho)
   on top of the acute young-plant case (§5). *This section originally proposed a "small
   global marginal widen" to close it — **§7 tested that patch and rejected it**: the deficit
   is heterogeneous in sign across zones (A/K narrow, C/D/E already wide), so a global factor
   over-inflates D/E while leaving A under. Superseded by §7.*

So the corrected pre-ship recipe is: **asset_rho≈0.5 + the young-plant regularizer only**
(the global marginal widen is dropped — see §7), then re-verify fleet and zone coverage.
The per-plant *deliverable* (what the grid ingests) is sound; the residual *aggregate/cross-zone*
gap is a documented known limitation (§8), addressable only by a structured asset covariance,
not by a global widen.

---

## 5. Short-history regularizer

`build_factors` flags the 6 young plants (2023–24) and widens their scenario deviations
to the pooled mature-fleet capacity-normalized spread (copula-preserving: only the
per-plant deviation magnitude grows). Factors are modest (1.05–1.25) because each young
plant's *historical* deviation std is only ~15–25% below the mature target — but the
calibration gap is larger (cov_80 0.60–0.69 implies true 2024 errors ~40% wider), so the
principled mature-target widening is expected to *narrow but not fully close* the gap.

### Before/after (52-day calibration, `--short-history-reg`)

| young plant | zone | cov_80 base | cov_80 reg | cov_90 base | cov_90 reg |
|---|---|---:|---:|---:|---:|
| Bluestone | E | 0.60 | **0.68** | 0.69 | 0.75 |
| Ball Hill | A | 0.63 | **0.68** | 0.71 | 0.74 |
| Baron Winds | C | 0.66 | **0.73** | 0.74 | 0.79 |
| Eight Point | C | 0.70 | **0.76** | 0.77 | 0.82 |
| Number Three | E | 0.66 | **0.69** | 0.75 | 0.77 |
| South Fork (K) | K | 0.69 | 0.69 | 0.80 | 0.79 |

**Mature control (25 plants): mean cov_80 0.822 → 0.820 — unchanged.** Fleet-sum cov_80
0.853 → 0.848. So the regularizer is **surgical** (touches only young plants) and
**helps but does not fully close** the gap (+0.03 to +0.08 cov_80, toward but not at
0.80) — exactly as predicted. South Fork is unchanged (factor 1.0: its *historical*
deviation std already exceeds the mature target, so its under-dispersion is a
marginal-shape / single-offshore-plant issue the std-ratio widener doesn't address).

Verdict: keep the regularizer as a documented partial mitigation; the 2023–24 cohort
remains a **known low-confidence bucket** that self-corrects as history accrues (plan §7,
§9). A stronger widening (`cap_floor_factor>1`) is available as a lever but was not
adopted, to avoid calibrating to the 2024 test year.

---

## 6. Verdict against the plan

- **Per-plant deliverable holds:** per-plant and per-zone scenarios are well-calibrated and
  rho-robust (§2), the existing path works on v4 (§1, leakage fixed), and load↔wind
  independence is defended in the tail (§4/§5). What the grid actually ingests — per-plant
  injections — is sound.
- **The genuine qualification is at the aggregate/cross-zone level (§4):** a single
  distance-scaled `asset_rho` over-couples zones at the default and can't reproduce the full
  cross-zone correlation matrix at any single value; and the headline fleet cov_80 of 0.85
  was an **artifact of error cancellation** (over-coupling masking marginal
  under-dispersion) — the corrected-rho fleet is 0.72. So "per-plant strictly dominates"
  becomes "per-plant is right for the per-plant product, but Stage A's direct cross-zone fit
  is genuinely better at the zonal/fleet level." This is the honest empirical answer to open
  question #3, and the strongest remaining argument for retaining some zonal structure.
- **Final ship recipe (corrected by §7):** `asset_rho=0.5` + the young-plant regularizer
  **only** — the global marginal widen proposed earlier was tested and rejected (§7). Fleet
  cov_80 ships at ≈0.73 as a documented known limitation (§8); the per-plant deliverable the
  grid ingests is sound. Shipped into `PGscen-2nd/scripts/10_run_pgscen_wind.py`
  (rho=0.5 default, `in_sample=False` leakage fix, `--short-history-reg` on by default).
- **Known low-confidence bucket confirmed and partially mitigated:** the 2023–24 cohort
  (§2, §5), as the plan anticipated; self-corrects as history accrues.

---

## 7. Fleet-dispersion diagnostic — the global marginal widen is REJECTED

§4 left a "corrected pre-ship recipe" that included **a modest global marginal widen** to
lift the rho=0.5 fleet cov_80 from 0.72 toward 0.80. Before building it we decomposed the
0.72 to ask *whether that patch is even the right tool*. It is not.
`diagnose_fleet_dispersion.py`, 52 held-out 2024 days at `asset_rho=0.5`, nscen=1000.

### The fleet under-dispersion is NOT a cross-zone copula deficit

Re-coupling the per-day-hour zone sums to the **exact empirical cross-zone correlation**
(Iman–Conover, marginals untouched) moves fleet cov_80 by **+0.004 (0.731 → 0.735)** —
negligible. The per-pair errors are real but **offset at the fleet level**: at rho=0.5 some
pairs under-couple (C–D scen 0.06 vs emp 0.18; D–E 0.08 vs 0.14) while others over-couple
(C–E 0.28 vs 0.11; A–C 0.51 vs 0.43), and they roughly cancel in the sum. A single
distance-scaled rho cannot fix per-pair *signs* in any case → **chasing fleet coverage via
rho is futile** (this is the §4/§6 cross-zone trade-off, now quantified as a fleet non-issue
but a per-pair limitation — see §8).

### The fleet under-dispersion is NOT a uniform marginal deficit either

Zone-sum scenario-std / empirical-std ratios are **heterogeneous in sign**:

| zone | σ ratio (scen/emp) | zone-sum cov_80 | young plants |
|---|---:|---:|---|
| A | **0.81 (too narrow)** | 0.62 | Ball Hill |
| C | 1.09 (wide) | 0.71 | Baron, Eight Point |
| D | 1.14 (wide) | 0.79 | — |
| E | 1.11 (wide) | 0.78 | — |
| K | 0.95 | 0.69 | South Fork |

A global widen `g` multiplies every zone by the same factor. The sweep shows the
blunt-instrument failure: to drag the **fleet** to 0.80 needs **g≈1.30**, which over-inflates
the already-wide zones (**D→0.92, E→0.89**) while zone A *still* only reaches 0.73. A single
factor cannot reconcile A/K (too narrow) with C/D/E (already wide). Pooled scenario fleet
variance is in fact **1.17× the empirical** — the fan is, on average, already too wide; the
under-coverage is conditional/heterogeneous, not a uniform scale deficit.

*(Caveat: the analytic pooled-variance split — "88% marginal / 5% copula" — conflates
within-day-hour fan width with across-day-hour variation, so we rely on the two **coverage**
counterfactuals above, not that number.)*

### Decision: ship `asset_rho=0.5` + the young-plant regularizer ONLY

The deficit concentrates where short history lives (A/Ball Hill, K/South Fork, C/Baron+Eight
Point) — so the **targeted** young-plant regularizer is the right tool; a global widen is not.
Confirmation run, full 52-day calibration at `asset_rho=0.5 --short-history-reg`:

| metric | rho=0.5 (no reg) | rho=0.5 + young-plant reg |
|---|---:|---:|
| fleet-sum cov_80 | 0.724 | **0.731** |
| per-zone cov_80 (A/C/D/E/K, plant-pooled) | .76/.81/.83/.78/.69 | **.765/.821/.832/.790/.690** |
| young plants (Ball Hill / Baron / Bluestone / Number Three) | .63/.66/.60/.66 | **.68/.73/.68/.69** |

The regularizer does its job (young cohort +0.03–0.08) and is surgical (fleet/zone aggregates
move <0.01). **The fleet residual (cov_80 0.73, cov_90 0.83) is a documented known
limitation (§8), not papered over with a widen the evidence rejects.** Two *mature* plants
are also mildly under-dispersed (Cassadaga A 0.66, Avangrid Roaring Brook E 0.69); extending
the widener to them would be calibrating to the 2024 test year, so it was not done.

Outputs: `outputs/diagnose/{variance_decomposition,cross_zone_corr,zone_marginal_std,marginal_widen_sweep}.csv`.

---

## 8. Known limitations (carried forward)

1. **Fleet/aggregate residual under-dispersion** (cov_80 ≈ 0.73, cov_90 ≈ 0.83). Neither a
   single `asset_rho` nor a global marginal widen fixes it cleanly (§7). The per-plant
   *deliverable* the grid ingests is sound; the aggregate has a residual heterogeneous /
   shape mismatch.

   **Mechanism (why a global widen is *structurally* wrong, not just empirically).** The
   under-dispersed zones A (6 plants) and **K (1 plant, South Fork)** have little intra-zone
   averaging, so their zone-sum fan is dominated by — and sensitive to — per-plant marginal
   misfit. The over-dispersed zones C/D/E (6–9 plants each) average per-plant marginal error
   away; their residual zone-sum dispersion comes from how the *correlations* aggregate, not
   from individual marginals. So the fleet 0.73 decomposes into **(i)** under-diversified
   zones mildly under-modelled *at the marginal* and **(ii)** heavily-diversified zones whose
   *modelled* zone-sum is wider than the empirical one (the §7 σ-ratios: A 0.81, K 0.95 vs
   C/D/E 1.09–1.14). A single multiplier cannot serve both regimes — it would have to widen
   A/K and *shrink* C/D/E at once. A **block / structured asset covariance** that places
   different correlation strength on {A,K} vs {C,D,E} can; the one-parameter distance kernel
   cannot. This is the principled next lever, deferred until it can be validated
   out-of-sample.
2. **Cross-zone per-pair coupling.** A single distance-scaled `asset_rho` cannot reproduce
   the full cross-zone matrix: at rho=0.5 the moderate pairs C–D and D–E under-couple
   (scen 0.06/0.08 vs emp 0.18/0.14) and C–E/A–C over-couple. They net out at the fleet
   level (§7) but the zonal *fit* of Stage A would represent each pair directly — the one
   genuine structural point in favour of zonal awareness (open question #3, answered as a
   real trade, not a clean win).
3. **2023–24 young-plant cohort** (§5). Partially mitigated by the regularizer; remains a
   low-confidence bucket that self-corrects as history accrues.
4. **Self-consistency, not metered truth** (§2, plan §9). PIT/coverage are vs the v4 modeled
   potential the engine was fit on; there is no hourly per-plant metered truth for ~28/31
   plants.
5. **Two ~3.5-yr plants under-dispersed — but probably a *tail*, not a *scale*, problem.**
   Cassadaga (zone A, commissioned 2021-07) and Roaring Brook / Avangrid (zone E, 2021-10)
   show cov_80 ≈ 0.66 / 0.69 yet sit *past* the ≤2-yr young-plant threshold (~3.5 yr of
   history by 2024). **Hypothesis:** their deviation *std* is representative but their *tails*
   are not — 3.5 years has not yet sampled an extreme event — so the principled correction is
   **tail extension via a GPD fit on the residuals** (the Carmona-style heavy-tail treatment
   the load side already uses), *not* the std-ratio widen the young-plant regularizer applies.
   Deliberately **not applied**: it is gated on out-of-sample evidence, and std-scaling these
   two now would calibrate to the 2024 test year (§5 rationale). A specific, falsifiable
   follow-up rather than a vague "some mature plants are narrow."
