# Architecture and promotion policy

## Objective

The system measures progress against an aspirational 10% monthly return, but
never treats that number as a required outcome. Capital preservation, bounded
drawdown, and correct operation take priority over trade frequency or return.

## Runtime

1. The worker polls OKX every minute for account state and 5-minute candles.
2. It stores immutable account, position, market, news, and decision records.
3. `us-equity-session-trend-v1` emits a reproducible long/flat baseline for
   selected US equity-linked perpetuals.
4. The risk engine evaluates the signal independently and records every block.
5. The private dashboard displays positions, signals, blocks, and recent news.
6. `/status` checks collector freshness, data accumulation, and the execution
   lock.

The observation universe is SPY, QQQ, AAPL, AMZN, AMD, AVGO, GOOGL, META,
MSFT, NVDA, JNJ, LLY, MRK, and UNH. These are USDT-settled derivatives, not
shares and not claims on the underlying companies or ETFs.

The first version intentionally uses REST polling rather than a complex
WebSocket execution path. A one-minute observation cadence is sufficient for
the current medium-horizon research strategy and is easier to audit. Signals
are session-aware and force a flat target outside the liquid core of the US
regular session; 24/7 availability does not imply 24/7 liquidity.

## Execution boundary

The observer and live controller are separate services. The live controller's
execution adapter includes:

- idempotent client order IDs
- reduce-only support and explicit position-side handling
- maximum order and total exposure checks immediately before submission
- spread, slippage, stale-price, and instrument-state checks
- stop-loss and daily-loss circuit breakers
- reconciliation against exchange order and position streams
- an operator kill switch independent of the strategy process

Live execution may be promoted only after all of the following:

1. Historical backtests include fees, slippage, funding, and delisted periods.
2. Parameters pass walk-forward and untouched out-of-sample tests.
3. Shadow decisions run continuously without data or reconciliation errors.
4. Maximum drawdown and loss limits remain within the configured policy.
5. A tiny live allocation completes order, cancel, fill, and recovery tests.
6. Both the environment acknowledgement and database execution gate are
   explicitly enabled.

## News and model use

Raw news is collected continuously. An LLM is deliberately not called every
minute: with small capital, model cost can exceed expected trading profit.
Future model analysis should summarize deduplicated, relevant events at a
slower cadence and produce structured evidence. It may adjust confidence or
block a trade, but it may not bypass deterministic risk controls.

## Underlying and event data

The research layer stores five years of daily underlying prices, periodic
underlying quotes, OKX-versus-underlying basis, material SEC filings, and
earnings dates. Entry decisions are blocked when the reference quote is more
than 20 minutes old, absolute basis exceeds 100 bps, or a corporate-event
window is active. These entry controls never block a risk-reducing exit.

`yfinance` is an unofficial, best-effort research source without an execution
SLA. It must be replaced or independently confirmed by a licensed real-time
feed before live entry decisions are enabled.

Research runs in a separate container that receives PostgreSQL credentials but
no OKX API key, secret, or passphrase. The smaller exchange worker does not
install `yfinance`; this limits the credential-bearing process's dependency
and network surface.

## Baseline result

The original crypto baseline has been retired at the operator's direction.
The first 30-day equity-perpetual baseline includes a 5 bps fee on each
position transition, but not funding or a full slippage model:

| Instrument | Return | Maximum drawdown | Trades |
| --- | ---: | ---: | ---: |
| SPY | 0.42% | 1.45% | 20 |
| QQQ | -1.11% | 2.69% | 32 |
| AAPL | -1.32% | 3.29% | 46 |
| AMZN | -2.23% | 5.41% | 58 |
| AMD | -1.06% | 6.40% | 82 |
| AVGO | -4.82% | 6.48% | 54 |
| GOOGL | 1.40% | 3.32% | 44 |
| META | -11.00% | 11.00% | 68 |
| MSFT | 0.58% | 2.82% | 82 |
| NVDA | -0.20% | 3.75% | 52 |
| JNJ | -4.98% | 5.46% | 62 |
| LLY | -3.05% | 4.68% | 56 |
| UNH | -5.27% | 7.13% | 56 |

MRK had only 574 candles after its recent listing and produced no trades.
The generally negative results reject this baseline for live use. They are
pipeline evidence, not permission for execution, and future strategy work must
use longer walk-forward samples rather than tune against this one window.

## Five-year daily research

