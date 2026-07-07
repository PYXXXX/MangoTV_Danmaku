import {
  Bell,
  ChartBar,
  GearSix,
  List,
  ListChecks,
  Pulse,
  Question,
  Rows,
  SignOut,
  X,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useState } from "react";
import type { AdminPage } from "../state/ui";

const navItems: Array<{ id: AdminPage; label: string; helper: string; icon: ReactNode }> = [
  { id: "activity", label: "活动监控", helper: "监控开播与自动化策略", icon: <Pulse size={22} /> },
  { id: "ops", label: "运营工作区", helper: "实时运营与后处理", icon: <ChartBar size={22} /> },
  { id: "settings", label: "系统配置", helper: "全局设置与集成", icon: <GearSix size={22} /> },
  { id: "machine", label: "机器状态", helper: "性能与服务健康", icon: <Pulse size={22} /> },
  { id: "logs", label: "系统日志", helper: "排障与审计", icon: <Rows size={22} /> }
];

interface ShellProps {
  activePage: AdminPage;
  title: string;
  subtitle: string;
  badges: ReactNode;
  children: ReactNode;
  onNavigate: (page: AdminPage) => void;
}

export function Shell({ activePage, title, subtitle, badges, children, onNavigate }: ShellProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const markSrc = "/studio/assets/live-ops-mark.png";
  const navigate = (page: AdminPage) => {
    onNavigate(page);
    setDrawerOpen(false);
  };
  return (
    <div className="relative grid min-h-dvh grid-cols-[300px_minmax(0,1fr)] text-[#fff7ea] max-xl:grid-cols-1">
      <div className="glass sticky top-0 z-30 hidden min-h-16 items-center justify-between gap-3 rounded-none border-x-0 border-t-0 px-4 py-3 max-sm:flex">
        <div className="flex min-w-0 items-center gap-3">
          <img
            src={markSrc}
            alt="直播运营工作台"
            className="orange-glow size-11 rounded-2xl object-cover"
            width={44}
            height={44}
            decoding="async"
          />
          <div className="min-w-0">
            <strong className="block truncate text-base font-black tracking-[-0.04em]">直播运营工作台</strong>
            <span className="block truncate font-mono text-[10px] uppercase tracking-[0.16em] text-ops-muted">Live Ops Studio</span>
          </div>
        </div>
        <button
          type="button"
          className="grid size-11 shrink-0 place-items-center rounded-2xl border border-white/10 bg-white/[0.05] text-slate-100"
          aria-label="打开菜单"
          aria-expanded={drawerOpen}
          onClick={() => setDrawerOpen(true)}
        >
          <List size={22} weight="bold" />
        </button>
      </div>

      <aside className="glass sticky top-0 z-20 flex h-dvh flex-col gap-8 rounded-none border-y-0 border-l-0 px-6 py-5 max-xl:static max-xl:h-auto max-xl:flex-row max-xl:items-center max-xl:overflow-x-auto max-sm:hidden">
        <div className="flex items-center gap-4">
          <img
            src={markSrc}
            alt="直播运营工作台"
            className="orange-glow size-14 rounded-2xl object-cover"
            width={56}
            height={56}
            decoding="async"
          />
          <div className="min-w-40">
            <strong className="block text-xl font-black tracking-[-0.05em]">直播运营工作台</strong>
            <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-ops-muted">MangoTV Live Ops Studio</span>
          </div>
        </div>

        <nav className="grid gap-3 max-xl:flex">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              data-testid={`studio-nav-${item.id}`}
              onClick={() => navigate(item.id)}
              className={[
                "group flex min-h-16 min-w-56 items-center gap-4 rounded-2xl border px-4 text-left transition",
                activePage === item.id
                  ? "border-orange-400/45 bg-orange-500/15 text-ops-gold shadow-[inset_4px_0_0_#ff861f]"
                  : "border-transparent bg-transparent text-slate-300 hover:border-white/10 hover:bg-white/[0.04]"
              ].join(" ")}
            >
              <span className="grid size-9 place-items-center rounded-xl bg-white/[0.05] text-ops-orange">{item.icon}</span>
              <span>
                <b className="block text-sm font-extrabold">{item.label}</b>
                <small className="mt-1 block text-xs text-ops-muted">{item.helper}</small>
              </span>
            </button>
          ))}
        </nav>

        <div className="mt-auto grid gap-3 max-xl:ml-auto max-xl:mt-0 max-sm:hidden">
          <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm font-bold text-emerald-200">
            <span className="mr-2 inline-block size-2 rounded-full bg-emerald-400 shadow-[0_0_0_6px_rgba(88,217,133,.12)]" />
            服务运行正常
          </div>
          <form action="/auth/logout" method="post">
            <button className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-bold text-slate-300" type="submit">
              <SignOut size={18} />
              退出登录
            </button>
          </form>
        </div>
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 hidden max-sm:block">
          <button
            type="button"
            className="absolute inset-0 bg-black/65 backdrop-blur-sm"
            aria-label="关闭菜单背景"
            onClick={() => setDrawerOpen(false)}
          />
          <aside className="glass absolute left-0 top-0 flex h-dvh w-[84vw] max-w-[340px] flex-col gap-6 rounded-none border-y-0 border-l-0 px-5 py-5 shadow-2xl">
            <div className="flex items-center justify-between gap-4">
              <div className="flex min-w-0 items-center gap-3">
                <img
                  src={markSrc}
                  alt="直播运营工作台"
                  className="orange-glow size-12 rounded-2xl object-cover"
                  width={48}
                  height={48}
                  decoding="async"
                />
                <div className="min-w-0">
                  <strong className="block truncate text-lg font-black tracking-[-0.05em]">直播运营工作台</strong>
                  <span className="block truncate font-mono text-[10px] uppercase tracking-[0.16em] text-ops-muted">MangoTV Live Ops Studio</span>
                </div>
              </div>
              <button
                type="button"
                className="grid size-10 shrink-0 place-items-center rounded-2xl border border-white/10 bg-white/[0.05]"
                aria-label="关闭菜单"
                onClick={() => setDrawerOpen(false)}
              >
                <X size={20} weight="bold" />
              </button>
            </div>

            <nav className="grid gap-3">
              {navItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  data-testid={`studio-mobile-nav-${item.id}`}
                  onClick={() => navigate(item.id)}
                  className={[
                    "group flex min-h-16 items-center gap-4 rounded-2xl border px-4 text-left transition active:scale-[0.98]",
                    activePage === item.id
                      ? "border-orange-400/45 bg-orange-500/15 text-ops-gold shadow-[inset_4px_0_0_#ff861f]"
                      : "border-white/5 bg-white/[0.025] text-slate-300"
                  ].join(" ")}
                >
                  <span className="grid size-9 place-items-center rounded-xl bg-white/[0.05] text-ops-orange">{item.icon}</span>
                  <span>
                    <b className="block text-sm font-extrabold">{item.label}</b>
                    <small className="mt-1 block text-xs text-ops-muted">{item.helper}</small>
                  </span>
                </button>
              ))}
            </nav>

            <div className="mt-auto grid gap-3">
              <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm font-bold text-emerald-200">
                <span className="mr-2 inline-block size-2 rounded-full bg-emerald-400 shadow-[0_0_0_6px_rgba(88,217,133,.12)]" />
                服务运行正常
              </div>
              <form action="/auth/logout" method="post">
                <button className="flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-bold text-slate-300" type="submit">
                  <SignOut size={18} />
                  退出登录
                </button>
              </form>
            </div>
          </aside>
        </div>
      )}

      <section className="min-w-0">
        <header className="sticky top-0 z-10 flex min-h-[70px] items-center justify-between gap-6 border-b border-white/10 bg-[#070a0d]/80 px-7 backdrop-blur-2xl max-lg:static max-lg:flex-col max-lg:items-start max-lg:py-4 max-sm:min-h-0 max-sm:px-4 max-sm:py-3">
          <div className="flex min-w-0 items-baseline gap-4">
            <h1 className="whitespace-nowrap text-2xl font-black tracking-[-0.055em] max-sm:text-xl">{title}</h1>
            <p className="truncate text-sm text-ops-muted max-sm:hidden">{subtitle}</p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3 max-sm:hidden">
            {badges}
            <button className="grid size-10 place-items-center rounded-xl border border-white/10 bg-white/[0.04]" type="button" aria-label="通知">
              <Bell size={20} />
            </button>
            <button className="grid size-10 place-items-center rounded-xl border border-white/10 bg-white/[0.04]" type="button" aria-label="帮助">
              <Question size={20} />
            </button>
          </div>
        </header>
        <main data-testid={`studio-page-${activePage}`} className="mx-auto w-full max-w-[1720px] px-7 py-7 max-sm:px-4 max-sm:py-5">{children}</main>
      </section>
    </div>
  );
}

