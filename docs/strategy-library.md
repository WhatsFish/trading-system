# Strategy library

The active research library contains 27 distinct long/flat strategy families
and 246 parameter specifications. Across 50 instruments this produces 12,300
daily experiments. Parameter variants are not counted as distinct families.

## Families

| Cluster | Families |
| --- | --- |
| Slow trend and momentum | SMA trend, EMA trend, price/SMA filter, time-series momentum, 52-week-high proximity, volatility-adjusted momentum, low-volatility trend, MACD |
| Breakout and expansion | Donchian, Bollinger breakout, Bollinger squeeze, ATR breakout, range expansion |
| Mean reversion | RSI(2) pullback, RSI reversion, Bollinger re-entry, z-score reversion, trend pullback, consecutive-down reversal, stochastic reversal, Williams %R |
| Volume | Volume-conditioned momentum, OBV trend |
| Session and gap | Gap continuation, overnight reversal |
| Relative and calendar | Relative strength versus SPY, turn of month |

All research signals are formed from completed data. A close-derived signal is
shifted to the next session open in backtests. Breakout channels exclude the
current bar. Parameters are selected on two validation folds; the selected
parameter then has to pass a third untouched holdout fold.

## Provenance

The library uses reproducible implementations inspired by established research
and practitioner sources:

- Moving averages and trading-range breaks: Brock, Lakonishok and LeBaron,
  [working-paper record](https://ideas.repec.org/p/att/wimass/90-22.html).
- Time-series momentum: Moskowitz, Ooi and Pedersen,
  [AQR methodology/data](https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Factors-Monthly).
- 52-week-high momentum: George and Hwang,
  [SSRN record](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1104491).
- RSI(2) trend pullback:
  [StockCharts strategy description](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/rsi-2).
- Bollinger rules and squeeze:
  [official Bollinger rules](https://www.bollingerbands.com/bollinger-band-rules).
- Volume-conditioned momentum: Lee and Swaminathan,
  [RePEc record](https://ideas.repec.org/a/bla/jfinan/v55y2000i5p2017-2069.html).
- Low-volatility effect: Blitz and van Vliet,
  [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=980865).
- Turn of month: McConnell and Xu, *Financial Analysts Journal* 2008.

RSI, MACD, stochastic, Williams %R, ATR, OBV, and simple z-score rules are
treated as experimental technical families, not presumed anomalies. They must
pass the same nested holdout and live-experience gates.

## Deliberately deferred

Opening-range breakout, VWAP reversion and intraday momentum require reliable
historical minute bars and spread data. Pairs/PCA strategies require short
legs, synchronized histories and funding-aware two-leg execution. Historical
earnings strategies require point-in-time announcement timestamps. They are
not approximated with unavailable data.

OKX stock perpetuals trade continuously but can have wider off-hours spreads
and depend on synthetic index components outside cash-market hours. Underlying
equity research therefore does not by itself validate weekend execution:
[OKX stock perpetual documentation](https://www.okx.com/en-us/help/stock-perpetuals).