The research job compares three fixed long/flat strategies against buy-and-hold
over three chronological out-of-sample windows after an initial 50% history
window. The first run identified GOOGL daily trend (140.21% return, 8.80%
maximum fold drawdown), MRK daily trend (37.76%, 10.67%), and JNJ daily
breakout (42.65%, 9.84%) as research candidates. These are not annualized
figures and do not include OKX funding or a full execution-slippage model.

Many strategies lost money or underperformed buy-and-hold, while high-return
AMD/NVDA variants had drawdowns above 30%. No candidate is approved for live
execution. The next validation must test stability by regime and compare
risk-adjusted returns after funding and modeled OKX fills.

## Retired shadow portfolio

The paper ledger was used during initial bring-up and remains available for
offline diagnostics. It is no longer scheduled or shown on the primary
dashboard now that bounded live experiments are active.

Historical shadow records are retained rather than deleted.

## Continuous strategy lab

Every weekday research run evaluates 12,300 bounded configurations: 246
parameter specifications from 27 distinct families across 50 instruments.
Parameters are selected using two chronological validation folds, then must
pass a third untouched holdout fold. The simulator shifts close-derived signals
to the next open and applies a conservative 15 bps cost per transition.
Failures and rejection reasons remain in the audit database.

This is continuous evaluation, not unconstrained self-modifying code. The
parameter space is versioned and bounded so results are reproducible and the
search cannot silently weaken risk criteria.

## Locked execution adapter

The execution adapter supports OKX order submission, cancellation, lookup, and
crash recovery by alphanumeric `clOrdId`. It enforces:

- the explicit equity-perpetual allowlist
- entry notional no greater than the current risk decision's authorization
- valid exchange lot sizes
- no short opening
- live environment acknowledgement
- the independent database execution switch
- a matching approved risk decision less than five minutes old

The adapter's transport was verified using real GOOGL minimum-size post-only
orders at roughly half the bid; each was canceled and reconciled without a
fill.

Live activation uses a separate controller service. It defaults to five
holdings and tracks exact filled quantities separately from the aggregate
OKX position. Entries are IOC limit orders capped by their maximum fill price
and include an attached 5% mark-price stop in the same exchange request.
Strategy exits retain that stop until the reduce-only exit is confirmed.

Manual trading in the same instrument while it is system-managed is prohibited.
If aggregate quantity exceeds the system-owned quantity, the controller
automatically disables new entries and does not submit a strategy exit. Manual
positions in other instruments are never selected or modified.

The bounded controller is active. The database gate blocks new entries
immediately when disabled, while risk-reducing exits and stop reconciliation
continue. The controller polls once per minute and may enter only when the
underlying reference, basis, corporate-event, account-exposure, daily-loss,
and drawdown checks all pass. A 7x24 exchange venue does not override stale
underlying-market checks.

When portfolio capacity is available, the controller scans the best eligible
candidate per symbol every minute in descending risk-adjusted score order. It
recalculates each candidate's current long/flat target, skips flat candidates,
and continues past candidate-specific risk blocks until it finds the first
approved long targets until the configured slots (default five) are filled. Asset
group and strategy cluster caps default to two positions and are configurable.

The default experimental account sizing policy authorizes up to 18% of current equity
per 1x isolated position; confirmed portfolio budgets can override this entry
size. It caps total account nominal exposure at 200% of
equity, including manual positions. New entries stop after a 10% daily equity
loss or 20% peak-to-current drawdown. A full, within-budget portfolio replaces
at most one incumbent per cycle: the challenger must exceed the weakest entry
score by 10 points, the incumbent must be at least one day old, and the exact
challenger is reserved and revalidated before entry.

Every filled entry creates a durable live experiment with its hypothesis,
strategy version and parameters, reference price, basis, event context, fees,
and attached stop. While open, the controller records mark-to-market
observations and maximum favorable/adverse excursion. Every closed experiment
gets a deterministic postmortem with net PnL, costs, exit reason, and lesson
codes. After at least five closed experiments in the same symbol/strategy
family, their average return and loss rate receive a bounded weight in future
candidate scoring; smaller samples are recorded but cannot change rankings.

## Versioned portfolio settings

`db/portfolio-settings.sql` is an explicitly operator-applied, transactional,
idempotent migration. No application startup runs migrations. It adds:

- `portfolio_settings`: singleton `id=1`, typed/validated JSON and integer revision;
- `portfolio_settings_history`: one immutable application-written history row
  per revision, actor, previous/new configuration and confirmed preview;
- `portfolio_settings_preview`: hashed, random single-use tokens, actor, expected
  revision, proposed configuration, account snapshot, expiry and consumption.

