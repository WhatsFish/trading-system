import unittest
from decimal import Decimal

from trading_system.strategy import ema, trend_signal


class StrategyTests(unittest.TestCase):
    def candles(self, values: list[Decimal]) -> list[dict]:
        return [
            {"close": str(value), "confirmed": True}
            for value in reversed(values)
        ]

    def test_ema_rejects_short_input(self) -> None:
        with self.assertRaises(ValueError):
            ema([Decimal("1")], 2)

    def test_uptrend_buys(self) -> None:
        values = [Decimal("100") + Decimal(i) / 5 for i in range(60)]
        self.assertEqual(trend_signal(self.candles(values)).action, "buy")

    def test_flat_market_holds(self) -> None:
        values = [Decimal("100") for _ in range(60)]
        self.assertEqual(trend_signal(self.candles(values)).action, "hold")


if __name__ == "__main__":
    unittest.main()

