import datetime as dt
from decimal import Decimal

import yfinance as yf

from .universe import ASSETS


SYMBOLS = tuple(asset.instrument.split("-", 1)[0] for asset in ASSETS)


def latest_quotes() -> dict[str, tuple[dt.datetime, Decimal]]:
    frame = yf.download(
        list(SYMBOLS),
        period="5d",
        interval="1m",
        auto_adjust=False,
        actions=False,
        group_by="ticker",
        threads=True,
        progress=False,
        prepost=False,
    )
    quotes: dict[str, tuple[dt.datetime, Decimal]] = {}
    for symbol in SYMBOLS:
        if symbol not in frame.columns.get_level_values(0):
            continue
        rows = frame[symbol].dropna(subset=["Close"])
        if rows.empty:
            continue
        timestamp = rows.index[-1].to_pydatetime()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
        quotes[symbol] = (timestamp, Decimal(str(float(rows["Close"].iloc[-1]))))
    return quotes
