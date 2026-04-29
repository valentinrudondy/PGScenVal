# Literature Comparison: Production Cost Model vs Market LMP

## Published validation studies

### General findings (across all PCM tools)

Production cost models consistently show 10-25% mean deviation from
market LMPs in well-calibrated studies. The deviation is typically
an underestimate (model LMPs lower than market) because:
- Models use marginal cost offers, not strategic bids
- Models lack scarcity pricing adders (ORDC)
- Models may miss congestion in reduced networks

### Specific studies

**NREL Prescient (MISO/PJM, 2019-2021)**:
Day-ahead LMP RMSE typically 15-30 $/MWh against markets with
mean prices of $30-40/MWh, corresponding to ~40-80% relative
error. Systematic underestimation of peak prices. Uses marginal
cost dispatch without bid markups.

**PROMOD (PJM, various years)**:
Studies for PJM capacity market filings report modeled annual
average LMPs within ~10-20% of actuals in normal years. Deviations
of 50-100%+ during scarcity events. PROMOD includes detailed
bid modeling when configured for it.

**PLEXOS (CAISO/WECC)**:
E3 and ICF studies report ~10-25% mean absolute deviation from
actuals in off-peak hours; peak hour deviations much larger.

### Our model in context

| Study | Model | Market | Deviation | Features included |
|-------|-------|--------|-----------|-------------------|
| NREL Prescient | Prescient | MISO/PJM | ~40-80% RMSE | No bids, no ORDC |
| PJM capacity | PROMOD | PJM | ~10-20% | Full bid modeling |
| E3/ICF | PLEXOS | CAISO | ~10-25% | Varies |
| **This project** | **Vatic/Egret** | **NYISO** | **-6.6% (no RS)** | **PTDF, Path B** |
| | | | **+12.3% (with RS)** | |

Our -6.6% (without reserve shortfall) is better than most published
PCM validations. This is likely because:
1. The bus collision fix ensures correct system load
2. Path B import costs are year-specific from NYISO DA LMP data
3. The 2020 September period is a mild shoulder season with
   minimal scarcity, where PCMs perform best

The +12.3% with reserve shortfall is still within the published
range and is attributable to a single known cause (reserve
constraint calibration).

## NYISO-specific parameters

**Locational reserve requirements** (from NYISO Ancillary Services Manual):
- 10-min synchronized: ~1,200-1,400 MW in SENY (zones G-K)
- 10-min non-synchronized: ~500-600 MW in NYC (zone J)
- 30-min total: ~2,500 MW system-wide
- The 2,620 MW used in the model is the total requirement applied
  as a single system-wide constraint, which is more restrictive
  than the actual multi-tier, multi-zone structure.

**Bid markups** (from Potomac Economics NYISO State of the Market reports):
- NYC gas units: ~1.15-1.35x marginal cost
- Upstate gas units: ~1.05-1.15x marginal cost
- System average: ~10-15% above marginal cost

**ORDC adders**:
- NYISO uses stepped reserve demand curves
- Maximum scarcity adder: ~$100-300/MWh for marginal reserve MW
- Typical adder during shoulder season: near zero
- Significant only during heat waves and cold snaps
