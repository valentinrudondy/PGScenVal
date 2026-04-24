"""Regression test: Path B year-specific import costs.

Verifies that:
1. _compute_path_b_import_costs returns year-specific costs for each year
2. The costs differ from the static defaults in _EXTERNAL_EQUIVALENTS
3. The costs are economically plausible (positive, within bounds)
4. NyisoLoader picks up Path B costs and applies them to generators
"""

import sys
from pathlib import Path

import pytest

# Add Vatic to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Vatic'))

from vatic.data.nyiso_loader import (
    _compute_path_b_import_costs,
    _EXTERNAL_EQUIVALENTS,
    NyisoLoader,
)

YEARS_WITH_DATA = [2020, 2022, 2023]  # years we have cached DA LMP data
STATIC_COSTS = {name: ext['cost'] for name, ext in _EXTERNAL_EQUIVALENTS.items()}


class TestPathBCostComputation:
    """Test the cost computation function directly."""

    @pytest.mark.parametrize("year", YEARS_WITH_DATA)
    def test_returns_costs_for_all_imports(self, year):
        costs = _compute_path_b_import_costs(year)
        assert len(costs) == 4, f"Expected 4 import costs, got {len(costs)}"
        for name in _EXTERNAL_EQUIVALENTS:
            assert name in costs, f"Missing cost for {name}"

    @pytest.mark.parametrize("year", YEARS_WITH_DATA)
    def test_costs_are_positive(self, year):
        costs = _compute_path_b_import_costs(year)
        for name, cost in costs.items():
            assert cost > 0, f"{name} cost is non-positive: {cost}"

    @pytest.mark.parametrize("year", YEARS_WITH_DATA)
    def test_costs_are_plausible(self, year):
        """Import costs should be between $1 and $200/MWh."""
        costs = _compute_path_b_import_costs(year)
        for name, cost in costs.items():
            assert 1 < cost < 200, (
                f"{name} cost ${cost}/MWh is outside plausible range")

    @pytest.mark.parametrize("year", YEARS_WITH_DATA)
    def test_costs_differ_from_static(self, year):
        """Path B costs should differ from the static defaults."""
        costs = _compute_path_b_import_costs(year)
        diffs = sum(1 for name in costs
                    if abs(costs[name] - STATIC_COSTS[name]) > 0.5)
        assert diffs >= 2, (
            f"Expected at least 2 imports to differ from static, got {diffs}")

    def test_2022_hq_much_higher_than_static(self):
        """2022 was a high-gas year; HQ cost should be well above $5."""
        costs = _compute_path_b_import_costs(2022)
        assert costs['HQ_import'] > 20, (
            f"2022 HQ cost ${costs['HQ_import']} should be >$20 (gas spike)")

    def test_missing_year_returns_empty(self):
        """A year without data should return an empty dict."""
        costs = _compute_path_b_import_costs(1999)
        assert costs == {}


class TestPathBInLoader:
    """Test that NyisoLoader applies Path B costs to generators."""

    def test_2022_pjm_cost_is_path_b(self):
        """PJM import cost in 2022 should be ~$65, not $30 (static)."""
        loader = NyisoLoader(use_reduced_network=True, year=2022)
        pjm_gens = [g for g in loader.generators
                    if 'PJM_import' in g.ID]
        assert len(pjm_gens) > 0

        for g in pjm_gens:
            if g.MaxPower > 0:
                cost = g.TotalCostValues[1] / g.MaxPower
                assert cost > 50, (
                    f"{g.ID} cost ${cost:.2f} should be >$50 for 2022")
                assert cost < 80, (
                    f"{g.ID} cost ${cost:.2f} should be <$80 for 2022")

    def test_2022_hq_cost_is_path_b(self):
        """HQ import cost in 2022 should be ~$38, not $5 (static)."""
        loader = NyisoLoader(use_reduced_network=True, year=2022)
        hq_gens = [g for g in loader.generators
                   if 'HQ_import' in g.ID]
        assert len(hq_gens) > 0

        for g in hq_gens:
            if g.MaxPower > 0:
                cost = g.TotalCostValues[1] / g.MaxPower
                assert cost > 25, (
                    f"{g.ID} cost ${cost:.2f} should be >$25 for 2022")

    def test_total_import_capacity_unchanged(self):
        """Path B changes costs, not capacity — totals must be preserved."""
        for year in YEARS_WITH_DATA:
            loader = NyisoLoader(use_reduced_network=True, year=year)
            import_gens = [g for g in loader.generators
                           if g.UnitType == 'Import']
            total = sum(g.MaxPower for g in import_gens)
            expected = sum(ext['pmax']
                           for ext in _EXTERNAL_EQUIVALENTS.values())
            assert abs(total - expected) < 1, (
                f"{year}: total import capacity {total} != {expected}")
