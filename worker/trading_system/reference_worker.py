import logging
import signal
import time

from .config import database_url_from_env
from .database import Database
from .reference import latest_quotes


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
STOP = False


def request_stop(_signum, _frame) -> None:
    global STOP
    STOP = True


def main() -> None:
    database = Database(database_url_from_env())
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not STOP:
        started = time.monotonic()
        try:
            quotes = latest_quotes()
            with database.connect() as connection:
                prices = database.latest_perpetual_prices(connection)
                database.save_reference_quotes(connection, quotes, prices)
                connection.commit()
            logging.info("reference refresh complete quotes=%s", len(quotes))
        except Exception:
            logging.exception("reference refresh failed")
        elapsed = time.monotonic() - started
        time.sleep(max(1, 900 - elapsed))


if __name__ == "__main__":
    main()
