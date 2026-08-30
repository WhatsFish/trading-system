import Link from "next/link";
import { Disclaimer } from "@/components/Disclaimer";
import { dashboardData } from "@/lib/queries";
import { strategyCopy, ui, type Lang } from "@/lib/strategy-copy";

export const dynamic = "force-dynamic";
export const revalidate = 30;

const number = (value: string | null | undefined, digits = 2) =>
  value == null ? "—" : Number(value).toFixed(digits);

export default async function TradingDashboard({
  searchParams,
}: {
  searchParams?: { lang?: string };
}) {
  const lang: Lang = searchParams?.lang === "en" ? "en" : "zh";
  const t = ui[lang];
  const data = await dashboardData();
  const {
    account,
    positions,
    positionTrends,
    heartbeat,
    basis,
    events,
    backtests,
    candidates,
    opportunities,
    executionAudits,
    liveState,
    liveExperiments,
    news,
  } = data;
  const stale =
    !heartbeat ||
    Date.now() - new Date(heartbeat.last_seen_at).getTime() > 180_000;
  const equity = Number(account?.total_equity_usd ?? 0);
  const systemExposure = positions.reduce((sum, position) => {
    if (!position.system_quantity) return sum;
    return sum + Number(position.system_quantity) * Number(position.mark_price ?? 0);
  }, 0);
  const estimatedBudget = equity * 0.18;
  const scanByKey = new Map(
    (liveState?.scan ?? []).map((item) => [
      `${item.symbol}:${item.family}`,
      item,
    ]),
  );
  const heldSymbols = new Set(
    positions.map((position) =>
      position.instrument.replace("-USDT-SWAP", ""),
    ),
  );
  const actionableOpportunities = opportunities.filter((candidate) => {
    const scan = scanByKey.get(`${candidate.symbol}:${candidate.family}`);
    return scan && scan.status !== "flat" && !heldSymbols.has(candidate.symbol);
  });

  return (
    <main className="mx-auto max-w-5xl px-5 py-10">
      <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t.title}</h1>
          <p className="mt-1 text-sm text-neutral-500">{t.subtitle}</p>
        </div>
        <div className="flex items-center gap-3">
          <div
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              stale
                ? "bg-red-100 text-red-700"
                : liveState?.execution_enabled
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-amber-100 text-amber-700"
            }`}
          >
            {stale
              ? "Worker stale"
              : liveState?.execution_enabled
                ? t.live
                : t.locked}
          </div>
          <div className="flex rounded-md border border-neutral-200 p-0.5 text-xs dark:border-neutral-800">
            <Link
              href={{ pathname: "/", query: { lang: "zh" } }}
              className={`rounded px-2 py-1 ${lang === "zh" ? "bg-neutral-900 text-white dark:bg-white dark:text-black" : ""}`}
            >
              中文
            </Link>
            <Link
              href={{ pathname: "/", query: { lang: "en" } }}
              className={`rounded px-2 py-1 ${lang === "en" ? "bg-neutral-900 text-white dark:bg-white dark:text-black" : ""}`}
            >
              English
            </Link>
          </div>
        </div>
      </header>

      <section className="mb-8 grid gap-3 sm:grid-cols-4">
        <Metric label={t.equity} value={`${number(account?.total_equity_usd, 2)} USDT`} />
        <Metric label={t.available} value={number(account?.available_usdt, 2)} />
        <Metric
          label={t.exposure}
          value={`${number(String(systemExposure), 2)} USDT`}
          sub={`${equity > 0 ? ((systemExposure / equity) * 100).toFixed(1) : "0.0"}%`}
        />
        <Metric label={t.slots} value={`${liveState?.managed_count ?? 0} / 5`} />
      </section>

      <Section title={t.positions}>
        {positions.length === 0 ? (
          <Empty text={t.noPositions} />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {positions.map((position) => {
              const managed = Boolean(position.system_strategy);
              const copy =
                managed && position.strategy_parameters
                  ? strategyCopy(
                      position.system_strategy!,
                      position.strategy_parameters,
                      lang,
                    )
                  : null;
              const trend = positionTrends[position.instrument];
              const aggregateSize = Number(position.size);
              const systemSize = Number(position.system_quantity ?? 0);
              const manualSize = Math.max(0, aggregateSize - systemSize);
              const systemPnl =
                managed && position.system_average_price
                  ? systemSize *
                    (Number(position.mark_price ?? 0) -
                      Number(position.system_average_price))
                  : null;
              return (
                <article
                  key={`${position.instrument}-${position.side}`}
                  className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-semibold">
                        {position.instrument.replace("-USDT-SWAP", "")}
                      </h3>
                      <p className="text-xs text-neutral-500">
                        {managed
                          ? manualSize > 0
                            ? lang === "zh"
                              ? "系统 + 手动混合持仓"
                              : "Mixed system + manual position"
                            : t.managed
                          : t.manual}{" "}
                        · {position.side} ·{" "}
                        {position.leverage}× {position.margin_mode}
                      </p>
                    </div>
                    <Trend value={trend} />
                  </div>
                  <div className="mt-4 grid grid-cols-3 gap-3 text-sm">
                    <Small
                      label={lang === "zh" ? "数量" : "Size"}
                      value={
                        managed && manualSize > 0
                          ? `${position.size} (${lang === "zh" ? "系统" : "system"} ${systemSize} / ${lang === "zh" ? "手动" : "manual"} ${manualSize})`
                          : position.size
                      }
                    />
                    <Small label={lang === "zh" ? "均价" : "Average"} value={number(position.average_price)} />
                    <Small label={lang === "zh" ? "标记价" : "Mark"} value={number(position.mark_price)} />
                    <Small
                      label={t.pnl}
                      value={
                        systemPnl == null
                          ? `${number(position.unrealized_pnl, 4)} USDT`
                          : `${number(String(systemPnl), 4)} ${lang === "zh" ? "系统" : "system"}`
                      }
                    />
                    <Small label={lang === "zh" ? "名义价值" : "Notional"} value={`${number(position.notional_usd)} USD`} />
                    <Small label={lang === "zh" ? "强平价" : "Liquidation"} value={number(position.liquidation_price)} />
                  </div>
                  {copy ? (
                    <div className="mt-4 space-y-2 border-t border-neutral-200 pt-3 text-sm dark:border-neutral-800">
                      <p>
                        <span className="text-neutral-500">{t.entryStrategy}：</span>
                        <strong>{copy.name}</strong> — {copy.entry}
                      </p>
                      <p>
                        <span className="text-neutral-500">{t.exitRule}：</span>
                        {copy.exit}
                      </p>
                      <p>
                        <span className="text-neutral-500">{t.stop}：</span>
                        {position.stop_trigger_price
                          ? `${number(position.stop_trigger_price)} (${lang === "zh" ? `覆盖系统数量 ${systemSize}` : `covers system quantity ${systemSize}`})`
                          : lang === "zh"
                            ? "等待系统保护单"
                            : "Awaiting system protection"}
                      </p>
                    </div>
                  ) : (
                    <p className="mt-4 border-t border-neutral-200 pt-3 text-sm text-amber-600 dark:border-neutral-800">
                      {lang === "zh"
                        ? "这是手动持仓，系统不会自动卖出。"
                        : "This is a manual position; the system will not sell it."}
                    </p>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </Section>

      <Section title={t.next} description={t.nextHelp}>
        {actionableOpportunities.length === 0 ? (
          <Empty text={lang === "zh" ? "当前没有通过研究门槛的持有目标。" : "No qualified long targets right now."} />
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {actionableOpportunities.slice(0, 8).map((candidate, index) => {
              const copy = strategyCopy(candidate.family, candidate.parameters, lang);
              const scan = scanByKey.get(`${candidate.symbol}:${candidate.family}`);
              const reasons = scan?.reasons ?? [];
              return (
                <article
                  key={`${candidate.symbol}-${candidate.family}`}
                  className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs text-neutral-500">#{index + 1}</p>
                      <h3 className="text-lg font-semibold">{candidate.symbol}</h3>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold">{t.estimated}</p>
                      <p className="text-emerald-600">≈ {estimatedBudget.toFixed(2)} USDT</p>
                    </div>
                  </div>
                  <p className="mt-3 text-sm">
                    <strong>{copy.name}</strong> — {copy.entry}
                  </p>
                  <p className="mt-1 text-xs text-neutral-500">
                    {lang === "zh" ? "卖出：" : "Exit: "}{copy.exit}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    <Chip text={`Score ${Number(candidate.score).toFixed(2)}`} />
                    <Chip text={`Holdout ${Number(candidate.return_pct).toFixed(1)}%`} />
                    <Chip text={`DD ${Number(candidate.drawdown_pct).toFixed(1)}%`} />
                  </div>
                  <p className={`mt-3 text-xs ${scan?.status === "blocked" || reasons.length ? "text-amber-600" : "text-neutral-500"}`}>
                    {scan
                      ? scanStatusText(scan.status, reasons, lang, t)
                      : t.ready}
                  </p>
                </article>
              );
            })}
          </div>
        )}
      </Section>

      <Section title={t.experience}>
        <div className="space-y-3">
          {liveExperiments.slice(0, 6).map((experiment) => {
            const copy = strategyCopy(
              experiment.strategy,
              experiment.strategy_parameters,
              lang,
            );
            return (
              <article
                key={experiment.id}
                className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800"
              >
                <div className="flex justify-between gap-3">
                  <h3 className="font-medium">
                    {experiment.instrument.replace("-USDT-SWAP", "")} · {copy.name}
                  </h3>
                  <span className="text-xs uppercase text-neutral-500">
                    {experiment.status}
                  </span>
                </div>
                <p className="mt-2 text-sm text-neutral-500">
                  {lang === "zh" ? "买入：" : "Entry: "}
                  {experiment.entry_quantity} @ {number(experiment.entry_price)}
                  {" · "}MFE {number(experiment.max_favorable_pct)}%
                  {" · "}MAE {number(experiment.max_adverse_pct)}%
                </p>
                {experiment.postmortem?.summary ? (
                  <p className="mt-3 text-sm">{experiment.postmortem.summary}</p>
                ) : null}
              </article>
            );
          })}
          {liveExperiments.length === 0 ? <Empty text={t.noExperience} /> : null}
        </div>
      </Section>

      <details className="mb-8 rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <summary className="cursor-pointer px-4 py-3 font-medium">{t.research}</summary>
        <div className="space-y-6 border-t border-neutral-200 p-4 dark:border-neutral-800">
          <Diagnostic title={t.candidates}>
            <SimpleTable
              headers={["Symbol", "Strategy", "Target", "Score", "Holdout", "DD"]}
              rows={candidates.slice(0, 30).map((candidate) => {
                const copy = strategyCopy(candidate.family, candidate.parameters, lang);
                return [
                  candidate.symbol,
                  copy.name,
                  candidate.current_target === 1 ? "HOLD LONG" : "FLAT",
                  Number(candidate.score).toFixed(2),
                  `${Number(candidate.return_pct).toFixed(1)}%`,
                  `${Number(candidate.drawdown_pct).toFixed(1)}%`,
                ];
              })}
            />
          </Diagnostic>
          <Diagnostic title={lang === "zh" ? "OKX 与真实股票基差" : "OKX vs underlying basis"}>
            <SimpleTable
              headers={["Symbol", "OKX", "Underlying", "Basis", "Reference"]}
              rows={basis.slice(0, 50).map((item) => [
                item.instrument.replace("-USDT-SWAP", ""),
                number(item.perpetual_price),
                number(item.underlying_price),
                `${Number(item.basis_bps).toFixed(1)} bps`,
                item.reference_stale ? "stale" : "fresh",
              ])}
            />
          </Diagnostic>
          <Diagnostic title={lang === "zh" ? "基础样本外回测" : "Baseline out-of-sample backtests"}>
            <SimpleTable
              headers={["Symbol", "Strategy", "Return", "Drawdown", "Trades"]}
              rows={backtests.slice(0, 30).map((item) => [
                item.symbol,
                item.strategy,
                `${Number(item.test_return_pct).toFixed(1)}%`,
                `${Number(item.test_drawdown_pct).toFixed(1)}%`,
                String(item.test_trades),
              ])}
            />
          </Diagnostic>
          <Diagnostic title={lang === "zh" ? "事件、执行记录与新闻" : "Events, execution and news"}>
            <div className="grid gap-5 md:grid-cols-3">
              <MiniList
                items={events.slice(0, 8).map((item) => `${item.symbol} · ${item.event_type}`)}
                empty={lang === "zh" ? "暂无近期事件" : "No upcoming events"}
              />
              <MiniList
                items={executionAudits.slice(0, 8).map(
                  (item) => `${item.instrument.replace("-USDT-SWAP", "")} · ${item.action} · ${item.state}`,
                )}
                empty={lang === "zh" ? "暂无执行记录" : "No execution records"}
              />
              <MiniList
                items={news.slice(0, 8).map((item) => `${item.source} · ${item.title}`)}
                empty={lang === "zh" ? "暂无新闻" : "No news"}
              />
            </div>
          </Diagnostic>
        </div>
      </details>

      <Disclaimer lang={lang} />
    </main>
  );
}

function Metric({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
      {sub ? <p className="mt-1 text-xs text-neutral-500">{sub}</p> : null}
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
      <h2 className="mb-1 text-sm font-semibold">{title}</h2>
      {description ? (
        <p className="mb-3 max-w-3xl text-sm leading-relaxed text-neutral-500">
          {description}
        </p>
      ) : null}
      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
        {children}
      </div>
    </section>
  );
}

function Trend({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return <span className="text-xs text-neutral-500">24h —</span>;
  }
  const positive = value >= 0;
  return (
    <span className={`rounded px-2 py-1 text-sm font-medium ${positive ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
      {positive ? "▲" : "▼"} {Math.abs(value).toFixed(2)}%
    </span>
  );
}

