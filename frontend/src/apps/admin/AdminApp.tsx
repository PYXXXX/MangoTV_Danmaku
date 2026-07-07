import {
  ArrowSquareOut,
  BellRinging,
  BookmarkSimple,
  Broadcast,
  CaretDown,
  ChatCircleDots,
  CheckCircle,
  Clock,
  Database,
  DotsThree,
  DownloadSimple,
  Gauge,
  GlobeHemisphereWest,
  Lightning,
  LinkSimple,
  MonitorPlay,
  PaperPlaneTilt,
  Play,
  Pulse,
  Robot,
  Scissors,
  ShieldCheck,
  Stop,
  UploadSimple,
  VideoCamera,
  WarningCircle
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost, apiUpload, getBootstrap, getSystemMetrics, getSystemLogs, getSystemStatus } from "../../api/client";
import type { ActivityItem, FeishuBindingStatus, MgtvAuthStatus, RecordingTimeline, RoundSession, SourceDetectionResult, SystemLogEvent, SystemLogSummary, SystemLogsResponse, SystemStatus, UpdateStatus } from "../../api/types";
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
  const selectedRoundId = useUiStore((state) => state.selectedRoundId);
  const bootstrap = useBootstrap();
  const publicState = bootstrap.data?.publicState;
  const systemStatus = bootstrap.data?.systemStatus;
  const sessions = publicState?.sessions || [];
  const round = sessions.find((item) => item.id === selectedRoundId) || currentRound(sessions, publicState?.activeSessionId);
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
          {page === "activity" && <ActivityMonitorPage activity={bootstrap.data.activity} status={systemStatus} />}
          {page === "ops" && <OperationsPage rounds={publicState?.sessions || []} activeRound={round} defaultActivity={bootstrap.data.defaults?.activityName || publicState?.defaults?.activity || ""} />}
          {page === "settings" && <SettingsBlueprintPage status={systemStatus} settings={bootstrap.data.settings} />}
          {page === "machine" && <MachineStatusPage initial={systemStatus} />}
          {page === "logs" && <SystemLogsPage initialLogs={bootstrap.data.logs || []} />}
        </>
      )}
    </Shell>
  );
}

type ActivityMonitorForm = {
  name: string;
  url: string;
  monitorEnabled: boolean;
  autoDetectSource: boolean;
  autoRecordVideo: boolean;
  autoRecordDanmaku: boolean;
  feishuNotify: boolean;
  pollSeconds: number;
  preferredQuality: string;
};

