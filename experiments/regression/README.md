# Regression Test Suite — NYISO Pipeline

This test suite catches the **six bug classes** encountered during the
development of the NYISO stochastic unit commitment pipeline. Each test
is designed to detect a specific failure mode in isolation, before it
propagates into multi-day ensemble results.

## Quick start

```bash
# Fast tests only (data-level checks, ~2 minutes):
cd /path/to/Princeton
conda activate vatic-test
pytest experiments/regression/ -m "not slow" -v

# Full suite including Vatic simulation tests (~30–60 minutes):
pytest experiments/regression/ -v

# Single test:
pytest experiments/regression/test_scenario_compression.py -v
```

## Prerequisites

- **conda environment**: `vatic-test` with PGscen-2nd, Vatic, and CBC solver
- **PGscen data**: `PGscen-2nd/data/NYISO/` (standard) and
  `PGscen-2nd/data/NYISO_real/` (HRRR-derived)
- **Pre-generated scenarios** (optional, for tests using archived outputs):
  `experiments/001_stochastic_vs_deterministic_jul2019/results/scenarios/`

---

## Test inventory

### Test 1: Scenario compression (`test_scenario_compression.py`)

**Bug class**: Scalar compression of wind scenarios.

**What happened**: An early version of the scenario generation pipeline
applied a single system-level scaling factor to all wind plants instead of
per-site trajectories. All plants moved in lockstep — destroying the spatial
correlation structure that drives localized congestion and unit commitment
variation.

**What the test checks**:
- For any two PGscen wind scenarios, per-plant Pearson correlation must have
  max < 0.95 (not scalar copies).
- At least 3 of the 5 most-correlated plants must have |r| < 0.7 (real
  spatial diversity).
- Within a single scenario, no two plants should be perfectly correlated
  (r > 0.99).

**Data tests**: Pre-generated parquets + freshly generated scenarios.

---

### Test 2: Timezone alignment (`test_timezone_alignment.py`)

**Bug class**: HRRR timezone mismatch.

**What happened**: PGscen's HRRR-derived wind data uses UTC timestamps, but
the original PGscen standard data used an implicit 06:00 UTC convention
(EST day boundary). When the scenario-application code didn't align
timezones, wind and load perturbations landed on wrong hours — shifting
peaks by 5–6 hours and producing nonsensical price patterns.

**What the test checks**:
- NyisoLoader gen_data/load_data indexes are UTC.
- PGscen wind/load actuals indexes are UTC.
- After applying a scenario via `_apply_scenario_to_timeseries`, load
  changes by 0.1%–50% (nonzero but plausible).
- After applying a scenario, at least 5 wind generators change values.

**Data tests**: NyisoLoader baseline + pre-generated scenarios + experiment
001's scenario application function.

---

### Test 3: Cold-start / warmup (`test_coldstart_warmup.py`)

**Bug class**: Cold-start contamination.

**What happened**: The first day of each simulation started with all
generators offline. The solver had to commit the entire fleet from cold,
producing massive load shedding and startup costs in the first hours. When
this day was also the analysis day (no warmup), the results were dominated
by the startup transient rather than actual market conditions.

**What the test checks**:
- Run Vatic for July 18 cold (no warmup) — record load shedding.
- Run July 17 (warmup) → July 18 (target) with chained conditions.
- Target-day shedding with warmup must be < 10% of cold-start shedding.

**Requires**: Vatic simulation (marked `@pytest.mark.slow`).

---

### Test 4: Multi-day RUC consistency (`test_multiday_ruc.py`)

**Bug class**: Deterministic day-by-day UC without condition chaining.

**What happened**: Each day was simulated independently, losing generator
state at day boundaries. This caused unnecessary cold starts every day,
inflating costs and masking the real commitment dynamics. A single multi-day
simulation doesn't have this boundary artifact.

**What the test checks**:
- Run Vatic as a single 3-day simulation (multi-day).
- Run Vatic as 3 separate 1-day simulations with chained initial conditions
  (day-by-day).
