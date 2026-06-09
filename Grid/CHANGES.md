# Grid (ex-Pourval) — Changes applied 2026-05-26

Working through `OPEN_ISSUES.md` in priority order. Summary: every item that
was tractable from the in-repo data is done. Three items remain blocked on
external data (NYISO TARS branch ratings, EIA-860 per-unit PMin, chained
warmup SCED for `init_state`). Two large items (`pourval_loader.py`, NYISO
interface constraints) remain as future work.

---

## What changed

### P0.1 — Branch ratings (DONE, via 7-year binding-constraint matching)
The friend supplied `binding_constraints_7y.csv` (315k rows, 2019–2025,
245 unique limiting facilities) plus the procedure in `ajoutmalin.md`.
Implementation:

1. `match_flowgates.py` parses every flowgate with ≥200 binding hours,
   maps NYISO substation abbreviations to local Bus IDs, and classifies
   each as `matched` (existing branch), `missing_branch` (both buses
   exist, branch is absent), `interface_constraint`, `unmatched_name`,
   or `unparsable`.
2. `calibrate_branches.py` applies the resulting decisions. It backs up
   `branch.csv` first, then writes new ratings on existing branches and
   appends new rows for missing ones. R/X for new branches come from
   haversine distance × typical per-km impedance at the line voltage.

**Calibrations applied** (6 branches — last two bumped after P2.4 closure
revealed they bound hard under correct load):

| UID                | Old        | New (MVA) | Flowgate                       |
|--------------------|-----------:|----------:|--------------------------------|
| L58_426            | 999,999    | 1,200     | Cricket Valley ↔ Pleasant Valley 345 kV (3,646h) |
| OSM_J_345_0004     | 999,999    | 900       | Goethals ↔ Gowanus 345 kV (2,914h) |
| OSM_J_345_0003     | 999,999    | 900       | Farragut ↔ Gowanus 345 kV (525+469h) |
| L316_320           | 999,999    | 700       | Packard ↔ Sawyer 230 kV (429h) |
| OSM_K_138_0026     | 999,999    | **900**   | Oakwood ↔ Syosset 138 kV (LI double-ckt; was 600, bumped after binding 24/24 hours) |
| L399_400           | 630        | **1,000** | Station_122 ↔ Clay_Station 345 kV (atypically low source rating; was 105 % overloaded) |

