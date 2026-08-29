import argparse
import datetime as dt
import json
import os
import time
import urllib.request
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb
import yfinance as yf

from .config import database_url_from_env
from .universe import ASSETS


SYMBOLS = tuple(asset.instrument.split("-", 1)[0] for asset in ASSETS)
COMPANY_SYMBOLS = tuple(
    symbol for symbol in SYMBOLS if symbol not in {"SPY", "QQQ"}
)
MATERIAL_FORMS = {"8-K", "10-K", "10-Q"}


def save_history(connection: psycopg.Connection, period: str) -> int:
    frame = yf.download(
        list(SYMBOLS),
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=False,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    inserted = 0
    with connection.cursor() as cursor:
        for symbol in SYMBOLS:
            if symbol not in frame.columns.get_level_values(0):
                continue
            rows = frame[symbol].dropna(subset=["Open", "High", "Low", "Close"])
            for timestamp, row in rows.iterrows():
                cursor.execute(
                    """
                    INSERT INTO underlying_daily
                      (symbol, date, open, high, low, close, volume, source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'yfinance')
                    ON CONFLICT (symbol, date) DO UPDATE SET
                      open = EXCLUDED.open, high = EXCLUDED.high,
                      low = EXCLUDED.low, close = EXCLUDED.close,
                      volume = EXCLUDED.volume, source = EXCLUDED.source,
                      ingested_at = NOW()
                    """,
                    (
                        symbol,
                        timestamp.date(),
                        float(row["Open"]),
                        float(row["High"]),
                        float(row["Low"]),
                        float(row["Close"]),
                        int(row["Volume"]) if row["Volume"] == row["Volume"] else None,
                    ),
                )
                inserted += 1
    return inserted


def fetch_sec_json(url: str, user_agent: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def save_sec_filings(connection: psycopg.Connection, user_agent: str) -> int:
    tickers = fetch_sec_json(
        "https://www.sec.gov/files/company_tickers.json", user_agent
    )
    cik_by_symbol = {
        row["ticker"].upper(): int(row["cik_str"]) for row in tickers.values()
    }
    cutoff = dt.date.today() - dt.timedelta(days=90)
    inserted = 0
    with connection.cursor() as cursor:
        for symbol in COMPANY_SYMBOLS:
            cik = cik_by_symbol.get(symbol)
            if cik is None:
                continue
            payload = fetch_sec_json(
                f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                user_agent,
            )
            recent = payload.get("filings", {}).get("recent", {})
            for form, date_text, accession, primary in zip(
                recent.get("form", []),
                recent.get("filingDate", []),
                recent.get("accessionNumber", []),
                recent.get("primaryDocument", []),
            ):
                filed_at = dt.date.fromisoformat(date_text)
                if form not in MATERIAL_FORMS or filed_at < cutoff:
                    continue
                clean_accession = accession.replace("-", "")
                url = (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{clean_accession}/{primary}"
                )
                cursor.execute(
                    """
                    INSERT INTO sec_filing
                      (accession_number, symbol, form, filed_at, url)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (accession_number) DO NOTHING
                    """,
                    (accession, symbol, form, filed_at, url),
                )
                inserted += cursor.rowcount
            time.sleep(0.12)
    return inserted


def save_earnings_events(connection: psycopg.Connection) -> int:
    inserted = 0
    with connection.cursor() as cursor:
        for symbol in COMPANY_SYMBOLS:
            calendar = yf.Ticker(symbol).calendar
            values = calendar.get("Earnings Date", []) if isinstance(calendar, dict) else []
            if not isinstance(values, list):
                values = [values]
            for value in values:
                if value is None:
                    continue
                starts_at = value
                if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
                    starts_at = dt.datetime.combine(
                        value, dt.time(12), tzinfo=dt.timezone.utc
                    )
                if isinstance(starts_at, dt.datetime) and starts_at.tzinfo is None:
                    starts_at = starts_at.replace(tzinfo=dt.timezone.utc)
                cursor.execute(
                    """
                    INSERT INTO corporate_event
                      (symbol, event_type, starts_at, source, details)
                    VALUES (%s, 'earnings', %s, 'yfinance', %s)
                    ON CONFLICT (symbol, event_type, starts_at, source)
                    DO UPDATE SET details = EXCLUDED.details, ingested_at = NOW()
                    """,
                    (
                        symbol,
                        starts_at,
                        Jsonb(
                            {
                                key: str(item)
                                for key, item in calendar.items()
                                if key.startswith("Earnings")
                            }
                        ),
                    ),
                )
                inserted += 1
            time.sleep(0.1)
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="5y")
    args = parser.parse_args()
    user_agent = os.environ.get("EDGAR_UA") or "trading-system admin@localhost"
    with psycopg.connect(database_url_from_env()) as connection:
        history = save_history(connection, args.period)
        filings = save_sec_filings(connection, user_agent)
        events = save_earnings_events(connection)
        connection.commit()
    print(
        f"research refresh complete history={history} filings={filings} "
        f"events={events}"
    )


if __name__ == "__main__":
    main()
