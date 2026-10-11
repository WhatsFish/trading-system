import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { allocationPreview, type AllocationHolding, type AllocationInput } from "../src/lib/allocation";
import { decimal, text, compare, mul } from "../src/lib/allocation-decimal";
import { DEFAULT_CONFIG, INSTRUMENTS, limits } from "../src/lib/portfolio";
import { readAllocation } from "../src/lib/allocation-store";
import type { Connection } from "../src/lib/portfolio-store";

const now = Date.parse("2026-10-11T08:00:00Z");
const ts = new Date(now).toISOString();
function holding(instrument = INSTRUMENTS[0]): AllocationHolding {
  return {
    instrument, strategy: "trend", parameters: { window: 20 },
    ownedQuantity: "1", accountPositions: [{ side: "long", size: "1" }],
    market: { ts, price: "5", state: "live" },
    signal: { family: "trend", parameters: { window: 20 }, target: 1, computedAt: ts },
    sizeRules: { lot: "0.01", minimum: "0.01" }, exitPending: false,
  };
}
function input(equity = 200, count = 1): AllocationInput {
  const holdings = INSTRUMENTS.slice(0, count).map(holding);
  return {
    now, config: { ...DEFAULT_CONFIG, maxHoldings: 6 }, revision: 1,
    snapshot: {
      id: "1", ts, equity, available: equity - count * 5,
      exposures: Object.fromEntries(holdings.map((h) => [h.instrument, 5])),
      held: holdings.map((h) => h.instrument), pending: false,
    },
    controller: { lastSeenAt: ts, revision: 1, settingsError: false }, holdings,
  };
}
test("funding 30 -> 200 increases the same budget illustration, not strategy conviction", () => {
  const before = allocationPreview(input(30)).rows[0];
  const after = allocationPreview(input(200)).rows[0];
  assert.equal(before.ceilingUsdt, "5.4");
  assert.equal(after.ceilingUsdt, "36");
  assert.equal(before.increaseUsdt, "0.4");
  assert.equal(after.increaseUsdt, "31");
  assert.equal(before.strategyTarget, after.strategyTarget);
  assert.equal(after.quantity, "6.2");
});
test("six 18% ceilings share cash proportionally instead of spending 108% or favoring first row", () => {
  const data = input(200, 6);
  const result = allocationPreview(data);
  assert.equal(result.summary.openSlots, 0);
  assert.equal(result.summary.entryBlocked, true);
  assert.equal(result.allocatedIncreaseUsdt, "170");
  assert.equal(result.increasePoolUsdt, "170");
  assert.equal(new Set(result.rows.map((r) => r.increaseUsdt)).size, 1);
  assert.equal(result.rows[0].increaseUsdt, "28.333333333333");
  assert.equal(result.rows[0].quantity, "5.66");
  assert.ok(result.rows.every((r) => r.reasons.includes("pooled")));
  const reversed = allocationPreview({ ...data, holdings: [...data.holdings].reverse() });
  assert.deepEqual(result.rows, [...reversed.rows].reverse());
  assert.ok(result.rows.reduce((n, r) => n + Number(r.quantityNotionalUsdt), 0) <= 170);
});
test("unequal gaps receive proportional shares; unrelated manual exposure and reserve consume budget", () => {
  const data = input(200, 2);
  data.holdings[1].ownedQuantity = "2";
  data.holdings[1].accountPositions[0].size = "2";
  data.snapshot.exposures[data.holdings[1].instrument] = 10;
  data.snapshot.exposures["MANUAL-USDT-SWAP"] = 150;
  data.config.totalBudgetMode = "account_equity";
  data.config.cashReserveUsdt = 10;
  data.snapshot.available = 80;
  const result = allocationPreview(data);
  assert.equal(result.increasePoolUsdt, "25");
  assert.equal(result.rows.length, 2);
  assert.equal(result.rows[0].increaseUsdt, "13.59649122807");
  assert.equal(result.rows[1].increaseUsdt, "11.403508771929");
});
test("cash reserve limits increases independently; hypothetical decreases never release cash", () => {
  const data = input(200, 2);
  data.snapshot.available = 12;
  data.config.cashReserveUsdt = 10;
  data.holdings[0].signal!.target = 0;
  const result = allocationPreview(data);
  assert.equal(result.increasePoolUsdt, "2");
  assert.equal(result.rows[0].targetUsdt, "0");
  assert.equal(result.rows[0].decreaseUsdt, "5");
  assert.equal(result.rows[0].quantity, "1");
  assert.equal(result.rows[1].increaseUsdt, "2");
  data.snapshot.available = 9;
  assert.equal(allocationPreview(data).rows[1].increaseUsdt, "0");
});
test("fixed/percent/legacy ceilings match existing settings formulas across 30/200 budgets", () => {
  for (const equity of [30, 200]) for (const revision of [0, 1]) {
    for (const totalBudgetMode of ["legacy_equity", "account_equity", "fixed_usdt"] as const) {
      for (const positionBudgetMode of ["fixed_usdt", "percent"] as const) {
        const data = input(equity);
        data.revision = revision; data.controller!.revision = revision;
        Object.assign(data.config, { totalBudgetMode, totalBudgetUsdt: totalBudgetMode === "fixed_usdt" ? 25 : 0,
          positionBudgetMode, positionBudgetValue: positionBudgetMode === "fixed_usdt" ? 50 : 18 });
        const result = allocationPreview(data);
        const existing = limits(data.config, data.snapshot, revision);
        assert.ok(Math.abs(Number(result.rows[0].ceilingUsdt) - existing.defaultPositionUsdt) < 1e-10);
        assert.equal(Number(result.totalUsdt), existing.totalNotionalUsdt);
      }
    }
  }
});
test("instrument override is capped by existing user budget; over-budget value is conceptual decrease only", () => {
  const data = input();
  data.config.instrumentBudgets = { [INSTRUMENTS[0]]: { mode: "fixed_usdt", value: 3 } };
  const row = allocationPreview(data).rows[0];
  assert.equal(row.ceilingUsdt, "3");
  assert.equal(row.decreaseUsdt, "2");
  assert.equal(row.increaseUsdt, "0");
  assert.ok(row.reasons.includes("decrease_only"));
});
test("stale/missing inputs block adjustments instead of inventing flat/sells", () => {
  const cases: [(data: AllocationInput) => void, string][] = [
    [(d) => { d.snapshot.ts = new Date(now - 180_001).toISOString(); }, "account_stale"],
    [(d) => { d.holdings[0].market!.ts = new Date(now - 180_001).toISOString(); }, "market_unavailable"],
    [(d) => { d.holdings[0].market = null; }, "market_unavailable"],
    [(d) => { d.holdings[0].market!.price = "NaN"; }, "invalid_position"],
    [(d) => { d.holdings[0].market!.state = "suspend"; }, "market_unavailable"],
    [(d) => { d.controller = null; }, "controller_stale"],
    [(d) => { d.controller!.lastSeenAt = new Date(now - 180_001).toISOString(); }, "controller_stale"],
    [(d) => { d.controller!.revision = 0; }, "revision_mismatch"],
    [(d) => { d.controller!.settingsError = true; }, "revision_mismatch"],
    [(d) => { d.snapshot.pending = true; }, "pending_orders"],
    [(d) => { d.holdings[0].exitPending = true; }, "exit_pending"],
    [(d) => { d.holdings[0].signal = null; }, "signal_unavailable"],
    [(d) => { d.holdings[0].signal!.computedAt = new Date(now - 4 * 86_400_000 - 1).toISOString(); }, "signal_unavailable"],
    [(d) => { d.holdings[0].signal!.family = "other"; }, "signal_unavailable"],
    [(d) => { d.holdings[0].signal!.parameters = { window: 21 }; }, "signal_unavailable"],
    [(d) => { d.holdings[0].signal!.target = -1; }, "signal_unavailable"],
  ];
  for (const [change, reason] of cases) {
    const data = input();
    change(data);
    const row = allocationPreview(data).rows[0];
    assert.ok(row.reasons.includes(reason as typeof row.reasons[number]), reason);
    assert.equal(row.targetUsdt, null, reason);
    assert.equal(row.decreaseUsdt, null, reason);
    assert.equal(row.increaseUsdt, null, reason);
    assert.equal(row.quantity, null, reason);
  }
});
test("manual same-symbol long/short or absent managed account quantity blocks both directions", () => {
  for (const positions of [
    [{ side: "long", size: "1.1" }], [{ side: "long", size: "0.9" }],
    [{ side: "short", size: "1" }], [], [{ side: "long", size: "1" }, { side: "short", size: "1" }],
  ]) for (const target of [0, 1]) {
    const data = input();
    data.holdings[0].accountPositions = positions;
    data.holdings[0].signal!.target = target;
    const row = allocationPreview(data).rows[0];
    assert.ok(row.reasons.includes("ownership_mismatch"));
    assert.equal(row.increaseUsdt, null);
    assert.equal(row.decreaseUsdt, null);
  }
});
test("actual zero is distinct from absent target; parameter ordering does not change exact match", () => {
  const data = input();
  data.holdings[0].parameters = { slow: 20, fast: 5 };
  data.holdings[0].signal!.parameters = { fast: 5, slow: 20 };
  data.holdings[0].signal!.target = 0;
  assert.equal(allocationPreview(data).rows[0].targetUsdt, "0");
  data.holdings[0].signal = null;
  assert.equal(allocationPreview(data).rows[0].strategyTarget, null);
  assert.equal(allocationPreview(data).rows[0].targetUsdt, null);
});
test("small lots, exact thresholds and dust never round quantity upward", () => {
  const data = input();
  data.holdings[0].market!.price = "0.1";
  data.holdings[0].sizeRules = { lot: "0.01", minimum: "0.01" };
  data.config.positionBudgetMode = "fixed_usdt";
  data.config.positionBudgetValue = 0.4;
  assert.equal(allocationPreview(data).rows[0].quantity, "3");
  data.config.positionBudgetValue = 0.1009;
  const dust = allocationPreview(data).rows[0];
  assert.equal(dust.quantity, "0");
  assert.ok(dust.reasons.includes("below_minimum"));
  data.config.positionBudgetValue = 0.101;
  assert.equal(allocationPreview(data).rows[0].quantity, "0.01");
  data.holdings[0].sizeRules = { lot: "0.000000000000000001", minimum: "0.000000000000000001" };
  const small = allocationPreview(data).rows[0];
  assert.equal(small.quantity, "0.01");
  assert.ok(compare(mul(decimal(small.quantity!), decimal("0.1")), decimal(small.increaseUsdt!)) <= 0);
  data.holdings[0].sizeRules = null;
  assert.equal(allocationPreview(data).rows[0].quantity, null);
  assert.ok(allocationPreview(data).rows[0].reasons.includes("size_rules_unavailable"));
});
test("raw numeric account values preserve cash boundaries beyond IEEE precision", () => {
  const data = input();
  data.exactAmounts = { equity: "200", available: "0.099999999999999999", exposures: ["5"] };
  data.holdings[0].sizeRules = { lot: "0.02", minimum: "0.02" };
  assert.equal(allocationPreview(data).rows[0].quantity, "0");
  assert.equal(text(decimal("1e-18")), "0");
});
test("database reader is SELECT-only, pins held family+JSON parameters, and does not invent exchange rules", async () => {
  const calls: string[] = [];
  const currentTs = new Date().toISOString();
  const db = { async query(sql: string) {
    calls.push(sql);
    if (sql.includes("to_regclass")) return { rows: [{ relation: "portfolio_settings" }] };
    if (sql.includes("FROM portfolio_settings")) return { rows: [{ revision: 1, config: { ...DEFAULT_CONFIG, maxHoldings: 6 } }] };
    if (sql.includes("ORDER BY ts DESC LIMIT 1") && sql.includes("account_snapshot")) return {
      rows: [{ id: "1", ts: currentTs, total_equity_usd: "200", available_usdt: "195" }],
    };
    if (sql.includes("GROUP BY instrument")) return { rows: [{ instrument: INSTRUMENTS[0], notional: "5" }] };
    if (sql.includes("SELECT instrument FROM live_position")) return { rows: [{ instrument: INSTRUMENTS[0] }] };
    if (sql.includes("SELECT EXISTS")) return { rows: [{ pending: false }] };
    if (sql.includes("worker_heartbeat")) return { rows: [{ last_seen_at: currentTs, detail: { portfolioRevision: 1 } }] };
    if (sql.includes("FROM position_snapshot")) return { rows: [{ instrument: INSTRUMENTS[0], side: "long", size: "1", notional: "5" }] };
    if (sql.includes("FROM account_snapshot WHERE")) return { rows: [{ equity: "200", available: "195" }] };
    if (sql.includes("FROM live_position l")) return { rows: [{
      instrument: INSTRUMENTS[0], strategy: "trend", strategy_parameters: { window: 20 }, owned_quantity: "1",
      market_ts: currentTs, market_price: "5", instrument_state: "live",
      target_family: "trend", target_parameters: { window: 20 }, current_target: 1, computed_at: currentTs,
    }] };
    throw new Error(`Unexpected SQL: ${sql}`);
  } } as unknown as Connection;
  const result = await readAllocation(db);
  assert.equal(result.rows[0].increaseUsdt, "31");
  assert.equal(result.rows[0].quantity, null);
  assert.ok(result.rows[0].reasons.includes("size_rules_unavailable"));
  assert.ok(calls.every((sql) => sql.trim().startsWith("SELECT")));
  const held = calls.find((sql) => sql.includes("FROM live_position l"))!;
  assert.match(held, /family = l.strategy AND parameters = l.strategy_parameters/);
  assert.doesNotMatch(held, /strategy_candidate|strategy_experiment/);
});
test("page is dynamic, read-only, linked, and covered by existing default-auth middleware", () => {
  const page = readFileSync("src/app/allocation/page.tsx", "utf8");
  const middleware = readFileSync("src/middleware.ts", "utf8");
  assert.match(page, /force-dynamic/);
  assert.match(page, /REPEATABLE READ READ ONLY/);
  assert.doesNotMatch(page, /fetch\(|createPreview|confirmPreview|<form|<button/);
  assert.match(middleware, /DASHBOARD_PASSWORD/);
  assert.doesNotMatch(middleware, /allocation|matcher/);
  assert.match(readFileSync("src/app/page.tsx", "utf8"), /\/allocation\?lang=/);
});