function ActivityMonitorPage({ activity, status }: { activity?: ActivityItem | null; status?: SystemStatus }) {
  const queryClient = useQueryClient();
  const monitor = status?.monitor;
  const config = monitor?.config || {};
  const state = monitor?.state || {};
  const activityId = activity?.id || "default";
  const serverForm = useMemo<ActivityMonitorForm>(() => ({
    name: activity?.name || config.activity || "歌手 2026",
    url: activity?.url || config.url || "",
    monitorEnabled: Boolean(activity?.monitorEnabled || config.enabled),
    autoDetectSource: config.autoDetectSource ?? true,
    autoRecordVideo: config.autoRecordVideo ?? false,
    autoRecordDanmaku: config.autoRecordDanmaku ?? true,
    feishuNotify: config.feishuNotify ?? true,
    pollSeconds: config.pollSeconds || 45,
    preferredQuality: config.preferredQuality || "auto"
  }), [activity?.name, activity?.monitorEnabled, activity?.url, config.activity, config.autoDetectSource, config.autoRecordDanmaku, config.autoRecordVideo, config.enabled, config.feishuNotify, config.pollSeconds, config.preferredQuality, config.url]);
  const [form, setForm] = useState<ActivityMonitorForm>(serverForm);
  const [isDirty, setIsDirty] = useState(false);

  useEffect(() => {
    if (!isDirty) {
      setForm(serverForm);
    }
  }, [isDirty, serverForm]);

  const updateForm = (patch: Partial<ActivityMonitorForm>) => {
    setIsDirty(true);
    setForm((current) => ({ ...current, ...patch }));
  };

  const save = useMutation({
    mutationFn: (next: ActivityMonitorForm) => apiPost("/api/activities", next),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
      setIsDirty(false);
    }
  });
  const detect = useMutation<SourceDetectionResult>({
    mutationFn: () => apiPost<SourceDetectionResult>(`/api/activities/${encodeURIComponent(activityId)}/source/detect`, { url: form.url, quality: form.preferredQuality }),
    onSuccess: async (payload) => {
      const available = normalizeQualityOptions(payload.availableQualities);
      if (available.length && form.preferredQuality !== "auto" && !available.includes(form.preferredQuality)) {
        const detectedQuality = payload.actualQuality && available.includes(payload.actualQuality) ? payload.actualQuality : available[0];
        setForm((current) => ({ ...current, preferredQuality: detectedQuality }));
        setIsDirty(true);
      }
      await queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
    }
  });
  const stop = useMutation({
    mutationFn: () => apiPost(`/api/activities/${encodeURIComponent(activityId)}/monitor/stop`),
    onSuccess: async () => {
      updateForm({ monitorEnabled: false });
      await queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
      setIsDirty(false);
    }
  });
  const saveCurrent = (override: Partial<ActivityMonitorForm> = {}) => {
    const next = { ...form, ...override };
    setIsDirty(true);
    setForm(next);
    save.mutate(next);
  };
  const busy = save.isPending || detect.isPending || stop.isPending;
  const error = save.error || detect.error || stop.error;
  const parsedActivityId = parseMgtvActivityId(form.url);
  const isRecognizedActivity = Boolean(parsedActivityId);
  const statusText = form.monitorEnabled ? "监控中" : "未启用";
  const statusTone = form.monitorEnabled ? "green" : isDirty ? "orange" : "neutral";
  const detectedQualities = useMemo(
    () => normalizeQualityOptions([
      ...(state.availableQualities || []),
      ...(detect.data?.availableQualities || []),
      state.quality || "",
      detect.data?.actualQuality || "",
      detect.data?.quality || "",
      form.preferredQuality === "auto" ? "" : form.preferredQuality
    ]),
    [detect.data?.actualQuality, detect.data?.availableQualities, detect.data?.quality, form.preferredQuality, state.availableQualities, state.quality]
  );
  const qualityOptions = useMemo(() => {
    const fetched = detectedQualities.length ? detectedQualities : ["1080P", "720P", "540P"];
    return ["auto", ...fetched.filter((item) => item !== "auto")];
  }, [detectedQualities]);
  const availableQualityText = detectedQualities.length ? detectedQualities.join(" / ") : "待检测";
  const recentEvents = [
    {
      time: formatShortTime(state.lastCheckAt),
      text: state.lastCheckAt ? "完成一次直播状态检测" : "等待第一次检测",
      tone: state.lastError ? "red" : "blue"
    },
    {
      time: parsedActivityId || "-",
      text: parsedActivityId ? `已识别活动 ID：${parsedActivityId}` : "活动链接待识别",
      tone: parsedActivityId ? "green" : "neutral"
    },
    {
      time: form.feishuNotify ? "ON" : "OFF",
      text: form.feishuNotify ? "飞书通知会随状态变化推送" : "飞书通知已关闭",
      tone: form.feishuNotify ? "green" : "neutral"
    }
  ];
  return (
    <section className="activity-monitor-page">
      <div className="mb-6 flex items-start justify-between gap-6 max-lg:flex-col">
        <div>
          <p className="mb-3 font-mono text-xs font-black uppercase tracking-[0.18em] text-ops-orange">Activity Monitor</p>
          <h2 className="text-4xl font-black tracking-[-0.06em] max-sm:text-3xl">活动监控</h2>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-ops-muted">
            配置活动信息与自动化策略，系统会监控开播、解析直播源，并按策略启动录制、弹幕采集和飞书通知。
          </p>
        </div>
        <button
          type="button"
          className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-blue-300/25 bg-blue-400/10 px-5 text-sm font-black text-blue-100 transition hover:border-blue-300/45 hover:bg-blue-400/15 disabled:opacity-60"
          disabled={busy || !form.url.trim()}
          onClick={() => detect.mutate()}
        >
          <Broadcast size={18} weight="bold" />
          立即检测一次
        </button>
      </div>

      <div className="grid items-start grid-cols-[minmax(390px,1.08fr)_minmax(390px,1fr)_minmax(340px,.92fr)] gap-5 max-2xl:grid-cols-[minmax(0,1fr)_minmax(340px,.9fr)] max-xl:grid-cols-1">
        <div className="grid content-start gap-5">
          <Card
            title="活动信息"
            action={<StatusBadge tone={statusTone}>{isDirty ? "有未保存修改" : statusText}</StatusBadge>}
            className="min-h-[330px]"
          >
            <div className="grid gap-5">
              <Field label="活动名称">
                <input className="ops-input min-h-[3.25rem]" value={form.name} onChange={(event) => updateForm({ name: event.target.value })} />
              </Field>
              <Field label="活动链接（官方活动页或直播页）">
                <div className="flex gap-2 max-sm:flex-col">
                  <input
                    className="ops-input min-h-[3.25rem]"
                    value={form.url}
                    onChange={(event) => updateForm({ url: event.target.value })}
                    placeholder="https://www.mgtv.com/z/1001668.html"
                  />
                  <a
                    className="grid size-[3.25rem] shrink-0 place-items-center rounded-2xl border border-white/10 bg-white/[0.04] text-slate-200 transition hover:border-orange-300/35 hover:text-ops-gold max-sm:size-auto max-sm:min-h-12"
                    href={form.url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    aria-label="打开活动链接"
                  >
                    <ArrowSquareOut size={20} />
                  </a>
                </div>
              </Field>
              <div className={`rounded-2xl border px-4 py-3 text-sm ${isRecognizedActivity ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-100" : "border-white/10 bg-black/20 text-ops-muted"}`}>
                <span className="inline-flex items-center gap-2 font-bold">
                  {isRecognizedActivity ? <CheckCircle size={18} weight="fill" /> : <WarningCircle size={18} />}
                  {isRecognizedActivity ? "已识别为官方活动页" : "未识别到标准活动页"}
                </span>
                <span className="mt-1 block text-xs opacity-80">
                  {isRecognizedActivity ? `活动 ID：${parsedActivityId}。直播开始后会自动解析机位与直播源。` : "请填写 mgtv.com/z/{活动ID}.html，或使用直播开始后的跳转链接。"}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                <InfoPill label="活动 ID" value={parsedActivityId || "待识别"} />
                <InfoPill label="状态" value={form.monitorEnabled ? "监控策略已启用" : "未开始监控"} />
              </div>
              <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                <button type="button" className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm font-black text-slate-100 transition hover:border-white/20 hover:bg-white/[0.07]" disabled={busy} onClick={() => saveCurrent()}>
                  保存活动
                </button>
                <button type="button" className="orange-glow rounded-2xl bg-ops-orange px-4 py-3 text-sm font-black text-[#1b0d03] transition hover:brightness-110 disabled:opacity-60" disabled={busy} onClick={() => saveCurrent({ monitorEnabled: true })}>
                  保存并监控
                </button>
              </div>
              {error && <p className="rounded-2xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100">{String((error as Error).message || error)}</p>}
            </div>
          </Card>

          <Card title="直播源检测" action={<StatusBadge tone={state.quality ? "green" : "neutral"}>{state.quality ? "已检测" : "待检测"}</StatusBadge>}>
            <div className="grid gap-4 text-sm">
              <p className="leading-7 text-ops-muted">
                系统会在开播后自动刷新活动页并解析可录制源。手动检测用于开播前复核配置。
              </p>
              <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                <InfoPill label="检测结果" value={state.lastError ? "检测失败" : state.quality ? "可录制" : "等待开播"} tone={state.lastError ? "red" : state.quality ? "green" : "neutral"} />
                <InfoPill label="可用清晰度" value={availableQualityText} tone={detectedQualities.length ? "green" : "neutral"} />
              </div>
              <button
                type="button"
                className="min-h-12 rounded-2xl border border-white/10 bg-white/[0.04] px-4 text-sm font-black text-slate-100 transition hover:border-blue-300/35 hover:bg-blue-400/10 disabled:opacity-60"
                disabled={busy || !form.url.trim()}
                onClick={() => detect.mutate()}
              >
                检测直播源
              </button>
              <p className="text-xs leading-6 text-ops-muted">建议在开播前或登录芒果 TV 后检测，以确认录制清晰度和权限。</p>
            </div>
          </Card>
        </div>

        <Card title="监控策略" action={<span className="text-xs font-bold text-ops-muted">说明</span>} className="min-h-[520px]">
          <div className="grid gap-2">
            <StrategyToggle
              icon={<Broadcast size={20} />}
              label="监控直播状态"
              description="监控是否开播，开播后按下方策略执行。"
              checked={form.monitorEnabled}
              onChange={(monitorEnabled) => updateForm({ monitorEnabled })}
            />
            <StrategyToggle
              icon={<Gauge size={20} />}
              label="开播后自动检测直播源"
              description="自动刷新活动页，解析机位和可录制播放源。"
              checked={form.autoDetectSource}
              onChange={(autoDetectSource) => updateForm({ autoDetectSource })}
            />
            <StrategyToggle
              icon={<VideoCamera size={20} />}
              label="检测成功后录制视频"
              description="需要 ffmpeg 和可直录 m3u8，1080P/VIP 依赖登录态。"
              checked={form.autoRecordVideo}
              onChange={(autoRecordVideo) => updateForm({ autoRecordVideo })}
            >
              <div className="mt-3 grid grid-cols-[1fr_1fr] gap-3 max-sm:grid-cols-1">
                <Field label="清晰度">
                  <select className="ops-input" value={form.preferredQuality} onChange={(event) => updateForm({ preferredQuality: event.target.value })}>
                    {qualityOptions.map((quality) => (
                      <option key={quality} value={quality}>{qualityLabel(quality)}</option>
                    ))}
                  </select>
                  <span className="text-xs leading-5 text-ops-subtle">
                    {detectedQualities.length ? `已从直播源检测到：${detectedQualities.join(" / ")}` : "检测直播源后会自动更新可选清晰度。"}
                  </span>
                </Field>
                <Field label="检测间隔（秒）">
                  <input className="ops-input" type="number" min={10} max={3600} value={form.pollSeconds} onChange={(event) => updateForm({ pollSeconds: Number(event.target.value) })} />
                </Field>
              </div>
            </StrategyToggle>
            <StrategyToggle
              icon={<ChatCircleDots size={20} />}
              label="检测成功后录制弹幕"
              description="保存完整原始弹幕，供实时分析和录制后切片复用。"
              checked={form.autoRecordDanmaku}
              onChange={(autoRecordDanmaku) => updateForm({ autoRecordDanmaku })}
            />
            <StrategyToggle
              icon={<BellRinging size={20} />}
              label="开播自动通知飞书"
              description="开播、录制异常、发布结果等事件推送到飞书卡片。"
              checked={form.feishuNotify}
              onChange={(feishuNotify) => updateForm({ feishuNotify })}
            />
          </div>
          <div className="mt-6 grid grid-cols-2 gap-3 max-sm:grid-cols-1">
            <button type="button" className="orange-glow inline-flex min-h-[3.25rem] items-center justify-center gap-2 rounded-2xl bg-ops-orange px-5 text-sm font-black text-[#1b0d03] transition hover:brightness-110 disabled:opacity-60" disabled={busy} onClick={() => saveCurrent({ monitorEnabled: true })}>
              <Play size={18} weight="fill" />
              开始监控
            </button>
            <button type="button" className="inline-flex min-h-[3.25rem] items-center justify-center gap-2 rounded-2xl border border-red-400/35 bg-red-400/15 px-5 text-sm font-black text-red-100 transition hover:bg-red-400/20 disabled:opacity-60" disabled={busy} onClick={() => stop.mutate()}>
              <Stop size={18} weight="fill" />
              停止监控
            </button>
          </div>
          {isDirty && <p className="mt-4 rounded-2xl border border-orange-400/25 bg-orange-400/10 px-4 py-3 text-xs leading-6 text-ops-gold">当前策略有未保存修改。保存后才会应用到后台监控任务。</p>}
        </Card>

        <div className="grid content-start gap-5 max-2xl:col-span-2 max-2xl:grid-cols-3 max-xl:col-span-1 max-xl:grid-cols-1">
          <Card title="运行状态" action={<a className="text-xs font-bold text-blue-200" href="/api/system/logs" target="_blank" rel="noreferrer">查看详情</a>}>
            <Timeline
              items={[
                { title: form.monitorEnabled ? "等待开播" : "监控未启用", description: state.lastCheckAt || "系统已准备监控活动页与直播状态", tone: form.monitorEnabled ? "active" : "idle" },
                { title: isRecognizedActivity ? "已解析活动页" : "活动页待识别", description: isRecognizedActivity ? `识别活动 ID：${parsedActivityId}` : "请先保存标准活动链接", tone: isRecognizedActivity ? "done" : "idle" },
                { title: "直播源待检测", description: state.lastError || state.quality || "等待开播或手动检测", tone: state.lastError ? "warn" : state.quality ? "done" : "idle" }
              ]}
            />
            <div className="mt-5 grid grid-cols-4 gap-2 rounded-2xl border border-white/10 bg-black/20 p-3 text-xs max-sm:grid-cols-2">
              <InfoPill label="当前状态" value={form.monitorEnabled ? "监控中" : "待命"} tone={form.monitorEnabled ? "green" : "neutral"} />
              <InfoPill label="开播时间" value="-" />
              <InfoPill label="当前机位" value={state.quality ? "已解析" : "-"} />
              <InfoPill label="直播源" value={state.quality ? "可录制" : "未检测"} tone={state.quality ? "green" : "neutral"} />
            </div>
          </Card>

          <Card title="飞书通知预览" action={<span className="text-xs font-bold text-blue-200">配置</span>}>
            <div className="rounded-3xl border border-white/10 bg-gradient-to-br from-slate-800/95 to-slate-950/95 p-5 shadow-2xl">
              <div className="mb-4 flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-2xl bg-blue-400/15 text-blue-200">
                  <ChatCircleDots size={22} weight="fill" />
                </span>
                <div>
                  <strong className="block text-sm">直播运营助手</strong>
                  <span className="text-xs text-ops-muted">BOT · {formatShortTime(new Date().toISOString())}</span>
                </div>
              </div>
              <strong className="block text-lg text-white">监控已启动</strong>
              <dl className="mt-3 grid gap-2 text-sm text-slate-200">
                <div className="flex justify-between gap-4"><dt className="text-ops-muted">活动</dt><dd>{form.name || "待配置"}</dd></div>
                <div className="flex justify-between gap-4"><dt className="text-ops-muted">活动 ID</dt><dd>{parsedActivityId || "-"}</dd></div>
                <div className="flex justify-between gap-4"><dt className="text-ops-muted">状态</dt><dd>{form.monitorEnabled ? "等待开播" : "未启用"}</dd></div>
              </dl>
              <p className="mt-4 border-t border-white/10 pt-3 text-xs text-ops-muted">开播时推送通知与关键数据。仅为预览效果。</p>
            </div>
          </Card>

          <Card title="采集统计（今日）">
            <div className="grid grid-cols-2 gap-3 max-2xl:grid-cols-1 max-sm:grid-cols-1">
              <CollectionMetric icon={<VideoCamera size={20} weight="fill" />} label="视频录制" value={form.autoRecordVideo ? "待启动" : "未启用"} detail="文件大小 0 B" tone="orange" />
              <CollectionMetric icon={<ChatCircleDots size={20} weight="fill" />} label="弹幕采集" value={`${formatCount(activity?.messageCount)} 条`} detail="有效弹幕 0 条" tone="blue" />
            </div>
          </Card>
        </div>

        <Card title="最近事件" className="col-span-2 max-2xl:col-span-2 max-xl:col-span-1" action={<span className="text-xs font-bold text-blue-200">查看全部</span>}>
          <div className="grid gap-3">
            {recentEvents.map((event) => (
              <div key={`${event.text}-${event.time}`} className="grid grid-cols-[90px_14px_minmax(0,1fr)] items-center gap-3 text-sm max-sm:grid-cols-[64px_12px_minmax(0,1fr)]">
                <span className="font-mono text-xs text-ops-muted">{event.time}</span>
                <span className={`size-2.5 rounded-full ${event.tone === "green" ? "bg-emerald-400" : event.tone === "red" ? "bg-red-400" : event.tone === "blue" ? "bg-blue-400" : "bg-white/25"}`} />
                <span className="truncate text-slate-200">{event.text}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </section>
  );
}

function parseMgtvActivityId(url = "") {
  const match = url.match(/mgtv\.com\/z\/(\d+)(?:\.html|\/|\?|#|$)/i);
  return match?.[1] || "";
}

function normalizeQualityOptions(values?: Array<string | undefined | null>) {
  const result: string[] = [];
  for (const value of values || []) {
    const text = String(value || "").trim();
    if (!text || text === "auto" || result.includes(text)) continue;
    result.push(text);
  }
  return result;
}

function qualityLabel(value: string) {
  return value === "auto" ? "自动最高可用" : value;
}

function formatShortTime(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function InfoPill({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "green" | "red" | "neutral" }) {
  const toneClass = tone === "green" ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-100" : tone === "red" ? "border-red-400/25 bg-red-400/10 text-red-100" : "border-white/10 bg-black/20 text-slate-100";
  return (
    <div className={`rounded-2xl border px-3 py-3 ${toneClass}`}>
      <span className="block text-[11px] font-bold text-ops-muted">{label}</span>
      <strong className="mt-1 block truncate text-sm">{value || "-"}</strong>
    </div>
  );
}

function StrategyToggle({ icon, label, description, checked, onChange, children }: { icon: React.ReactNode; label: string; description: string; checked: boolean; onChange: (value: boolean) => void; children?: React.ReactNode }) {
  return (
    <div className="border-b border-white/[0.07] py-4 last:border-b-0">
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)} className="grid w-full grid-cols-[44px_minmax(0,1fr)_52px] items-center gap-4 text-left">
        <span className="grid size-11 place-items-center rounded-2xl bg-white/[0.06] text-ops-muted">
          {icon}
        </span>
        <span>
          <strong className="block text-sm text-white">{label}</strong>
          <span className="mt-1 block text-xs leading-5 text-ops-muted">{description}</span>
        </span>
        <span className={`h-8 w-14 rounded-full p-1 transition ${checked ? "bg-ops-orange shadow-[0_0_24px_rgba(255,134,31,.26)]" : "bg-white/10"}`}>
          <i className={`block size-6 rounded-full bg-white shadow-sm transition-transform ${checked ? "translate-x-6" : ""}`} />
        </span>
      </button>
      {children && <div className="pl-[60px] max-sm:pl-0">{children}</div>}
    </div>
  );
}

function CollectionMetric({ icon, label, value, detail, tone }: { icon: React.ReactNode; label: string; value: string; detail: string; tone: "orange" | "blue" }) {
  const color = tone === "orange" ? "text-ops-orange bg-orange-400/10" : "text-blue-200 bg-blue-400/10";
  return (
    <div className="rounded-3xl border border-white/10 bg-black/20 p-4">
      <span className={`mb-4 grid size-10 place-items-center rounded-2xl ${color}`}>{icon}</span>
      <span className="block text-sm text-ops-muted">{label}</span>
      <strong className="mt-2 block text-2xl tracking-[-0.04em]">{value}</strong>
      <span className="mt-3 block border-t border-white/10 pt-3 text-xs text-ops-muted">{detail}</span>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-2 text-sm text-ops-muted">
      {label}
      {children}
    </label>
  );
}

function OperationsPage({ rounds, activeRound, defaultActivity }: { rounds: RoundSession[]; activeRound: RoundSession | null; defaultActivity: string }) {
  const queryClient = useQueryClient();
  const resultType = useUiStore((state) => state.resultType);
  const setResultType = useUiStore((state) => state.setResultType);
  const selectedRoundId = useUiStore((state) => state.selectedRoundId);
  const setSelectedRoundId = useUiStore((state) => state.setSelectedRoundId);
  const result = selectedResult(activeRound, resultType);
  const rows = rankingRows(activeRound, result.data);
  const total = rows.reduce((sum, row) => sum + row.votes, 0);
  const reviewCount = Number(result.data.reviewCount || activeRound?.reviewCount || 0);
  const [roundForm, setRoundForm] = useState({
    activity: defaultActivity || activeRound?.activity || "歌手 2026",
    name: "",
    url: ""
  });
  const [opsMode, setOpsMode] = useState<"realtime" | "post">("realtime");
  const [renameValue, setRenameValue] = useState("");
  const [selectedRecordingId, setSelectedRecordingId] = useState(activeRound?.id || rounds.find((item) => item.recording)?.id || "");
  const [markerForm, setMarkerForm] = useState({ label: "", atSeconds: 0 });
  const [clipForm, setClipForm] = useState({ label: "", startSeconds: 0, endSeconds: 0 });
  const [pendingDelete, setPendingDelete] = useState<null | { kind: "round"; label: string } | { kind: "activity"; activity: string }>(null);
  const [deleteSyncPublic, setDeleteSyncPublic] = useState(true);
  const [preciseFile, setPreciseFile] = useState<File | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    setRoundForm((current) => ({
      ...current,
      activity: current.activity || defaultActivity || activeRound?.activity || "歌手 2026"
    }));
  }, [defaultActivity, activeRound?.activity]);
  useEffect(() => {
    if (!selectedRecordingId) {
      setSelectedRecordingId(activeRound?.id || rounds.find((item) => item.recording)?.id || "");
    }
  }, [activeRound?.id, rounds, selectedRecordingId]);
  const recordingRound = rounds.find((item) => item.id === selectedRecordingId) || activeRound;
  const recordingTimeline = useQuery<RecordingTimeline>({
    queryKey: ["recording-timeline", recordingRound?.id],
    queryFn: () => apiGet<RecordingTimeline>(`/api/recordings/${encodeURIComponent(recordingRound?.id || "")}/timeline`),
    enabled: Boolean(recordingRound?.id && recordingRound?.recording),
    refetchInterval: recordingRound?.recording?.status === "recording" ? 10_000 : false
  });
  const startRound = useMutation({
    mutationFn: () => apiPost("/api/rounds/start", {
      activity: roundForm.activity,
      name: roundForm.name || `第 ${rounds.length + 1} 轮`,
      url: roundForm.url || undefined,
      recordVideo: false,
      collectDanmaku: true
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const endRound = useMutation({
    mutationFn: () => apiPost("/api/rounds/" + encodeURIComponent(activeRound?.id || "") + "/end", { publish: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const publish = useMutation({
    mutationFn: () => apiPost("/api/rounds/" + encodeURIComponent(activeRound?.id || "") + "/publish", { resultKind: result.type }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const pushFeishu = useMutation({
    mutationFn: () => apiPost("/api/feishu/push-card"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const detectSource = useMutation({
    mutationFn: () => apiPost("/api/mgtv/source/check", { url: activeRound?.pageUrl || roundForm.url || undefined }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const renameRound = useMutation({
    mutationFn: () => apiPatch("/api/rounds/" + encodeURIComponent(activeRound?.id || ""), { name: renameValue }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const deleteRound = useMutation({
    mutationFn: ({ publish }: { publish: boolean }) => apiDelete(`/api/rounds/${encodeURIComponent(activeRound?.id || "")}?publish=${publish ? "1" : "0"}`),
    onSuccess: () => {
      setPendingDelete(null);
      setSelectedRoundId(null);
      queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
    }
  });
  const deleteActivity = useMutation({
    mutationFn: ({ activity, publish }: { activity: string; publish: boolean }) => apiDelete(`/api/activities/${encodeURIComponent(activity)}?publish=${publish ? "1" : "0"}`),
    onSuccess: () => {
      setPendingDelete(null);
      setSelectedRoundId(null);
      queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
    }
  });
  const addMarker = useMutation({
    mutationFn: () => apiPost(`/api/rounds/${encodeURIComponent(recordingRound?.id || "")}/recording/markers`, markerForm),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recording-timeline", recordingRound?.id] });
      queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
    }
  });
  const createClip = useMutation({
    mutationFn: () => apiPost(`/api/rounds/${encodeURIComponent(recordingRound?.id || "")}/recording/clips`, clipForm),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recording-timeline", recordingRound?.id] });
      queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
    }
  });
  const createAnalysisRound = useMutation({
    mutationFn: (clipId: string) => apiPost(`/api/rounds/${encodeURIComponent(recordingRound?.id || "")}/recording/clips/${encodeURIComponent(clipId)}/analysis-round`, { name: clipForm.label || "片段分析" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const uploadPrecise = useMutation({
    mutationFn: () => {
      if (!activeRound?.id || !preciseFile) throw new Error("请先选择已结束场次和精确结果文件");
      const form = new FormData();
      form.append("file", preciseFile);
      return apiUpload(`/api/rounds/${encodeURIComponent(activeRound.id)}/precise-result`, form);
    },
    onSuccess: () => {
      setPreciseFile(null);
      setResultType("precise");
      queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
    }
  });
  const deleteCurrentRound = () => {
    if (!activeRound) return;
    setDeleteSyncPublic(true);
    setPendingDelete({ kind: "round", label: roundName(activeRound) });
  };
  const deleteCurrentActivity = () => {
    const activity = activeRound?.activity || roundForm.activity || defaultActivity;
    if (!activity) return;
    setDeleteSyncPublic(true);
    setPendingDelete({ kind: "activity", activity });
  };
  const confirmDelete = () => {
    if (!pendingDelete) return;
    if (pendingDelete.kind === "round") {
      deleteRound.mutate({ publish: deleteSyncPublic });
      return;
    }
    deleteActivity.mutate({ activity: pendingDelete.activity, publish: deleteSyncPublic });
  };
  const copyPublicLink = async () => {
    const publicUrl = new URL("/studio/public", window.location.origin).toString();
    await navigator.clipboard?.writeText(publicUrl);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };
  const operationError = startRound.error || endRound.error || publish.error || pushFeishu.error || detectSource.error || renameRound.error || deleteRound.error || deleteActivity.error || addMarker.error || createClip.error || createAnalysisRound.error || uploadPrecise.error || recordingTimeline.error;
  const timeline = recordingTimeline.data;
  const density = timeline?.danmakuDensity || [];
  const maxDensity = Math.max(1, ...density.map((item) => item.count));
  const recording = timeline?.recording || recordingRound?.recording || null;
  const sortedRounds = [...rounds].sort((a, b) => String(b.startedAt || b.endedAt || "").localeCompare(String(a.startedAt || a.endedAt || "")));
  const roundRows = sortedRounds.slice(0, 6);
  const activeDurationSeconds = activeRound?.startedAt ? Math.max(0, (Date.now() - new Date(activeRound.startedAt).getTime()) / 1000) : 0;
  const recordingDuration = Number(timeline?.durationSeconds || recording?.durationSeconds || activeDurationSeconds || 0);
  const markers = timeline?.markers || recording?.markers || [];
  const clips = timeline?.clips || recording?.clips || [];
  const firstCandidate = rows[0];
  const activityLabel = activeRound?.activity || defaultActivity || roundForm.activity || "歌手 2026";
  const activeRoundLabel = activeRound ? roundName(activeRound) : "等待场次";
  const activeQuality = recording?.status === "recording" ? "录制中" : activeRound?.pageUrl ? "已解析" : "待检测";
  const activePageUrl = activeRound?.pageUrl || roundForm.url || "等待识别";
  return (
    <section className="ops-cockpit grid gap-4">
      <div className="grid grid-cols-[290px_minmax(0,1fr)_360px] gap-4 max-2xl:grid-cols-[300px_minmax(0,1fr)] max-xl:grid-cols-1">
        <OpsPanel
          title="当前直播状态"
          action={<span className={`rounded-full px-3 py-1 text-xs font-black ${activeRound?.status === "running" ? "bg-emerald-400/12 text-emerald-200" : "bg-white/[0.06] text-ops-muted"}`}>{activeRound?.status === "running" ? "监控中" : "等待场次"}</span>}
          className="min-h-[520px]"
        >
          <div className="rounded-3xl border border-white/10 bg-black/25 p-4">
            <OpsStatusItem
              icon={<CheckCircle size={22} weight="fill" />}
              tone={activeRound ? "green" : "idle"}
              title="活动页已识别"
              detail={activePageUrl}
              meta={formatShortTime(activeRound?.startedAt)}
            />
            <OpsStatusItem
              icon={<CheckCircle size={22} weight="fill" />}
              tone={activeRound?.pageUrl ? "green" : "idle"}
              title="直播源已解析"
              detail={activeRound?.pageUrl ? "机位已解析，可开始采集" : "等待活动监控解析"}
              meta={activeRound?.pageUrl ? "已就绪" : "-"}
            />
            <OpsStatusItem
              icon={<VideoCamera size={22} weight="fill" />}
              tone={recording?.status === "recording" ? "orange" : "idle"}
              title={recording?.status === "recording" ? "视频录制中" : "视频未录制"}
              detail="录制时长"
              meta={recording?.status === "recording" ? formatClockDuration(recordingDuration) : "-"}
              emph={recording?.status === "recording" ? formatClockDuration(recordingDuration) : undefined}
            />
            <OpsStatusItem
              icon={<ChatCircleDots size={22} weight="fill" />}
              tone={activeRound?.status === "running" ? "blue" : "idle"}
              title={activeRound?.status === "running" ? "弹幕采集中" : "弹幕待命"}
              detail="已采集弹幕"
              meta={`${formatCount(activeRound?.messageCount)} 条`}
              emph={activeRound?.status === "running" ? `${formatCount(activeRound?.messageCount)} 条` : undefined}
            />
            <OpsStatusItem
              icon={<MonitorPlay size={22} weight="fill" />}
              tone={activeRound?.pageUrl ? "purple" : "idle"}
              title="当前清晰度"
              detail={activeQuality}
              meta={activeRound?.pageUrl ? activeQuality : "-"}
              emph={activeRound?.pageUrl ? activeQuality : undefined}
              last
            />
          </div>
          <button
            type="button"
            className="mt-4 inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl border border-blue-300/25 bg-blue-400/10 px-4 text-sm font-black text-blue-100 transition hover:bg-blue-400/15 disabled:opacity-60"
            disabled={detectSource.isPending}
            onClick={() => detectSource.mutate()}
          >
            <Broadcast size={18} />
            立即检测一次
          </button>
        </OpsPanel>

        <OpsPanel title="场次与切片" className="min-h-[520px]">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-4">
            <div className="flex gap-8">
              <button type="button" onClick={() => setOpsMode("realtime")} className={`border-b-2 pb-2 text-sm font-black ${opsMode === "realtime" ? "border-ops-orange text-white" : "border-transparent text-ops-muted"}`}>实时运营</button>
              <button type="button" onClick={() => setOpsMode("post")} className={`border-b-2 pb-2 text-sm font-black ${opsMode === "post" ? "border-ops-orange text-white" : "border-transparent text-ops-muted"}`}>录制后处理</button>
            </div>
            <div className="grid grid-cols-2 rounded-2xl border border-white/10 bg-black/25 p-1">
              <button className={`rounded-xl px-4 py-2 text-xs font-black ${result.type === "rough" ? "bg-orange-400/15 text-ops-gold" : "text-ops-muted"}`} onClick={() => setResultType("rough")} type="button">粗略结果</button>
              <button className={`rounded-xl px-4 py-2 text-xs font-black ${result.type === "precise" ? "bg-orange-400/15 text-ops-gold" : "text-ops-muted"}`} onClick={() => setResultType("precise")} type="button" disabled={!activeRound?.results?.precise}>精确结果</button>
            </div>
          </div>

          <div className="mb-5 grid grid-cols-[minmax(0,1fr)_230px] gap-5 max-lg:grid-cols-1">
            <Field label="场次名称">
              <input
                className="ops-input min-h-[3.25rem]"
                value={roundForm.name}
                onChange={(event) => setRoundForm({ ...roundForm, name: event.target.value })}
                placeholder={`例如：第 ${rounds.length + 1} 轮 选歌`}
                maxLength={20}
              />
              <span className="justify-self-end font-mono text-xs text-ops-subtle">{roundForm.name.length}/20</span>
            </Field>
            <div className="grid gap-3">
              <button type="button" className="orange-glow inline-flex min-h-[3.25rem] items-center justify-center gap-2 rounded-2xl bg-ops-orange px-5 text-sm font-black text-[#1b0d03] transition hover:brightness-110 disabled:opacity-60" onClick={() => startRound.mutate()} disabled={startRound.isPending}>
                <Play size={18} weight="fill" />
                开始新一轮
              </button>
              <button type="button" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-orange-400/35 bg-orange-400/10 px-5 text-sm font-black text-ops-gold transition hover:bg-orange-400/15 disabled:opacity-60" onClick={() => endRound.mutate()} disabled={!activeRound || activeRound.status !== "running" || endRound.isPending}>
                <UploadSimple size={18} weight="bold" />
                结束并发布粗略结果
              </button>
            </div>
          </div>

          <div className="overflow-x-auto rounded-2xl border border-white/10 bg-black/20">
            <table className="w-full min-w-[620px] text-left text-sm">
              <thead className="text-xs text-ops-muted">
                <tr className="border-b border-white/10">
                  <th className="px-4 py-3 font-bold">场次</th>
                  <th className="px-4 py-3 font-bold">时间范围</th>
                  <th className="px-4 py-3 font-bold">状态</th>
                  <th className="px-4 py-3 font-bold">弹幕数</th>
                  <th className="px-4 py-3 text-right font-bold">操作</th>
                </tr>
              </thead>
              <tbody>
                {roundRows.map((round) => (
                  <tr key={round.id} className={`border-b border-white/[0.06] last:border-0 ${round.id === activeRound?.id || round.id === selectedRoundId ? "bg-orange-400/[0.055]" : ""}`}>
                    <td className="px-4 py-3">
                      <button type="button" className="text-left" onClick={() => setSelectedRoundId(round.id)}>
                        <strong className="block text-slate-100">{roundName(round)}</strong>
                        <span className="mt-1 block text-xs text-ops-muted">{round.activity || "未分类活动"}</span>
                      </button>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-ops-muted">{roundDisplayRange(round)}</td>
                    <td className="px-4 py-3"><RoundStatusPill round={round} /></td>
                    <td className="px-4 py-3 font-mono text-slate-200">{formatCount(round.messageCount)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <a className="ops-mini-button" href={`/api/rounds/${encodeURIComponent(round.id)}/result.png?result=${round.results?.precise ? "precise" : "rough"}`}>导出 PNG</a>
                        <a className="ops-mini-button" href={`/api/rounds/${encodeURIComponent(round.id)}.jsonl`}>导出弹幕</a>
                        <button type="button" className="ops-mini-button" onClick={() => setSelectedRoundId(round.id)}>更多</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!roundRows.length && (
                  <tr>
                    <td className="px-4 py-12 text-center text-ops-muted" colSpan={5}>暂无场次。输入名称后可开始新一轮。</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-ops-muted">
            <span className="inline-flex items-center gap-2"><Clock size={15} /> 提示：结束场次后可回看录屏、上传精确结果，并发布公开页。</span>
            <div className="flex flex-wrap gap-2">
              <input className="max-w-56 rounded-xl border border-white/10 bg-black/25 px-3 py-2 text-xs text-slate-100" type="file" accept=".json,.xml,application/json,text/xml,application/xml" onChange={(event) => setPreciseFile(event.target.files?.[0] || null)} />
              <button type="button" className="ops-mini-button border-red-300/25 text-red-100" disabled={!activeRound || activeRound.status === "running" || !preciseFile || uploadPrecise.isPending} onClick={() => uploadPrecise.mutate()}>上传精确结果</button>
              <button type="button" className="ops-mini-button border-red-300/25 text-red-100" disabled={!activeRound || activeRound.status === "running" || deleteRound.isPending} onClick={deleteCurrentRound}>删除场次</button>
            </div>
          </div>
        </OpsPanel>

        <OpsPanel
          title="飞书协同与发布"
          action={<span className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-black text-emerald-200"><span className="size-2 rounded-full bg-emerald-400" />已连接</span>}
          className="min-h-[520px] max-2xl:col-span-2 max-xl:col-span-1"
        >
          <p className="mb-3 text-xs text-ops-muted">飞书卡片预览（实时更新）</p>
          <div className="rounded-3xl border border-white/10 bg-[#111923] p-4 shadow-2xl">
            <div className="mb-3 flex items-center gap-3">
              <span className="grid size-9 place-items-center rounded-full bg-blue-400/20 text-blue-200"><Robot size={21} weight="fill" /></span>
              <div>
                <strong className="block text-sm">直播运营助手 <span className="ml-1 rounded bg-white/10 px-1 text-[10px] text-ops-muted">机器人</span></strong>
                <span className="text-xs text-ops-muted">{formatShortTime(new Date().toISOString())}</span>
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-4">
              <div className="flex items-start justify-between gap-3">
                <strong className="block text-xl tracking-[-0.04em]">{activityLabel}</strong>
                <span className="rounded-lg bg-orange-400/15 px-2 py-1 text-[10px] font-black text-ops-gold">{activeRound?.status === "running" ? "实时运营" : "待同步"}</span>
              </div>
              <div className="mt-1 flex items-center gap-2 text-sm text-ops-muted">
                <span className="truncate">{activeRoundLabel}</span>
                <span>{activeRound?.status === "running" ? "进行中" : "等待场次"}</span>
                <span className="font-mono">{formatClockDuration(activeDurationSeconds)}</span>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 border-y border-white/10 py-3">
                <MiniMetric label="弹幕" value={formatCount(result.data.messageCount || activeRound?.messageCount)} />
                <MiniMetric label="有效计票" value={formatCount(total)} />
                <MiniMetric label="语义待审" value={formatCount(reviewCount)} />
              </div>
              <div className="mt-3 grid grid-cols-[1fr_1fr_1fr_40px] gap-2">
                <button type="button" className="ops-mini-button justify-center px-2" onClick={() => setSelectedRoundId(activeRound?.id || null)}>场次列表</button>
                <button type="button" className="ops-mini-button justify-center px-2" onClick={() => pushFeishu.mutate()} disabled={pushFeishu.isPending}>切换场次</button>
                <a className="ops-mini-button justify-center px-2" href={activeRound ? `/api/rounds/${encodeURIComponent(activeRound.id)}/result.png?result=${result.type}` : "#"}>导出 PNG</a>
                <button type="button" className="ops-mini-button justify-center px-2"><DotsThree size={18} /></button>
              </div>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2">
            {["开播通知", "异常通知（断流/录制失败等）", "场次开始/结束通知", "关键操作回执"].map((label) => (
              <span key={label} className="flex min-w-0 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-2.5 py-2 text-xs text-slate-200">
                <span className="relative inline-flex h-4 w-8 shrink-0 rounded-full bg-ops-orange"><i className="absolute right-1 top-1 size-2 rounded-full bg-white" /></span>
                <span className="truncate">{label}</span>
              </span>
            ))}
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2">
            <button className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-2xl bg-blue-500 px-2 text-xs font-black text-white transition hover:brightness-110 disabled:opacity-60" type="button" disabled={pushFeishu.isPending} onClick={() => pushFeishu.mutate()}>
              <PaperPlaneTilt size={18} weight="fill" />
              同步到飞书
            </button>
            <button className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-2xl bg-emerald-500 px-2 text-xs font-black text-white transition hover:brightness-110 disabled:opacity-60" type="button" disabled={!activeRound || publish.isPending} onClick={() => publish.mutate()}>
              <GlobeHemisphereWest size={18} weight="fill" />
              发布公开页
            </button>
            <button className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-2xl border border-white/10 bg-white/[0.04] px-2 text-xs font-black text-slate-100 transition hover:bg-white/[0.07]" type="button" onClick={copyPublicLink}>
              <LinkSimple size={18} />
              {copied ? "已复制" : "复制公开链接"}
            </button>
          </div>
          <p className="mt-3 truncate text-xs text-ops-muted">公开链接：https://pyxxxx.github.io/MangoTV_Danmaku/</p>
        </OpsPanel>
      </div>

      <OpsPanel title="录制后处理" className="min-h-[430px]">
        <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-5 max-xl:grid-cols-1">
          <div className="grid gap-4">
            <div className="flex flex-wrap items-center gap-4">
              <select className="ops-input max-w-[360px]" value={recordingRound?.id || ""} onChange={(event) => setSelectedRecordingId(event.target.value)}>
                {[...rounds].filter((item) => item.recording).map((item) => (
                  <option key={item.id} value={item.id}>{item.activity || "未分类活动"} / {roundName(item)}</option>
                ))}
                {!rounds.some((item) => item.recording) && <option value="">暂无录制</option>}
              </select>
              <span className="inline-flex items-center gap-2 text-sm text-ops-muted">
                <span className={`size-2 rounded-full ${recording?.status === "recording" ? "bg-emerald-400" : "bg-white/25"}`} />
                {recording?.status === "recording" ? "录制中" : "等待录制"}
              </span>
              <span className="font-mono text-sm text-ops-muted">{formatClockDuration(recordingDuration)}</span>
            </div>
            <div className="grid grid-cols-[280px_minmax(0,1fr)] gap-4 max-lg:grid-cols-1">
              <div className="overflow-hidden rounded-2xl border border-white/10 bg-black/80">
                {recording?.hasVideo && recording.videoUrl ? (
                  <video className="aspect-video w-full bg-black" controls src={recording.videoUrl} />
                ) : (
                  <div className="grid aspect-video place-items-center bg-black text-ops-muted">
                    <Play size={70} weight="fill" className="text-white/35" />
                  </div>
                )}
                <div className="flex items-center gap-3 border-t border-white/10 px-4 py-3 text-xs text-slate-200">
                  <Play size={16} weight="fill" />
                  <span className="size-4 rounded-full bg-white/80" />
                  <span className="font-mono">{formatClockDuration(Math.min(recordingDuration, Number(clipForm.startSeconds || 0)))} / {formatClockDuration(recordingDuration)}</span>
                  <span className="ml-auto">⛶</span>
                </div>
              </div>
              <div className="grid content-center gap-4 rounded-2xl border border-white/10 bg-black/20 p-4">
                <RecordingRuler density={density} maxDensity={maxDensity} markers={markers} clips={clips} durationSeconds={recordingDuration} />
              </div>
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-black/20 p-4">
            <div className="grid grid-cols-2 gap-3">
              <button type="button" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-orange-400/45 bg-orange-400/15 px-4 text-sm font-black text-ops-gold" disabled={!recordingRound?.id || addMarker.isPending} onClick={() => addMarker.mutate()}>
                <BookmarkSimple size={18} weight="bold" />
                添加标记
              </button>
              <button type="button" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-blue-400/45 bg-blue-400/15 px-4 text-sm font-black text-blue-100" disabled={!recordingRound?.id || createClip.isPending} onClick={() => createClip.mutate()}>
                <Scissors size={18} weight="bold" />
                截取片段
              </button>
              <button type="button" className="col-span-2 inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-emerald-400/45 bg-emerald-400/15 px-4 text-sm font-black text-emerald-100" disabled={!clips[0] || createAnalysisRound.isPending} onClick={() => clips[0] && createAnalysisRound.mutate(clips[0].id)}>
                <Gauge size={18} weight="bold" />
                生成分析场次
              </button>
            </div>
            <div className="mt-4 grid gap-3">
              <Field label="当前位置标记">
                <input className="ops-input" value={markerForm.label} onChange={(event) => setMarkerForm({ ...markerForm, label: event.target.value })} placeholder="例如：高能片段 / 主持人口播" />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="截取开始（秒）"><input className="ops-input" type="number" value={clipForm.startSeconds} onChange={(event) => setClipForm({ ...clipForm, startSeconds: Number(event.target.value) })} /></Field>
                <Field label="截取结束（秒）"><input className="ops-input" type="number" value={clipForm.endSeconds} onChange={(event) => setClipForm({ ...clipForm, endSeconds: Number(event.target.value) })} /></Field>
              </div>
              <Field label="片段名称">
                <input className="ops-input" value={clipForm.label} onChange={(event) => setClipForm({ ...clipForm, label: event.target.value })} placeholder="例如：第一段回放" />
              </Field>
            </div>
            <div className="mt-5 flex items-center justify-between">
              <span className="text-sm text-ops-muted">已创影片段（{clips.length}）</span>
              <button className="inline-flex items-center gap-1 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-black text-slate-100" type="button">
                查看全部
                <CaretDown size={14} />
              </button>
            </div>
            <div className="mt-3 grid gap-2">
              {clips.slice(0, 3).map((clip) => (
                <div key={clip.id} className="rounded-2xl border border-white/10 bg-white/[0.035] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm text-slate-100">{clip.label}</span>
                    <span className="rounded-full bg-emerald-400/12 px-3 py-1 text-xs font-black text-emerald-200">已生成场次</span>
                  </div>
                  <span className="mt-1 block font-mono text-xs text-ops-muted">{formatClockDuration(clip.startSeconds)} - {formatClockDuration(clip.endSeconds)}</span>
                </div>
              ))}
              {!clips.length && <p className="rounded-2xl border border-white/10 bg-white/[0.035] px-4 py-5 text-sm text-ops-muted">暂无片段</p>}
            </div>
          </div>
        </div>
        <p className="mt-4 inline-flex items-center gap-2 text-xs leading-6 text-ops-muted">
          <Clock size={15} />
          说明：从录屏中截取片段后，会自动提取对应时间范围的弹幕，生成可分析的场次接入实时精选、飞书同步与发布。
        </p>
      </OpsPanel>

      {operationError && (
        <div className="rounded-2xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100">
          {String((operationError as Error).message || operationError)}
        </div>
      )}
      {pendingDelete && (
        <div className="rounded-3xl border border-red-300/35 bg-[#2a0f0f] p-5">
          <strong className="block text-sm text-red-100">
            确认删除{pendingDelete.kind === "round" ? `场次「${pendingDelete.label}」` : `活动「${pendingDelete.activity}」`}
          </strong>
          <p className="mt-2 text-xs leading-6 text-red-100/75">
            删除后不可在管理台恢复。采集中场次会被服务端拒绝。
          </p>
          <label className="mt-3 flex items-center gap-2 text-xs font-bold text-red-50">
            <input type="checkbox" checked={deleteSyncPublic} onChange={(event) => setDeleteSyncPublic(event.target.checked)} />
            删除后立即同步远端公开页
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-xs font-black text-slate-200" onClick={() => setPendingDelete(null)}>取消</button>
            <button type="button" className="rounded-xl bg-red-500 px-4 py-2 text-xs font-black text-white" disabled={deleteRound.isPending || deleteActivity.isPending} onClick={confirmDelete}>确认删除</button>
          </div>
        </div>
      )}
    </section>
  );
}

function OpsPanel({ title, action, children, className = "" }: { title: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`glass relative min-w-0 overflow-hidden rounded-3xl p-5 ${className}`}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <h3 className="text-xl font-black tracking-[-0.04em]">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function OpsStatusItem({ icon, tone, title, detail, meta, emph, last = false }: { icon: React.ReactNode; tone: "green" | "orange" | "blue" | "purple" | "idle"; title: string; detail: string; meta?: string; emph?: string; last?: boolean }) {
  const toneClass = {
    green: "bg-emerald-400 text-[#062413]",
    orange: "bg-ops-orange text-[#1b0d03]",
    blue: "bg-blue-500 text-white",
    purple: "bg-purple-500 text-white",
    idle: "bg-slate-700 text-slate-300"
  }[tone];
  const lineClass = tone === "idle" ? "bg-white/10" : "bg-gradient-to-b from-ops-orange to-blue-500";
  return (
    <div className="grid grid-cols-[48px_minmax(0,1fr)] gap-3">
      <div className="relative grid justify-items-center">
        <span className={`z-10 grid size-10 place-items-center rounded-full ${toneClass}`}>{icon}</span>
        {!last && <span className={`absolute top-10 h-[calc(100%+14px)] w-px ${lineClass}`} />}
      </div>
      <div className={`min-h-[74px] border-b border-white/[0.08] pb-4 ${last ? "border-b-0 pb-0" : ""}`}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <strong className="block text-sm text-slate-100">{title}</strong>
            <span className="mt-1 block truncate text-xs leading-5 text-ops-muted">{detail}</span>
          </div>
          {emph ? <b className="shrink-0 font-mono text-2xl font-black text-ops-orange">{emph}</b> : <span className="shrink-0 font-mono text-xs text-ops-muted">{meta || "-"}</span>}
        </div>
      </div>
    </div>
  );
}

function RoundStatusPill({ round }: { round: RoundSession }) {
  const precise = Boolean(round.results?.precise);
  const running = round.status === "running";
  const label = running ? "进行中" : precise ? "已发布" : "已结束";
  const className = running
    ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
    : precise
      ? "border-purple-400/25 bg-purple-400/10 text-purple-200"
      : "border-blue-400/25 bg-blue-400/10 text-blue-200";
  return <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-black ${className}`}>{label}</span>;
}

function RecordingRuler({ density, maxDensity, markers, clips, durationSeconds }: { density: Array<{ t: number; count: number }>; maxDensity: number; markers: Array<{ id: string; label: string; atSeconds: number }>; clips: Array<{ id: string; label: string; startSeconds: number; endSeconds: number }>; durationSeconds: number }) {
  const safeDuration = Math.max(1, Number(durationSeconds || 0));
  const buckets = density.length ? density.slice(0, 120) : Array.from({ length: 90 }, (_, index) => ({ t: index, count: 0 }));
  const markerItems = markers.slice(0, 5);
  const clipItems = clips.slice(0, 3);
  return (
    <div className="grid gap-4">
      <div className="relative h-32 rounded-2xl border border-white/10 bg-black/30 p-4">
        <div className="absolute left-4 right-4 top-5 h-px bg-white/10" />
        <div className="absolute left-4 right-4 top-8 flex justify-between font-mono text-[10px] text-ops-subtle">
          <span>00:00</span>
          <span>{formatClockDuration(safeDuration / 2)}</span>
          <span>{formatClockDuration(safeDuration)}</span>
        </div>
        {clipItems.map((clip) => {
          const left = Math.min(96, Math.max(0, (clip.startSeconds / safeDuration) * 100));
          const width = Math.min(100 - left, Math.max(4, ((clip.endSeconds - clip.startSeconds) / safeDuration) * 100));
          return <span key={clip.id} className="absolute top-[52px] h-2 rounded-full bg-blue-400/55" style={{ left: `calc(1rem + ${left}% * .92)`, width: `${width}%` }} />;
        })}
        {markerItems.map((marker, index) => {
          const left = Math.min(96, Math.max(2, (marker.atSeconds / safeDuration) * 100));
          const palette = ["bg-emerald-500", "bg-ops-orange", "bg-blue-500", "bg-yellow-500", "bg-purple-500"];
          return (
            <span key={marker.id} className="absolute top-[50px] grid justify-items-center gap-1" style={{ left: `calc(${left}% - 18px)` }}>
              <b className={`rounded-xl px-2 py-1 text-[10px] ${palette[index % palette.length]} text-white`}>{marker.label}</b>
              <i className={`h-9 w-px ${palette[index % palette.length]}`} />
              <i className={`size-3 rounded-full ${palette[index % palette.length]}`} />
            </span>
          );
        })}
        <div className="absolute bottom-5 left-4 right-4 flex h-6 items-end gap-px">
          {buckets.map((item, index) => (
            <span
              key={`${item.t}-${index}`}
              className={`min-w-px flex-1 rounded-t ${item.count ? "bg-gradient-to-t from-blue-500 to-ops-orange" : "bg-white/[0.06]"}`}
              style={{ height: `${item.count ? Math.max(12, (item.count / Math.max(1, maxDensity)) * 100) : 12}%` }}
            />
          ))}
        </div>
      </div>
      <div className="rounded-2xl border border-white/10 bg-black/25 p-4">
        <div className="flex flex-wrap items-center gap-8 text-xs text-ops-muted">
          <span className="inline-flex items-center gap-2"><i className="size-2 rounded-full bg-ops-orange" /> 已添加标记</span>
          <span className="inline-flex items-center gap-2"><i className="size-2 rounded-full bg-blue-500" /> 片段区间</span>
        </div>
      </div>
    </div>
  );
}

function roundDisplayRange(round: RoundSession) {
  if (round.timeRange) return round.timeRange;
  if (round.startedAt && (round.endedAt || round.stoppedAt)) {
    return `${formatShortClock(round.startedAt)} - ${formatShortClock(round.endedAt || round.stoppedAt)}`;
  }
  if (round.startedAt) return `${formatShortClock(round.startedAt)} - 进行中`;
  return "-";
}

function formatShortClock(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatClockDuration(seconds: unknown) {
  const total = Math.max(0, Math.floor(Number(seconds || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/15 p-2">
      <span className="block text-xs text-ops-muted">{label}</span>
      <b className="mt-1 block font-mono text-lg font-black">{value}</b>
    </div>
  );
}

function SettingsBlueprintPage({ status, settings }: { status?: SystemStatus; settings?: unknown }) {
  const queryClient = useQueryClient();
  const config = ((settings as { config?: Record<string, any> } | undefined)?.config || {}) as Record<string, any>;
  const [form, setForm] = useState<Record<string, any>>({});

  useEffect(() => {
    const vote = config.vote || {};
    const mgtv = config.mgtv || {};
    const recording = config.recording || {};
    const github = config.github || {};
    const feishu = config.feishu || {};
    const operatorAuth = config.operator_auth || {};
    const listen = config.listen || {};
    const storage = config.storage || {};
    setForm({
      voteActivity: vote.activity || "歌手 2026",
      votePolicy: vote.multi_candidate_policy || "all",
      candidatesText: candidatesToText(vote.candidates || []),
      mgtvUrl: mgtv.url || "",
      historyApi: mgtv.history_api || "https://lb.bz.mgtv.com/get_history",
      roomId: mgtv.room_id || "",
      cameraId: mgtv.camera_id || "",
      flag: mgtv.flag || "liveshow",
      pollSeconds: mgtv.poll_seconds || 2,
      reconnectSeconds: mgtv.reconnect_seconds || 5,
      dedupHotCacheSize: mgtv.dedup_hot_cache_size || 200000,
      dedupMaxRecords: mgtv.dedup_max_records || 100000000,
      dedupDbPath: mgtv.dedup_db_path || "server/data/fingerprints.sqlite3",
      recordingEnabled: Boolean(recording.enabled),
      preferredQuality: recording.preferred_quality || "auto",
      streamUrl: "",
      ffmpegPath: recording.ffmpeg_path || "ffmpeg",
      recordingDirectory: recording.directory || "server/data/recordings",
      githubEnabled: Boolean(github.enabled),
      githubOwner: github.owner || "",
      githubRepo: github.repo || "",
      githubBranch: github.branch || "main",
      githubPath: github.path || "site/data/results.json",
      githubToken: "",
      feishuEnabled: Boolean(feishu.enabled),
      feishuMode: feishu.connection_mode || "websocket",
      feishuAppId: feishu.app_id || "",
      feishuAppSecret: "",
      feishuVerificationToken: "",
      feishuOpenIds: (feishu.allowed_open_ids || []).join("\n"),
      feishuChatIds: (feishu.allowed_chat_ids || []).join("\n"),
      publicResultsUrl: feishu.public_results_url || "",
      authEnabled: Boolean(operatorAuth.enabled),
      newPassword: "",
      sessionHours: operatorAuth.session_hours || 12,
      secureCookie: Boolean(operatorAuth.secure_cookie),
      maxFailures: operatorAuth.max_failures || 5,
      failureWindowSeconds: operatorAuth.failure_window_seconds || 300,
      listenHost: listen.host || "127.0.0.1",
      listenPort: listen.port || 8080,
      publicBaseUrl: listen.public_base_url || "",
      storageDirectory: storage.directory || "server/data"
    });
  }, [settings]);

  const update = (key: string, value: unknown) => setForm((current) => ({ ...current, [key]: value }));
  const save = useMutation({
    mutationFn: () => apiPost("/api/settings", buildSettingsPayload(form)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const mgtvAuth = useQuery<MgtvAuthStatus>({
    queryKey: ["mgtv-auth"],
    queryFn: () => apiGet<MgtvAuthStatus>("/api/mgtv/auth"),
    refetchInterval: 5_000
  });
  const startMgtvAuth = useMutation({
    mutationFn: () => apiPost<MgtvAuthStatus>("/api/mgtv/auth/start"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mgtv-auth"] });
      queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
    }
  });
  const feishuBinding = useQuery<FeishuBindingStatus>({
    queryKey: ["feishu-binding"],
    queryFn: () => apiGet<FeishuBindingStatus>("/api/feishu/binding"),
    refetchInterval: 5_000
  });
  const startFeishuBinding = useMutation({
    mutationFn: () => apiPost<FeishuBindingStatus>("/api/feishu/binding/start"),
    onSuccess: (payload) => {
      if (payload.verificationUrl) {
        window.open(payload.verificationUrl, "_blank", "noopener,noreferrer");
      }
      queryClient.invalidateQueries({ queryKey: ["feishu-binding"] });
      queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] });
    }
  });
  const sendFeishuTestCard = useMutation({
    mutationFn: () => apiPost("/api/feishu/push-card"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const updateStatus = useQuery<UpdateStatus>({
    queryKey: ["update-status"],
    queryFn: () => apiGet<UpdateStatus>("/api/update/status"),
    refetchInterval: 5_000
  });
  const applyUpdate = useMutation({
    mutationFn: () => apiPost("/api/update/apply"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["update-status"] })
  });
  const restartService = useMutation({
    mutationFn: () => apiPost("/api/restart"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const mgtvView = startMgtvAuth.data || mgtvAuth.data;
  const feishuView = startFeishuBinding.data || feishuBinding.data;
  const updateView = updateStatus.data;
  const updateProgress = updateView?.progress || {};
  return (
    <section>
      <PageHeading
        kicker="System Settings"
        title="系统配置"
        description="低频配置集中在这里；活动 URL 与日常操作请在活动监控和运营工作区完成。保存后服务端会返回热重载、下一场生效或需安全重启的影响。"
        action={<PrimaryButton onClick={() => save.mutate()}>保存并热应用</PrimaryButton>}
      />
      {save.error && <p className="mb-4 rounded-2xl border border-red-400/30 bg-red-400/10 px-5 py-4 text-sm text-red-100">{String((save.error as Error).message || save.error)}</p>}
      {Boolean(save.data) && <p className="mb-4 rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-5 py-4 text-sm text-emerald-100">配置已保存。{(save.data as any)?.restartRequired ? "部分配置需要安全重启。" : "可热应用配置已生效。"}</p>}
      <div className="grid grid-cols-[1fr_1fr_1fr_.75fr] gap-4 max-2xl:grid-cols-2 max-lg:grid-cols-1">
        <Card title="连接与账号">
          <div className="grid gap-4">
            <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <strong className="block text-sm">芒果 TV 扫码登录</strong>
                  <p className="mt-2 text-xs leading-6 text-ops-muted">用于检测 1080P/VIP 清晰度与解析可录制播放流，登录态只保存在服务器配置中。</p>
                </div>
                <StatusBadge tone={mgtvView?.cookieConfigured ? "green" : mgtvView?.status === "pending" ? "orange" : "neutral"}>
                  {mgtvView?.cookieConfigured ? "已登录" : mgtvView?.status === "pending" ? "等待扫码" : "未登录"}
                </StatusBadge>
              </div>
              <div className="mt-4 grid grid-cols-[minmax(0,1fr)_112px] gap-4 max-sm:grid-cols-1">
                <div className="grid gap-2 text-xs leading-6 text-ops-muted">
                  <span>账号：{mgtvView?.user?.nickname || mgtvView?.user?.uid || "-"}</span>
                  <span>VIP：{mgtvView?.user?.isVip ? `是${mgtvView.user.vipType ? ` · ${mgtvView.user.vipType}` : ""}` : mgtvView?.cookieConfigured ? "否/未知" : "未知"}</span>
                  <span>协议：{mgtvView?.loginProtocolAvailable ? mgtvView.loginProtocol || "mgtv_http_qr" : "不可用"}</span>
                  {(mgtvView?.error || startMgtvAuth.error || mgtvAuth.error) && (
                    <span className="rounded-xl border border-red-400/30 bg-red-400/10 px-3 py-2 text-red-100">{String(mgtvView?.error || (startMgtvAuth.error as Error)?.message || (mgtvAuth.error as Error)?.message)}</span>
                  )}
                </div>
                <div className="grid min-h-28 place-items-center rounded-2xl border border-white/10 bg-white/[0.035] p-2">
                  {mgtvView?.screenshot ? <img className="max-h-28 rounded-xl" src={mgtvView.screenshot} alt="芒果 TV 登录二维码" /> : <span className="text-center text-xs text-ops-muted">二维码将在扫码登录时显示</span>}
                </div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <button type="button" className="rounded-xl bg-ops-orange px-4 py-3 text-sm font-black text-[#1b0d03]" disabled={startMgtvAuth.isPending || mgtvView?.status === "pending"} onClick={() => startMgtvAuth.mutate()}>
                  {mgtvView?.cookieConfigured ? "重新扫码" : "发起扫码登录"}
                </button>
                <button type="button" className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm font-black text-slate-100" onClick={() => queryClient.invalidateQueries({ queryKey: ["mgtv-auth"] })}>刷新状态</button>
              </div>
            </div>
            <SettingsToggle label="启用飞书 Bot" checked={Boolean(form.feishuEnabled)} onChange={(value) => update("feishuEnabled", value)} />
            <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <strong className="block text-sm">飞书一键绑定</strong>
                  <p className="mt-2 text-xs leading-6 text-ops-muted">绑定后可在飞书卡片内完成开轮次、切换场次、导出 PNG、删除和录制后处理。</p>
                </div>
                <StatusBadge tone={feishuView?.status === "bound" || feishuView?.appSecretConfigured ? "green" : feishuView?.status === "pending" ? "orange" : "neutral"}>
                  {feishuView?.status === "pending" ? "等待授权" : feishuView?.appSecretConfigured ? "已绑定" : "未绑定"}
                </StatusBadge>
              </div>
              <div className="mt-4 grid gap-2 text-xs leading-6 text-ops-muted">
                <span>App ID：{feishuView?.appId || form.feishuAppId || "-"}</span>
                <span>授权 open_id：{feishuView?.openId || "-"}</span>
                <span>长连接：{feishuView?.workerAlive ? "运行中" : "未运行"}</span>
                {feishuView?.userCode && <span className="rounded-xl border border-orange-400/30 bg-orange-400/10 px-3 py-2 font-mono text-ops-gold">授权码：{feishuView.userCode}</span>}
                {feishuView?.verificationUrl && <a className="rounded-xl border border-blue-400/30 bg-blue-400/10 px-3 py-2 font-black text-blue-100" href={feishuView.verificationUrl} target="_blank" rel="noreferrer">打开飞书授权页</a>}
                {(feishuView?.error || startFeishuBinding.error || feishuBinding.error || sendFeishuTestCard.error) && (
                  <span className="rounded-xl border border-red-400/30 bg-red-400/10 px-3 py-2 text-red-100">{String(feishuView?.error || (startFeishuBinding.error as Error)?.message || (feishuBinding.error as Error)?.message || (sendFeishuTestCard.error as Error)?.message)}</span>
                )}
                {sendFeishuTestCard.isSuccess && <span className="rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-emerald-100">测试卡片已发送到已配置的飞书会话。</span>}
              </div>
              <div className="mt-4 grid grid-cols-3 gap-3 max-sm:grid-cols-1">
                <button type="button" className="rounded-xl bg-ops-orange px-4 py-3 text-sm font-black text-[#1b0d03]" disabled={startFeishuBinding.isPending || feishuView?.status === "pending"} onClick={() => startFeishuBinding.mutate()}>
                  {feishuView?.appSecretConfigured ? "重新绑定" : "发起绑定"}
                </button>
                <button type="button" className="rounded-xl border border-blue-400/30 bg-blue-400/15 px-4 py-3 text-sm font-black text-blue-100" disabled={sendFeishuTestCard.isPending} onClick={() => sendFeishuTestCard.mutate()}>发送测试卡片</button>
                <button type="button" className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm font-black text-slate-100" onClick={() => queryClient.invalidateQueries({ queryKey: ["feishu-binding"] })}>刷新状态</button>
              </div>
            </div>
            <Field label="飞书连接模式">
              <select className="ops-input" value={form.feishuMode || "websocket"} onChange={(event) => update("feishuMode", event.target.value)}>
                <option value="websocket">WebSocket 长连接</option>
                <option value="webhook">HTTP 回调</option>
              </select>
            </Field>
            <Field label="飞书 App ID">
              <input className="ops-input" value={form.feishuAppId || ""} onChange={(event) => update("feishuAppId", event.target.value)} />
            </Field>
            <Field label="App Secret（留空保留）">
              <input className="ops-input" type="password" value={form.feishuAppSecret || ""} onChange={(event) => update("feishuAppSecret", event.target.value)} />
            </Field>
            <Field label="公开结果页 URL">
              <input className="ops-input" value={form.publicResultsUrl || ""} onChange={(event) => update("publicResultsUrl", event.target.value)} />
            </Field>
            <SettingsToggle label="启用 GitHub 发布" checked={Boolean(form.githubEnabled)} onChange={(value) => update("githubEnabled", value)} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Owner"><input className="ops-input" value={form.githubOwner || ""} onChange={(event) => update("githubOwner", event.target.value)} /></Field>
              <Field label="Repo"><input className="ops-input" value={form.githubRepo || ""} onChange={(event) => update("githubRepo", event.target.value)} /></Field>
            </div>
            <Field label="Fine-grained Token（留空保留）">
              <input className="ops-input" type="password" value={form.githubToken || ""} onChange={(event) => update("githubToken", event.target.value)} />
            </Field>
          </div>
        </Card>

        <Card title="采集与录制">
          <div className="grid gap-4">
            <Field label="默认活动名称"><input className="ops-input" value={form.voteActivity || ""} onChange={(event) => update("voteActivity", event.target.value)} /></Field>
            <Field label="多人弹幕策略">
              <select className="ops-input" value={form.votePolicy || "all"} onChange={(event) => update("votePolicy", event.target.value)}>
                <option value="all">all · 每位各计 1 票</option>
                <option value="review">review · 多人弹幕待审</option>
              </select>
            </Field>
            <Field label="候选人与别名（每行：正式名, 别名1, 别名2）">
              <textarea className="ops-input min-h-36" value={form.candidatesText || ""} onChange={(event) => update("candidatesText", event.target.value)} />
            </Field>
            <Field label="默认直播 URL"><input className="ops-input" value={form.mgtvUrl || ""} onChange={(event) => update("mgtvUrl", event.target.value)} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="room_id"><input className="ops-input" value={form.roomId || ""} onChange={(event) => update("roomId", event.target.value)} /></Field>
              <Field label="camera_id"><input className="ops-input" value={form.cameraId || ""} onChange={(event) => update("cameraId", event.target.value)} /></Field>
            </div>
            <SettingsToggle label="启用默认录屏" checked={Boolean(form.recordingEnabled)} onChange={(value) => update("recordingEnabled", value)} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="默认清晰度"><input className="ops-input" value={form.preferredQuality || "auto"} onChange={(event) => update("preferredQuality", event.target.value)} /></Field>
              <Field label="ffmpeg 路径"><input className="ops-input" value={form.ffmpegPath || ""} onChange={(event) => update("ffmpegPath", event.target.value)} /></Field>
            </div>
            <Field label="录屏直播流 URL（留空保留）"><input className="ops-input" value={form.streamUrl || ""} onChange={(event) => update("streamUrl", event.target.value)} /></Field>
          </div>
        </Card>

        <Card title="安全、存储与更新">
          <div className="grid gap-4">
            <SettingsToggle label="启用运营端密码" checked={Boolean(form.authEnabled)} onChange={(value) => update("authEnabled", value)} />
            <Field label="设置新密码（留空保留）"><input className="ops-input" type="password" value={form.newPassword || ""} onChange={(event) => update("newPassword", event.target.value)} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="会话小时"><input className="ops-input" type="number" value={form.sessionHours || 12} onChange={(event) => update("sessionHours", Number(event.target.value))} /></Field>
              <Field label="失败上限"><input className="ops-input" type="number" value={form.maxFailures || 5} onChange={(event) => update("maxFailures", Number(event.target.value))} /></Field>
            </div>
            <Field label="数据目录"><input className="ops-input" value={form.storageDirectory || ""} onChange={(event) => update("storageDirectory", event.target.value)} /></Field>
            <Field label="录制目录"><input className="ops-input" value={form.recordingDirectory || ""} onChange={(event) => update("recordingDirectory", event.target.value)} /></Field>
            <div className="grid grid-cols-[1fr_120px] gap-3">
              <Field label="监听地址"><input className="ops-input" value={form.listenHost || ""} onChange={(event) => update("listenHost", event.target.value)} /></Field>
              <Field label="端口"><input className="ops-input" type="number" value={form.listenPort || 8080} onChange={(event) => update("listenPort", Number(event.target.value))} /></Field>
            </div>
            <Field label="外部访问地址"><input className="ops-input" value={form.publicBaseUrl || ""} onChange={(event) => update("publicBaseUrl", event.target.value)} /></Field>
            <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <strong className="block text-sm">程序版本升级</strong>
                  <p className="mt-2 text-xs leading-6 text-ops-muted">仅允许 fast-forward 更新。采集中、工作区脏数据或已有升级任务时会被后端拒绝。</p>
                </div>
                <StatusBadge tone={updateView?.inProgress ? "orange" : updateView?.updateAvailable ? "blue" : updateView?.dirty ? "red" : "green"}>
                  {updateView?.inProgress ? "升级中" : updateView?.updateAvailable ? "发现新版本" : updateView?.dirty ? "工作区有改动" : "已是最新"}
                </StatusBadge>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-xs leading-6 text-ops-muted">
                <span>当前 commit：<b className="font-mono text-slate-100">{updateView?.currentShort || "-"}</b></span>
                <span>远端 commit：<b className="font-mono text-slate-100">{updateView?.remoteShort || "-"}</b></span>
                <span>目标分支：{updateView?.remote && updateView?.remoteBranch ? `${updateView.remote}/${updateView.remoteBranch}` : "-"}</span>
                <span>传输速度：{updateProgress.speed || "-"}</span>
              </div>
              <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10">
                <span className="block h-full rounded-full bg-gradient-to-r from-ops-blue to-ops-orange transition-all" style={{ width: `${Math.max(0, Math.min(100, Number(updateProgress.percent || 0)))}%` }} />
              </div>
              <p className="mt-3 text-xs leading-6 text-ops-muted">{updateProgress.detail || (updateView?.updateAvailable ? "发现远端新 commit，可一键升级。" : "当前部署已经与远端目标分支一致。")}</p>
              {!!updateView?.blockers?.length && (
                <div className="mt-3 rounded-xl border border-orange-400/30 bg-orange-400/10 px-3 py-2 text-xs leading-6 text-ops-gold">
                  {updateView.blockers.join("；")}
                </div>
              )}
              {(updateStatus.error || applyUpdate.error || restartService.error) && (
                <div className="mt-3 rounded-xl border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs leading-6 text-red-100">
                  {String((updateStatus.error as Error)?.message || (applyUpdate.error as Error)?.message || (restartService.error as Error)?.message)}
                </div>
              )}
              <div className="mt-4 grid grid-cols-3 gap-3 max-sm:grid-cols-1">
                <button type="button" className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm font-black text-slate-100" disabled={updateStatus.isFetching} onClick={() => queryClient.invalidateQueries({ queryKey: ["update-status"] })}>检查更新</button>
                <button type="button" className="rounded-xl bg-ops-orange px-4 py-3 text-sm font-black text-[#1b0d03]" disabled={!updateView?.canApply || updateView?.inProgress || applyUpdate.isPending} onClick={() => applyUpdate.mutate()}>一键升级</button>
                <button type="button" className="rounded-xl border border-orange-400/35 bg-orange-400/10 px-4 py-3 text-sm font-black text-ops-gold" disabled={!status?.health?.restartRequired || restartService.isPending} onClick={() => restartService.mutate()}>安全重启</button>
              </div>
            </div>
          </div>
        </Card>

        <Card title="本次修改影响">
          <div className="grid gap-3 text-sm">
            <Impact tone="green" title="立即生效" items={["飞书白名单", "弹幕轮询间隔", "GitHub 发布路径", "运营登录策略"]} />
            <Impact tone="blue" title="下一场生效" items={["候选人与别名", "默认清晰度", "room_id / camera_id", "录制开关"]} />
            <Impact tone="orange" title="需要重启" items={status?.health?.restartFields?.length ? status.health.restartFields : ["监听地址", "主数据目录"]} />
          </div>
          <button type="button" className="mt-5 w-full rounded-xl bg-ops-orange px-5 py-3 text-sm font-black text-[#1b0d03]" disabled={save.isPending} onClick={() => save.mutate()}>
            保存并热应用
          </button>
        </Card>
      </div>
    </section>
  );
}

function candidatesToText(candidates: Array<{ name?: string; aliases?: string[] }> = []) {
  return candidates.map((candidate) => {
    const aliases = (candidate.aliases || []).filter((alias) => alias && alias !== candidate.name);
    return [candidate.name, ...aliases].filter(Boolean).join(", ");
  }).join("\n");
}

function parseCandidates(text: string) {
  return text
    .split(/\n+/)
    .map((line) => line.split(/[,，]/).map((item) => item.trim()).filter(Boolean))
    .filter((items) => items.length)
    .map(([name, ...aliases]) => ({ name, aliases: [name, ...aliases] }));
}

function splitIds(text: string) {
  return String(text || "").split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean);
}

function buildSettingsPayload(form: Record<string, any>) {
  return {
    listen: {
      host: form.listenHost,
      port: Number(form.listenPort || 8080),
      public_base_url: form.publicBaseUrl || ""
    },
    storage: {
      directory: form.storageDirectory
    },
    vote: {
      activity: form.voteActivity,
      multi_candidate_policy: form.votePolicy,
      candidates: parseCandidates(form.candidatesText || "")
    },
    mgtv: {
      url: form.mgtvUrl,
      history_api: form.historyApi,
      flag: form.flag || "liveshow",
      room_id: form.roomId || "",
      camera_id: form.cameraId || "",
      poll_seconds: Number(form.pollSeconds || 2),
      reconnect_seconds: Number(form.reconnectSeconds || 5),
      count_initial_history: false,
      dedup_hot_cache_size: Number(form.dedupHotCacheSize || 200000),
      dedup_max_records: Number(form.dedupMaxRecords || 100000000),
      dedup_db_path: form.dedupDbPath
    },
    recording: {
      enabled: Boolean(form.recordingEnabled),
      stream_url: form.streamUrl || "",
      preferred_quality: form.preferredQuality || "auto",
      ffmpeg_path: form.ffmpegPath || "ffmpeg",
      directory: form.recordingDirectory
    },
    github: {
      enabled: Boolean(form.githubEnabled),
      owner: form.githubOwner || "",
      repo: form.githubRepo || "",
      branch: form.githubBranch || "main",
      path: form.githubPath || "site/data/results.json",
      token: form.githubToken || ""
    },
    feishu: {
      enabled: Boolean(form.feishuEnabled),
      connection_mode: form.feishuMode || "websocket",
      app_id: form.feishuAppId || "",
      app_secret: form.feishuAppSecret || "",
      verification_token: form.feishuVerificationToken || "",
      allowed_open_ids: splitIds(form.feishuOpenIds || ""),
      allowed_chat_ids: splitIds(form.feishuChatIds || ""),
      public_results_url: form.publicResultsUrl || ""
    },
    operator_auth: {
      enabled: Boolean(form.authEnabled),
      new_password: form.newPassword || "",
      session_hours: Number(form.sessionHours || 12),
      secure_cookie: Boolean(form.secureCookie),
      max_failures: Number(form.maxFailures || 5),
      failure_window_seconds: Number(form.failureWindowSeconds || 300)
    }
  };
}

function SettingsToggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="flex items-center justify-between rounded-2xl border border-white/10 bg-black/20 p-4 text-left">
      <strong className="text-sm text-white">{label}</strong>
      <span className={`h-7 w-12 rounded-full p-1 ${checked ? "bg-ops-orange" : "bg-white/10"}`}>
        <i className={`block size-5 rounded-full bg-white transition ${checked ? "translate-x-5" : ""}`} />
      </span>
    </button>
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
  const [refreshSeconds, setRefreshSeconds] = useState(15);
  const status = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus, initialData: initial, refetchInterval: refreshSeconds ? refreshSeconds * 1000 : false });
  const metrics = useQuery({ queryKey: ["system-metrics", "15m"], queryFn: () => getSystemMetrics("15m"), refetchInterval: refreshSeconds ? refreshSeconds * 1000 : false });
  const payload = status.data;
  const [history, setHistory] = useState<Array<{ at: string; cpu: number; memory: number; network: number; danmaku: number }>>([]);
  useEffect(() => {
    if (!payload) return;
    setHistory((current) => {
      const memoryPercent = payload.memory?.totalBytes ? ((payload.memory.usedBytes || 0) / payload.memory.totalBytes) * 100 : 0;
      const networkTotal = Number(payload.network?.rxBytes || 0) + Number(payload.network?.txBytes || 0);
      const danmakuRate = Number(payload.services?.collector?.activeCount || 0);
      const next = [
        ...current,
        {
          at: payload.systemTime || new Date().toISOString(),
          cpu: Number(payload.cpu?.loadPercent || 0),
          memory: memoryPercent,
          network: networkTotal,
          danmaku: danmakuRate
        }
      ];
      return next.slice(-60);
    });
  }, [payload?.generatedAt, payload?.systemTime]);
  const metricPoints = metrics.data?.points || [];
  const trend = metricPoints.length
    ? {
      cpu: metricPoints.map((item) => Number(item.cpuPercent || 0)),
      memory: metricPoints.map((item) => Number(item.memoryPercent || 0)),
      network: metricPoints.map((item) => Number(item.rxBytesPerSecond || 0) + Number(item.txBytesPerSecond || 0)),
      danmaku: metricPoints.map((item) => Number(item.danmakuPerSecond || 0))
    }
    : {
      cpu: history.map((item) => item.cpu),
      memory: history.map((item) => item.memory),
      network: history.map((item) => item.network),
      danmaku: history.map((item) => item.danmaku)
    };
  return (
    <section>
      <PageHeading
        kicker="System Health"
        title="机器状态监控"
        description="实时监控服务器与服务运行状态，保障直播运营稳定可靠。"
        action={
          <div className="flex flex-wrap items-center gap-3">
            <select className="ops-input" style={{ width: "auto", minWidth: "10rem" }} value={refreshSeconds} onChange={(event) => setRefreshSeconds(Number(event.target.value))}>
              <option value={0}>停止自动刷新</option>
              <option value={5}>自动刷新：5 秒</option>
              <option value={15}>自动刷新：15 秒</option>
              <option value={30}>自动刷新：30 秒</option>
            </select>
            <button type="button" className="rounded-xl bg-ops-orange px-5 py-3 text-sm font-black text-[#1b0d03]" disabled={status.isFetching || metrics.isFetching} onClick={() => { status.refetch(); metrics.refetch(); }}>立即刷新</button>
          </div>
        }
      />
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
          <p className="text-sm leading-7 text-ops-muted">错误数：{payload?.health?.recentErrorCount || 0}。如果出现录制失败、直播源检测失败或 GitHub 发布失败，请跳转系统日志查看同一时间段事件。</p>
        </Card>
        <Card title="性能趋势（最近采样）" className="col-span-4 max-2xl:col-span-2 max-lg:col-span-1">
          <div className="grid grid-cols-4 gap-4 max-xl:grid-cols-2 max-md:grid-cols-1">
            <TrendCard label="CPU 使用率" suffix="%" values={trend.cpu} />
            <TrendCard label="内存使用率" suffix="%" values={trend.memory} />
            <TrendCard label="网络速度" suffix="B/s" values={trend.network} format={(value) => `${formatBytes(value)}/s`} />
            <TrendCard label="弹幕速率" suffix="条/秒" values={trend.danmaku} />
          </div>
        </Card>
      </div>
    </section>
  );
}

function TrendCard({ label, values, suffix, format }: { label: string; values: number[]; suffix?: string; format?: (value: unknown) => string }) {
  const latest = values.at(-1) || 0;
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm text-ops-muted">{label}</span>
        <strong className="font-mono text-lg">{format ? format(latest) : `${Math.round(latest)}${suffix || ""}`}</strong>
      </div>
      <Sparkline values={values} />
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const points = values.length ? values : [0];
  const max = Math.max(1, ...points);
  const width = 280;
  const height = 72;
  const path = points.map((value, index) => {
    const x = points.length === 1 ? 0 : (index / (points.length - 1)) * width;
    const y = height - (value / max) * (height - 8) - 4;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-20 w-full overflow-visible">
      <path d={path} fill="none" stroke="#ff861f" strokeWidth="3" strokeLinecap="round" />
    </svg>
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

function logTimeRange(range: string) {
  if (range === "all") {
    return { from: "", to: "" };
  }
  const hours = range === "24h" ? 24 : range === "6h" ? 6 : 1;
  return {
    from: new Date(Date.now() - hours * 3600 * 1000).toISOString(),
    to: new Date().toISOString()
  };
}

function SystemLogsPage({ initialLogs }: { initialLogs: SystemLogEvent[] }) {
  const [filters, setFilters] = useState({ q: "", level: "", source: "", range: "1h" });
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [followLogs, setFollowLogs] = useState(true);
  const timeRange = logTimeRange(filters.range);
  const query = new URLSearchParams();
  query.set("limit", "160");
  if (filters.q.trim()) query.set("q", filters.q.trim());
  if (filters.level) query.set("level", filters.level);
  if (filters.source) query.set("source", filters.source);
  if (timeRange.from) query.set("from", timeRange.from);
  if (timeRange.to) query.set("to", timeRange.to);
  const logs = useQuery({
    queryKey: ["system-logs", filters],
    queryFn: () => apiGet<SystemLogsResponse>(`/api/system/logs?${query.toString()}`),
    initialData: { events: initialLogs },
    refetchInterval: followLogs ? 10_000 : false
  });
  const summary = useMutation({
    mutationFn: () => apiPost<SystemLogSummary>("/api/system/logs/summary", {
      q: filters.q,
      level: filters.level,
      source: filters.source,
      from: timeRange.from,
      to: timeRange.to
    })
  });
  const items = logs.data.events || logs.data.items || [];
  const sources = Array.from(new Set(items.map((item) => item.source).filter(Boolean))) as string[];
  const selected = items[selectedIndex] || items[0];
  const exportLogs = () => {
    window.open(`/api/system/logs/export?${query.toString()}`, "_blank", "noopener,noreferrer");
  };
  return (
    <section>
      <PageHeading
        kicker="System Logs"
        title="系统日志"
        description="按时间查看系统运行日志，支持搜索、过滤、导出和排障摘要。"
        action={
          <div className="flex flex-wrap gap-3">
            <button type="button" className={`rounded-xl border px-5 py-3 text-sm font-black ${followLogs ? "border-blue-400/35 bg-blue-400/15 text-blue-100" : "border-white/10 bg-white/[0.04] text-slate-200"}`} onClick={() => setFollowLogs((value) => !value)}>
              {followLogs ? "日志实时跟随" : "已暂停跟随"}
            </button>
            <button type="button" className="rounded-xl border border-orange-400/35 bg-orange-400/10 px-5 py-3 text-sm font-black text-ops-gold" disabled={summary.isPending} onClick={() => summary.mutate()}>
              生成排障摘要
            </button>
            <button type="button" className="rounded-xl bg-ops-orange px-5 py-3 text-sm font-black text-[#1b0d03]" disabled={logs.isFetching} onClick={() => logs.refetch()}>立即刷新</button>
          </div>
        }
      />
      <div className="mb-4 grid grid-cols-[minmax(260px,1fr)_140px_160px_180px_auto] gap-3 rounded-3xl border border-white/10 bg-white/[0.04] p-4 max-lg:grid-cols-1">
        <input className="ops-input" value={filters.q} onChange={(event) => setFilters({ ...filters, q: event.target.value })} placeholder="搜索错误、场次 ID、关键词…" />
        <select className="ops-input" value={filters.level} onChange={(event) => setFilters({ ...filters, level: event.target.value })}>
          <option value="">全部级别</option>
          <option value="INFO">INFO</option>
          <option value="WARN">WARN</option>
          <option value="ERROR">ERROR</option>
        </select>
        <select className="ops-input" value={filters.source} onChange={(event) => setFilters({ ...filters, source: event.target.value })}>
          <option value="">全部来源</option>
          {sources.map((source) => <option key={source} value={source}>{source}</option>)}
        </select>
        <select className="ops-input" value={filters.range} onChange={(event) => setFilters({ ...filters, range: event.target.value })}>
          <option value="1h">最近 1 小时</option>
          <option value="6h">最近 6 小时</option>
          <option value="24h">最近 24 小时</option>
          <option value="all">全部时间</option>
        </select>
        <button className="rounded-xl bg-blue-500 px-4 py-3 text-sm font-black text-white" type="button" onClick={exportLogs}>导出日志</button>
      </div>
      {summary.data && (
        <div className="mb-4 rounded-3xl border border-orange-400/30 bg-orange-400/10 p-5 text-sm leading-7 text-ops-gold">
          <strong className="block text-base text-ops-gold">排障摘要</strong>
          <p className="mt-2">{summary.data.summary}</p>
          <ul className="mt-3 grid gap-1 text-slate-200">
            {(summary.data.suggestions || []).map((item) => <li key={item}>• {item}</li>)}
          </ul>
        </div>
      )}
      {summary.error && <p className="mb-4 rounded-2xl border border-red-400/30 bg-red-400/10 px-5 py-4 text-sm text-red-100">{String((summary.error as Error).message || summary.error)}</p>}
      <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-4 max-xl:grid-cols-1">
        <Card>
          <div className="grid gap-2">
            {items.length ? items.map((event, index) => (
              <button key={`${event.time}-${index}`} type="button" onClick={() => setSelectedIndex(index)} className="text-left">
                <LogRow event={event} active={index === selectedIndex} />
              </button>
            )) : <div className="grid min-h-80 place-items-center text-ops-muted">暂无日志</div>}
          </div>
        </Card>
        <Card title="日志详情">
          {selected ? (
            <pre className="whitespace-pre-wrap rounded-2xl border border-white/10 bg-black/30 p-4 font-mono text-xs leading-6 text-slate-200">{JSON.stringify(selected, null, 2)}</pre>
          ) : (
            <p className="text-sm text-ops-muted">选择日志查看详情。</p>
          )}
          {selected?.level === "ERROR" && (
            <div className="mt-4 rounded-2xl border border-orange-400/30 bg-orange-400/10 p-4 text-sm leading-7 text-ops-gold">
              建议排障：先查看同一来源前后 5 条日志，确认是否与录制、直播源检测、GitHub 发布或飞书推送有关；必要时导出日志交给运维 agent。
            </div>
          )}
          <div className="mt-5">
            <h4 className="mb-3 text-sm font-black text-slate-200">相邻事件</h4>
            <Timeline items={items.slice(0, 5).map((event) => ({ title: event.summary || "事件", description: `${event.source || "service"} · ${event.time ? new Date(event.time).toLocaleTimeString("zh-CN", { hour12: false }) : ""}`, tone: event.level === "ERROR" ? "warn" : "done" }))} />
          </div>
        </Card>
      </div>
      <Card title="事件时间线" className="mt-4">
        {items.length ? (
          <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
            {items.slice(0, 6).map((event, index) => (
              <article key={`${event.time}-timeline-${index}`} className="rounded-2xl border border-white/10 bg-black/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className={`rounded-full px-3 py-1 font-mono text-[11px] font-black ${event.level === "ERROR" ? "bg-red-400/15 text-red-200" : event.level === "WARN" ? "bg-yellow-400/15 text-yellow-100" : "bg-blue-400/15 text-blue-100"}`}>
                    {event.level || "INFO"}
                  </span>
                  <time className="font-mono text-[11px] text-ops-muted">{event.time ? new Date(event.time).toLocaleTimeString("zh-CN", { hour12: false }) : "-"}</time>
                </div>
                <strong className="mt-4 block truncate text-sm">{event.summary || event.detail || "系统事件"}</strong>
                <p className="mt-2 truncate text-xs text-ops-muted">{event.source || "service"}</p>
              </article>
            ))}
          </div>
        ) : (
          <div className="grid min-h-36 place-items-center text-ops-muted">暂无可展示的事件时间线。</div>
        )}
      </Card>
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
