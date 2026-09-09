import { createHash, randomBytes } from "node:crypto";
import type { PoolClient } from "pg";
import { CONFIRMATION, DEFAULT_CONFIG, limits, PortfolioError, validateConfig, type PortfolioSnapshot } from "./portfolio";

export type Connection = Pick<PoolClient, "query">;
export async function inTransaction<T>(db: Connection, action: () => Promise<T>): Promise<T> {
  await db.query("BEGIN");
  try {
    await db.query("SET LOCAL statement_timeout = '15s'");
    const result = await action();
    await db.query("COMMIT");
    return result;
  } catch (error) {
    await db.query("ROLLBACK");
    throw error;
  }
}
const tokenHash = (token: string) => createHash("sha256").update(token).digest("hex");
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  return JSON.stringify(value);
}
export async function readConfig(db: Connection) {
  const relation = await db.query("SELECT to_regclass('portfolio_settings') AS relation");
  if (!relation.rows[0]?.relation) return { revision: 0, config: validateConfig(DEFAULT_CONFIG), migrationRequired: true };
  const result = await db.query("SELECT revision, config FROM portfolio_settings WHERE id = 1");
  const row = result.rows[0];
  if (!row || !Number.isInteger(row.revision) || row.revision < 0) throw new PortfolioError("invalid_stored_settings", 503);
  return { revision: row.revision as number, config: validateConfig(row.config), migrationRequired: false };
}
function numeric(value: unknown): number {
  if ((typeof value !== "string" && typeof value !== "number") || value === "") throw new PortfolioError("invalid_account_snapshot", 503);
  const n = Number(value);
  if (!Number.isFinite(n)) throw new PortfolioError("invalid_account_snapshot", 503);
  return n;
}
export async function readSnapshot(db: Connection): Promise<PortfolioSnapshot> {
  const result = await db.query("SELECT id::text, ts, total_equity_usd, available_usdt FROM account_snapshot ORDER BY ts DESC LIMIT 1");
  const row = result.rows[0];
  if (!row || !Number.isFinite(new Date(row.ts).getTime()) || Date.now() - new Date(row.ts).getTime() > 180_000 ||
      new Date(row.ts).getTime() > Date.now() + 30_000) throw new PortfolioError("account_snapshot_stale", 503);
  const positions = await db.query(
    "SELECT instrument, CASE WHEN COUNT(notional_usd) = COUNT(*) THEN SUM(ABS(notional_usd)) END AS notional FROM position_snapshot WHERE account_snapshot_id = $1 AND size <> 0 GROUP BY instrument", [row.id],
  );
  const managed = await db.query("SELECT instrument FROM live_position WHERE owned_quantity > 0");
  const pending = await db.query("SELECT EXISTS (SELECT 1 FROM execution_audit WHERE action = 'buy' AND state NOT IN ('filled', 'canceled', 'order_failed')) AS pending");
  const exposures = Object.fromEntries(positions.rows.map((p) => [p.instrument, numeric(p.notional)]));
  return { id: row.id, ts: new Date(row.ts).toISOString(), equity: numeric(row.total_equity_usd),
    available: numeric(row.available_usdt), exposures,
    held: Array.from(new Set([...Object.keys(exposures), ...managed.rows.map((p) => String(p.instrument))])).sort(),
    pending: Boolean(pending.rows[0].pending) };
}
export async function overview(db: Connection) {
  const current = await readConfig(db);
  const snapshot = await readSnapshot(db);
  const history = current.migrationRequired ? [] : (await db.query(
    "SELECT revision, config, previous_config, confirmed_at, actor, preview FROM portfolio_settings_history ORDER BY revision DESC LIMIT 50",
  )).rows;
  const heartbeat = (await db.query(
    "SELECT last_seen_at, detail FROM worker_heartbeat WHERE worker = 'live-controller'",
  )).rows[0];
  const controller = heartbeat ? {
    lastSeenAt: new Date(heartbeat.last_seen_at).toISOString(),
    revision: typeof heartbeat.detail?.portfolioRevision === "number" ? heartbeat.detail.portfolioRevision as number : null,
    settingsError: Boolean(heartbeat.detail?.portfolioError),
  } : null;
  return { ...current, snapshot, limits: limits(current.config, snapshot, current.revision), history, controller };
}
export async function createPreview(db: Connection, actor: string, input: unknown, expectedRevision: unknown) {
  const config = validateConfig(input);
  const current = await readConfig(db);
  if (current.migrationRequired) throw new PortfolioError("migration_required", 503);
  if (!Number.isInteger(expectedRevision) || expectedRevision !== current.revision) throw new PortfolioError("revision_conflict", 409);
  const snapshot = await readSnapshot(db);
  const summary = { snapshot, originalConfig: current.config,
    affectedInstruments: Array.from(new Set([
      ...Object.keys(current.config.instrumentBudgets), ...Object.keys(config.instrumentBudgets),
    ])).sort(),
    current: limits(current.config, snapshot, current.revision),
    proposed: limits(config, snapshot, current.revision + 1) };
  const token = randomBytes(32).toString("hex");
  await db.query(
    "INSERT INTO portfolio_settings_preview (token_hash, expected_revision, config, summary, actor) VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)",
    [tokenHash(token), current.revision, JSON.stringify(config), JSON.stringify(summary), actor],
  );
  return { token, expectedRevision: current.revision, config, summary, expiresInSeconds: 600 };
}
// Caller owns a transaction. Lock order matches the worker: configuration,
// then row. CAS plus token consumption and history insertion commit together.
export async function confirmPreview(db: Connection, actor: string, input: unknown) {
  if (!input || typeof input !== "object") throw new PortfolioError("confirmation_required");
  const body = input as Record<string, unknown>;
  if (body.acknowledgement !== CONFIRMATION || typeof body.token !== "string" || !/^[a-f0-9]{64}$/.test(body.token) ||
      !Number.isInteger(body.expectedRevision)) throw new PortfolioError("confirmation_required");
  await db.query("SELECT pg_advisory_xact_lock(884424)");
  const preview = (await db.query(
    "SELECT expected_revision, config, summary FROM portfolio_settings_preview WHERE token_hash = $1 AND actor = $2 AND consumed_at IS NULL AND expires_at > NOW() FOR UPDATE",
    [tokenHash(body.token), actor],
  )).rows[0];
  if (!preview) throw new PortfolioError("preview_expired_or_consumed", 409);
  const current = await readConfig(db);
  if (current.migrationRequired || current.revision !== preview.expected_revision || current.revision !== body.expectedRevision) throw new PortfolioError("revision_conflict", 409);
  const config = validateConfig(preview.config);
  const snapshot = await readSnapshot(db);
  // Never confirm a preview based on a different account snapshot.
  if (snapshot.id !== preview.summary.snapshot.id ||
      canonical(snapshot) !== canonical(preview.summary.snapshot)) throw new PortfolioError("snapshot_changed_preview_again", 409);
  const revision = current.revision + 1;
  const saved = await db.query(
    "UPDATE portfolio_settings SET revision = $1, config = $2::jsonb, updated_at = NOW(), updated_by = $3 WHERE id = 1 AND revision = $4 RETURNING revision",
    [revision, JSON.stringify(config), actor, current.revision],
  );
  if (saved.rowCount !== 1) throw new PortfolioError("revision_conflict", 409);
  await db.query(
    "INSERT INTO portfolio_settings_history (revision, config, previous_config, actor, preview) VALUES ($1, $2::jsonb, $3::jsonb, $4, $5::jsonb)",
    [revision, JSON.stringify(config), JSON.stringify(current.config), actor, JSON.stringify(preview.summary)],
  );
  await db.query("UPDATE portfolio_settings_preview SET consumed_at = NOW() WHERE token_hash = $1", [tokenHash(body.token)]);
  return { revision, config };
}
