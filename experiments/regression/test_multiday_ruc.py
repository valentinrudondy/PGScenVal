"""Test 4: Multi-day RUC vs. day-by-day simulation.

Bug class: Deterministic day-by-day UC without condition chaining.
When running multi-day analysis day-by-day, each day's unit commitment must
inherit the final generator states from the previous day. If initial
conditions aren't chained, every day starts from a cold state, causing
excessive startups and inflated costs. A properly chained day-by-day run
should produce costs within 2% of a single multi-day simulation.

Guard: Compare total cost of 3-day day-by-day (chained) vs. 3-day multi-day
(single simulation). They should be within 2% on a moderate-load period.
"""

import datetime
import os
import tempfile

import pandas as pd
import pytest


@pytest.mark.slow
class TestMultiDayRUC:
    """Verify day-by-day chaining matches multi-day simulation costs."""

    def _run_simulation(self, loader, gen_data, load_data, start_date,
                         num_days, last_conditions_file=None):
        """Run Vatic for num_days starting at start_date."""
        from vatic.engines import Simulator

        sim = Simulator(
            template_data=loader.template,
            gen_data=gen_data,
            load_data=load_data,
            out_dir=None,
            start_date=start_date,
            num_days=num_days,
            solver="cbc",
            solver_options={"seconds": 300},
            run_lmps=False,
            mipgap=0.01,
            load_shed_penalty=1e4,
            reserve_shortfall_penalty=1e3,
            reserve_factor=0.05,
            output_detail=1,
            prescient_sced_forecasts=False,
            ruc_prescience_hour=0,
            ruc_execution_hour=16,
            ruc_every_hours=24,
            ruc_horizon=48,
            sced_horizon=4,
            lmp_shortfall_costs=False,
            enforce_sced_shutdown_ramprate=False,
            no_startup_shutdown_curves=False,
            init_ruc_file=None,
            verbosity=0,
            output_max_decimals=4,
            create_plots=False,
            renew_costs=None,
            save_to_csv=False,
            last_conditions_file=last_conditions_file,
        )
        return sim.simulate()

    def test_chained_dayby_day_matches_multiday(self, nyiso_loader):
        """Day-by-day (chained) total cost must be within 2% of multi-day.

        Uses a moderate-load shoulder period (April 15–17, 2019) where
        congestion is minimal and cold-start effects are the dominant
        cost driver.

        If the day-by-day cost is > 2% higher than multi-day, condition
        chaining is likely broken — each day restarts cold.
        """
        from vatic.data.nyiso_loader import NyisoLoader

        # Use 4 days of timeseries (3 simulation + 1 buffer for RUC horizon)
        # Using a shoulder period for moderate load
        start = pd.Timestamp("2019-04-15", tz="utc")
        end = start + pd.Timedelta(days=4)  # need extra day for RUC lookahead
        gen_data, load_data = nyiso_loader.create_timeseries(start, end)

        # --- Multi-day: single 3-day simulation ---
        results_multi = self._run_simulation(
            nyiso_loader, gen_data, load_data,
            datetime.date(2019, 4, 15), num_days=3,
        )
        cost_multi = (
            results_multi["hourly_summary"]["FixedCosts"].sum()
            + results_multi["hourly_summary"]["VariableCosts"].sum()
        )

        # --- Day-by-day: 3 separate 1-day simulations, chained ---
        cost_dayby = 0.0
        prev_cond = None

        for day_offset in range(3):
            day = datetime.date(2019, 4, 15) + datetime.timedelta(days=day_offset)
            day_start = pd.Timestamp(day.isoformat(), tz="utc")
            day_end = day_start + pd.Timedelta(days=2)

            # Slice timeseries for this day
            gen_day = gen_data.loc[
                (gen_data.index >= day_start) & (gen_data.index < day_end)
            ]
            load_day = load_data.loc[
                (load_data.index >= day_start) & (load_data.index < day_end)
            ]

            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                cond_path = tmp.name

            try:
                # Re-create loader with chained initial conditions
                if prev_cond is not None:
                    loader_day = NyisoLoader(
                        init_state_file=prev_cond,
                        pgscen_dir=str(
                            '/Users/val/Desktop/Princeton/PGscen-2nd/data/NYISO_real'
                        ),
                        use_reduced_network=True,
                        fuel_price_date=day.isoformat(),
                        year=2019,
                    )
                else:
                    loader_day = nyiso_loader

                results_day = self._run_simulation(
                    loader_day, gen_day, load_day, day, num_days=1,
                    last_conditions_file=cond_path,
                )
                cost_dayby += (
                    results_day["hourly_summary"]["FixedCosts"].sum()
                    + results_day["hourly_summary"]["VariableCosts"].sum()
                )

                # Clean up previous conditions file
                if prev_cond is not None:
                    os.unlink(prev_cond)
                prev_cond = cond_path

            except Exception:
                if os.path.exists(cond_path):
                    os.unlink(cond_path)
                raise

        # Clean up final conditions file
        if prev_cond and os.path.exists(prev_cond):
            os.unlink(prev_cond)

        # Cost comparison: day-by-day should not be > 2% more expensive
        if cost_multi == 0:
            pytest.skip("Multi-day cost is zero — simulation may not have run")

        rel_diff = abs(cost_dayby - cost_multi) / cost_multi
        assert rel_diff < 0.02, (
            f"Day-by-day cost (${cost_dayby:,.0f}) differs from multi-day "
            f"(${cost_multi:,.0f}) by {rel_diff:.1%}. "
            f"Condition chaining may be broken."
        )
