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

export async function dashboardData() {
  const accountRows = await query<Account>(
    "SELECT id, ts, total_equity_usd, available_usdt FROM account_snapshot ORDER BY ts DESC LIMIT 1",
  );
  const account = accountRows[0] ?? null;
  const [positions, decisions, news, heartbeat] = await Promise.all([
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
       ORDER BY s.instrument, s.ts DESC`,
    ),
    query<News>(
      "SELECT source, published_at, title, url FROM news_item ORDER BY published_at DESC NULLS LAST LIMIT 12",
    ),
    query<Heartbeat>(
      "SELECT last_seen_at, status, detail FROM worker_heartbeat WHERE worker = 'collector'",
    ),
  ]);
  return { account, positions, decisions, news, heartbeat: heartbeat[0] ?? null };
}

