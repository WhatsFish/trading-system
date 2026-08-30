import unittest
import datetime as dt
from collections import Counter
from decimal import Decimal

from trading_system.live_controller import (
    desired_action,
    portfolio_candidate_allowed,
    replacement_allowed,
)


class LiveControllerTests(unittest.TestCase):
    def test_enters_only_without_existing_position(self) -> None:
        self.assertEqual(desired_action(1, False, False), "buy")
        self.assertEqual(desired_action(1, True, False), "hold")

    def test_exits_only_managed_position(self) -> None:
        self.assertEqual(desired_action(0, True, True), "sell")
        self.assertEqual(desired_action(0, True, False), "hold")

    def test_never_reenters_recorded_managed_position(self) -> None:
        self.assertEqual(desired_action(1, False, True), "hold")

    def test_portfolio_caps_symbol_cluster_and_group(self) -> None:
        candidate = {
            "symbol": "NVDA",
            "cluster": "slow-trend",
        }
        self.assertTrue(
            portfolio_candidate_allowed(candidate, set(), Counter(), Counter())
        )
        self.assertFalse(
            portfolio_candidate_allowed(candidate, {"NVDA"}, Counter(), Counter())
        )
        self.assertFalse(
            portfolio_candidate_allowed(
                candidate, set(), Counter({"slow-trend": 2}), Counter()
            )
        )
        self.assertFalse(
            portfolio_candidate_allowed(
                candidate, set(), Counter(), Counter({"semiconductor": 2})
            )
        )

    def test_replacement_requires_age_and_score_hysteresis(self) -> None:
        now = dt.datetime(2026, 8, 30, tzinfo=dt.timezone.utc)
        old = now - dt.timedelta(days=2)
        recent = now - dt.timedelta(hours=12)
        self.assertTrue(
            replacement_allowed(Decimal("30"), Decimal("20"), old, now)
        )
        self.assertFalse(
            replacement_allowed(Decimal("29.9"), Decimal("20"), old, now)
        )
        self.assertFalse(
            replacement_allowed(Decimal("40"), Decimal("20"), recent, now)
        )


if __name__ == "__main__":
    unittest.main()
