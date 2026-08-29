import unittest
from dataclasses import replace
from decimal import Decimal

from trading_system.config import Settings
from trading_system.risk import evaluate
from trading_system.strategy import Signal


class RiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            okx_key="x",
            okx_secret="x",
            okx_passphrase="x",
            database_url="x",
            mode="observe",
            live_ack="",
            instruments=("SPY-USDT-SWAP",),
            poll_seconds=60,
        )
        self.signal = Signal("buy", Decimal("0.8"), Decimal("100"), {}, "trend")

    def test_observe_mode_is_never_approved(self) -> None:
        decision = evaluate(
            self.settings,
            self.signal,
            Decimal("30"),
            Decimal("0"),
            "normal",
            "live",
            False,
        )
        self.assertFalse(decision.approved)
        self.assertIn("mode_is_observe", decision.reasons)

    def test_premarket_is_blocked_even_with_live_gates(self) -> None:
        live = replace(
            self.settings,
            mode="live",
            live_ack="I_UNDERSTAND_LIVE_TRADING_RISK",
        )
        decision = evaluate(
            live,
            self.signal,
            Decimal("30"),
            Decimal("0"),
            "pre_market",
            "live",
            True,
        )
        self.assertFalse(decision.approved)
        self.assertIn("non_normal_instrument_blocked", decision.reasons)


if __name__ == "__main__":
    unittest.main()
