"use client";

import { useEffect, useState } from "react";
import { CONFIRMATION, DEFAULT_CONFIG, INSTRUMENTS, type Budget, type PortfolioConfig } from "@/lib/portfolio";
import type { createPreview, overview } from "@/lib/portfolio-store";

type Overview = Awaited<ReturnType<typeof overview>>;
type Preview = Awaited<ReturnType<typeof createPreview>>;
const endpoint = "/trading/api/portfolio-settings";
const inputClass = "rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700";
const warningCopy: Record<string, [string, string]> = {
  insufficient_equity: ["预算超过实际权益，仅按实际权益计算。", "Budget exceeds actual equity; effective budget is clamped to equity."],
  reserve_exceeds_available: ["可用 USDT 不足以满足现金储备，禁止新开仓。", "Available USDT cannot cover the reserve; new entries are blocked."],
  holdings_over_cap: ["已有持仓超过上限，禁止新开仓和策略换仓。", "Existing holdings exceed the cap; new entries and replacements are blocked."],
  total_over_budget: ["当前敞口超过总预算，禁止新增敞口。", "Current exposure exceeds the total budget; increasing exposure is blocked."],
  positions_over_budget: ["已有标的市值超过单仓预算，全部新开仓和策略换仓暂停（价格上涨或权益下降也会触发）；不会自动减仓。", "An existing mark-value exposure exceeds its budget: all entries and replacements pause, including after appreciation or an equity decline. No automatic reductions."],
  pending_entries: ["存在未完成订单，先等待对账。", "Pending entries must reconcile before new entries."],
  group_cluster_caps: ["最大持仓数超过当前 4 个资产组的合计上限；如需更多持仓，请明确提高高级分散限制。", "Maximum holdings exceeds the combined cap of the four current asset groups; explicitly raise the advanced diversification caps to permit more holdings."],
  concentration_caps_raised: ["分散限制已高于默认 2 仓，同组或同策略簇集中风险增加；持仓数仍受候选信号及现金约束。", "Diversification caps exceed the default of two: group or strategy concentration risk increases. Candidate signals and cash still constrain actual holdings."],
};

