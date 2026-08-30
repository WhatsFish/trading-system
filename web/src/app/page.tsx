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
    shadowAccount,
    shadowPositions,
    shadowTrades,
    candidates,
    executionAudits,
  } = await dashboardData();
  const stale = !heartbeat || Date.now() - new Date(heartbeat.last_seen_at).getTime() > 180_000;

  return (
    <main className="mx-auto max-w-5xl px-5 py-10">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Trading System</h1>
          <p className="mt-1 text-sm text-neutral-500">
            24/7 market observation · deterministic risk · execution locked
          </p>
        </div>
        <div className={`rounded-full px-3 py-1 text-xs font-medium ${
          stale ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"
        }`}>
          {stale ? "worker stale" : `${heartbeat?.status ?? "unknown"} · observe`}
        </div>
      </header>

      <section className="mb-8 grid gap-4 sm:grid-cols-3">
        <Metric label="Total equity" value={`${money(account?.total_equity_usd)} USD`} />
        <Metric label="Available USDT" value={money(account?.available_usdt)} />
        <Metric label="Open positions" value={String(positions.length)} />
      </section>

      <Section title="Shadow portfolio · no real orders">
        <div className="mb-4 grid gap-3 sm:grid-cols-4">
          <Metric label="Virtual equity" value={`${money(shadowAccount?.equity)} USDT`} />
          <Metric label="Virtual cash" value={money(shadowAccount?.cash)} />
          <Metric label="Realized PnL" value={money(shadowAccount?.realized_pnl)} />
          <Metric label="Drawdown" value={`${money(shadowAccount?.drawdown_pct)}%`} />
        </div>
        {shadowPositions.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-neutral-500">
                <tr><th>Instrument</th><th>Strategy</th><th>Quantity</th><th>Entry</th><th>Mark</th><th>PnL</th></tr>
              </thead>
              <tbody>
                {shadowPositions.map((position) => (
                  <tr key={position.instrument} className="border-t border-neutral-200 dark:border-neutral-800">
                    <td className="py-2 font-medium">{position.instrument.replace("-USDT-SWAP", "")}</td>
                    <td>{position.strategy.replace("daily-", "")}</td>
                    <td>{position.quantity}</td>
                    <td>{money(position.average_price)}</td>
                    <td>{money(position.mark_price)}</td>
                    <td>{money(position.unrealized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty text="No virtual position yet; entries are evaluated near each US market close." />}
        {shadowTrades.length > 0 && (
          <p className="mt-3 text-xs text-neutral-500">
            {shadowTrades.length} recent simulated fills · 5 bps fee + 10 bps adverse slippage per side
          </p>
        )}
      </Section>

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

      <Section title="Latest strategy decisions">
        <div className="grid gap-3 md:grid-cols-3">
          {decisions.map((d) => (
            <article key={d.instrument} className="rounded-md border border-neutral-200 p-4 dark:border-neutral-800">
              <div className="flex items-center justify-between">
                <h3 className="font-medium">{d.instrument.replace("-USDT-SWAP", "")}</h3>
                <span className="rounded bg-neutral-100 px-2 py-0.5 text-xs uppercase dark:bg-neutral-800">{d.action}</span>
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

      <Section title="Out-of-sample daily backtests">
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

      <Section title="Continuous strategy lab candidates">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-neutral-500">
              <tr><th>Symbol</th><th>Family</th><th>Score</th><th>Return</th><th>Drawdown</th><th>Folds</th></tr>
            </thead>
            <tbody>
              {candidates.map((candidate) => (
                <tr key={`${candidate.symbol}-${candidate.family}`} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-2 font-medium">{candidate.symbol}</td>
                  <td>{candidate.family}</td>
                  <td>{Number(candidate.score).toFixed(2)}</td>
                  <td>{Number(candidate.return_pct).toFixed(2)}%</td>
                  <td>{Number(candidate.drawdown_pct).toFixed(2)}%</td>
                  <td>{candidate.positive_folds}/3</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!candidates.length && <Empty text="Waiting for the first strategy-lab run." />}
        </div>
      </Section>

      <Section title="Execution transport audit · automation locked">
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">{title}</h2>
      <div className="rounded-md border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">{children}</div>
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-neutral-500">{text}</p>;
}
