import numpy as np
import pandas as pd

from .strategy_library import StrategySpec


def positions_from_rules(
    entry: pd.Series,
    exit_rule: pd.Series,
    max_hold: int | None = None,
) -> np.ndarray:
    output = np.zeros(len(entry), dtype=np.int8)
    position = 0
    held = 0
    for index in range(len(entry)):
        if not position and bool(entry.iloc[index]):
            position, held = 1, 0
        elif position:
            held += 1
            if bool(exit_rule.iloc[index]) or (
                max_hold is not None and held >= max_hold
            ):
                position = 0
        output[index] = position
    return output


def rsi(close: pd.Series, period: int) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).rolling(period).mean()
    loss = (-change.clip(upper=0)).rolling(period).mean()
    relative = gain / loss.replace(0, np.nan)
    result = 100 - 100 / (1 + relative)
    result = result.mask((loss == 0) & (gain > 0), 100)
    result = result.mask((loss == 0) & (gain == 0), 50)
    return result.fillna(50)


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)


def generate_targets_vectorized(
    frame: pd.DataFrame,
    spec: StrategySpec,
    benchmark_close: pd.Series,
) -> np.ndarray:
    close = frame["close"]
    open_price = frame["open"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"].fillna(0)
    name = spec.name
    p = spec.parameters

    if name in {"sma-trend", "ema-trend"}:
        fast, slow = int(p["fast"]), int(p["slow"])
        if name == "sma-trend":
            fast_line = close.rolling(fast).mean()
            slow_line = close.rolling(slow).mean()
        else:
            fast_line = close.ewm(span=fast, adjust=False).mean()
            slow_line = close.ewm(span=slow, adjust=False).mean()
        return ((close > fast_line) & (fast_line > slow_line)).astype(np.int8).to_numpy()

    if name == "price-sma-filter":
        average = close.shift(1).rolling(int(p["period"])).mean()
        entry = close > average
        exit_rule = close < average * (1 - float(p["exitBufferPct"]) / 100)
        return positions_from_rules(entry, exit_rule)

    if name == "time-series-momentum":
        momentum = close.pct_change(int(p["lookback"]))
        return (momentum > float(p["thresholdPct"]) / 100).astype(np.int8).to_numpy()

    if name == "high-proximity-momentum":
        rolling_high = high.shift(1).rolling(int(p["lookback"])).max()
        return (close >= rolling_high * float(p["proximityPct"]) / 100).astype(np.int8).to_numpy()

    if name == "donchian-breakout":
        entry = close > high.shift(1).rolling(int(p["entryDays"])).max()
        exit_rule = close < low.shift(1).rolling(int(p["exitDays"])).min()
        return positions_from_rules(entry, exit_rule)

    if name in {"bollinger-breakout", "bollinger-reentry"}:
        period = int(p["period"])
        average = close.shift(1).rolling(period).mean()
        deviation = close.shift(1).rolling(period).std(ddof=0) * float(p["stdDev"])
        lower, upper = average - deviation, average + deviation
        if name == "bollinger-breakout":
            return positions_from_rules(close > upper, close < average)
        setup = close.shift(1) < lower.shift(1)
        return positions_from_rules(setup & (close > lower), close >= average)

    if name == "bollinger-squeeze":
        period = int(p["period"])
        average = close.shift(1).rolling(period).mean()
        deviation = close.shift(1).rolling(period).std(ddof=0)
        width = 4 * deviation / average
        threshold = width.shift(1).rolling(int(p["bandwidthDays"])).quantile(
            float(p["quantilePct"]) / 100
        )
        entry = (width <= threshold) & (close > average + 2 * deviation)
        return positions_from_rules(entry, close < average)

    if name in {"atr-breakout", "range-expansion"}:
        measure = true_range(frame).shift(1).rolling(int(p["period"])).mean()
        multiple = float(p["multiple"])
        if name == "atr-breakout":
            entry = close > close.shift(1) + measure * multiple
            exit_rule = close < close.shift(1) - measure
        else:
            entry = (close > open_price) & ((high - low) > measure * multiple)
            exit_rule = close < close.shift(1)
        return positions_from_rules(entry, exit_rule)

    if name in {"rsi2-pullback", "rsi-reversion"}:
        period = 2 if name == "rsi2-pullback" else int(p["period"])
        oscillator = rsi(close, period)
        if name == "rsi2-pullback":
            entry = (close > close.shift(1).rolling(200).mean()) & (
                oscillator <= float(p["entryRsi"])
            )
            exit_rule = close > close.shift(1).rolling(int(p["exitSma"])).mean()
        else:
            entry = oscillator <= float(p["entryRsi"])
            exit_rule = oscillator >= float(p["exitRsi"])
        return positions_from_rules(entry, exit_rule)

    if name in {"zscore-reversion", "bollinger-reentry"}:
        period = int(p["period"])
        average = close.shift(1).rolling(period).mean()
        deviation = close.shift(1).rolling(period).std(ddof=0)
        zscore = (close - average) / deviation.replace(0, np.nan)
        return positions_from_rules(
            zscore <= -float(p.get("entryZ", 2)),
            zscore >= 0,
        )

    if name == "trend-pullback":
        trend = close > close.shift(1).rolling(int(p["trendDays"])).mean()
        pullback_average = close.shift(1).rolling(int(p["pullbackDays"])).mean()
        entry = trend & (
            close <= pullback_average * (1 - float(p["dipPct"]) / 100)
        )
        return positions_from_rules(entry, close >= pullback_average)

    if name == "consecutive-down":
        falling = close.diff().lt(0).rolling(int(p["downDays"])).sum() == int(p["downDays"])
        trend = close > close.shift(1).rolling(200).mean()
        return positions_from_rules(
            falling & trend,
            pd.Series(False, index=frame.index),
            int(p["maxHoldDays"]),
        )

    if name in {"stochastic-reversion", "williams-r-reversion"}:
        period = int(p["period"])
        highest = high.shift(1).rolling(period).max()
        lowest = low.shift(1).rolling(period).min()
        oscillator = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
        if name == "stochastic-reversion":
            entry = oscillator <= float(p["entryPct"])
        else:
            entry = oscillator - 100 <= float(p["entry"])
        return positions_from_rules(entry, oscillator >= 60)

    if name == "volume-momentum":
        momentum = close.pct_change(int(p["lookback"]))
        baseline = volume.shift(1).rolling(int(p["volumeDays"])).mean()
        return (
            (momentum > 0)
            & (volume >= baseline * float(p["volumeMultiple"]))
        ).astype(np.int8).to_numpy()

    if name == "obv-trend":
        signed_volume = np.sign(close.diff().fillna(0)) * volume
        obv = signed_volume.cumsum()
        return (
            (obv > obv.shift(1).rolling(int(p["obvDays"])).mean())
            & (close > close.shift(1).rolling(int(p["priceDays"])).mean())
        ).astype(np.int8).to_numpy()

    if name in {"gap-continuation", "overnight-reversal"}:
        gap = open_price / close.shift(1) - 1
        threshold = float(p["gapPct"]) / 100
        entry = (
            (gap >= threshold) & (close > open_price)
            if name == "gap-continuation"
            else (gap <= -threshold) & (close > open_price)
        )
        return positions_from_rules(
            entry,
            pd.Series(False, index=frame.index),
            int(p["holdDays"]),
        )

    if name == "volatility-adjusted-momentum":
        momentum = close.pct_change(int(p["lookback"]))
        volatility = close.pct_change().rolling(int(p["volatilityDays"])).std(ddof=0)
        return (
            momentum / volatility.replace(0, np.nan)
            > float(p["minimumRatio"])
        ).astype(np.int8).to_numpy()

    if name == "low-volatility-trend":
        volatility = close.pct_change().rolling(int(p["volatilityDays"])).std(ddof=0)
        median_volatility = volatility.shift(1).rolling(252).median()
        trend = close > close.shift(1).rolling(int(p["trendDays"])).mean()
        return (trend & (volatility <= median_volatility)).astype(np.int8).to_numpy()

    if name == "relative-strength":
        stock_return = close.pct_change(int(p["lookback"]))
        benchmark_return = benchmark_close.pct_change(int(p["lookback"]))
        return (
            stock_return - benchmark_return > float(p["excessPct"]) / 100
        ).astype(np.int8).to_numpy()

    if name == "turn-of-month":
        dates = pd.DatetimeIndex(frame.index)
        next_month = pd.Series(dates.month, index=frame.index).shift(-1)
        last_day = next_month.notna() & (
            pd.Series(dates.month, index=frame.index) != next_month
        )
        first_days = pd.Series(dates.day, index=frame.index) <= int(p["exitTradingDay"])
        return (last_day | first_days).astype(np.int8).to_numpy()

    if name == "macd-trend":
        fast = close.ewm(span=int(p["fast"]), adjust=False).mean()
        slow = close.ewm(span=int(p["slow"]), adjust=False).mean()
        macd = fast - slow
        signal = macd.ewm(span=int(p["signal"]), adjust=False).mean()
        return ((macd > signal) & (macd > 0)).astype(np.int8).to_numpy()

    raise ValueError(f"unknown strategy: {name}")
