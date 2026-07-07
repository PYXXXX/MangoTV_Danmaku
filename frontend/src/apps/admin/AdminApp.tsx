import {
  Database,
  Lightning,
  Pulse,
  ShieldCheck
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiPost, getBootstrap, getSystemLogs, getSystemStatus } from "../../api/client";
import type { RoundSession, SystemLogEvent, SystemStatus } from "../../api/types";
import { Card, PageHeading, PrimaryButton, Shell, StatusBadge } from "../../components/Shell";
import { MetricCard } from "../../components/MetricCard";
import { RankingTable } from "../../components/RankingTable";
import { Timeline } from "../../components/Timeline";
import { currentRound, formatBytes, formatCount, formatDuration, rankingRows, roundName, selectedResult } from "../../lib/format";
import { useUiStore } from "../../state/ui";

function useBootstrap() {
  return useQuery({ queryKey: ["studio-bootstrap"], queryFn: getBootstrap });
}

export function AdminApp() {
  const page = useUiStore((state) => state.page);
  const setPage = useUiStore((state) => state.setPage);
  const bootstrap = useBootstrap();
  const publicState = bootstrap.data?.publicState;
  const systemStatus = bootstrap.data?.systemStatus;
  const round = currentRound(publicState?.sessions || [], publicState?.activeSessionId);
  const monitorStatus = systemStatus?.monitor?.state?.status;
  const feishuStatus = systemStatus?.services?.feishu?.status;
  const title = "直播运营工作台";
  const subtitle = round ? `${round.activity || "未分类活动"} · ${roundName(round)}` : "等待开始场次";
  return (
    <Shell
      activePage={page}
      title={title}
      subtitle={subtitle}
      onNavigate={setPage}
      badges={
        <>
          <StatusBadge tone={monitorStatus === "running" || monitorStatus === "source_ready" ? "green" : "orange"}>
            {systemStatus?.monitor?.config?.activity || publicState?.defaults?.activity || "活动未配置"}
          </StatusBadge>
          <StatusBadge tone={round?.status === "running" ? "blue" : "neutral"}>{round?.status === "running" ? "弹幕采集中" : "弹幕待命"}</StatusBadge>
          <StatusBadge tone={feishuStatus === "connected" ? "blue" : "neutral"}>{feishuStatus === "connected" ? "飞书已连接" : "飞书未连接"}</StatusBadge>
        </>
      }
    >
      {bootstrap.isLoading && <div className="grid min-h-[50vh] place-items-center text-ops-muted">正在读取工作台状态…</div>}
      {bootstrap.error && <div className="rounded-2xl border border-red-400/30 bg-red-400/10 p-5 text-red-100">读取失败：{String(bootstrap.error)}</div>}
      {bootstrap.data && (
        <>
          {page === "activity" && <ActivityMonitorPage status={systemStatus} />}
          {page === "ops" && <OperationsPage rounds={publicState?.sessions || []} activeRound={round} />}
          {page === "settings" && <SettingsBlueprintPage status={systemStatus} />}
          {page === "machine" && <MachineStatusPage initial={systemStatus} />}
          {page === "logs" && <SystemLogsPage initialLogs={bootstrap.data.logs || []} />}
        </>
      )}
    </Shell>
  );
}

