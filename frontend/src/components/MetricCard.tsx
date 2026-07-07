import type { ReactNode } from "react";

export function MetricCard({ label, value, detail, icon, tone = "orange" }: { label: string; value: ReactNode; detail?: ReactNode; icon?: ReactNode; tone?: "orange" | "green" | "blue" | "red" }) {
  const toneClass = {
    orange: "text-ops-orange bg-orange-400/10",
    green: "text-ops-green bg-emerald-400/10",
    blue: "text-ops-blue bg-blue-400/10",
    red: "text-ops-red bg-red-400/10"
  }[tone];
  return (
    <article className="glass rounded-3xl p-5">
      <div className="flex items-start gap-4">
        {icon && <span className={`grid size-12 place-items-center rounded-2xl ${toneClass}`}>{icon}</span>}
        <div>
          <span className="text-sm text-ops-muted">{label}</span>
          <strong className="mt-2 block text-2xl font-black tracking-[-0.045em]">{value}</strong>
          {detail && <p className="mt-1 text-xs text-ops-muted">{detail}</p>}
        </div>
      </div>
    </article>
  );
}
