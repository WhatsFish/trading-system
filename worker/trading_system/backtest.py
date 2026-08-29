import argparse
from dataclasses import dataclass
from decimal import Decimal

import datetime as dt

from .strategy import equity_signal


@dataclass
class Result:
    trades: int
    return_pct: Decimal
    max_drawdown_pct: Decimal


def run(
    closes: list[Decimal],
    fee_rate: Decimal,
    timestamps: list[dt.datetime] | None = None,
) -> Result:
    if len(closes) < 120:
        raise ValueError("at least 120 candles are required")
    if timestamps is not None and len(timestamps) != len(closes):
        raise ValueError("timestamps and closes must have equal length")
    equity = Decimal("1")
    peak = equity
    max_drawdown = Decimal("0")
    position = 0
    trades = 0
    candles: list[dict] = []

    for index, close in enumerate(closes):
        timestamp = (
            timestamps[index]
            if timestamps is not None
            else dt.datetime(2026, 8, 24, 14, 0, tzinfo=dt.timezone.utc)
            + dt.timedelta(minutes=5 * index)
        )
        candles.insert(
            0,
            {
                "close": str(close),
                "confirmed": True,
                "ts": int(timestamp.timestamp() * 1000),
            },
        )
        if len(candles) < 60:
            continue
        signal_result = equity_signal(candles[:100], timestamp)
        target = (
            1
            if signal_result.action == "buy"
            else 0
            if signal_result.action == "sell"
            else position
        )
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
            SELECT ts, close FROM market_candle
            WHERE instrument = %s AND bar = '5m' AND confirmed
            ORDER BY ts
            """,
            (args.instrument,),
        ).fetchall()
    result = run(
        [Decimal(row[1]) for row in rows],
        args.fee_rate,
        [row[0] for row in rows],
    )
    print(
        f"trades={result.trades} return={result.return_pct:.2f}% "
        f"max_drawdown={result.max_drawdown_pct:.2f}%"
    )


if __name__ == "__main__":
    main()
