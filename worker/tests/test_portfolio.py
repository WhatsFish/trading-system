import copy
import datetime as dt
import json
import sys
import unittest
import re
from collections import Counter
from pathlib import Path
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_system.config import Settings
from trading_system.executor import Executor, OrderIntent
from trading_system.live_controller import (
    _run_cycle, attempt_entry, bounded_entry_size, portfolio_candidate_allowed, record_decision,
)
from trading_system.portfolio import DEFAULT_CONFIG, PortfolioAccount, PortfolioSettings, load_portfolio
from trading_system.risk import evaluate
from trading_system.strategy import Signal
from trading_system.universe import BY_INSTRUMENT


def config(revision=1, **changes):
    return PortfolioSettings.parse({**copy.deepcopy(DEFAULT_CONFIG), **changes}, revision)


def account(held=0, equity="100", available="100", exposure="2", pending=False):
    symbols = ["SPY", "QQQ", "AAPL", "NVDA", "LLY", "MSFT"][:held]
    exposures = {f"{s}-USDT-SWAP": D(exposure) for s in symbols}
    return PortfolioAccount(D(equity), D(available), exposures, frozenset(exposures), pending)


def settings():
    return Settings("k", "s", "p", "db", "live", "I_UNDERSTAND_LIVE_TRADING_RISK", ("GOOGL-USDT-SWAP",), 60)


