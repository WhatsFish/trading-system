import { Disclaimer } from "@/components/Disclaimer";
import { dashboardData } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const revalidate = 30;

const money = (value: string | null | undefined) =>
  value == null ? "—" : Number(value).toFixed(4);

export default async function TradingDashboard() {
  const { account, positions, decisions, news, heartbeat } = await dashboardData();
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

