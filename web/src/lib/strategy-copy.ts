export type Lang = "zh" | "en";

type Params = Record<string, number>;
type Copy = {
  zh: { name: string; entry: string; exit: string };
  en: { name: string; entry: string; exit: string };
};

const copies: Record<string, (p: Params) => Copy> = {
  "sma-trend": (p) => ({
    zh: { name: "简单均线趋势", entry: `${p.fast} 日均线高于 ${p.slow} 日均线，且价格在两者上方`, exit: `价格或短均线跌回长期趋势线下方` },
    en: { name: "SMA trend", entry: `${p.fast}-day average above ${p.slow}-day average, with price above both`, exit: "Price or the fast average loses the long-term trend" },
  }),
  "ema-trend": (p) => ({
    zh: { name: "指数均线趋势", entry: `${p.fast} 日指数均线高于 ${p.slow} 日指数均线`, exit: "短期指数均线失去长期趋势" },
    en: { name: "EMA trend", entry: `${p.fast}-day EMA above ${p.slow}-day EMA`, exit: "The fast EMA loses the slow trend" },
  }),
  "price-sma-filter": (p) => ({
    zh: { name: "价格趋势过滤", entry: `价格站上 ${p.period} 日均线`, exit: `价格跌破均线${p.exitBufferPct ? `约 ${p.exitBufferPct}%` : ""}` },
    en: { name: "Price/SMA filter", entry: `Price closes above its ${p.period}-day average`, exit: `Price falls ${p.exitBufferPct ? `${p.exitBufferPct}% ` : ""}below the average` },
  }),
  "time-series-momentum": (p) => ({
    zh: { name: "时间序列动量", entry: `过去 ${p.lookback} 日收益高于 ${p.thresholdPct}%`, exit: `同周期收益回落到 ${p.thresholdPct}% 或以下` },
    en: { name: "Time-series momentum", entry: `${p.lookback}-day return exceeds ${p.thresholdPct}%`, exit: `Return over the same horizon falls to ${p.thresholdPct}% or below` },
  }),
  "high-proximity-momentum": (p) => ({
    zh: { name: "接近阶段新高", entry: `价格处于过去 ${p.lookback} 日高点的 ${p.proximityPct}% 以内`, exit: "价格明显远离阶段高点" },
    en: { name: "High-proximity momentum", entry: `Price is within ${100 - p.proximityPct}% of its ${p.lookback}-day high`, exit: "Price moves materially away from the rolling high" },
  }),
  "donchian-breakout": (p) => ({
    zh: { name: "唐奇安通道突破", entry: `突破过去 ${p.entryDays} 日最高价`, exit: `跌破过去 ${p.exitDays} 日最低价` },
    en: { name: "Donchian breakout", entry: `Break above the prior ${p.entryDays}-day high`, exit: `Break below the prior ${p.exitDays}-day low` },
  }),
  "bollinger-breakout": (p) => ({
    zh: { name: "布林带突破", entry: `突破 ${p.period} 日均线以上 ${p.stdDev} 个标准差`, exit: "跌回布林中轨" },
    en: { name: "Bollinger breakout", entry: `Close above the ${p.period}-day band at ${p.stdDev} standard deviations`, exit: "Fall back below the middle band" },
  }),
  "bollinger-squeeze": (p) => ({
    zh: { name: "布林带收缩突破", entry: `波动率处于过去 ${p.bandwidthDays} 日低位后向上突破`, exit: "跌回布林中轨" },
    en: { name: "Bollinger squeeze", entry: `Upside break after volatility compresses versus ${p.bandwidthDays} days`, exit: "Fall back below the middle band" },
  }),
  "atr-breakout": (p) => ({
    zh: { name: "ATR 波动突破", entry: `价格上涨超过 ${p.multiple} 倍 ${p.period} 日平均真实波幅`, exit: "价格出现反向波动扩张" },
    en: { name: "ATR breakout", entry: `Rise exceeds ${p.multiple}× the ${p.period}-day average true range`, exit: "A downside range expansion invalidates the move" },
  }),
  "range-expansion": (p) => ({
    zh: { name: "日内区间扩张", entry: `上涨日振幅超过 ${p.multiple} 倍近期平均振幅`, exit: "收盘弱于前一日" },
    en: { name: "Range expansion", entry: `An up day's range exceeds ${p.multiple}× its recent average`, exit: "Close weakens below the previous close" },
  }),
  "rsi2-pullback": (p) => ({
    zh: { name: "RSI(2) 趋势回调", entry: `长期趋势向上且 RSI(2) 低于 ${p.entryRsi}`, exit: `价格恢复到 ${p.exitSma} 日均线上方` },
    en: { name: "RSI(2) pullback", entry: `Long-term uptrend with RSI(2) at or below ${p.entryRsi}`, exit: `Price recovers above the ${p.exitSma}-day average` },
  }),
  "rsi-reversion": (p) => ({
    zh: { name: "RSI 超卖反转", entry: `${p.period} 日 RSI 低于 ${p.entryRsi}`, exit: `RSI 恢复到 ${p.exitRsi}` },
    en: { name: "RSI reversion", entry: `${p.period}-day RSI falls below ${p.entryRsi}`, exit: `RSI recovers to ${p.exitRsi}` },
  }),
  "bollinger-reentry": (p) => ({
    zh: { name: "布林带回归", entry: `跌出 ${p.period} 日下轨后重新回到带内`, exit: "回到布林中轨" },
    en: { name: "Bollinger re-entry", entry: `Re-enter the ${p.period}-day band after closing below it`, exit: "Return to the middle band" },
  }),
  "zscore-reversion": (p) => ({
    zh: { name: "Z-score 均值回归", entry: `价格低于 ${p.period} 日均值 ${p.entryZ} 个标准差`, exit: "价格回到均值" },
    en: { name: "Z-score reversion", entry: `Price is ${p.entryZ} standard deviations below its ${p.period}-day mean`, exit: "Price returns to the mean" },
  }),
  "trend-pullback": (p) => ({
    zh: { name: "上涨趋势回调", entry: `${p.trendDays} 日趋势向上，价格比 ${p.pullbackDays} 日均线低 ${p.dipPct}%`, exit: "价格恢复到短期均线" },
    en: { name: "Trend pullback", entry: `${p.trendDays}-day uptrend with a ${p.dipPct}% dip below the ${p.pullbackDays}-day average`, exit: "Price recovers to the short average" },
  }),
  "consecutive-down": (p) => ({
    zh: { name: "连续下跌反转", entry: `长期趋势向上但连续下跌 ${p.downDays} 天`, exit: `最多持有 ${p.maxHoldDays} 天` },
    en: { name: "Consecutive-down reversal", entry: `Long-term uptrend after ${p.downDays} consecutive down days`, exit: `Exit after at most ${p.maxHoldDays} days` },
  }),
  "stochastic-reversion": (p) => ({
    zh: { name: "随机指标反转", entry: `${p.period} 日随机指标低于 ${p.entryPct}`, exit: "指标恢复到 60 以上" },
    en: { name: "Stochastic reversion", entry: `${p.period}-day stochastic falls below ${p.entryPct}`, exit: "Oscillator recovers above 60" },
  }),
  "williams-r-reversion": (p) => ({
    zh: { name: "Williams %R 反转", entry: `${p.period} 日 Williams %R 低于 ${p.entry}`, exit: "指标恢复到 -40 以上" },
    en: { name: "Williams %R reversion", entry: `${p.period}-day Williams %R falls below ${p.entry}`, exit: "Oscillator recovers above -40" },
  }),
  "volume-momentum": (p) => ({
    zh: { name: "放量动量", entry: `${p.lookback} 日上涨且成交量超过 ${p.volumeDays} 日均量 ${p.volumeMultiple} 倍`, exit: "价格动量或放量条件消失" },
    en: { name: "Volume momentum", entry: `Positive ${p.lookback}-day return with volume ${p.volumeMultiple}× its ${p.volumeDays}-day average`, exit: "Price or volume confirmation disappears" },
  }),
  "obv-trend": (p) => ({
    zh: { name: "OBV 能量潮趋势", entry: `OBV 高于 ${p.obvDays} 日趋势且价格高于 ${p.priceDays} 日均线`, exit: "量价趋势不再同时成立" },
    en: { name: "OBV trend", entry: `OBV is above its ${p.obvDays}-day trend and price above its ${p.priceDays}-day average`, exit: "Volume and price trends stop agreeing" },
  }),
  "gap-continuation": (p) => ({
    zh: { name: "跳空延续", entry: `高开至少 ${p.gapPct}% 且当天继续上涨`, exit: `持有 ${p.holdDays} 天后退出` },
    en: { name: "Gap continuation", entry: `Gap up at least ${p.gapPct}% and continue higher that day`, exit: `Exit after ${p.holdDays} days` },
  }),
  "overnight-reversal": (p) => ({
    zh: { name: "隔夜下跌反转", entry: `低开至少 ${p.gapPct}% 但当天转强`, exit: `持有 ${p.holdDays} 天后退出` },
    en: { name: "Overnight reversal", entry: `Gap down at least ${p.gapPct}% but recover during the day`, exit: `Exit after ${p.holdDays} days` },
  }),
  "volatility-adjusted-momentum": (p) => ({
    zh: { name: "波动调整动量", entry: `${p.lookback} 日动量相对 ${p.volatilityDays} 日波动率足够强`, exit: "风险调整后的动量低于门槛" },
    en: { name: "Volatility-adjusted momentum", entry: `${p.lookback}-day momentum is strong versus ${p.volatilityDays}-day volatility`, exit: "Risk-adjusted momentum falls below threshold" },
  }),
  "low-volatility-trend": (p) => ({
    zh: { name: "低波动趋势", entry: `价格高于 ${p.trendDays} 日均线且 ${p.volatilityDays} 日波动率较低`, exit: "趋势破坏或波动率升高" },
    en: { name: "Low-volatility trend", entry: `Price above its ${p.trendDays}-day average with low ${p.volatilityDays}-day volatility`, exit: "Trend breaks or volatility rises" },
  }),
  "relative-strength": (p) => ({
    zh: { name: "相对标普强势", entry: `过去 ${p.lookback} 日跑赢 SPY 至少 ${p.excessPct}%`, exit: `相对收益回落到 ${p.excessPct}% 或以下` },
    en: { name: "Relative strength vs SPY", entry: `Outperform SPY by at least ${p.excessPct}% over ${p.lookback} days`, exit: `Relative outperformance falls to ${p.excessPct}% or below` },
  }),
  "turn-of-month": (p) => ({
    zh: { name: "月末月初效应", entry: "月末最后一个交易日进入", exit: `新月第 ${p.exitTradingDay} 个交易日前后退出` },
    en: { name: "Turn of month", entry: "Enter around the final trading day of the month", exit: `Exit around trading day ${p.exitTradingDay} of the new month` },
  }),
  "macd-trend": (p) => ({
    zh: { name: "MACD 趋势", entry: `MACD(${p.fast}, ${p.slow}, ${p.signal}) 向上且位于零轴上方`, exit: "MACD 跌破信号线或零轴" },
    en: { name: "MACD trend", entry: `MACD(${p.fast}, ${p.slow}, ${p.signal}) is bullish and above zero`, exit: "MACD loses its signal line or zero level" },
  }),
};

