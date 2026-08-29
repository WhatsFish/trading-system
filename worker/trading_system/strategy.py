from dataclasses import dataclass
import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Signal:
    action: str
    confidence: Decimal
    reference_price: Decimal
    features: dict[str, str | float]
    rationale: str


def ema(values: list[Decimal], period: int) -> Decimal:
    if len(values) < period:
        raise ValueError("not enough values")
    multiplier = Decimal(2) / Decimal(period + 1)
    result = sum(values[:period]) / Decimal(period)
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return result


def trend_signal(candles: list[dict]) -> Signal:
    completed = [row for row in reversed(candles) if row["confirmed"]]
    closes = [Decimal(row["close"]) for row in completed]
    if len(closes) < 55:
        raise ValueError("at least 55 completed candles are required")

    fast = ema(closes, 12)
    slow = ema(closes, 26)
    current = closes[-1]
    momentum = current / closes[-13] - 1
    trend_gap = fast / slow - 1
    strength = min(
        Decimal("1"),
        (abs(trend_gap) * Decimal("100") + abs(momentum) * Decimal("20")),
    )

    if trend_gap > Decimal("0.0015") and momentum > Decimal("0.002"):
        action = "buy"
        rationale = "Fast trend is above slow trend with positive one-hour momentum."
    elif trend_gap < Decimal("-0.0015") and momentum < Decimal("-0.002"):
        action = "sell"
        rationale = "Fast trend is below slow trend with negative one-hour momentum."
    else:
        action = "hold"
        rationale = "Trend and momentum do not agree strongly enough."

    return Signal(
        action=action,
        confidence=max(Decimal("0.25"), strength),
        reference_price=current,
        features={
            "ema12": str(fast),
            "ema26": str(slow),
            "trendGapPct": float(trend_gap * 100),
            "momentum1hPct": float(momentum * 100),
        },
        rationale=rationale,
    )


def us_equity_session(as_of: dt.datetime) -> str:
    eastern = as_of.astimezone(ZoneInfo("America/New_York"))
    if eastern.weekday() >= 5:
        return "closed"
    minutes = eastern.hour * 60 + eastern.minute
    if minutes < 9 * 60 + 40:
        return "closed"
    if minutes >= 15 * 60 + 45:
        return "closing"
    return "regular"


def equity_signal(candles: list[dict], as_of: dt.datetime | None = None) -> Signal:
    completed = [row for row in reversed(candles) if row["confirmed"]]
    closes = [Decimal(row["close"]) for row in completed]
    if len(closes) < 60:
        raise ValueError("at least 60 completed candles are required")
    current = closes[-1]
    latest_ms = int(completed[-1].get("ts", 0))
    observed_at = as_of or dt.datetime.fromtimestamp(
        latest_ms / 1000, tz=dt.timezone.utc
    )
    session = us_equity_session(observed_at)

    fast = ema(closes, 20)
    slow = ema(closes, 50)
    momentum = current / closes[-13] - 1
    trend_gap = fast / slow - 1

    if session != "regular":
        return Signal(
            action="sell",
            confidence=Decimal("1"),
            reference_price=current,
            features={
                "session": session,
                "ema20": str(fast),
                "ema50": str(slow),
                "trendGapPct": float(trend_gap * 100),
                "momentum1hPct": float(momentum * 100),
            },
            rationale="US regular session is closed or near closing; hold no overnight exposure.",
        )

    strength = min(
        Decimal("1"),
        abs(trend_gap) * Decimal("125") + abs(momentum) * Decimal("20"),
    )
    if trend_gap > Decimal("0.001") and momentum > Decimal("0.0015"):
        action = "buy"
        rationale = "Regular-session trend and one-hour momentum are both positive."
    elif trend_gap < Decimal("-0.0005") or momentum < Decimal("-0.001"):
        action = "sell"
        rationale = "Regular-session trend or momentum invalidates a long position."
    else:
        action = "hold"
        rationale = "Regular-session evidence is insufficient for a long entry."

    return Signal(
        action=action,
        confidence=max(Decimal("0.25"), strength),
        reference_price=current,
        features={
            "session": session,
            "ema20": str(fast),
            "ema50": str(slow),
            "trendGapPct": float(trend_gap * 100),
            "momentum1hPct": float(momentum * 100),
        },
        rationale=rationale,
    )