export function PortfolioSettings({ lang }: { lang: "zh" | "en" }) {
  const en = lang === "en";
  const t = (zh: string, english: string) => en ? english : zh;
  const [data, setData] = useState<Overview | null>(null);
  const [config, setConfig] = useState<PortfolioConfig>(DEFAULT_CONFIG);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<number | null>(null);
  const [instrument, setInstrument] = useState(INSTRUMENTS[0]);
  async function request(body?: unknown) {
    const response = await fetch(endpoint, {
      method: body ? "POST" : "GET", cache: "no-store", credentials: "same-origin",
      ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error ?? "settings_unavailable");
    return result;
  }
  async function load() {
    setBusy(true); setError(""); setPreview(null); setConfirmed(false);
    try {
      const result: Overview = await request();
      setData(result); setConfig(result.config);
    } catch (error) {
      setData(null);
      setError(error instanceof Error ? error.message : "settings_unavailable");
    } finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  function change(next: PortfolioConfig) {
    setConfig(next); setPreview(null); setConfirmed(false); setSaved(null);
  }
  async function makePreview() {
    setBusy(true); setError(""); setSaved(null); setConfirmed(false); setPreview(null);
    try { setPreview(await request({ action: "preview", expectedRevision: data?.revision, config })); }
    catch (error) { setError(error instanceof Error ? error.message : "settings_unavailable"); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!preview || !confirmed) return;
    setBusy(true); setError("");
    try {
      const result = await request({ action: "confirm", expectedRevision: preview.expectedRevision,
        token: preview.token, acknowledgement: CONFIRMATION });
      setPreview(null); setConfirmed(false); setSaved(result.revision);
      await load();
    } catch (error) {
      setError(error instanceof Error ? error.message : "settings_unavailable");
      setPreview(null); setConfirmed(false);
    } finally { setBusy(false); }
  }
  function budgetEditor(value: Budget, update: (next: Budget) => void) {
    return <span className="flex flex-wrap gap-2">
      <select aria-label={t("单仓预算单位", "Position budget unit")} className={inputClass} value={value.mode} onChange={(e) => update({ ...value, mode: e.target.value as Budget["mode"] })}>
        <option value="percent">{t("预算基数百分比 (%)", "Percent of budget base (%)")}</option>
        <option value="fixed_usdt">{t("固定名义金额 (USDT)", "Fixed notional (USDT)")}</option>
      </select>
      <input aria-label={t("单仓预算数值", "Position budget value")} className={`${inputClass} w-32`} type="number" min="0.01" max={value.mode === "percent" ? 100 : 1e9} step="any" value={value.value} onChange={(e) => update({ ...value, value: Number(e.target.value) })} />
    </span>;
  }
  return <section className="space-y-5">
    <p className="rounded border border-amber-400 p-4 text-sm">
      {t("所有金额为名义敞口 USDT（不是保证金）；杠杆固定 1 倍。此处不改变交易开关。确认后，已启用的实盘控制器可能在下一周期下真实订单。不会自动调仓或清算现有持仓；止损及正常策略退出继续运行。", "All amounts are notional USDT, not margin; leverage stays 1x. This does not change execution gates. After confirmation, an already-enabled live controller may place real orders on its next cycle. No automatic rebalancing or liquidation; protective stops and normal strategy exits continue.")}
    </p>
    <p className="text-sm text-neutral-500">{t("默认：最多 5 仓，单仓权益 18%，原总敞口上限 200%，每资产组/策略簇 2 仓。可明确提高单仓预算与分散上限；仍受权益、现金、总预算、费用及最小下单量约束，不借款。", "Defaults: five holdings, 18% equity per position, legacy 200% aggregate ceiling, two per group/cluster. Explicit settings can increase position budgets and diversification caps; equity, cash, total budget, fees and minimum order sizes still apply. No borrowing.")}</p>
    <p className="text-sm text-amber-700 dark:text-amber-300">{t("首次保存后，任一现有持仓市值超过当前单仓预算会暂停全部新开仓和换仓，即使仅提高最大持仓数；价格上涨或权益下降也会触发。请核对预览。不会自动再平衡或清算。", "After the first save, any holding above its current per-instrument budget pauses all entries and replacements—even if only maximum holdings was raised. Appreciation or an equity decline also triggers this rule. Review the preview; there is no automatic rebalancing or liquidation.")}</p>
    <button className={inputClass} disabled={busy} onClick={() => void load()}>{t("重新加载当前设置", "Reload current settings")}</button>
    {error && <p role="alert" className="text-red-600">{t("操作失败，未确认的设置不会生效。版本/快照冲突请重新加载和预览。错误：", "Request failed; unconfirmed settings do not take effect. For revision/snapshot conflicts, reload and preview again. Error: ")}{error}</p>}
    {saved !== null && <p role="status" className="text-emerald-600">{t("已保存版本 ", "Saved revision ")}{saved}{t("，等待控制器读取；不代表已开新仓。", "; awaiting controller consumption, not proof of a new holding.")}</p>}
    {data && <>
      <p>{t("当前版本", "Current revision")} {data.revision} · {t("账户快照", "Account snapshot")} {data.snapshot.ts}</p>
      <p className="text-sm">{t("控制器最近报告版本", "Controller last reported revision")}: {data.controller?.revision ?? "—"} · {data.controller?.lastSeenAt ?? t("尚无记录", "No heartbeat")}
        {(!data.controller || data.controller.settingsError || data.controller.revision !== data.revision || Date.now() - new Date(data.controller.lastSeenAt).getTime() > 180_000) &&
          <strong className="ml-2 text-amber-700 dark:text-amber-300">{t("未验证控制器已读取当前设置；保存不代表生效或成交。", "Controller consumption is not verified; saving is not proof of activation or a fill.")}</strong>}
      </p>
      {data.migrationRequired && <p role="alert">{t("尚未由操作员应用数据库迁移；不可保存。", "Operator migration has not been applied; saving is unavailable.")}</p>}
      <fieldset disabled={busy || data.migrationRequired} className="space-y-4">
        <label className="flex flex-wrap items-center gap-3">{t("最大持仓数 (1–50)", "Maximum holdings (1–50)")}
          <input className={`${inputClass} w-24`} type="number" min="1" max="50" step="1" value={config.maxHoldings} onChange={(e) => change({ ...config, maxHoldings: Number(e.target.value) })} />
        </label>
        <details className="space-y-3 rounded border p-3">
          <summary>{t("高级分散限制（默认各 2 仓）", "Advanced diversification caps (default: two each)")}</summary>
          <label className="flex items-center gap-3">{t("每资产组最大仓数 (1–50)", "Maximum per asset group (1–50)")}
            <input className={`${inputClass} w-24`} type="number" min="1" max="50" step="1" value={config.maxPerAssetGroup} onChange={(e) => change({ ...config, maxPerAssetGroup: Number(e.target.value) })} />
          </label>
          <label className="flex items-center gap-3">{t("每策略簇最大仓数 (1–50)", "Maximum per strategy cluster (1–50)")}
            <input className={`${inputClass} w-24`} type="number" min="1" max="50" step="1" value={config.maxPerStrategyCluster} onChange={(e) => change({ ...config, maxPerStrategyCluster: Number(e.target.value) })} />
          </label>
          <p className="text-sm text-neutral-500">{t("当前 4 个资产组的理论最多仓数为 4 × 组上限；默认最多 8 仓。9 仓需组上限至少 3，策略簇限制也可能减少可用候选。提高上限增加集中风险；降低不自动卖出，只限制新增和换仓候选。", "Four asset groups permit at most 4 × group cap holdings (eight by default). Nine requires a group cap of at least three; cluster caps may further restrict candidates. Raising caps increases concentration risk; lowering caps does not sell holdings, only restricts entry and replacement candidates.")}</p>
        </details>
        <label className="flex flex-wrap items-center gap-3">{t("总交易预算模式", "Total trading budget mode")}
          <select className={inputClass} value={config.totalBudgetMode} onChange={(e) => change({ ...config,
            totalBudgetMode: e.target.value as PortfolioConfig["totalBudgetMode"],
            totalBudgetUsdt: e.target.value === "fixed_usdt" ? 30 : 0 })}>
            <option value="legacy_equity">{t("兼容旧规则：总敞口上限为权益 200%", "Legacy: 200% equity aggregate guard")}</option>
            <option value="account_equity">{t("账户权益：总预算为权益 100%", "Account equity: 100% equity budget")}</option>
            <option value="fixed_usdt">{t("固定 USDT 总预算", "Fixed USDT total budget")}</option>
          </select>
        </label>
        {config.totalBudgetMode === "fixed_usdt" && <label className="flex items-center gap-3">{t("总预算 USDT（不超过实际权益）", "Total USDT (clamped to actual equity)")}
          <input className={`${inputClass} w-32`} type="number" min="0.01" max="1000000000" step="any" value={config.totalBudgetUsdt} onChange={(e) => change({ ...config, totalBudgetUsdt: Number(e.target.value) })} />
        </label>}
        <div><p className="mb-2">{t("默认单标的预算", "Default per-instrument budget")}</p>
          {budgetEditor({ mode: config.positionBudgetMode, value: config.positionBudgetValue }, (b) => change({ ...config, positionBudgetMode: b.mode, positionBudgetValue: b.value }))}
        </div>
        <p className="text-sm text-neutral-500">{t("百分比基数：固定总预算模式取 min(预算, 实际权益)，其他模式取实际权益。储备从总预算与可用现金中扣除；已确认单仓预算可超过默认 18%，但不超过预算基数、剩余总预算及可用现金。", "Percentage base: min(fixed budget, actual equity) in fixed mode; actual equity otherwise. Reserve is excluded from aggregate budget and available cash. Confirmed position budgets can exceed the default 18%, but not the budget base, remaining total budget or available cash.")}</p>
        <label className="flex items-center gap-3">{t("现金储备 USDT", "Cash reserve USDT")}
          <input className={`${inputClass} w-32`} type="number" min="0" max="1000000000" step="any" value={config.cashReserveUsdt} onChange={(e) => change({ ...config, cashReserveUsdt: Number(e.target.value) })} />
        </label>
        <div className="space-y-3">
          <p>{t("个别标的覆盖预算（可选）", "Per-instrument overrides (optional)")}</p>
          <div className="flex flex-wrap gap-2"><select aria-label={t("标的", "Instrument")} className={inputClass} value={instrument} onChange={(e) => setInstrument(e.target.value)}>{INSTRUMENTS.map((i) => <option key={i}>{i}</option>)}</select>
            <button className={inputClass} onClick={() => change({ ...config, instrumentBudgets: { ...config.instrumentBudgets, [instrument]: { mode: config.positionBudgetMode, value: config.positionBudgetValue } } })}>{t("添加覆盖", "Add override")}</button>
          </div>
          {Object.entries(config.instrumentBudgets).map(([i, b]) => <div className="flex flex-wrap items-center gap-2" key={i}>
            <span>{i}</span>{budgetEditor(b, (next) => change({ ...config, instrumentBudgets: { ...config.instrumentBudgets, [i]: next } }))}
            <button className={inputClass} onClick={() => { const next = { ...config.instrumentBudgets }; delete next[i]; change({ ...config, instrumentBudgets: next }); }}>{t("移除", "Remove")}</button>
          </div>)}
        </div>
        <button className="rounded bg-neutral-900 px-4 py-2 text-white dark:bg-white dark:text-black" onClick={() => void makePreview()}>{t("预览更改（不生效）", "Preview changes (not applied)")}</button>
      </fieldset>
      {preview && <div className="space-y-4 rounded border border-amber-400 p-4">
        <h2 className="font-semibold">{t("确认前比较：当前 → 拟议", "Before confirmation: current → proposed")}</h2>
        <table className="w-full text-left text-sm"><tbody>
          {([
            ["maxHoldings", t("最大持仓数", "Maximum holdings")],
            ["maxPerAssetGroup", t("每资产组上限", "Per asset group cap")],
            ["maxPerStrategyCluster", t("每策略簇上限", "Per strategy cluster cap")],
            ["percentageBaseUsdt", t("百分比基数 USDT", "Percentage base USDT")],
            ["totalNotionalUsdt", t("扣除储备后总敞口 USDT", "Total notional after reserve USDT")],
            ["defaultPositionUsdt", t("默认单仓上限 USDT", "Default position ceiling USDT")],
            ["reserveUsdt", t("现金储备 USDT", "Cash reserve USDT")],
            ["remainingUsdt", t("剩余可部署 USDT", "Remaining deployable USDT")],
            ["openSlots", t("剩余仓位", "Open slots")],
          ] as const).map(([key, label]) => <tr key={key}><th className="py-1 font-normal">{label}</th><td>{preview.summary.current[key].toFixed(2)} → {preview.summary.proposed[key].toFixed(2)}</td></tr>)}
        </tbody></table>
        <p className="text-sm">{t("已有持仓 / 总敞口 / 可用 USDT：", "Existing holdings / exposure / available USDT: ")}{preview.summary.proposed.heldCount} / {preview.summary.proposed.exposureUsdt.toFixed(2)} / {preview.summary.proposed.availableUsdt.toFixed(2)}</p>
        {preview.summary.affectedInstruments.map((i) => <p className="text-sm" key={i}>{i}: {preview.summary.current.instrumentLimits[i].toFixed(2)} → {preview.summary.proposed.instrumentLimits[i].toFixed(2)} USDT
          {!preview.config.instrumentBudgets[i] && <span> · {t("移除覆盖，恢复默认预算", "Override removed; default budget applies")}</span>}
        </p>)}
        <p>{preview.summary.proposed.entryBlocked ? t("当前账户状态下新开仓受阻。", "New entries are blocked under the current account state.") : t("预算允许不代表策略一定下单。", "Budget availability does not guarantee a strategy order.")}</p>
        {preview.summary.proposed.warnings.map((w) => <p className="text-amber-700 dark:text-amber-300" key={w}>{warningCopy[w]?.[en ? 1 : 0] ?? w}</p>)}
        {preview.summary.proposed.overPositions.length > 0 && <p>{preview.summary.proposed.overPositions.join(", ")}</p>}
        <p className="text-sm">{t("预览最多有效 10 分钟；账户快照或设置变化后必须重新预览。不会自动卖出旧仓。", "Preview expires after 10 minutes, or when account snapshot/settings change. Existing positions are not automatically sold.")}</p>
        <label className="flex items-start gap-2"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(e) => setConfirmed(e.target.checked)} />
          {t("我已核对预算、警告及真实交易风险，明确确认保存上述设置。", "I reviewed the limits, warnings and real-trading risk, and explicitly confirm saving these settings.")}</label>
        <button className="rounded bg-red-700 px-4 py-2 text-white disabled:opacity-40" disabled={!confirmed || busy} onClick={() => void save()}>{t("确认保存（可能影响下一周期真实订单）", "Confirm save (may affect real orders next cycle)")}</button>
      </div>}
      <h2 className="text-lg font-semibold">{t("配置审计历史（最近 50 条）", "Settings audit history (latest 50)")}</h2>
      {data.history.map((row) => <details className="rounded border p-3 text-sm" key={row.revision}>
        <summary>v{row.revision} · {new Date(row.confirmed_at).toLocaleString(en ? "en-US" : "zh-CN")} · {row.actor}</summary>
        <p className="mt-2">{t("前一设置 / 已保存设置 / 确认预览", "Previous / saved settings / confirmed preview")}</p>
        <pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify({ previous: row.previous_config, saved: row.config, preview: row.preview }, null, 2)}</pre>
      </details>)}
    </>}
  </section>;
}
