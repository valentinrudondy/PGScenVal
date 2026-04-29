# Missing Feature Impact Estimates

**Year**: 2020 Sep 22-24
**Baseline**: Model bus LMP $19.4/MWh vs NYISO load-weighted $17.3/MWh (+12.3%)

## Decomposition

### 1. Reserve shortfall penalty: +$3.3/MWh (dominant factor)

The 2,620 MW fixed reserve requirement binds in 39/72 hours (54%).
When binding, the $1,000/MWh penalty inflates the marginal price by
~$6.0/MWh on those hours. System-average contribution: **+$3.3/MWh**.

Without reserve shortfall, the model LMP drops to $16.1/MWh, which
is -6.6% below NYISO — slightly underestimating, as expected for a
production cost model without bid markups.

**Root cause**: The 2,620 MW is the total NYISO operating reserve
requirement, but the real system meets it with a mix of synchronized
reserves, 10-minute non-sync, and 30-minute reserves from different
resource types. The model applies it as a single constraint on
thermal headroom, which is more restrictive than the multi-tier
real requirement. Additionally, the model does not count storage
discharge headroom or import ramp as reserve-eligible.

**Fix**: Implement a multi-tier reserve requirement or reduce the
single-tier requirement to ~2,000 MW (the spinning + 10-min
non-sync component that thermal units actually provide). Alternatively,
use reserve_factor=0.05 instead of fixed MW to scale with load.

### 2. No congestion pricing: 0 direct, but prevents zonal accuracy

The model produces uniform LMPs across all 35 buses. This doesn't
directly explain the system-average gap but prevents meaningful
zonal LMP validation.

Interface constraints are set at 2.0x Kron scale and never bind
for this shoulder-season week. To produce congestion:
- Reduce Kron scale from 2.0x to 1.0-1.3x
- Or add zonal reserve requirements that force local generation

**Estimated impact on system-average LMP**: Neutral to slightly
negative (-$0-1/MWh). Congestion would lower upstate LMPs and
raise downstate LMPs, but load-weighted average wouldn't change
much since most load is downstate.

### 3. No bid markups: would INCREASE overestimation

The model already overestimates by +12.3%. Adding 5-15% bid markups
would increase model LMPs by ~$1-3/MWh, worsening the match.

This means the model's marginal cost curves are already calibrated
at approximately the right level. The overestimation from reserve
shortfall happens to approximately offset the typical 5-15%
underestimation from using cost instead of offer prices.

**Estimated impact**: +$1-3/MWh (wrong direction).

### 4. No ORDC (Operating Reserve Demand Curve): small effect

NYISO uses stepped reserve demand curves, not a continuous ORDC
like ERCOT. The maximum scarcity adder is ~$100-300/MWh for the
marginal reserve MWh, but this activates rarely.

For Sep 2020 (shoulder season, moderate load), ORDC adders were
likely near zero. This feature matters more during heat waves
(July) or cold snaps (January).

**Estimated impact for this period**: ~$0/MWh.

### 5. No capacity payments: negligible hourly LMP effect

NYISO's installed capacity market (ICAP) charges are settled
separately from energy LMPs. They do not add to hourly DA LMPs.

**Estimated impact**: $0/MWh.

## Summary

| Feature | Impact on gap | Direction |
|---------|:------------:|:---------:|
| Reserve shortfall penalty | **+$3.3/MWh** | Increases overestimation |
| No congestion | ~$0/MWh | Neutral |
| No bid markups | +$1-3/MWh | Would increase overestimation |
| No ORDC | ~$0/MWh | Neutral for this period |
| No capacity payments | $0/MWh | None |

**Key insight**: The model's +12.3% overestimation is not from
missing features that underestimate LMPs. It's from the reserve
shortfall penalty being too aggressive. Removing that single effect
brings the model to -6.6%, which is within the expected range for
a production cost model and approximately offset by the absence
of bid markups.

The model is closer to NYISO than initially believed. The apparent
40-50% underestimation was caused by comparing average cost (not
marginal cost) to NYISO LMPs.
