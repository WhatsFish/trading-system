import test from "node:test";
import assert from "node:assert/strict";
import { authorize } from "../src/lib/portfolio-auth";
import { CONFIRMATION, DEFAULT_CONFIG, INSTRUMENTS, limits, PortfolioError, validateConfig, type PortfolioSnapshot } from "../src/lib/portfolio";
import { confirmPreview, createPreview, inTransaction, readConfig, readSnapshot, type Connection } from "../src/lib/portfolio-store";

const freshSnapshot = (): PortfolioSnapshot => ({
  id: "42", ts: new Date().toISOString(), equity: 100, available: 100, exposures: {}, held: [], pending: false,
});
const config = (changes = {}) => validateConfig({ ...DEFAULT_CONFIG, ...changes });

test("default compatibility and fixed/percent/reserve ceilings", () => {
  const snapshot = freshSnapshot();
  assert.equal(limits(config(), snapshot, 0).maxHoldings, 5);
  assert.equal(limits(config(), snapshot, 0).defaultPositionUsdt, 18);
  assert.equal(limits(config(), snapshot, 0).totalNotionalUsdt, 200);
  const fixed = limits(config({ totalBudgetMode: "fixed_usdt", totalBudgetUsdt: 30, cashReserveUsdt: 5 }), snapshot, 1);
  assert.equal(fixed.totalNotionalUsdt, 25);
  assert.equal(fixed.defaultPositionUsdt, 5.4);
  assert.equal(fixed.remainingUsdt, 25);
  const clamped = limits(config({ totalBudgetMode: "fixed_usdt", totalBudgetUsdt: 300 }), snapshot, 1);
  assert.equal(clamped.percentageBaseUsdt, 100);
  assert.ok(clamped.warnings.includes("insufficient_equity"));
  assert.equal(limits(config({ totalBudgetMode: "account_equity" }), snapshot, 1).totalNotionalUsdt, 100);
});
test("holdings6, reductions, pending and explicit overrides above legacy sizing", () => {
  const snapshot = { ...freshSnapshot(), held: INSTRUMENTS.slice(0, 5) };
  assert.equal(limits(config({ maxHoldings: 6 }), snapshot, 1).openSlots, 1);
  assert.equal(limits(config({ maxHoldings: 4 }), snapshot, 1).entryBlocked, true);
  assert.equal(limits(config(), { ...snapshot, pending: true }, 1).entryBlocked, true);
  const c = config({ positionBudgetMode: "fixed_usdt", positionBudgetValue: 50,
    instrumentBudgets: { "SPY-USDT-SWAP": { mode: "fixed_usdt", value: 4 } } });
  const result = limits(c, { ...snapshot, exposures: { "SPY-USDT-SWAP": 5 } }, 1);
  assert.equal(result.defaultPositionUsdt, 50);
  assert.equal(result.instrumentLimits["SPY-USDT-SWAP"], 4);
  assert.deepEqual(result.overPositions, ["SPY-USDT-SWAP"]);
  assert.equal(result.entryBlocked, true);
});
test("strict validation rejects invalid, NaN, Infinity, units and unknown instruments", () => {
  for (const changes of [
    { maxHoldings: 0 }, { maxHoldings: 51 }, { maxHoldings: 5.5 }, { maxHoldings: true },
    ...["maxPerAssetGroup", "maxPerStrategyCluster"].flatMap((key) =>
      [0, 51, 2.5, true, "3", NaN, Infinity].map((value) => ({ [key]: value }))),
    { totalBudgetMode: ["fixed_usdt"] }, { totalBudgetMode: "margin" },
    { positionBudgetValue: NaN }, { positionBudgetValue: Infinity }, { positionBudgetValue: 101 },
    { positionBudgetValue: "18" }, { cashReserveUsdt: -1 }, { totalBudgetUsdt: 30 },
    { totalBudgetMode: "fixed_usdt", totalBudgetUsdt: 30, cashReserveUsdt: 30 },
    { instrumentBudgets: { "BTC-USDT-SWAP": { mode: "percent", value: 1 } } },
    { unknown: 1 },
  ]) assert.throws(() => config(changes), PortfolioError);
  assert.throws(() => limits(config(), { ...freshSnapshot(), available: NaN }, 1), PortfolioError);
});
test("confirmed budgets increase within equity, fixed totals and cash without changing defaults", () => {
  const snapshot = freshSnapshot();
  const fixed = config({ positionBudgetMode: "fixed_usdt", positionBudgetValue: 30 });
  assert.equal(limits(fixed, snapshot, 1).defaultPositionUsdt, 30);
  assert.equal(limits(fixed, snapshot, 0).defaultPositionUsdt, 18);
  assert.equal(limits(config({ positionBudgetValue: 50 }), snapshot, 1).defaultPositionUsdt, 50);
  assert.equal(limits(config({ ...fixed, positionBudgetValue: 300 }), snapshot, 1).defaultPositionUsdt, 100);
  assert.equal(limits(config({ ...fixed, totalBudgetMode: "fixed_usdt", totalBudgetUsdt: 25 }), snapshot, 1).defaultPositionUsdt, 25);
  const cash = limits(config({ ...fixed, cashReserveUsdt: 5 }), { ...snapshot, available: 25 }, 1);
  assert.equal(cash.remainingUsdt, 20);
  assert.equal(limits(config(), snapshot, 0).defaultPositionUsdt, 18);
});
test("seven/eight/nine holdings and configurable diversification warnings", () => {
  for (const maxHoldings of [7, 8, 9]) {
    const result = limits(config({ maxHoldings }), freshSnapshot(), 1);
    assert.equal(result.openSlots, maxHoldings);
    assert.equal(result.maxPerAssetGroup, 2);
    assert.equal(result.maxPerStrategyCluster, 2);
    assert.equal(result.warnings.includes("group_cluster_caps"), maxHoldings === 9);
  }
  const raised = limits(config({ maxHoldings: 9, maxPerAssetGroup: 3, maxPerStrategyCluster: 4 }), freshSnapshot(), 1);
  assert.equal(raised.warnings.includes("group_cluster_caps"), false);
  assert.ok(raised.warnings.includes("concentration_caps_raised"));
});
test("first-save appreciation and equity decline freeze all entries without liquidation", () => {
  for (const [equity, exposure] of [[100, 18.01], [90, 18]]) {
    const snapshot = { ...freshSnapshot(), equity, exposures: { "SPY-USDT-SWAP": exposure }, held: ["SPY-USDT-SWAP"] };
    const original = structuredClone(snapshot);
    assert.equal(limits(config(), snapshot, 0).entryBlocked, false);
    const saved = limits(config({ maxHoldings: 6 }), snapshot, 1);
    assert.equal(saved.entryBlocked, true);
    assert.deepEqual(saved.overPositions, ["SPY-USDT-SWAP"]);
    assert.ok(saved.warnings.includes("positions_over_budget"));
    assert.equal(limits(config({ maxHoldings: 6, positionBudgetValue: 25 }), snapshot, 1).entryBlocked, false);
    assert.deepEqual(snapshot, original);
  }
});

