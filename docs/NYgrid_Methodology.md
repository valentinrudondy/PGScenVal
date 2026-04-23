# NYgrid Methodology: How the New York State Baseline Grid Model Was Constructed

**Based on**: Liu, M.V., Yuan, B., Wang, Z., Sward, J.A., Zhang, K.M., Anderson, C.L. (2023). "An Open Source Representation for the NYS Electric Grid to Support Power Grid and Market Transition Studies." *IEEE Transactions on Power Systems*, 38(4), 3293-3302.

**Repository**: https://github.com/AndersonEnergyLab-Cornell/NYgrid

---

## 1. Motivation and Purpose

New York State passed the Climate Leadership and Community Protection Act (CLCPA), which targets 9 GW of offshore wind, 3 GW of energy storage, and 6 GW of solar by the mid-2030s. Evaluating the feasibility and impact of such an aggressive transition requires a validated power grid model that captures the physical characteristics of the NYS transmission system. However, real utility grid data is confidential for security and commercial reasons.

NYgrid fills this gap by providing an open-source baseline model built entirely from publicly available data. It is not a synthetic test case -- it is designed to reproduce the actual behavior of the NYS grid (power flows, locational marginal prices, congestion patterns) closely enough for research and planning studies.

---

## 2. Starting Point: The NPCC 140-Bus System

The model is built from the **NPCC 140-bus system**, a power system test case from the Power System Toolbox maintained by Joe Chow at RPI. This network represents the backbone transmission system of the Northeast Power Coordinating Council (NPCC) region of the Eastern Interconnection.

### What the NPCC-140 contains

| Component | Count |
|-----------|-------|
| Buses | 140 |
| Generators | 48 |
| Transmission lines | 233 |
| ISO areas covered | 5 (NYISO full, ISO-NE partial, PJM partial, MISO partial, IESO partial) |

The 140 buses are distributed across five ISO regions:
- **Area 1** (New England / ISO-NE): 36 buses, partial representation
- **Area 2-3** (New York / NYISO): 46 buses, full representation (buses 37-82)
- **Area 4** (Ontario / IESO): 31 buses, partial representation
- **Area 5-6** (PJM): 27 buses, partial representation

The network includes bus locations (latitude/longitude), voltage levels (115-345 kV), and transmission line impedance parameters (resistance, reactance, charging susceptance). This geographical fidelity is critical -- it allows spatially correlated renewable energy integration analysis.

### Why NPCC-140 was chosen

Previous NYS grid models had significant limitations:
- **Allen et al. (2008)**: 36-bus reduction from FERC 715, intended for algorithm testing not regional study
- **Howard et al.**: transshipment model with 11 zones, no power flow capability
- **Burchett et al.**: 68-bus NPCC, not updated for NYS transmission characteristics
- **NYISO CARIS/RNA reports**: provide topology diagrams but not line parameters

The NPCC-140 is the only publicly available network that (a) covers all of NYS with geographical information, (b) preserves external interfaces with neighboring grids, and (c) includes transmission line electrical parameters needed for power flow analysis.

---

## 3. Bus Layout: Why Buses Are Where They Are

### The 46 NY buses

The 46 buses within NYS (buses 37-82) represent major substations in the bulk transmission system. Each bus corresponds to a physical location -- a high-voltage substation where transmission lines converge, generators connect, and load is served.

**Zone assignment**: Each bus is assigned to one of NYISO's 11 load zones (A through K):

