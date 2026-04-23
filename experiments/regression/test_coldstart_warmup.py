"""Test 3: Cold-start / warmup contamination.

Bug class: Cold-start contamination.
When Vatic starts a simulation without warmup, all generators begin in an
arbitrary initial state (typically all offline). The first hours of simulation
show massive load shedding and reserve shortfall as the solver scrambles to
commit units. This "cold-start transient" contaminates results if the first
simulated day is also the analysis day.

Guard: Compare load shedding on a target day when run with vs. without a
warmup day. The warmup version should have dramatically less shedding.
"""

import datetime
import tempfile

import pandas as pd
import pytest


@pytest.mark.slow
class TestColdStartWarmup:
    """Verify that warmup days eliminate cold-start load shedding."""

    def _run_single_day(self, loader, gen_data, load_data, day_date,
                         last_conditions_file=None):
        """Run Vatic for one day and return the results dict."""
        from vatic.engines import Simulator

        sim = Simulator(
            template_data=loader.template,
            gen_data=gen_data,
            load_data=load_data,
            out_dir=None,
            start_date=day_date,
            num_days=1,
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

    def test_warmup_reduces_load_shedding(self, nyiso_loader):
        """Target-day shedding with warmup must be < 10% of cold-start shedding.

        Run 1: July 18 cold (no warmup) — expect significant shedding.
        Run 2: July 17 (warmup) + July 18 (target) — expect near-zero shedding
        on the target day.

        If the warmup doesn't help, either the pipeline is ignoring initial
        conditions or the warmup chain is broken.
        """
        from vatic.data.nyiso_loader import NyisoLoader
        import tempfile
        import os

        pgscen_dir = str(
            nyiso_loader.__class__.__module__  # dummy — we'll reuse the fixture
        )

        # --- Run 1: Cold start on July 18 ---
        start_cold = pd.Timestamp("2019-07-18", tz="utc")
        end_cold = start_cold + pd.Timedelta(days=2)
        gen_cold, load_cold = nyiso_loader.create_timeseries(start_cold, end_cold)

        results_cold = self._run_single_day(
            nyiso_loader, gen_cold, load_cold,
            datetime.date(2019, 7, 18),
        )
        shedding_cold = results_cold["hourly_summary"]["LoadShedding"].sum()

        # --- Run 2: Warmup July 17 + target July 18 ---
        # First run July 17 to generate conditions
        start_warm = pd.Timestamp("2019-07-17", tz="utc")
        end_warm = start_warm + pd.Timedelta(days=2)
        gen_warm, load_warm = nyiso_loader.create_timeseries(start_warm, end_warm)

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            cond_path = tmp.name

        try:
            results_warmup_day = self._run_single_day(
                nyiso_loader, gen_warm, load_warm,
                datetime.date(2019, 7, 17),
                last_conditions_file=cond_path,
            )

            # Now run July 18 using warmup conditions
            # Re-create loader with init_state
            loader2 = NyisoLoader(
                init_state_file=cond_path,
                pgscen_dir=str(
                    nyiso_loader._NyisoLoader__pgscen_dir
                    if hasattr(nyiso_loader, '_NyisoLoader__pgscen_dir')
                    else '/Users/val/Desktop/Princeton/PGscen-2nd/data/NYISO_real'
                ),
                use_reduced_network=True,
                fuel_price_date="2019-07-18",
                year=2019,
            )
            gen_target, load_target = loader2.create_timeseries(
                start_cold, end_cold
            )

            results_target = self._run_single_day(
                loader2, gen_target, load_target,
                datetime.date(2019, 7, 18),
            )
            shedding_target = results_target["hourly_summary"]["LoadShedding"].sum()

        finally:
            import os
            if os.path.exists(cond_path):
                os.unlink(cond_path)

        # If cold-start shedding is near zero, the test is not informative
        if shedding_cold < 1.0:
            pytest.skip(
                f"Cold-start shedding is only {shedding_cold:.1f} MWh — "
                f"no cold-start problem to detect"
            )

        # The warmup target-day shedding must be < 10% of cold-start shedding
        ratio = shedding_target / shedding_cold if shedding_cold > 0 else 0
        assert ratio < 0.10, (
            f"Warmup did not reduce load shedding: cold={shedding_cold:.0f} MWh, "
            f"warmup={shedding_target:.0f} MWh (ratio={ratio:.2f}). "
            f"Initial conditions may not be chained correctly."
        )
