from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .config import database_url_from_env
from .research_backtest import targets

if TYPE_CHECKING:
    import psycopg


CANDIDATES = {
    "GOOGL-USDT-SWAP": "daily-trend",
    "JNJ-USDT-SWAP": "daily-breakout",
    "MRK-USDT-SWAP": "daily-trend",
}
FEE_RATE = Decimal("0.0005")
SLIPPAGE_RATE = Decimal("0.001")
POSITION_FRACTION = Decimal("0.16")
LOT_SIZE = Decimal("0.01")
MAX_BASIS_BPS = Decimal("100")


def floor_lot(value: Decimal) -> Decimal:
    return (value / LOT_SIZE).to_integral_value(rounding=ROUND_DOWN) * LOT_SIZE


def buy_fill(market_price: Decimal) -> Decimal:
    return market_price * (Decimal("1") + SLIPPAGE_RATE)


def sell_fill(market_price: Decimal) -> Decimal:
    return market_price * (Decimal("1") - SLIPPAGE_RATE)


def in_close_window(now: dt.datetime) -> bool:
    eastern = now.astimezone(ZoneInfo("America/New_York"))
    minutes = eastern.hour * 60 + eastern.minute
    return eastern.weekday() < 5 and 16 * 60 <= minutes <= 16 * 60 + 30


def latest_target(
    connection: psycopg.Connection,
    symbol: str,
    strategy: str,
) -> int:
    rows = connection.execute(
        "SELECT date, close FROM underlying_daily WHERE symbol = %s ORDER BY date",
        (symbol,),
    ).fetchall()
    closes = [Decimal(row[1]) for row in rows]
    quote = connection.execute(
        """
        SELECT underlying_quoted_at::date, underlying_price
        FROM basis_snapshot
        WHERE instrument = %s
        ORDER BY ts DESC LIMIT 1
        """,
        (f"{symbol}-USDT-SWAP",),
    ).fetchone()
    if quote and (not rows or quote[0] > rows[-1][0]):
        closes.append(Decimal(quote[1]))
    if len(closes) < 60:
        return 0
    return targets(closes, strategy)[-1]