function ActivityMonitorPage({ status }: { status?: SystemStatus }) {
  const monitor = status?.monitor;
  const config = monitor?.config || {};
  const state = monitor?.state || {};
  const detect = useMutation({
    mutationFn: () => apiPost("/api/mgtv/source/check", { url: config.url || undefined })
  });
  return (
    <section>
      <PageHeading
        kicker="Activity Monitor"
        title="活动监控"
        description="配置活动信息与自动化策略，系统将监控开播、解析直播源，并按策略启动录制、弹幕采集与飞书通知。"
        action={<PrimaryButton onClick={() => detect.mutate()}>立即检测直播源</PrimaryButton>}
      />
      <div className="grid grid-cols-[minmax(360px,1fr)_minmax(420px,1fr)_minmax(330px,.85fr)] gap-4 max-2xl:grid-cols-1">
        <Card title="活动信息" action={<StatusBadge tone={config.enabled ? "green" : "orange"}>{config.enabled ? "监控中" : "未启用"}</StatusBadge>} className="min-h-[360px]">
          <div className="grid gap-4">
            <label className="grid gap-2 text-sm text-ops-muted">
              活动名称
              <input className="rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-base text-white outline-none" value={config.activity || ""} readOnly />
            </label>
            <label className="grid gap-2 text-sm text-ops-muted">
              活动链接
              <input className="rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-base text-white outline-none" value={config.url || ""} readOnly />
            </label>
            <p className="text-sm leading-7 text-ops-muted">{state.message || "保存活动链接后，监控器会按策略轮询直播状态。"}</p>
          </div>
        </Card>

        <Card title="监控策略" className="min-h-[360px]">
          <div className="grid gap-4">
            {[
              ["监控直播状态", config.enabled],
              ["开播后自动检测直播源", config.autoDetectSource],
              ["检测成功后录制视频", config.autoRecordVideo],
              ["检测成功后录制弹幕", config.autoRecordDanmaku],
              ["状态变化通知飞书", config.feishuNotify]
            ].map(([label, enabled]) => (
              <div key={String(label)} className="flex items-center justify-between border-b border-white/[0.07] py-3">
                <div>
                  <strong className="block text-sm">{label}</strong>
                  <span className="text-xs text-ops-muted">当前策略来自系统配置，保存页会计算热重载影响。</span>
                </div>
                <span className={`h-7 w-12 rounded-full p-1 ${enabled ? "bg-ops-orange" : "bg-white/10"}`}>
                  <i className={`block size-5 rounded-full bg-white transition ${enabled ? "translate-x-5" : ""}`} />
                </span>
              </div>
            ))}
          </div>
        </Card>

        <Card title="运行状态" className="min-h-[360px]">
          <Timeline
            items={[
              { title: "等待开播", description: state.lastCheckAt || "监控器已准备", tone: config.enabled ? "active" : "idle" },
              { title: "已解析活动页", description: config.url || "未配置活动链接", tone: config.url ? "done" : "idle" },
              { title: "直播源待检测", description: state.lastError || "开播后自动解析", tone: state.lastError ? "warn" : "idle" }
            ]}
          />
        </Card>
      </div>
    </section>
  );
}

