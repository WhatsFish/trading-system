import logging
import signal
import time
from decimal import Decimal

from .config import Settings
from .database import Database
from .news import fetch_news, save_news
from .okx import OkxClient
from .risk import evaluate
from .strategy import equity_signal
from .universe import BY_INSTRUMENT


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
STOP = False


def request_stop(_signum, _frame) -> None:
    global STOP
    STOP = True


def run_cycle(settings: Settings, client: OkxClient, database: Database) -> None:
    account = client.account_balance()
    positions = client.positions()
    tickers = client.tickers()
    instruments = client.instruments()
    with database.connect() as connection:
        equity, exposure = database.save_account(connection, account, positions)
        execution_enabled = database.execution_enabled(connection)
        for instrument in settings.instruments:
            candles = client.candles(instrument)
            ticker = tickers[instrument]
            details = instruments[instrument]
            database.save_candles(connection, instrument, candles)
            database.save_market(connection, instrument, ticker, details)
            if instrument not in BY_INSTRUMENT:
                raise ValueError(f"instrument is not in the equity allowlist: {instrument}")
            signal_result = equity_signal(candles)
            reference_stale, basis_bps, event_risk = database.latest_reference_risk(
                connection, instrument
            )
            decision = evaluate(
                settings=settings,
                signal=signal_result,
                equity=equity,
                total_exposure=exposure,
                instrument_rule_type=details.get("ruleType", ""),
                instrument_state=details.get("state", ""),
                execution_enabled=execution_enabled,
                reference_stale=reference_stale,
                basis_bps=basis_bps,
                event_risk=event_risk,
            )
            database.save_signal_and_risk(
                connection,
                instrument,
                signal_result,
                decision,
                settings.mode,
                "us-equity-session-trend-v1",
            )
            time.sleep(0.06)
        database.heartbeat(
            connection,
            "ok",
            {
                "mode": settings.mode,
                "equityUsd": str(equity),
                "exposureUsd": str(exposure),
                "instrumentCount": len(settings.instruments),
                "universe": "us-equity-perpetuals",
            },
        )
        connection.commit()


def main() -> None:
    settings = Settings.from_env()
    client = OkxClient(
        settings.okx_key, settings.okx_secret, settings.okx_passphrase
    )
    database = Database(settings.database_url)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    news_due = 0.0

    while not STOP:
        started = time.monotonic()
        try:
            run_cycle(settings, client, database)
            if started >= news_due:
                with database.connect() as connection:
                    count = save_news(connection, fetch_news())
                    connection.commit()
                logging.info("news ingest complete inserted=%s", count)
                news_due = started + 900
            logging.info("collector cycle complete mode=%s", settings.mode)
        except Exception:
            logging.exception("collector cycle failed")
            try:
                with database.connect() as connection:
                    database.heartbeat(connection, "error", {"mode": settings.mode})
                    connection.commit()
            except Exception:
                logging.exception("failed to record worker error")
        elapsed = time.monotonic() - started
        time.sleep(max(1, settings.poll_seconds - elapsed))


if __name__ == "__main__":
    main()
