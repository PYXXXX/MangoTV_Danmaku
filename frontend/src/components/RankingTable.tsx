import { Crown } from "@phosphor-icons/react";
import type { RankingRow } from "../api/types";
import { formatCount } from "../lib/format";

export function RankingTable({ rows }: { rows: RankingRow[] }) {
  const max = Math.max(1, ...rows.map((item) => item.votes));
  if (!rows.length) {
    return <div className="grid min-h-80 place-items-center text-sm text-ops-subtle">结果发布后将在这里显示</div>;
  }
  return (
    <div className="divide-y divide-white/[0.07]">
      {rows.map((item, index) => (
        <article key={item.candidateId} className="grid min-h-[76px] grid-cols-[52px_180px_minmax(160px,1fr)_110px] items-center gap-5 max-md:grid-cols-[44px_1fr_96px]">
          <span className={`grid size-9 place-items-center rounded-full font-mono text-sm font-black ${index === 0 ? "bg-gradient-to-br from-yellow-300 to-orange-500 text-[#201005]" : "bg-white/10 text-slate-200"}`}>
            {index === 0 ? <Crown size={18} weight="fill" /> : index + 1}
          </span>
          <div className="min-w-0">
            <strong className="block truncate text-xl font-black tracking-[-0.04em]">{item.name}</strong>
            <span className="text-xs text-ops-muted">{item.percent.toFixed(1)}% · 趋势 {item.trend && item.trend > 0 ? "+" : ""}{item.trend ?? 0}%</span>
          </div>
          <div className="h-3 overflow-hidden rounded-full bg-white/10 max-md:col-span-2 max-md:col-start-2">
            <div className="h-full rounded-full bg-gradient-to-r from-ops-orange to-ops-gold" style={{ width: `${Math.max(2, (item.votes / max) * 100)}%` }} />
          </div>
          <strong className="text-right font-mono text-2xl font-black">{formatCount(item.votes)}</strong>
        </article>
      ))}
    </div>
  );
}
