export function Disclaimer({ lang = "en" }: { lang?: "zh" | "en" }) {
  return (
    <footer className="mt-10 border-t border-neutral-200 pt-5 text-xs leading-relaxed text-neutral-500 dark:border-neutral-800">
      {lang === "zh"
        ? "本系统用于自动化交易研究与执行，不构成收益保证。历史回测和候选分数不能预测未来表现。"
        : "Systematic trading research and execution, not a return guarantee. Historical backtests and candidate scores do not predict future performance."}
    </footer>
  );
}
