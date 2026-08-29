CREATE TABLE IF NOT EXISTS market_candle (
  instrument   TEXT        NOT NULL,
  bar          TEXT        NOT NULL,
  ts            TIMESTAMPTZ NOT NULL,
  open          NUMERIC     NOT NULL,
  high          NUMERIC     NOT NULL,
  low           NUMERIC     NOT NULL,
  close         NUMERIC     NOT NULL,
  volume        NUMERIC     NOT NULL,
  confirmed     BOOLEAN     NOT NULL,
  ingested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (instrument, bar, ts)
);
CREATE INDEX IF NOT EXISTS market_candle_recent
  ON market_candle (instrument, bar, ts DESC);

CREATE TABLE IF NOT EXISTS market_snapshot (
  id             BIGSERIAL   PRIMARY KEY,
  instrument     TEXT        NOT NULL,
  ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_price     NUMERIC     NOT NULL,
  bid_price      NUMERIC,
  ask_price      NUMERIC,
  open_24h       NUMERIC,
  high_24h       NUMERIC,
  low_24h        NUMERIC,
  volume_24h     NUMERIC,
  instrument_state TEXT,
  rule_type      TEXT
);
CREATE INDEX IF NOT EXISTS market_snapshot_recent
  ON market_snapshot (instrument, ts DESC);

CREATE TABLE IF NOT EXISTS account_snapshot (
  id              BIGSERIAL   PRIMARY KEY,
  ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  total_equity_usd NUMERIC     NOT NULL,
  available_usdt  NUMERIC     NOT NULL,
  raw             JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS account_snapshot_recent ON account_snapshot (ts DESC);

CREATE TABLE IF NOT EXISTS position_snapshot (
  account_snapshot_id BIGINT      NOT NULL REFERENCES account_snapshot(id) ON DELETE CASCADE,
  instrument          TEXT        NOT NULL,
  side                TEXT        NOT NULL,
  size                NUMERIC     NOT NULL,
  average_price       NUMERIC,
  mark_price          NUMERIC,
  leverage            NUMERIC,
  notional_usd        NUMERIC,
  unrealized_pnl      NUMERIC,
  liquidation_price   NUMERIC,
  margin_mode         TEXT,
  PRIMARY KEY (account_snapshot_id, instrument, side)
);

CREATE TABLE IF NOT EXISTS strategy_signal (
  id             BIGSERIAL   PRIMARY KEY,
  instrument     TEXT        NOT NULL,
  strategy       TEXT        NOT NULL,
  ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  action         TEXT        NOT NULL CHECK (action IN ('buy', 'sell', 'hold')),
  confidence     NUMERIC     NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  reference_price NUMERIC    NOT NULL,
  features       JSONB       NOT NULL,
  rationale      TEXT        NOT NULL
);
CREATE INDEX IF NOT EXISTS strategy_signal_recent
  ON strategy_signal (instrument, ts DESC);

CREATE TABLE IF NOT EXISTS risk_decision (
  id                 BIGSERIAL   PRIMARY KEY,
  signal_id          BIGINT      NOT NULL REFERENCES strategy_signal(id),
  ts                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  approved           BOOLEAN     NOT NULL,
  mode               TEXT        NOT NULL,
  proposed_notional  NUMERIC     NOT NULL DEFAULT 0,
  reasons            JSONB       NOT NULL,
  limits             JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS risk_decision_recent ON risk_decision (ts DESC);

CREATE TABLE IF NOT EXISTS news_item (
  id            BIGSERIAL   PRIMARY KEY,
  source        TEXT        NOT NULL,
  published_at  TIMESTAMPTZ,
  title         TEXT        NOT NULL,
  url           TEXT        NOT NULL,
  summary       TEXT,
  ingested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (source, url)
);
CREATE INDEX IF NOT EXISTS news_item_recent ON news_item (published_at DESC);

CREATE TABLE IF NOT EXISTS worker_heartbeat (
  worker       TEXT PRIMARY KEY,
  last_seen_at TIMESTAMPTZ NOT NULL,
  status       TEXT NOT NULL,
  detail       JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS system_setting (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO system_setting (key, value)
VALUES ('execution_enabled', 'false')
ON CONFLICT (key) DO NOTHING;

