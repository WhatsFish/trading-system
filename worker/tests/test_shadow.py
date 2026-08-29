import datetime as dt
import unittest
from decimal import Decimal

from trading_system.shadow import buy_fill, floor_lot, in_close_window, sell_fill


class ShadowTests(unittest.TestCase):
    def test_fills_are_adversarial(self) -> None:
        self.assertGreater(buy_fill(Decimal("100")), Decimal("100"))
        self.assertLess(sell_fill(Decimal("100")), Decimal("100"))

    def test_quantity_is_rounded_down(self) -> None:
        self.assertEqual(floor_lot(Decimal("0.019")), Decimal("0.01"))

    def test_close_window_uses_new_york_dst(self) -> None:
        summer = dt.datetime(2026, 8, 24, 20, 5, tzinfo=dt.timezone.utc)
        winter = dt.datetime(2026, 12, 7, 21, 5, tzinfo=dt.timezone.utc)
        weekend = dt.datetime(2026, 8, 29, 20, 5, tzinfo=dt.timezone.utc)
        self.assertTrue(in_close_window(summer))
        self.assertTrue(in_close_window(winter))
        self.assertFalse(in_close_window(weekend))


if __name__ == "__main__":
    unittest.main()
