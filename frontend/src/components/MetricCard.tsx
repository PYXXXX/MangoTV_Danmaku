import type { ReactNode } from "react";

export function MetricCard({ label, value, detail, icon, tone = "orange" }: { label: string; value: ReactNode; detail?: ReactNode; icon?: ReactNode; tone?: "orange" | "green" | "blue" | "red" }) {
  const toneClass = {
    orange: "text-ops-orange bg-orange-400/10",
    green: "text-ops-green bg-emerald-400/10",
    blue: "text-ops-blue bg-blue-400/10",
    red: "text-ops-red bg-red-400/10"
  }[tone];
  return (
    <article className="glass min-w-0 rounded-3xl p-5">
      <div className="flex min-w-0 items-start gap-4">
        {icon && <span className={`grid size-12 shrink-0 place-items-center rounded-2xl ${toneClass}`}>{icon}</span>}
        <div className="min-w-0">
          <span className="text-sm text-ops-muted">{label}</span>
          <strong className="mt-2 block min-w-0 break-words text-2xl font-black tracking-[-0.045em]">{value}</strong>
          {detail && <p className="mt-1 min-w-0 text-xs text-ops-muted [overflow-wrap:anywhere]">{detail}</p>}
        </div>
      </div>
    </article>
  );
}
