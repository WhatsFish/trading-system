import json
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb


def decimal_or_none(value: str | None) -> Decimal | None:
    return Decimal(value) if value not in (None, "") else None


class Database:
    def __init__(self, url: str) -> None:
        self.url = url

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url)

    def save_candles(self, connection: psycopg.Connection, instrument: str, rows: list[dict]) -> None:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO market_candle
                  (instrument, bar, ts, open, high, low, close, volume, confirmed)
                VALUES (%s, '5m', to_timestamp(%s / 1000.0), %s, %s, %s, %s, %s, %s)
                ON CONFLICT (instrument, bar, ts) DO UPDATE SET
                  open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                  close = EXCLUDED.close, volume = EXCLUDED.volume,
                  confirmed = EXCLUDED.confirmed, ingested_at = NOW()
                """,
                [
                    (
                        instrument,
                        row["ts"],
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        row["volume"],
                        row["confirmed"],
                    )
                    for row in rows
                ],
            )

    def save_market(
        self,
        connection: psycopg.Connection,
        instrument: str,
        ticker: dict,
        details: dict,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO market_snapshot
                  (instrument, last_price, bid_price, ask_price, open_24h,
                   high_24h, low_24h, volume_24h, instrument_state, rule_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    instrument,
                    ticker["last"],
                    decimal_or_none(ticker.get("bidPx")),
                    decimal_or_none(ticker.get("askPx")),
                    decimal_or_none(ticker.get("open24h")),
                    decimal_or_none(ticker.get("high24h")),
                    decimal_or_none(ticker.get("low24h")),
                    decimal_or_none(ticker.get("volCcy24h")),
                    details.get("state"),
                    details.get("ruleType"),
                ),
            )

    def save_account(
        self,
        connection: psycopg.Connection,
        account: dict,
        positions: list[dict],
    ) -> tuple[Decimal, Decimal]:
        available = next(
            (
                Decimal(row.get("availBal", "0"))
                for row in account.get("details", [])
                if row.get("ccy") == "USDT"
            ),
            Decimal("0"),
        )
        equity = Decimal(account.get("totalEq") or "0")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO account_snapshot (total_equity_usd, available_usdt, raw)
                VALUES (%s, %s, %s) RETURNING id
                """,
                (equity, available, Jsonb(account)),
            )
            snapshot_id = cursor.fetchone()[0]
            for row in positions:
                size = Decimal(row.get("pos") or "0")
                if size == 0:
                    continue
                cursor.execute(
                    """
                    INSERT INTO position_snapshot
                      (account_snapshot_id, instrument, side, size, average_price,
                       mark_price, leverage, notional_usd, unrealized_pnl,
                       liquidation_price, margin_mode)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        snapshot_id,
                        row["instId"],
                        row.get("posSide", "net"),
                        size,
                        decimal_or_none(row.get("avgPx")),
                        decimal_or_none(row.get("markPx")),
                        decimal_or_none(row.get("lever")),
                        decimal_or_none(row.get("notionalUsd")),
                        decimal_or_none(row.get("upl")),
                        decimal_or_none(row.get("liqPx")),
                        row.get("mgnMode"),
                    ),
                )
        exposure = sum(
            (
                abs(Decimal(row.get("notionalUsd") or "0"))
                for row in positions
                if Decimal(row.get("pos") or "0") != 0
            ),
            Decimal("0"),
        )
        return equity, exposure

    def execution_enabled(self, connection: psycopg.Connection) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT value FROM system_setting WHERE key = 'execution_enabled'"
            )
            row = cursor.fetchone()
        return bool(row and row[0] == "true")

    def save_signal_and_risk(
        self,
        connection: psycopg.Connection,
        instrument: str,
        signal,
        decision,
        mode: str,
        strategy: str,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO strategy_signal
                  (instrument, strategy, action, confidence, reference_price,
                   features, rationale)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    instrument,
                    strategy,
                    signal.action,
                    signal.confidence,
                    signal.reference_price,
                    Jsonb(signal.features),
                    signal.rationale,
                ),
            )
            signal_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO risk_decision
                  (signal_id, approved, mode, proposed_notional, reasons, limits)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    signal_id,
                    decision.approved,
                    mode,
                    decision.proposed_notional,
                    Jsonb(list(decision.reasons)),
                    Jsonb(decision.limits),
                ),
            )

    def heartbeat(
        self, connection: psycopg.Connection, status: str, detail: dict
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO worker_heartbeat (worker, last_seen_at, status, detail)
                VALUES ('collector', NOW(), %s, %s)
                ON CONFLICT (worker) DO UPDATE SET
                  last_seen_at = NOW(), status = EXCLUDED.status,
                  detail = EXCLUDED.detail
                """,
                (status, Jsonb(detail)),
            )
