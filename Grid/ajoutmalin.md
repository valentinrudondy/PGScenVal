# Procedure: branch calibration from 7 years of NYISO binding constraints

## Objective

Use 7 years of NYISO DAM data (2019–2025) to:
1. Identify real branches that chronically saturate
2. Calibrate ratings of existing branches in `branch.csv`
3. Add branches that are physically real but absent from the model
4. Re-validate with `b9_validate.py`

The file `match_flowgates.py` already contains the matching logic — this procedure extends it and moves to action.

---

## Model context

- **739 buses**, including 71 OSM substations in zones J/K (Bus ID ≥ 10100)
- **867 branches** — all OSM at 999,999 MVA except ~20 manually calibrated
- Reference results: **v29, 4/4 PASS, Spearman 0.931**
- Main weaknesses: J=K (no price differentiation), J/K ratios too high (1.44/1.29)
- v28 backups available: `bus_backup_v28.csv`, `branch_backup_v28.csv`, `gen_backup_v28.csv`

---

## Step 1 — Fetch 7 years of binding constraints

### Script to create: `fetch_bc_7years.py`

```python
"""Fetch NYISO DAM binding constraints 2019-2025 via gridstatus."""
import gridstatus, pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexi\Projects\NYISO_Build\dartboard-ref\Realist\NYISO")
OUT  = ROOT / "grid_data/binding_constraints_7y.csv"

nyiso = gridstatus.NYISO()
frames = []
for year in range(2019, 2026):
    print(f"Fetching {year}...")
    try:
        df = nyiso.get_limiting_constraints_day_ahead(
            start=f"{year}-01-01",
            end=f"{year+1}-01-01",
            verbose=False,
        )
        frames.append(df)
        print(f"  {len(df):,} rows")
    except Exception as e:
        print(f"  ERROR {year}: {e}")

all_bc = pd.concat(frames, ignore_index=True)
all_bc.to_csv(OUT, index=False)
print(f"\nSaved -> {OUT}  ({len(all_bc):,} rows)")
```

**Note on columns**: gridstatus returns columns such as `Interval Start`, `Interval End`,
`Limiting Facility`, `Facility PTID`, `Contingency`, `Constraint Cost`.
If names change across years, normalize before concat:
```python
df = df.rename(columns={
    "Time": "Interval Start",
    "Facility": "Limiting Facility",
    "Cost": "Constraint Cost",
})
```

**Verify coverage** after fetch:
```python
df = pd.read_csv(OUT)
print(df['Interval Start'].agg(['min','max']))
print(f"Unique days: {pd.to_datetime(df['Interval Start']).dt.date.nunique()}")
```
Expected: ~2,555 days, ~300,000–400,000 rows.

---

## Step 2 — Extended analysis: match the flowgates

Modify `match_flowgates.py` line 8 to point to the new file:
```python
bc = pd.read_csv(f'{ROOT}/grid_data/binding_constraints_7y.csv')
```

Then re-run:
```
python match_flowgates.py > match_7y_results.txt
```

### What to look for in the results

**Existing branches to calibrate**: all with `hours_7y >= 200` (i.e., ~4 cumulative weeks over 7 years).
Interpretation: if a branch saturates 200h/7y = 29h/y on average → significant constraint.

**Missing branches to add**: only if:
- Reliable match (both buses clearly identified, no name confusion)
- `hours_7y >= 500` AND `mean_cost >= 10 $/MWh`
- Both buses exist in `bus.csv` with consistent coordinates (same zone or adjacent zones)

---

## Step 3 — Derive realistic ratings

### Method A — By shadow price (recommended)

The shadow price of a flow constraint = marginal cost of congestion.
A branch with average shadow price $X/MWh and average flow F MW saturates at its rating R.

Rating estimate:
```
R_estimated = max_observed_flow × 1.10   (10% safety margin)
```

Where `max_observed_flow` is the maximum flow on this branch in `results_v29/line_detail.csv`.

If the branch is not yet in the model (flow = 0), use the rule:
```
R_estimated ≈ (mean_shadow_price × zone_load) / 1000
```
This is approximate — use Method B instead.

### Method B — From official NYISO data

NYISO publishes interface limits in the DAM. For key J/K branches:

