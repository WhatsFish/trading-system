export const INSTRUMENTS = [
  "SPY", "QQQ", "SMH", "XBI", "AAPL", "ADBE", "AMZN", "APP", "CRM", "CRWD",
  "CSCO", "DELL", "GOOGL", "IBM", "META", "MSFT", "NET", "NFLX", "NOW", "OKTA",
  "ORCL", "PLTR", "SHOP", "SNOW", "TWLO", "VRT", "AMD", "AMAT", "ARM", "ASML",
  "AVGO", "CRDO", "INTC", "KLAC", "LRCX", "MRVL", "MU", "NVDA", "QCOM", "SMCI",
  "TSM", "WDC", "HIMS", "ISRG", "JNJ", "LLY", "MRK", "MRNA", "OSCR", "UNH",
].map((symbol) => `${symbol}-USDT-SWAP`);

export type Budget = { mode: "percent" | "fixed_usdt"; value: number };
export type PortfolioConfig = {
  maxHoldings: number;
  maxPerAssetGroup: number;
  maxPerStrategyCluster: number;
  totalBudgetMode: "legacy_equity" | "account_equity" | "fixed_usdt";
  totalBudgetUsdt: number;
  positionBudgetMode: Budget["mode"];
  positionBudgetValue: number;
  cashReserveUsdt: number;
  instrumentBudgets: Record<string, Budget>;
};
export const DEFAULT_CONFIG: PortfolioConfig = {
  maxHoldings: 5, maxPerAssetGroup: 2, maxPerStrategyCluster: 2,
  totalBudgetMode: "legacy_equity", totalBudgetUsdt: 0,
  positionBudgetMode: "percent", positionBudgetValue: 18,
  cashReserveUsdt: 0, instrumentBudgets: {},
};
export class PortfolioError extends Error {
  constructor(message: string, public status = 400) { super(message); }
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new PortfolioError("invalid_object");
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, expected: string[]) {
  if (Object.keys(value).sort().join() !== [...expected].sort().join()) throw new PortfolioError("invalid_fields");
}
function amount(value: unknown, name: string, max = 1e9): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > max) throw new PortfolioError(`invalid_${name}`);
  return value;
}
function budget(mode: unknown, value: unknown): Budget {
  if (mode !== "percent" && mode !== "fixed_usdt") throw new PortfolioError("invalid_position_mode");
  const n = amount(value, "position_value", mode === "percent" ? 100 : 1e9);
  if (n === 0) throw new PortfolioError("position_value_must_be_positive");
  return { mode, value: n };
}
export function validateConfig(input: unknown): PortfolioConfig {
  const c = object(input);
  keys(c, Object.keys(DEFAULT_CONFIG));
  const maxHoldings = amount(c.maxHoldings, "max_holdings", 50);
  if (!Number.isInteger(maxHoldings) || maxHoldings < 1) throw new PortfolioError("invalid_max_holdings");
  const count = (key: "maxPerAssetGroup" | "maxPerStrategyCluster") => {
    const n = amount(c[key], key, 50);
    if (!Number.isInteger(n) || n < 1) throw new PortfolioError(`invalid_${key}`);
    return n;
  };
  const maxPerAssetGroup = count("maxPerAssetGroup");
  const maxPerStrategyCluster = count("maxPerStrategyCluster");
  const totalBudgetMode = c.totalBudgetMode;
  if (typeof totalBudgetMode !== "string" || !["legacy_equity", "account_equity", "fixed_usdt"].includes(totalBudgetMode)) throw new PortfolioError("invalid_total_mode");
  const totalBudgetUsdt = amount(c.totalBudgetUsdt, "total_budget");
  const cashReserveUsdt = amount(c.cashReserveUsdt, "cash_reserve");
  if (totalBudgetMode === "fixed_usdt" ? totalBudgetUsdt <= cashReserveUsdt : totalBudgetUsdt !== 0) throw new PortfolioError("invalid_total_reserve");
  const position = budget(c.positionBudgetMode, c.positionBudgetValue);
  const overrides = object(c.instrumentBudgets);
  if (Object.keys(overrides).length > 50) throw new PortfolioError("too_many_overrides");
  const instrumentBudgets: Record<string, Budget> = {};
  for (const [instrument, entry] of Object.entries(overrides)) {
    if (!INSTRUMENTS.includes(instrument)) throw new PortfolioError("unknown_instrument");
    const b = object(entry);
    keys(b, ["mode", "value"]);
    instrumentBudgets[instrument] = budget(b.mode, b.value);
  }
  return { maxHoldings, maxPerAssetGroup, maxPerStrategyCluster,
    totalBudgetMode: totalBudgetMode as PortfolioConfig["totalBudgetMode"],
    totalBudgetUsdt, cashReserveUsdt, positionBudgetMode: position.mode,
    positionBudgetValue: position.value, instrumentBudgets };
}
export type PortfolioSnapshot = {
  id: string; ts: string; equity: number; available: number;
  exposures: Record<string, number>; held: string[]; pending: boolean;
};
export function positionLimit(config: PortfolioConfig, equity: number, instrument: string, revision = 1) {
  const base = config.totalBudgetMode === "fixed_usdt" ? Math.min(equity, config.totalBudgetUsdt) : equity;
  const b = config.instrumentBudgets[instrument] ?? { mode: config.positionBudgetMode, value: config.positionBudgetValue };
  return Math.max(0, Math.min(revision === 0 ? equity * .18 : base, b.mode === "percent" ? base * b.value / 100 : b.value));
}
export function limits(config: PortfolioConfig, snapshot: PortfolioSnapshot, revision: number) {
  const { equity, available, exposures } = snapshot;
  if (![equity, available, ...Object.values(exposures)].every(Number.isFinite) || equity <= 0 ||
      Object.values(exposures).some((n) => n < 0)) throw new PortfolioError("invalid_account_snapshot", 503);
  const base = config.totalBudgetMode === "fixed_usdt" ? Math.min(equity, config.totalBudgetUsdt) : equity;
  const gross = config.totalBudgetMode === "legacy_equity" ? equity * 2 : base;
  const total = Math.max(0, Math.min(gross, equity * 2) - config.cashReserveUsdt);
  const symbolLimit = (instrument: string) => positionLimit(config, equity, instrument, revision);
  const exposure = Object.values(exposures).reduce((sum, n) => sum + n, 0);
  const overPositions = revision > 0 ? Object.keys(exposures).filter((i) => exposures[i] > symbolLimit(i)) : [];
  const heldCount = new Set(snapshot.held).size;
  const remaining = Math.max(0, Math.min(total - exposure, available - config.cashReserveUsdt));
  const warnings: string[] = [];
  if (config.totalBudgetMode === "fixed_usdt" && config.totalBudgetUsdt > equity) warnings.push("insufficient_equity");
  if (available <= config.cashReserveUsdt) warnings.push("reserve_exceeds_available");
  if (heldCount > config.maxHoldings) warnings.push("holdings_over_cap");
  if (exposure > total) warnings.push("total_over_budget");
  if (overPositions.length) warnings.push("positions_over_budget");
  if (snapshot.pending) warnings.push("pending_entries");
  if (config.maxHoldings > 4 * config.maxPerAssetGroup) warnings.push("group_cluster_caps");
  if (config.maxPerAssetGroup > 2 || config.maxPerStrategyCluster > 2) warnings.push("concentration_caps_raised");
  return {
    maxHoldings: config.maxHoldings, maxPerAssetGroup: config.maxPerAssetGroup,
    maxPerStrategyCluster: config.maxPerStrategyCluster,
    percentageBaseUsdt: base, totalNotionalUsdt: total,
    defaultPositionUsdt: symbolLimit(""), exposureUsdt: exposure,
    availableUsdt: available, reserveUsdt: config.cashReserveUsdt, remainingUsdt: remaining,
    heldCount, openSlots: Math.max(0, config.maxHoldings - heldCount),
    entryBlocked: snapshot.pending || heldCount >= config.maxHoldings || exposure > total || overPositions.length > 0 || remaining <= 0,
    overPositions, warnings,
    instrumentLimits: Object.fromEntries(INSTRUMENTS.map((i) => [i, symbolLimit(i)])),
  };
}
export const CONFIRMATION = "CONFIRM_PORTFOLIO_LIMITS";
