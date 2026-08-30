from __future__ import annotations

import datetime as dt
import json
import logging
import signal
import time
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from .config import Settings
from .executor import Executor, OrderIntent, floor_step
from .okx import OkxClient, OkxError
from .risk import evaluate
from .strategy import Signal
from .strategy_lab import parameter_targets

if TYPE_CHECKING:
    from .database import Database


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
STOP = False
POLL_SECONDS = 60
STOP_DISTANCE = Decimal("0.05")
ENTRY_PRICE_BUFFER = Decimal("0.005")


def request_stop(_signum, _frame) -> None:
    global STOP
    STOP = True


def alphanumeric_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:20]}"[:32]


def current_position(rows: list[dict], instrument: str) -> dict | None:
    return next(
        (
            row
            for row in rows
            if row.get("instId") == instrument
            and row.get("posSide") == "long"
            and Decimal(row.get("pos") or "0") > 0
        ),
        None,
    )


def desired_action(
    target: int, has_position: bool, is_managed: bool
) -> str:
    if target == 1 and not has_position and not is_managed:
        return "buy"
    if target == 0 and has_position and is_managed:
        return "sell"
    return "hold"


def candidate_target(connection, symbol: str, family: str, parameters: dict) -> int:
    rows = connection.execute(
        "SELECT date, close FROM underlying_daily WHERE symbol = %s ORDER BY date",
        (symbol,),
    ).fetchall()
    if not rows:
        return 0
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
    if quote and quote[0] >= rows[-1][0]:
        if quote[0] == rows[-1][0]:
            closes[-1] = Decimal(quote[1])
        else:
            closes.append(Decimal(quote[1]))
    return parameter_targets(closes, family, parameters)[-1]


def account_metrics(connection, account: dict, positions: list[dict]) -> tuple:
    equity = Decimal(account.get("totalEq") or "0")
    exposure = sum(
        (
            abs(Decimal(row.get("notionalUsd") or "0"))
            for row in positions
            if Decimal(row.get("pos") or "0") != 0
        ),
        Decimal("0"),
    )
    today = dt.datetime.now(dt.timezone.utc).date()
    first = connection.execute(
        """
        SELECT total_equity_usd FROM account_snapshot
        WHERE ts::date = %s ORDER BY ts LIMIT 1
        """,
        (today,),
    ).fetchone()
    peak = connection.execute(
        "SELECT MAX(total_equity_usd) FROM account_snapshot"
    ).fetchone()[0]
    daily_pnl = equity - Decimal(first[0]) if first else Decimal("0")
    return equity, exposure, daily_pnl, Decimal(peak or equity)


def record_decision(
    settings: Settings,
    database: Database,
    instrument: str,
    strategy: str,
    action: str,
    price: Decimal,
    parameters: dict,
    account: dict,
    positions: list[dict],
    details: dict,
) -> tuple[int, bool, tuple[str, ...], Decimal]:
    with database.connect() as connection:
        stale, basis, event_risk = database.latest_reference_risk(
            connection, instrument
        )
        equity, exposure, daily_pnl, peak = account_metrics(
            connection, account, positions
        )
        enabled = database.execution_enabled(connection)
        signal_result = Signal(
            action=action,
            confidence=Decimal("1"),
            reference_price=price,
            features={"parameters": json.dumps(parameters, sort_keys=True)},
            rationale=f"Continuous strategy lab target from {strategy}.",
        )
        decision = evaluate(
            settings,
            signal_result,
            equity,
            exposure,
            details.get("ruleType", ""),
            details.get("state", ""),
            enabled,
            daily_pnl,
            peak,
            stale,
            basis,
            event_risk,
        )
        decision_id = database.save_signal_and_risk(
            connection,
            instrument,
            signal_result,
            decision,
            settings.mode,
            f"lab-{strategy}",
        )
        connection.commit()
        return (
            decision_id,
            decision.approved,
            decision.reasons,
            decision.proposed_notional,
        )


