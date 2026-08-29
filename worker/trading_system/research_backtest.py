import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from .config import database_url_from_env
from .universe import ASSETS


@dataclass(frozen=True)
class Result:
    return_pct: Decimal
    drawdown_pct: Decimal
    trades: int


def mean(values: list[Decimal]) -> Decimal:
    return sum(values) / Decimal(len(values))


def targets(closes: list[Decimal], strategy: str) -> list[int]:
    output = [0] * len(closes)
    position = 0
    for index in range(50, len(closes)):
        close = closes[index]
        sma20 = mean(closes[index - 20 : index])
        sma50 = mean(closes[index - 50 : index])
        if strategy == "daily-trend":
            position = int(close > sma20 > sma50)
        elif strategy == "daily-breakout":
            if not position and close > max(closes[index - 20 : index]):
                position = 1
            elif position and close < min(closes[index - 10 : index]):
                position = 0
        elif strategy == "daily-mean-reversion":
            if not position and close < sma20 * Decimal("0.97") and close > sma50:
                position = 1
            elif position and close >= sma20:
                position = 0
        elif strategy == "buy-and-hold":
            position = 1
        else:
            raise ValueError(f"unknown strategy: {strategy}")
        output[index] = position
    return output


def evaluate(
    closes: list[Decimal],
    desired: list[int],
    fee_rate: Decimal = Decimal("0.0005"),
) -> Result:
    if len(closes) != len(desired) or len(closes) < 2:
        raise ValueError("prices and targets must have equal, non-trivial length")
    equity = Decimal("1")
    peak = equity
    drawdown = Decimal("0")
    position = 0
    trades = 0
    for index in range(1, len(closes)):
        if position:
            equity *= closes[index] / closes[index - 1]
        if desired[index] != position:
            equity *= Decimal("1") - fee_rate
            position = desired[index]
            trades += 1
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    return Result((equity - 1) * 100, drawdown * 100, trades)


def walk_forward(
    closes: list[Decimal],
    desired: list[int],
    fee_rate: Decimal = Decimal("0.0005"),
) -> Result:
    if len(closes) < 504:
        raise ValueError("at least two years of daily data are required")
    points = [
        len(closes) // 2,
        len(closes) * 2 // 3,
        len(closes) * 5 // 6,
        len(closes),
    ]
    compounded = Decimal("1")
    max_drawdown = Decimal("0")
    trades = 0
    for start, end in zip(points, points[1:]):
        result = evaluate(
            closes[start - 1 : end],
            desired[start - 1 : end],
            fee_rate,
        )
        compounded *= Decimal("1") + result.return_pct / Decimal("100")
        max_drawdown = max(max_drawdown, result.drawdown_pct)
        trades += result.trades
    return Result((compounded - 1) * 100, max_drawdown, trades)


def main() -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    strategies = (
        "buy-and-hold",
        "daily-trend",
        "daily-breakout",
        "daily-mean-reversion",
    )
    with psycopg.connect(database_url_from_env()) as connection:
        for asset in ASSETS:
            symbol = asset.instrument.split("-", 1)[0]
            rows = connection.execute(
                """
                SELECT date, close FROM underlying_daily
                WHERE symbol = %s ORDER BY date
                """,
                (symbol,),
            ).fetchall()
            if len(rows) < 252 * 2:
                print(f"{symbol}: skipped, only {len(rows)} daily rows")
                continue
            split = len(rows) // 2
            dates = [row[0] for row in rows]
            closes = [Decimal(row[1]) for row in rows]
            for strategy in strategies:
                desired = targets(closes, strategy)
                test_start = split
                result = walk_forward(closes, desired)
                connection.execute(
                    """
                    INSERT INTO backtest_result
                      (symbol, strategy, train_start, train_end, test_start,
                       test_end, test_return_pct, test_drawdown_pct,
                       test_trades, assumptions)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        symbol,
                        strategy,
                        dates[0],
                        dates[split - 1],
                        dates[test_start],
                        dates[-1],
                        result.return_pct,
                        result.drawdown_pct,
                        result.trades,
                        Jsonb(
                            {
                                "split": "50% initial train, 3 expanding out-of-sample windows",
                                "feePerTransition": "0.0005",
                                "slippage": "not modeled",
                                "positioning": "long/flat",
                            }
                        ),
                    ),
                )
                print(
                    f"{symbol} {strategy}: return={result.return_pct:.2f}% "
                    f"drawdown={result.drawdown_pct:.2f}% trades={result.trades}"
                )
        connection.commit()


if __name__ == "__main__":
    main()
