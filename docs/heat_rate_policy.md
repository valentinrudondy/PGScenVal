# Heat Rate Policy Decision

## Decision: A — Freeze at 2019 values

Generator heat rates are frozen at the 2019 NYgrid baseline values
for all simulation years. This is an explicit, documented decision.

## Rationale

### Heat rates change slowly

Heat rates are physical properties of generators determined by
thermodynamic design, turbine condition, and operating mode. For a
given unit at a given operating point, the heat rate changes only due
to:
- Major refurbishment (e.g., turbine blade replacement)
- Degradation over time (~0.1-0.3% per year)
- Fuel switching (rare for NY gas/oil units)

Year-over-year changes are typically 0.5-2%, much smaller than the
10-30% variation in fuel prices across years.

### Impact on LMPs is small

The LMP at a bus is set by the marginal generator's variable cost:

    variable_cost = heat_rate × fuel_price

If heat rates drift by 1% while fuel prices change by 30%, the heat
rate contribution to LMP error is:

    heat_rate_error / fuel_price_error ≈ 0.01 / 0.30 ≈ 3%

This is well below the ~$5-10/MWh errors from other sources (import
pricing, Kron approximation, cost-based vs. market dispatch).

### EIA-923 data availability

EIA Form 923 (Power Plant Operations Report) publishes monthly
generator-level heat rates for plants >10 MW. The data is:
- Published annually with a 12-18 month lag
- Available at the plant level (not always generator-level)
- Covers fuel consumption and net generation, from which heat rates
  can be derived
- Available from 2001 onward via the EIA Open Data API

Implementing per-year heat rate updates would require:
1. Downloading EIA-923 data for each year
2. Matching EIA plant IDs to NYISO PTIDs (non-trivial)
3. Computing unit-level heat rates from monthly fuel/generation data
4. Handling missing data (many small units don't report)
5. Validating that the updated heat rates don't introduce artifacts

### Cost-benefit

The implementation effort (1-2 weeks) is disproportionate to the
expected accuracy improvement (<1% on LMPs). The existing heat rate
curves in the baseline were derived from EIA-923 2019 data with
linear and quadratic fits (R² > 0.85 for most units).

## Implications

- Generator cost curves use `heat_rate × fuel_price` where heat_rate
  is the 2019 value and fuel_price is year-specific (from
  `fuelPriceWeekly_{year}.csv`).
- The fuel price update captures the dominant year-over-year cost
  variation. Heat rate freeze adds a small systematic bias that is
  constant across years.
- If a unit undergoes a major refurbishment that changes its heat
  rate by >10%, this would show up as a unit-level LMP error but
  not a systematic model bias.

## Future reconsideration

Consider upgrading to Decision B (per-year heat rates) if:
1. A specific validation failure is traced to heat rate drift
2. The EIA-923 matching infrastructure is built for another purpose
3. The model's other error sources are reduced to the point where
   heat rate drift becomes the dominant term

Until then, this is a documented known limitation (see
`docs/known_limitations.md` item 5).