def recover_incomplete_entries(
    client: OkxClient, database: Database
) -> bool:
    from psycopg.types.json import Jsonb

    unresolved = False
    with database.connect() as connection:
        audits = connection.execute(
            """
            SELECT a.client_order_id, a.instrument, a.detail,
              COALESCE(s.strategy, ''), COALESCE(s.features, '{}'::jsonb)
            FROM execution_audit a
            LEFT JOIN risk_decision r
              ON r.id = (a.detail->>'riskDecisionId')::bigint
            LEFT JOIN strategy_signal s ON s.id = r.signal_id
            WHERE a.action = 'buy'
              AND a.state IN ('requesting', 'submitted', 'live', 'partially_filled')
            ORDER BY a.ts
            """
        ).fetchall()
        for client_id, instrument, detail, strategy_name, features in audits:
            try:
                order = client.order_by_client_id(instrument, client_id)
            except OkxError:
                unresolved = True
                continue
            state = order.get("state", "unknown")
            filled = Decimal(order.get("accFillSz") or "0")
            connection.execute(
                """
                UPDATE execution_audit SET exchange_order_id = %s,
                  state = %s, detail = detail || %s::jsonb
                WHERE client_order_id = %s
                """,
                (order["ordId"], state, json.dumps(order), client_id),
            )
            if filled > 0:
                family = strategy_name.removeprefix("lab-")
                parameters = json.loads(features.get("parameters", "{}"))
                connection.execute(
                    """
                    INSERT INTO live_position
                      (instrument, strategy, entry_order_id,
                       entry_client_order_id, owned_quantity, average_price,
                       strategy_parameters)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (instrument) DO UPDATE SET
                      owned_quantity = EXCLUDED.owned_quantity,
                      average_price = EXCLUDED.average_price,
                      strategy_parameters = EXCLUDED.strategy_parameters,
                      updated_at = NOW()
                    """,
                    (
                        instrument,
                        family,
                        order["ordId"],
                        client_id,
                        filled,
                        Decimal(order["avgPx"]),
                        Jsonb(parameters),
                    ),
                )
                basis = connection.execute(
                    """
                    SELECT underlying_price, basis_bps, underlying_quoted_at,
                           reference_stale
                    FROM basis_snapshot
                    WHERE instrument = %s ORDER BY ts DESC LIMIT 1
                    """,
                    (instrument,),
                ).fetchone()
                recent_news = connection.execute(
                    """
                    SELECT COUNT(*) FROM news_item
                    WHERE published_at > NOW() - INTERVAL '24 hours'
                    """
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO live_experiment
                      (instrument, strategy, strategy_parameters, hypothesis,
                       entry_order_id, entry_client_order_id, entry_time,
                       entry_quantity, entry_price, entry_fee, entry_context)
                    VALUES (%s, %s, %s, %s, %s, %s,
                            to_timestamp(%s / 1000.0), %s, %s, %s, %s)
                    ON CONFLICT (entry_order_id) DO NOTHING
                    """,
                    (
                        instrument,
                        family,
                        Jsonb(parameters),
                        (
                            f"{family} signal remains valid until its "
                            "parameterized exit or the 5% protective stop."
                        ),
                        order["ordId"],
                        client_id,
                        int(order.get("cTime") or int(time.time() * 1000)),
                        filled,
                        Decimal(order["avgPx"]),
                        abs(Decimal(order.get("fee") or "0")),
                        Jsonb(
                            {
                                "underlyingPrice": str(basis[0]) if basis else None,
                                "basisBps": str(basis[1]) if basis else None,
                                "underlyingQuotedAt": (
                                    basis[2].isoformat() if basis else None
                                ),
                                "referenceStale": bool(basis[3]) if basis else True,
                                "recentNewsCount": recent_news,
                                "riskDecisionId": detail.get("riskDecisionId"),
                                "stopTriggerPrice": detail.get("stopTriggerPrice"),
                            }
                        ),
                    ),
                )
                stop_client_id = detail.get("stopClientOrderId")
                if stop_client_id:
                    try:
                        algo = client.algo_order_by_client_id(
                            instrument, stop_client_id
                        )
                    except OkxError:
                        logging.exception(
                            "attached stop lookup failed instrument=%s",
                            instrument,
                        )
                    else:
                        connection.execute(
                            """
                            INSERT INTO protective_order
                              (instrument, exchange_algo_id, trigger_price,
                               size, state)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (instrument) DO UPDATE SET
                              exchange_algo_id = EXCLUDED.exchange_algo_id,
                              trigger_price = EXCLUDED.trigger_price,
                              size = EXCLUDED.size, state = EXCLUDED.state,
                              reconciled_size = 0,
                              updated_at = NOW()
                            """,
                            (
                                instrument,
                                algo["algoId"],
                                Decimal(detail["stopTriggerPrice"]),
                                filled,
                                algo.get("state", "unknown"),
                            ),
                        )
            if state not in {"canceled", "filled", "order_failed"}:
                unresolved = True
        connection.commit()
    return unresolved


def observe_experiment(
    database: Database,
    instrument: str,
    mark_price: Decimal,
    owned_quantity: Decimal,
    average_price: Decimal,
) -> None:
    unrealized = owned_quantity * (mark_price - average_price)
    return_pct = (
        (mark_price / average_price - 1) * Decimal("100")
        if average_price > 0
        else Decimal("0")
    )
    with database.connect() as connection:
        experiment = connection.execute(
            """
            SELECT id FROM live_experiment
            WHERE instrument = %s AND status = 'open'
            ORDER BY entry_time DESC LIMIT 1
            """,
            (instrument,),
        ).fetchone()
        if not experiment:
            return
        basis = connection.execute(
            """
            SELECT underlying_price, basis_bps FROM basis_snapshot
            WHERE instrument = %s ORDER BY ts DESC LIMIT 1
            """,
            (instrument,),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO live_experiment_observation
              (experiment_id, mark_price, underlying_price, basis_bps,
               unrealized_pnl, return_pct)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                experiment[0],
                mark_price,
                basis[0] if basis else None,
                basis[1] if basis else None,
                unrealized,
                return_pct,
            ),
        )
        connection.execute(
            """
            UPDATE live_experiment
            SET max_favorable_pct = GREATEST(max_favorable_pct, %s),
                max_adverse_pct = LEAST(max_adverse_pct, %s),
                updated_at = NOW()
            WHERE id = %s
            """,
            (return_pct, return_pct, experiment[0]),
        )
        connection.commit()


def finalize_experiment(
    database: Database,
    instrument: str,
    exit_order: dict,
    reason: str,
) -> None:
    from psycopg.types.json import Jsonb

    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT id, entry_quantity, entry_price, entry_fee,
                   max_favorable_pct, max_adverse_pct
            FROM live_experiment
            WHERE instrument = %s AND status = 'open'
            ORDER BY entry_time DESC LIMIT 1
            FOR UPDATE
            """,
            (instrument,),
        ).fetchone()
        if not row:
            return
        fill_time = int(
            exit_order.get("fillTime")
            or exit_order.get("uTime")
            or exit_order.get("cTime")
            or int(time.time() * 1000)
        )
        connection.execute(
            """
            INSERT INTO live_experiment_exit_fill
              (experiment_id, order_id, filled_at, quantity, price, fee, reason)
            VALUES (%s, %s, to_timestamp(%s / 1000.0), %s, %s, %s, %s)
            ON CONFLICT (experiment_id, order_id) DO UPDATE SET
              quantity = EXCLUDED.quantity, price = EXCLUDED.price,
              fee = EXCLUDED.fee, reason = EXCLUDED.reason
            """,
            (
                row[0],
                exit_order["ordId"],
                fill_time,
                Decimal(exit_order["accFillSz"]),
                Decimal(exit_order["avgPx"]),
                abs(Decimal(exit_order.get("fee") or "0")),
                reason,
            ),
        )
        aggregate = connection.execute(
            """
            SELECT SUM(quantity), SUM(quantity * price), SUM(fee), MAX(filled_at)
            FROM live_experiment_exit_fill WHERE experiment_id = %s
            """,
            (row[0],),
        ).fetchone()
        quantity = min(Decimal(row[1]), Decimal(aggregate[0]))
        exit_value = Decimal(aggregate[1])
        exit_fee = Decimal(aggregate[2])
        exit_price = exit_value / Decimal(aggregate[0])
        gross = exit_value - quantity * Decimal(row[2])
        net = gross - Decimal(row[3]) - exit_fee
        notional = quantity * Decimal(row[2])
        return_pct = (
            net / notional * Decimal("100") if notional > 0 else Decimal("0")
        )
        mfe = Decimal(row[4])
        mae = Decimal(row[5])
        lessons = []
        if net < 0 and mfe <= 0:
            lessons.append("entry_thesis_never_gained")
        elif net < 0 and mfe > 0:
            lessons.append("gave_back_open_profit")
        if reason == "protective stop":
            lessons.append("protective_stop_limited_loss")
        if exit_fee + Decimal(row[3]) > abs(gross) and gross != 0:
            lessons.append("costs_dominated_gross_result")
        if mae < Decimal("-3"):
            lessons.append("large_adverse_excursion")
        outcome = "win" if net > 0 else "loss" if net < 0 else "flat"
        postmortem = {
            "outcome": outcome,
            "summary": (
                f"{outcome}: net {net:.6f} USDT ({return_pct:.2f}%), "
                f"MFE {mfe:.2f}%, MAE {mae:.2f}%, exit={reason}."
            ),
            "lessonCodes": lessons,
            "fees": str(exit_fee + Decimal(row[3])),
        }
        connection.execute(
            """
            UPDATE live_experiment SET
              status = 'closed', exit_order_id = %s,
              exit_time = to_timestamp(%s / 1000.0), exit_price = %s,
              exit_fee = %s, exit_reason = %s, gross_pnl = %s,
              net_pnl = %s, return_pct = %s, postmortem = %s,
              updated_at = NOW()
            WHERE id = %s
            """,
            (
                exit_order["ordId"],
                int(aggregate[3].timestamp() * 1000),
                exit_price,
                exit_fee,
                reason,
                gross,
                net,
                return_pct,
                Jsonb(postmortem),
                row[0],
            ),
        )
        connection.commit()


