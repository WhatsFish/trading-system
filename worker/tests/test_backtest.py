import unittest
from decimal import Decimal

from trading_system.backtest import run


class BacktestTests(unittest.TestCase):
    def test_requires_meaningful_history(self) -> None:
        with self.assertRaises(ValueError):
            run([Decimal("1")] * 20, Decimal("0.001"))

    def test_reports_bounded_result(self) -> None:
        prices = [Decimal("100") + Decimal(i) / 10 for i in range(150)]
        result = run(prices, Decimal("0.001"))
        self.assertGreaterEqual(result.trades, 1)
        self.assertGreater(result.return_pct, Decimal("-100"))
        self.assertGreaterEqual(result.max_drawdown_pct, Decimal("0"))


if __name__ == "__main__":
    unittest.main()
