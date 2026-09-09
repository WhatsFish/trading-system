"""Versioned notional ceilings, independent of strategy and execution gates."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .universe import BY_INSTRUMENT


DEFAULT_CONFIG = {
    "maxHoldings": 5,
    "maxPerAssetGroup": 2,
    "maxPerStrategyCluster": 2,
    "totalBudgetMode": "legacy_equity",
    "totalBudgetUsdt": 0,
    "positionBudgetMode": "percent",
    "positionBudgetValue": 18,
    "cashReserveUsdt": 0,
    "instrumentBudgets": {},
}
ZERO = Decimal("0")


def amount(value, name: str, maximum: str = "1000000000") -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name}: numeric value required")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"{name}: invalid number") from error
    if not result.is_finite() or not ZERO <= result <= Decimal(maximum):
        raise ValueError(f"{name}: out of range")
    return result


def metric(value, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as error:
        raise ValueError(f"{name}: invalid account metric") from error
    if not result.is_finite():
        raise ValueError(f"{name}: non-finite account metric")
    return result


@dataclass(frozen=True)
class PortfolioSettings:
    revision: int
    max_holdings: int
    total_mode: str
    total_usdt: Decimal
    position_mode: str
    position_value: Decimal
    reserve: Decimal
    overrides: dict[str, tuple[str, Decimal]]
    max_per_asset_group: int = 2
    max_per_strategy_cluster: int = 2

    @classmethod
    def parse(cls, config: dict, revision: int = 0) -> "PortfolioSettings":
        if type(revision) is not int or revision < 0:
            raise ValueError("invalid portfolio revision")
        if not isinstance(config, dict) or set(config) != set(DEFAULT_CONFIG):
            raise ValueError("invalid portfolio configuration fields")
        count = config["maxHoldings"]
        if type(count) is not int or not 1 <= count <= 50:
            raise ValueError("maxHoldings must be an integer from 1 to 50")
        for name in ("maxPerAssetGroup", "maxPerStrategyCluster"):
            if type(config[name]) is not int or not 1 <= config[name] <= 50:
                raise ValueError(f"{name} must be an integer from 1 to 50")
        mode = config["totalBudgetMode"]
        if mode not in ("legacy_equity", "account_equity", "fixed_usdt"):
            raise ValueError("invalid total budget mode")
        total = amount(config["totalBudgetUsdt"], "totalBudgetUsdt")
        reserve = amount(config["cashReserveUsdt"], "cashReserveUsdt")
        if (mode == "fixed_usdt" and (total <= 0 or reserve >= total)) or (
            mode != "fixed_usdt" and total != 0
        ):
            raise ValueError("fixed budget must exceed reserve; other modes require total=0")

        def budget(mode, value):
            if mode not in ("percent", "fixed_usdt"):
                raise ValueError("invalid position budget mode")
            value = amount(value, "position budget", "100" if mode == "percent" else "1000000000")
            if value <= 0:
                raise ValueError("position budget must be positive")
            return mode, value

        position_mode, position_value = budget(
            config["positionBudgetMode"], config["positionBudgetValue"]
        )
        overrides = config["instrumentBudgets"]
        if not isinstance(overrides, dict) or len(overrides) > 50:
            raise ValueError("invalid instrument budgets")
        parsed = {}
        for instrument, entry in overrides.items():
            if instrument not in BY_INSTRUMENT or not isinstance(entry, dict) or set(entry) != {"mode", "value"}:
                raise ValueError("invalid instrument budget")
            parsed[instrument] = budget(entry["mode"], entry["value"])
        return cls(revision, count, mode, total, position_mode, position_value, reserve, parsed,
                   config["maxPerAssetGroup"], config["maxPerStrategyCluster"])

    def limits(self, equity: Decimal, legacy_total: Decimal = Decimal("2")) -> tuple[Decimal, Decimal]:
        base = min(equity, self.total_usdt) if self.total_mode == "fixed_usdt" else equity
        total = equity * legacy_total if self.total_mode == "legacy_equity" else base
        return max(ZERO, base), max(ZERO, min(total, equity * legacy_total) - self.reserve)

    def symbol_limit(self, instrument: str, equity: Decimal, legacy_single: Decimal = Decimal(".18")) -> Decimal:
        base, _ = self.limits(equity)
        mode, value = self.overrides.get(instrument, (self.position_mode, self.position_value))
        cap = base * value / 100 if mode == "percent" else value
        return max(ZERO, min(cap, equity * legacy_single if self.revision == 0 else base))


def load_portfolio(connection) -> PortfolioSettings:
    if not connection.execute("SELECT to_regclass('portfolio_settings')").fetchone()[0]:
        return PortfolioSettings.parse(DEFAULT_CONFIG)
    row = connection.execute("SELECT revision, config FROM portfolio_settings WHERE id = 1").fetchone()
    if not row:
        raise ValueError("portfolio settings singleton is missing")
    return PortfolioSettings.parse(row[1], row[0])


@dataclass(frozen=True)
class PortfolioAccount:
    equity: Decimal
    available: Decimal
    exposures: dict[str, Decimal]
    held: frozenset[str]
    pending: bool = False

    @classmethod
    def from_exchange(cls, account: dict, positions: list[dict], managed=(), pending=False):
        equity = metric(account.get("totalEq"), "equity")
        usdt = next((row for row in account.get("details", []) if row.get("ccy") == "USDT"), {})
        available = metric(usdt.get("availBal"), "available USDT")
        exposures: dict[str, Decimal] = {}
        for row in positions:
            if metric(row.get("pos"), "position size") != 0:
                instrument = row["instId"]
                exposures[instrument] = exposures.get(instrument, ZERO) + abs(metric(row.get("notionalUsd"), "position notional"))
        managed = frozenset(managed)
        return cls(equity, available, exposures, frozenset(exposures) | managed,
                   pending or bool(managed - exposures.keys()))

    def entry_limit(self, config: PortfolioSettings, instrument: str, legacy_single=Decimal(".18"), legacy_total=Decimal("2"), replacement=False):
        reasons = []
        _, total = config.limits(self.equity, legacy_total)
        exposure = sum(self.exposures.values(), ZERO)
        if self.pending:
            reasons.append("portfolio_pending_entry")
        if len(self.held) > config.max_holdings or (not replacement and len(self.held) >= config.max_holdings):
            reasons.append("portfolio_holdings_limit")
        if instrument in self.held:
            reasons.append("portfolio_instrument_already_held")
        if exposure > total:
            reasons.append("portfolio_total_over_budget")
        # Legacy unsaved settings retain the old appreciation/replacement behavior.
        if config.revision > 0 and any(
            value > config.symbol_limit(symbol, self.equity, legacy_single)
            for symbol, value in self.exposures.items()
        ):
            reasons.append("portfolio_existing_position_over_budget")
        limit = max(ZERO, min(
            config.symbol_limit(instrument, self.equity, legacy_single),
            total - exposure,
            self.available - config.reserve,
        ))
        if limit <= 0:
            reasons.append("portfolio_no_deployable_cash")
        return limit, tuple(reasons)


def pending_entries(connection, exclude_client_id: str = "") -> bool:
    return bool(connection.execute(
        """SELECT EXISTS (
          SELECT 1 FROM execution_audit WHERE action = 'buy'
          AND state NOT IN ('filled', 'canceled', 'order_failed')
          AND client_order_id <> %s)""",
        (exclude_client_id,),
    ).fetchone()[0])
