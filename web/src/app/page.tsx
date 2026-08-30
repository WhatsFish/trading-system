import { Disclaimer } from "@/components/Disclaimer";
import { dashboardData } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const revalidate = 30;

const money = (value: string | null | undefined) =>
  value == null ? "—" : Number(value).toFixed(4);

export default async function TradingDashboard() {
  const {
    account,
    positions,
    decisions,
    news,
    heartbeat,
    basis,
    events,
    backtests,
    candidates,
    executionAudits,
    liveState,
    liveExperiments,
  } = await dashboardData();
  const stale = !heartbeat || Date.now() - new Date(heartbeat.last_seen_at).getTime() > 180_000;

  return (
    <main className="mx-auto max-w-5xl px-5 py-10">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Trading System</h1>
          <p className="mt-1 text-sm text-neutral-500">
            24/7 market observation · deterministic risk · execution{" "}
            {liveState?.execution_enabled ? "live" : "locked"}
          </p>
        </div>
        <div className={`rounded-full px-3 py-1 text-xs font-medium ${
          stale ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"
        }`}>
          {stale
            ? "worker stale"
            : liveState?.execution_enabled
              ? `live · dynamic sizing${liveState.managed_instrument ? ` · ${liveState.managed_instrument.replace("-USDT-SWAP", "")}` : ""}`
              : `${heartbeat?.status ?? "unknown"} · observe`}
        </div>
      </header>

      <section className="mb-8 grid gap-4 sm:grid-cols-4">
        <Metric label="Total equity" value={`${money(account?.total_equity_usd)} USD`} />
        <Metric label="Available USDT" value={money(account?.available_usdt)} />
        <Metric label="Open positions" value={String(positions.length)} />
        <Metric label="System portfolio" value={`${liveState?.managed_count ?? 0} / 5`} />
      </section>

      <Section title="Open positions">
        {positions.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-neutral-500">
                <tr><th>Instrument</th><th>Side</th><th>Size</th><th>Mark</th><th>PnL</th><th>Liq.</th></tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={`${p.instrument}-${p.side}`} className="border-t border-neutral-200 dark:border-neutral-800">
                    <td className="py-2 font-medium">{p.instrument}</td>
                    <td>{p.side}</td><td>{p.size}</td><td>{money(p.mark_price)}</td>
                    <td>{money(p.unrealized_pnl)}</td><td>{money(p.liquidation_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty text="No open positions." />}
      </Section>

      <Section
        title="Market-session observations · not live order instructions"
        description="These cards apply one common short-term session rule to all 14 symbols. They help monitor market state, but the live controller trades only the top candidate shown further below."
      >
        <div className="grid gap-3 md:grid-cols-3">
          {decisions.map((d) => (
            <article key={d.instrument} className="rounded-md border border-neutral-200 p-4 dark:border-neutral-800">
              <div className="flex items-center justify-between">
                <h3 className="font-medium">{d.instrument.replace("-USDT-SWAP", "")}</h3>
                <span className="rounded bg-neutral-100 px-2 py-0.5 text-xs uppercase dark:bg-neutral-800">
                  {d.action === "buy" ? "ENTRY SIGNAL" : d.action === "sell" ? "FLAT / EXIT" : "NO CHANGE"}
                </span>
              </div>
              <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">{d.rationale}</p>
              <p className="mt-3 text-xs text-neutral-500">
                confidence {Math.round(Number(d.confidence) * 100)}% · blocked: {d.reasons.join(", ") || "no"}
              </p>
            </article>
          ))}
          {!decisions.length && <Empty text="Waiting for the first collector cycle." />}
        </div>
      </Section>

      <Section title="OKX vs underlying">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-neutral-500">
              <tr><th>Symbol</th><th>OKX</th><th>Underlying</th><th>Basis</th><th>Reference</th></tr>
            </thead>
            <tbody>
              {basis.map((item) => (
                <tr key={item.instrument} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-2 font-medium">{item.instrument.replace("-USDT-SWAP", "")}</td>
                  <td>{money(item.perpetual_price)}</td>
                  <td>{money(item.underlying_price)}</td>
                  <td>{Number(item.basis_bps).toFixed(1)} bps</td>
                  <td className={item.reference_stale ? "text-amber-600" : "text-emerald-600"}>
                    {item.reference_stale ? "stale" : "fresh"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!basis.length && <Empty text="Waiting for underlying reference data." />}
        </div>
      </Section>

      <Section
        title="Baseline out-of-sample backtests"
        description="Same four baseline rules are applied to every stock for an apples-to-apples comparison. Return is compounded test-period performance; max drawdown is the largest peak-to-trough loss; trades counts individual buy or sell transitions, not round trips."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-neutral-500">
              <tr><th>Symbol</th><th>Strategy</th><th>Return</th><th>Max drawdown</th><th>Trades</th></tr>
            </thead>
            <tbody>
              {backtests.map((item) => (
                <tr key={`${item.symbol}-${item.strategy}`} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-2 font-medium">{item.symbol}</td>
                  <td>{item.strategy.replace("daily-", "")}</td>
                  <td>{Number(item.test_return_pct).toFixed(2)}%</td>
                  <td>{Number(item.test_drawdown_pct).toFixed(2)}%</td>
                  <td>{item.test_trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!backtests.length && <Empty text="Waiting for long-history research." />}
        </div>
      </Section>

      <Section
        title="Continuous strategy lab candidates"
        description="The daily lab runs 12,300 configurations across 50 instruments and 27 distinct strategy families. Parameters are selected using the first two validation windows; Return and Drawdown below come from the untouched final holdout window. Score conservatively uses the weaker risk-adjusted result. Folds shows how many of all three windows were profitable. Live is the number of completed real experiments."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-neutral-500">
              <tr><th>Symbol</th><th>Family</th><th>Parameters</th><th>Target</th><th>Score</th><th>Return</th><th>Drawdown</th><th>Folds</th><th>Live</th></tr>
            </thead>
            <tbody>
              {candidates.map((candidate) => (
                <tr key={`${candidate.symbol}-${candidate.family}`} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-2 font-medium">{candidate.symbol}</td>
                  <td>{candidate.family}</td>
                  <td className="font-mono text-xs">{formatParameters(candidate.family, candidate.parameters)}</td>
                  <td className={candidate.current_target === 1 ? "font-medium text-emerald-600" : "text-neutral-500"}>
                    {candidate.current_target === 1 ? "HOLD LONG" : "FLAT"}
                  </td>
                  <td>{Number(candidate.score).toFixed(2)}</td>
                  <td>{Number(candidate.return_pct).toFixed(2)}%</td>
                  <td>{Number(candidate.drawdown_pct).toFixed(2)}%</td>
                  <td>{candidate.positive_folds}/3</td>
                  <td>{candidate.live_experience_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!candidates.length && <Empty text="Waiting for the first strategy-lab run." />}
        </div>
      </Section>

      <Section title="Execution audit">
        <div className="divide-y divide-neutral-200 dark:divide-neutral-800">
          {executionAudits.map((audit, index) => (
            <div key={`${audit.ts}-${index}`} className="flex flex-wrap justify-between gap-2 py-2 text-sm">
              <span><strong>{audit.instrument.replace("-USDT-SWAP", "")}</strong> · {audit.action} {audit.requested_size}</span>
              <span className="text-neutral-500">{audit.state}</span>
            </div>
          ))}
          {!executionAudits.length && <Empty text="No real transport test has been recorded." />}
        </div>
      </Section>

      <Section title="Live trading experiments and lessons">
        <div className="space-y-3">
          {liveExperiments.map((experiment) => (
            <article key={experiment.id} className="rounded-md border border-neutral-200 p-4 dark:border-neutral-800">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-medium">
                  {experiment.instrument.replace("-USDT-SWAP", "")} · {experiment.strategy}
                </h3>
                <span className="rounded bg-neutral-100 px-2 py-0.5 text-xs uppercase dark:bg-neutral-800">
                  {experiment.status}
                </span>
              </div>
              <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
                {experiment.hypothesis}
              </p>
              <p className="mt-2 text-xs text-neutral-500">
                entry {experiment.entry_quantity} @ {money(experiment.entry_price)}
                {" · "}MFE {Number(experiment.max_favorable_pct).toFixed(2)}%
                {" · "}MAE {Number(experiment.max_adverse_pct).toFixed(2)}%
              </p>
              {experiment.postmortem?.summary && (
                <p className="mt-3 border-t border-neutral-200 pt-3 text-sm dark:border-neutral-800">
                  {experiment.postmortem.summary}
                </p>
              )}
              {experiment.postmortem?.lessonCodes?.length ? (
                <p className="mt-1 text-xs text-neutral-500">
                  lessons: {experiment.postmortem.lessonCodes.join(", ")}
                </p>
              ) : null}
            </article>
          ))}
          {!liveExperiments.length && (
            <Empty text="No live strategy experiment has entered yet. Future trades will be recorded with context and postmortems." />
          )}
        </div>
      </Section>

      <Section title="Upcoming event risk">
        <div className="divide-y divide-neutral-200 dark:divide-neutral-800">
          {events.map((event) => (
            <div key={`${event.symbol}-${event.event_type}-${event.starts_at}`} className="flex justify-between py-2 text-sm">
              <span><strong>{event.symbol}</strong> · {event.event_type}</span>
              <span className="text-neutral-500">{new Date(event.starts_at).toLocaleDateString()}</span>
            </div>
          ))}
          {!events.length && <Empty text="No scheduled events in the next 30 days." />}
        </div>
      </Section>

      <Section title="Market news">
        <div className="divide-y divide-neutral-200 dark:divide-neutral-800">
          {news.map((item) => (
            <a key={item.url} href={item.url} target="_blank" rel="noreferrer" className="block py-3 hover:underline">
              <p className="text-sm font-medium">{item.title}</p>
              <p className="mt-1 text-xs text-neutral-500">{item.source}</p>
            </a>
          ))}
          {!news.length && <Empty text="Waiting for news ingestion." />}
        </div>
      </Section>
      <Disclaimer />
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-8">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">{title}</h2>
      {description ? (
        <p className="mb-3 max-w-4xl text-sm leading-relaxed text-neutral-500">{description}</p>
      ) : null}
      <div className="rounded-md border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">{children}</div>
    </section>
  );
}

function formatParameters(family: string, parameters: Record<string, number>) {
  const labels: Record<string, string> = {
    fast: "fast",
    slow: "slow",
    period: "period",
    lookback: "lookback",
    entryDays: "entry",
    exitDays: "exit",
    holdDays: "hold",
    gapPct: "gap%",
    entryRsi: "entry RSI",
    exitRsi: "exit RSI",
    stdDev: "std",
    dipPct: "dip%",
  };
  return Object.entries(parameters)
    .map(([key, value]) => `${labels[key] ?? key}=${value}`)
    .join(" · ");
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-neutral-500">{text}</p>;
}
