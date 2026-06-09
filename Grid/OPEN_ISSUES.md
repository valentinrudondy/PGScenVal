# Grid (ex-Pourval) — Open Issues and Fix Priorities

Status as of 2026-05-26 smoke test (`EXPERIMENT_TAG=smoke`, `SCED_DATE=2025-07-20`,
no `HOURLY_LOAD_CSV`, no `HOURLY_CF_CSV`). The standalone `run_sced.py`
completes 24 hours but the results are not physically meaningful. Below is
every issue surfaced, ranked by what must be fixed before any number is
quotable.

Evidence files referenced live under
`grid_data/sced_inputs/results_smoke/`.

---

## P0 — Blockers (no quantitative result is trustworthy until fixed)

### P0.1 — Branch ratings are missing on 877/899 lines
Only 22 of 899 branches carry a finite `Cont Rating`; the rest are
`999_999 MW` (effectively infinite). Of the 22 that are rated, **four are
already overloaded** in the smoke run:

| Line     | From→To zone | Flow (MW) | Rating | Use     |
|----------|--------------|-----------|--------|---------|
| L399_400 | B → C        | −1344     | 630    | 213 %   |
| L359_510 | F → G        |  1720     | 840    | 205 %   |
| L354_359 | G → F        |   840     | 840    | 100 %   |
| L366_398 | E → C        |  −800     | 800    | 100 %   |

Action: populate `Cont Rating` for the remaining 877 branches from
NYISO interface capacities and HIFLD line specs. The "Result is not
transmission feasible" warnings persist until this is fixed.

### P0.2 — DC tie locations are partially wrong
The keyword-search fallback in `run_sced.py` lines ~250–262 silently routes
ties to arbitrary same-zone buses when the keyword misses. Current state:

| Tie         | MW    | Landed at                       | Status                          |
|-------------|-------|---------------------------------|---------------------------------|
| Chateauguay | 1000  | Middle_Road_Station             | OK                              |
| Massena     |  200  | Massena_Substation              | OK                              |
| Niagara     |  500  | Moraine_Road_Station            | Suspect — not the NY-Ontario tie point  |
| Ramapo      |  600  | Ramapo_Substation               | OK                              |
| **Linden**  |  300  | **Academy_Substation (fallback)** | **Wrong** — should be Goethals_Substation |
| **Northport**|  100 | **East_Garden_City (fallback)** | **Wrong** — no NORTHPORT bus exists |

Action: replace the `(keyword, mw, zone)` list with explicit `Bus Name` ↔
tie-point assignments. Verify the Niagara substation row exists and is
actually the Ontario interconnect.

### P0.3 — 4 Zone J buses ship with NaN `Area`/`Sub Area`
Affected buses: Newtown, **Goethals**, Willowbrook, Woodrow — exactly the
NYC ConEd cluster flagged in the README as "draft topology, CEII not
public." Goethals being NaN is also why the Linden tie keyword search
missed it (P0.2). The current `fillna(zone_letter→8)` in `run_sced.py` is
a crash workaround, not a data fix.

Action: get correct Area/Sub Area for these 4 rows in
`grid_data/sced_inputs/SourceData/bus.csv`, and revisit whether their
branch connectivity (the `DRAFT_` lines) is accurate.

### P0.4 — Timeseries are flat — every hour after warmup is identical
**RESOLVED** (load + wind/solar):
- Load (a) via `HOURLY_LOAD_CSV` (NYISO MIS palIntegrated, fetched by
  `fetch_nyiso_load.py`); produces real diurnal load shape.
- Wind/solar via PGscen integration in `run_sced.py` (auto-detects
  `../PGscen-2nd/data/NYISO_real`, set `PGSCEN_DIR=""` to disable).
  Per-site actuals + day-ahead forecasts, UTC→Eastern aligned.
  Validated 2019-07-18: solar=0 MW at midnight (was 267 MW), wind
  CF range 0.004–0.661.

Residual: hydro stays at flat 50 % CF (no per-plant data in PGscen).
For SCED dates past PGscen coverage (2025+), still falls back to
DEFAULT_CF — supply `HOURLY_CF_CSV` for those.

### P0.5 — Bus-level LMPs span 4 orders of magnitude in the same hour
At hour 12: min $0.83, max $4,217, std $1,711. Zone medians range from
$53 (D) to $4,135 (A). The $47.79/MWh "Price" in `hourly_summary.csv`
is a load-weighted average that hides this.

Root cause: P0.1 — a handful of binding constraints over a sparsely-rated
network produce arbitrary PTDF shadow prices. Will resolve when P0.1 is
fixed; cannot be fixed in isolation.

