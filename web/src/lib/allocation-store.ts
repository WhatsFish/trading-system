import { allocationPreview, type AllocationHolding } from "./allocation";
import { readConfig, readSnapshot, type Connection } from "./portfolio-store";

export async function readAllocation(db: Connection) {
  const current = await readConfig(db);
  const snapshot = await readSnapshot(db);
  const heartbeat = (await db.query(
    "SELECT last_seen_at, detail FROM worker_heartbeat WHERE worker = 'live-controller'",
  )).rows[0];
  const positions = (await db.query(
    "SELECT instrument, side, size::text, ABS(notional_usd)::text AS notional FROM position_snapshot WHERE account_snapshot_id = $1 AND size <> 0",
    [snapshot.id],
  )).rows;
  const exact = (await db.query(
    "SELECT total_equity_usd::text AS equity, available_usdt::text AS available FROM account_snapshot WHERE id = $1",
    [snapshot.id],
  )).rows[0];
  const holdings = (await db.query(`
    SELECT l.instrument, l.strategy, l.strategy_parameters, l.owned_quantity::text, l.exit_client_order_id,
      m.ts AS market_ts, m.last_price::text AS market_price, m.instrument_state,
      t.family AS target_family, t.parameters AS target_parameters, t.current_target, t.computed_at
    FROM live_position l
    LEFT JOIN LATERAL (
      SELECT ts, last_price, instrument_state FROM market_snapshot
      WHERE instrument = l.instrument ORDER BY ts DESC LIMIT 1
    ) m ON TRUE
    LEFT JOIN LATERAL (
      SELECT family, parameters, current_target, computed_at FROM strategy_live_target
      WHERE symbol = regexp_replace(l.instrument, '-USDT-SWAP$', '')
        AND family = l.strategy AND parameters = l.strategy_parameters
      ORDER BY computed_at DESC LIMIT 1
    ) t ON TRUE
    WHERE l.owned_quantity > 0
    ORDER BY l.instrument
  `)).rows;
  return allocationPreview({
    ...current, snapshot,
    exactAmounts: { equity: exact.equity, available: exact.available, exposures: positions.map((p) => p.notional) },
    controller: heartbeat ? {
      lastSeenAt: new Date(heartbeat.last_seen_at).toISOString(),
      revision: typeof heartbeat.detail?.portfolioRevision === "number" ? heartbeat.detail.portfolioRevision : null,
      settingsError: Boolean(heartbeat.detail?.portfolioError),
    } : null,
    holdings: holdings.map((row): AllocationHolding => ({
      instrument: row.instrument, strategy: row.strategy, parameters: row.strategy_parameters,
      ownedQuantity: row.owned_quantity,
      accountPositions: positions.filter((p) => p.instrument === row.instrument).map((p) => ({ side: p.side, size: p.size })),
      market: row.market_ts ? { ts: new Date(row.market_ts).toISOString(), price: row.market_price, state: row.instrument_state } : null,
      signal: row.computed_at ? {
        family: row.target_family, parameters: row.target_parameters,
        target: row.current_target, computedAt: new Date(row.computed_at).toISOString(),
      } : null,
      // The current database stores prices, not exchange lot/minimum metadata.
      // Never substitute guessed sizes or fetch trading credentials/exchange data.
      sizeRules: null,
      exitPending: Boolean(row.exit_client_order_id),
    })),
  });
}