The application never updates/deletes history. A database administrator can
still modify these tables; this is an application audit trail, not a
cryptographically tamper-proof ledger. Preview records persist for audit/debug
purposes; no new scheduled retention job is installed.

### Budget semantics

All money inputs are finite numeric **USDT notional**, from zero to 1 billion;
position amounts must be positive, percentages `(0,100]`, and maximum holdings,
`maxPerAssetGroup` and `maxPerStrategyCluster` integers `[1,50]`. Group and
cluster caps default to two. The four asset groups therefore allow at most
eight holdings by default: explicitly choosing nine requires a group cap of at
least three and sufficiently permissive cluster caps. Signals and available
cash may still limit actual holdings. Raising caps increases concentration
risk; lowering caps restricts new/replacement candidates without selling holdings.
Aggregate exposure remains limited to 200% of actual equity. Unknown fields,
modes and instruments are rejected.

Let `E` be actual total equity, `A` actual available USDT, `R` reserve, and `X`
gross absolute notional exposure across all account positions (including
manual/unmanaged instruments). Equity's existing USD valuation is treated as
USDT-equivalent, consistently with the legacy engine; there is no FX conversion.

| Total mode | Percentage base `B` | Aggregate ceiling after reserve `T` |
| --- | --- | --- |
| `legacy_equity` (default) | `E` | `max(0, 2E - R)` |
| `account_equity` | `E` | `max(0, E - R)` |
| `fixed_usdt` | `min(requested USDT, E)` | `max(0, B - R)` |

For confirmed settings (revision > 0), an instrument's ceiling is
`min(B, fixed USDT or B × percentage / 100)`. An instrument override replaces
the default budget for that instrument. Explicit budgets may exceed the default
18%; unsaved revision 0 retains the legacy 18%-of-equity ceiling.
Its actual new-entry authorization is no more than
`max(0, min(instrument ceiling, T-X, A-R))`, and is further bounded by existing
strategy confidence, reference, circuit-breaker, price and lot-size checks.
Ceilings are upper bounds, not allocations or target weights.

Example: equity 100, fixed total 30, reserve 5, per-position 18% yields a
percentage base of 30, position ceiling 5.40 and aggregate deployable ceiling
25 USDT. Total 300 with equity 100 is clamped to 100, not additional capital.
With equity 100 and the account-equity total mode, a confirmed fixed
per-position budget of 30 authorizes up to 30, or 50% authorizes up to 50,
subject to cash, remaining aggregate budget and confidence. Neither borrows
funds nor changes leverage.

Available cash is an additional independent limit even in legacy mode. Entries
remain 1x isolated IOC with bounded limit prices; rounding is downward, and
budgets too small for exchange minimum size produce no order. Replacement
preflight uses the same bounded price and lot-rounded size before authorizing
an incumbent sale; it does not set leverage or submit any exchange mutation.
Market/account changes after a preflight can still prevent the subsequent entry.
Budget sizing
does not model a fixed exchange fee rate; reserve additional USDT for fees and
funding. Market appreciation, funding and fees can move holdings beyond a
ceiling after entry; the system does not force them back to a target weight.

### Runtime and concurrency

The controller loads one immutable settings revision per cycle. A shared
configuration advisory lock `884424` spans the entire cycle, so a confirmation
cannot change budgets between replacement preflight, an ordinary exit, and a
new entry. The existing portfolio-controller lock `884423` remains unchanged.
Settings saves use the exclusive transaction form of `884424`; requests time
out after 15 seconds rather than waiting indefinitely for a long cycle.
On timeout or HTTP uncertainty, reload settings/history before retrying.

Each entry's risk decision records `limits.portfolioRevision`. The executor
requires that same current revision, re-reads account/cash/positions, enforces
the portfolio ceiling again and writes the revision into `execution_audit`.
Recovered experiments copy that revision into `entry_context`. Entry submissions
also serialize on `884425`; this session lock remains held across the durable
`requesting` audit commit and the exchange request. Independent reduce-only
exits do not depend on settings loading or these entry locks.
The executor's additional shared configuration lock is nonblocking: it rejects
an entry rather than queuing behind a writer waiting for the controller's
shared lock on another connection.

Holdings count the union of live account instruments and still-owned managed
instruments. Manual exposure consumes budget and holding slots but is never
automatically sold. An unreconciled managed holding missing from the account
view, unresolved entry audit, or any ordinary exchange pending order blocks
new entries conservatively until reconciliation. Partial fills are not assumed
to free budget. Filled entries refresh account and positions before scanning
the next candidate; the executor independently refreshes again immediately
before each submit.