type PreviewRow = { expected_revision: number; config: unknown; summary: { snapshot: PortfolioSnapshot }; actor: string; consumed: boolean; expired: boolean };
class FakeDb {
  state = { revision: 0, config: config(), previews: {} as Record<string, PreviewRow>, history: [] as unknown[] };
  backup: typeof this.state | null = null;
  snapshot = freshSnapshot();
  failHistory = false;
  migration = true;
  calls: string[] = [];
  get db() { return this as unknown as Connection; }
  async query(sql: string, args: unknown[] = []) {
    this.calls.push(sql);
    const p = args as [string, number, string, string, string];
    const result = (rows: unknown[] = [], rowCount = rows.length) => ({ rows, rowCount });
    if (sql === "BEGIN") { this.backup = structuredClone(this.state); return result(); }
    if (sql === "ROLLBACK") { this.state = this.backup!; this.backup = null; return result(); }
    if (sql === "COMMIT") { this.backup = null; return result(); }
    if (sql.startsWith("SET LOCAL") || sql.includes("pg_advisory_xact_lock")) return result();
    if (sql.includes("to_regclass")) return result([{ relation: this.migration ? "portfolio_settings" : null }]);
    if (sql.startsWith("SELECT revision, config")) return result([{ revision: this.state.revision, config: this.state.config }]);
    if (sql.includes("FROM account_snapshot")) return result([{ id: this.snapshot.id, ts: this.snapshot.ts,
      total_equity_usd: this.snapshot.equity, available_usdt: this.snapshot.available }]);
    if (sql.includes("FROM position_snapshot")) return result(Object.entries(this.snapshot.exposures).map(([instrument, notional]) => ({ instrument, notional })));
    if (sql.includes("FROM live_position")) return result(this.snapshot.held.map((instrument) => ({ instrument })));
    if (sql.includes("FROM execution_audit")) return result([{ pending: this.snapshot.pending }]);
    if (sql.startsWith("INSERT INTO portfolio_settings_preview")) {
      this.state.previews[p[0]] = { expected_revision: p[1], config: JSON.parse(p[2]),
        summary: JSON.parse(p[3]), actor: p[4], consumed: false, expired: false };
      return result([], 1);
    }
    if (sql.startsWith("SELECT expected_revision")) {
      const row = this.state.previews[p[0]];
      return result(row && row.actor === args[1] && !row.consumed && !row.expired ? [row] : []);
    }
    if (sql.startsWith("UPDATE portfolio_settings SET")) {
      if (this.state.revision !== args[3]) return result();
      this.state.revision = Number(args[0]); this.state.config = JSON.parse(String(args[1]));
      return result([{ revision: this.state.revision }]);
    }
    if (sql.startsWith("INSERT INTO portfolio_settings_history")) {
      if (this.failHistory) throw new Error("simulated history failure");
      this.state.history.push(args); return result([], 1);
    }
    if (sql.startsWith("UPDATE portfolio_settings_preview")) {
      this.state.previews[p[0]].consumed = true; return result([], 1);
    }
    throw new Error(`Unexpected SQL in mock: ${sql}`);
  }
}
const proposed = () => config({ maxHoldings: 6, totalBudgetMode: "fixed_usdt", totalBudgetUsdt: 30 });
async function preview(db: FakeDb) {
  return inTransaction(db.db, () => createPreview(db.db, "operator", proposed(), 0));
}
async function confirm(db: FakeDb, p: Awaited<ReturnType<typeof preview>>, changes = {}) {
  return inTransaction(db.db, () => confirmPreview(db.db, "operator", {
    token: p.token, expectedRevision: p.expectedRevision, acknowledgement: CONFIRMATION, ...changes,
  }));
}
test("preview alone never updates settings; explicit server confirmation and one atomic audit", async () => {
  const db = new FakeDb();
  const p = await preview(db);
  assert.equal(db.state.revision, 0);
  assert.equal(db.state.history.length, 0);
  await assert.rejects(confirm(db, p, { acknowledgement: undefined }), /confirmation_required/);
  assert.equal(db.state.revision, 0);
  // PostgreSQL JSONB may reorder object keys.
  const stored = Object.values(db.state.previews)[0];
  stored.summary.snapshot = Object.fromEntries(Object.entries(stored.summary.snapshot).reverse()) as PortfolioSnapshot;
  const result = await confirm(db, p, { config: config({ maxHoldings: 50 }) });
  assert.equal(result.revision, 1);
  assert.equal(db.state.config.maxHoldings, 6); // confirmation payload cannot replace preview
  assert.equal(db.state.history.length, 1);
  assert.ok(Object.values(db.state.previews)[0].consumed);
  assert.ok(db.calls.includes("SELECT pg_advisory_xact_lock(884424)"));
  await assert.rejects(confirm(db, p), /preview_expired_or_consumed/);
});
test("preview includes removed and added overrides and confirmation uses immutable stored config", async () => {
  const db = new FakeDb();
  db.state.config = config({ instrumentBudgets: {
    "SPY-USDT-SWAP": { mode: "fixed_usdt", value: 4 },
    "QQQ-USDT-SWAP": { mode: "fixed_usdt", value: 5 },
  } });
  const proposedConfig = config({ instrumentBudgets: {
    "QQQ-USDT-SWAP": { mode: "fixed_usdt", value: 6 },
    "GOOGL-USDT-SWAP": { mode: "fixed_usdt", value: 30 },
  } });
  const p = await inTransaction(db.db, () => createPreview(db.db, "operator", proposedConfig, 0));
  assert.deepEqual(p.summary.affectedInstruments, ["GOOGL-USDT-SWAP", "QQQ-USDT-SWAP", "SPY-USDT-SWAP"]);
  assert.equal(p.summary.originalConfig.instrumentBudgets["SPY-USDT-SWAP"].value, 4);
  assert.equal(p.summary.current.instrumentLimits["SPY-USDT-SWAP"], 4);
  assert.equal(p.summary.proposed.instrumentLimits["SPY-USDT-SWAP"], 18);
  proposedConfig.instrumentBudgets["GOOGL-USDT-SWAP"].value = 99;
  p.config.instrumentBudgets["GOOGL-USDT-SWAP"].value = 98;
  p.summary.originalConfig.instrumentBudgets = {};
  const result = await confirm(db, p, { config: proposedConfig });
  assert.equal(result.config.instrumentBudgets["GOOGL-USDT-SWAP"].value, 30);
  assert.equal(result.config.instrumentBudgets["SPY-USDT-SWAP"], undefined);
  const history = db.state.history[0] as unknown[];
  assert.equal(JSON.parse(String(history[4])).originalConfig.instrumentBudgets["SPY-USDT-SWAP"].value, 4);
});
test("concurrent editors use CAS and retain only successful audit", async () => {
  const db = new FakeDb();
  const first = await preview(db);
  const second = await preview(db);
  await confirm(db, first);
  await assert.rejects(confirm(db, second), /revision_conflict/);
  assert.equal(db.state.revision, 1);
  assert.equal(db.state.history.length, 1);
});
test("audit failure rolls back settings and token consumption", async () => {
  const db = new FakeDb();
  const p = await preview(db);
  db.failHistory = true;
  await assert.rejects(confirm(db, p), /simulated history failure/);
  assert.equal(db.state.revision, 0);
  assert.equal(db.state.history.length, 0);
  assert.equal(Object.values(db.state.previews)[0].consumed, false);
});
test("tokens bind actor, expire, and cannot confirm changed account state", async () => {
  const db = new FakeDb();
  const p = await preview(db);
  await assert.rejects(inTransaction(db.db, () => confirmPreview(db.db, "other", { token: p.token, expectedRevision: 0, acknowledgement: CONFIRMATION })), /preview_expired_or_consumed/);
  db.snapshot.id = "43";
  await assert.rejects(confirm(db, p), /snapshot_changed_preview_again/);
  db.snapshot.id = "42";
  Object.values(db.state.previews)[0].expired = true;
  await assert.rejects(confirm(db, p), /preview_expired_or_consumed/);
});
test("missing migration defaults read-only; invalid stored settings and stale snapshot fail closed", async () => {
  const db = new FakeDb();
  db.migration = false;
  assert.equal((await readConfig(db.db)).config.maxHoldings, 5);
  await assert.rejects(preview(db), /migration_required/);
  db.migration = true;
  db.state.config.maxHoldings = 0;
  await assert.rejects(readConfig(db.db), /invalid_max_holdings/);
  db.snapshot.ts = new Date(Date.now() - 181_000).toISOString();
  await assert.rejects(readSnapshot(db.db), /account_snapshot_stale/);
});
test("route authorization requires Basic credentials and same-origin JSON mutations", () => {
  const before = { user: process.env.DASHBOARD_USER, password: process.env.DASHBOARD_PASSWORD };
  process.env.DASHBOARD_USER = "test-user"; process.env.DASHBOARD_PASSWORD = "test-password";
  const headers = { authorization: `Basic ${Buffer.from("test-user:test-password").toString("base64")}`,
    origin: "https://example.test", host: "example.test", "x-forwarded-proto": "https", "content-type": "application/json" };
  const request = (changes = {}) => new Request("http://localhost:3000/trading/api/portfolio-settings", { headers: { ...headers, ...changes } });
  try {
    assert.equal(authorize(request(), true), "test-user");
    assert.throws(() => authorize(request({ authorization: "" }), true), /authentication_required/);
    assert.throws(() => authorize(request({ origin: "https://evil.test" }), true), /same_origin_required/);
    assert.throws(() => authorize(request({ origin: "" }), true), /same_origin_required/);
    assert.throws(() => authorize(request({ "sec-fetch-site": "cross-site" }), true), /same_origin_required/);
    assert.throws(() => authorize(request({ "content-type": "text/plain" }), true), /json_required/);
    delete process.env.DASHBOARD_PASSWORD;
    assert.throws(() => authorize(request(), true), /authentication_not_configured/);
  } finally {
    if (before.user === undefined) delete process.env.DASHBOARD_USER; else process.env.DASHBOARD_USER = before.user;
    if (before.password === undefined) delete process.env.DASHBOARD_PASSWORD; else process.env.DASHBOARD_PASSWORD = before.password;
  }
});
