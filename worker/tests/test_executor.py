import unittest
from decimal import Decimal

from trading_system.config import Settings
from trading_system.executor import OrderIntent, floor_step, validate_intent


class ExecutorTests(unittest.TestCase):
    def settings(self, mode: str = "observe") -> Settings:
        return Settings(
            "k", "s", "p", "db", mode,
            "I_UNDERSTAND_LIVE_TRADING_RISK" if mode == "live" else "",
            ("GOOGL-USDT-SWAP",), 60,
        )

    def intent(self, **changes) -> OrderIntent:
        values = {
            "instrument": "GOOGL-USDT-SWAP",
            "action": "buy",
            "size": Decimal("0.01"),
            "price": Decimal("200"),
            "reduce_only": False,
            "client_order_id": "test1",
            "risk_decision_id": 1,
            "order_type": "limit",
            "stop_trigger_price": Decimal("190"),
            "stop_client_order_id": "stoptest1",
        }
        values.update(changes)
        return OrderIntent(**values)

    def test_rounds_down_to_tick(self) -> None:
        self.assertEqual(floor_step(Decimal("1.239"), Decimal("0.01")), Decimal("1.23"))

    def test_locked_mode_rejects_order(self) -> None:
        with self.assertRaises(PermissionError):
            validate_intent(
                self.intent(), self.settings(), False,
                Decimal("200"), Decimal("0.01"), Decimal("0.01"), Decimal("5"),
            )

    def test_notional_cap_is_hard(self) -> None:
        with self.assertRaises(ValueError):
            validate_intent(
                self.intent(size=Decimal("0.03")), self.settings("live"), True,
                Decimal("200"), Decimal("0.01"), Decimal("0.01"), Decimal("5"),
            )

    def test_short_opening_is_disabled(self) -> None:
        with self.assertRaises(ValueError):
            validate_intent(
                self.intent(action="sell"), self.settings("live"), True,
                Decimal("200"), Decimal("0.01"), Decimal("0.01"),
            )

    def test_invalid_client_order_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_intent(
                self.intent(client_order_id="bad-id"), self.settings("live"), True,
                Decimal("200"), Decimal("0.01"), Decimal("0.01"),
            )

    def test_bounded_long_can_pass_all_gates(self) -> None:
        validate_intent(
            self.intent(), self.settings("live"), True,
            Decimal("200"), Decimal("0.01"), Decimal("0.01"), Decimal("5"),
        )

    def test_ioc_price_ceiling_enforces_entry_cap(self) -> None:
        validate_intent(
            self.intent(price=Decimal("201"), order_type="ioc"),
            self.settings("live"),
            True,
            Decimal("200"),
            Decimal("0.01"),
            Decimal("0.01"),
            Decimal("5"),
        )

    def test_reduce_only_exit_can_close_appreciated_position(self) -> None:
        validate_intent(
            self.intent(
                action="sell",
                size=Decimal("0.10"),
                price=None,
                reduce_only=True,
                order_type="market",
                stop_trigger_price=None,
                stop_client_order_id=None,
            ),
            self.settings("live"),
            True,
            Decimal("300"),
            Decimal("0.01"),
            Decimal("0.01"),
        )

    def test_kill_switch_never_blocks_reduce_only_exit(self) -> None:
        validate_intent(
            self.intent(
                action="sell",
                price=None,
                reduce_only=True,
                order_type="market",
                stop_trigger_price=None,
                stop_client_order_id=None,
            ),
            self.settings("live"),
            False,
            Decimal("200"),
            Decimal("0.01"),
            Decimal("0.01"),
        )


if __name__ == "__main__":
    unittest.main()
