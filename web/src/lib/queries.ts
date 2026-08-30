import { query } from "./db";

export type Account = {
  id: string;
  ts: Date;
  total_equity_usd: string;
  available_usdt: string;
};

export type Position = {
  instrument: string;
  side: string;
  size: string;
  average_price: string | null;
  mark_price: string | null;
  leverage: string | null;
  notional_usd: string | null;
  unrealized_pnl: string | null;
  liquidation_price: string | null;
  margin_mode: string | null;
};

export type Decision = {
  instrument: string;
  ts: Date;
  action: "buy" | "sell" | "hold";
  confidence: string;
  reference_price: string;
  rationale: string;
  approved: boolean;
  mode: string;
  proposed_notional: string;
  reasons: string[];
};

export type News = {
  source: string;
  published_at: Date | null;
  title: string;
  url: string;
};

export type Heartbeat = {
  last_seen_at: Date;
  status: string;
  detail: Record<string, string>;
};

export type Basis = {
  instrument: string;
  ts: Date;
  perpetual_price: string;
  underlying_price: string;
  basis_bps: string;
  reference_stale: boolean;
};

export type Event = {
  symbol: string;
  event_type: string;
  starts_at: Date;
  source: string;
};

export type Backtest = {
  symbol: string;
  strategy: string;
  test_return_pct: string;
  test_drawdown_pct: string;
  test_trades: number;
  test_start: Date;
  test_end: Date;
};

export type ShadowAccount = {
  initial_cash: string;
  cash: string;
  realized_pnl: string;
  equity: string;
  unrealized_pnl: string;
  drawdown_pct: string;
  ts: Date;
};

export type ShadowPosition = {
  instrument: string;
  strategy: string;
  quantity: string;
  average_price: string;
  mark_price: string;
  unrealized_pnl: string;
};

export type ShadowTrade = {
  id: string;
  ts: Date;
  instrument: string;
  strategy: string;
  side: "buy" | "sell";
  quantity: string;
  execution_price: string;
  fee: string;
  realized_pnl: string | null;
};

export type Candidate = {
  symbol: string;
  family: string;
  score: string;
  parameters: Record<string, number>;
  return_pct: string;
  drawdown_pct: string;
  positive_folds: number;
  trades: number;
  promoted_at: Date;
};

export type ExecutionAudit = {
  ts: Date;
  instrument: string;
  action: string;
  requested_size: string;
  requested_price: string | null;
  state: string;
};

export async function dashboardData() {
  const instruments = (process.env.TRADING_INSTRUMENTS ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const accountRows = await query<Account>(
    "SELECT id, ts, total_equity_usd, available_usdt FROM account_snapshot ORDER BY ts DESC LIMIT 1",
  );
  const account = accountRows[0] ?? null;
  const [
    positions,
    decisions,
    news,
    heartbeat,
    basis,
    events,
    backtests,
    shadowAccounts,
    shadowPositions,
    shadowTrades,
    candidates,
    executionAudits,
  ] = await Promise.all([
    account
      ? query<Position>(
          "SELECT instrument, side, size, average_price, mark_price, leverage, notional_usd, unrealized_pnl, liquidation_price, margin_mode FROM position_snapshot WHERE account_snapshot_id = $1 ORDER BY instrument",
          [account.id],
        )
      : Promise.resolve([]),
    query<Decision>(
      `SELECT DISTINCT ON (s.instrument)
         s.instrument, s.ts, s.action, s.confidence, s.reference_price,
         s.rationale, r.approved, r.mode, r.proposed_notional, r.reasons
       FROM strategy_signal s JOIN risk_decision r ON r.signal_id = s.id
       WHERE s.instrument = ANY($1::text[])
       ORDER BY s.instrument, s.ts DESC`,
      [instruments],
    ),
    query<News>(
      "SELECT source, published_at, title, url FROM news_item ORDER BY published_at DESC NULLS LAST LIMIT 12",
    ),
    query<Heartbeat>(
      "SELECT last_seen_at, status, detail FROM worker_heartbeat WHERE worker = 'collector'",
    ),
    query<Basis>(
      `SELECT DISTINCT ON (instrument)
         instrument, ts, perpetual_price, underlying_price, basis_bps,
         reference_stale OR NOW() - underlying_quoted_at > INTERVAL '20 minutes'
           AS reference_stale
       FROM basis_snapshot
       WHERE instrument = ANY($1::text[])
       ORDER BY instrument, ts DESC`,
      [instruments],
    ),
    query<Event>(
      `SELECT symbol, event_type, starts_at, source
       FROM corporate_event
       WHERE starts_at BETWEEN NOW() - INTERVAL '1 day' AND NOW() + INTERVAL '30 days'
       ORDER BY starts_at LIMIT 20`,
    ),
    query<Backtest>(
      `SELECT DISTINCT ON (symbol, strategy)
         symbol, strategy, test_return_pct, test_drawdown_pct, test_trades,
         test_start, test_end
       FROM backtest_result
       ORDER BY symbol, strategy, generated_at DESC`,
    ),
    query<ShadowAccount>(
      `SELECT a.initial_cash, a.cash, a.realized_pnl,
         e.equity, e.unrealized_pnl, e.ts,
         CASE WHEN peak.peak > 0
           THEN (peak.peak - e.equity) / peak.peak * 100 ELSE 0 END AS drawdown_pct
       FROM shadow_account a
       JOIN LATERAL (
         SELECT equity, unrealized_pnl, ts
         FROM shadow_equity_snapshot ORDER BY ts DESC LIMIT 1
       ) e ON TRUE
       JOIN LATERAL (
         SELECT MAX(equity) AS peak FROM shadow_equity_snapshot
       ) peak ON TRUE
       WHERE a.id = 1`,
    ),
    query<ShadowPosition>(
      `SELECT p.instrument, p.strategy, p.quantity, p.average_price,
         m.last_price AS mark_price,
         p.quantity * (m.last_price - p.average_price) AS unrealized_pnl
       FROM shadow_position p
       JOIN LATERAL (
         SELECT last_price FROM market_snapshot
         WHERE instrument = p.instrument ORDER BY ts DESC LIMIT 1
       ) m ON TRUE
       ORDER BY p.instrument`,
    ),
    query<ShadowTrade>(
      `SELECT id, ts, instrument, strategy, side, quantity,
         execution_price, fee, realized_pnl
       FROM shadow_trade ORDER BY ts DESC LIMIT 20`,
    ),
    query<Candidate>(
      `SELECT c.symbol, c.family, c.score, c.promoted_at,
         e.parameters, e.return_pct, e.drawdown_pct,
         e.positive_folds, e.trades
       FROM strategy_candidate c
       JOIN strategy_experiment e ON e.id = c.experiment_id
       ORDER BY c.score DESC LIMIT 20`,
    ),
    query<ExecutionAudit>(
      `SELECT ts, instrument, action, requested_size, requested_price, state
       FROM execution_audit ORDER BY ts DESC LIMIT 10`,
    ),
  ]);
  return {
    account,
    positions,
    decisions,
    news,
    basis,
    events,
    backtests,
    shadowAccount: shadowAccounts[0] ?? null,
    shadowPositions,
    shadowTrades,
    candidates,
    executionAudits,
    heartbeat: heartbeat[0] ?? null,
  };
}
