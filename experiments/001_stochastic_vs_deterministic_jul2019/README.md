# Experiment 001: Stochastic vs. Deterministic Unit Commitment — July 2019

## Research Question

For a fixed summer peak week (July 15–21, 2019), how much does accounting for
renewable and load uncertainty change expected production cost and commitment
behavior compared to a deterministic run on NYISO's point forecast?

## Method

1. **Scenario generation** — PGscen-2nd generates 100 correlated day-ahead
   scenarios for 31 wind plants, 16 solar plants, and 11 NYISO load zones.
   Each day is fitted independently using RegimeGeminiEngine (wind, load) and
   RegimePCAGeminiEngine (solar) with HRRR-derived historical data.

2. **Deterministic baseline** — Vatic runs a single simulation per day using
   the NYISO day-ahead forecast as both forecast and actual. This produces the
   "what-if-the-forecast-were-perfect" reference cost.

3. **Stochastic ensemble** — For each of the 100 scenarios, Vatic runs a
   simulation per day with that scenario's wind/solar/load substituted for the
   forecast. Each scenario is independent → embarrassingly parallel.

4. **Analysis** — Compare production cost, LMPs, commitment patterns, and
   reliability events between the deterministic baseline and the stochastic
   ensemble.

## Reproduction

```bash
# Activate the environment with both pgscen and vatic installed
conda activate vatic-test

# Smoke test first (5 scenarios, 1 day — ~5 min)
python run.py --smoke
python analyze.py --smoke

# Full run (100 scenarios × 7 days — ~9 hours)
python run.py
python analyze.py
```

## Directory Structure

```
001_stochastic_vs_deterministic_jul2019/
├── config.yaml          # experiment parameters
├── run.py               # main runner (scenarios + simulations)
├── analyze.py           # results processing + plots
├── README.md            # this file
├── requirements.txt     # pinned dependencies
└── results/             # output (gitignored)
    ├── run.log
    ├── summary_report.md
    ├── scenarios/       # PGscen output (parquet)
    ├── deterministic/   # Vatic baseline output (pkl)
    ├── stochastic/      # Vatic ensemble output (pkl)
    └── figures/         # publication-quality plots (PNG, 300 dpi)
```

## Key Assumptions

- Network: Kron-reduced 46-bus NY model from Cornell's NYgrid
- Solver: CBC (open source MILP) with 1% optimality gap
- UC parameters: class-based defaults from 2019 baseline (no public source for
  plant-specific heat rates or min up/down times)
- Fuel prices: 2019 weekly averages from EIA
- Blenheim-Gilboa pumped storage: excluded (not yet wired in NyisoLoader)
- External equivalents: PJM, HQ, NE, IESO modeled as import generators
