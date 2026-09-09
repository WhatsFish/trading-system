-- Operator-applied migration. Application startup never runs this file.
BEGIN;
CREATE TABLE IF NOT EXISTS portfolio_settings (
  id SMALLINT PRIMARY KEY CHECK (id = 1),
  revision INTEGER NOT NULL CHECK (revision >= 0),
  config JSONB NOT NULL CHECK (jsonb_typeof(config) = 'object'),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_settings_history (
  revision INTEGER PRIMARY KEY CHECK (revision >= 0),
  config JSONB NOT NULL,
  previous_config JSONB,
  confirmed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  actor TEXT NOT NULL,
  preview JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_settings_preview (
  token_hash TEXT PRIMARY KEY,
  expected_revision INTEGER NOT NULL,
  config JSONB NOT NULL,
  summary JSONB NOT NULL,
  actor TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '10 minutes',
  consumed_at TIMESTAMPTZ
);
INSERT INTO portfolio_settings (id, revision, config, updated_by)
VALUES (1, 0, '{
  "maxHoldings":5,"maxPerAssetGroup":2,"maxPerStrategyCluster":2,
  "totalBudgetMode":"legacy_equity","totalBudgetUsdt":0,
  "positionBudgetMode":"percent","positionBudgetValue":18,
  "cashReserveUsdt":0,"instrumentBudgets":{}
}', 'migration-default')
ON CONFLICT (id) DO NOTHING;
INSERT INTO portfolio_settings_history (revision, config, actor, preview)
SELECT revision, config, updated_by, '{"kind":"legacy-default"}'::jsonb
FROM portfolio_settings WHERE revision = 0
ON CONFLICT (revision) DO NOTHING;
COMMIT;
