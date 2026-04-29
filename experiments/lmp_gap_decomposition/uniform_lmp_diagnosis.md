# Uniform LMP Diagnosis: Kron Scale Sweep

**Date**: 2026-04-28
**Test case**: 2020-09-22 (shoulder season, single day)

## Problem

The model produces identical bus LMPs across all 35 buses at every
hour. NYISO actual shows $10-20/MWh zonal spread (NORTH cheap,
LONGIL expensive). Without zonal differentiation, the model cannot
answer zonal research questions.

## Kron scale sweep results

| Kron | CE util | UPNY util | Max spread | Bus LMP | LS | Status |
|:----:|:-------:|:---------:|:----------:|:-------:|:--:|--------|
| 2.0x | 97% | <70% | $0.00 | $18.4 | 0 | Current default |
| 1.95x | 100% | 98% | $0.00 | $17.5 | 0 | At limit, no spread |
| 1.9x | 101% | 100% | $0.00 | $17.3 | 0 | Slight overflow |
| **1.85x** | 104% | 103% | **$2.53** | $18.3 | 0 | First zonal spread |
| 1.5x | 133% | 128% | $0.52 | $16.5 | 0 | Heavy overflow |
| 1.3x | 154% | 147% | $0.52 | $16.1 | 0 | Even heavier |
| 1.1x | 183% | 174% | $0.00 | $15.9 | 0 | Violations absorbed |
| 1.0x | 199% | 196% | $5,000 | $50.9 | 0 | Slack penalty dominates |

All runs complete with zero load shedding. The $5,000/MWh PTDF
slack prevents infeasibility at any scale.

## Critical interface: Central East

Central East (zones C/E to F/G, limit 2,570 MW raw) is the
binding constraint in the Kron-reduced network. At 2.0x scale
(5,140 MW), it runs at 97% utilization — just below binding.

The UPNY-ConEd interface (zones F-I to G-K, limit 5,700 MW raw)
is the second-most utilized.

## Why no spread even at the limit?

At 1.95x, Central East is at 100% utilization but produces zero
LMP spread. This is because Egret's PTDF lazy violation adder
uses a slack-based approach:

1. The PTDF loop solves the LP without interface constraints
2. It checks for violations and adds slack variables
3. The slack penalty ($5,000/MWh) becomes a cost in the objective
4. The LP dual (bus LMP) reflects the slack cost uniformly

The slack mechanism prevents the constraint from producing a
sharp dual variable (shadow price) that would differentiate
upstream and downstream buses. Instead, the penalty is spread
across the system.

## Path to zonal differentiation

Two approaches:

### Approach A: Hard interface constraints (no slack)

Remove the violation_penalty from interface constraints and
enforce them as hard limits. This would produce true congestion
shadow prices but risks infeasibility during high-load hours.

- Pro: correct zonal LMP separation
- Con: may cause infeasibility, requires careful limit calibration
- Effort: moderate (modify data_providers.py)

### Approach B: Zonal reserve requirements

Add locational reserve requirements (SENY 1,200 MW, NYC 300 MW)
that force expensive downstate generators online. This creates
zonal price separation without relying on transmission congestion.

- Pro: addresses the real mechanism (NYISO's zonal reserves ARE
  the primary driver of downstate LMP premiums)
- Con: requires Egret zonal reserve support
- Effort: moderate

### Approach C: Reduce Kron scale + accept slack violations

Use 1.85x scale. Central East and UPNY-ConEd overflow by ~3-4%
with slack absorbing the excess. This produces $2.53 spread in
peak hours — small but a start.

- Pro: simplest parameter change
- Con: $2.53 spread vs NYISO's ~$8 spread is too small
- Effort: trivial (one parameter)

## Recommendation

**Approach B (zonal reserves) is the correct path.** In NYISO,
zonal LMP differentiation is primarily driven by locational
reserve requirements, not transmission congestion. The Central
East interface binds occasionally, but the ~$3-8/MWh downstate
premium comes from SENY generators being required for local
reserves, not from transmission flow limits.

Reducing the Kron scale (Approach C) could help marginally but
addresses the wrong mechanism. Hard interface constraints
(Approach A) would produce differentiation but for the wrong
reason if the flow patterns in the Kron-reduced network don't
match the full 140-bus model.

## Impact on current research

The uniform LMP does NOT affect:
- System-level cost-of-uncertainty (comparing stochastic vs
  deterministic within the same model)
- Total production cost accuracy (system bus LMP matches NYISO
  to within 12%)
- Commitment decisions (the dispatch is correct)

It DOES limit:
- Per-zone LMP analysis
- Congestion revenue calculations
- Zonal renewable curtailment studies
