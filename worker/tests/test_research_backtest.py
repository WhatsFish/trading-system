import unittest
from decimal import Decimal

from trading_system.research_backtest import evaluate, targets, walk_forward


class ResearchBacktestTests(unittest.TestCase):
    def test_unknown_strategy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            targets([Decimal(i) for i in range(100)], "unknown")

    def test_trend_enters_rising_market(self) -> None:
        prices = [Decimal(100 + i) for i in range(100)]
        self.assertEqual(targets(prices, "daily-trend")[-1], 1)

    def test_fees_are_charged_on_transitions(self) -> None:
        result = evaluate(
            [Decimal("100"), Decimal("100"), Decimal("100")],
            [0, 1, 0],
            Decimal("0.01"),
        )
        self.assertEqual(result.trades, 2)
        self.assertLess(result.return_pct, 0)

    def test_walk_forward_requires_two_years(self) -> None:
        prices = [Decimal("100")] * 503
        with self.assertRaises(ValueError):
            walk_forward(prices, [0] * len(prices))

    def test_buy_and_hold_is_a_visible_benchmark(self) -> None:
        prices = [Decimal(100 + index) for index in range(600)]
        result = walk_forward(prices, targets(prices, "buy-and-hold"))
        self.assertGreater(result.return_pct, 0)
        self.assertEqual(result.trades, 3)


if __name__ == "__main__":
    unittest.main()