| Zone | Region | Buses | Key characteristics |
|------|--------|-------|---------------------|
| A (West) | Buffalo/Niagara | 8 | Niagara hydro (2460 MW), coal |
| B (Genesee) | Rochester | 3 | Ginna nuclear (582 MW) |
| C (Central) | Syracuse/Oswego | 11 | Nine Mile Point + FitzPatrick nuclear (2782 MW) |
| D (North) | Plattsburgh/Massena | 2 | St. Lawrence hydro (856 MW), HQ imports |
| E (Mohawk Valley) | Utica/Binghamton | 7 | Small hydro, Marcy South corridor |
| F (Capital) | Albany/Troy | 4 | Combined cycle gas, HQ/NE imports |
| G (Hudson Valley) | Poughkeepsie/Newburgh | 5 | Bowline/Roseton/Danskammer gas/oil |
| H (Millwood) | Westchester | 1 | Indian Point nuclear (2066 MW), ConEd gateway |
| I (Dunwoodie) | Yonkers | 1 | Underground cable interface to NYC |
| J (New York City) | NYC | 2 | Dense gas/oil generation, highest load |
| K (Long Island) | LI | 2 | Island grid, import-constrained |

**Why some zones have many buses and others have few**: The bus count reflects the complexity of the transmission topology in each zone. Zone C has 11 buses because the Central NY area has many 345 kV and 115 kV substations connecting the nuclear plants, the Oswego generating station, and the east-west transmission corridors. Zones H and I have only 1 bus each because they represent a single major transmission path (Millwood/Dunwoodie) that funnels power from upstate to the NYC metro area.

### The 94 external buses

The remaining 94 buses represent neighboring ISO areas. They are needed to model the power flow interactions at the NY borders (imports from HQ, IESO, and PJM; exports to ISO-NE). In the original NPCC-140, these buses have their own generators and loads. In the NYgrid model, the external areas are simplified via network reduction (see Section 6).

### Population-weighted load allocation

Bus loads within each zone are allocated proportionally to the population served by each substation. The NPCC-140 base case already exhibited positive correlation between bus loading and population for most zones, but Liu et al. made corrections for zones B, G, and K where the original allocation did not match population distribution. This is documented in `Data/bus_ny_type_zone_population.csv`.

---

## 4. Transmission Lines: Why Lines Connect Specific Buses

### Original NPCC-140 branches

The 233 transmission lines in the NPCC-140 represent the major bulk power transmission paths. Their electrical parameters (resistance R, reactance X, charging susceptance B) determine how power flows through the network. The parameters are given in per-unit on a 100 MVA base.

### Modifications by NYgrid

Liu et al. applied several modifications to better represent the current NYS grid:

**1. Removed 3 PJM-IESO direct connections**
- Lines 84-116, 87-115, 90-114 connected PJM and IESO through buses that bypass NYS
- Removing them ensures external areas connect only through NYS, making it possible to control and validate interface flows

**2. Updated external interface ratings**
- PJM connections (buses 66-134, 67-138, 81-125, 75-124, 60-140): set to declared transfer capacities
- NE connections (buses 29-37, 35-73): set to declared limits
- IESO connections (buses 48-100, 54-102, 54-103): set to declared limits

**3. Added Marcy South line (E-G connection)**
- The NPCC-140 was missing the 345 kV Marcy South transmission corridor connecting zone E to zone G
- Two segments added: bus 43-38 and bus 38-77
- Reactance estimated from conductor type and physical distance between substations using: X = (L * X_L) / Z_base
- Distances: 137 miles (bus 43-38) and 47 miles (bus 38-77)

**4. Added HVDC lines**
After network reduction, four controllable HVDC lines were added:
- Bus 21-80: Cross Sound Cable + NPX-1385 (ISO-NE to zone K)
- Bus 124-79: Neptune (PJM to zone K)
- Bus 125-81: VFT + HTP (PJM to zone J)

### The 7 NYISO internal interfaces

The critical transmission constraints in NYS are defined as **interfaces** -- aggregate flow limits across groups of parallel transmission lines. These are the binding constraints that create congestion and zonal price separation:

| Interface | Direction | Typical limit | Physical meaning |
|-----------|-----------|--------------|-----------------|
| DYSINGER EAST | A -> B | 3,150 MW | Western NY to Rochester corridor |
| WEST CENTRAL | B -> C | varies | Rochester to Syracuse |
| TOTAL EAST | C/E | 6,800 MW | Major east-west divide |
| MOSES SOUTH | D -> E | 3,150 MW | North Country to Mohawk Valley |
| CENTRAL EAST | E -> F/G | 2,570 MW | **Key bottleneck**: upstate to downstate |
| UPNY-ConEd | G -> H | 5,700 MW | Hudson Valley to Westchester/NYC |
| SPR/DUN-SOUTH | I -> J/K | 4,600 MW | Dunwoodie to NYC/Long Island |