- Total costs must be within 2% of each other.

**Requires**: Vatic simulation (marked `@pytest.mark.slow`).

---

### Test 5: Load scenario diversity (`test_load_diversity.py`)

**Bug class**: Load scenarios never applied.

**What happened**: A bug in the scenario application code caused the load
baseline to pass through unchanged to every stochastic scenario. All 100
runs used identical demand — the "stochastic" ensemble had zero demand
uncertainty. The cost-of-uncertainty number was entirely driven by
wind/solar variation, missing the dominant source of forecast error.

**What the test checks**:
- For 10 pre-generated load scenarios, per-zone coefficient of variation
  (CV) at peak hour must be >= 0.3% for all 11 NYISO zones.
- Freshly generated load scenarios also pass the CV threshold.
- No two load scenarios are bitwise identical.

**Data tests**: Pre-generated parquets + freshly generated scenarios.

---

### Test 6: Per-plant wind variance (`test_wind_variance.py`)

**Bug class**: Wind scenario suppression at plant level.

**What happened**: Even after fixing system-level scalar compression, some
plants could still have degenerate variance — for example, if a site-to-
generator mapping error sent the same HRRR data to multiple plants, or if
clipping/rounding eliminated small differences. The result: plant-level
dispatch was driven by noise-free profiles.

**What the test checks**:
- For 10 wind scenarios, each plant's mean daily output must vary with
  (max − min) / nameplate >= 5% across scenarios, for at least 80% of
  plants.
- Hour-by-hour system wind CV must exceed 1% for at least half the hours
  in a day.

**Data tests**: Pre-generated parquets + freshly generated scenarios.

---

## Test markers

| Marker | Meaning | Typical runtime |
|--------|---------|-----------------|
| *(none)* | Data-only test, no Vatic simulation | 10–60 seconds |
| `@pytest.mark.slow` | Requires Vatic UC+ED simulation | 5–20 minutes |

Use `pytest -m "not slow"` to skip simulation tests during development.

## When to run

- **Before any ensemble run**: Run the full suite to catch regressions.
- **After modifying PGscen code**: Run tests 1, 5, 6 (scenario quality).
- **After modifying NyisoLoader**: Run test 2 (timezone) + tests 3, 4
  (simulation consistency).
- **After modifying scenario application** (`_apply_scenario_to_timeseries`):
  Run tests 2, 5 (application correctness).

---

## Mutation tests (`test_mutations.py`)

Each regression test claims to catch a specific bug class. The mutation tests
prove those claims by injecting deliberately-broken data and confirming the
assertion fires. There are 8 mutation tests covering the 4 fast bug classes:

| Bug class | Mutation | What's injected |
|-----------|----------|-----------------|
| Compression (test 1) | `test_scalar_compressed_scenarios_detected` | All plants share the same temporal profile × per-plant scalar |
| Compression (test 1) | `test_lockstep_within_scenario_detected` | Within-scenario pairwise r = 1.0 |
| Timezone (test 2) | `test_no_load_change_detected` | load_mod == load_orig (zero change) |
| Timezone (test 2) | `test_massive_load_change_detected` | load_mod = load_orig × 3.0 (200% change) |
| Load diversity (test 5) | `test_zero_cv_detected` | 10 identical load scenario copies |
| Load diversity (test 5) | `test_identical_pairs_detected` | Same 10 identical copies |
| Wind variance (test 6) | `test_zero_spread_detected` | 20/23 plants have zero cross-scenario spread |
| Wind variance (test 6) | `test_zero_hourly_cv_detected` | System-wind totals are identical across scenarios |

**Why tests 3 and 4 have no mutations**: The cold-start and multi-day RUC
tests require running actual Vatic simulations. Constructing broken inputs
that simulate cold-start contamination or unchained day boundaries would
require ~20 minutes of solver time per mutation — too expensive for a test
that only confirms "assert ratio < 0.10 catches ratio > 0.10." The assertion
logic for those tests is simple threshold comparisons, not complex data
processing, so the risk of a false pass is low.

