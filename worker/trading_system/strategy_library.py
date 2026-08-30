from dataclasses import dataclass
import datetime as dt
import itertools
import math
from decimal import Decimal


@dataclass(frozen=True)
class StrategySpec:
    name: str
    cluster: str
    parameters: dict[str, int | float]


def strategy_specs() -> list[StrategySpec]:
    specs: list[StrategySpec] = []

    def add(name: str, cluster: str, rows) -> None:
        specs.extend(StrategySpec(name, cluster, parameters) for parameters in rows)

    add("sma-trend", "slow-trend", (
        {"fast": fast, "slow": slow}
        for fast, slow in itertools.product((5, 10, 20, 30), (50, 100, 150, 200))
        if fast < slow
    ))
    add("ema-trend", "slow-trend", (
        {"fast": fast, "slow": slow}
        for fast, slow in itertools.product((5, 10, 20), (50, 100, 200))
    ))
    add("price-sma-filter", "slow-trend", (
        {"period": period, "exitBufferPct": buffer}
        for period, buffer in itertools.product((50, 100, 150, 200), (0, 2))
    ))
    add("time-series-momentum", "slow-trend", (
        {"lookback": lookback, "thresholdPct": threshold}
        for lookback, threshold in itertools.product((60, 120, 252), (0, 5))
    ))
    add("high-proximity-momentum", "slow-trend", (
        {"lookback": lookback, "proximityPct": proximity}
        for lookback, proximity in itertools.product((120, 252), (95, 98, 99))
    ))
    add("donchian-breakout", "breakout", (
        {"entryDays": entry, "exitDays": exit_days}
        for entry, exit_days in itertools.product((20, 40, 60), (5, 10, 20))
        if exit_days < entry
    ))
    add("bollinger-breakout", "breakout", (
        {"period": period, "stdDev": deviation}
        for period, deviation in itertools.product((20, 40, 60), (1.5, 2.0, 2.5))
    ))
    add("bollinger-squeeze", "breakout", (
        {"period": 20, "bandwidthDays": days, "quantilePct": quantile}
        for days, quantile in itertools.product((60, 120, 180), (10, 20))
    ))
    add("atr-breakout", "breakout", (
        {"period": period, "multiple": multiple}
        for period, multiple in itertools.product((14, 20, 30), (1.0, 1.5, 2.0))
    ))
    add("range-expansion", "breakout", (
        {"period": period, "multiple": multiple}
        for period, multiple in itertools.product((10, 20, 40), (1.2, 1.5, 2.0))
    ))
    add("rsi2-pullback", "mean-reversion", (
        {"entryRsi": entry, "exitSma": exit_sma}
        for entry, exit_sma in itertools.product((5, 10, 15), (3, 5, 10))
    ))
    add("rsi-reversion", "mean-reversion", (
        {"period": period, "entryRsi": entry, "exitRsi": exit_rsi}
        for period, entry, exit_rsi in itertools.product((7, 14, 21), (20, 30), (50, 60))
    ))
    add("bollinger-reentry", "mean-reversion", (
        {"period": period, "stdDev": deviation}
        for period, deviation in itertools.product((20, 40, 60), (1.5, 2.0, 2.5))
    ))
    add("zscore-reversion", "mean-reversion", (
        {"period": period, "entryZ": entry}
        for period, entry in itertools.product((10, 20, 40, 60), (1.5, 2.0, 2.5))
    ))
    add("trend-pullback", "mean-reversion", (
        {"trendDays": trend, "pullbackDays": pullback, "dipPct": dip}
        for trend, pullback, dip in itertools.product((100, 200), (10, 20), (2, 4, 6))
    ))
    add("consecutive-down", "mean-reversion", (
        {"downDays": down, "maxHoldDays": hold}
        for down, hold in itertools.product((2, 3, 4, 5), (2, 5, 10))
    ))
    add("stochastic-reversion", "mean-reversion", (
        {"period": period, "entryPct": entry}
        for period, entry in itertools.product((5, 14, 21), (10, 20, 30))
    ))
    add("williams-r-reversion", "mean-reversion", (
        {"period": period, "entry": entry}
        for period, entry in itertools.product((7, 14, 28), (-80, -90))
    ))
    add("volume-momentum", "volume", (
        {"lookback": lookback, "volumeDays": volume_days, "volumeMultiple": multiple}
        for lookback, volume_days, multiple in itertools.product(
            (20, 60, 120), (20, 50), (1.2, 1.5)
        )
    ))
    add("obv-trend", "volume", (
        {"obvDays": obv_days, "priceDays": price_days}
        for obv_days, price_days in itertools.product((20, 50, 100), (50, 100))
    ))
    add("gap-continuation", "session-gap", (
        {"gapPct": gap, "holdDays": hold}
        for gap, hold in itertools.product((1, 2, 3), (3, 5, 10))
    ))
    add("overnight-reversal", "session-gap", (
        {"gapPct": gap, "holdDays": hold}
        for gap, hold in itertools.product((1, 2, 3), (1, 2, 3))
    ))
    add("volatility-adjusted-momentum", "slow-trend", (
        {"lookback": lookback, "volatilityDays": vol_days, "minimumRatio": ratio}
        for lookback, vol_days, ratio in itertools.product(
            (60, 120, 252), (20, 60), (0.5, 1.0)
        )
    ))
    add("low-volatility-trend", "slow-trend", (
        {"volatilityDays": vol_days, "trendDays": trend}
        for vol_days, trend in itertools.product((20, 60, 120), (50, 100, 200))
    ))
    add("relative-strength", "relative-strength", (
        {"lookback": lookback, "excessPct": excess}
        for lookback, excess in itertools.product((20, 60, 120, 252), (0, 2, 5))
    ))
    add("turn-of-month", "calendar", (
        {"exitTradingDay": day} for day in (2, 3, 4, 5)
    ))
    add("macd-trend", "slow-trend", (
        {"fast": fast, "slow": slow, "signal": signal}
        for fast, slow, signal in (
            (8, 21, 5), (12, 26, 9), (16, 35, 9),
            (5, 35, 5), (10, 30, 7), (20, 50, 10),
        )
    ))
    return specs


