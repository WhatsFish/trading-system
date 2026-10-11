import { limits, type PortfolioConfig, type PortfolioSnapshot } from "./portfolio";
import { add, compare, decimal, div, floorLot, min, mul, positive, sub, text, type Decimal } from "./allocation-decimal";

export type AllocationHolding = {
  instrument: string;
  strategy: string;
  parameters: Record<string, unknown>;
  ownedQuantity: string;
  accountPositions: { side: string; size: string }[];
  market: { ts: string; price: string; state: string | null } | null;
  signal: { family: string; parameters: Record<string, unknown>; target: number; computedAt: string } | null;
  // Both sizes must be expressed in owned_quantity's base-asset units.
  sizeRules: { lot: string; minimum: string } | null;
  exitPending: boolean;
};
export type AllocationInput = {
  config: PortfolioConfig;
  revision: number;
  snapshot: PortfolioSnapshot;
  exactAmounts?: { equity: string; available: string; exposures: string[] };
  controller: { lastSeenAt: string; revision: number | null; settingsError: boolean } | null;
  holdings: AllocationHolding[];
  now?: number;
};
const zero = () => decimal(0);
const sum = (values: Decimal[]) => values.reduce(add, zero());
const fresh = (ts: string, age: number, now: number) => {
  const time = new Date(ts).getTime();
  return Number.isFinite(time) && time <= now + 30_000 && now - time <= age;
};
function canonical(value: unknown): string {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return JSON.stringify(Object.keys(value).sort().map((key) => [key, canonical((value as Record<string, unknown>)[key])]));
  }
  return JSON.stringify(value);
}
function nonnegative(value: string | number): Decimal {
  const n = decimal(value);
  if (compare(n, zero()) < 0) throw new Error("negative_input");
  return n;
}
function strictlyPositive(value: string): Decimal {
  const n = nonnegative(value);
  if (compare(n, zero()) === 0) throw new Error("zero_input");
  return n;
}
export type AllocationReason =
  | "account_stale" | "controller_stale" | "revision_mismatch" | "pending_orders"
  | "market_unavailable" | "ownership_mismatch" | "signal_unavailable"
  | "exit_pending" | "size_rules_unavailable" | "below_minimum" | "pooled"
  | "decrease_only" | "at_ceiling" | "invalid_position";
export type AllocationRow = {
  instrument: string; strategy: string; ownedQuantity: string;
  currentUsdt: string | null; ceilingUsdt: string;
  strategyTarget: 0 | 1 | null; targetUsdt: string | null;
  increaseUsdt: string | null; decreaseUsdt: string | null;
  quantity: string | null; quantityNotionalUsdt: string | null;
  reasons: AllocationReason[];
};

