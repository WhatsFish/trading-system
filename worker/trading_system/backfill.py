import argparse
import datetime as dt
import time

from .config import Settings
from .database import Database
from .okx import OkxClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.days <= 365:
        raise ValueError("days must be between 1 and 365")

    settings = Settings.from_env()
    client = OkxClient(
        settings.okx_key, settings.okx_secret, settings.okx_passphrase
    )
    database = Database(settings.database_url)
    cutoff = int(
        (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).timestamp()
        * 1000
    )

    for instrument in settings.instruments:
        cursor: int | None = None
        total = 0
        while True:
            rows = client.historical_candles(instrument, after=cursor)
            if not rows:
                break
            with database.connect() as connection:
                database.save_candles(connection, instrument, rows)
                connection.commit()
            total += len(rows)
            oldest = min(row["ts"] for row in rows)
            if oldest <= cutoff or oldest == cursor:
                break
            cursor = oldest
            time.sleep(0.12)
        print(f"{instrument}: stored {total} historical candles")


if __name__ == "__main__":
    main()
