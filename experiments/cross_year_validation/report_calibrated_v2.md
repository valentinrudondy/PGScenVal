# Cross-Year Validation Report v2 — After Import Limit Update

> Generated 2026-04-23. Change 2 applied: import Pmax values updated
> to median declared transfer capability from NYISO interface flow data
> (2019–2023). All runs include warmup day + 2,620 MW fixed reserve.

## Result: 2022 FAILS — HQ import cost too low

**Change 2 must not be applied without also updating HQ import cost.**
The 2022 LMP deviation collapsed from +10.8% to **-59.9%** because
3,015 MW of HQ hydro at $5/MWh floods the market, displacing $50–90/MWh
gas generation. This is the warning sign flagged in the task.

## Summary table

| Year | Metric | v1 (old imports) | v2 (new imports) | Target | Status |
|------|--------|-----------------|-----------------|--------|--------|
| 2020 | Load shed | 0 MWh | 0 MWh | <100 | PASS |
| 2020 | Reserve shortfall | 1,917 MWh | **0 MWh** | <500 | **fixed** |
| 2020 | LMP deviation | +38.8% | **-5.0%** | <±40% | **improved** |
| 2022 | Load shed | 0 MWh | 0 MWh | <100 | PASS |
| 2022 | Reserve shortfall | 6,976 MWh | **0 MWh** | <500 | **fixed** |
| 2022 | LMP deviation | +10.8% | **-59.9%** | <±8% | **FAIL** |
| 2023 | Load shed | 0 MWh | 0 MWh | <100 | PASS |
| 2023 | Reserve shortfall | 0 MWh | 0 MWh | <500 | PASS |
| 2023 | LMP deviation | +17.4% | **-13.0%** | <±40% | improved |

## Import dispatch statistics

| Year | Import | Pmax | Mean dispatch | % hours at Pmax | % hours at 0 |
|------|--------|------|---------------|-----------------|--------------|
| 2020 | PJM ($30) | 3,660 | 42 MW | 0% | 90% |
| 2020 | HQ ($5) | 3,015 | 3,015 MW | **100%** | 0% |
| 2020 | NE ($35) | 1,680 | 0 MW | 0% | 100% |
| 2020 | IESO ($15) | 1,625 | 685 MW | 11% | 43% |
| 2022 | PJM ($30) | 3,660 | 2,324 MW | 1% | 0% |
| 2022 | HQ ($5) | 3,015 | 2,880 MW | **74%** | 0% |
| 2022 | NE ($35) | 1,680 | 0 MW | 0% | 100% |
| 2022 | IESO ($15) | 1,625 | 636 MW | 7% | 36% |
| 2023 | PJM ($30) | 3,660 | 121 MW | 0% | 53% |
| 2023 | HQ ($5) | 3,015 | 3,007 MW | **96%** | 0% |
| 2023 | NE ($35) | 1,680 | 0 MW | 0% | 100% |
| 2023 | IESO ($15) | 1,625 | 734 MW | 7% | 12% |

### Sanity check assessment

- **PJM ($30/MWh)**: Behaves economically. Dispatches significantly
  only in 2022 when NY internal LMPs exceed $30 due to high gas prices.
  At Pmax only 1% of hours. In 2020/2023 with LMPs ~$16–20, PJM is
  uneconomic and barely dispatches. **Correct behavior.**

- **HQ ($5/MWh)**: At or near Pmax in every year (74–100% of hours).
  At $5/MWh, HQ is always cheaper than any NY generator (even nuclear
  at ~$7/MWh fuel cost). This is correct optimizer behavior given the
  cost input — but the **$5 cost is wrong for 2022**. In reality, HQ
  imports are priced via bilateral contracts at prices that track
  regional LMPs, not at HQ's internal generation cost. **Warning sign
  triggered.**

- **NE ($35/MWh)**: Zero dispatch in all years. Internal LMPs are
  below $35 in 2020 and 2023, and NE is correctly not imported. In
  2022, internal LMPs would be $70+ without HQ flooding, but with HQ
  suppressing prices to $27, NE is still uneconomic. **Correct
  behavior** (given the HQ distortion).

- **IESO ($15/MWh)**: Moderate dispatch (636–734 MW mean). At Pmax
  7–11% of hours, at zero 12–43% of hours. Dispatches when NY internal
  prices exceed $15. **Correct behavior.**

## What the data tells us

### The good news

1. **Reserve shortfall eliminated in all years.** The extra import
   capacity provides headroom that the old limits didn't allow. 2020
   shortfall dropped 1,917 → 0, 2022 dropped 6,976 → 0.

2. **2020 LMP match is excellent.** Model $15.85 vs NYISO $16.68
   (-5.0%). This is the best match of any year across all calibration
   iterations.

3. **Import dispatch is economically rational.** PJM, NE, and IESO
   all dispatch only when their cost is below the internal LMP.

### The problem

**HQ at $5/MWh is price-inelastic** — it always dispatches at maximum
because nothing in NY is cheaper. This makes the model insensitive to
the NY marginal cost, which is gas-price-driven. In a $9/MWh gas year
(2022), the real HQ import price would be bid at $30–50/MWh (capturing
the NY-HQ basis differential), not at HQ's internal $5/MWh cost.

The fix is year-specific HQ import costs, but that was explicitly
excluded from this task ("Do NOT change import COST values"). The import
Pmax changes are physically correct; the cost model needs work.

## Recommendation

**Keep the new Pmax values** — they represent physical capability and
are correct. **Do not apply Change 2 to production runs until HQ cost
is recalibrated.** For the next iteration:

1. Set HQ cost to the NYISO Zone D day-ahead LMP for each year (this
   is the price at which HQ actually clears in the NY market). For
   2022, this would be ~$45–50/MWh, which would make HQ dispatch only
   when NY-internal prices exceed that level.

2. Alternatively, set HQ cost to the bilateral contract price
   (approximately 80% of the annual average Zone D LMP, reflecting
   the discount for firm capacity).

3. A third option: keep HQ cost at $5 but cap HQ Pmax at the actual
   realized average import level (~1,500–2,000 MW depending on year)
   rather than the declared physical limit. This is a volume cap
   approach rather than a price fix.

Until then, the **v1 calibration (Changes 1+3 with old import limits)
remains the production configuration**.