Lowering below the current count/total ceiling blocks new entries and
replacement attempts, with no liquidation. Once a configuration has explicitly
been confirmed (revision > 0), any existing instrument above its current
per-instrument ceiling also blocks new/increasing exposure and replacement
preflights. This is deliberately a global entry freeze, including natural
mark-price appreciation or an equity decline, even on a first save that merely
raises maximum holdings to six. The preview lists all over-budget instruments
and warns before confirmation. Raise their budgets explicitly or wait for
normal exits/account changes; settings never liquidate them to restore compliance.
Unsaved revision 0 retains legacy appreciation behavior for the
18% single-entry ceiling. Normal signal exits and protective stops continue.
No new strategy add/reduce, rebalance, or portfolio optimization logic is added.

Missing tables are treated as unactivated revision-0 legacy configuration by
the worker, and read-only defaults by the portal. A missing singleton in an
existing table, malformed configuration, invalid account metrics or a settings
read failure cannot become a permissive entry fallback. The controller reports
the settings error in its heartbeat and still runs protective management.

### Portal confirmation and activation

The route `/trading/api/portfolio-settings` rechecks Basic credentials itself,
in addition to middleware. Mutations require JSON plus an exact Origin matching
the request Host and proxy protocol; cross-site Fetch Metadata is rejected.
The existing trusted nginx proxy must preserve Host and set
`X-Forwarded-Proto`. Missing authentication configuration fails closed.
Passwords, Basic headers and database errors are never returned or audited.
Responses are `no-store`.

POST `action=preview` validates server-side and records the proposed settings,
not an activation. Confirmation requires a server-issued, unexpired token bound
to the authenticated actor, matching expected revision and explicit
`CONFIRM_PORTFOLIO_LIMITS` acknowledgement. Proposed settings on a confirmation
payload are ignored; only the persisted validated preview can be saved.
A conditional revision update, history insert and token consumption share one
transaction. Concurrent editors, reused/expired tokens and invalid values
cannot silently overwrite a revision.

The preview shows current/proposed limits, current exposure and holdings,
reserve, effective capital and warnings. Its stored summary includes the original
configuration and the union of old/new instrument overrides, so removal visibly
compares the old override with the newly effective default. Confirmation still
uses only the server-stored preview, never edited client-side values.
Account data must be at most three
minutes old. Confirmation must still see the same snapshot and account state;
the preview expires after ten minutes or sooner when state/revision changes.
Reload/preview again on conflict. The UI explicitly warns about real orders
on a subsequent enabled cycle, over-budget holdings, insufficient funds and
the absence of automatic liquidation.

Development does **not** migrate a live database, deploy code, alter execution
gates, change secrets, or activate a sixth holding. Before operator activation,
validate the migration in an isolated database and deploy both the reviewed
worker and web images under a safe, entry-disabled rollout. Confirm that the
new controller reports revision 0 before allowing portal edits. Old images
ignore this feature; applying a migration alone does not enforce budgets.
To restore settings, preview/confirm the old values as a **new revision**, never
edit history. Do not roll back to an old worker that ignores tighter budgets
while entries are enabled.

Unit tests use in-memory SQL/exchange mocks, not production services. They verify
runtime wiring, limits, revision checks, actor-bound previews, replay/conflict
rejection and transaction rollback on audit failure. The separate
[PostgreSQL acceptance suite](portfolio-postgres-acceptance.md) exercises actual
migrations, store queries, atomic rollback, concurrent confirmations and advisory
locks against a disposable database. Neither suite submits exchange orders.
The portal does not call trading APIs, so externally placed pending
orders may only be discovered by the executor; manual trading outside these
locks and exchange eventual consistency cannot be made atomic by a web preview.
External/manual quantity changes mark an experiment unreconciled and exclude
it from learning rather than fabricating missing fills or fees.

## Profit protection

Every entry starts with an exchange-side stop about 5% below entry. Strategy
invalidation and score-based replacement remain the primary exits. In
addition, protection only ratchets upward:

- below 5% maximum favorable excursion, retain the initial stop;
- after reaching 5%, move the stop to about 0.3% above entry;
- after reaching 8%, trail four percentage points behind the best recorded
  return.

The stop is amended in place at OKX, never moved downward. If price has already
crossed the newly required protection level, the controller closes its exact
owned quantity immediately. This is profit protection rather than a fixed
take-profit ceiling, so strong trends can continue running.