def record_partial_exit(
    database: Database,
    instrument: str,
    exit_order: dict,
    reason: str,
) -> None:
    with database.connect() as connection:
        experiment = connection.execute(
            """
            SELECT id FROM live_experiment
            WHERE instrument = %s AND status = 'open'
            ORDER BY entry_time DESC LIMIT 1
            """,
            (instrument,),
        ).fetchone()
        if not experiment:
            return
        fill_time = int(
            exit_order.get("fillTime")
            or exit_order.get("uTime")
            or exit_order.get("cTime")
            or int(time.time() * 1000)
        )
        connection.execute(
            """
            INSERT INTO live_experiment_exit_fill
              (experiment_id, order_id, filled_at, quantity, price, fee, reason)
            VALUES (%s, %s, to_timestamp(%s / 1000.0), %s, %s, %s, %s)
            ON CONFLICT (experiment_id, order_id) DO UPDATE SET
              quantity = EXCLUDED.quantity, price = EXCLUDED.price,
              fee = EXCLUDED.fee, reason = EXCLUDED.reason
            """,
            (
                experiment[0],
                exit_order["ordId"],
                fill_time,
                Decimal(exit_order["accFillSz"]),
                Decimal(exit_order["avgPx"]),
                abs(Decimal(exit_order.get("fee") or "0")),
                reason,
            ),
        )
        connection.commit()