export function allocationPreview(input: AllocationInput) {
  const { config, snapshot, revision } = input;
  const now = input.now ?? Date.now();
  const summary = limits(config, snapshot, revision);
  const equity = nonnegative(input.exactAmounts?.equity ?? snapshot.equity);
  const reserve = nonnegative(config.cashReserveUsdt);
  const available = decimal(input.exactAmounts?.available ?? snapshot.available);
  const base = config.totalBudgetMode === "fixed_usdt" ? min(equity, decimal(config.totalBudgetUsdt)) : equity;
  const total = positive(sub(config.totalBudgetMode === "legacy_equity" ? mul(equity, decimal(2)) : base, reserve));
  const exposure = sum((input.exactAmounts?.exposures ?? Object.values(snapshot.exposures)).map(nonnegative));
  const pool = positive(min(sub(available, reserve), sub(total, exposure)));
  const blockers: AllocationReason[] = [];
  if (!fresh(snapshot.ts, 180_000, now)) blockers.push("account_stale");
  if (!input.controller || !fresh(input.controller.lastSeenAt, 180_000, now)) blockers.push("controller_stale");
  if (!input.controller || input.controller.revision !== revision || input.controller.settingsError) blockers.push("revision_mismatch");
  if (snapshot.pending) blockers.push("pending_orders");
  const entries = input.holdings.map((holding) => {
    const budget = config.instrumentBudgets[holding.instrument] ?? { mode: config.positionBudgetMode, value: config.positionBudgetValue };
    const configured = budget.mode === "percent" ? div(mul(base, decimal(budget.value)), decimal(100)) : decimal(budget.value);
    const ceiling = min(revision === 0 ? div(mul(equity, decimal(18)), decimal(100)) : base, configured);
    const row: AllocationRow = {
      instrument: holding.instrument, strategy: holding.strategy, ownedQuantity: holding.ownedQuantity,
      currentUsdt: null, ceilingUsdt: text(ceiling), strategyTarget: null, targetUsdt: null,
      increaseUsdt: null, decreaseUsdt: null, quantity: null, quantityNotionalUsdt: null, reasons: [...blockers],
    };
    let price = zero(), gap = zero(), decrease = zero();
    try {
      const owned = strictlyPositive(holding.ownedQuantity);
      const positions = holding.accountPositions.filter((p) => compare(decimal(p.size), zero()) !== 0);
      if (positions.length !== 1 || positions[0].side !== "long" || compare(decimal(positions[0].size), owned) !== 0) {
        row.reasons.push("ownership_mismatch");
      }
      const market = holding.market;
      if (!market || !fresh(market.ts, 180_000, now) || market.state !== "live") row.reasons.push("market_unavailable");
      else {
        price = strictlyPositive(market.price);
        row.currentUsdt = text(mul(owned, price));
      }
      const signal = holding.signal;
      if (!signal || signal.family !== holding.strategy || canonical(signal.parameters) !== canonical(holding.parameters) ||
          !fresh(signal.computedAt, 4 * 86_400_000, now) || (signal.target !== 0 && signal.target !== 1)) {
        row.reasons.push("signal_unavailable");
      } else row.strategyTarget = signal.target;
      if (holding.exitPending) row.reasons.push("exit_pending");
      if (!row.reasons.length && row.strategyTarget !== null && row.currentUsdt !== null) {
        const target = row.strategyTarget === 1 ? ceiling : zero();
        row.targetUsdt = text(target);
        gap = positive(sub(target, mul(owned, price)));
        decrease = positive(sub(mul(owned, price), target));
        row.decreaseUsdt = text(decrease);
        if (compare(decrease, zero()) > 0) row.reasons.push("decrease_only");
        if (compare(gap, zero()) === 0 && compare(decrease, zero()) === 0) row.reasons.push("at_ceiling");
      }
    } catch {
      row.reasons.push("invalid_position");
      gap = zero(); decrease = zero();
      row.targetUsdt = null; row.decreaseUsdt = null;
    }
    return { row, holding, gap, decrease, price };
  });
  const gaps = sum(entries.map((e) => e.gap));
  const deployable = min(gaps, pool);
  for (const { row, holding, gap, decrease, price } of entries) {
    if (row.targetUsdt === null) continue;
    const share = compare(gaps, zero()) > 0 ? div(mul(gap, deployable), gaps) : zero();
    row.increaseUsdt = text(share);
    if (compare(share, gap) < 0) row.reasons.push("pooled");
    const adjustment = compare(decrease, zero()) > 0 ? decrease : share;
    if (compare(adjustment, zero()) === 0) {
      row.quantity = "0"; row.quantityNotionalUsdt = "0";
      continue;
    }
    try {
      if (!holding.sizeRules) throw new Error("missing_rules");
      const lot = strictlyPositive(holding.sizeRules.lot);
      const minimum = strictlyPositive(holding.sizeRules.minimum);
      const quantity = floorLot(div(adjustment, price), lot);
      if (compare(quantity, minimum) < 0) {
        row.quantity = "0"; row.quantityNotionalUsdt = "0"; row.reasons.push("below_minimum");
      } else {
        row.quantity = text(quantity, 100);
        row.quantityNotionalUsdt = text(mul(quantity, price));
      }
    } catch {
      row.reasons.push("size_rules_unavailable");
    }
  }
  return {
    revision, snapshotAt: snapshot.ts, blockers, summary,
    totalUsdt: text(total), exposureUsdt: text(exposure), cashAfterReserveUsdt: text(positive(sub(available, reserve))),
    increasePoolUsdt: text(pool), allocatedIncreaseUsdt: text(deployable),
    managedValueUsdt: entries.every(({ row }) => row.currentUsdt !== null)
      ? text(sum(entries.map(({ row }) => decimal(row.currentUsdt!)))) : null,
    rows: entries.map(({ row }) => row),
  };
}