---

## P1 — High (needed before any realistic simulation)

### P1.1 — `PMin = 0` for every non-nuclear thermal unit
Source: `gen.csv` ships with `PMin MW = 0` for all 458 thermal units
(284 Gas, 106 Biomass, 68 Oil). With `PMin=0`, commitment decisions are
trivialised — a unit "on" at 0 MW costs nothing, so the UC has no reason
to ever shut anything down. Real gas plants are 30–50 % PMin/PMax.

Action: populate `PMin` from EIA-860 plant data or unit-type defaults
(CT ≈ 0.5×Pmax, CC ≈ 0.4×Pmax, ST ≈ 0.3×Pmax).

### P1.2 — `init_state.csv` is not time-of-day aware
1,461 of 1,504 generators are flagged "on for 1000 hours" at t=0,
including **all 632 solar, all 38 wind, all 372 hydro units**. Solar
cannot have been "on" for 1,000 hours at midnight on a July day. The
remaining 43 "off" units are all Gas. The file is a static template,
not a state snapshot for `SCED_DATE`.

Action: generate `init_state.csv` per date from a previous-day SCED, or
at minimum (i) restrict UnitOnT0State to thermal+nuclear, (ii) reflect a
plausible overnight-thermal commitment for the target hour.

### P1.3 — Heat-rate curves treated as flat $/MWh
`run_sced.py` reads `HR_incr_1` and uses it as the flat marginal cost.
Real units have quadratic heat-rate curves with increasing marginal
cost beyond mid-load. `Output_pct_0/1/2` and the three `HR_incr` columns
exist in `gen.csv` but only the first segment is read.

Stats from current input:
- Biomass: flat $38, no dispersion
- Gas: $23–62 (OK)
- Oil: only 2 distinct values ($214 and $269)
- Nuclear: flat $6, OK

Action: build a 3-segment piecewise cost curve from the three
`HR_incr_*` columns, with fuel-price multiplication if not already
embedded.

### P1.4 — Reserves are chronically short
`AvailableReserves ≈ 1,328 MW` against a 5 % requirement of ~1,400 MW
for 14 consecutive hours → 79 MW shortfall reported each hour. Thermal
is committed near max with little operational headroom. With realistic
load shapes (P0.4), this gets worse.

Action: investigate after P1.1 and P1.2 — coarse PMin and incorrect
initial states may force overcommitment. Then re-evaluate reserve
factor / fixed MW target.

### P1.5 — Pumped-hydro mis-classified as BESS
The 1,160 MW / 9,280 MWh Blenheim-Gilboa pumped storage is in
`storage.csv` and gets bucketed into Zone E BESS. After zone aggregation
it dominates the system (92 % of total energy capacity). Pumped hydro
has different round-trip efficiency, cycling economics, and minimum SOC
than lithium BESS.

Action: split into two storage tables, or add a `_stor_type` filter so
pumped hydro and BESS are modeled with different parameters.

### P1.6 — Zones J and K have zero BESS in current storage allocation
After the storage aggregation, Zone J = 0 MW, Zone K = 0 MW. The
underlying `storage.csv` has 59 units but none are at Zone J/K buses
after the join, contradicting EIA-860 (Ravenswood, BQDM, LI grid BESS
projects). Likely a Bus ID assignment issue, not a missing-units issue.

Action: cross-check `storage.csv` `Bus ID` field against EIA-860 plant
locations for NYC and LI projects.

---

## P2 — Medium (required for integration with existing pipeline)

### P2.1 — No `NyisoLoader`-compatible loader exists
`run_sced.py` builds a local `NYISOLoader` class inline. It does not
expose:
- `loader.template` (used by every experiment under `experiments/`)
- `loader._pgscen_site_map` (used for scenario application in
  experiments 001/002)
- the interface-constraint dict (the existing loader exposes 7 NYISO
  interfaces: DYSINGER_EAST, WEST_CENTRAL, TOTAL_EAST, MOSES_SOUTH,
  CENTRAL_EAST, UPNY_CONED, SPR_DUN_SOUTH)
- Path B year-specific import costs

Action: create `Vatic/vatic/data/pourval_loader.py` (or rename to
`grid_loader.py`) implementing the same public contract as
`NyisoLoader`. PGscen wind/solar sites map by nearest lat/lon within the
same zone (Pourval bus rows already carry `lat`/`lng`).

### P2.2 — NYISO interface constraints not wired
The 22 rated branches don't include the named NYISO interfaces. The
existing `NyisoLoader` aggregates intra-zone branch crossings into 7
named interfaces with calibrated limits. Pourval has finer resolution
but no aggregation logic.

