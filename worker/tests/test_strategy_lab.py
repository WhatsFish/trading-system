import unittest
from decimal import Decimal

from trading_system.strategy_lab import parameter_grid, parameter_targets


class StrategyLabTests(unittest.TestCase):
    def test_grid_is_bounded_and_diverse(self) -> None:
        grid = parameter_grid()
        self.assertGreaterEqual(len(grid), 25)
        self.assertLessEqual(len(grid), 50)
        self.assertEqual({family for family, _ in grid}, {"trend", "breakout", "mean-reversion"})

    def test_trend_detects_sustained_rise(self) -> None:
        closes = [Decimal(100 + index) for index in range(200)]
        targets = parameter_targets(closes, "trend", {"fast": 10, "slow": 50})
        self.assertEqual(targets[-1], 1)

    def test_unknown_family_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            parameter_targets([Decimal("1")] * 200, "unknown", {})


if __name__ == "__main__":
    unittest.main()