function OperationsPage({ rounds, activeRound }: { rounds: RoundSession[]; activeRound: RoundSession | null }) {
  const queryClient = useQueryClient();
  const resultType = useUiStore((state) => state.resultType);
  const setResultType = useUiStore((state) => state.setResultType);
  const result = selectedResult(activeRound, resultType);
  const rows = rankingRows(activeRound, result.data);
  const total = rows.reduce((sum, row) => sum + row.votes, 0);
  const startRound = useMutation({
    mutationFn: () => apiPost("/api/rounds/start", {
      activity: activeRound?.activity || "歌手 2026",
      name: `第 ${rounds.length + 1} 轮`,
      recordVideo: false,
      collectDanmaku: true
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const endRound = useMutation({
    mutationFn: () => apiPost("/api/rounds/" + encodeURIComponent(activeRound?.id || "") + "/end", { publish: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  return (
    <section>
      <PageHeading
        kicker="Operations Workspace"
        title="运营工作区"
        description="实时开轮次、录制后切片、飞书同步和公开发布集中在这里。这个页面将替代旧的表单堆叠式操作区。"
        action={<PrimaryButton onClick={() => startRound.mutate()}>开始新一轮</PrimaryButton>}
      />
      <div className="grid grid-cols-[320px_minmax(620px,1fr)_390px] gap-4 max-2xl:grid-cols-1">
        <Card title="当前直播状态">
          <Timeline
            items={[
              { title: "活动页", description: activeRound?.pageUrl || activeRound?.activity || "等待识别", tone: activeRound ? "done" : "idle" },
              { title: "直播源", description: activeRound?.pageUrl ? "已解析活动页" : "待检测", tone: activeRound?.pageUrl ? "done" : "idle" },
              { title: "视频录制", description: activeRound?.recording?.status || "未录制", tone: activeRound?.recording ? "active" : "idle" },
              { title: "弹幕采集", description: `${formatCount(activeRound?.messageCount)} 条`, tone: activeRound?.status === "running" ? "active" : "idle" }
            ]}
          />
        </Card>

        <Card
          title="场次与切片"
          action={
            <div className="grid grid-cols-2 rounded-xl border border-white/10 bg-black/20 p-1">
              <button className={`rounded-lg px-4 py-2 text-sm font-black ${result.type === "rough" ? "bg-orange-400/15 text-ops-gold" : "text-ops-muted"}`} onClick={() => setResultType("rough")} type="button">粗略结果</button>
              <button className={`rounded-lg px-4 py-2 text-sm font-black ${result.type === "precise" ? "bg-orange-400/15 text-ops-gold" : "text-ops-muted"}`} onClick={() => setResultType("precise")} type="button" disabled={!activeRound?.results?.precise}>精确结果</button>
            </div>
          }
        >
          <div className="grid grid-cols-[1fr_280px] gap-4 max-xl:grid-cols-1">
            <div>
              <RankingTable rows={rows} />
            </div>
            <div className="grid content-start gap-3">
              <button type="button" onClick={() => endRound.mutate()} disabled={!activeRound || activeRound.status !== "running"} className="rounded-xl border border-red-400/35 bg-red-400/15 px-4 py-3 text-sm font-black text-red-100">结束并发布粗略结果</button>
              <a className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-center text-sm font-black text-slate-100" href={activeRound ? `/api/rounds/${encodeURIComponent(activeRound.id)}/result.png?result=${result.type}` : "#"}>导出 PNG</a>
              <a className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-center text-sm font-black text-slate-100" href={activeRound ? `/api/rounds/${encodeURIComponent(activeRound.id)}.jsonl` : "#"}>导出弹幕</a>
              <div className="rounded-2xl border border-white/10 bg-black/20 p-4 text-sm text-ops-muted">
                <b className="mb-2 block text-white">当前场次</b>
                {activeRound ? `${activeRound.activity || "未分类活动"} / ${roundName(activeRound)}` : "等待场次"}
              </div>
            </div>
          </div>
        </Card>

        <Card title="飞书协同与发布" action={<StatusBadge tone="blue">卡片预览</StatusBadge>}>
          <div className="rounded-2xl border border-white/10 bg-black/20 p-5">
            <strong className="block text-2xl font-black tracking-[-0.04em]">{activeRound?.activity || "暂无活动"}</strong>
            <span className="mt-2 block text-sm text-ops-muted">{activeRound ? roundName(activeRound) : "等待场次"}</span>
            <div className="mt-5 grid grid-cols-3 gap-3">
              <MiniMetric label="弹幕" value={formatCount(result.data.messageCount || activeRound?.messageCount)} />
              <MiniMetric label="有效" value={formatCount(total)} />
              <MiniMetric label="待审" value={formatCount(result.data.reviewCount || activeRound?.reviewCount)} />
            </div>
          </div>
          <div className="mt-4 grid gap-3">
            <button className="rounded-xl bg-blue-500 px-4 py-3 text-sm font-black text-white" type="button">同步到飞书</button>
            <button className="rounded-xl bg-emerald-500 px-4 py-3 text-sm font-black text-white" type="button">发布公开页</button>
          </div>
        </Card>
      </div>

      <Card title="录制后处理" className="mt-4">
        <div className="grid grid-cols-[280px_minmax(0,1fr)_320px] gap-5 max-xl:grid-cols-1">
          <div className="aspect-video rounded-2xl border border-white/10 bg-black/60" />
          <div className="grid content-center gap-4">
            <div className="h-2 rounded-full bg-gradient-to-r from-ops-orange via-ops-blue to-purple-400" />
            <div className="grid grid-cols-5 gap-3 text-center text-xs text-ops-muted">
              {["开始", "选歌环节", "演唱环节", "互动投票", "结果公布"].map((item) => <span key={item}>{item}</span>)}
            </div>
          </div>
          <div className="grid content-start gap-3">
            <button className="rounded-xl border border-orange-400/40 bg-orange-400/15 px-4 py-3 text-sm font-black text-ops-gold" type="button">添加标记</button>
            <button className="rounded-xl border border-blue-400/40 bg-blue-400/15 px-4 py-3 text-sm font-black text-blue-100" type="button">截取片段</button>
            <button className="rounded-xl border border-emerald-400/40 bg-emerald-400/15 px-4 py-3 text-sm font-black text-emerald-100" type="button">生成分析场次</button>
          </div>
        </div>
      </Card>
    </section>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.035] p-3">
      <span className="block text-xs text-ops-muted">{label}</span>
      <b className="mt-1 block font-mono text-xl font-black">{value}</b>
    </div>
  );
}

function SettingsBlueprintPage({ status }: { status?: SystemStatus }) {
  return (
    <section>
      <PageHeading kicker="System Settings" title="系统配置" description="新版配置页将由配置 schema 驱动，展示连接与账号、采集与录制、安全存储更新，以及真实 diff 影响分析。" />
      <div className="grid grid-cols-[1fr_1fr_1fr_.75fr] gap-4 max-2xl:grid-cols-2 max-lg:grid-cols-1">
        <SettingsColumn title="连接与账号" items={["芒果 TV 扫码登录", "飞书 Bot 绑定", "GitHub 发布"]} />
        <SettingsColumn title="采集与录制" items={["弹幕采集参数", "直播录制参数", "自动检测直播源"]} />
        <SettingsColumn title="安全、存储与更新" items={["运营端密码", "存储目录", "程序版本升级"]} />
        <Card title="本次修改影响">
          <div className="grid gap-3 text-sm">
            <Impact tone="green" title="立即生效" items={["飞书白名单", "轮询间隔", "GitHub 路径"]} />
            <Impact tone="blue" title="下一场生效" items={["默认清晰度", "room_id / camera_id"]} />
            <Impact tone="orange" title="需要重启" items={status?.health?.restartFields || ["监听地址", "主数据目录"]} />
          </div>
        </Card>
      </div>
    </section>
  );
}

function SettingsColumn({ title, items }: { title: string; items: string[] }) {
  return (
    <Card title={title}>
      <div className="grid gap-3">
        {items.map((item) => (
          <div key={item} className="rounded-2xl border border-white/10 bg-black/20 p-4">
            <strong className="block text-sm">{item}</strong>
            <span className="mt-1 block text-xs text-ops-muted">等待接入 schema form 与校验接口</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Impact({ tone, title, items }: { tone: "green" | "blue" | "orange"; title: string; items: string[] }) {
  const toneClass = tone === "green" ? "text-emerald-200 bg-emerald-400/10" : tone === "blue" ? "text-blue-200 bg-blue-400/10" : "text-ops-gold bg-orange-400/10";
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
      <span className={`rounded-full px-3 py-1 text-xs font-black ${toneClass}`}>{title}</span>
      <ul className="mt-3 grid gap-2 text-ops-muted">
        {items.map((item) => <li key={item}>• {item}</li>)}
      </ul>
    </div>
  );
}

function MachineStatusPage({ initial }: { initial?: SystemStatus }) {
  const status = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus, initialData: initial, refetchInterval: 15_000 });
  const payload = status.data;
  return (
    <section>
      <PageHeading kicker="System Health" title="机器状态监控" description="实时监控服务器与服务运行状态，保障直播运营稳定可靠。" />
      <div className="mb-4 grid grid-cols-4 gap-4 max-xl:grid-cols-2 max-md:grid-cols-1">
        <MetricCard label="系统时间" value={payload?.systemTime ? new Date(payload.systemTime).toLocaleString("zh-CN", { hour12: false }) : "--"} icon={<Pulse size={24} />} />
        <MetricCard label="服务运行时长" value={formatDuration(payload?.uptimeSeconds)} icon={<Lightning size={24} />} tone="green" />
        <MetricCard label="当前进程" value={`${payload?.process?.name || "mgtv-danmaku"} #${payload?.process?.pid || "-"}`} icon={<Database size={24} />} tone="blue" />
        <MetricCard label="健康状态" value={payload?.health?.status === "ok" ? "正常" : payload?.health?.status || "未知"} icon={<ShieldCheck size={24} />} tone={payload?.health?.status === "error" ? "red" : "green"} />
      </div>
      <div className="grid grid-cols-4 gap-4 max-2xl:grid-cols-2 max-lg:grid-cols-1">
        <Card title="CPU"><BigMetric value={payload?.cpu?.loadPercent == null ? "--" : `${Math.round(payload.cpu.loadPercent)}%`} detail={`核心 ${payload?.cpu?.count || "-"} · Load ${(payload?.cpu?.loadAverage || []).map((n) => n.toFixed(2)).join(" / ") || "-"}`} /></Card>
        <Card title="内存"><BigMetric value={payload?.memory?.totalBytes ? `${Math.round(((payload.memory.usedBytes || 0) / payload.memory.totalBytes) * 100)}%` : formatBytes(payload?.memory?.processRssBytes)} detail={`进程 RSS ${formatBytes(payload?.memory?.processRssBytes)}`} /></Card>
        <Card title="网络"><BigMetric value={payload?.network?.available ? formatBytes((payload.network.rxBytes || 0) + (payload.network.txBytes || 0)) : "不可用"} detail={`入 ${formatBytes(payload?.network?.rxBytes)} · 出 ${formatBytes(payload?.network?.txBytes)}`} /></Card>
        <Card title="磁盘"><BigMetric value={formatBytes(payload?.disk?.data?.freeBytes)} detail={`录制目录可用 ${formatBytes(payload?.disk?.recordings?.freeBytes)}`} /></Card>
        <Card title="服务运行状态" className="col-span-2 max-lg:col-span-1">
          <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
            {Object.entries(payload?.services || {}).map(([name, service]) => (
              <div key={name} className="flex justify-between rounded-2xl border border-white/10 bg-black/20 p-4 text-sm">
                <span className="text-ops-muted">{name}</span>
                <strong>{String(service.status || "unknown")}</strong>
              </div>
            ))}
          </div>
        </Card>
        <Card title="最近告警" className="col-span-2 max-lg:col-span-1">
          <p className="text-sm leading-7 text-ops-muted">错误数：{payload?.health?.recentErrorCount || 0}。后续将接入 alerts API 和 15 分钟趋势。</p>
        </Card>
      </div>
    </section>
  );
}

function BigMetric({ value, detail }: { value: string; detail: string }) {
  return (
    <div>
      <strong className="block font-mono text-5xl font-black tracking-[-0.06em]">{value}</strong>
      <p className="mt-3 text-sm text-ops-muted">{detail}</p>
    </div>
  );
}

function SystemLogsPage({ initialLogs }: { initialLogs: SystemLogEvent[] }) {
  const logs = useQuery({ queryKey: ["system-logs"], queryFn: () => getSystemLogs(160), initialData: { events: initialLogs }, refetchInterval: 10_000 });
  const items = logs.data.events || logs.data.items || [];
  const selected = items[0];
  return (
    <section>
      <PageHeading kicker="System Logs" title="系统日志" description="按时间查看系统运行日志，支持搜索、过滤、导出和排障摘要。" />
      <div className="mb-4 grid grid-cols-[minmax(260px,1fr)_140px_160px_auto] gap-3 rounded-3xl border border-white/10 bg-white/[0.04] p-4 max-lg:grid-cols-1">
        <input className="rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm outline-none" placeholder="搜索错误、场次 ID、关键词…" />
        <select className="rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm"><option>全部级别</option><option>INFO</option><option>WARN</option><option>ERROR</option></select>
        <select className="rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm"><option>全部来源</option></select>
        <button className="rounded-xl bg-blue-500 px-4 py-3 text-sm font-black text-white" type="button">导出日志</button>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-4 max-xl:grid-cols-1">
        <Card>
          <div className="grid gap-2">
            {items.length ? items.map((event, index) => <LogRow key={`${event.time}-${index}`} event={event} active={index === 0} />) : <div className="grid min-h-80 place-items-center text-ops-muted">暂无日志</div>}
          </div>
        </Card>
        <Card title="日志详情">
          {selected ? (
            <pre className="whitespace-pre-wrap rounded-2xl border border-white/10 bg-black/30 p-4 font-mono text-xs leading-6 text-slate-200">{JSON.stringify(selected, null, 2)}</pre>
          ) : (
            <p className="text-sm text-ops-muted">选择日志查看详情。</p>
          )}
          <div className="mt-5">
            <Timeline items={items.slice(0, 5).map((event) => ({ title: event.summary || "事件", description: `${event.source || "service"} · ${event.time ? new Date(event.time).toLocaleTimeString("zh-CN", { hour12: false }) : ""}`, tone: event.level === "ERROR" ? "warn" : "done" }))} />
          </div>
        </Card>
      </div>
    </section>
  );
}

function LogRow({ event, active }: { event: SystemLogEvent; active?: boolean }) {
  const levelTone = event.level === "ERROR" ? "bg-red-400/15 text-red-200" : event.level === "WARN" ? "bg-yellow-400/15 text-yellow-100" : "bg-blue-400/15 text-blue-100";
  return (
    <article className={`grid grid-cols-[190px_80px_130px_minmax(0,1fr)] items-center gap-3 rounded-2xl border p-3 text-sm max-lg:grid-cols-1 ${active ? "border-orange-400/45 bg-orange-400/10" : "border-white/10 bg-black/20"}`}>
      <time className="font-mono text-xs text-ops-muted">{event.time ? new Date(event.time).toLocaleString("zh-CN", { hour12: false }) : "-"}</time>
      <span className={`rounded-full px-3 py-1 text-center font-mono text-xs font-black ${levelTone}`}>{event.level || "INFO"}</span>
      <span className="text-ops-muted">{event.source || "service"}</span>
      <strong className="truncate">{event.summary || event.detail || "无摘要"}</strong>
    </article>
  );
}
