import { GithubLogo, LinkSimple, ShieldCheck, DownloadSimple, Microphone } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getPublicPageState } from "../../api/client";
import { Card } from "../../components/Shell";
import { RankingTable } from "../../components/RankingTable";
import { currentRound, formatCount, rankingRows, roundName, selectedResult } from "../../lib/format";

const dataSource = "https://pyxxxx.github.io/MangoTV_Danmaku/";

export function PublicResultsApp() {
  const query = useQuery({ queryKey: ["public-results"], queryFn: getPublicPageState });
  const state = query.data;
  const [selectedSessionId, setSelectedSessionId] = useState<string>("");
  const [resultType, setResultType] = useState<"rough" | "precise">("rough");
  const sessions = state?.sessions || [];
  const defaultSession = currentRound(sessions, state?.activeSessionId);
  useEffect(() => {
    if (!selectedSessionId && defaultSession?.id) {
      setSelectedSessionId(defaultSession.id);
      setResultType(defaultSession.defaultResultType || "rough");
    }
  }, [defaultSession?.id, defaultSession?.defaultResultType, selectedSessionId]);
  const session = sessions.find((item) => item.id === selectedSessionId) || defaultSession;
  const result = selectedResult(session, resultType);
  const rows = rankingRows(session, result.data);
  const leader = rows[0];
  const total = rows.reduce((sum, item) => sum + item.votes, 0);
  const activity = session?.activity || state?.defaults?.activity || "直播活动";
  const exportPngUrl =
    (result.type === "precise" ? session?.resultImageUrls?.precise : session?.resultImageUrls?.rough)
    || session?.resultImageUrl
    || (session ? `/exports/rounds/${encodeURIComponent(session.id)}/result.png?result=${result.type}` : "#");
  const recent = [...sessions]
    .sort((a, b) => String(b.stoppedAt || b.startedAt || "").localeCompare(String(a.stoppedAt || a.startedAt || "")))
    .slice(0, 5);
  return (
    <div className="min-h-dvh text-[#fff7ea] public-stage">
      <nav className="sticky top-0 z-10 flex min-h-16 items-center justify-between border-b border-white/10 bg-[#06090d]/80 px-8 backdrop-blur-2xl max-md:flex-col max-md:items-start max-md:gap-3 max-md:py-4">
        <a className="flex items-center gap-3 text-xl font-black tracking-[-0.045em]" href="./">
          <span className="orange-glow grid size-10 place-items-center rounded-full bg-gradient-to-br from-[#ff9d35] to-[#ff7417] text-[#160b04]">▶</span>
          公开结果页
        </a>
        <div className="flex flex-wrap items-center gap-7 text-sm text-slate-300">
          <a href="#ranking">{activity}</a>
          <a href="#timeline">场次列表</a>
          <a href="#source">数据说明</a>
          <a className="inline-flex min-h-9 items-center gap-2 rounded-full border border-white/10 px-4" href="https://github.com/PYXXXX/MangoTV_Danmaku" target="_blank" rel="noreferrer">
            <GithubLogo size={18} weight="fill" />
            GitHub
          </a>
        </div>
      </nav>

      <main className="relative z-[1] mx-auto w-[min(1540px,calc(100%-46px))] py-7">
        <header className="grid min-h-[310px] grid-cols-[minmax(0,1fr)_minmax(420px,635px)] gap-6 max-lg:grid-cols-1">
          <section className="grid content-center">
            <p className="mb-4 font-mono text-xs font-black uppercase tracking-[0.18em] text-ops-orange">Public Live Report</p>
            <h1 className="max-w-4xl text-6xl font-black leading-[.96] tracking-[-0.065em] max-md:text-4xl">
              <span className="text-ops-gold">{activity}</span> · 直播弹幕投票统计
            </h1>
            <p className="mt-5 max-w-3xl text-xl leading-8 text-[#d6d0c6]">
              实时弹幕切片分析与公开结果发布。数据每 30 秒自动刷新一次。
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Badge tone="orange">{result.type === "precise" ? "精确结果" : "粗略结果"}</Badge>
              <Badge tone="green">{session?.results?.precise ? "精确结果已发布" : "精确结果待发布"}</Badge>
              <Badge>数据更新于 {state?.publishedAt ? new Date(state.publishedAt).toLocaleString("zh-CN", { hour12: false }) : "尚未同步"}</Badge>
            </div>
          </section>

          <Card title="当前场次" className="bg-black/20">
            <strong className="block text-4xl font-black tracking-[-0.055em]">{session ? roundName(session) : "等待发布"}</strong>
            <span className="mt-2 block text-sm text-ops-muted">{session?.timeRange || (session?.status === "running" ? "正在采集" : "暂无场次时间")}</span>
            <div className="mt-6 rounded-3xl border border-orange-400/40 bg-orange-400/10 p-5">
              {leader ? (
                <>
                  <span className="rounded-full bg-orange-400/15 px-3 py-1 text-xs font-black text-ops-gold">当前领先</span>
                  <div className="mt-4 grid grid-cols-[86px_minmax(0,1fr)_120px] items-center gap-4 max-sm:grid-cols-1">
                    <div className="orange-glow grid size-20 place-items-center rounded-full border border-orange-300/40 bg-[radial-gradient(circle,#ffc077,#ff861f_58%,#2a1305)] text-[#2a1305]">
                      <Microphone size={42} weight="fill" />
                    </div>
                    <div>
                      <strong className="block text-4xl font-black tracking-[-0.055em]">{leader.name}</strong>
                      <small className="mt-2 block text-xl font-black text-ops-gold">{formatCount(leader.votes)} 票</small>
                    </div>
                    <strong className="font-mono text-5xl font-black text-ops-orange">{leader.percent.toFixed(1)}%</strong>
                  </div>
                  <div className="mt-5 h-2 overflow-hidden rounded-full bg-white/10">
                    <span className="block h-full rounded-full bg-gradient-to-r from-ops-orange to-ops-gold" style={{ width: `${Math.max(3, leader.percent)}%` }} />
                  </div>
                </>
              ) : (
                <p className="text-sm text-ops-muted">结果将在这里显示</p>
              )}
            </div>
          </Card>
        </header>

        <div className="my-5 grid grid-cols-3 rounded-3xl border border-white/10 bg-white/[0.04] max-md:grid-cols-1">
          <Metric label="弹幕样本" value={formatCount(result.data.messageCount || session?.messageCount)} />
          <Metric label="有效计票" value={formatCount(total)} />
          <Metric label="语义待审" value={formatCount(result.data.reviewCount || session?.reviewCount)} />
        </div>

        <section className="grid grid-cols-[minmax(0,1.35fr)_minmax(390px,.95fr)] gap-5 max-xl:grid-cols-1">
          <Card
            title="实时弹幕投票排名"
            className="min-h-[520px]"
            action={
              <div className="grid grid-cols-2 rounded-xl border border-white/10 bg-black/20 p-1">
                <button className={`rounded-lg px-4 py-2 text-sm font-black ${result.type === "rough" ? "bg-orange-400/15 text-ops-gold" : "text-ops-muted"}`} type="button" onClick={() => setResultType("rough")}>粗略结果</button>
                <button className={`rounded-lg px-4 py-2 text-sm font-black ${result.type === "precise" ? "bg-orange-400/15 text-ops-gold" : "text-ops-muted"}`} type="button" disabled={!session?.results?.precise} onClick={() => setResultType("precise")}>精确结果</button>
              </div>
            }
          >
            <div id="ranking">
              <RankingTable rows={rows} />
            </div>
          </Card>

          <aside className="grid content-start gap-4">
            <Card title="公开导出">
              <div className="grid gap-3">
                <a className="orange-glow inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-[#ff9d35] to-[#ff7417] px-4 text-sm font-black text-[#190d05]" href={exportPngUrl}>
                  <DownloadSimple size={18} weight="bold" />
                  导出当前结果 PNG
                </a>
                <button className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-black" type="button" onClick={() => navigator.clipboard?.writeText(window.location.href)}>
                  <LinkSimple size={18} />
                  复制分享链接
                </button>
                <a className="inline-flex min-h-12 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-black" href="./data/results.json" download>下载 JSON 数据</a>
              </div>
            </Card>

            <Card title="场次时间线">
              <div id="timeline" className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                {(state?.sessions || []).map((item) => (
                  <button key={item.id} type="button" onClick={() => { setSelectedSessionId(item.id); setResultType(item.defaultResultType || "rough"); }} className={`min-h-24 rounded-2xl border p-4 text-left ${item.id === session?.id ? "border-orange-400/60 bg-orange-400/10" : "border-white/10 bg-black/20"}`}>
                    <strong className="block text-sm">{roundName(item)}</strong>
                    <span className="mt-2 block text-xs leading-5 text-ops-muted">{item.timeRange || item.status} · {formatCount(item.messageCount)} 样本</span>
                  </button>
                ))}
              </div>
            </Card>

            <Card title="数据来源">
              <div id="source" className="grid gap-3 text-sm leading-7 text-ops-muted">
                <p className="flex gap-2"><ShieldCheck size={20} className="mt-1 text-ops-green" /> 页面数据来自公开弹幕采集与统计分析。</p>
                <p>公开结果页地址：<a className="text-ops-gold" href={dataSource}>{dataSource}</a></p>
                <p>统计数据不代表湖南卫视 &amp; 芒果 TV 立场，仅供娱乐参考。</p>
              </div>
            </Card>

            <Card title="最近发布">
              <div className="grid gap-3">
                {recent.map((item) => (
                  <button key={item.id} type="button" onClick={() => setSelectedSessionId(item.id)} className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-left text-sm">
                    <span className="truncate">{roundName(item)} · {item.defaultResultType === "precise" ? "精确结果" : "粗略结果"}</span>
                    <time className="shrink-0 text-xs text-ops-muted">{item.stoppedAt ? new Date(item.stoppedAt).toLocaleTimeString("zh-CN", { hour12: false }) : item.status}</time>
                  </button>
                ))}
                {!recent.length && <p className="text-sm text-ops-muted">暂无发布记录</p>}
              </div>
            </Card>
          </aside>
        </section>
      </main>

      {query.isError && <div className="fixed bottom-5 left-1/2 -translate-x-1/2 rounded-2xl border border-red-400/30 bg-red-400/15 px-5 py-3 text-sm text-red-100">公开数据读取失败</div>}
    </div>
  );
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "orange" | "green" | "neutral" }) {
  const toneClass = tone === "orange"
    ? "border-orange-400/40 bg-orange-400/10 text-ops-gold"
    : tone === "green"
      ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
      : "border-white/10 bg-white/[0.04] text-slate-300";
  return <span className={`inline-flex min-h-9 items-center rounded-xl border px-3 text-sm font-bold ${toneClass}`}>{children}</span>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-r border-white/10 p-6 last:border-r-0 max-md:border-b max-md:border-r-0">
      <span className="block text-sm text-ops-muted">{label}</span>
      <strong className="mt-2 block font-mono text-5xl font-black tracking-[-0.06em]">{value}</strong>
    </div>
  );
}
