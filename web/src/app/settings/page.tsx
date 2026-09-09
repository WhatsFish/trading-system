import Link from "next/link";
import { Disclaimer } from "@/components/Disclaimer";
import { PortfolioSettings } from "@/components/PortfolioSettings";

export default function SettingsPage({ searchParams }: { searchParams?: { lang?: string } }) {
  const lang = searchParams?.lang === "en" ? "en" : "zh";
  return <main className="mx-auto max-w-5xl space-y-6 px-5 py-10">
    <nav className="flex gap-4 text-sm">
      <Link href={`/?lang=${lang}`}>{lang === "zh" ? "← 仪表盘" : "← Dashboard"}</Link>
      <Link href="/settings?lang=zh">中文</Link><Link href="/settings?lang=en">English</Link>
    </nav>
    <h1 className="text-2xl font-semibold">{lang === "zh" ? "持仓与资金设置" : "Holdings and budget settings"}</h1>
    <PortfolioSettings lang={lang} />
    <Disclaimer lang={lang} />
  </main>;
}
