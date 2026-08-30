from dataclasses import dataclass
from decimal import Decimal

from .config import Settings
from .strategy import Signal


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    proposed_notional: Decimal
    reasons: tuple[str, ...]
    limits: dict[str, str]


def evaluate(
    settings: Settings,
    signal: Signal,
    equity: Decimal,
    total_exposure: Decimal,
    instrument_rule_type: str,
    instrument_state: str,
    execution_enabled: bool,
    daily_pnl: Decimal = Decimal("0"),
    peak_equity: Decimal | None = None,
    reference_stale: bool = True,
    basis_bps: Decimal | None = None,
    event_risk: bool = False,
) -> RiskDecision:
    reasons: list[str] = []
    is_entry = signal.action == "buy"
    proposed = (
        max(Decimal("0"), equity * settings.max_position_pct)
        if is_entry
        else Decimal("0")
    )
    peak = peak_equity or equity
    drawdown = (peak - equity) / peak if peak > 0 else Decimal("1")

    if settings.mode != "live":
        reasons.append("mode_is_observe")
    if settings.live_ack != "I_UNDERSTAND_LIVE_TRADING_RISK":
        reasons.append("live_ack_missing")
    if is_entry and not execution_enabled:
        reasons.append("database_execution_gate_disabled")
    if signal.action == "hold":
        reasons.append("signal_is_hold")
    if instrument_state != "live":
        reasons.append("instrument_not_live")
    if instrument_rule_type != "normal":
        reasons.append("non_normal_instrument_blocked")
    if is_entry and reference_stale:
        reasons.append("underlying_reference_stale")
    if is_entry and basis_bps is None:
        reasons.append("underlying_basis_missing")
    elif is_entry and abs(basis_bps) > settings.max_basis_bps:
        reasons.append("underlying_basis_too_wide")
    if is_entry and event_risk:
        reasons.append("corporate_event_window")
    if equity <= 0:
        reasons.append("no_equity")
    if is_entry and total_exposure + proposed > equity * settings.max_total_exposure_pct:
        reasons.append("total_exposure_limit")
    if is_entry and daily_pnl <= -(peak * settings.daily_loss_pct):
        reasons.append("daily_loss_circuit_breaker")
    if is_entry and drawdown >= settings.max_drawdown_pct:
        reasons.append("max_drawdown_circuit_breaker")

    return RiskDecision(
        approved=not reasons,
        proposed_notional=proposed,
        reasons=tuple(reasons),
        limits={
            "maxPositionPct": str(settings.max_position_pct),
            "maxTotalExposurePct": str(settings.max_total_exposure_pct),
            "maxLeverage": str(settings.max_leverage),
            "dailyLossPct": str(settings.daily_loss_pct),
            "maxDrawdownPct": str(settings.max_drawdown_pct),
            "maxBasisBps": str(settings.max_basis_bps),
        },
    )