def mark_equity(connection: psycopg.Connection) -> Decimal:
    account = connection.execute(
        "SELECT cash, realized_pnl FROM shadow_account WHERE id = 1"
    ).fetchone()
    positions = connection.execute(
        """
        SELECT p.quantity, p.average_price, m.last_price
        FROM shadow_position p
        JOIN LATERAL (
          SELECT last_price FROM market_snapshot
          WHERE instrument = p.instrument ORDER BY ts DESC LIMIT 1
        ) m ON TRUE
        """
    ).fetchall()
    market_value = sum(
        (Decimal(quantity) * Decimal(price) for quantity, _, price in positions),
        Decimal("0"),
    )
    unrealized = sum(
        (
            Decimal(quantity) * (Decimal(price) - Decimal(average))
            for quantity, average, price in positions
        ),
        Decimal("0"),
    )
    cash = Decimal(account[0])
    equity = cash + market_value
    connection.execute(
        """
        INSERT INTO shadow_equity_snapshot
          (cash, market_value, equity, realized_pnl, unrealized_pnl)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (cash, market_value, equity, account[1], unrealized),
    )
    return equity


def run(now: dt.datetime | None = None) -> dict:
    import psycopg
    from psycopg.types.json import Jsonb

    current = now or dt.datetime.now(dt.timezone.utc)
    eastern = current.astimezone(ZoneInfo("America/New_York"))
    with psycopg.connect(database_url_from_env()) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(884422)")
        if not in_close_window(current):
            equity = mark_equity(connection)
            connection.commit()
            return {"status": "marked", "equity": str(equity), "trades": 0}

        claimed = connection.execute(
            """
            INSERT INTO shadow_run (market_date, status, detail)
            VALUES (%s, 'running', '{}'::jsonb)
            ON CONFLICT (market_date) DO NOTHING
            RETURNING market_date
            """,
            (eastern.date(),),
        ).fetchone()
        if not claimed:
            equity = mark_equity(connection)
            connection.commit()
            return {"status": "already-ran", "equity": str(equity), "trades": 0}

        account = connection.execute(
            """
            SELECT initial_cash, cash FROM shadow_account
            WHERE id = 1 FOR UPDATE
            """
        ).fetchone()
        initial_cash = Decimal(account[0])
        cash = Decimal(account[1])
        trade_count = 0
        starting_equity = mark_equity(connection)
        peak_equity = Decimal(
            connection.execute(
                "SELECT MAX(equity) FROM shadow_equity_snapshot"
            ).fetchone()[0]
        )
        drawdown_block = (
            peak_equity > 0
            and (peak_equity - starting_equity) / peak_equity >= Decimal("0.05")
        )

        for instrument, strategy in CANDIDATES.items():
            symbol = instrument.split("-", 1)[0]
            target = latest_target(connection, symbol, strategy)
            position = connection.execute(
                """
                SELECT quantity, average_price, entry_fee
                FROM shadow_position WHERE instrument = %s
                """,
                (instrument,),
            ).fetchone()
            market = connection.execute(
                """
                SELECT last_price FROM market_snapshot
                WHERE instrument = %s ORDER BY ts DESC LIMIT 1
                """,
                (instrument,),
            ).fetchone()
            basis = connection.execute(
                """
                SELECT
                  reference_stale
                    OR NOW() - underlying_quoted_at > INTERVAL '20 minutes',
                  basis_bps
                FROM basis_snapshot
                WHERE instrument = %s ORDER BY ts DESC LIMIT 1
                """,
                (instrument,),
            ).fetchone()
            event_risk = connection.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM corporate_event
                  WHERE symbol = %s
                    AND starts_at BETWEEN NOW() - INTERVAL '6 hours'
                                      AND NOW() + INTERVAL '24 hours'
                ) OR EXISTS (
                  SELECT 1 FROM sec_filing
                  WHERE symbol = %s AND filed_at >= CURRENT_DATE - 1
                )
                """,
                (symbol, symbol),
            ).fetchone()[0]
            if not market:
                continue
            market_price = Decimal(market[0])

            if target == 1 and not position:
                if (
                    not basis
                    or basis[0]
                    or abs(Decimal(basis[1])) > MAX_BASIS_BPS
                    or event_risk
                    or drawdown_block
                ):
                    continue
                budget = min(initial_cash * POSITION_FRACTION, cash)
                execution = buy_fill(market_price)
                quantity = floor_lot(
                    budget / (execution * (Decimal("1") + FEE_RATE))
                )
                if quantity <= 0:
                    continue
                notional = quantity * execution
                fee = notional * FEE_RATE
                cash -= notional + fee
                connection.execute(
                    """
                    INSERT INTO shadow_position
                      (instrument, symbol, strategy, quantity, average_price, entry_fee)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (instrument, symbol, strategy, quantity, execution, fee),
                )
                connection.execute(
                    """
                    INSERT INTO shadow_trade
                      (instrument, strategy, side, quantity, market_price,
                       execution_price, fee, reason)
                    VALUES (%s, %s, 'buy', %s, %s, %s, %s, 'daily target long')
                    """,
                    (instrument, strategy, quantity, market_price, execution, fee),
                )
                trade_count += 1
            elif target == 0 and position:
                quantity = Decimal(position[0])
                execution = sell_fill(market_price)
                fee = quantity * execution * FEE_RATE
                proceeds = quantity * execution - fee
                realized = (
                    quantity * (execution - Decimal(position[1]))
                    - Decimal(position[2])
                    - fee
                )
                cash += proceeds
                connection.execute(
                    "DELETE FROM shadow_position WHERE instrument = %s",
                    (instrument,),
                )
                connection.execute(
                    """
                    INSERT INTO shadow_trade
                      (instrument, strategy, side, quantity, market_price,
                       execution_price, fee, realized_pnl, reason)
                    VALUES (%s, %s, 'sell', %s, %s, %s, %s, %s, 'daily target flat')
                    """,
                    (
                        instrument,
                        strategy,
                        quantity,
                        market_price,
                        execution,
                        fee,
                        realized,
                    ),
                )
                connection.execute(
                    """
                    UPDATE shadow_account
                    SET realized_pnl = realized_pnl + %s
                    WHERE id = 1
                    """,
                    (realized,),
                )
                trade_count += 1

        connection.execute(
            "UPDATE shadow_account SET cash = %s, updated_at = NOW() WHERE id = 1",
            (cash,),
        )
        equity = mark_equity(connection)
        detail = {"trades": trade_count, "equity": str(equity)}
        connection.execute(
            """
            UPDATE shadow_run SET status = 'ok', detail = %s
            WHERE market_date = %s
            """,
            (Jsonb(detail), eastern.date()),
        )
        connection.commit()
        return {"status": "ok", **detail}


def main() -> None:
    print(run())


if __name__ == "__main__":
    main()