function Small({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-neutral-500">{label}</p>
      <p className="mt-0.5 font-medium">{value}</p>
    </div>
  );
}

function Chip({ text }: { text: string }) {
  return <span className="rounded bg-neutral-100 px-2 py-1 dark:bg-neutral-800">{text}</span>;
}

function Diagnostic({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">{title}</summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

function SimpleTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-neutral-500">
          <tr>{headers.map((header) => <th key={header} className="pb-2 pr-4">{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-t border-neutral-200 dark:border-neutral-800">
              {row.map((cell, cellIndex) => <td key={cellIndex} className="py-2 pr-4">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MiniList({ items, empty }: { items: string[]; empty: string }) {
  return items.length ? (
    <ul className="space-y-2 text-xs text-neutral-600 dark:text-neutral-400">
      {items.map((item, index) => <li key={index}>{item}</li>)}
    </ul>
  ) : <Empty text={empty} />;
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-neutral-500">{text}</p>;
}

function reasonText(reason: string, lang: Lang) {
  const reasons: Record<string, { zh: string; en: string }> = {
    underlying_reference_stale: { zh: "真实股票报价陈旧", en: "underlying quote is stale" },
    underlying_basis_too_wide: { zh: "OKX 与真实股票偏价过大", en: "OKX basis is too wide" },
    corporate_event_window: { zh: "临近财报或重大事件", en: "earnings or material event window" },
    total_exposure_limit: { zh: "账户总仓位已达上限", en: "account exposure limit" },
    daily_loss_circuit_breaker: { zh: "触发单日亏损熔断", en: "daily loss circuit breaker" },
    max_drawdown_circuit_breaker: { zh: "触发最大回撤熔断", en: "maximum drawdown circuit breaker" },
  };
  return reasons[reason]?.[lang] ?? reason;
}

function scanStatusText(
  status: string,
  reasons: string[],
  lang: Lang,
  labels: (typeof ui)[Lang],
) {
  if (status === "blocked" || reasons.length > 0) {
    return `${labels.blocked}：${reasons.map((reason) => reasonText(reason, lang)).join("、")}`;
  }
  const statuses: Record<string, { zh: string; en: string }> = {
    entered: { zh: "已由系统买入", en: "Entered by the system" },
    unfilled: { zh: "刚才尝试下单但未成交", en: "Recent order attempt was not filled" },
    below_minimum_size: { zh: "风险预算低于交易所最小下单量", en: "Risk budget is below the exchange minimum size" },
    existing_manual_position: { zh: "同一股票已有手动持仓，系统跳过", en: "Skipped because a manual position already exists" },
    emergency_exit: { zh: "保护单异常，系统已紧急退出", en: "Protection failed and the system exited" },
    approved: { zh: "风控已通过，等待执行", en: "Risk approved; awaiting execution" },
  };
  return statuses[status]?.[lang] ?? labels.ready;
}
