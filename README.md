# Trading System

A 24/7, audit-first OKX US-equity-perpetual research system. It focuses on
technology and healthcare leaders plus S&P 500/Nasdaq-100 ETFs, collects
market and account data, evaluates session-aware deterministic strategies,
enforces hard risk limits, and exposes a private dashboard.

The default and deployed mode is `observe`: decisions are recorded, but no
orders are sent. Live execution requires explicit code review, successful
backtests, shadow operation, and two independent configuration gates.

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

The weekday research job also evaluates a bounded 420-combination strategy
grid and updates the candidate leaderboard. Every rejected experiment remains
auditable.

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

The active policy allows at most one system-managed long, sized up to 35% of
current equity, with 1x isolated leverage, an atomic attached 5% stop, and no
short opening. The executor enforces the exact notional authorized by the
corresponding risk decision rather than a fixed dollar cap.

Live experiments retain their hypothesis, entry context, fees, mark-to-market
path, MFE/MAE, outcome, and deterministic postmortem. After five closed samples
in a symbol/strategy family, live outcomes receive a bounded weight in the
next strategy-lab ranking.
