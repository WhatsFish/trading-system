from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import json
import logging
import os
import time
from typing import TYPE_CHECKING
import uuid

from .config import Settings
from .okx import OkxClient, OkxError
from .universe import BY_INSTRUMENT

if TYPE_CHECKING:
    from .database import Database


TRANSPORT_TEST_MAX_NOTIONAL = Decimal("5")
LIVE_ACK = "I_UNDERSTAND_LIVE_TRADING_RISK"
TRANSPORT_TEST_ACK = "PLACE_AND_CANCEL_REAL_ORDER"


@dataclass(frozen=True)
class OrderIntent:
    instrument: str
    action: str
    size: Decimal
    price: Decimal | None
    reduce_only: bool
    client_order_id: str
    risk_decision_id: int
    order_type: str = "limit"
    stop_trigger_price: Decimal | None = None
    stop_client_order_id: str | None = None


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def validate_intent(
    intent: OrderIntent,
    settings: Settings,
    execution_enabled: bool,
    last_price: Decimal,
    lot_size: Decimal,
    minimum_size: Decimal,
    authorized_entry_notional: Decimal | None = None,
) -> None:
    if intent.instrument not in BY_INSTRUMENT:
        raise ValueError("instrument is outside the equity allowlist")
    if intent.action not in {"buy", "sell"}:
        raise ValueError("unsupported action")
    if (
        not intent.client_order_id.isalnum()
        or not 1 <= len(intent.client_order_id) <= 32
    ):
        raise ValueError("client order ID must be 1-32 alphanumeric characters")
    if intent.size < minimum_size or intent.size != floor_step(intent.size, lot_size):
        raise ValueError("size violates instrument lot rules")
    if intent.order_type not in {"limit", "ioc", "market"}:
        raise ValueError("unsupported order type")
    if intent.order_type in {"limit", "ioc"} and intent.price is None:
        raise ValueError("priced order requires a limit price")
    if intent.order_type == "market" and intent.price is not None:
        raise ValueError("market order cannot carry a limit price")
    reference = intent.price or last_price
    if intent.action == "buy" and (
        authorized_entry_notional is None
        or intent.size * reference > authorized_entry_notional
    ):
        raise ValueError("order exceeds risk-authorized entry notional")
    if intent.action == "sell" and not intent.reduce_only:
        raise ValueError("short opening is disabled")
    if settings.mode != "live" or settings.live_ack != LIVE_ACK:
        raise PermissionError("environment live gates are closed")
    if intent.action == "buy" and not execution_enabled:
        raise PermissionError("database execution gate is closed")
    if intent.action == "buy" and (
        intent.stop_trigger_price is None
        or intent.stop_client_order_id is None
        or not intent.stop_client_order_id.isalnum()
        or not 1 <= len(intent.stop_client_order_id) <= 32
    ):
        raise ValueError("live entry requires a valid attached stop")


