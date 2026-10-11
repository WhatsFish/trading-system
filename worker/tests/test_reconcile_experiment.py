import datetime as dt
from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch

from trading_system.reconcile_experiment import reconcile, validate_evidence


class ReconcileExperimentTests(unittest.TestCase):
    def setUp(self):
        self.opened = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
        self.closed = self.opened + dt.timedelta(days=1)
        self.experiment = {
            "id": 5, "instrument": "JNJ-USDT-SWAP",
            "entry_order_id": "entry1", "entry_client_order_id": "buy1",
            "entry_time": self.opened, "next_entry_time": self.closed + dt.timedelta(days=1),
            "entry_quantity": Decimal(".01"), "entry_price": Decimal("100"),
            "entry_fee": Decimal(".001"),
        }
        self.entry = {
            "instId": "JNJ-USDT-SWAP", "ordId": "entry1", "clOrdId": "buy1",
            "side": "buy", "posSide": "long", "state": "filled", "accFillSz": ".01",
            "avgPx": "100", "fee": "-.001", "feeCcy": "USDT",
            "fillTime": str(int(self.opened.timestamp() * 1000)),
        }
        self.exit = {
            **self.entry, "ordId": "exit1", "clOrdId": "sell1", "side": "sell",
            "avgPx": "110", "reduceOnly": "true",
            "fillTime": str(int(self.closed.timestamp() * 1000)),
        }
        self.audit = {"exchange_order_id": "exit1", "client_order_id": "sell1", "requested_size": Decimal(".01")}
        self.db = MagicMock()
        self.conn = self.db.connect.return_value.__enter__.return_value
        self.client = MagicMock()
        self.client.order.side_effect = [self.entry, self.exit]
        self.row = (
            5, self.experiment["instrument"], "entry1", "buy1", self.opened,
            Decimal(".01"), Decimal("100"), Decimal(".001"),
            self.experiment["next_entry_time"], "open", False,
        )

        def execute(sql, params=None):
            result = MagicMock()
            if "pg_try_advisory_lock" in sql:
                result.fetchone.return_value = (True,)
            elif "FROM live_experiment e WHERE" in sql:
                result.fetchone.return_value = self.row
            elif "FROM execution_audit" in sql:
                result.fetchall.return_value = [("exit1", "sell1", Decimal(".01"))]
            elif "SELECT EXISTS" in sql:
                result.fetchone.return_value = (False,)
            elif "SELECT status, exit_order_id" in sql:
                result.fetchone.return_value = ("closed", "exit1", Decimal(".098"))
            return result

        self.conn.execute.side_effect = execute

    def test_exact_full_exit_evidence(self):
        result = validate_evidence(self.experiment, self.entry, self.exit, self.audit)
        self.assertEqual(Decimal(result["netPnlExcludingFundingUsdt"]), Decimal(".098"))
        self.assertEqual(Decimal(result["returnPctExcludingFunding"]), Decimal("9.8"))

    def test_rejects_wrong_identity_partial_fees_and_invalid_numbers(self):
        for change in (
            {"instId": "KLAC-USDT-SWAP"}, {"ordId": "other"}, {"clOrdId": "other"},
            {"side": "buy"}, {"posSide": "short"}, {"state": "live"},
            {"reduceOnly": "false"}, {"feeCcy": "BTC"}, {"fee": ".001"},
            {"accFillSz": ".005"}, {"accFillSz": ".02"},
            {"avgPx": "NaN"}, {"avgPx": "Infinity"}, {"avgPx": "0"},
            {"fee": "NaN"}, {"fillTime": "0"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_evidence(self.experiment, self.entry, {**self.exit, **change}, self.audit)

    def test_rejects_newer_trade_exit_and_mismatched_entry(self):
        for key, value in (
            ("entry_price", Decimal("101")), ("entry_fee", Decimal(".002")),
            ("entry_time", self.opened - dt.timedelta(days=1)),
            ("next_entry_time", self.closed),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_evidence({**self.experiment, key: value}, self.entry, self.exit, self.audit)

    @patch("trading_system.reconcile_experiment.finalize_experiment")
    def test_default_dry_run_never_writes_ledger_or_exchange(self, finalize):
        result = reconcile(self.db, self.client, 5, "exit1")
        self.assertFalse(result["applied"])
        finalize.assert_not_called()
        self.assertEqual([call[0] for call in self.client.method_calls], ["order", "order"])
        self.assertFalse(any(
            word in call.args[0].upper()
            for call in self.conn.execute.call_args_list
            for word in ("UPDATE ", "INSERT ", "DELETE ")
        ))

    @patch("trading_system.reconcile_experiment.finalize_experiment")
    def test_apply_finalizes_exact_id_and_verifies(self, finalize):
        result = reconcile(self.db, self.client, 5, "exit1", apply=True)
        self.assertTrue(result["applied"])
        self.assertEqual(finalize.call_args.kwargs, {"experiment_id": 5})
        self.assertIn("pg_advisory_unlock", self.conn.execute.call_args.args[0])
        self.assertEqual([call[0] for call in self.client.method_calls], ["order", "order"])

    @patch("trading_system.reconcile_experiment.finalize_experiment")
    def test_current_or_closed_experiment_cannot_be_repaired(self, finalize):
        for status, owned in (("open", True), ("closed", False)):
            self.row = (*self.row[:9], status, owned)
            with self.subTest(status=status, owned=owned), self.assertRaises(ValueError):
                reconcile(self.db, self.client, 5, "exit1", apply=True)
        finalize.assert_not_called()
        self.client.order.assert_not_called()

    @patch("trading_system.reconcile_experiment.finalize_experiment")
    def test_conflicting_fill_blocks_apply(self, finalize):
        original = self.conn.execute.side_effect

        def execute(sql, params=None):
            result = original(sql, params)
            if "SELECT EXISTS" in sql:
                result.fetchone.return_value = (True,)
            return result

        self.conn.execute.side_effect = execute
        with self.assertRaisesRegex(ValueError, "attributed elsewhere"):
            reconcile(self.db, self.client, 5, "exit1", apply=True)
        finalize.assert_not_called()

    def test_busy_controller_prevents_repair(self):
        self.conn.execute.side_effect = None
        self.conn.execute.return_value.fetchone.return_value = (False,)
        with self.assertRaisesRegex(RuntimeError, "controller is busy"):
            reconcile(self.db, self.client, 5, "exit1", apply=True)
        self.client.order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
