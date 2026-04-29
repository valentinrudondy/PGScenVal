# Load Source Diagnostic

**Date**: 2026-04-27
**Target hour**: 2019-07-17 20:00 UTC (4pm EDT, Wednesday peak)

## Side-by-side comparison

| Source | MW | vs Actual |
|--------|----:|:---------:|
| **(a) NYISO actual (metered)** | **29,320** | --- |
| (b) NYISO DA forecast | 28,458 | -2.9% |
| (c) PGscen scenario 000 | 29,693 | +1.3% |
| (d) Deterministic model demand | 27,604 | -5.9% |
| (e) NyisoLoader fcst (bus-distributed) | 26,684 | -9.0% |
| (f) NyisoLoader actl (bus-distributed) | 27,604 | -5.9% |

## Finding: two-part load underestimation

### Part 1: Bus name collision bug (4.7% / 1,374 MW)

NyisoLoader.create_timeseries() distributes zonal load to buses using
a dict `bzf` keyed by bus NAME. Four pairs of buses in NYgrid share
the same name but have different bus IDs, causing the earlier entry
to be silently overwritten:

| Bus name | Bus IDs | Zone | Load kept | Load lost |
|----------|---------|------|-----------|-----------|
| ROCHESTER | 52, 53 | B (GENESE) | 462 MW | **1,063 MW** |
| RAMAPO | 75, 76 | G (HUD VL) | 182 MW | 182 MW |
| HUNTLEY | 56, 57 | A (WEST) | 120 MW | 86 MW |
| GARDENVILLE | 58, 59 | A (WEST) | 353 MW | 42 MW |
| **Total** | | | | **1,374 MW** |

This is a bug in the load distribution code (lines 1458-1462 of
nyiso_loader.py). The fix is to SUM load fractions for buses sharing
a name instead of overwriting:

```python
# Current (buggy):
bzf[n] = (bz[bid], s / zt[bz[bid]])

# Fixed:
if n in bzf:
    bzf[n] = (bzf[n][0], bzf[n][1] + s / zt[bz[bid]])
else:
    bzf[n] = (bz[bid], s / zt[bz[bid]])
```

Impact: Zone B (GENESE) loses 69.7% of its load. Zone G (HUD VL)
loses 20%. Zone A (WEST) loses 10.7%.

### Part 2: DA forecast bias (1.2% / ~342 MW)

The remaining gap is the NYISO day-ahead forecast being lower than
realized actual load. This is normal DA forecast conservatism,
especially during heat waves. This is NOT a bug -- it's the correct
behavior for a stochastic UC study using DA forecasts.

## What the cost-of-uncertainty result actually means

The v2 stochastic experiment uses DA forecast-based load (with the
bus collision bug). The 100 PGscen scenarios perturb around the
forecast. The cost-of-uncertainty (-1.01%) measures:

> "Given the DA forecast as baseline, how much does accounting for
> forecast uncertainty change expected production cost?"

This is the correct research question for stochastic UC. The gap
to NYISO actual is forecast error, not model conservatism.

The PGscen scenarios DO sometimes exceed the actual (scenario 000 =
29,693 MW vs actual 29,320 MW), confirming they sample the forecast
error distribution correctly.

## Recommendation

1. Fix the bus name collision bug (restores ~1,374 MW / 4.7% of load)
2. Do NOT replace DA forecast with actuals for the stochastic study
3. Re-run the v2 ensemble after the bug fix for a cleaner baseline
4. When comparing model LMPs to NYISO actual, note that the model
   uses DA forecast load, not realized load