The CENTRAL EAST interface (~2,570 MW) is the most important constraint in the NYISO market. It separates cheap upstate generation (hydro, nuclear) from expensive downstate load (NYC, Long Island), creating the characteristic price split between upstate ($20-25/MWh) and downstate ($25-40/MWh).

---

## 5. Generators: How Generation Was Modeled

### Thermal generators (227 units, 27,064 MW)

**Source**: NYISO 2019 Load & Capacity Data Report, RGGI hourly emissions data, EIA-860/923.

**Process**:
1. Identified 227 fossil fuel generators from NYISO records
2. For 140 large generators tracked by RGGI (>25 MW): derived heat rate curves, Pmax, Pmin, and ramp rates from hourly generation and heat input data
3. For 87 smaller generators (mostly gas turbines in zones J and K): used EIA standard heat rates by unit type
4. Assigned each generator to the nearest bus within its NYISO load zone using `gen_bus_assignment.csv`
5. Fitted linear heat rate curves: TotalHeat(P) = slope * P + intercept, where slope is in MMBTU/MWh

**Cost curves**: Heat rate * fuel price = total cost. Fuel prices from NYISO CARIS report, varying by fuel type and week:
- Natural gas: $3-10/MMBTU depending on zone and season
- Fuel Oil 2: ~$18/MMBTU
- Fuel Oil 6: ~$13/MMBTU
- Coal: ~$3.10/MMBTU

**Generation types by zone**: Downstate zones (F, G, J, K) are dominated by gas and oil steam/CT units. Upstate zones (A-E) have coal, combined cycle gas, and nuclear. This spatial distribution means power generally flows from north to south, creating the characteristic interface congestion.

### Nuclear generators (6 units, 5,430 MW)

**Source**: US Nuclear Regulatory Commission daily capacity factors.

| Plant | Capacity | Zone | Bus |
|-------|---------|------|-----|
| FitzPatrick | 854.5 MW | C | 50 |
| Nine Mile Point 1 | 629 MW | C | 50 |
| Nine Mile Point 2 | 1,299 MW | C | 50 |
| Indian Point 2 | 1,025.9 MW | H | 74 |
| Indian Point 3 | 1,039.9 MW | H | 74 |
| Ginna | 581.7 MW | B | 53 |

Nuclear is modeled as must-run with near-zero marginal cost ($1-3/MWh). Hourly output = nameplate * daily capacity factor.

**Note**: Indian Point 2 and 3 shut down in 2020 and 2021 respectively. The 2019 baseline includes both. Simulations of 2021+ must remove ~2 GW of nuclear from zone H.

### Hydro generators (~4,270 MW)

**Source**: EIA Form 923 monthly data, NYISO fuel mix data.

The two dominant hydro plants are:
- **Robert Moses Niagara** (zone A, bus 55): 2,460 MW. Dominates the diurnal pattern with lower night output (~1,800 MW) and higher day output (~2,600 MW) due to bidding strategy. Contributes ~80% of the variation in total hydro output.
- **St. Lawrence** (zone D, bus 48): 856 MW. Operates at relatively constant monthly capacity factor, prioritizing water level regulation.

**Modeling approach**:
1. St. Lawrence output = monthly capacity factor * nameplate (from EIA-923)
2. Niagara output = 0.8 * total_hydro - St.Lawrence output (absorbs the variation)
3. All other small hydro = 0.2 * total_hydro, distributed by capacity share

Wind and other renewables are modeled as negative load (non-dispatchable).

---

## 6. Network Reduction: From 140 Buses to the NYS Model

### Why reduction is needed

The NPCC-140 has 94 external buses that represent New England, PJM, IESO, and other areas. These cannot be directly simulated for NYS-focused studies because:
- Their detailed generation data is not available
- Their internal topology is not the focus
- They increase computational cost 3x

