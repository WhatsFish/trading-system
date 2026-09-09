import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { Pool, type PoolClient } from "pg";
import { CONFIRMATION, DEFAULT_CONFIG, PortfolioError, validateConfig } from "../src/lib/portfolio";
import { confirmPreview, createPreview, inTransaction, readConfig, readSnapshot } from "../src/lib/portfolio-store";

const databaseUrl = process.env.TEST_PORTFOLIO_DATABASE_URL;
const actor = "isolated-acceptance";
const proposed = validateConfig({ ...DEFAULT_CONFIG, maxHoldings: 6 });
const hash = (token: string) => createHash("sha256").update(token).digest("hex");
type Preview = Awaited<ReturnType<typeof createPreview>>;
const body = (p: Preview) => ({
  token: p.token, expectedRevision: p.expectedRevision, acknowledgement: CONFIRMATION,
});
const errorIs = (message: string, status = 409) => (error: unknown) => {
  assert.ok(error instanceof PortfolioError);
  assert.equal(error.message, message);
  assert.equal(error.status, status);
  return true;
};

test("isolated PostgreSQL portfolio acceptance", {
  skip: !databaseUrl && "Set TEST_PORTFOLIO_DATABASE_URL explicitly; no PostgreSQL acceptance was run",
  timeout: 90_000,
}, async (t) => {
  const url = new URL(databaseUrl!);
  assert.ok(["postgres:", "postgresql:"].includes(url.protocol));
  assert.equal(url.pathname, "/portfolio_test", "Refusing any database other than portfolio_test");
  assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(url.hostname), "Use the isolated container loopback only");
  assert.equal(url.search, "", "Connection query overrides are not permitted");
  const pool = new Pool({
    connectionString: databaseUrl, max: 5, connectionTimeoutMillis: 3000,
    statement_timeout: 5000, application_name: "portfolio-isolated-acceptance",
  });
  const db = await pool.connect();
  t.after(() => { db.release(); return pool.end(); });
  assert.equal((await db.query("SELECT current_database() AS name")).rows[0].name, "portfolio_test");
  const schema = await readFile(resolve(process.cwd(), "../db/schema.sql"), "utf8");
  const migration = await readFile(resolve(process.cwd(), "../db/portfolio-settings.sql"), "utf8");

  async function seed() {
    await db.query(`TRUNCATE portfolio_settings_preview, portfolio_settings_history,
      portfolio_settings, position_snapshot, account_snapshot, live_position, execution_audit RESTART IDENTITY CASCADE`);
    await db.query(migration);
    return (await db.query(`INSERT INTO account_snapshot (total_equity_usd, available_usdt, raw)
      VALUES (100, 80, '{}') RETURNING id::text`)).rows[0].id as string;
  }
  const preview = () => inTransaction(db, () => createPreview(db, actor, proposed, 0));
  const confirm = (p: Preview, connection = db, who = actor, changes = {}) =>
    inTransaction(connection, () => confirmPreview(connection, who, { ...body(p), ...changes }));
  const state = async () => ({
    settings: (await db.query("SELECT * FROM portfolio_settings ORDER BY id")).rows,
    history: (await db.query("SELECT * FROM portfolio_settings_history ORDER BY revision")).rows,
    previews: (await db.query("SELECT * FROM portfolio_settings_preview ORDER BY token_hash")).rows,
  });
  async function connection() {
    const client = await pool.connect();
    return client;
  }
  // Observe actual PostgreSQL waiters rather than relying on a sleep to infer blocking.
  async function waitForLock(observer: PoolClient, pid: number, key: number, mode: string) {
    const deadline = Date.now() + 3000;
    while (Date.now() < deadline) {
      const result = await observer.query(`SELECT 1 FROM pg_locks WHERE pid = $1
        AND locktype = 'advisory' AND classid = 0 AND objid = $2
        AND objsubid = 1 AND mode = $3 AND NOT granted`, [pid, key, mode]);
      if (result.rowCount) return;
      await delay(20);
    }
    assert.fail(`No ${mode} waiter observed for PID ${pid}, advisory key ${key}`);
  }

  await t.test("base schema and migration are idempotent, including after a confirmed revision", async () => {
    await db.query(schema);
    assert.equal((await readConfig(db)).migrationRequired, true);
    await assert.rejects(preview(), errorIs("migration_required", 503));
    await db.query(schema);
    await db.query(migration);
    const initial = await state();
    assert.equal(initial.settings.length, 1);
    assert.equal(initial.history.length, 1);
    assert.deepEqual(initial.settings[0].config, DEFAULT_CONFIG);
    assert.equal(initial.settings[0].revision, 0);
    await db.query(migration);
    assert.deepEqual(await state(), initial);
    await seed();
    await confirm(await preview());
    const saved = await state();
    await db.query(schema);
    await db.query(migration);
    assert.deepEqual(await state(), saved);
  });

  await t.test("readSnapshot aggregates absolute exposure, managed holdings and pending buy states", async () => {
    const id = await seed();
    await db.query(`INSERT INTO position_snapshot (account_snapshot_id, instrument, side, size, notional_usd)
      VALUES ($1, 'SPY-USDT-SWAP', 'long', 1, 10.25),
             ($1, 'SPY-USDT-SWAP', 'short', -1, -4.50),
             ($1, 'QQQ-USDT-SWAP', 'long', 0, NULL)`, [id]);
    await db.query(`INSERT INTO live_position (instrument, strategy, strategy_parameters, entry_order_id,
      entry_client_order_id, owned_quantity, average_price)
      VALUES ('SPY-USDT-SWAP', 'test', '{}', '1', '1', 1, 10),
             ('NVDA-USDT-SWAP', 'test', '{}', '2', '2', 1, 10)`);
    let snapshot = await readSnapshot(db);
    assert.equal(snapshot.id, id);
    assert.equal(snapshot.equity, 100);
    assert.equal(snapshot.available, 80);
    assert.deepEqual(snapshot.exposures, { "SPY-USDT-SWAP": 14.75 });
    assert.deepEqual(snapshot.held, ["NVDA-USDT-SWAP", "SPY-USDT-SWAP"]);
    assert.equal(snapshot.pending, false);
    for (const [action, orderState, pending] of [
      ["buy", "filled", false], ["buy", "canceled", false], ["buy", "order_failed", false],
      ["sell", "submitted", false], ["buy", "submitted", true], ["buy", "partially_filled", true],
    ] as const) {
      await db.query("DELETE FROM execution_audit");
      await db.query(`INSERT INTO execution_audit
        (client_order_id, instrument, action, requested_size, state, detail)
        VALUES ('test', 'SPY-USDT-SWAP', $1, 1, $2, '{}')`, [action, orderState]);
      snapshot = await readSnapshot(db);
      assert.equal(snapshot.pending, pending, `${action}/${orderState}`);
    }
    await db.query("UPDATE position_snapshot SET size = 1 WHERE instrument = 'QQQ-USDT-SWAP'");
    await assert.rejects(readSnapshot(db), errorIs("invalid_account_snapshot", 503));
    await db.query("UPDATE position_snapshot SET size = 0 WHERE instrument = 'QQQ-USDT-SWAP'");
    await db.query("UPDATE account_snapshot SET total_equity_usd = 'NaN'");
    await assert.rejects(readSnapshot(db), errorIs("invalid_account_snapshot", 503));
    await db.query("UPDATE account_snapshot SET total_equity_usd = 100, ts = NOW() - INTERVAL '181 seconds'");
    await assert.rejects(readSnapshot(db), errorIs("account_snapshot_stale", 503));
    await db.query("UPDATE account_snapshot SET ts = NOW() + INTERVAL '60 seconds'");
    await assert.rejects(readSnapshot(db), errorIs("account_snapshot_stale", 503));
    await db.query("DELETE FROM account_snapshot");
    await assert.rejects(readSnapshot(db), errorIs("account_snapshot_stale", 503));
  });

  await t.test("preview persists only a hash; actor, acknowledgement, expiry and single-use are enforced", async () => {
    await seed();
    const p = await preview();
    const before = await state();
    assert.equal(before.settings[0].revision, 0);
    assert.equal(before.history.length, 1);
    assert.equal(before.previews[0].token_hash, hash(p.token));
    assert.equal(before.previews[0].consumed_at, null);
    assert.equal(new Date(before.previews[0].expires_at).getTime() - new Date(before.previews[0].created_at).getTime(), 600_000);
    await assert.rejects(confirm(p, db, "another-operator"), errorIs("preview_expired_or_consumed"));
    await assert.rejects(confirm(p, db, actor, { acknowledgement: "" }), errorIs("confirmation_required", 400));
    await assert.rejects(confirm(p, db, actor, { expectedRevision: 9 }), errorIs("revision_conflict"));
    assert.deepEqual(await state(), before);
    await db.query("UPDATE portfolio_settings_preview SET expires_at = NOW() - INTERVAL '1 second'");
    await assert.rejects(confirm(p), errorIs("preview_expired_or_consumed"));
    await db.query("UPDATE portfolio_settings_preview SET expires_at = NOW() + INTERVAL '10 minutes'");
    const result = await confirm(p, db, actor, { config: { ...proposed, maxHoldings: 50 } });
    assert.equal(result.revision, 1);
    assert.deepEqual(result.config, proposed);
    const after = await state();
    assert.equal(after.history.length, 2);
    assert.deepEqual(after.history[1].previous_config, DEFAULT_CONFIG);
    assert.deepEqual(after.history[1].config, proposed);
    assert.deepEqual(after.history[1].preview, p.summary);
    assert.equal(after.history[1].actor, actor);
    assert.ok(after.previews[0].consumed_at);
    await assert.rejects(confirm(p), errorIs("preview_expired_or_consumed"));
    await assert.rejects(preview(), errorIs("revision_conflict"));
    assert.deepEqual(await state(), after);
  });

  await t.test("real SQL history failure and post-confirm exception roll back config, history and consumption", async () => {
    await seed();
    const p = await preview();
    const before = await state();
    await db.query(`ALTER TABLE portfolio_settings_history ADD CONSTRAINT acceptance_history_failure CHECK (revision = 0)`);
    try {
      await assert.rejects(confirm(p), (error: unknown) => {
        assert.equal((error as { code: string }).code, "23514");
        return true;
      });
      assert.deepEqual(await state(), before);
    } finally {
      await db.query("ALTER TABLE portfolio_settings_history DROP CONSTRAINT acceptance_history_failure");
    }
    await assert.rejects(inTransaction(db, async () => {
      await confirmPreview(db, actor, body(p));
      throw new Error("acceptance failure after token consumption");
    }), /acceptance failure after token consumption/);
    assert.deepEqual(await state(), before);
    assert.equal((await confirm(p)).revision, 1);
    assert.equal((await db.query("SHOW statement_timeout")).rows[0].statement_timeout, "5s");
  });

  await t.test("different tokens racing on separate connections permit exactly one revision and history write", async () => {
    await seed();
    const first = await preview();
    const second = await preview();
    const other = await connection();
    try {
      const results = await Promise.allSettled([confirm(first), confirm(second, other)]);
      assert.equal(results.filter((r) => r.status === "fulfilled").length, 1);
      const failure = results.find((r) => r.status === "rejected") as PromiseRejectedResult;
      errorIs("revision_conflict")(failure.reason);
      const saved = await state();
      assert.equal(saved.settings[0].revision, 1);
      assert.equal(saved.history.length, 2);
      assert.equal(saved.previews.filter((p) => p.consumed_at).length, 1);
    } finally {
      other.release();
    }
  });

  await t.test("same token racing on separate connections is consumed exactly once", async () => {
    await seed();
    const p = await preview();
    const other = await connection();
    try {
      const results = await Promise.allSettled([confirm(p), confirm(p, other)]);
      assert.equal(results.filter((r) => r.status === "fulfilled").length, 1);
      const failure = results.find((r) => r.status === "rejected") as PromiseRejectedResult;
      errorIs("preview_expired_or_consumed")(failure.reason);
      assert.equal((await state()).history.length, 2);
    } finally {
      other.release();
    }
  });

  await t.test("new snapshot ID and same-snapshot exposure, cash, holdings or pending mutations invalidate previews", async () => {
    for (const mutation of [
      `INSERT INTO account_snapshot (ts, total_equity_usd, available_usdt, raw)
        VALUES (clock_timestamp() + INTERVAL '1 second', 100, 80, '{}')`,
      "UPDATE account_snapshot SET available_usdt = 79",
      `INSERT INTO position_snapshot (account_snapshot_id, instrument, side, size, notional_usd)
        SELECT id, 'SPY-USDT-SWAP', 'long', 1, 10 FROM account_snapshot`,
      `INSERT INTO live_position (instrument, strategy, strategy_parameters, entry_order_id,
        entry_client_order_id, owned_quantity, average_price)
        VALUES ('NVDA-USDT-SWAP', 'test', '{}', 'test', 'test', 1, 10)`,
      `INSERT INTO execution_audit (client_order_id, instrument, action, requested_size, state, detail)
        VALUES ('test', 'SPY-USDT-SWAP', 'buy', 1, 'submitted', '{}')`,
    ]) {
      await seed();
      const p = await preview();
      const before = await state();
      await db.query(mutation);
      await assert.rejects(confirm(p), errorIs("snapshot_changed_preview_again"));
      assert.deepEqual(await state(), before);
    }
  });

  await t.test("worker shared 884424 lock blocks confirmation; queued writer rejects nested executor try-lock", async () => {
    await seed();
    const p = await preview();
    const controller = await connection();
    const executor = await connection();
    const confirmer = await connection();
    let confirmation: ReturnType<typeof confirm> | undefined;
    try {
      await controller.query("SELECT pg_advisory_lock_shared(884424)");
      const pid = (await confirmer.query("SELECT pg_backend_pid() AS pid")).rows[0].pid;
      confirmation = confirm(p, confirmer);
      void confirmation.catch(() => {});
      await waitForLock(db, pid, 884424, "ExclusiveLock");
      assert.equal((await executor.query("SELECT pg_try_advisory_lock_shared(884424) AS acquired")).rows[0].acquired, false);
      assert.equal((await readConfig(db)).revision, 0);
      await controller.query("SELECT pg_advisory_unlock_shared(884424)");
      assert.equal((await confirmation).revision, 1);
      assert.equal((await executor.query("SELECT pg_try_advisory_lock_shared(884424) AS acquired")).rows[0].acquired, true);
    } finally {
      await controller.query("SELECT pg_advisory_unlock_all()");
      await executor.query("SELECT pg_advisory_unlock_all()");
      await confirmation?.catch(() => {});
      controller.release(); executor.release(); confirmer.release();
    }
  });

  await t.test("confirmation exclusive lock lasts until commit or rollback and blocks worker shared locks", async () => {
    for (const rollback of [false, true]) {
      await seed();
      const p = await preview();
      const worker = await connection();
      try {
        await db.query("BEGIN");
        await confirmPreview(db, actor, body(p));
        assert.equal((await worker.query("SELECT pg_try_advisory_lock_shared(884424) AS acquired")).rows[0].acquired, false);
        assert.equal((await readConfig(worker)).revision, 0, "Uncommitted configuration is invisible");
        await db.query(rollback ? "ROLLBACK" : "COMMIT");
        assert.equal((await worker.query("SELECT pg_try_advisory_lock_shared(884424) AS acquired")).rows[0].acquired, true);
        assert.equal((await readConfig(worker)).revision, rollback ? 0 : 1);
      } finally {
        await db.query("ROLLBACK");
        await worker.query("SELECT pg_advisory_unlock_all()");
        worker.release();
      }
    }
  });

  await t.test("worker lock order shares configuration 884424 while serializing submissions with 884425", async () => {
    await seed();
    const p = await preview();
    const first = await connection();
    const second = await connection();
    const confirmer = await connection();
    let submission: Promise<unknown> | undefined;
    let confirmation: ReturnType<typeof confirm> | undefined;
    try {
      for (const worker of [first, second]) {
        assert.equal((await worker.query("SELECT pg_try_advisory_lock_shared(884424) AS acquired")).rows[0].acquired, true);
      }
      await first.query("SELECT pg_advisory_lock(884425)");
      assert.equal((await second.query("SELECT pg_try_advisory_lock(884425) AS acquired")).rows[0].acquired, false);
      const pid = (await second.query("SELECT pg_backend_pid() AS pid")).rows[0].pid;
      submission = second.query("SELECT pg_advisory_lock(884425)");
      void submission.catch(() => {});
      await waitForLock(db, pid, 884425, "ExclusiveLock");
      const confirmPid = (await confirmer.query("SELECT pg_backend_pid() AS pid")).rows[0].pid;
      confirmation = confirm(p, confirmer);
      void confirmation.catch(() => {});
      await waitForLock(db, confirmPid, 884424, "ExclusiveLock");
      await first.query("SELECT pg_advisory_unlock(884425), pg_advisory_unlock_shared(884424)");
      await submission;
      assert.equal((await readConfig(db)).revision, 0, "Second executor still holds shared configuration lock");
      await second.query("SELECT pg_advisory_unlock(884425), pg_advisory_unlock_shared(884424)");
      assert.equal((await confirmation).revision, 1);
    } finally {
      await first.query("SELECT pg_advisory_unlock_all()");
      await submission?.catch(() => {});
      await second.query("SELECT pg_advisory_unlock_all()");
      await confirmation?.catch(() => {});
      first.release(); second.release(); confirmer.release();
    }
  });
});
