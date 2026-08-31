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
  system_strategy: string | null;
  strategy_parameters: Record<string, number> | null;
  system_quantity: string | null;
  stop_trigger_price: string | null;
  system_average_price: string | null;
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
  managed_count: number;
  scan: Array<{
    symbol: string;
    family: string;
    status: string;
    reasons: string[];
  }>;
};

export type MarketSession = {
  latest_reference: Date | null;
};

export type LiveExperiment = {
  id: string;
  instrument: string;
  strategy: string;
  strategy_parameters: Record<string, number>;
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
    news,
    heartbeat,
    basis,
    events,
    backtests,
    candidates,
    opportunities,
    executionAudits,
    liveStates,
    liveExperiments,
    marketSessions,
  ] = await Promise.all([
    account
      ? query<Position>(
          `SELECT p.instrument, p.side, p.size, p.average_price,
             p.mark_price, p.leverage, p.notional_usd, p.unrealized_pnl,
             p.liquidation_price, p.margin_mode,
             l.strategy AS system_strategy,
             l.strategy_parameters,
             l.owned_quantity AS system_quantity,
             stop.trigger_price AS stop_trigger_price,
             l.average_price AS system_average_price
           FROM position_snapshot p
           LEFT JOIN live_position l
             ON l.instrument = p.instrument AND p.side = 'long'
           LEFT JOIN protective_order stop
             ON stop.instrument = p.instrument AND stop.state = 'active'
           WHERE p.account_snapshot_id = $1
           ORDER BY p.instrument`,
          [account.id],
        )
      : Promise.resolve([]),
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
         e.parameters, e.holdout_return_pct AS return_pct,
         e.holdout_drawdown_pct AS drawdown_pct,
         e.positive_folds, e.trades, e.live_experience_count,
         e.live_adjustment, e.current_target
       FROM strategy_candidate c
       JOIN strategy_experiment e ON e.id = c.experiment_id
       ORDER BY c.score DESC LIMIT 100`,
    ),
    query<Candidate>(
      `SELECT symbol, family, score, promoted_at, parameters,
         holdout_return_pct AS return_pct,
         holdout_drawdown_pct AS drawdown_pct,
         positive_folds, trades, live_experience_count,
         live_adjustment, current_target
       FROM (
         SELECT DISTINCT ON (e.symbol)
           e.symbol, e.family, c.score, c.promoted_at, e.parameters,
           e.holdout_return_pct, e.holdout_drawdown_pct,
           e.positive_folds, e.trades, e.live_experience_count,
           e.live_adjustment, t.current_target
         FROM strategy_candidate c
         JOIN strategy_experiment e ON e.id = c.experiment_id
         JOIN strategy_live_target t
           ON t.symbol = e.symbol AND t.family = e.family
          AND t.parameters = e.parameters
          AND t.computed_at > NOW() - INTERVAL '4 days'
         WHERE t.current_target = 1
         ORDER BY e.symbol, c.score DESC
       ) active
       ORDER BY score DESC LIMIT 10`,
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
         h.detail->>'managedInstrument' AS managed_instrument,
         COALESCE((h.detail->>'managedCount')::int, 0) AS managed_count,
         COALESCE(h.detail->'scan', '[]'::jsonb) AS scan
       FROM (SELECT 1) seed
       LEFT JOIN worker_heartbeat h ON h.worker = 'live-controller'`,
    ),
    query<LiveExperiment>(
      `SELECT id, instrument, strategy, strategy_parameters, hypothesis, entry_time,
         entry_quantity, entry_price, status, exit_time, exit_reason,
         net_pnl, return_pct, max_favorable_pct, max_adverse_pct, postmortem
       FROM live_experiment ORDER BY entry_time DESC LIMIT 20`,
    ),
    query<MarketSession>(
      "SELECT MAX(underlying_quoted_at) AS latest_reference FROM basis_snapshot",
    ),
  ]);
  return {
    account,
    positions,
    news,
    basis,
    events,
    backtests,
    candidates,
    opportunities,
    executionAudits,
    liveState: liveStates[0],
    liveExperiments,
    heartbeat: heartbeat[0] ?? null,
    positionTrends: await getPositionTrends(positions),
    latestReference: marketSessions[0]?.latest_reference ?? null,
  };
}

async function getPositionTrends(positions: Position[]) {
  const pairs = await Promise.all(
    positions.map(async (position) => {
      try {
        const response = await fetch(
          `https://www.okx.com/api/v5/market/ticker?instId=${encodeURIComponent(position.instrument)}`,
          { next: { revalidate: 30 } },
        );
        if (!response.ok) return [position.instrument, null] as const;
        const payload = await response.json() as {
          code: string;
          data: Array<{ last: string; open24h: string }>;
        };
        const ticker = payload.data[0];
        if (payload.code !== "0" || !ticker || Number(ticker.open24h) === 0) {
          return [position.instrument, null] as const;
        }
        return [
          position.instrument,
          (Number(ticker.last) / Number(ticker.open24h) - 1) * 100,
        ] as const;
      } catch {
        return [position.instrument, null] as const;
      }
    }),
  );
  return Object.fromEntries(pairs) as Record<string, number | null>;
}