class PortfolioTests(unittest.TestCase):
    def test_legacy_compatibility(self):
        c = config(revision=0)
        self.assertEqual(c.max_holdings, 5)
        self.assertEqual(c.limits(D("100")), (D("100"), D("200")))
        self.assertEqual(c.symbol_limit("SPY-USDT-SWAP", D("100")), D("18"))
        self.assertEqual(account().entry_limit(c, "SPY-USDT-SWAP"), (D("18"), ()))

    def test_portal_and_worker_allowlists_match(self):
        source = (Path(__file__).resolve().parents[2] / "web/src/lib/portfolio.ts").read_text()
        array = source.split("export const INSTRUMENTS = [", 1)[1].split("].map", 1)[0]
        symbols = re.findall(r'"([A-Z]+)"', array)
        self.assertEqual({f"{symbol}-USDT-SWAP" for symbol in symbols}, set(BY_INSTRUMENT))

    def test_unapplied_migration_seed_matches_worker_defaults(self):
        source = (Path(__file__).resolve().parents[2] / "db/portfolio-settings.sql").read_text()
        seed = re.search(r"VALUES \(1, 0, '(\{.*?\})', 'migration-default'\)", source, re.S)
        self.assertIsNotNone(seed)
        self.assertEqual(json.loads(seed[1]), DEFAULT_CONFIG)
        self.assertEqual(config(revision=0).max_per_asset_group, 2)
        self.assertEqual(config(revision=0).max_per_strategy_cluster, 2)

    def test_sixth_and_reduction(self):
        self.assertFalse(account(5).entry_limit(config(maxHoldings=6), "GOOGL-USDT-SWAP")[1])
        for count in (4, 5):
            self.assertIn("portfolio_holdings_limit", account(5).entry_limit(config(maxHoldings=count), "GOOGL-USDT-SWAP")[1])
        self.assertIn("portfolio_holdings_limit", account(5).entry_limit(config(maxHoldings=4), "GOOGL-USDT-SWAP", replacement=True)[1])

    def test_fixed_budget_percent_reserve_and_cash(self):
        c = config(totalBudgetMode="fixed_usdt", totalBudgetUsdt=30, cashReserveUsdt=5)
        self.assertEqual(c.limits(D("100")), (D("30"), D("25")))
        self.assertEqual(c.symbol_limit("SPY-USDT-SWAP", D("100")), D("5.4"))
        self.assertEqual(account(1, available="6").entry_limit(c, "GOOGL-USDT-SWAP")[0], D("1"))
        self.assertEqual(config(totalBudgetMode="fixed_usdt", totalBudgetUsdt=300).limits(D("100"))[0], D("100"))

    def test_position_overrides_and_existing_stricter_cap(self):
        c = config(positionBudgetMode="fixed_usdt", positionBudgetValue=50,
                   instrumentBudgets={"SPY-USDT-SWAP": {"mode": "fixed_usdt", "value": 4}})
        self.assertEqual(c.symbol_limit("GOOGL-USDT-SWAP", D("100")), D("50"))
        self.assertEqual(c.symbol_limit("SPY-USDT-SWAP", D("100")), D("4"))
        self.assertIn("portfolio_existing_position_over_budget", account(1, exposure="5").entry_limit(c, "GOOGL-USDT-SWAP", replacement=True)[1])

    def test_sequential_budget_and_pending(self):
        c = config(totalBudgetMode="fixed_usdt", totalBudgetUsdt=30,
                   positionBudgetMode="fixed_usdt", positionBudgetValue=18)
        first, reasons = account().entry_limit(c, "SPY-USDT-SWAP")
        self.assertEqual(first, D("18"))
        second, reasons = account(1, exposure=str(first), available="82").entry_limit(c, "GOOGL-USDT-SWAP")
        self.assertEqual(second, D("12"))
        self.assertLessEqual(first + second, D("30"))
        self.assertIn("portfolio_pending_entry", account(pending=True).entry_limit(c, "SPY-USDT-SWAP")[1])

    def test_invalid_configs_and_account_metrics(self):
        bad = [
            {"maxHoldings": 0}, {"maxHoldings": 51}, {"maxHoldings": True}, {"maxHoldings": 5.5},
            {"cashReserveUsdt": float("nan")}, {"positionBudgetValue": float("inf")},
            {"positionBudgetValue": 101}, {"positionBudgetValue": "18"},
            {"totalBudgetMode": "margin"}, {"cashReserveUsdt": -1},
            {"totalBudgetMode": "fixed_usdt", "totalBudgetUsdt": 30, "cashReserveUsdt": 30},
            {"totalBudgetUsdt": 30}, {"instrumentBudgets": {"BTC-USDT-SWAP": {"mode": "percent", "value": 1}}},
            *[{key: value} for key in ("maxPerAssetGroup", "maxPerStrategyCluster")
              for value in (0, 51, True, 2.5, "3", float("nan"), float("inf"))],
        ]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config(**changes)
        for value in ("NaN", "Infinity", None):
            with self.assertRaises(ValueError):
                PortfolioAccount.from_exchange({"totalEq": value}, [])

    def test_unreconciled_managed_fill_blocks_next_entry(self):
        a = PortfolioAccount.from_exchange(
            {"totalEq": "100", "details": [{"ccy": "USDT", "availBal": "100"}]},
            [], ["SPY-USDT-SWAP"],
        )
        self.assertTrue(a.pending)

    def test_missing_migration_defaults_but_missing_row_fails(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = (None,)
        self.assertEqual(load_portfolio(db).max_holdings, 5)
        db.execute.return_value.fetchone.side_effect = [("portfolio_settings",), None]
        with self.assertRaises(ValueError):
            load_portfolio(db)

    def test_invalid_portfolio_blocks_buy_not_exit(self):
        for action, approved in (("buy", False), ("sell", True)):
            result = evaluate(settings(), Signal(action, D("1"), D("100"), {}, "test"),
                              D("100"), D("0"), "normal", "live", True,
                              reference_stale=False, basis_bps=D("0"), portfolio_error="invalid")
            self.assertEqual(result.approved, approved)

    def test_budget_increase_respects_cash_equity_total_and_legacy(self):
        for c, available, expected in (
            (config(positionBudgetMode="fixed_usdt", positionBudgetValue=30), "100", "30"),
            (config(positionBudgetValue=50), "100", "50"),
            (config(positionBudgetValue=50, cashReserveUsdt=5), "25", "20"),
            (config(positionBudgetMode="fixed_usdt", positionBudgetValue=300), "1000", "100"),
            (config(totalBudgetMode="fixed_usdt", totalBudgetUsdt=25,
                    positionBudgetMode="fixed_usdt", positionBudgetValue=30), "100", "25"),
            (config(revision=0, positionBudgetValue=50), "100", "18"),
        ):
            with self.subTest(c=c, available=available):
                decision = evaluate(
                    settings(), Signal("buy", D("1"), D("100"), {}, "test"),
                    D("100"), D("0"), "normal", "live", True,
                    reference_stale=False, basis_bps=D("0"), portfolio=c,
                    portfolio_account=account(available=available), instrument="GOOGL-USDT-SWAP",
                )
                self.assertTrue(decision.approved)
                self.assertEqual(decision.proposed_notional, D(expected))
        a = PortfolioAccount(D("100"), D("100"), {"SPY-USDT-SWAP": D("190")},
                             frozenset({"SPY-USDT-SWAP"}))
        limit, _ = a.entry_limit(config(positionBudgetValue=50), "GOOGL-USDT-SWAP")
        self.assertEqual(limit, D("10"))

    def test_appreciation_and_equity_decline_freeze_only_confirmed_entries(self):
        for equity, exposure in (("100", "18.01"), ("90", "18")):
            a = account(1, equity=equity, exposure=exposure)
            for replacement in (False, True):
                with self.subTest(equity=equity, replacement=replacement):
                    self.assertIn("portfolio_existing_position_over_budget",
                                  a.entry_limit(config(maxHoldings=6), "GOOGL-USDT-SWAP",
                                                replacement=replacement)[1])
                    self.assertNotIn("portfolio_existing_position_over_budget",
                                     a.entry_limit(config(revision=0), "GOOGL-USDT-SWAP",
                                                   replacement=replacement)[1])
            self.assertFalse(a.entry_limit(config(maxHoldings=6, positionBudgetValue=25),
                                           "GOOGL-USDT-SWAP")[1])
        result = evaluate(settings(), Signal("sell", D("1"), D("100"), {}, "test"),
                          D("90"), D("18"), "normal", "live", False,
                          portfolio=config(), portfolio_account=account(1, equity="90", exposure="18"))
        self.assertTrue(result.approved)

    def test_configurable_diversification_preserves_defaults(self):
        candidate = {"symbol": "GOOGL", "cluster": "trend"}
        for group_cap, cluster_cap, expected in ((2, 2, False), (3, 2, False), (2, 3, False), (3, 3, True)):
            self.assertEqual(portfolio_candidate_allowed(
                candidate, set(), Counter({"trend": 2}), Counter({"technology": 2}),
                config(maxPerAssetGroup=group_cap, maxPerStrategyCluster=cluster_cap),
            ), expected)

    def test_preflight_sizing_rounds_down_and_validates_inputs(self):
        ticker = {"askPx": "100"}
        details = {"tickSz": ".01", "lotSz": ".01", "minSz": ".01"}
        price, size = bounded_entry_size(D("30"), ticker, details)
        self.assertEqual(price, D("100.50"))
        self.assertEqual(size, D(".29"))
        self.assertLessEqual(price * size, D("30"))
        self.assertEqual(bounded_entry_size(D(".01"), ticker, details)[1], D("0"))
        for value in ("0", "-1", "NaN", "Infinity"):
            with self.assertRaises(ValueError):
                bounded_entry_size(D(value), ticker, details)
            for key in details:
                with self.assertRaises(ValueError):
                    bounded_entry_size(D("30"), ticker, {**details, key: value})


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.connection = self.db.connect.return_value.__enter__.return_value
        self.client = MagicMock()
        self.client.account_balance.return_value = {"totalEq": "100", "details": [{"ccy": "USDT", "availBal": "90"}]}
        self.client.positions.return_value = [
            {"instId": i, "posSide": "long", "pos": "1", "notionalUsd": str(n)}
            for i, n in account(5).exposures.items()
        ]
        self.client.pending_orders.return_value = []
        groups = ["index", "index", "technology", "semiconductor", "healthcare"]
        self.managed = [
            {"instrument": row["instId"], "strategy_cluster": f"cluster-{i}",
             "asset_group": groups[i], "replacement_eligible": True,
             "strategy_parameters": {},
             "entry_score": "1", "opened_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)}
            for i, row in enumerate(self.client.positions.return_value)
        ]
        self.candidate = {"symbol": "GOOGL", "cluster": "new", "family": "sma-trend",
                          "parameters": {}, "score": "40", "current_target": 1}

    def run_controller(self, portfolio, *, invalid=False, real_entry=False, replacement=False):
        # All exchange/DB interactions are mocks; psycopg is not needed locally.
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(Error=RuntimeError)}), \
             patch("trading_system.live_controller.load_portfolio", side_effect=ValueError("bad") if invalid else None, return_value=portfolio) as load, \
             patch("trading_system.live_controller.recover_incomplete_entries", return_value=False), \
             patch("trading_system.live_controller.load_managed_positions", return_value=self.managed,
                   side_effect=[self.managed, self.managed, self.managed[1:], self.managed[1:]] if replacement else None), \
             patch("trading_system.live_controller.load_candidates", return_value=[self.candidate]), \
             patch("trading_system.live_controller.load_replacement_reservation", return_value=None,
                   side_effect=[None, self.candidate] if replacement else None), \
             patch("trading_system.live_controller.pending_entries", return_value=False), \
             patch("trading_system.live_controller.manage_position", return_value="hold") as manage, \
             patch("trading_system.live_controller.attempt_entry",
                   side_effect=attempt_entry if real_entry else [("approved", ()), ("entered", ())] if replacement else None,
                   return_value=("entered", ())) as entry, \
             patch("trading_system.live_controller.close_owned_position") as close:
            _run_cycle(settings(), self.client, self.db, MagicMock())
            self.assertEqual(load.call_count, 1)
            self.assertEqual(manage.call_count, len(self.managed))
            return entry, close

    def test_controller_uses_six_slots_and_one_revision(self):
        c = config(maxHoldings=6)
        entry, close = self.run_controller(c)
        entry.assert_called_once()
        self.assertIs(entry.call_args.kwargs["portfolio"], c)
        close.assert_not_called()

    def test_controller_reduction_and_invalid_still_manage_without_replacement(self):
        for c, invalid in ((config(maxHoldings=4), False), (None, True)):
            with self.subTest(invalid=invalid):
                entry, close = self.run_controller(c, invalid=invalid)
                entry.assert_not_called()
                close.assert_not_called()

    def test_replacement_tiny_override_never_sells_incumbent(self):
        self.client.instrument.return_value = {"tickSz": ".01", "lotSz": ".01", "minSz": ".01",
                                               "ruleType": "normal", "state": "live"}
        self.client.ticker.return_value = {"last": "100", "askPx": "100"}
        self.db.latest_reference_risk.return_value = (False, D("0"), False)
        self.db.save_signal_and_risk.return_value = 7
        with patch("trading_system.live_controller.account_metrics", return_value=(D("100"), D("10"), D("0"), D("100"))):
            entry, close = self.run_controller(config(
                instrumentBudgets={"GOOGL-USDT-SWAP": {"mode": "fixed_usdt", "value": .01}},
            ), real_entry=True)
        entry.assert_called_once()
        self.assertFalse(entry.call_args.kwargs["execute"])
        decision = self.db.save_signal_and_risk.call_args.args[3]
        self.assertTrue(decision.approved)
        self.assertEqual(decision.proposed_notional, D(".01"))
        close.assert_not_called()
        self.client.set_leverage.assert_not_called()
        self.client.place_order.assert_not_called()
        self.assertFalse(any("INSERT INTO replacement_reservation" in call.args[0]
                             for call in self.connection.execute.call_args_list))

    def test_valid_preflight_is_read_only_at_exchange(self):
        self.client.instrument.return_value = {"tickSz": ".01", "lotSz": ".01", "minSz": ".01"}
        self.client.ticker.return_value = {"last": "100", "askPx": "100"}
        executor = MagicMock()
        for authorized, expected in (("30", "approved"), (".01", "below_minimum_size")):
            with patch("trading_system.live_controller.record_decision", return_value=(7, True, (), D(authorized))):
                self.assertEqual(attempt_entry(
                    settings(), self.client, self.db, executor, self.candidate,
                    self.client.account_balance(), self.client.positions(), execute=False,
                    portfolio=config(positionBudgetMode="fixed_usdt", positionBudgetValue=30),
                ), (expected, ()))
        self.client.set_leverage.assert_not_called()
        executor.submit.assert_not_called()

    def test_replacement_preflight_and_reentry_use_configured_diversification_caps(self):
        self.managed[3].update(instrument="MSFT-USDT-SWAP", asset_group="technology", strategy_cluster="new")
        self.managed[2]["strategy_cluster"] = "new"
        self.client.positions.return_value[3]["instId"] = "MSFT-USDT-SWAP"
        entry, close = self.run_controller(config(), replacement=True)
        entry.assert_not_called()
        close.assert_not_called()
        self.connection.reset_mock()
        c = config(maxPerAssetGroup=3, maxPerStrategyCluster=3)
        entry, close = self.run_controller(c, replacement=True)
        self.assertEqual(entry.call_count, 2)
        self.assertFalse(entry.call_args_list[0].kwargs["execute"])
        for call in entry.call_args_list:
            self.assertIs(call.kwargs["portfolio"], c)
        close.assert_called_once()

    def test_controller_can_fill_seventh_eighth_and_ninth_with_explicit_caps(self):
        original = copy.deepcopy(self.managed)
        for count in (7, 8, 9):
            self.managed = copy.deepcopy(original)
            for symbol in ("MSFT", "AMD", "JNJ")[:count - 6]:
                self.managed.append({
                    **original[0], "instrument": f"{symbol}-USDT-SWAP",
                    "asset_group": BY_INSTRUMENT[f"{symbol}-USDT-SWAP"].group,
                    "strategy_cluster": "new",
                })
            self.client.positions.return_value = [
                {"instId": m["instrument"], "posSide": "long", "pos": "1", "notionalUsd": "2"}
                for m in self.managed
            ]
            with self.subTest(count=count):
                entry, close = self.run_controller(config(
                    maxHoldings=count, maxPerAssetGroup=3, maxPerStrategyCluster=4,
                ))
                entry.assert_called_once()
                close.assert_not_called()
        entry, _ = self.run_controller(config(maxHoldings=9))
        entry.assert_not_called()

    def test_controller_appreciation_freeze_does_not_liquidate(self):
        self.client.positions.return_value[0]["notionalUsd"] = "18.01"
        self.client.instrument.return_value = {"ruleType": "normal", "state": "live"}
        self.client.ticker.return_value = {"last": "100"}
        self.db.latest_reference_risk.return_value = (False, D("0"), False)
        with patch("trading_system.live_controller.account_metrics", return_value=(D("100"), D("26.01"), D("0"), D("100"))):
            entry, close = self.run_controller(config(maxHoldings=6), real_entry=True)
        entry.assert_called_once()
        self.assertIn("portfolio_existing_position_over_budget", self.db.save_signal_and_risk.call_args.args[3].reasons)
        close.assert_not_called()
        self.client.set_leverage.assert_not_called()

    def test_record_decision_wires_budget_and_revision(self):
        self.db.latest_reference_risk.return_value = (False, D("0"), False)
        self.db.save_signal_and_risk.return_value = 7
        with patch("trading_system.live_controller.account_metrics", return_value=(D("100"), D("10"), D("0"), D("100"))), \
             patch("trading_system.live_controller.load_managed_positions", return_value=self.managed), \
             patch("trading_system.live_controller.pending_entries", return_value=False):
            result = record_decision(settings(), self.db, "GOOGL-USDT-SWAP", "test", "buy", D("100"), {},
                                     self.client.account_balance(), self.client.positions(),
                                     {"ruleType": "normal", "state": "live"},
                                     portfolio=config(maxHoldings=6, totalBudgetMode="fixed_usdt", totalBudgetUsdt=30))
        self.assertTrue(result[1])
        self.assertEqual(result[3], D("5.4"))
        decision = self.db.save_signal_and_risk.call_args.args[3]
        self.assertEqual(decision.limits["portfolioRevision"], "1")

    def test_attempt_entry_uses_authorized_notional_and_forwards_revision(self):
        c = config(maxHoldings=6)
        self.client.instrument.return_value = {"tickSz": ".01", "lotSz": ".01", "minSz": ".01"}
        self.client.ticker.return_value = {"last": "100", "askPx": "100"}
        executor = MagicMock()
        self.connection.execute.return_value.fetchone.return_value = (D(".05"), D("100"))
        with patch("trading_system.live_controller.record_decision", return_value=(7, True, (), D("5.4"))) as risk, \
             patch("trading_system.live_controller.recover_incomplete_entries", return_value=False), \
             patch("trading_system.live_controller.protection_is_live", return_value=True):
            status, _ = attempt_entry(settings(), self.client, self.db, executor, self.candidate,
                                      self.client.account_balance(), self.client.positions(), portfolio=c)
        self.assertEqual(status, "entered")
        self.assertIs(risk.call_args.kwargs["portfolio"], c)
        intent = executor.submit.call_args.args[0]
        self.assertLessEqual(intent.size * intent.price, D("5.4"))
        self.client.set_leverage.assert_called_once_with("GOOGL-USDT-SWAP", "1")

    def executor_fixture(self, revision="1", authorized=D("18")):
        self.client.instrument.return_value = {"lotSz": ".01", "minSz": ".01"}
        self.client.ticker.return_value = {"last": "100"}
        self.client.place_order.return_value = {"ordId": "test-order"}
        def execute(sql, params=None):
            result = MagicMock()
            if "SELECT exchange_order_id" in sql:
                result.fetchone.return_value = None
            elif "SELECT r.approved" in sql:
                result.fetchone.return_value = (True, "GOOGL-USDT-SWAP", "buy", authorized, {"portfolioRevision": revision})
            elif "SELECT instrument FROM live_position" in sql:
                result.fetchall.return_value = [(i["instrument"],) for i in self.managed]
            return result
        self.connection.execute.side_effect = execute
        return OrderIntent("GOOGL-USDT-SWAP", "buy", D(".05"), D("100"), False,
                           "testbuy", 7, "ioc", D("95"), "teststop")

    def test_executor_revalidates_revision_holdings_pending_and_budget(self):
        for c, revision, pending, allowed in [
            (config(maxHoldings=6), "1", False, True),
            (config(maxHoldings=5), "1", False, False),
            (config(maxHoldings=6), "0", False, False),
            (config(maxHoldings=6, positionBudgetMode="fixed_usdt", positionBudgetValue=4), "1", False, False),
            (config(maxHoldings=6), "1", True, False),
        ]:
            with self.subTest(c=c, revision=revision, pending=pending):
                self.client.place_order.reset_mock()
                intent = self.executor_fixture(revision)
                with patch("trading_system.executor.load_portfolio", return_value=c), \
                     patch("trading_system.executor.pending_entries", return_value=pending):
                    if allowed:
                        self.assertEqual(Executor(settings(), self.client, self.db).submit(intent), "test-order")
                        audit = next(call.args[1][-1] for call in self.connection.execute.call_args_list
                                     if "INSERT INTO execution_audit" in call.args[0])
                        self.assertIn('"portfolioRevision": 1', audit)
                    else:
                        with self.assertRaises(PermissionError):
                            Executor(settings(), self.client, self.db).submit(intent)
                        self.client.place_order.assert_not_called()

    def test_executor_never_waits_on_configuration_writer(self):
        intent = self.executor_fixture()
        self.connection.execute.side_effect = None
        self.connection.execute.return_value.fetchone.return_value = (False,)
        with self.assertRaisesRegex(PermissionError, "update in progress"):
            Executor(settings(), self.client, self.db).submit(intent)
        self.client.place_order.assert_not_called()

    def test_increased_budget_flows_from_risk_through_entry_and_executor(self):
        c = config(maxHoldings=6, totalBudgetMode="account_equity",
                   instrumentBudgets={"GOOGL-USDT-SWAP": {"mode": "fixed_usdt", "value": 30}})
        self.db.latest_reference_risk.return_value = (False, D("0"), False)
        self.db.save_signal_and_risk.return_value = 7
        self.client.instrument.return_value = {"tickSz": ".01", "lotSz": ".01", "minSz": ".01",
                                               "ruleType": "normal", "state": "live"}
        self.client.ticker.return_value = {"last": "100", "askPx": "100"}
        self.connection.execute.return_value.fetchone.return_value = (D(".29"), D("100.50"))
        executor = MagicMock()
        with patch("trading_system.live_controller.account_metrics", return_value=(D("100"), D("10"), D("0"), D("100"))), \
             patch("trading_system.live_controller.load_managed_positions", return_value=self.managed), \
             patch("trading_system.live_controller.pending_entries", return_value=False), \
             patch("trading_system.live_controller.recover_incomplete_entries", return_value=False), \
             patch("trading_system.live_controller.protection_is_live", return_value=True):
            status, _ = attempt_entry(
                settings(), self.client, self.db, executor, self.candidate,
                self.client.account_balance(), self.client.positions(), portfolio=c,
            )
        self.assertEqual(status, "entered")
        decision = self.db.save_signal_and_risk.call_args.args[3]
        self.assertTrue(decision.approved)
        self.assertEqual(decision.proposed_notional, D("30"))
        intent = executor.submit.call_args.args[0]
        self.assertGreater(intent.size * intent.price, D("18"))
        self.assertLessEqual(intent.size * intent.price, D("30"))
        self.executor_fixture(authorized=decision.proposed_notional)
        with patch("trading_system.executor.load_portfolio", return_value=c), \
             patch("trading_system.executor.pending_entries", return_value=False):
            self.assertEqual(Executor(settings(), self.client, self.db).submit(intent), "test-order")
        self.assertEqual(self.client.place_order.call_args.args[0]["tdMode"], "isolated")
        self.client.set_leverage.assert_called_once_with("GOOGL-USDT-SWAP", "1")


if __name__ == "__main__":
    unittest.main()
