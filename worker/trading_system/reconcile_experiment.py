"""Repair one historical full exit using exact exchange order evidence.

Default is a read-only preview. --apply writes the experience ledger only;
this module never submits, cancels or amends exchange orders.
"""
import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
from typing import TYPE_CHECKING

from .config import Settings
from .live_controller import finalize_experiment
from .okx import OkxClient

if TYPE_CHECKING:
    from .database import Database


def number(value, label: str, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"{label} is not numeric") from error
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{label} is invalid")
    return result


def validate_evidence(experiment: dict, entry: dict, exit_order: dict, audit: dict) -> dict:
    for label, order, side, order_id in (
        ("entry", entry, "buy", experiment["entry_order_id"]),
        ("exit", exit_order, "sell", audit["exchange_order_id"]),
    ):
        if (
            order.get("instId") != experiment["instrument"]
            or order.get("ordId") != order_id
            or order.get("side") != side
            or order.get("posSide") != "long"
            or order.get("state") != "filled"
        ):
            raise ValueError(f"{label} identity, side or terminal state mismatch")
        if order.get("feeCcy") != "USDT":
            raise ValueError(f"{label} fee currency is not USDT")
        if number(order.get("fee"), f"{label} fee") > 0:
            raise ValueError("rebated fees require separate reconciliation")
    if entry.get("clOrdId") != experiment["entry_client_order_id"]:
        raise ValueError("entry client ID mismatch")
    if exit_order.get("clOrdId") != audit["client_order_id"]:
        raise ValueError("exit client ID mismatch")
    if exit_order.get("reduceOnly") not in (True, "true"):
        raise ValueError("exit is not reduce-only")
    quantity = number(experiment["entry_quantity"], "entry quantity", True)
    if any(
        number(value, "full exit quantity", True) != quantity
        for value in (entry.get("accFillSz"), exit_order.get("accFillSz"), audit["requested_size"])
    ):
        raise ValueError("partial or excess exits require separate reconciliation")
    price = number(experiment["entry_price"], "entry price", True)
    if abs(number(entry.get("avgPx"), "exchange entry price", True) - price) > Decimal("0.00000001"):
        raise ValueError("entry price mismatch")
    entry_fee = abs(number(entry.get("fee"), "entry fee"))
    if entry_fee != number(experiment["entry_fee"], "recorded entry fee"):
        raise ValueError("entry fee mismatch")
    opened = dt.datetime.fromtimestamp(int(entry["fillTime"]) / 1000, dt.timezone.utc)
    closed = dt.datetime.fromtimestamp(int(exit_order["fillTime"]) / 1000, dt.timezone.utc)
    if abs((opened - experiment["entry_time"]).total_seconds()) > 1:
        raise ValueError("entry timestamp mismatch")
    if closed < opened or (
        experiment["next_entry_time"] is not None and closed >= experiment["next_entry_time"]
    ):
        raise ValueError("exit is outside the exact experiment's holding interval")
    exit_price = number(exit_order.get("avgPx"), "exit price", True)
    gross = quantity * (exit_price - price)
    fees = entry_fee + abs(number(exit_order.get("fee"), "exit fee"))
    return {
        "experimentId": experiment["id"],
        "instrument": experiment["instrument"],
        "exitOrderId": exit_order["ordId"],
        "exitTime": closed.isoformat(),
        "grossPnlUsdt": str(gross),
        "feesUsdt": str(fees),
        "netPnlExcludingFundingUsdt": str(gross - fees),
        "returnPctExcludingFunding": str((gross - fees) / (quantity * price) * 100),
    }


def reconcile(database: "Database", client: OkxClient, experiment_id: int, exit_order_id: str, apply: bool = False) -> dict:
    with database.connect() as connection:
        # Exclude controller turnover while validating ownership and finalizing.
        if not connection.execute("SELECT pg_try_advisory_lock(884423)").fetchone()[0]:
            raise RuntimeError("controller is busy; retry reconciliation later")
        try:
            row = connection.execute(
                """
                SELECT e.id, e.instrument, e.entry_order_id, e.entry_client_order_id,
                       e.entry_time, e.entry_quantity, e.entry_price, e.entry_fee,
                       (SELECT MIN(n.entry_time) FROM live_experiment n
                        WHERE n.instrument = e.instrument AND n.entry_time > e.entry_time),
                       e.status,
                       EXISTS (SELECT 1 FROM live_position p WHERE p.entry_order_id = e.entry_order_id)
                FROM live_experiment e WHERE e.id = %s
                """, (experiment_id,),
            ).fetchone()
            if not row:
                raise ValueError("experiment not found")
            if row[9] not in ("open", "closed_unreconciled"):
                raise ValueError("experiment is already closed or not eligible")
            if row[10]:
                raise ValueError("experiment still owns a managed position")
            experiment = dict(zip((
                "id", "instrument", "entry_order_id", "entry_client_order_id", "entry_time",
                "entry_quantity", "entry_price", "entry_fee", "next_entry_time",
            ), row[:9]))
            audits = connection.execute(
                """
                SELECT exchange_order_id, client_order_id, requested_size
                FROM execution_audit WHERE exchange_order_id = %s
                  AND instrument = %s AND action = 'sell' AND ts >= %s
                """, (exit_order_id, experiment["instrument"], experiment["entry_time"]),
            ).fetchall()
            if len(audits) != 1:
                raise ValueError("exact system exit audit is missing or ambiguous")
            conflicts = connection.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM live_experiment_exit_fill
                  WHERE (order_id = %s AND experiment_id <> %s)
                     OR (experiment_id = %s AND order_id <> %s)
                  UNION ALL
                  SELECT 1 FROM live_experiment
                  WHERE exit_order_id = %s AND id <> %s)
                """, (exit_order_id, experiment_id, experiment_id, exit_order_id,
                      exit_order_id, experiment_id),
            ).fetchone()[0]
            if conflicts:
                raise ValueError("exit is attributed elsewhere or experiment has other exit fills")
            audit = dict(zip(("exchange_order_id", "client_order_id", "requested_size"), audits[0]))
            entry = client.order(experiment["instrument"], experiment["entry_order_id"])
            exit_order = client.order(experiment["instrument"], exit_order_id)
            result = validate_evidence(experiment, entry, exit_order, audit)
            if apply:
                finalize_experiment(
                    database, experiment["instrument"], exit_order,
                    "historical audited exit recovered; funding excluded",
                    experiment_id=experiment_id,
                )
                verified = connection.execute(
                    "SELECT status, exit_order_id, net_pnl FROM live_experiment WHERE id = %s",
                    (experiment_id,),
                ).fetchone()
                if verified != ("closed", exit_order_id, Decimal(result["netPnlExcludingFundingUsdt"])):
                    raise RuntimeError("ledger verification failed after reconciliation")
            result["applied"] = apply
            return result
        finally:
            connection.execute("SELECT pg_advisory_unlock(884423)")


def main() -> None:
    from .database import Database

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", type=int, required=True)
    parser.add_argument("--exit-order-id", required=True)
    parser.add_argument("--apply", action="store_true", help="Write ledger only after validating exchange evidence")
    args = parser.parse_args()
    settings = Settings.from_env()
    result = reconcile(
        Database(settings.database_url),
        OkxClient(settings.okx_key, settings.okx_secret, settings.okx_passphrase),
        args.experiment_id, args.exit_order_id, args.apply,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
