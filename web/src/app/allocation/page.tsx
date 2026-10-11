import Link from "next/link";
import { Disclaimer } from "@/components/Disclaimer";
import { pool } from "@/lib/db";
import { readAllocation } from "@/lib/allocation-store";
import type { AllocationReason } from "@/lib/allocation";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const reasons: Record<AllocationReason, [string, string]> = {
  account_stale: ["账户快照过期", "Account snapshot is stale"],
  controller_stale: ["控制器心跳缺失或过期", "Controller heartbeat missing or stale"],
  revision_mismatch: ["配置与控制器版本不一致或配置异常", "Settings/controller revision mismatch or settings error"],
  pending_orders: ["存在未决委托，调整暂不可用", "Unresolved orders: adjustments unavailable"],
  market_unavailable: ["行情缺失、过期或合约非交易状态", "Market missing, stale, or instrument not live"],
  ownership_mismatch: ["账户数量与系统持有量不符（含同标的手动仓位）；不估算调整", "Account/managed quantity mismatch (including manual same-symbol positions); no adjustment"],
  signal_unavailable: ["缺少四天内同策略、同参数的目标；不是空仓信号", "No target within four days matching the held strategy and parameters; not a flat signal"],
  exit_pending: ["已有退出流程，调整暂不可用", "Exit already pending: adjustments unavailable"],
  size_rules_unavailable: ["未持久化交易所手数/最小量；数量估算不可用", "Exchange lot/minimum metadata is not persisted; quantity estimate unavailable"],
  below_minimum: ["向下取整后不足最小交易量（碎仓或金额不足）", "Below minimum after rounding down (dust or insufficient amount)"],
  pooled: ["按所有可用增持缺口比例分配现金池", "Shared cash pool allocated proportionally to all eligible increase gaps"],
  decrease_only: ["仅概念性减持差额；不自动再平衡，不预支卖出资金", "Conceptual decrease only; no automatic rebalance or anticipated sale cash"],
  at_ceiling: ["当前价值与假设目标一致", "Current value matches the hypothetical target"],
  invalid_position: ["持仓或价格数据无效", "Invalid position or price data"],
};
const amount = (value: string | null, unknown: string) => value === null ? unknown : `${Number(value).toFixed(2)} USDT`;

