# BESS Integration Guide

## How storage is modeled in Vatic

Vatic uses Egret's storage formulation, which models each storage unit
with:

- **Decision variables**: charge power (MW), discharge power (MW),
  state of charge (fraction of energy capacity)
- **Complementarity**: cannot charge and discharge simultaneously
- **SOC balance**: energy in = charge × efficiency; energy out =
  discharge / efficiency; SOC tracks cumulative energy
- **SOC bounds**: min_soc ≤ SOC ≤ 1.0 at every hour
- **End-of-horizon**: SOC at final hour ≥ initial SOC (prevents
  the optimizer from draining storage to zero)
- **Ramp limits**: per-hour limits on charge/discharge rate changes
- **Costs**: optional charge_cost and discharge_cost ($/MWh)

## Existing storage units

| Unit | Type | Bus | Discharge | Charge | Energy | Eff. (RT) |
|------|------|-----|-----------|--------|--------|-----------|
| BG (Blenheim-Gilboa) | Pumped hydro | GILBOA (38, Zone E) | 1,160 MW | 1,160 MW | 9,280 MWh | 80% |
| Lewiston | Pumped hydro | NIAGARA E (55, Zone A) | 240 MW | 240 MW | 2,880 MWh | 77% |

## How to add a new BESS unit

### Step 1: Add to `_PUMPED_STORAGE` dict

In [nyiso_loader.py](../Vatic/vatic/data/nyiso_loader.py), add an
entry to the `_PUMPED_STORAGE` dictionary (the name is historical —
it handles all storage types, not just pumped hydro):

```python
'MyBESS': {
    'name': 'My Battery Storage System',
    'bus': 82,              # Bus ID from NYgrid network
    'max_discharge_rate': 200,   # MW
    'max_charge_rate': 200,      # MW
    'energy_capacity': 800,      # MWh (200 MW × 4h)
    'charge_efficiency': 0.92,   # Typical Li-ion one-way
    'discharge_efficiency': 0.92,# Round-trip ~85%
    'initial_soc': 0.5,          # Start at 50%
    'min_soc': 0.1,              # Don't go below 10%
},
```

### Step 2: Choose the right bus

Use the zone-to-bus mapping from the Kron-reduced network:

| Zone | Letter | Representative bus ID | Bus name |
|------|--------|----------------------|----------|
| WEST | A | 55 | NIAGARA E |
| GENESE | B | 53 | ROCHESTER |
| CENTRL | C | 50 | OSWEGO |
| NORTH | D | 48 | MOSES E |
| MHK VL | E | 38 | GILBOA |
| CAPITL | F | 42 | ALBANY area |
| HUD VL | G | 77 | ROSETON area |
| MILLWD | H | 74 | BUCHANAN |
| DUNWOD | I | 75 | RAMAPO |
| N.Y.C. | J | 82 | NYC load center |
| LONGIL | K | 80 | LONG ISLAND |

### Step 3: Required parameters

| Parameter | Unit | Description | Typical BESS |
|-----------|------|-------------|--------------|
| `max_discharge_rate` | MW | Maximum discharge power | Project nameplate |
| `max_charge_rate` | MW | Maximum charge power | Usually = discharge |
| `energy_capacity` | MWh | Total energy capacity | MW × duration (hours) |
| `charge_efficiency` | 0–1 | One-way charge efficiency | 0.92–0.95 |
| `discharge_efficiency` | 0–1 | One-way discharge efficiency | 0.92–0.95 |
| `initial_soc` | 0–1 | Starting state of charge | 0.5 |
| `min_soc` | 0–1 | Minimum allowed SOC | 0.05–0.10 |

### Step 4: Verify

Run the smoke test:

```bash
python experiments/bess_test/run.py --test 2
```

Check that:
- The unit appears in storage dispatch output
- SOC stays within bounds
- The unit charges and discharges at appropriate hours

## How storage dispatch works

The UC/ED optimizer dispatches storage to minimize total system cost.
With `charge_cost=0` and `discharge_cost=0`, storage arbitrages
peak/off-peak price differences:

1. **RUC (day-ahead)**: The unit commitment determines whether storage
   will be available. Since storage has no startup constraints, it's
   always available.

