# Trading System

A 24/7, audit-first OKX US-equity-perpetual research system. It covers 50
technology, semiconductor and healthcare names plus broad/sector ETFs, collects
market and account data, evaluates session-aware deterministic strategies,
enforces hard risk limits, and exposes a private dashboard.

The collector defaults to `observe`: decisions are recorded without sending
orders. The separate `live` controller can execute when both execution gates
are enabled; do not assume an existing installation is locked.

## Architecture

- `worker/`: Python collector, strategy engine, risk engine, and backtester
- `web/`: private Next.js dashboard
- `db/`: PostgreSQL schema and idempotent bootstrap
- Shared Postgres and Docker network used by the other services on this VM

## Safety model

- No withdrawal endpoint exists in the codebase.
- The web container never receives OKX credentials.
- Pre-market instruments are blocked.
- Position, leverage, daily-loss, drawdown, stale-data, and cooldown limits
  are deterministic and cannot be overridden by a strategy or LLM.
- `TRADING_MODE=observe` and `LIVE_TRADING_ACK` form separate execution gates.
- Monthly return is an evaluation target, never a guaranteed result or a
  reason to force a trade.

## Local checks

```bash
python3 -m unittest discover -s worker/tests -v
docker compose build
```

Backfill and evaluate the deterministic baseline:

```bash
docker compose exec worker python -m trading_system.backfill --days 30
docker compose exec worker sh -lc \
  'python -m trading_system.backtest SPY-USDT-SWAP --database-url \
  "postgresql://trading_system:${TRADING_PG_PASSWORD}@db:5432/trading_system"'
```

Backtest output is evidence about a historical sample, not permission to trade.
Use walk-forward/out-of-sample validation and shadow operation before enabling
even a small live allocation.

Refresh the isolated underlying/SEC research layer and its multi-window
out-of-sample comparisons:

```bash
./scripts/run-research.sh
```

The `research` container has no OKX credentials. The credential-bearing
`worker` image intentionally does not install `yfinance`.

The earlier shadow portfolio is retained as an offline diagnostic tool but is
not scheduled or shown on the primary dashboard. Live experiments are the
operational source of trading experience.

The weekday research job evaluates 12,300 configurations across 27 distinct
strategy families and updates the nested-holdout candidate leaderboard. Every
rejected experiment remains auditable. See
[`docs/strategy-library.md`](docs/strategy-library.md).

The execution transport test requires a one-off acknowledgement and places a
minimum-size post-only order far from market before immediately canceling it:

```bash
docker compose exec -T \
  -e EXECUTION_TEST_ACK=PLACE_AND_CANCEL_REAL_ORDER \
  worker python -m trading_system.executor
```

Bounded live automation runs as the separate `live` service. Its database gate
can be changed without rebuilding or stopping account observation:

```bash
./scripts/live-off.sh  # immediately blocks new entries; managed exits continue
./scripts/live-on.sh
```

The default policy allows up to five longs, each sized up to 18%
of current equity, with 1x isolated leverage, an atomic attached 5% stop, and
no short opening. At most two positions may share an asset group or strategy
cluster. The executor enforces the exact notional authorized by each risk
decision rather than a fixed dollar cap.

Live experiments retain their hypothesis, entry context, fees, mark-to-market
path, MFE/MAE, outcome, and deterministic postmortem. After five closed samples
in a symbol/strategy family, live outcomes receive a bounded weight in the
next strategy-lab ranking.

The live controller scans all eligible candidates once per minute, ordered by
score. It recalculates current targets, skips flat candidates, and continues
after candidate-specific risk blocks until one entry is approved.

## Holdings and budget settings (operator-controlled activation)

The bilingual portal at `/trading/settings?lang=en` (or `lang=zh`) supports:

- maximum holdings from 1–50 (for example 5, 6, 7, 8, 9);
- legacy equity limits, a 100%-of-account-equity budget, or a fixed USDT
  total budget such as 30 or 300, clamped to actual account equity;
- default and per-instrument notional budgets in fixed USDT or percent;
- advanced per-asset-group and per-strategy-cluster caps from 1–50 (default 2);
- a USDT cash reserve, current/proposed preview, explicit confirmation,
  optimistic revision checks, and a recent audit history.

Amounts are **notional, not margin**; leverage stays 1x with no borrowing.
Confirmed budgets can increase individual positions beyond the default 18%
(for example fixed 30 against equity 100), within actual equity, available
cash and remaining total budget; the 200% aggregate risk guard still applies.
Four asset groups at the default cap of two permit at most eight holdings:
nine requires an explicit group cap of at least three, sufficient cluster caps,
signals and cash.
Existing holdings are never automatically resized or liquidated by a settings
change. Protective stops and normal strategy exits remain active.
After the first save, any existing mark exposure above its per-instrument
budget freezes all new entries/replacements, including after appreciation or
an equity decline—even if only maximum holdings was raised. The preview warns
and lists affected holdings; settings do not rebalance.

**Development of this feature does not activate a sixth holding.** No production
migration, setting change, deployment, restart or order is part of development.
For activation, the operator must review the branch and tests, arrange a safe
rollout with new entries disabled, apply only `db/portfolio-settings.sql` to the
intended database with PostgreSQL `ON_ERROR_STOP`, and deploy the reviewed worker
and web images together. Do not run the full bootstrap just to upgrade an
existing database (bootstrap also manages the database role). Verify controller
health/revision before restoring any previously authorized entry gate.
Then open the portal, preview the desired settings and explicitly confirm.
An already-enabled controller may place real orders on its next cycle after
confirmation; a saved revision is not evidence of a fill.

The migration seeds revision 0 with **5 / 18% / legacy 200% aggregate guard /
two per group and cluster / zero reserve**, without changing execution gates. Missing migration preserves
worker legacy defaults and makes portal saving unavailable. Invalid stored
configuration blocks entries, not protective management.

See [portfolio settings architecture](docs/architecture.md#versioned-portfolio-settings)
for formulas, fail-closed behavior, concurrency, rollout/rollback and limitations.

Focused checks (no database or exchange required):

```bash
PYTHONPATH=worker:worker/tests python3 -m unittest \
  test_portfolio test_risk test_executor test_live_controller -v
cd web
npm run typecheck
./node_modules/.bin/tsc --module commonjs --moduleResolution node --target es2020 \
  --esModuleInterop --skipLibCheck --outDir .portfolio-test-build tests/portfolio.test.ts
node --test .portfolio-test-build/tests/portfolio.test.js
# Run build after typecheck, never concurrently against .next:
NEXT_TELEMETRY_DISABLED=1 PG_HOST=127.0.0.1 PG_PORT=1 npm run build
```

The Node checks use the built-in test runner and installed TypeScript, with
mocked SQL transactions. Generated `.portfolio-test-build` files are disposable
and must not be committed. They do not constitute a production database
migration or exchange integration test.

For actual migration, transaction and advisory-lock coverage, run the
[isolated PostgreSQL acceptance suite](docs/portfolio-postgres-acceptance.md).
It uses a disposable database and never connects to the production account.
