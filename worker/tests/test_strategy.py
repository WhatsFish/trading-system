import datetime as dt
import unittest
from decimal import Decimal

from trading_system.strategy import ema, equity_signal, trend_signal, us_equity_session


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

    def test_equity_strategy_exits_outside_regular_session(self) -> None:
        values = [Decimal("100") + Decimal(i) / 10 for i in range(70)]
        saturday = dt.datetime(2026, 8, 29, 14, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(equity_signal(self.candles(values), saturday).action, "sell")

    def test_equity_strategy_can_buy_during_regular_session(self) -> None:
        values = [Decimal("100") + Decimal(i) / 5 for i in range(70)]
        monday = dt.datetime(2026, 8, 24, 15, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(equity_signal(self.candles(values), monday).action, "buy")

    def test_session_uses_new_york_timezone(self) -> None:
        summer_open = dt.datetime(2026, 8, 24, 14, 0, tzinfo=dt.timezone.utc)
        summer_close = dt.datetime(2026, 8, 24, 20, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(us_equity_session(summer_open), "regular")
        self.assertEqual(us_equity_session(summer_close), "closing")


if __name__ == "__main__":
    unittest.main()