Explicitly **NOT** calibrated (friend's warning, would collapse Zone D):
- `L224_227` (Scriba ↔ Volney 345 kV, 3,769h binding) — left at 999,999.

**Branches added** (7 missing, with R/X computed from lat/lon distance):

| UID prefix                     | From → To          | kV  | km | MVA |
|--------------------------------|--------------------|-----|----|----:|
| NYISO_E179_HELLGATE_138        | E. 179th ↔ HellGate | 138 | 6  | 450 |
| NYISO_GREENWD_VERNON_138       | Greenwood ↔ Vernon | 138 | 12 | 450 |
| NYISO_MOTTHAVN_DUNW_345_×2     | Mott Haven ↔ Dunwoodie | 345 | 15 | 1,200 ea |
| NYISO_MOTTHAVN_RAINEY_345_×2   | Mott Haven ↔ Rainey | 345 | 6  | 1,200 ea |
| NYISO_PLSNTVLY_LEEDS_345       | Pleasant Vly ↔ Leeds | 345 | 58 | 1,200 |

**Not addressed** (require structural bus splits, out of scope):
- 138 kV flowgates on substations our model only carries at 345 kV
  (Astoria, Rainey, Mott Haven, Fresh Kills, East Garden City) — the
  friend's notes mention this for Astoria specifically.
- 7 zone-level interface flowgates (CENTRAL EAST – VC, SCH-NE-NY,
  SCH-PJ-NY, etc.) — these need `template['Interfaces']` entries,
  which is part of P2.2 (`pourval_loader.py` work, still pending).
- ~92 substations not in our bus.csv at all (Adirondack, Pulaski,
  Northport, Pilgrim, Glenwood, Lake Success, …) — data gap.

**Result**: bus LMPs went from $-31 to $2,264 range (h18, std $741) to a
clean upstate-to-downstate gradient:

```
Hour  A    B    C    D    E    F    G    J     K
00   $0   $0   $0   $0  $12  $13  $-0  $61   $57
10  $23  $23  $23  $21  $80  $68  $54  $61   $57
15  $24  $24  $24  $24  $41  $40  $28  $62   $58
18  $62  $62  $62  $62  $62  $62  $62  $62   $58 (peak)
22  $24  $24  $24  $24  $41  $40  $28  $61   $57
```

Zone K shows internal $50–63 spread (LI congestion); J/K maintain ~$5
premium over upstate even at peak. **No severely-overloaded branches**
(>=1.5x). 63 line-hours bind at >=99 % — these are real binding
constraints now, not arbitrary shadow prices.

### P0.2 — DC tie pinning (DONE)
Replaced the keyword-search-with-silent-fallback in `DC_TIES` with explicit
`Bus ID` pins:

| Tie                              | Bus ID | Where                                |
|----------------------------------|--------|--------------------------------------|
| HQ (Chateauguay + Phase II)      | 335    | Massena 765 kV, Zone D               |
| Ontario                          | 390    | Robert Moses 345 kV, Zone A          |
| PJM Ramapo                       | 410    | Ramapo 500 kV, Zone G                |
| PJM Linden VFT                   | 10104  | Goethals 345 kV, Zone J              |
| ISO-NE Cross Sound Cable         | 10153  | Shoreham, Zone K                     |

Chateauguay (1000 MW) and Massena (200 MW) collapsed into one 1200 MW HQ
import at Massena, since both HQ interconnects converge there on the NY
side. Bus ID is used directly (not Bus Name) because of the duplicate
Goethals issue below.

A missing target now raises `RuntimeError` instead of falling back.

### P0.3 — NaN Zone J buses (DONE, partial)
Four buses (Newtown, Goethals 10197, Willowbrook, Woodrow) ship with NaN
`Area`/`Sub Area`/`is_split`. Script now:

- Fills `Area`/`Sub Area` from zone letter (A→1 … K→9), logging which
  buses were patched
- `is_split` mask now includes the `"nan"` string variant (the original
  `["false", "0", "false"]` typo excluded NaN buses from load eligibility)
- Bus Name collisions (Goethals 10104/10197, East_36th_Street 10121/10206)
  now get `__bus<ID>` suffix so Vatic's name-dedupe doesn't collapse load

The underlying data should be reconciled with the grid maintainer — the
NaN rows are likely placeholders for draft / CEII-not-public topology.

### P0.4 — Real hourly load (DONE)
Wrote `fetch_nyiso_load.py` (the helper the README referenced but didn't
ship). Fetches from `http://mis.nyiso.com/public/csv/palIntegrated/` and
writes a 24-row CSV with columns `Zone_A…Zone_K`. Test fetch of
2025-07-20 succeeded: peak 25,277 MW at hour 18, daily mean 21,164 MW.

Also fixed `run_sced.py`'s consumption of this CSV to sum Zone_H + Zone_I
into Zone G (because the script's `ZONE_LOAD_MW` keeps the H/I-into-G
merge per README convention) — the old code only read Zone_G and dropped
H/I entirely.

Usage:
```bash
python fetch_nyiso_load.py --date 2025-07-20
HOURLY_LOAD_CSV=grid_data/hourly_load_20250720.csv python run_sced.py
```

### P1.1 — PMin per-unit (DONE, full)
The `gen.csv` `Output_pct_1` column carries the real per-unit elbow /
part-load fraction — 16 distinct values for Gas (0.10 peaker, 0.15 small
CT, 0.30 mid, 0.40 CC), 3 for Oil, 0.90 Nuclear, 0.30 Biomass. The
script now uses `Output_pct_1 × PMax` as PMin, falling back to a flat
30 %/95 % only when `Output_pct_1` is 0 / NaN. All 284 Gas units now
have realistic per-unit PMin — verified `PMin/PMax == Output_pct_1` for
every unit.

### P1.2 — init_state via chained warmup SCED (DONE)
The shipped `init_state.csv` has every gen flagged ±1000h (no recent
transition, max UC flexibility). With that as init, the optimizer has
to figure out the entire commitment pattern at hour 0, paying ~$750k
in fixed startup costs and doing ~28 unit on/offs in the first hour
just to settle.

A real chained run uses the previous day's end-of-day state. Two
plumbing pieces added:

1. `run_sced.py` accepts two new env vars:
   - `INIT_STATE_OVERRIDE` → path to alternate init_state.csv. Merged
     with the shipped renewables (since `init_state.csv` doubles as
     the generator roster in `GridLoader.__init__` — gens absent from
     it get dropped from the template).
   - `LAST_CONDITIONS_FILE` → path where this run writes its
     end-of-day state for chaining.
2. `run_with_warmup.py` orchestrates a two-day chain:
   - Fetches NYISO hourly load for both days (cached)
   - Runs warmup SCED for day-1 → writes `last_conditions_<date>.csv`
   - Runs target SCED with that file as `INIT_STATE_OVERRIDE`

The merge logic is the subtle bit: Vatic's stats_manager writes
only thermal gens to `last_conditions_file`, and the loader's
`first_states` read drops any gen missing from the file. So we
**merge** warmup thermal states with the original renewable rows
into `RES_DIR/init_state_merged.csv` and point the loader there.

**Result** (2025-07-20 target, 2025-07-19 warmup):

| Metric              | partial_fixes | chained  | Δ    |
|---------------------|---------------|----------|------|
| Hour 0 FixedCosts   | $751,482      | $268,275 | −65 %|
| Hour 0 on/offs      | 28            | 9        | −68 %|
| Hour 0 ramp MW      | 1,563         | 313      | −80 %|
| Day-total cost      | $14.7 M       | $13.4 M  | −9 % |

Hour 0 is now a smooth handoff from day-before commitments instead
of a cold-start scramble. LMP behaviour from hours 15-21 still
shows the L399_400 / OSM_K_138_0026 binding (P0.1 leftover) —
chained init can't relax binding transmission constraints.

Usage:
```bash
python run_with_warmup.py --date 2025-07-20 --tag chained
# Or, to reuse a cached warmup conditions file:
python run_with_warmup.py --date 2025-07-20 --tag chained --skip-warmup-if-cached
```

### P1.3 — Cost curves with no-load fixed cost (DONE, data-limited)
`parse_generator` now reads the `Fixed Cost($/hr)` column (previously
ignored) and builds the cost curve as `fixed + mc × p` on `[PMin, PMax]`.

Verified the input is genuinely linear, not piecewise: `HR_avg_0 == 0`
and `HR_incr_1 == HR_incr_2` for **every** of 1,504 rows. The "3-segment"
structure in `gen.csv` carries the elbow (`Output_pct_1`, now used for
PMin per P1.1) but no piecewise heat-rate values. Real piecewise heat
rates would have to come from EIA-860 — there is nothing more to extract
from the in-repo data.

Before: cost = mc × p, starting at (0, 0). After: cost = fixed + mc × p,
starting at (PMin, fixed + mc·PMin).

### P1.5 — Pumped hydro vs BESS split (DONE)
Storage aggregation now splits by `_stor_type` column (already present in
`storage.csv` with values `battery` / `pumped_hydro`). Result for
2025-07-20 smoke run:

```
Source: 44 battery + 15 pumped_hydro units
6 BESS units (one per zone with batteries):
   BESS_A 20MW/42MWh   BESS_B 20/20    BESS_C 52/198
   BESS_D 43/93        BESS_E 25/28    BESS_G 48/114
2 PH units:
   PH_E  1165MW/9321MWh @ Gilboa_Substation  (Blenheim-Gilboa)
   PH_A   220MW/1760MWh @ Robert_Moses_Substation (Lewiston)
```

Pumped hydro uses its own efficiency (~0.89 from data, vs 0.96 lithium)
and gets a 10 % min-SOC floor.

### P1.6 — J/K storage gap (DONE — diagnostic only)
`storage.csv` has zero entries in Zone J and Zone K. The real NYISO
fleet has BESS in both (Ravenswood, BQDM, LI Grid Storage). Script now
prints a `WARNING: Zone J/K has zero storage units` so the gap is
visible. Closing it requires updated data, not code.

### P2/P3 cleanups (DONE selectively)

- **P2.3** — dropped buses + branches now write to
  `results_<tag>/dropped_topology.csv` and `dropped_branches.csv`.
- **P3.2** — `is_split` mask typo fixed (now correctly includes NaN-mark
  buses as eligible loads).
- **P3.6** — vatic import error message now says set `PYTHONPATH`, not
  `pip install vatic` (the package is a local repo, not on PyPI).

### P2.1 + P2.2 — PourvalLoader + interface constraints (DONE)
`Vatic/vatic/data/pourval_loader.py` (~620 lines) exposes the exact
public surface of `NyisoLoader` so the existing `experiments/`
directory can swap loaders with a one-line import change. Built on the
same `GridLoader` base class.

**Contract verified** (with `from vatic.data.pourval_loader import
PourvalLoader as NyisoLoader` standing in for the existing class):

| Required by experiments      | PourvalLoader |
|------------------------------|---------------|
| `loader.template` (38 keys)  | ✓             |
| `loader.buses[i].ID/.Name`   | ✓             |
| `loader._pgscen_site_map`    | ✓ (25 PGscen sites mapped for 2019) |
| `loader.template['Buses']`   | ✓ (754 names) |
| `loader.template['Interfaces']` | ✓ (7 NYISO flowgates wired) |
| `create_timeseries(s, e)`    | ✓ MultiIndex `(actl|fcst, asset)` |
| Constructor: `init_state_file`, `use_reduced_network`, `fuel_price_date`, `pgscen_dir`, `year` | ✓ (use_reduced_network accepted+ignored — no Kron variant) |

**What's inside**:
- CSV loading + parse from `Grid/grid_data/sced_inputs/SourceData/`
  (no source mutation — closes P2.5 for the loader path)
- Bus normalisation: NaN Area/Sub Area fillna from zone letter,
  duplicate Bus Name uniquification (Goethals 10104/10197, etc.)
- Load distribution: EIA-861 county weights with BaseKV^0.5 fallback,
  hardcoded `ZONE_LOAD_MW` Gold Book peak totals
- DC tie injections (5 ties, Bus ID-pinned, applied as constants in
  `create_timeseries` — same fix as P2.4)
- Disconnected-component pruning (drops isolated buses + their gens)
- Per-unit PMin from `Output_pct_1` (P1.1)
- Linear cost curves with `Fixed Cost($/hr)` no-load (P1.3)
- Storage split by `_stor_type`: 6 BESS + 2 pumped-hydro units (P1.5),
  initial SOC clipped to [0.01, 0.99]
- 7 named NYISO interface constraints (DYSINGER_EAST, WEST_CENTRAL,
  TOTAL_EAST, MOSES_SOUTH, CENTRAL_EAST, UPNY_CONED, SPR_DUN_SOUTH)
  with 2019 declared limits, built by walking zone-crossing branches
- Path B import costs from cached NYISO DA LMP data (`data/nyiso_cache/
  {year}/da_lbmp/`) — verified producing year-specific values for
  2019: HQ=$13/MWh, NE=$20, PJM=$20, IESO=$24
- PGscen wind/solar site → bus mapping by **nearest lat/lon in same
  zone** (finer than NyisoLoader's zone-centroid approach)
- `create_timeseries` with two paths:
  - PGscen actuals + day-ahead forecasts for wind/solar, zonal load
    distributed to buses by share, plus constant DC tie injection
  - Fallback to flat default CFs when no `pgscen_dir` given

**End-to-end test**: ran a full Vatic `Simulator` for 2019-07-08 with
PourvalLoader → completed in 75 s, no errors. Drop-in works.

**How to migrate an experiment**:
```python
# Before:
from vatic.data.nyiso_loader import NyisoLoader

# After (one-line change — all kwargs are accepted):
from vatic.data.pourval_loader import PourvalLoader as NyisoLoader
```

### Experiments — runtime loader switch (DONE)

Migrated 5 of 5 main experiment runners. Each accepts a `LOADER`
environment variable (or `vatic.loader` config key) selecting
``nyiso`` (default, backward-compatible) or ``pourval``:

- `experiments/001_stochastic_vs_deterministic_jul2019/run.py`
- `experiments/002_v2_baseline/run.py` (config.yaml gets a `loader:` key)
- `experiments/cross_year_validation/run.py`
- `experiments/path_b_validation/run.py`
- `experiments/bess_test/run.py` (Test 2 skips under pourval — uses NyisoLoader-private `_PUMPED_STORAGE` dict by design)

Two PourvalLoader fixes surfaced during the 002 pilot:

1. **Wind file naming**: PGscen-2nd's 2019+ wind CSVs carry a
   `.pluswind_v3` suffix (the wind-model paper variant). Added
   `_find_pgscen_renew_csv` helper that accepts both naming variants.

2. **Site-map injectivity**: PourvalLoader was mapping multiple PGscen
   sites to the same gen ID (25 sites → 11 unique gens), which created
   duplicate gen_data columns that crashed Vatic's data_provider.
   Switched to "nearest **unused** gen of matching fuel in same zone"
   with a cross-zone fallback. Now 25/25 sites get unique gens.

**End-to-end pilot**: `experiments/002_v2_baseline` deterministic step
on 2019-07-17 → 2019-07-18 with `LOADER=pourval`. Both days completed
successfully. Day 2019-07-18: **78.8 s, total cost $16.6 M, zero load
shedding**. Transmission infeasibility warnings (L399_400 /
OSM_K_138_0026 still tight under July 2019 loading) match prior runs.

The 4 NyisoLoader-specific regression tests under
`experiments/regression/` are **intentionally** not migrated — they
exist to validate NyisoLoader behaviour and have nothing to test
against PourvalLoader. One throwaway script `bess_test/
check_cycling_2022.py` also still hardcodes NyisoLoader.

Default remains `LOADER=nyiso` to preserve v29-validated results.
Opt-in to the new grid via:
```bash
LOADER=pourval python experiments/002_v2_baseline/run.py --smoke
```

### Inner-congestion proxies for NYC 138 kV flowgates (ATTEMPTED, REVERTED)

**Problem.** NYISO's 7-year binding-constraint data references 90,355
binding-hours of 138 kV flowgates at Astoria, Fresh Kills, East Garden
City, Rainey, Mott Haven, Shore Road, and Gowanus — every one of these
substations exists in `bus.csv` only at 345 kV. The 138 kV side is real
(Manhattan/LI ConEd distribution layer) but isn't modelled. Bus splits
are the proper fix; they require ConEd CEII data we don't have access
to (`ajoutmalin.md` flags this as deferred structural work).

**Attempted synthetic fix.** Added `J_INNER` and `K_INNER` interface
constraints to `pourval_loader.py:_INTERFACE_DEFS`, using existing
zone-crossing branches `(F,J)+(G,J)` and `(G,K)+(J,K)`. The intent:
cap net imports into J and K at values tighter than the published
UPNY_CONED/SPR_DUN_SOUTH limits, so the optimizer is forced to commit
in-city peakers — proxying for the aggregate "138 kV cables saturate
before 345 kV interfaces do" effect.

**Why it didn't work.** Two failure modes, both observed empirically:

1. **Loose limits never bind.** Observed natural flow on the (F,J)+(G,J)
   crossings during 2019-07-18 was 1,200-2,900 MW — well below the
   UPNY_CONED limit (5,700 MW). Setting J_INNER ≥ 2,900 produced bit-
   for-bit identical results to the BASE run. Similarly K's net flow
   was -1,040 to +170 MW (K mostly *exports* to G/J), so K_INNER at any
   reasonable limit didn't bind either.

2. **Tight limits create PTDF artifacts.** Setting J_INNER = 2,500
   and K_INNER = [-800, +800] DID make the constraints bind, but PTDF
   amplification on a 754-bus network without 138 kV bus topology drove
   shadow prices to **$4,000-$8,000/MWh across all downstate zones** at
   peak hours, dwarfing the intended J vs K differentiation. The PTDF
   factors for a "ghost" inner constraint applied to 345 kV branches
   don't match the physical 138 kV cable PTDF, so the shadow price
   propagates wildly through the network.

**Conclusion.** Synthetic 345 kV interface constraints fundamentally
cannot proxy for 138 kV intra-zone congestion in this topology. The
two layers operate on different physical paths with different PTDF
distributions, and trying to bridge them with an interface constraint
creates either no effect or wild side effects.

**Reverted.** `_INTERFACE_DEFS` no longer contains `J_INNER` or
`K_INNER`. The 7 published NYISO interfaces remain. Zone J = Zone K
LMPs at peak are accepted as a known limitation of the 754-bus
topology, to be resolved when bus splits land (no near-term plan).

**One useful side effect, kept**: while investigating, we found that
`L316_320` (Packard ↔ Sawyer 230 kV in Zone A) was 102 % loaded under
2019 July loads at its previous 700 MVA rating, producing a $1,800
LMP spike in Zone A via PTDF. Bumped to 850 MVA in
`calibrate_branches.py` — this **does** improve results and is
unrelated to the synthetic-constraint failure.

### Not addressed yet

- **P2.4** — DONE. Root cause: DC tie injections were folded into
  `bus.csv["MW Load"]` in Step 2 and then *scaled* by `hourly/peak` in
  `create_timeseries` — so a 1,200 MW constant HQ import became
  ~700 MW at off-peak D-zone hours. Fix: keep ties out of bus.csv and
  apply them as constant per-hour offsets after the load scaling.
  Step 4 now logs `expected_peak vs actual_peak` — gap is 0 MW. (Side
  effect: closing the gap exposes a real overload on the friend's
  pre-rated L399_400 / OSM_K_138_0026 lines under correct loading;
  noted below.) Also added a Vatic `apply_sced` monkey-patch that
  clips storage SOC to [0,1] — `PercentFraction` tripped on
  `1.0000001` FP overshoot for short-duration BESS without it.
- ~~**P2.5** — `run_sced.py` still mutates `SourceData/*.csv` files~~ —
  **fixed**: per-run `WORK_DIR` keeps SourceData read-only (see above).
- **P3.5** — results dir still gets clobbered on tag reuse.

---

## Before vs after (2025-07-20)

Identical date, identical config except for the fixes above. Numbers
from `grid_data/sced_inputs/results_smoke/hourly_summary.csv` (before)
and `results_p0_p1_fixes/hourly_summary.csv` (after).

| Metric                          | Before (flat CFs, no fixes) | After P0–P1   | After P0.1 calibration |
|---------------------------------|----------------------------:|--------------:|-----------------------:|
| Demand range across 24 hours    | flat 28,143 MW              | 15.6–23.4 GW  | 15.6–23.4 GW           |
| System price range              | $45–$69 (flat after h7)     | $26–$57       | $25–$55                |
| Bus LMP range (hour 18)         | $0.83–$4,217                | $-31–$2,264   | **$50–$63**            |
| Bus LMP std (hour 18)           | $1,711                      | $741          | **$1.51**              |
| Severely overloaded branches    | 4 (up to 213%)              | 4 (same)      | **0**                  |
| Line-hours binding ≥99 %        | 4                           | 4             | 63 (real constraints)  |
| "Transmission infeasible" warns | yes (every hour)            | yes (peak)    | **no**                 |
| Reserve shortfall hours         | 15 of 24                    | 0 of 24       | 0 of 24                |
| Renewables curtailment hours    | 7                           | 5             | 13                     |
| Number of storage units         | 6 BESS lump                 | 6 BESS + 2 PH | 6 BESS + 2 PH          |
| DC ties correctly placed        | 4 of 6                      | 5 of 5        | 5 of 5                 |
| Total cost                      | $32.3 M                     | $17.0 M       | $14.7 M                |

Demand ramps from 15.6 GW overnight to 23.4 GW peak. LMPs across all 24
hours show the expected upstate→downstate gradient — Zone A overnight
at $0–7/MWh (renewables + nuclear set the price), midstate (E–F) at
$30–80, and J/K maintaining a $5/MWh premium with internal Long Island
congestion visible as Zone K dispersion.

---

### P2.5 — SourceData is now read-only (DONE 2026-05-27)

Previously, `run_sced.py` mutated `Grid/grid_data/sced_inputs/SourceData/`
between Steps 1-3 (branch ratings scaled, bus.csv rewritten with load
distribution + tie-injected loads + Area fillna + uniquified names,
gen.csv rewritten with populated PMin, init_state.csv filtered to surviving
gens). Re-running with different env vars therefore permanently modified
the source data.

The fix is a per-run working directory:

- `SRC_DIR` now points to the canonical read-only source location
  (`Grid/grid_data/sced_inputs/SourceData` for local, `DATA/sced_inputs/
  SourceData` under `$DARTBOARD_SCRATCH`).
- `WORK_DIR = RES_DIR / "work"` is created fresh on each run and the
  five source CSVs are copied in.
- All subsequent reads/writes (Steps 1-5, `NYISOLoader.init_state_file`,
  storage loading) go through `WORK_DIR` only.

`calibrate_branches.py` remains the only sanctioned mutator of source
CSVs; it owns its own backup-then-write workflow.

**Verified** with 2025-07-20 smoke run (`EXPERIMENT_TAG=p25_workdir`):
- MD5s of `branch.csv` / `bus.csv` / `gen.csv` / `init_state.csv` /
  `storage.csv` in `SourceData/` identical before and after the run
- `results_p25_workdir/work/` contains the per-run mutated copies
  (45 KB branch, 75 KB bus, 153 KB gen, 35 KB init_state, 5 KB storage)
- Simulation metrics byte-identical to pre-refactor `pgscen_smoke_2025`
  run at the same date (84 s, $14.7 M, 1636 MW curtailment hour 0).

### PGscen integration in run_sced.py (DONE 2026-05-27)

`run_sced.py` now pulls per-site wind/solar from PGscen-2nd CSVs when the
`PGSCEN_DIR` env var resolves (auto-detects the sibling
`../PGscen-2nd/data/NYISO_real`). The integration mirrors the PourvalLoader
pattern that already worked in `experiments/`:

- `_find_pgscen_renew_csv` handles the `.pluswind_v3` filename variant
- `_load_pgscen_renew` loads actuals + day-ahead forecasts, converts UTC
  to Eastern (DST-aware) via `tz_convert("America/New_York")`, dedupes the
  fall-back-DST collision, and reindexes onto the 48 h `dt_index`
- `_build_pgscen_site_map` snaps each PGscen site to the nearest unused
  gen of the same fuel in the same zone (cross-zone fallback)
- `create_timeseries` priority: explicit `HOURLY_CF_CSV` > PGscen >
  `DEFAULT_CF`. Mapped gens get per-site values; unmapped wind/solar gens
  get system-aggregate CF (operational-fleet output ÷ summed nameplate)
- `actl` and `fcst` columns are now genuinely distinct (forecast file
  drives `fcst`, actuals file drives `actl`); previously they were
  byte-identical
- Hydro keeps the flat 50 % CF — no per-plant data in PGscen

**Verified** on 2019-07-18 (within PGscen coverage):
- 23 wind sites mapped, CF range 0.004–0.661 (real intermittency)
- 2 solar sites mapped, CF range 0.000–0.714 (zero at night)
- Solar at midnight: **0.00 MW** (was 267 MW)
- RenewablesAvailable now varies 2010–3179 MW across the 24 h
  (was constant 3080 MW)

**Backward compatible**: for `SCED_DATE=2025-07-20`, no 2025 wind/solar
CSVs exist → silent fallback to `DEFAULT_CF`. Identical metrics to
pre-change runs at the same date (FixedCosts, VariableCosts,
RenewablesAvailable=3080 verbatim).

Set `PGSCEN_DIR=""` to disable explicitly.

---

## What's still wrong, and why

- ~~Solar 267 MW at midnight~~ — **fixed** via PGscen integration above.
  For SCED dates past PGscen wind/solar coverage (2025+) the constant-CF
  fallback still triggers; for those dates set `HOURLY_CF_CSV` instead.
- **Peak-hour overgeneration of 200–940 MW** — UC commits more thermal
  than needed during sunset hours. With per-unit PMin now correct
  (P1.1 fully done), the residual likely comes from forced renewable
  output (constant CFs floored at PMax × DEFAULT_CF) and from thermal
  PMin floors below the must-run set.
- **Hours 18–21 LMP spike — FIXED.** After closing P2.4, two branches
  with atypically tight pre-rated values (`L399_400` 630 MVA at 345 kV,
  `OSM_K_138_0026` 600 MVA at 138 kV) bound hard and produced $4,100/MWh
  shadow prices. Bumped to the upper end of friend's empirical
  envelopes (1,000 and 900 MVA respectively). Result on 2025-07-20:

  | Run                  | h18 LMP range  | h18 LMP std | Overloaded line-hours |
  |----------------------|----------------|-------------|-----------------------|
  | partial_fixes        | $-77 to $4,453 | $510        | many (binding > 100 %) |
  | calibrated (masked)  | $50 to $63     | $1.5        | 0                     |
  | **ratings_bumped**   | **$62 only**   | **$0.00**   | **0**                 |

  Both branches still bind at their new ratings (max flow 1000 / 900 MW
  matches rating exactly) so the calibration didn't over-relax; it just
  moved the binding from "infeasible by 5 %" to "clean 100 % binding".
- **~92 unmatched flowgates** — substations absent from our bus.csv
  (Adirondack, Pulaski, Northport, Pilgrim, Glenwood, Lake Success, …).
  Pure data gap.

---

## Reproducing the full pipeline

```bash
cd /Users/val/Desktop/Princeton/Grid

# 1. Fetch real hourly load for the simulation date
python fetch_nyiso_load.py --date 2025-07-20

# 2. (One-time) Calibrate branch ratings + add missing branches
#    Idempotent if re-run; always backs up branch.csv first.
python match_flowgates.py            # writes match_flowgates_results.csv
python calibrate_branches.py         # writes branch_backup_<ts>.csv

# 3. Run SCED
PYTHONPATH=../Vatic:../PGscen-2nd \
  EXPERIMENT_TAG=calibrated \
  HOURLY_LOAD_CSV=grid_data/hourly_load_20250720.csv \
  python run_sced.py
```

Outputs land in `grid_data/sced_inputs/results_calibrated/`. Runtime
~73 s with Gurobi (4 threads).