| Flowgate | Known official rating |
|----------|----------------------|
| UPNY-CONED (G→J) | 6,615 MW summer / 5,400 MW winter |
| DUNWODIE↔SHORE_RD 345 kV | ~1,300 MVA (already in model) |
| GOETHALS↔GOWANUS 345 kV | Fetch from NYISO MIS: `http://mis.nyiso.com/public/csv/flowlimits/` |

For local J/K 138 kV branches, NYISO empirical rule:
- Single circuit 138 kV: 250–450 MVA
- Double circuit 138 kV: 500–900 MVA
- 345 kV: 800–1,500 MVA

### Method C — From observed flow in v29

```python
import pandas as pd
lines = pd.read_csv('grid_data/sced_inputs/results_v29/line_detail.csv')
stats = lines.groupby('Line')['Flow'].agg(
    max_abs=lambda x: x.abs().max(),
    p95=lambda x: x.abs().quantile(0.95),
)
# Suggested rating = max_abs * 1.15 (if existing unconstrained branch)
```

---

## Step 4 — Calibrate existing branches

### Priority branches (from the 7-year analysis)

For each branch in the `existing` list of `match_flowgates.py` with `hours_7y >= 200`:

1. Retrieve max flow in `results_v29/line_detail.csv`
2. Calculate `rating = max(max_flow × 1.15, 200)`  (floor 200 MVA)
3. Apply in `branch.csv`

**DO NOT calibrate** (reset to 999,999):
- Any upstate Zone A–D branch if this collapses the zone ratio (cf. v28 lesson L224_227)
- Verify that zones D and C keep a ratio > 0.30 after calibration

### Script: `calibrate_branches_v30.py`

```python
"""
Apply calibrated ratings from 7 years of binding constraints.
Start from branch_backup_v28.csv as the base.
"""
import pandas as pd, shutil
from pathlib import Path

ROOT = Path(r"C:\Users\alexi\Projects\NYISO_Build\dartboard-ref\Realist\NYISO")
SD   = ROOT / "grid_data/sced_inputs/SourceData"

# Backup before any modification
shutil.copy(SD / "branch.csv", SD / "branch_backup_v29.csv")

branch = pd.read_csv(SD / "branch.csv")

# Ratings derived from 7-year analysis + v29 flows
# Format: UID -> rating MVA
CALIBRATIONS = {
    # Existing branches — ratings from 7 years of binding constraints
    # Fill in after step 2 analysis
    # Example:
    # "L_GOETHALS_GOWANUS":  900,   # GOETHALS↔GOWANUS 345kV, 1672h/y
    # "L_RAINEY_VERNON":     400,   # RAINEY↔VERNON 138kV, 1606h
    # "LTP_K_Y50_SHR_DUN": 1300,   # already calibrated, confirm
    # "L224_227":          99999,   # DO NOT constrain (collapses zone D)
}

for uid, rating in CALIBRATIONS.items():
    mask = branch['UID'] == uid
    if mask.sum() == 0:
        print(f"WARN: branch {uid} not found")
        continue
    old = branch.loc[mask, 'Cont Rating'].iloc[0]
    branch.loc[mask, 'Cont Rating'] = float(rating)
    print(f"  {uid}: {old:.0f} -> {rating:.0f} MVA")

branch.to_csv(SD / "branch.csv", index=False)
print(f"branch.csv updated ({len(branch)} branches)")
```

---

## Step 5 — Add missing branches

### Reliable branches to add (6–8 targets)

For each confirmed missing branch:

1. Identify bus IDs from `bus.csv` (both buses already exist)
2. Calculate resistance/reactance from geographic distance:

```python
import math

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

# Typical parameters for 138 kV overhead line:
# R = 0.05 Ω/km, X = 0.40 Ω/km, base 100 MVA, base kV = 138
# r_pu = R_ohm/km * km / (kV_base²/MVA_base)

def line_params(dist_km, kv, mva_base=100):
    z_base = kv**2 / mva_base
    if kv >= 300:
        r_per_km, x_per_km = 0.03, 0.30
    elif kv >= 100:
        r_per_km, x_per_km = 0.05, 0.40
    else:
        r_per_km, x_per_km = 0.08, 0.45
    return r_per_km * dist_km / z_base, x_per_km * dist_km / z_base
```

