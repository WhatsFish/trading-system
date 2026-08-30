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

CREATE TABLE IF NOT EXISTS underlying_daily (
  symbol       TEXT        NOT NULL,
  date         DATE        NOT NULL,
  open         NUMERIC     NOT NULL,
  high         NUMERIC     NOT NULL,
  low          NUMERIC     NOT NULL,
  close        NUMERIC     NOT NULL,
  volume       BIGINT,
  source       TEXT        NOT NULL,
  ingested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS underlying_daily_recent
  ON underlying_daily (symbol, date DESC);

CREATE TABLE IF NOT EXISTS underlying_quote (
  symbol       TEXT        NOT NULL,
  quoted_at    TIMESTAMPTZ NOT NULL,
  price        NUMERIC     NOT NULL,
  source       TEXT        NOT NULL,
  ingested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, quoted_at)
);
CREATE INDEX IF NOT EXISTS underlying_quote_recent
  ON underlying_quote (symbol, quoted_at DESC);

CREATE TABLE IF NOT EXISTS basis_snapshot (
  id                 BIGSERIAL   PRIMARY KEY,
  instrument         TEXT        NOT NULL,
  ts                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  perpetual_price    NUMERIC     NOT NULL,
  underlying_price   NUMERIC     NOT NULL,
  underlying_quoted_at TIMESTAMPTZ NOT NULL,
  basis_bps          NUMERIC     NOT NULL,
  reference_stale    BOOLEAN     NOT NULL
);
CREATE INDEX IF NOT EXISTS basis_snapshot_recent
  ON basis_snapshot (instrument, ts DESC);

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

CREATE TABLE IF NOT EXISTS sec_filing (
  accession_number TEXT        PRIMARY KEY,
  symbol           TEXT        NOT NULL,
  form             TEXT        NOT NULL,
  filed_at         DATE        NOT NULL,
  url              TEXT        NOT NULL,
  ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS sec_filing_recent
  ON sec_filing (symbol, filed_at DESC);

CREATE TABLE IF NOT EXISTS corporate_event (
  symbol       TEXT        NOT NULL,
  event_type   TEXT        NOT NULL,
  starts_at    TIMESTAMPTZ NOT NULL,
  source       TEXT        NOT NULL,
  details      JSONB       NOT NULL DEFAULT '{}'::jsonb,
  ingested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, event_type, starts_at, source)
);
CREATE INDEX IF NOT EXISTS corporate_event_upcoming
  ON corporate_event (starts_at);