def mark_experiment_unreconciled(
    database: Database, instrument: str, reason: str
) -> None:
    from psycopg.types.json import Jsonb

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE live_experiment
            SET status = 'closed_unreconciled', exit_reason = %s,
                postmortem = %s, updated_at = NOW()
            WHERE instrument = %s
              AND status IN ('open', 'open_unreconciled')
            """,
            (
                reason,
                Jsonb(
                    {
                        "outcome": "unknown",
                        "summary": "Position changed outside the controller; exact PnL requires manual review.",
                        "lessonCodes": ["external_intervention"],
                    }
                ),
                instrument,
            ),
        )
        connection.commit()


def ensure_managed_experiment(database: Database, managed: dict) -> None:
    from psycopg.types.json import Jsonb

    with database.connect() as connection:
        exists = connection.execute(
            """
            SELECT 1 FROM live_experiment
            WHERE entry_order_id = %s
            """,
            (managed["entry_order_id"],),
        ).fetchone()
        if exists:
            return
        connection.execute(
            """
            INSERT INTO live_experiment
              (instrument, strategy, strategy_parameters, hypothesis,
               entry_order_id, entry_client_order_id, entry_time,
               entry_quantity, entry_price, entry_context, status)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s,
                    'open_unreconciled')
            ON CONFLICT (entry_order_id) DO NOTHING
            """,
            (
                managed["instrument"],
                managed["strategy"],
                Jsonb(managed.get("strategy_parameters") or {}),
                "Legacy managed position discovered after experience-ledger migration.",
                managed["entry_order_id"],
                managed["entry_client_order_id"],
                managed["owned_quantity"],
                managed["average_price"],
                Jsonb(
                    {
                        "backfilled": True,
                        "learningEligible": False,
                        "reason": "exact historical entry context unavailable",
                    }
                ),
            ),
        )
        connection.commit()


def protection_is_live(
    client: OkxClient, database: Database, instrument: str
) -> bool:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT exchange_algo_id, reconciled_size FROM protective_order
            WHERE instrument = %s
            """,
            (instrument,),
        ).fetchone()
    if not row:
        return False
    try:
        algo = client.algo_order(row[0])
    except OkxError:
        return False
    if algo.get("state") == "live":
        with database.connect() as connection:
            connection.execute(
                """
                UPDATE protective_order SET state = 'active', updated_at = NOW()
                WHERE instrument = %s
                """,
                (instrument,),
            )
            connection.commit()
        return True
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE protective_order SET state = %s, updated_at = NOW()
            WHERE instrument = %s
            """,
            (algo.get("state", "unknown"), instrument),
        )
        if algo.get("state") == "effective":
            managed = connection.execute(
                """
                SELECT owned_quantity FROM live_position
                WHERE instrument = %s FOR UPDATE
                """,
                (instrument,),
            ).fetchone()
            if managed:
                order_ids = algo.get("ordIdList") or []
                if isinstance(order_ids, str):
                    order_ids = [order_ids] if order_ids else []
                if not order_ids and algo.get("ordId"):
                    order_ids = [algo["ordId"]]
                if not order_ids:
                    logging.error(
                        "effective stop has no spawned order ID instrument=%s",
                        instrument,
                    )
                    connection.commit()
                    return True
                try:
                    spawned = client.order(instrument, order_ids[-1])
                except OkxError:
                    logging.exception(
                        "spawned stop order lookup failed instrument=%s",
                        instrument,
                    )
                    connection.commit()
                    return True
                cumulative = Decimal(spawned.get("accFillSz") or "0")
                reconciled = Decimal(row[1])
                delta = max(Decimal("0"), cumulative - reconciled)
                remaining = max(Decimal("0"), Decimal(managed[0]) - delta)
                connection.execute(
                    """
                    UPDATE protective_order
                    SET reconciled_size = %s, updated_at = NOW()
                    WHERE instrument = %s
                    """,
                    (cumulative, instrument),
                )
                if remaining == 0:
                    connection.execute(
                        "DELETE FROM live_position WHERE instrument = %s",
                        (instrument,),
                    )
                    finalize_experiment(
                        database, instrument, spawned, "protective stop"
                    )
                else:
                    connection.execute(
                        """
                        UPDATE live_position
                        SET owned_quantity = %s, updated_at = NOW()
                        WHERE instrument = %s
                        """,
                        (remaining, instrument),
                    )
                    if delta > 0:
                        record_partial_exit(
                            database,
                            instrument,
                            spawned,
                            "protective stop partial fill",
                        )
                if (
                    remaining > 0
                    and spawned.get("state") not in {"canceled", "filled"}
                ):
                    connection.commit()
                    return True
        connection.commit()
    return False


def disable_new_entries(database: Database, reason: str) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE system_setting
            SET value = 'false', updated_at = NOW()
            WHERE key = 'execution_enabled'
            """
        )
        database.heartbeat(
            connection,
            "error",
            {"executionEnabled": False, "reason": reason},
            worker="live-controller",
        )
        connection.commit()


