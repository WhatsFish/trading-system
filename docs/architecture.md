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

There is no order placement, transfer, borrowing, earning, or withdrawal code
in the deployed worker. Future order execution must be a separate adapter with:

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

## Shadow portfolio

The paper ledger starts with 30 USDT and currently evaluates three deliberately
small candidates: GOOGL daily trend, JNJ daily breakout, and MRK daily trend.
It uses the latest OKX perpetual quote but never calls an order endpoint.

Entries are evaluated once near the US market close. Each position is capped
at 16% of initial virtual capital, with three candidates limiting aggregate
target exposure below 50%. Simulated fills pay 5 bps fees and 10 bps adverse
slippage on each side. A 5% shadow-account drawdown blocks new entries while
exits remain available. Stale references, basis above 100 bps, SEC filings, and
earnings windows also block entries.

## Continuous strategy lab

Every weekday research run evaluates 420 bounded parameter combinations across
trend, breakout, and mean-reversion families. Each experiment is evaluated on
three chronological out-of-sample folds with a conservative 15 bps transition
cost. Candidates require at least two positive folds, six transitions,
drawdown no greater than 15%, and a positive `return - 2 * drawdown` score.
Failures and rejection reasons remain in the audit database.

This is continuous evaluation, not unconstrained self-modifying code. The
parameter space is versioned and bounded so results are reproducible and the
search cannot silently weaken risk criteria.

## Locked execution adapter

The execution adapter supports OKX order submission, cancellation, lookup, and
crash recovery by alphanumeric `clOrdId`. It enforces:

- the explicit equity-perpetual allowlist
- a hard 5 USDT order-notional ceiling
- valid exchange lot sizes
- no short opening
- live environment acknowledgement
- the independent database execution switch
- a matching approved risk decision less than five minutes old

The adapter's transport was verified using real GOOGL minimum-size post-only
orders at roughly half the bid; each was canceled and reconciled without a
fill.

Live activation uses a separate controller service. It may manage at most one
position and tracks its exact filled quantity separately from the aggregate
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