Action: in the new loader, build interface groups by walking branches
whose endpoints cross specific zone pairs (e.g. C↔E = TOTAL_EAST), then
emit `template['Interfaces']` with NYISO 2025 declared limits.

### P2.3 — Two disconnected buses silently dropped
Step 2b reports "Dropping 2 disconnected buses (0.0 MW load)" and
"branch.csv: 899 retained, 1 dropped". The dropped IDs are not logged.
For reproducibility, the connectivity check should write the dropped
list to a sidecar file.

Action: dump dropped bus IDs and branch UIDs to
`results_<tag>/dropped_topology.csv`.

### P2.4 — Load distribution leaks 628 MW between Step 2 and Step 5
- Step 2 reports "Net load after ties: 28,771 MW"
- `hourly_summary.csv` reports "Demand: 28,142.75 MW" each hour

The 628 MW gap is unexplained — the two dropped buses had 0 MW load, so
it isn't them. Likely the Vatic loader silently zeros load at buses
whose `Bus Name` doesn't appear in the bus_county_weights map, or some
buses are inadvertently filtered when building the template.

Action: instrument the bus → template handoff and account for the gap.

### P2.5 — Step 1 mutates `grid_data/sced_inputs/SourceData/branch.csv`
**RESOLVED**: `run_sced.py` now copies the five source CSVs into a
per-run `WORK_DIR` (`results_<tag>/work/`) on every invocation and reads/
writes only there. `SourceData/` stays read-only — `calibrate_branches.py`
is the only sanctioned mutator. Verified via MD5 comparison.

---

## P3 — Low (cleanups, sanity, nice-to-have)

### P3.1 — `EIA 861 county weights` leaves 102 buses on fallback
"102 buses used BaseKV fallback weight" — these are buses absent from
`bus_county_weights.csv` and get a `BaseKV^0.5 × 0.01` proxy. Acceptable
but worth quantifying which zones / how much load.

### P3.2 — `is_split` column has mixed bool/NaN values
`pd.read_csv` gives `True/False/NaN` for `is_split`. The mask uses
`.astype(str).str.lower().isin(["false","0","false"])` — the third value
is a typo for what was presumably "False" duplicated. Works because
"false" appears twice in the set, but the intent is unclear.

### P3.3 — `STORAGE_AGGREGATE` modes other than `zone` are stubbed
`run_sced.py` lines 604–606: `STORAGE_AGG != "zone"` just sets
`storage_elements = {}` and prints a message — `bus` and `none` modes do
nothing useful.

### P3.4 — Hardcoded summer-peak zonal load
`ZONE_LOAD_MW` (run_sced.py lines 82–92) is the Gold Book 2025 summer
coincident peak. For winter or shoulder-season runs, these numbers are
wrong, and the script offers no override beyond an env var. The README
documents this caveat but `SCED_DATE` defaulting to a peak summer day
makes the hardcoded values look authoritative.

### P3.5 — `EXPERIMENT_TAG` reuses the same `results_<tag>` directory
Re-running with the same tag overwrites previous results without
warning. A timestamp suffix or a `--force` flag would prevent silent
clobbering during iteration.

### P3.6 — `vatic` import error is uninformative
Line 337 prints `pip install vatic` even though `vatic` is a local
unpackaged module. The actual fix is to set
`PYTHONPATH=Vatic:PGscen-2nd` or install the local package in editable
mode.

---

## Suggested order of attack

1. **P0.1 + P0.3** together — fix branch ratings and the NaN Zone J
   buses. Without these, every flow and price is fiction.
2. **P0.2** — manually pin the 6 DC ties to named buses; remove the
   keyword-fallback path.
3. **P0.4** — wire `HOURLY_LOAD_CSV` from NYISO MIS for one validation
   day. Even without PGscen integration, a real diurnal load gives
   recognisable price shape.
4. **P1.1 + P1.2** — populate PMin from EIA-860 and rebuild init_state
   per-date. After this, point (1)'s LMPs should look like NYISO
   reality, not numerical noise.
5. **P1.3 / P1.5 / P1.6** — heat-rate piecewise curves, split pumped
   hydro from BESS, fix J/K storage allocation.
6. **P2.1 + P2.2** — create `pourval_loader.py` matching the
   `NyisoLoader` contract, with interface constraints. This unblocks
   every existing experiment under `experiments/`.
7. **P2.x + P3.x** — cleanups.

A practical milestone after step 4: re-run with a real load CSV and a
date for which 2025 NYISO DA LMPs are available, and validate
zone-by-zone medians within ±25 % of actuals. If that lands, the grid
is ready for stochastic experiments.