export function StatusBadge({ tone = "neutral", children }: { tone?: "green" | "orange" | "blue" | "red" | "neutral"; children: ReactNode }) {
  const toneClass = {
    green: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
    orange: "border-orange-400/35 bg-orange-400/10 text-ops-gold",
    blue: "border-blue-400/30 bg-blue-400/10 text-blue-200",
    red: "border-red-400/30 bg-red-400/10 text-red-200",
    neutral: "border-white/10 bg-white/[0.04] text-slate-300"
  }[tone];
  return (
    <span className={`inline-flex min-h-9 items-center gap-2 rounded-full border px-3 text-sm font-extrabold ${toneClass}`}>
      <span className="size-2 rounded-full bg-current shadow-[0_0_0_6px_rgba(255,255,255,.08)]" />
      {children}
    </span>
  );
}

export function PageHeading({ kicker, title, description, action }: { kicker: string; title: string; description: string; action?: ReactNode }) {
  return (
    <div className="mb-6 flex items-start justify-between gap-6 max-md:flex-col">
      <div>
        <p className="mb-3 font-mono text-xs font-black uppercase tracking-[0.18em] text-ops-orange">{kicker}</p>
        <h2 className="text-4xl font-black tracking-[-0.06em]">{title}</h2>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-ops-muted">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function Card({ title, children, action, className = "" }: { title?: string; children: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <section className={`glass relative overflow-hidden rounded-3xl p-5 ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-start justify-between gap-4">
          {title ? <h3 className="text-lg font-black tracking-[-0.035em]">{title}</h3> : <span />}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function PrimaryButton({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} className="orange-glow inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-[#ff9d35] to-[#ff7417] px-5 text-sm font-black text-[#190d05]">
      <ListChecks size={18} weight="bold" />
      {children}
    </button>
  );
}
