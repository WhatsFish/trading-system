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
            reference_stale=False,
            basis_bps=Decimal("0"),
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
            reference_stale=False,
            basis_bps=Decimal("0"),
        )
        self.assertFalse(decision.approved)
        self.assertIn("non_normal_instrument_blocked", decision.reasons)

    def test_live_trade_can_pass_all_independent_gates(self) -> None:
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
            "normal",
            "live",
            True,
            reference_stale=False,
            basis_bps=Decimal("10"),
            event_risk=False,
        )
        self.assertTrue(decision.approved)

    def test_wide_basis_and_event_block_trade(self) -> None:
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
            "normal",
            "live",
            True,
            reference_stale=False,
            basis_bps=Decimal("150"),
            event_risk=True,
        )
        self.assertFalse(decision.approved)
        self.assertIn("underlying_basis_too_wide", decision.reasons)
        self.assertIn("corporate_event_window", decision.reasons)

    def test_stale_reference_never_blocks_risk_reducing_exit(self) -> None:
        live = replace(
            self.settings,
            mode="live",
            live_ack="I_UNDERSTAND_LIVE_TRADING_RISK",
        )
        exit_signal = replace(self.signal, action="sell")
        decision = evaluate(
            live,
            exit_signal,
            Decimal("20"),
            Decimal("20"),
            "normal",
            "live",
            True,
            daily_pnl=Decimal("-10"),
            peak_equity=Decimal("30"),
            reference_stale=True,
            basis_bps=None,
            event_risk=True,
        )
        self.assertTrue(decision.approved)
        self.assertEqual(decision.proposed_notional, Decimal("0"))


if __name__ == "__main__":
    unittest.main()