def mean(values: list[Decimal]) -> Decimal:
    return sum(values) / Decimal(len(values))


def stddev(values: list[Decimal]) -> Decimal:
    average = mean(values)
    variance = sum((value - average) ** 2 for value in values) / Decimal(len(values))
    return Decimal(str(math.sqrt(float(variance))))


def ema(values: list[Decimal], period: int) -> Decimal:
    if not values:
        return Decimal("0")
    alpha = Decimal(2) / Decimal(period + 1)
    result = values[0]
    for value in values[1:]:
        result += alpha * (value - result)
    return result


def ema_series(values: list[Decimal], period: int) -> list[Decimal]:
    if not values:
        return []
    alpha = Decimal(2) / Decimal(period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(output[-1] + alpha * (value - output[-1]))
    return output


def rsi(values: list[Decimal], period: int) -> Decimal:
    if len(values) <= period:
        return Decimal("50")
    changes = [values[i] - values[i - 1] for i in range(len(values) - period, len(values))]
    gains = sum(max(change, Decimal("0")) for change in changes)
    losses = sum(max(-change, Decimal("0")) for change in changes)
    if losses == 0:
        return Decimal("100")
    relative = gains / losses
    return Decimal("100") - Decimal("100") / (Decimal("1") + relative)


def atr(bars: list[dict], end: int, period: int) -> Decimal:
    ranges = []
    for index in range(end - period, end):
        previous = Decimal(bars[index - 1]["close"])
        high = Decimal(bars[index]["high"])
        low = Decimal(bars[index]["low"])
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    return mean(ranges)


def percentile(values: list[Decimal], value: Decimal) -> Decimal:
    if not values:
        return Decimal("0.5")
    return Decimal(sum(item <= value for item in values)) / Decimal(len(values))


def generate_targets(
    bars: list[dict],
    spec: StrategySpec,
    benchmark_bars: list[dict] | None = None,
) -> list[int]:
    closes = [Decimal(row["close"]) for row in bars]
    opens = [Decimal(row["open"]) for row in bars]
    highs = [Decimal(row["high"]) for row in bars]
    lows = [Decimal(row["low"]) for row in bars]
    volumes = [Decimal(row.get("volume") or "0") for row in bars]
    dates = [row["date"] for row in bars]
    benchmark = (
        [Decimal(row["close"]) for row in benchmark_bars]
        if benchmark_bars and len(benchmark_bars) == len(bars)
        else closes
    )
    output = [0] * len(bars)
    position = 0
    days_held = 0
    previous_outside_lower = False
    macd_values: list[Decimal] | None = None
    macd_signal: list[Decimal] | None = None
    if spec.name == "macd-trend":
        fast_series = ema_series(closes, int(spec.parameters["fast"]))
        slow_series = ema_series(closes, int(spec.parameters["slow"]))
        macd_values = [
            fast_value - slow_value
            for fast_value, slow_value in zip(fast_series, slow_series)
        ]
        macd_signal = ema_series(macd_values, int(spec.parameters["signal"]))

    for index in range(2, len(bars)):
        name = spec.name
        p = spec.parameters
        close = closes[index]
        prior_close = closes[index - 1]
        if position:
            days_held += 1

        if name in {"sma-trend", "ema-trend"}:
            fast, slow = int(p["fast"]), int(p["slow"])
            if index >= slow:
                fast_value = (
                    ema(closes[index - slow : index + 1], fast)
                    if name == "ema-trend"
                    else mean(closes[index - fast + 1 : index + 1])
                )
                slow_value = (
                    ema(closes[index - slow : index + 1], slow)
                    if name == "ema-trend"
                    else mean(closes[index - slow + 1 : index + 1])
                )
                position = int(close > fast_value > slow_value)
        elif name == "price-sma-filter":
            period = int(p["period"])
            if index >= period:
                average = mean(closes[index - period : index])
                exit_level = average * (Decimal("1") - Decimal(str(p["exitBufferPct"])) / 100)
                position = 1 if close > average else 0 if close < exit_level else position
        elif name == "time-series-momentum":
            lookback = int(p["lookback"])
            if index >= lookback:
                threshold = Decimal(str(p["thresholdPct"])) / 100
                position = int(close / closes[index - lookback] - 1 > threshold)
        elif name == "high-proximity-momentum":
            lookback = int(p["lookback"])
            if index >= lookback:
                proximity = Decimal(str(p["proximityPct"])) / 100
                position = int(close >= max(highs[index - lookback : index]) * proximity)
        elif name == "donchian-breakout":
            entry, exit_days = int(p["entryDays"]), int(p["exitDays"])
            if index >= entry:
                if not position and close > max(highs[index - entry : index]):
                    position = 1
                elif position and close < min(lows[index - exit_days : index]):
                    position = 0
        elif name in {"bollinger-breakout", "bollinger-reentry"}:
            period = int(p["period"])
            if index >= period:
                window = closes[index - period : index]
                average = mean(window)
                deviation = stddev(window) * Decimal(str(p["stdDev"]))
                lower, upper = average - deviation, average + deviation
                if name == "bollinger-breakout":
                    position = 1 if close > upper else 0 if close < average else position
                else:
                    if not position and previous_outside_lower and close > lower:
                        position = 1
                    elif position and close >= average:
                        position = 0
                    previous_outside_lower = close < lower
        elif name == "bollinger-squeeze":
            period, history = int(p["period"]), int(p["bandwidthDays"])
            if index >= period + history:
                widths = []
                for end in range(index - history, index):
                    window = closes[end - period : end]
                    average = mean(window)
                    widths.append(stddev(window) * 4 / average)
                current_window = closes[index - period : index]
                average = mean(current_window)
                deviation = stddev(current_window) * 2
                threshold = sorted(widths)[max(0, int(len(widths) * float(p["quantilePct"]) / 100) - 1)]
                current_width = deviation * 2 / average
                position = 1 if current_width <= threshold and close > average + deviation else 0 if close < average else position
        elif name in {"atr-breakout", "range-expansion"}:
            period = int(p["period"])
            if index > period:
                measure = atr(bars, index, period)
                multiple = Decimal(str(p["multiple"]))
                if name == "atr-breakout":
                    position = 1 if close > prior_close + measure * multiple else 0 if close < prior_close - measure else position
                else:
                    today_range = highs[index] - lows[index]
                    direction_up = close > opens[index]
                    position = 1 if direction_up and today_range > measure * multiple else 0 if close < prior_close else position
        elif name in {"rsi2-pullback", "rsi-reversion"}:
            period = 2 if name == "rsi2-pullback" else int(p["period"])
            if index >= max(200, period + 1):
                current_rsi = rsi(closes[: index + 1], period)
                if name == "rsi2-pullback":
                    trend = close > mean(closes[index - 200 : index])
                    if not position and trend and current_rsi <= Decimal(str(p["entryRsi"])):
                        position = 1
                    elif position and close > mean(closes[index - int(p["exitSma"]) : index]):
                        position = 0
                else:
                    position = 1 if not position and current_rsi <= Decimal(str(p["entryRsi"])) else 0 if position and current_rsi >= Decimal(str(p["exitRsi"])) else position
        elif name == "zscore-reversion":
            period = int(p["period"])
            if index >= period:
                window = closes[index - period : index]
                deviation = stddev(window)
                zscore = (close - mean(window)) / deviation if deviation else Decimal("0")
                position = 1 if not position and zscore <= -Decimal(str(p["entryZ"])) else 0 if position and zscore >= 0 else position
        elif name == "trend-pullback":
            trend_days, pullback_days = int(p["trendDays"]), int(p["pullbackDays"])
            if index >= trend_days:
                trend = close > mean(closes[index - trend_days : index])
                pullback = close <= mean(closes[index - pullback_days : index]) * (1 - Decimal(str(p["dipPct"])) / 100)
                position = 1 if not position and trend and pullback else 0 if position and close >= mean(closes[index - pullback_days : index]) else position
        elif name == "consecutive-down":
            down_days = int(p["downDays"])
            if index >= max(200, down_days):
                falling = all(closes[j] < closes[j - 1] for j in range(index - down_days + 1, index + 1))
                trend = close > mean(closes[index - 200 : index])
                if not position and trend and falling:
                    position, days_held = 1, 0
                elif position and days_held >= int(p["maxHoldDays"]):
                    position, days_held = 0, 0
        elif name in {"stochastic-reversion", "williams-r-reversion"}:
            period = int(p["period"])
            if index >= period:
                highest, lowest = max(highs[index - period : index]), min(lows[index - period : index])
                oscillator = (close - lowest) / (highest - lowest) * 100 if highest != lowest else Decimal("50")
                if name == "stochastic-reversion":
                    position = 1 if not position and oscillator <= Decimal(str(p["entryPct"])) else 0 if position and oscillator >= 60 else position
                else:
                    williams = oscillator - 100
                    position = 1 if not position and williams <= Decimal(str(p["entry"])) else 0 if position and williams >= -40 else position
        elif name == "volume-momentum":
            lookback, volume_days = int(p["lookback"]), int(p["volumeDays"])
            if index >= max(lookback, volume_days):
                momentum = close / closes[index - lookback] - 1
                relative_volume = volumes[index] / mean(volumes[index - volume_days : index]) if mean(volumes[index - volume_days : index]) else 0
                position = int(momentum > 0 and relative_volume >= Decimal(str(p["volumeMultiple"])))
        elif name == "obv-trend":
            obv_days, price_days = int(p["obvDays"]), int(p["priceDays"])
            if index >= max(obv_days, price_days):
                obv = []
                total = Decimal("0")
                for j in range(index - obv_days, index + 1):
                    total += volumes[j] if closes[j] > closes[j - 1] else -volumes[j] if closes[j] < closes[j - 1] else 0
                    obv.append(total)
                position = int(obv[-1] > mean(obv) and close > mean(closes[index - price_days : index]))
        elif name in {"gap-continuation", "overnight-reversal"}:
            gap = opens[index] / prior_close - 1
            threshold = Decimal(str(p["gapPct"])) / 100
            if not position:
                continuation = name == "gap-continuation" and gap >= threshold and close > opens[index]
                reversal = name == "overnight-reversal" and gap <= -threshold and close > opens[index]
                if continuation or reversal:
                    position, days_held = 1, 0
            elif days_held >= int(p["holdDays"]):
                position = 0
        elif name == "volatility-adjusted-momentum":
            lookback, vol_days = int(p["lookback"]), int(p["volatilityDays"])
            if index >= max(lookback, vol_days) + 1:
                momentum = close / closes[index - lookback] - 1
                returns = [closes[j] / closes[j - 1] - 1 for j in range(index - vol_days + 1, index + 1)]
                volatility = stddev(returns)
                ratio = momentum / volatility if volatility else Decimal("0")
                position = int(ratio > Decimal(str(p["minimumRatio"])))
        elif name == "low-volatility-trend":
            vol_days, trend_days = int(p["volatilityDays"]), int(p["trendDays"])
            if index >= max(vol_days, trend_days) + 1:
                returns = [closes[j] / closes[j - 1] - 1 for j in range(index - vol_days + 1, index + 1)]
                recent_vol = stddev(returns)
                rolling_volatility = []
                history_start = max(vol_days + 1, index - 252)
                for end in range(history_start, index):
                    sample = [
                        closes[j] / closes[j - 1] - 1
                        for j in range(end - vol_days + 1, end + 1)
                    ]
                    rolling_volatility.append(stddev(sample))
                threshold = (
                    sorted(rolling_volatility)[len(rolling_volatility) // 2]
                    if rolling_volatility
                    else recent_vol
                )
                position = int(
                    close > mean(closes[index - trend_days : index])
                    and recent_vol <= threshold
                )
        elif name == "relative-strength":
            lookback = int(p["lookback"])
            if index >= lookback:
                stock_return = close / closes[index - lookback] - 1
                benchmark_return = benchmark[index] / benchmark[index - lookback] - 1
                position = int(stock_return - benchmark_return > Decimal(str(p["excessPct"])) / 100)
        elif name == "turn-of-month":
            date = dates[index]
            next_date = dates[index + 1] if index + 1 < len(dates) else date
            first_index = index
            while (
                first_index > 0
                and dates[first_index - 1].year == date.year
                and dates[first_index - 1].month == date.month
            ):
                first_index -= 1
            trading_day = index - first_index + 1
            first_days = trading_day <= int(p["exitTradingDay"])
            last_day = next_date.month != date.month
            position = 1 if last_day or first_days else 0
        elif name == "macd-trend":
            slow = int(p["slow"])
            if index >= slow + int(p["signal"]):
                position = int(
                    macd_values is not None
                    and macd_signal is not None
                    and macd_values[index] > macd_signal[index]
                    and macd_values[index] > 0
                )
        else:
            raise ValueError(f"unknown strategy: {name}")
        output[index] = position
    return output