3. Format of a row in `branch.csv`:

```python
new_branch = {
    "UID":          "NYISO_J_GREENWD_VERNON",   # NYISO_ prefix to distinguish
    "From Bus":     bus_id_from,
    "To Bus":       bus_id_to,
    "R":            r_pu,
    "X":            x_pu,
    "B":            0.0,
    "Cont Rating":  rating_mva,   # from step 3
    "Short Term Rating": rating_mva * 1.2,
    "Emergency Rating":  rating_mva * 1.4,
    "Tap Ratio":    1.0,
    "Phase Shift":  0.0,
    "In Service":   True,
    "Branch Type":  "Line",
}
```

### Consistency check before adding

```python
# 1. Are both buses in the same connected component?
import networkx as nx
G = nx.Graph()
for _, br in branch.iterrows():
    G.add_edge(int(br['From Bus']), int(br['To Bus']))
assert nx.has_path(G, bus_id_from, bus_id_to), "buses not connected!"

# 2. Is the branch not a duplicate?
assert not ((branch['From Bus']==bus_id_from) & (branch['To Bus']==bus_id_to)).any()
assert not ((branch['From Bus']==bus_id_to)   & (branch['To Bus']==bus_id_from)).any()

# 3. Is the distance physically plausible (< 150 km for 138 kV)?
assert dist_km < 150, f"distance {dist_km:.0f} km suspicious for 138 kV"
```

---

## Step 6 — Validation pipeline

```
python calibrate_branches_v30.py     # apply ratings
python run_v30.py                    # (create from run_v29.py with tag="v30")
python b9_validate.py                # 4 criteria
```

### Success criteria for v30

| Metric | v29 (reference) | v30 target |
|--------|-----------------|------------|
| Spearman | 0.931 | ≥ 0.920 |
| J ratio | 1.44 | ≤ 1.35 |
| K ratio | 1.29 | ≤ 1.20 |
| J ≠ K | no (J=K) | yes (K > J) |
| Zone D | 0.40 | ≥ 0.35 |
| Load shed | 0 | 0 |

### Warning signals

- If an upstate zone (A–D) drops below 0.25 → the calibrated branch is blocking it. Reset to 999,999.
- If J or K has load shedding → rating too tight. Multiply by 1.5.
- If Spearman < 0.90 → regression, revert to branch_backup_v29.csv.

---

## Specific attention points

### GREENWD↔VERNON 138 kV (3,207h, $50.7/MWh)
The most frequent unmodeled constraint. Both Greenwood_Substation and
Vernon_Substation buses exist in our model (Zone J, 138 kV). The branch
is missing but the nodes are there — this is the most impactful addition to make.

### ASTANNEX 138 ASTORIAE 138 (3,629h — most frequent of all)
Our model has only one Astoria bus at 345 kV. In reality, Astoria is a generating station with
multiple distinct busbars at 138 kV and 345 kV. To properly model this flowgate,
the Astoria_Annex bus would need to be split into two: one at 345 kV and one at 138 kV. This is a
more structural modification — to be handled separately after simple branch calibration.

### LAKSUCSS / WILLWBRK / SPRNBRK
The matches for these tokens are uncertain (Lake_Colby ≠ Lake Success, Willis ≠ Williamsbridge).
Do not add these branches without manual verification of GPS coordinates vs the NYISO network.
Verification source: https://www.nyiso.com/transmission-planning (transmission network maps).

### Scriba↔Volney (L224_227)
This branch already exists and was constrained in v28 (1,200 MVA → collapse of zone D).
The 7-year analysis shows 792h binding. Do not re-constrain unless it has been demonstrated
that the impact on zone D remains acceptable (ratio D ≥ 0.35).

---

## Summary of files involved

| File | Role |
|------|------|
| `fetch_bc_7years.py` | to create — fetch gridstatus 2019–2025 |
| `grid_data/binding_constraints_7y.csv` | fetch output |
| `match_flowgates.py` | already exists — change the `bc = pd.read_csv(...)` line |
| `calibrate_branches_v30.py` | to create — apply ratings |
| `run_v30.py` | to create from run_v29.py (tag="v30") |
| `b9_validate.py` | exists — change RES to results_v30 |
| `branch_backup_v29.csv` | created automatically by calibrate script |