export function strategyCopy(family: string, parameters: Params, lang: Lang) {
  const factory = copies[family];
  if (!factory) {
    return {
      name: family.replaceAll("-", " "),
      entry: lang === "zh" ? "满足该策略的入场条件" : "The strategy entry condition is met",
      exit: lang === "zh" ? "策略条件失效时退出" : "Exit when the strategy is invalidated",
    };
  }
  return factory(parameters)[lang];
}

export const ui = {
  zh: {
    title: "交易系统",
    subtitle: "真实账户 · 自动策略 · 风控与复盘",
    live: "真实交易运行中",
    locked: "新开仓已暂停",
    equity: "账户总权益",
    available: "可用 USDT",
    exposure: "系统仓位",
    slots: "系统持仓槽位",
    positions: "当前真实持仓",
    noPositions: "当前没有持仓",
    manual: "手动持仓",
    managed: "系统持仓",
    trend24h: "24 小时涨跌",
    pnl: "未实现盈亏",
    entryStrategy: "买入策略",
    exitRule: "卖出条件",
    stop: "保护止损",
    next: "下一步最可能买入",
    nextHelp: "按候选分数排序，只展示当前建议持有的股票。预计金额是风险预算；实际下单仍需通过价格、基差、事件和账户风控。",
    estimated: "预计金额",
    ready: "等待市场与风控",
    blocked: "当前被拦截",
    experience: "真实交易经验",
    noExperience: "系统还没有完成第一笔真实策略交易。",
    research: "研究与诊断",
    candidates: "全部优质策略候选",
    diagnostics: "基差、回测、事件、执行记录和新闻",
    premarket: "盘前",
    regular: "常规交易",
    afterHours: "盘后",
    closed: "休市",
    reference: "参考价",
  },
  en: {
    title: "Trading System",
    subtitle: "Live account · systematic strategies · risk and lessons",
    live: "Live trading active",
    locked: "New entries paused",
    equity: "Account equity",
    available: "Available USDT",
    exposure: "System exposure",
    slots: "System slots",
    positions: "Current live positions",
    noPositions: "No open positions",
    manual: "Manual position",
    managed: "System position",
    trend24h: "24h change",
    pnl: "Unrealized PnL",
    entryStrategy: "Entry strategy",
    exitRule: "Exit condition",
    stop: "Protective stop",
    next: "Most likely next purchases",
    nextHelp: "Ranked by candidate score and limited to current long targets. Estimated amount is a risk budget; price, basis, event, and account checks still apply.",
    estimated: "Estimated amount",
    ready: "Waiting for market and risk checks",
    blocked: "Currently blocked",
    experience: "Live trading experience",
    noExperience: "The system has not completed its first live strategy trade.",
    research: "Research and diagnostics",
    candidates: "All quality strategy candidates",
    diagnostics: "Basis, backtests, events, execution audit, and news",
    premarket: "Premarket",
    regular: "Regular session",
    afterHours: "After hours",
    closed: "Market closed",
    reference: "reference",
  },
} as const;