export default async function AllocationPage({ searchParams }: { searchParams?: { lang?: string } }) {
  const lang = searchParams?.lang === "en" ? "en" : "zh";
  const en = lang === "en";
  const t = (zh: string, english: string) => en ? english : zh;
  const unavailable = t("不可用", "Unavailable");
  let data: Awaited<ReturnType<typeof readAllocation>> | null = null;
  try {
    const client = await pool.connect();
    try {
      await client.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
      await client.query("SET LOCAL statement_timeout = '5s'");
      data = await readAllocation(client);
      await client.query("COMMIT");
    } catch (error) {
      data = null;
      console.error("Allocation preview query failed", error instanceof Error ? error.name : "unknown");
      await client.query("ROLLBACK");
    } finally { client.release(); }
  } catch (error) {
    data = null;
    console.error("Allocation preview unavailable", error instanceof Error ? error.name : "unknown");
  }
  return <main className="mx-auto max-w-6xl space-y-6 px-5 py-10">
    <nav className="flex flex-wrap gap-4 text-sm underline">
      <Link href={`/?lang=${lang}`}>{t("← 仪表盘", "← Dashboard")}</Link>
      <Link href={`/settings?lang=${lang}`}>{t("持仓与资金设置", "Holdings & budgets")}</Link>
      <Link href="/allocation?lang=zh">中文</Link><Link href="/allocation?lang=en">English</Link>
    </nav>
    <h1 className="text-2xl font-semibold">{t("持仓配置预览（只读模拟）", "Held allocation preview (read-only simulation)")}</h1>
    <section className="space-y-2 rounded-lg border border-amber-300 p-4 text-sm">
      <p>{t("不下单、不保存设置、不自动再平衡；仅查看已有系统持仓。", "No orders, settings saves, or automatic rebalancing. Existing managed holdings only.")}</p>
      <p>{t("策略仅给出持有(1)或空仓(0)，没有推荐金额。下方假设：持有时以用户预算上限为目标，空仓时为零。预算上限不是策略推荐仓位。", "The strategy supplies long (1) or flat (0), not a recommended amount. The illustration uses the user budget ceiling when long, zero when flat. A budget ceiling is not a strategy-recommended allocation.")}</p>
      <p>{t("新增金额共同受可用现金减预留、总预算减全部账户敞口约束，并按增持缺口比例分配；减持所得在成交前不计入现金。不新增标的、不改变排名，无盈利门槛。", "Increases share min(available cash − reserve, total budget − all account exposure), proportionally to increase gaps. Conceptual sale proceeds never fund increases before fills. No new symbols, ranking changes, or profitability gate.")}</p>
      <p>{t("仅金额估算；不模拟费用、滑点、资金费或全部执行风控。数量需有效手数和最小量后向下取整。", "Notional estimates only; fees, slippage, funding, and full execution checks are not simulated. Quantity estimates require valid lot/minimum sizes and round down.")}</p>
    </section>
    {!data ? <p role="status">{t("预览不可用：账户快照可能超过180秒，或配置/数据库数据不可用。未把缺失数据视为零，也未生成调整。", "Preview unavailable: account may be older than 180 seconds, or configuration/database data is unavailable. Missing data is not zero; no adjustments were generated.")}</p> : <>
      <p className="text-sm text-neutral-500">{t("账户快照", "Account snapshot")}: {data.snapshotAt} · {t("配置版本", "Settings revision")}: {data.revision}</p>
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[
          [t("系统持有市值", "Managed position value"), amount(data.managedValueUsdt, unavailable)],
          [t("全部账户敞口（含手动）", "All account exposure (including manual)"), amount(data.exposureUsdt, unavailable)],
          [t("总预算上限（已扣预留）", "Total ceiling (after reserve)"), amount(data.totalUsdt, unavailable)],
          [t("可用现金减预留", "Available cash after reserve"), amount(data.cashAfterReserveUsdt, unavailable)],
          [t("共同增持资金池", "Shared increase pool"), amount(data.increasePoolUsdt, unavailable)],
          [t("假设分配增持金额", "Hypothetical allocated increases"), data.blockers.length ? unavailable : amount(data.allocatedIncreaseUsdt, unavailable)],
        ].map(([label, value]) => <div key={label} className="rounded-lg border border-neutral-300 p-3"><div className="text-xs text-neutral-500">{label}</div><div className="mt-1 font-medium">{value}</div></div>)}
      </section>
      <p className="text-sm">{t("预留", "Reserve")}: {amount(String(data.summary.reserveUsdt), unavailable)} · {t("持仓数 / 上限", "Holdings / cap")}: {data.summary.heldCount} / {data.summary.maxHoldings}. {t("数量/分组上限约束新建仓；本页仅模拟调整已有仓位，不将其当作执行授权。", "Holding/group caps restrict new entries; this page illustrates existing holdings only and is not execution authorization.")}</p>
      {data.blockers.length > 0 && <p role="status" className="text-amber-700">{data.blockers.map((r) => reasons[r][en ? 1 : 0]).join(" · ")}</p>}
      {!data.rows.length && <p>{t("当前无系统持仓；不会选择新标的。", "No managed holdings; no new symbols are selected.")}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead><tr>{[
            t("标的 / 策略", "Instrument / strategy"), t("系统数量 / 市值", "Owned quantity / value"),
            t("用户预算上限", "User budget ceiling"), t("当前策略目标", "Current strategy target"),
            t("假设目标金额", "Hypothetical target"), t("增持 / 概念性减持", "Increase / conceptual decrease"),
            t("调整数量估算", "Adjustment quantity estimate"),
          ].map((label) => <th key={label} className="border-b p-3 align-top">{label}</th>)}</tr></thead>
          <tbody>{data.rows.map((row) => <tr key={row.instrument} className="border-b">
            <td className="p-3 align-top"><div>{row.instrument}</div><div className="text-xs">{row.strategy}</div></td>
            <td className="p-3 align-top">{row.ownedQuantity}<br />{amount(row.currentUsdt, unavailable)}</td>
            <td className="p-3 align-top">{amount(row.ceilingUsdt, unavailable)}</td>
            <td className="p-3 align-top">{row.strategyTarget === null ? unavailable : row.strategyTarget === 1 ? t("持有 (1)", "Long (1)") : t("空仓 (0)", "Flat (0)")}</td>
            <td className="p-3 align-top">{amount(row.targetUsdt, unavailable)}</td>
            <td className="p-3 align-top"><div>+ {amount(row.increaseUsdt, unavailable)}</div><div>− {amount(row.decreaseUsdt, unavailable)}</div></td>
            <td className="min-w-64 p-3 align-top">
              <div>{row.quantity ?? unavailable}{row.quantity !== null ? t("（基础资产单位）", " (base-asset units)") : ""}</div>
              {row.quantityNotionalUsdt !== null && <div>{t("取整后金额", "Rounded notional")}: {amount(row.quantityNotionalUsdt, unavailable)}</div>}
              <ul className="mt-2 space-y-1 text-xs text-neutral-500">{row.reasons.map((r) => <li key={r}>{reasons[r][en ? 1 : 0]}</li>)}</ul>
            </td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
    <Disclaimer lang={lang} />
  </main>;
}
