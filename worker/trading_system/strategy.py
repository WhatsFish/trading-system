from dataclasses import dataclass
from decimal import Decimal


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

