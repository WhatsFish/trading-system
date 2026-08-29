# Architecture and promotion policy

## Objective

The system measures progress against an aspirational 10% monthly return, but
never treats that number as a required outcome. Capital preservation, bounded
drawdown, and correct operation take priority over trade frequency or return.

## Runtime

1. The worker polls OKX every minute for account state and 5-minute candles.
2. It stores immutable account, position, market, news, and decision records.
3. `ema-trend-v1` emits a reproducible baseline signal for BTC, ETH, and SOL.
4. The risk engine evaluates the signal independently and records every block.
5. The private dashboard displays positions, signals, blocks, and recent news.
6. `/status` checks collector freshness, data accumulation, and the execution
   lock.

The first version intentionally uses REST polling rather than a complex
WebSocket execution path. A one-minute observation cadence is sufficient for
the current medium-horizon research strategy and is easier to audit.

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

## Baseline result

The first 30-day, 5-minute long/flat baseline run (including a 5 bps fee per
position transition, before funding and modeled slippage) produced:

| Instrument | Return | Maximum drawdown | Trades |
| --- | ---: | ---: | ---: |
| BTC-USDT-SWAP | 3.01% | 5.70% | 132 |
| ETH-USDT-SWAP | 2.86% | 8.78% | 198 |
| SOL-USDT-SWAP | -0.70% | 11.67% | 242 |

This is pipeline validation, not strategy validation. The sample is short,
the drawdowns are too large for the account, and the results do not justify
live execution.
