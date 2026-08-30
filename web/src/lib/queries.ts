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
  live_experience_count: number;
  live_adjustment: string;
  current_target: number;
};

export type ExecutionAudit = {
  ts: Date;
  instrument: string;
  action: string;
  requested_size: string;
  requested_price: string | null;
  state: string;
};

export type LiveState = {
  execution_enabled: boolean;
  controller_status: string | null;
  controller_seen_at: Date | null;
  managed_instrument: string | null;
};

export type LiveExperiment = {
  id: string;
  instrument: string;
  strategy: string;
  hypothesis: string;
  entry_time: Date;
  entry_quantity: string;
  entry_price: string;
  status: string;
  exit_time: Date | null;
  exit_reason: string | null;
  net_pnl: string | null;
  return_pct: string | null;
  max_favorable_pct: string;
  max_adverse_pct: string;
  postmortem: {
    outcome?: string;
    summary?: string;
    lessonCodes?: string[];
  } | null;
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
    candidates,
    executionAudits,
    liveStates,
    liveExperiments,
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
    query<Candidate>(
      `SELECT c.symbol, c.family, c.score, c.promoted_at,
         e.parameters, e.return_pct, e.drawdown_pct,
         e.positive_folds, e.trades, e.live_experience_count,
         e.live_adjustment, e.current_target
       FROM strategy_candidate c
       JOIN strategy_experiment e ON e.id = c.experiment_id
       ORDER BY c.score DESC LIMIT 20`,
    ),
    query<ExecutionAudit>(
      `SELECT ts, instrument, action, requested_size, requested_price, state
       FROM execution_audit ORDER BY ts DESC LIMIT 10`,
    ),
    query<LiveState>(
      `SELECT
         COALESCE((SELECT value = 'true' FROM system_setting
                   WHERE key = 'execution_enabled'), false) AS execution_enabled,
         h.status AS controller_status,
         h.last_seen_at AS controller_seen_at,
         h.detail->>'managedInstrument' AS managed_instrument
       FROM (SELECT 1) seed
       LEFT JOIN worker_heartbeat h ON h.worker = 'live-controller'`,
    ),
    query<LiveExperiment>(
      `SELECT id, instrument, strategy, hypothesis, entry_time,
         entry_quantity, entry_price, status, exit_time, exit_reason,
         net_pnl, return_pct, max_favorable_pct, max_adverse_pct, postmortem
       FROM live_experiment ORDER BY entry_time DESC LIMIT 20`,
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
    candidates,
    executionAudits,
    liveState: liveStates[0],
    liveExperiments,
    heartbeat: heartbeat[0] ?? null,
  };
}