CREATE TABLE IF NOT EXISTS backtest_result (
  id                BIGSERIAL   PRIMARY KEY,
  symbol            TEXT        NOT NULL,
  strategy          TEXT        NOT NULL,
  generated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  train_start       DATE        NOT NULL,
  train_end         DATE        NOT NULL,
  test_start        DATE        NOT NULL,
  test_end          DATE        NOT NULL,
  test_return_pct   NUMERIC     NOT NULL,
  test_drawdown_pct NUMERIC     NOT NULL,
  test_trades       INTEGER     NOT NULL,
  assumptions       JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS backtest_result_recent
  ON backtest_result (symbol, strategy, generated_at DESC);

CREATE TABLE IF NOT EXISTS strategy_experiment (
  id               BIGSERIAL   PRIMARY KEY,
  run_id           UUID        NOT NULL,
  symbol           TEXT        NOT NULL,
  family           TEXT        NOT NULL,
  parameters       JSONB       NOT NULL,
  fold_returns     JSONB       NOT NULL,
  return_pct       NUMERIC     NOT NULL,
  drawdown_pct     NUMERIC     NOT NULL,
  trades           INTEGER     NOT NULL,
  positive_folds   INTEGER     NOT NULL,
  score            NUMERIC     NOT NULL,
  eligible         BOOLEAN     NOT NULL,
  rejection_reason TEXT,
  generated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS strategy_experiment_rank
  ON strategy_experiment (run_id, eligible, score DESC);

CREATE TABLE IF NOT EXISTS strategy_candidate (
  symbol         TEXT        NOT NULL,
  family         TEXT        NOT NULL,
  experiment_id  BIGINT      NOT NULL REFERENCES strategy_experiment(id),
  score          NUMERIC     NOT NULL,
  promoted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, family)
);

CREATE TABLE IF NOT EXISTS execution_audit (
  id              BIGSERIAL   PRIMARY KEY,
  client_order_id TEXT        NOT NULL UNIQUE,
  ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  instrument      TEXT        NOT NULL,
  action          TEXT        NOT NULL,
  requested_size  NUMERIC     NOT NULL,
  requested_price NUMERIC,
  exchange_order_id TEXT,
  state           TEXT        NOT NULL,
  detail          JSONB       NOT NULL
);

CREATE TABLE IF NOT EXISTS protective_order (
  instrument       TEXT        PRIMARY KEY,
  exchange_algo_id TEXT        NOT NULL,
  trigger_price    NUMERIC     NOT NULL,
  size             NUMERIC     NOT NULL,
  reconciled_size  NUMERIC     NOT NULL DEFAULT 0,
  state            TEXT        NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE protective_order
  ADD COLUMN IF NOT EXISTS reconciled_size NUMERIC NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS live_position (
  instrument       TEXT        PRIMARY KEY,
  strategy         TEXT        NOT NULL,
  entry_order_id   TEXT        NOT NULL,
  entry_client_order_id TEXT    NOT NULL,
  owned_quantity   NUMERIC     NOT NULL CHECK (owned_quantity > 0),
  average_price    NUMERIC     NOT NULL,
  exit_client_order_id TEXT,
  exit_state       TEXT,
  opened_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE live_position ADD COLUMN IF NOT EXISTS entry_client_order_id TEXT;
ALTER TABLE live_position ADD COLUMN IF NOT EXISTS owned_quantity NUMERIC;
ALTER TABLE live_position ADD COLUMN IF NOT EXISTS average_price NUMERIC;
ALTER TABLE live_position ADD COLUMN IF NOT EXISTS exit_client_order_id TEXT;
ALTER TABLE live_position ADD COLUMN IF NOT EXISTS exit_state TEXT;
ALTER TABLE live_position ALTER COLUMN entry_client_order_id SET NOT NULL;
ALTER TABLE live_position ALTER COLUMN owned_quantity SET NOT NULL;
ALTER TABLE live_position ALTER COLUMN average_price SET NOT NULL;

CREATE TABLE IF NOT EXISTS shadow_account (
  id            SMALLINT    PRIMARY KEY CHECK (id = 1),
  initial_cash  NUMERIC     NOT NULL,
  cash          NUMERIC     NOT NULL,
  realized_pnl  NUMERIC     NOT NULL DEFAULT 0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO shadow_account (id, initial_cash, cash)
VALUES (1, 30, 30)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS shadow_position (
  instrument  TEXT        PRIMARY KEY,
  symbol      TEXT        NOT NULL,
  strategy    TEXT        NOT NULL,
  quantity    NUMERIC     NOT NULL CHECK (quantity > 0),
  average_price NUMERIC   NOT NULL,
  entry_fee   NUMERIC     NOT NULL,
  opened_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shadow_trade (
  id            BIGSERIAL   PRIMARY KEY,
  ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  instrument    TEXT        NOT NULL,
  strategy      TEXT        NOT NULL,
  side          TEXT        NOT NULL CHECK (side IN ('buy', 'sell')),
  quantity      NUMERIC     NOT NULL,
  market_price  NUMERIC     NOT NULL,
  execution_price NUMERIC   NOT NULL,
  fee           NUMERIC     NOT NULL,
  realized_pnl  NUMERIC,
  reason        TEXT        NOT NULL
);
CREATE INDEX IF NOT EXISTS shadow_trade_recent ON shadow_trade (ts DESC);

CREATE TABLE IF NOT EXISTS shadow_equity_snapshot (
  id             BIGSERIAL   PRIMARY KEY,
  ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  cash           NUMERIC     NOT NULL,
  market_value   NUMERIC     NOT NULL,
  equity         NUMERIC     NOT NULL,
  realized_pnl   NUMERIC     NOT NULL,
  unrealized_pnl NUMERIC     NOT NULL
);
CREATE INDEX IF NOT EXISTS shadow_equity_recent
  ON shadow_equity_snapshot (ts DESC);

CREATE TABLE IF NOT EXISTS shadow_run (
  market_date DATE        PRIMARY KEY,
  ran_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  status      TEXT        NOT NULL,
  detail      JSONB       NOT NULL
);

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
