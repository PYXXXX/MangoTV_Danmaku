import { CheckCircle, Circle, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";

export interface TimelineItem {
  title: string;
  description: string;
  tone?: "done" | "active" | "warn" | "idle";
  right?: ReactNode;
}

export function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <div className="grid">
      {items.map((item, index) => {
        const icon = item.tone === "warn"
          ? <WarningCircle size={22} weight="fill" />
          : item.tone === "done" || item.tone === "active"
            ? <CheckCircle size={22} weight="fill" />
            : <Circle size={22} />;
        const color = item.tone === "warn" ? "text-ops-orange" : item.tone === "done" ? "text-ops-green" : item.tone === "active" ? "text-ops-blue" : "text-slate-500";
        return (
          <div key={`${item.title}-${index}`} className="relative grid min-w-0 grid-cols-[42px_minmax(0,1fr)_minmax(0,auto)] gap-3 border-b border-white/[0.07] py-4 last:border-b-0">
            {index < items.length - 1 && <span className="absolute left-[20px] top-11 h-[calc(100%-22px)] border-l border-dashed border-white/15" />}
            <span className={`relative z-10 grid size-10 place-items-center rounded-full border border-white/10 bg-white/[0.04] ${color}`}>{icon}</span>
            <div className="min-w-0">
              <strong className="block truncate text-sm font-black">{item.title}</strong>
              <small className="mt-1 block truncate text-xs text-ops-muted">{item.description}</small>
            </div>
            <div className="min-w-0 truncate text-right text-xs text-ops-muted">{item.right}</div>
          </div>
        );
      })}
    </div>
  );
}