class Executor:
    def __init__(
        self, settings: Settings, client: OkxClient, database: Database
    ) -> None:
        self.settings = settings
        self.client = client
        self.database = database

    def submit(self, intent: OrderIntent) -> str:
        details = self.client.instrument(intent.instrument)
        ticker = self.client.ticker(intent.instrument)
        with self.database.connect() as connection:
            enabled = self.database.execution_enabled(connection)
            existing = connection.execute(
                """
                SELECT exchange_order_id FROM execution_audit
                WHERE client_order_id = %s
                """,
                (intent.client_order_id,),
            ).fetchone()
            if existing:
                if existing[0]:
                    return existing[0]
                try:
                    recovered = self.client.order_by_client_id(
                        intent.instrument, intent.client_order_id
                    )
                except OkxError:
                    logging.warning(
                        "order not found during idempotent recovery; "
                        "resubmitting same client ID=%s",
                        intent.client_order_id,
                    )
                else:
                    connection.execute(
                        """
                        UPDATE execution_audit
                        SET exchange_order_id = %s, state = %s,
                            detail = detail || %s::jsonb
                        WHERE client_order_id = %s
                        """,
                        (
                            recovered["ordId"],
                            recovered.get("state", "submitted"),
                            json.dumps(recovered),
                            intent.client_order_id,
                        ),
                    )
                    connection.commit()
                    return recovered["ordId"]
            risk = connection.execute(
                """
                SELECT r.approved, s.instrument, s.action, r.proposed_notional
                FROM risk_decision r
                JOIN strategy_signal s ON s.id = r.signal_id
                WHERE r.id = %s
                  AND r.ts > NOW() - INTERVAL '5 minutes'
                """,
                (intent.risk_decision_id,),
            ).fetchone()
            if (
                not risk
                or not risk[0]
                or risk[1] != intent.instrument
                or risk[2] != intent.action
            ):
                raise PermissionError("fresh matching approved risk decision required")
            validate_intent(
                intent,
                self.settings,
                enabled,
                Decimal(ticker["last"]),
                Decimal(details["lotSz"]),
                Decimal(details["minSz"]),
                Decimal(risk[3]) if intent.action == "buy" else None,
            )
            audit_detail = json.dumps(
                {
                    "riskDecisionId": intent.risk_decision_id,
                    "stopClientOrderId": intent.stop_client_order_id,
                    "stopTriggerPrice": (
                        str(intent.stop_trigger_price)
                        if intent.stop_trigger_price is not None
                        else None
                    ),
                }
            )
            if existing:
                connection.execute(
                    """
                    UPDATE execution_audit
                    SET detail = detail || %s::jsonb, state = 'requesting'
                    WHERE client_order_id = %s
                    """,
                    (audit_detail, intent.client_order_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO execution_audit
                      (client_order_id, instrument, action, requested_size,
                       requested_price, state, detail)
                    VALUES (%s, %s, %s, %s, %s, 'requesting', %s::jsonb)
                    """,
                    (
                        intent.client_order_id,
                        intent.instrument,
                        intent.action,
                        intent.size,
                        intent.price,
                        audit_detail,
                    ),
                )
            connection.commit()
            order = {
                "instId": intent.instrument,
                "tdMode": "isolated",
                "side": intent.action,
                "posSide": "long",
                "ordType": intent.order_type,
                "sz": format(intent.size, "f"),
                "clOrdId": intent.client_order_id,
                "reduceOnly": intent.reduce_only,
            }
            if intent.price is not None:
                order["px"] = format(intent.price, "f")
            if intent.action == "buy":
                order["attachAlgoOrds"] = [
                    {
                        "attachAlgoClOrdId": intent.stop_client_order_id,
                        "slTriggerPx": format(intent.stop_trigger_price, "f"),
                        "slOrdPx": "-1",
                        "slTriggerPxType": "mark",
                    }
                ]
            result = self.client.place_order(order)
            connection.execute(
                """
                UPDATE execution_audit
                SET exchange_order_id = %s, state = 'submitted',
                    detail = detail || %s::jsonb
                WHERE client_order_id = %s
                """,
                (
                    result["ordId"],
                    json.dumps(result),
                    intent.client_order_id,
                ),
            )
            connection.commit()
            return result["ordId"]


def transport_test(settings: Settings) -> dict:
    from .database import Database

    if os.environ.get("EXECUTION_TEST_ACK") != TRANSPORT_TEST_ACK:
        raise PermissionError("execution transport test acknowledgement missing")
    client = OkxClient(
        settings.okx_key, settings.okx_secret, settings.okx_passphrase
    )
    database = Database(settings.database_url)
    instrument = "GOOGL-USDT-SWAP"
    details = client.instrument(instrument)
    ticker = client.ticker(instrument)
    tick = Decimal(details["tickSz"])
    size = Decimal(details["minSz"])
    price = floor_step(Decimal(ticker["bidPx"]) * Decimal("0.5"), tick)
    stop_trigger = floor_step(price * Decimal("0.95"), tick)
    if size * price > TRANSPORT_TEST_MAX_NOTIONAL:
        raise ValueError("transport test exceeds live cap")
    with database.connect() as connection:
        if database.execution_enabled(connection):
            raise PermissionError("refusing transport test while automation is enabled")
    client_order_id = f"tstest{uuid.uuid4().hex[:20]}"
    result = client.place_order(
        {
            "instId": instrument,
            "tdMode": "isolated",
            "side": "buy",
            "posSide": "long",
            "ordType": "post_only",
            "px": format(price, "f"),
            "sz": format(size, "f"),
            "clOrdId": client_order_id,
            "attachAlgoOrds": [
                {
                    "attachAlgoClOrdId": f"tsteststop{uuid.uuid4().hex[:18]}",
                    "slTriggerPx": format(stop_trigger, "f"),
                    "slOrdPx": "-1",
                    "slTriggerPxType": "mark",
                }
            ],
        }
    )
    order_id = result["ordId"]
    try:
        client.cancel_order(instrument, order_id)
        for _ in range(10):
            order = client.order(instrument, order_id)
            if order.get("state") == "canceled":
                with database.connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO execution_audit
                          (client_order_id, instrument, action, requested_size,
                           requested_price, exchange_order_id, state, detail)
                        VALUES (%s, %s, 'buy', %s, %s, %s, 'canceled', %s::jsonb)
                        """,
                        (
                            client_order_id,
                            instrument,
                            size,
                            price,
                            order_id,
                            json.dumps(order),
                        ),
                    )
                    connection.commit()
                return {
                    "instrument": instrument,
                    "size": str(size),
                    "price": str(price),
                    "state": "canceled",
                }
            time.sleep(0.5)
        raise RuntimeError("transport test order did not reach canceled state")
    except Exception:
        try:
            client.cancel_order(instrument, order_id)
        except Exception as cancel_error:
            logging.warning(
                "second cancellation attempt failed order=%s error=%s",
                order_id,
                cancel_error,
            )
        raise


def main() -> None:
    print(transport_test(Settings.from_env()))


if __name__ == "__main__":
    main()