def cancel_protection(
    client: OkxClient, database: Database, instrument: str
) -> None:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT exchange_algo_id FROM protective_order
            WHERE instrument = %s AND state = 'active'
            """,
            (instrument,),
        ).fetchone()
        if not row:
            return
        connection.execute(
            """
            UPDATE protective_order SET state = 'canceling', updated_at = NOW()
            WHERE instrument = %s
            """,
            (instrument,),
        )
        connection.commit()
    client.cancel_algo(instrument, row[0])
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE protective_order SET state = 'canceled', updated_at = NOW()
            WHERE instrument = %s
            """,
            (instrument,),
        )
        connection.commit()


def close_owned_position(
    settings: Settings,
    client: OkxClient,
    database: Database,
    executor: Executor,
    managed: dict,
    account: dict,
    positions: list[dict],
    details: dict,
    parameters: dict,
    reason: str,
) -> None:
    instrument = managed["instrument"]
    aggregate = current_position(positions, instrument)
    if not aggregate:
        if protection_is_live(client, database, instrument):
            cancel_protection(client, database, instrument)
        with database.connect() as connection:
            connection.execute(
                "DELETE FROM live_position WHERE instrument = %s",
                (instrument,),
            )
            connection.commit()
        mark_experiment_unreconciled(
            database, instrument, "position absent outside controller exit"
        )
        return
    owned = min(
        Decimal(managed["owned_quantity"]),
        Decimal(aggregate["pos"]),
    )
    with database.connect() as connection:
        exit_row = connection.execute(
            """
            SELECT exit_client_order_id FROM live_position
            WHERE instrument = %s FOR UPDATE
            """,
            (instrument,),
        ).fetchone()
        exit_client_id = (
            exit_row[0]
            if exit_row and exit_row[0]
            else alphanumeric_id("tsexit")
        )
        connection.execute(
            """
            UPDATE live_position
            SET exit_client_order_id = %s, exit_state = 'preparing',
                updated_at = NOW()
            WHERE instrument = %s
            """,
            (exit_client_id, instrument),
        )
        connection.commit()
    price = Decimal(client.ticker(instrument)["last"])
    decision_id, approved, reasons, _ = record_decision(
        settings,
        database,
        instrument,
        managed["strategy"],
        "sell",
        price,
        parameters,
        account,
        positions,
        details,
    )
    if not approved:
        raise RuntimeError(f"risk-reducing exit blocked unexpectedly: {reasons}")
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE live_position SET exit_state = 'submitting', updated_at = NOW()
            WHERE instrument = %s
            """,
            (instrument,),
        )
        connection.commit()
    executor.submit(
        OrderIntent(
            instrument,
            "sell",
            owned,
            None,
            True,
            exit_client_id,
            decision_id,
            "market",
        )
    )
    for _ in range(15):
        time.sleep(1)
        order = client.order_by_client_id(instrument, exit_client_id)
        filled = Decimal(order.get("accFillSz") or "0")
        if filled >= owned:
            cancel_protection(client, database, instrument)
            finalize_experiment(
                database, instrument, order, reason
            )
            with database.connect() as connection:
                connection.execute(
                    "DELETE FROM live_position WHERE instrument = %s",
                    (instrument,),
                )
                connection.commit()
            logging.info("managed exit complete instrument=%s reason=%s", instrument, reason)
            return
        if order.get("state") in {"canceled", "filled"} and filled == 0:
            with database.connect() as connection:
                connection.execute(
                    """
                    UPDATE live_position
                    SET exit_client_order_id = NULL, exit_state = 'retry',
                        updated_at = NOW()
                    WHERE instrument = %s
                    """,
                    (instrument,),
                )
                connection.commit()
            raise RuntimeError("managed exit had zero fill; protected retry required")
        if order.get("state") in {"canceled", "filled"} and filled > 0:
            record_partial_exit(database, instrument, order, reason)
            remaining = owned - filled
            with database.connect() as connection:
                connection.execute(
                    """
                    UPDATE live_position
                    SET owned_quantity = %s, exit_client_order_id = NULL,
                        exit_state = 'partial', updated_at = NOW()
                    WHERE instrument = %s
                    """,
                    (remaining, instrument),
                )
                connection.commit()
            raise RuntimeError("managed exit partially filled; retry required")
    raise RuntimeError("managed exit did not reconcile")


def load_candidate(connection, managed: dict | None) -> dict | None:
    if managed:
        symbol = managed["instrument"].split("-", 1)[0]
        if not managed.get("strategy_parameters"):
            return None
        return {
            "symbol": symbol,
            "family": managed["strategy"],
            "parameters": managed["strategy_parameters"],
        }
    else:
        row = connection.execute(
            """
            SELECT e.symbol, e.family, e.parameters
            FROM strategy_candidate c
            JOIN strategy_experiment e ON e.id = c.experiment_id
            WHERE e.current_target = 1
            ORDER BY c.score DESC LIMIT 1
            """
        ).fetchone()
    if not row:
        return None
    return {"symbol": row[0], "family": row[1], "parameters": row[2]}


def run_cycle(
    settings: Settings, client: OkxClient, database: Database, executor: Executor
) -> None:
    unresolved = recover_incomplete_entries(client, database)
    account = client.account_balance()
    positions = client.positions()
    with database.connect() as connection:
        enabled = database.execution_enabled(connection)
        row = connection.execute(
            """
            SELECT instrument, strategy, owned_quantity, average_price,
                   exit_client_order_id, strategy_parameters,
                   entry_order_id, entry_client_order_id
            FROM live_position LIMIT 1
            """
        ).fetchone()
        managed = (
            {
                "instrument": row[0],
                "strategy": row[1],
                "owned_quantity": row[2],
                "average_price": row[3],
                "exit_client_order_id": row[4],
                "strategy_parameters": row[5],
                "entry_order_id": row[6],
                "entry_client_order_id": row[7],
            }
            if row
            else None
        )
        candidate = load_candidate(connection, managed)
        database.heartbeat(
            connection,
            "ok" if enabled else "locked",
            {
                "mode": settings.mode,
                "executionEnabled": enabled,
                "managedInstrument": managed["instrument"] if managed else None,
                "unresolvedEntry": unresolved,
            },
            worker="live-controller",
        )
        connection.commit()
    if unresolved or (not enabled and not managed):
        return

    if managed:
        ensure_managed_experiment(database, managed)
        instrument = managed["instrument"]
        details = client.instrument(instrument)
        if managed["exit_client_order_id"]:
            close_owned_position(
                settings,
                client,
                database,
                executor,
                managed,
                account,
                positions,
                details,
                candidate["parameters"] if candidate else {},
                "resume durable exit",
            )
            return
        protection_live = protection_is_live(client, database, instrument)
        with database.connect() as connection:
            refreshed = connection.execute(
                """
                SELECT instrument, strategy, owned_quantity, average_price,
                       strategy_parameters, entry_order_id,
                       entry_client_order_id
                FROM live_position WHERE instrument = %s
                """,
                (instrument,),
            ).fetchone()
        if not refreshed:
            return
        managed = {
            "instrument": refreshed[0],
            "strategy": refreshed[1],
            "owned_quantity": refreshed[2],
            "average_price": refreshed[3],
            "strategy_parameters": refreshed[4],
            "entry_order_id": refreshed[5],
            "entry_client_order_id": refreshed[6],
        }
        positions = client.positions()
        aggregate = current_position(positions, instrument)
        if not aggregate:
            if protection_live:
                cancel_protection(client, database, instrument)
            with database.connect() as connection:
                connection.execute(
                    "DELETE FROM live_position WHERE instrument = %s",
                    (instrument,),
                )
                connection.commit()
            mark_experiment_unreconciled(
                database, instrument, "aggregate position disappeared"
            )
            return
        if not protection_live:
            logging.error("attached stop unavailable; closing managed position")
            close_owned_position(
                settings,
                client,
                database,
                executor,
                managed,
                account,
                positions,
                details,
                candidate["parameters"] if candidate else {},
                "attached stop unavailable",
            )
            return
        owned = Decimal(managed["owned_quantity"])
        aggregate_size = Decimal(aggregate["pos"])
        observe_experiment(
            database,
            instrument,
            Decimal(aggregate.get("markPx") or aggregate.get("last")),
            owned,
            Decimal(managed["average_price"]),
        )
        if aggregate_size > owned:
            logging.critical(
                "manual quantity detected on managed instrument=%s "
                "owned=%s aggregate=%s; disabling new entries",
                instrument,
                owned,
                aggregate_size,
            )
            disable_new_entries(
                database, "manual quantity on managed instrument"
            )
            return
        if aggregate_size < owned:
            mark_experiment_unreconciled(
                database,
                instrument,
                "external reduction made fill attribution incomplete",
            )
            managed["owned_quantity"] = aggregate_size
            with database.connect() as connection:
                connection.execute(
                    """
                    UPDATE live_position SET owned_quantity = %s, updated_at = NOW()
                    WHERE instrument = %s
                    """,
                    (aggregate_size, instrument),
                )
                connection.commit()
            close_owned_position(
                settings,
                client,
                database,
                executor,
                managed,
                account,
                positions,
                details,
                candidate["parameters"] if candidate else {},
                "external position reduction detected",
            )
            return
        if not candidate:
            close_owned_position(
                settings,
                client,
                database,
                executor,
                managed,
                account,
                positions,
                details,
                {},
                "candidate removed",
            )
            return
        with database.connect() as connection:
            target = candidate_target(
                connection,
                candidate["symbol"],
                candidate["family"],
                candidate["parameters"],
            )
        if target == 0:
            close_owned_position(
                settings,
                client,
                database,
                executor,
                managed,
                account,
                positions,
                details,
                candidate["parameters"],
                "strategy target flat",
            )
        return

    if not candidate:
        return
    instrument = f"{candidate['symbol']}-USDT-SWAP"
    if current_position(positions, instrument):
        return
    with database.connect() as connection:
        target = candidate_target(
            connection,
            candidate["symbol"],
            candidate["family"],
            candidate["parameters"],
        )
    if target == 0:
        return

    details = client.instrument(instrument)
    ticker = client.ticker(instrument)
    last = Decimal(ticker["last"])
    decision_id, approved, reasons, authorized_notional = record_decision(
        settings,
        database,
        instrument,
        candidate["family"],
        "buy",
        last,
        candidate["parameters"],
        account,
        positions,
        details,
    )
    if not approved:
        logging.info("live entry blocked instrument=%s reasons=%s", instrument, reasons)
        return

    ceiling = floor_step(
        Decimal(ticker["askPx"]) * (Decimal("1") + ENTRY_PRICE_BUFFER),
        Decimal(details["tickSz"]),
    )
    budget = authorized_notional
    size = floor_step(budget / ceiling, Decimal(details["lotSz"]))
    if size < Decimal(details["minSz"]):
        logging.info("live entry below minimum size instrument=%s", instrument)
        return
    client.set_leverage(instrument, "1")
    client_id = alphanumeric_id("tsentry")
    stop_client_id = alphanumeric_id("tsstop")
    stop_trigger = floor_step(
        last * (Decimal("1") - STOP_DISTANCE),
        Decimal(details["tickSz"]),
    )
    executor.submit(
        OrderIntent(
            instrument,
            "buy",
            size,
            ceiling,
            False,
            client_id,
            decision_id,
            "ioc",
            stop_trigger,
            stop_client_id,
        )
    )
    if recover_incomplete_entries(client, database):
        raise RuntimeError("entry remains unresolved after IOC submission")
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT owned_quantity, average_price FROM live_position
            WHERE entry_client_order_id = %s
            """,
            (client_id,),
        ).fetchone()
    if not row:
        return
    if not protection_is_live(client, database, instrument):
        logging.error("attached stop missing after fill; closing managed position")
        with database.connect() as connection:
            managed_row = connection.execute(
                """
                SELECT instrument, strategy, owned_quantity, average_price,
                       strategy_parameters, entry_order_id,
                       entry_client_order_id
                FROM live_position WHERE instrument = %s
                """,
                (instrument,),
            ).fetchone()
        close_owned_position(
            settings,
            client,
            database,
            executor,
            {
                "instrument": managed_row[0],
                "strategy": managed_row[1],
                "owned_quantity": managed_row[2],
                "average_price": managed_row[3],
                "strategy_parameters": managed_row[4],
                "entry_order_id": managed_row[5],
                "entry_client_order_id": managed_row[6],
            },
            client.account_balance(),
            client.positions(),
            details,
            candidate["parameters"],
            "initial stop failed",
        )


def main() -> None:
    from .database import Database

    settings = Settings.from_env()
    client = OkxClient(
        settings.okx_key, settings.okx_secret, settings.okx_passphrase
    )
    database = Database(settings.database_url)
    executor = Executor(settings, client, database)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not STOP:
        started = time.monotonic()
        failed = False
        try:
            run_cycle(settings, client, database, executor)
        except Exception:
            failed = True
            logging.exception("live controller cycle failed")
        delay = 1 if failed else max(1, POLL_SECONDS - (time.monotonic() - started))
        time.sleep(delay)


if __name__ == "__main__":
    main()