---

## Known gaps — what this suite does NOT cover

The regression suite targets the 6 bug classes we actually hit. There are
important failure modes it cannot detect:

### 1. Solar scenario bugs

Only wind scenarios are tested for compression and spatial variance. Solar
in the 2019 NYISO model has only 2 generators totaling ~4 MW — not enough
sites to meaningfully test spatial correlation or per-plant spread. Solar
scenarios are applied as a system-level ratio, which is appropriate for the
current 2-generator model but would need per-plant tests if NYISO's solar
fleet grows (it will, especially post-2023 with distributed solar).

### 2. Bus-to-zone mapping errors

The NyisoLoader distributes zonal load to individual buses using the
RenewableGen.csv load-proportion table. If a zone's buses are mapped
incorrectly (e.g., a Zone J bus assigned to Zone K), load scenarios would
be applied to the wrong buses — correct at the zone level but wrong at the
bus level. This would only show up as incorrect locational prices, not as
any aggregate metric we test. Detecting it requires comparing bus-level
LMPs to NYISO nodal price data, which is a Phase 2/6 validation task.

### 3. Cost curve unit errors (heat rate vs. $/MWh)

The NyisoLoader converts NYgrid heat rate curves (MMBTU/MWh) to cost
curves ($/MWh) using fuel prices. If fuel prices are in the wrong units
(e.g., $/MMBTU vs. $/gallon) or the heat rate interpretation flips
(MMBTU/h vs. MMBTU/MWh), the resulting cost curves would be off by an
order of magnitude. This would manifest as wildly wrong LMPs but would
not be caught by scenario-level tests. It requires comparison to NYISO
published LMPs (Phase 2 cross-year validation).

### 4. Storage SOC constraint violations

Pumped storage (Blenheim-Gilboa, Lewiston) and future BESS units must
respect state-of-charge bounds. If SOC tracking is broken (e.g., charging
but not decrementing), the solver may dispatch storage as free energy.
No test currently verifies SOC trajectory continuity. Phase 4 (BESS
integration) will add these tests.

### 5. Reserve requirement miscalibration

The reserve_factor=0.05 parameter sets spinning reserve at 5% of
forecasted load. NYISO's actual 2019 operating reserve requirement is
~2,620 MW (10-minute reserves) — a fixed MW target, not a load fraction.
The 5% rule overestimates reserves at low load and underestimates at peak.
Phase 3 (reserve audit) will diagnose and calibrate this.

### 6. Kron reduction fidelity

The 46-bus Kron-reduced network is an electrical equivalent of the full
140-bus NPCC model. If the reduction introduces impedance errors, branch
flow limits will be wrong — congestion will appear on the wrong interfaces.
Validating this requires comparing Kron-reduced PTDF flows to full-network
flows on the same dispatch, which is a one-time verification task, not a
regression test.

### 7. External equivalent calibration drift

The 4 external equivalents (PJM, HQ, NE, IESO) use 2019 p95 flow limits
and average LMPs. For other years, these limits change (e.g., HQ imports
increased in 2022–2023 due to new HVDC capacity). No test checks whether
the external equivalent parameters are appropriate for the simulation year.
Phase 5 (NYCA flow definition) will document the calibration sources.

### 8. PGscen model convergence failures

PGscen's RegimeGeminiEngine uses EM-based fitting that can silently fail
to converge (the `RuntimeWarning: invalid value encountered in scalar
divide` visible in test output). If the model doesn't converge, scenarios
may collapse to the forecast mean. The current tests catch the symptom
(zero variance) but not the root cause (convergence failure). A dedicated
test would check the engine's log-likelihood convergence flag.

### 9. Fuel price staleness

For years other than 2019, fuel prices come from EIA API lookups cached
locally. If the cache is stale or the API call fails, the loader silently
falls back to 2019 prices. No test verifies that fuel prices match the
simulation year. This matters most for natural gas, which varied from
$1.63/MMBTU (2020) to $6.45/MMBTU (2022).