### The Ward equivalent method

Liu et al. use a **modified Ward-type network equivalent**, which is the standard method for power system reduction. The algorithm:

1. Select buses to retain (46 NY buses + 9 boundary buses + 2 special buses = 57)
2. Compute the bus admittance matrix (Y-bus) for the full 140-bus system
3. Partition Y into internal (retained) and external (eliminated) blocks
4. Apply Gaussian elimination to produce equivalent impedances at the boundary buses
5. Replace the eliminated external buses with equivalent "virtual" generators and loads at the boundary buses

The result is electrically equivalent -- DC power flow solutions on the reduced network match the original network on all retained branches (verified to 10^-9 precision).

### Post-reduction modifications

After reduction, the network was further modified:
- Added HVDC lines (Cross Sound Cable, Neptune, HTP, VFT) connecting external areas to zone J/K
- Added the Marcy South AC line (zones E-G)
- Added interface flow limits matching NYISO declared values

The final reduced network has the same zonal topology as NYISO's RNA report shipment model.

---

## 7. Validation

### Power flow validation (2019, all hours)

DC power flow was run for every hour of 2019 and compared against NYISO-recorded interface flows. Results:
- Interquartile range: within +/-10% for all 7 internal interfaces
- 95% interval: within +/-15% for most interfaces
- Outliers in Dysinger East and Moses South: caused by hydro simplifications

The model achieves **90% accuracy for most hours** when provided with precise generation profiles.

### LMP validation (winter and summer 2019)

DC-OPF was run for winter (Dec-Jan) and summer (Jun-Aug) and zonal LMPs compared with NYISO historical data. Correlation coefficients:
- **0.8-0.9** for most zones in both seasons
- Lower for zone A (hydro bidding complexity), zone F (long-term contracts), zone K (72 thermal generators with complex bidding)

The model captures the statistical trends of real LMPs but cannot reproduce individual hours exactly because it does not model strategic bidding behavior, long-term contracts, or reserve market interactions.

### Known limitations from the paper

1. **Linear cost curves**: Real generators bid non-linear curves; the linear approximation understates cost at high output
2. **Hydro simplification**: Monthly capacity factor for St. Lawrence ignores within-month variation
3. **Missing bidding behavior**: Some generators (e.g., Bethlehem Energy Center) operate at lower-than-cost bids due to steam contracts or other revenue streams
4. **No startup costs**: The OPF formulation in the paper sets minimum output to zero, approximating UC with free cycling. Real startup costs are significant for steam and nuclear units.

---

## 8. Data Sources Summary

| Data | Source | Resolution |
|------|--------|-----------|
| Network topology | NPCC 140-bus system (Power System Toolbox) | Static |
| Bus locations | NPCC 140-bus lat/lon | Static |
| Generator list | NYISO 2019 Load & Capacity Data Report | Annual |
| Thermal hourly generation | RGGI hourly emissions database | Hourly |
| Nuclear capacity factor | US NRC daily reports | Daily |
| Hydro generation | EIA Form 923, NYISO fuel mix | Monthly/Hourly |
| Zonal load | NYISO real-time market database | 5-min / Hourly |
| Interface flows | NYISO interface flow database | 5-min |
| Fuel prices | EIA, NYISO CARIS report | Weekly |
| Zonal LMPs | NYISO real-time market database | 5-min |

All data is publicly available. The model and code are open-source under MIT license.

---

## References

- Liu, M.V. et al. (2023). "An Open Source Representation for the NYS Electric Grid." IEEE Trans. Power Systems, 38(4), 3293-3302.
- NYgrid GitHub: https://github.com/AndersonEnergyLab-Cornell/NYgrid
- NPCC 140-bus system: Power System Toolbox, Chow, J.H. and Cheung, K.W.
- NYISO 2019 Gold Book (Load & Capacity Data Report)
- RGGI: https://www.rggi.org/
- EIA Forms 860 and 923: https://www.eia.gov/electricity/data/
