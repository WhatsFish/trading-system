import argparse
from dataclasses import dataclass
from decimal import Decimal

from .strategy import trend_signal


@dataclass
class Result:
    trades: int
    return_pct: Decimal
    max_drawdown_pct: Decimal


def run(closes: list[Decimal], fee_rate: Decimal) -> Result:
    if len(closes) < 120:
        raise ValueError("at least 120 candles are required")
    equity = Decimal("1")
    peak = equity
    max_drawdown = Decimal("0")
    position = 0
    trades = 0
    candles: list[dict] = []

    for index, close in enumerate(closes):
        candles.insert(0, {"close": str(close), "confirmed": True})
        if len(candles) < 55:
            continue
        signal_result = trend_signal(candles[:100])
        target = 1 if signal_result.action == "buy" else 0
        if index > 0 and position:
            equity *= close / closes[index - 1]
        if target != position:
            equity *= Decimal("1") - fee_rate
            trades += 1
            position = target
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return Result(
        trades=trades,
        return_pct=(equity - 1) * 100,
        max_drawdown_pct=max_drawdown * 100,
    )


def main() -> None:
    import psycopg

    parser = argparse.ArgumentParser()
    parser.add_argument("instrument")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--fee-rate", type=Decimal, default=Decimal("0.0005"))
    args = parser.parse_args()
    with psycopg.connect(args.database_url) as connection:
        rows = connection.execute(
            """
            SELECT close FROM market_candle
            WHERE instrument = %s AND bar = '5m' AND confirmed
            ORDER BY ts
            """,
            (args.instrument,),
        ).fetchall()
    result = run([Decimal(row[0]) for row in rows], args.fee_rate)
    print(
        f"trades={result.trades} return={result.return_pct:.2f}% "
        f"max_drawdown={result.max_drawdown_pct:.2f}%"
    )


if __name__ == "__main__":
    main()
