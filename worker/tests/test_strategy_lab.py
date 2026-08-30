import unittest
import datetime as dt
from decimal import Decimal

from trading_system.strategy_library import (
    StrategySpec,
    generate_targets,
    strategy_specs,
)
from trading_system.strategy_lab import completed_session_cutoff


class StrategyLabTests(unittest.TestCase):
    def test_grid_is_bounded_and_diverse(self) -> None:
        specs = strategy_specs()
        self.assertGreaterEqual(len(specs), 200)
        self.assertGreaterEqual(len({spec.name for spec in specs}), 20)

    def test_trend_detects_sustained_rise(self) -> None:
        bars = [
            {
                "date": __import__("datetime").date(2020, 1, 1)
                + __import__("datetime").timedelta(days=index),
                "open": str(100 + index),
                "high": str(101 + index),
                "low": str(99 + index),
                "close": str(100 + index),
                "volume": "1000",
            }
            for index in range(220)
        ]
        targets = generate_targets(
            bars,
            StrategySpec("sma-trend", "slow-trend", {"fast": 10, "slow": 50}),
            bars,
        )
        self.assertEqual(targets[-1], 1)

    def test_unknown_family_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            generate_targets(
                [
                    {
                        "date": __import__("datetime").date(2020, 1, 1),
                        "open": "1",
                        "high": "1",
                        "low": "1",
                        "close": "1",
                        "volume": "1",
                    }
                ]
                * 3,
                StrategySpec("unknown", "unknown", {}),
            )

    def test_incomplete_us_session_is_excluded(self) -> None:
        before_close = dt.datetime(
            2026, 8, 31, 18, 0, tzinfo=dt.timezone.utc
        )
        after_close = dt.datetime(
            2026, 8, 31, 21, 0, tzinfo=dt.timezone.utc
        )
        self.assertEqual(
            completed_session_cutoff(before_close), dt.date(2026, 8, 30)
        )
        self.assertEqual(
            completed_session_cutoff(after_close), dt.date(2026, 8, 31)
        )


if __name__ == "__main__":
    unittest.main()