2. **SCED (real-time)**: Each hourly dispatch optimizes storage
   charge/discharge alongside all generators. The optimizer charges
   when marginal cost is low (off-peak, overnight) and discharges
   when marginal cost is high (peak afternoon/evening).

3. **SOC tracking**: Egret's SOC balance equation ensures energy
   conservation. The end-of-horizon constraint prevents the optimizer
   from simply draining storage at the end of the simulation.

## Typical BESS parameters by technology

| Technology | Duration | RT efficiency | Min SOC | Degradation |
|------------|----------|---------------|---------|-------------|
| Li-ion (LFP) | 2–4h | 85–88% | 5–10% | ~2%/year |
| Li-ion (NMC) | 1–2h | 87–92% | 10–20% | ~3%/year |
| Flow battery | 4–8h | 65–75% | 0–5% | minimal |
| Pumped hydro | 8–12h | 75–82% | 10% | minimal |

## Notes on the Egret storage model

- **Typo warning**: Egret uses `discharge_efficienty` (misspelled) as
  the parameter key. The NyisoLoader template builder uses this
  misspelling intentionally. Do not "fix" it.

- **Self-discharge**: Controlled by `retention_rate_60min` (default
  1.0 = no self-discharge). For Li-ion, self-discharge is negligible
  at hourly resolution (~0.01%/hour).

- **No degradation model**: Egret does not model cycle-dependent
  degradation. For multi-year studies, adjust `energy_capacity`
  annually based on expected degradation.

- **No minimum charge time**: Unlike thermal generators, storage has
  no minimum up/down time constraints. It can switch from charging
  to discharging (or vice versa) in consecutive hours.

## BESS cycling behavior

### When batteries cycle (and when they don't)

Storage cycling is driven by the **peak-to-trough price spread**.
The optimizer only charges when the off-peak price is low enough
that charging + efficiency losses + discharging at peak yields a
net cost reduction. The break-even spread for a battery with
round-trip efficiency η is approximately:

```
break-even spread ≈ trough_price × (1/η - 1)
```

For 85% RT efficiency and a $5/MWh trough: break-even ≈ $0.88/MWh
(always profitable). For 80% RT (pumped hydro) and $25 trough:
break-even ≈ $6.25/MWh.

### Observed behavior by scenario

| Scenario | Price spread | BG cycling | Explanation |
|----------|-------------|------------|-------------|
| 2019 shoulder (Sep) | $5–12/MWh | Minimal (5h chg, 4h dis) | Spread barely exceeds BG break-even at 80% RT |
| 2022 summer (Jul) | $24–63/MWh | Active (7h chg, 16h dis) | $34/MWh arbitrage profit; clear charge-at-trough, discharge-at-peak |
| Lewiston (any) | Same system | Never cycles | Zone A has low local LMPs (cheap hydro); local spread insufficient |

### End-of-horizon SOC constraint

Egret enforces `SOC[final_hour] >= EndPointSocStorage`, which defaults
to `initial_state_of_charge` (0.5). This prevents the optimizer from
simply draining storage over the simulation horizon. In the RUC
(48-hour planning), the optimizer sees this constraint and plans
charging in later hours to restore SOC.

In practice, when price spreads are small, the optimizer drains
storage early and does minimal charging — just enough to satisfy
the constraint marginally. When spreads are large, it actively
cycles multiple times per day.

### SOC persistence across day-by-day simulations

**Bug found and fixed in Phase 4 validation**: The `last_conditions_file`
(CSV used to chain generator states across day-by-day simulations)
originally saved only thermal generator states (`UnitOnT0State`,
`PowerGeneratedT0`). Storage SOC was not persisted, causing every
new day to reset SOC to the default `initial_state_of_charge` (0.5).
This masked the actual cycling behavior — storage appeared to "refill"
magically at day boundaries.

**Fix**: `stats_manager.py` now writes a companion `*_storage.csv`
file alongside the conditions CSV, containing `FinalSOC` for each
storage unit. `nyiso_loader.py` reads this file when loading initial
conditions and uses the chained SOC instead of the default.

After the fix, storage SOC correctly carries over: a unit that ends
day 1 at SOC=0.10 starts day 2 at SOC=0.10, forcing the optimizer
to charge before it can discharge again.
