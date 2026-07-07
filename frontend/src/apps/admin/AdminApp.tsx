import {
  ArrowSquareOut,
  BellRinging,
  BookmarkSimple,
  Broadcast,
  CalendarBlank,
  CaretLeft,
  CaretRight,
  ChatCircleDots,
  CheckCircle,
  Clock,
  CopySimple,
  Database,
  DotsThree,
  DownloadSimple,
  FileText,
  FunnelSimple,
  Gauge,
  GlobeHemisphereWest,
  Lightning,
  LinkSimple,
  MagnifyingGlass,
  MonitorPlay,
  PaperPlaneTilt,
  Play,
  Pulse,
  Robot,
  Scissors,
  ShieldCheck,
  Sparkle,
  Stop,
  UploadSimple,
  VideoCamera,
  WarningCircle
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { apiDelete, apiGet, apiPatch, apiPost, apiUpload, getBootstrap, getSystemMetrics, getSystemLogs, getSystemStatus } from "../../api/client";
import type { ActivityItem, FeishuBindingStatus, FeishuPushResult, MgtvAuthStatus, Recording, RecordingTimeline, RoundSession, SourceDetectionResult, SystemLogEvent, SystemLogSummary, SystemLogsResponse, SystemStatus, UpdateStatus } from "../../api/types";
import { Card, PageHeading, PrimaryButton, Shell, StatusBadge } from "../../components/Shell";
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
  const selectedRound = sessions.find((item) => item.id === selectedRoundId && item.visibility !== "private" && item.kind !== "recording");
  const round = selectedRound || currentRound(sessions, publicState?.activeSessionId);
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
          {page === "activity" && <ActivityMonitorPage activity={bootstrap.data.activity} status={systemStatus} rounds={publicState?.sessions || []} recordings={bootstrap.data.recordings || []} />}
          {page === "ops" && (
            <OperationsPage
              rounds={publicState?.sessions || []}
              activeRound={round}
              defaultActivity={bootstrap.data.defaults?.activityName || publicState?.defaults?.activity || ""}
              publicResultsUrl={bootstrap.data.defaults?.publicResultsUrl || publicState?.defaults?.publicResultsUrl || ""}
            />
          )}
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

function ActivityMonitorPage({ activity, status, rounds = [], recordings = [] }: { activity?: ActivityItem | null; status?: SystemStatus; rounds?: RoundSession[]; recordings?: Recording[] }) {
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
  const recordingRounds = useMemo(() => rounds.filter((round) => round.kind === "recording" || round.visibility === "private" || Boolean(round.recording)), [rounds]);
  const activeRecording = recordings.find((item) => item.status === "recording")
    || recordingRounds.find((round) => round.recording?.status === "recording")?.recording
    || null;
  const latestRecordingRound = recordingRounds.find((round) => round.id === activeRecording?.roundId)
    || recordingRounds[0]
    || null;
  const latestRecording = activeRecording || latestRecordingRound?.recording || recordings[0] || null;
  const recordingMessageCount = Number(latestRecordingRound?.messageCount || activity?.messageCount || 0);
  const videoMetricValue = activeRecording ? "录制中" : form.autoRecordVideo ? "待启动" : "未启用";
  const videoMetricDetail = activeRecording
    ? `${formatClockDuration(activeRecording.durationSeconds || 0)} · ${formatBytes(activeRecording.fileSizeBytes)}`
    : latestRecording?.status === "stopped"
      ? `最近完成 · ${formatBytes(latestRecording.fileSizeBytes)}`
      : "等待开播后按策略启动";
  const danmakuMetricValue = activeRecording || latestRecordingRound ? `${formatCount(recordingMessageCount)} 条` : form.autoRecordDanmaku ? "待启动" : "未启用";
  const danmakuMetricDetail = activeRecording
    ? "独立录制弹幕正在持续写入"
    : latestRecordingRound
      ? `${roundName(latestRecordingRound)} · ${latestRecordingRound.status === "running" ? "写入中" : "已完成"}`
      : "开播后保存完整原始弹幕";
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
              <CollectionMetric icon={<VideoCamera size={20} weight="fill" />} label="视频录制" value={videoMetricValue} detail={videoMetricDetail} tone="orange" />
              <CollectionMetric icon={<ChatCircleDots size={20} weight="fill" />} label="弹幕采集" value={danmakuMetricValue} detail={danmakuMetricDetail} tone="blue" />
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

function OperationsPage({ rounds, activeRound, defaultActivity, publicResultsUrl }: { rounds: RoundSession[]; activeRound: RoundSession | null; defaultActivity: string; publicResultsUrl: string }) {
  const queryClient = useQueryClient();
  const resultType = useUiStore((state) => state.resultType);
  const setResultType = useUiStore((state) => state.setResultType);
  const selectedRoundId = useUiStore((state) => state.selectedRoundId);
  const setSelectedRoundId = useUiStore((state) => state.setSelectedRoundId);
  const publishableRounds = useMemo(() => rounds.filter((item) => item.visibility !== "private" && item.kind !== "recording"), [rounds]);
  const recordingRounds = useMemo(() => rounds.filter((item) => item.kind === "recording" || item.visibility === "private" || Boolean(item.recording)), [rounds]);
  const realtimeRounds = useMemo(() => publishableRounds.filter((item) => (item.kind || "realtime") === "realtime"), [publishableRounds]);
  const analysisRounds = useMemo(() => publishableRounds.filter((item) => item.kind === "analysis"), [publishableRounds]);
  const result = selectedResult(activeRound, resultType);
  const rows = rankingRows(activeRound, result.data);
  const total = rows.reduce((sum, row) => sum + row.votes, 0);
  const reviewCount = Number(result.data.reviewCount || activeRound?.reviewCount || 0);
  const [roundForm, setRoundForm] = useState({
    activity: defaultActivity || activeRound?.activity || "歌手 2026",
    name: "",
    url: ""
  });
  const [recordingForm, setRecordingForm] = useState({
    activity: defaultActivity || activeRound?.activity || "歌手 2026",
    name: "",
    url: ""
  });
  const [opsMode, setOpsMode] = useState<"realtime" | "post">("realtime");
  const [renameValue, setRenameValue] = useState("");
  const [selectedRecordingId, setSelectedRecordingId] = useState(recordingRounds.find((item) => item.recording?.status === "recording")?.id || recordingRounds[0]?.id || "");
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
    setRecordingForm((current) => ({
      ...current,
      activity: current.activity || defaultActivity || activeRound?.activity || "歌手 2026"
    }));
  }, [defaultActivity, activeRound?.activity]);
  useEffect(() => {
    const selectedHasRecording = recordingRounds.some((item) => item.id === selectedRecordingId && item.recording);
    const preferredRecordingId = recordingRounds.find((item) => item.recording?.status === "recording")?.id
      || recordingRounds.find((item) => item.recording)?.id
      || "";
    if (!selectedRecordingId || (!selectedHasRecording && preferredRecordingId)) {
      setSelectedRecordingId(preferredRecordingId);
    }
  }, [recordingRounds, selectedRecordingId]);
  const recordingRound = recordingRounds.find((item) => item.id === selectedRecordingId) || null;
  const recordingTimeline = useQuery<RecordingTimeline>({
    queryKey: ["recording-timeline", recordingRound?.id],
    queryFn: () => apiGet<RecordingTimeline>(`/api/recordings/${encodeURIComponent(recordingRound?.id || "")}/timeline`),
    enabled: Boolean(recordingRound?.id && recordingRound?.recording),
    refetchInterval: recordingRound?.recording?.status === "recording" ? 10_000 : false
  });
  const startRound = useMutation({
    mutationFn: () => apiPost("/api/rounds/start", {
      activity: roundForm.activity,
      name: roundForm.name || `第 ${realtimeRounds.length + 1} 轮`,
      url: roundForm.url || undefined,
      recordVideo: false,
      collectDanmaku: true
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const startFullRecording = useMutation({
    mutationFn: () => apiPost("/api/recordings/start", {
      activity: recordingForm.activity,
      name: recordingForm.name || `${recordingForm.activity || defaultActivity || "直播"} 全程录制`,
      url: recordingForm.url || undefined,
      recordVideo: true,
      collectDanmaku: true
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const endRound = useMutation({
    mutationFn: () => apiPost("/api/rounds/" + encodeURIComponent(activeRound?.id || "") + "/end", { publish: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const stopFullRecording = useMutation({
    mutationFn: () => apiPost("/api/recordings/" + encodeURIComponent(recordingRound?.id || "") + "/stop"),
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
    mutationFn: ({ clipId, name }: { clipId: string; name: string }) => apiPost(`/api/rounds/${encodeURIComponent(recordingRound?.id || "")}/recording/clips/${encodeURIComponent(clipId)}/analysis-round`, { name: name || "片段分析" }),
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
    const publicUrl = publicResultsUrl || new URL("/studio/public", window.location.origin).toString();
    await navigator.clipboard?.writeText(publicUrl);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };
  const operationError = startRound.error || startFullRecording.error || endRound.error || stopFullRecording.error || publish.error || pushFeishu.error || detectSource.error || renameRound.error || deleteRound.error || deleteActivity.error || addMarker.error || createClip.error || createAnalysisRound.error || uploadPrecise.error || recordingTimeline.error;
  const timeline = recordingTimeline.data;
  const density = timeline?.danmakuDensity || [];
  const maxDensity = Math.max(1, ...density.map((item) => item.count));
  const recording = timeline?.recording || recordingRound?.recording || null;
  const sortedRounds = [...publishableRounds].sort((a, b) => String(b.startedAt || b.endedAt || "").localeCompare(String(a.startedAt || a.endedAt || "")));
  const roundRows = sortedRounds.slice(0, 6);
  const activeDurationSeconds = activeRound?.startedAt ? Math.max(0, (Date.now() - new Date(activeRound.startedAt).getTime()) / 1000) : 0;
  const recordingDuration = Number(timeline?.durationSeconds || recording?.durationSeconds || activeDurationSeconds || 0);
  const markers = timeline?.markers || recording?.markers || [];
  const clips = timeline?.clips || recording?.clips || [];
  const autoClips = clips.filter((clip) => clip.kind === "auto");
  const manualClips = clips.filter((clip) => clip.kind !== "auto");
  const canPostProcess = Boolean(recording?.canPostProcess && recordingRound?.id);
  const postProcessReason = recording?.postProcessReason || (recording?.status === "recording" ? "正在录制中，完整视频封装完成后才能打标与手动切片" : "选择已完成录制后可后处理");
  const firstCandidate = rows[0];
  const activityLabel = activeRound?.activity || defaultActivity || roundForm.activity || "歌手 2026";
  const activeRoundLabel = activeRound ? roundName(activeRound) : "等待场次";
  const activeQuality = recording?.status === "recording" ? "录制中" : activeRound?.pageUrl ? "已解析" : "待检测";
  const activePageUrl = activeRound?.pageUrl || roundForm.url || "等待识别";
  const independentRecordingRunning = recordingRounds.some((round) => round.recording?.status === "recording");
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
                placeholder={`例如：第 ${realtimeRounds.length + 1} 轮 选歌`}
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
            <span className="inline-flex items-center gap-2"><Clock size={15} /> 可发布轮次 {publishableRounds.length} 个，其中实时 {realtimeRounds.length} 个，片段分析 {analysisRounds.length} 个。</span>
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
          <p className="mt-3 truncate text-xs text-ops-muted">公开链接：{publicResultsUrl || new URL("/studio/public", window.location.origin).toString()}</p>
        </OpsPanel>
      </div>

      <OpsPanel title="录制后处理" className="min-h-[560px]">
        <div className="mb-5 rounded-3xl border border-white/10 bg-black/20 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <strong className="block text-sm text-slate-100">独立录制任务</strong>
              <p className="mt-1 text-xs leading-5 text-ops-muted">用于不能实时盯直播的场景：完整录制视频与弹幕，结束后自动按设置切片，再进入后处理。</p>
            </div>
            <span className="rounded-full bg-white/[0.06] px-3 py-1 text-xs font-black text-ops-muted">不会改变实时运营按钮逻辑</span>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto_auto] gap-3 max-xl:grid-cols-2 max-sm:grid-cols-1">
            <Field label="录制名称">
              <input className="ops-input" value={recordingForm.name} onChange={(event) => setRecordingForm({ ...recordingForm, name: event.target.value })} placeholder={`${recordingForm.activity || "直播"} 全程录制`} />
            </Field>
            <Field label="官方活动页或直播 URL">
              <input className="ops-input" value={recordingForm.url} onChange={(event) => setRecordingForm({ ...recordingForm, url: event.target.value })} placeholder="留空使用活动监控/系统配置链接" />
            </Field>
            <button type="button" className="orange-glow self-end inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl bg-ops-orange px-5 text-sm font-black text-[#1b0d03] transition hover:brightness-110 disabled:opacity-50" disabled={independentRecordingRunning || startFullRecording.isPending} onClick={() => startFullRecording.mutate()}>
              <VideoCamera size={18} weight="fill" />
              开始录制
            </button>
            <button type="button" className="self-end inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-red-400/35 bg-red-400/15 px-5 text-sm font-black text-red-100 transition hover:bg-red-400/20 disabled:opacity-50" disabled={!recordingRound?.recording || recordingRound.recording.status !== "recording" || stopFullRecording.isPending} onClick={() => stopFullRecording.mutate()}>
              <Stop size={18} weight="fill" />
              结束录制
            </button>
          </div>
        </div>
        <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-4">
            <select className="ops-input min-w-0 max-w-[420px]" value={recordingRound?.id || ""} onChange={(event) => setSelectedRecordingId(event.target.value)}>
              {recordingRounds.map((item) => (
                <option key={item.id} value={item.id}>{item.activity || "未分类活动"} / {roundName(item)}</option>
              ))}
              {!recordingRounds.length && <option value="">暂无录制</option>}
            </select>
            <span className="inline-flex items-center gap-2 text-sm text-ops-muted">
              <span className={`size-2 rounded-full ${recording?.status === "recording" ? "bg-emerald-400" : canPostProcess ? "bg-blue-400" : "bg-white/25"}`} />
              {recording?.status === "recording" ? "录制中" : canPostProcess ? "可后处理" : "等待完整录制"}
            </span>
            <span className="font-mono text-sm text-ops-muted">{formatClockDuration(recordingDuration)}</span>
          </div>
          <span className={`rounded-full px-3 py-1 text-xs font-black ${canPostProcess ? "bg-emerald-400/12 text-emerald-200" : "bg-orange-400/12 text-ops-gold"}`}>
            {postProcessReason}
          </span>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_360px] gap-5 max-2xl:grid-cols-[minmax(0,1fr)_330px] max-lg:grid-cols-1">
          <div className="grid gap-4">
            <div className="overflow-hidden rounded-3xl border border-white/10 bg-black/80 shadow-2xl">
              {canPostProcess && recording?.videoUrl ? (
                  <video className="aspect-video w-full bg-black" controls preload="metadata" src={recording.videoUrl} />
                ) : (
                  <div className="grid aspect-video w-full place-items-center bg-black text-center text-ops-muted">
                    <div>
                      <Play size={82} weight="fill" className="mx-auto text-white/35" />
                      <p className="mt-3 text-sm">{postProcessReason}</p>
                    </div>
                  </div>
                )}
              <div className="flex flex-wrap items-center gap-3 border-t border-white/10 px-4 py-3 text-xs text-slate-200">
                <Play size={16} weight="fill" />
                <span className="font-mono">{formatClockDuration(Math.min(recordingDuration, Number(clipForm.startSeconds || 0)))} / {formatClockDuration(recordingDuration)}</span>
                <span className="ml-auto text-ops-muted">完整视频完成后开放打标与手动切片</span>
              </div>
            </div>
            <div className="grid content-center gap-4 rounded-3xl border border-white/10 bg-black/20 p-4">
              <RecordingRuler density={density} maxDensity={maxDensity} markers={markers} clips={clips} durationSeconds={recordingDuration} />
              <div className="grid grid-cols-3 gap-3 max-sm:grid-cols-1">
                <MiniMetric label="自动切片" value={recording?.autoSplitStatus || "-"} />
                <MiniMetric label="已打标" value={`${markers.length}`} />
                <MiniMetric label="手动片段" value={`${manualClips.length}`} />
              </div>
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-black/20 p-4">
            <div className="grid grid-cols-2 gap-3">
              <button type="button" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-orange-400/45 bg-orange-400/15 px-4 text-sm font-black text-ops-gold disabled:opacity-45" disabled={!canPostProcess || addMarker.isPending} onClick={() => addMarker.mutate()}>
                <BookmarkSimple size={18} weight="bold" />
                添加标记
              </button>
              <button type="button" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-blue-400/45 bg-blue-400/15 px-4 text-sm font-black text-blue-100 disabled:opacity-45" disabled={!canPostProcess || createClip.isPending} onClick={() => createClip.mutate()}>
                <Scissors size={18} weight="bold" />
                截取片段
              </button>
              <button type="button" className="col-span-2 inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-emerald-400/45 bg-emerald-400/15 px-4 text-sm font-black text-emerald-100 disabled:opacity-45" disabled={!clips.length || createAnalysisRound.isPending} onClick={() => {
                const latestClip = clips[clips.length - 1];
                if (latestClip) createAnalysisRound.mutate({ clipId: latestClip.id, name: latestClip.label || "片段分析" });
              }}>
                <Gauge size={18} weight="bold" />
                生成最近片段分析场次
              </button>
            </div>
            <p className="mt-3 rounded-2xl border border-white/10 bg-white/[0.035] px-4 py-3 text-xs leading-6 text-ops-muted">
              {postProcessReason}。录制中的弹幕密度会继续刷新，但视频打标和手动切片只读取已完成的完整文件。
            </p>
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
            <div className="mt-5 flex items-center justify-between gap-3">
              <span className="text-sm text-ops-muted">已创影片段（{clips.length}，自动 {autoClips.length}，手动 {manualClips.length}）</span>
              <span className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-black text-slate-100">
                可导出 JSONL / 生成场次
              </span>
            </div>
            <div className="mt-3 grid max-h-[420px] gap-2 overflow-y-auto pr-1">
              {clips.map((clip) => {
                const roundId = encodeURIComponent(recordingRound?.id || "");
                const clipId = encodeURIComponent(clip.id);
                const danmakuUrl = clip.danmakuUrl || `/api/recordings/${roundId}/clips/${clipId}.jsonl`;
                const rawDanmakuUrl = clip.rawDanmakuUrl || `/api/recordings/${roundId}/clips/${clipId}/raw.jsonl`;
                return (
                <div key={clip.id} className="rounded-2xl border border-white/10 bg-white/[0.035] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm text-slate-100">{clip.label}</span>
                    <span className={`rounded-full px-3 py-1 text-xs font-black ${clip.kind === "auto" ? "bg-blue-400/12 text-blue-200" : "bg-emerald-400/12 text-emerald-200"}`}>{clip.kind === "auto" ? "自动切片" : "手动切片"}</span>
                  </div>
                  <span className="mt-1 block font-mono text-xs text-ops-muted">{formatClockDuration(clip.startSeconds)} - {formatClockDuration(clip.endSeconds)}</span>
                  <div className="mt-3 grid grid-cols-3 gap-2 max-sm:grid-cols-1">
                    <a className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-xs font-black text-slate-100 transition hover:bg-white/[0.08]" href={danmakuUrl}>
                      <DownloadSimple size={15} />
                      分析 JSONL
                    </a>
                    <a className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-xs font-black text-slate-100 transition hover:bg-white/[0.08]" href={rawDanmakuUrl}>
                      <DownloadSimple size={15} />
                      原始 JSONL
                    </a>
                    <button
                      type="button"
                      className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-xl border border-emerald-400/45 bg-emerald-400/15 px-3 text-xs font-black text-emerald-100 transition hover:bg-emerald-400/20 disabled:opacity-45"
                      disabled={createAnalysisRound.isPending}
                      onClick={() => createAnalysisRound.mutate({ clipId: clip.id, name: clip.label || "片段分析" })}
                    >
                      <Gauge size={15} weight="bold" />
                      发布为场次
                    </button>
                  </div>
                </div>
                );
              })}
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
  const label = round.kind === "recording" ? (running ? "录制中" : "录制完成") : round.kind === "analysis" ? "片段分析" : running ? "进行中" : precise ? "已发布" : "已结束";
  const className = running
    ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
    : round.kind === "analysis"
      ? "border-orange-400/25 bg-orange-400/10 text-ops-gold"
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
      autoSplitEnabled: recording.auto_split_enabled !== false,
      autoSplitMinutes: Math.max(5, Math.round(Number(recording.auto_split_seconds || 3600) / 60)),
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
    mutationFn: () => apiPost<FeishuPushResult>("/api/feishu/push-card"),
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
  const runtime = ((settings as { runtime?: { restartRequired?: boolean; restartFields?: string[] } } | undefined)?.runtime || {});
  const saveResult = save.data as { restartRequired?: boolean; restartFields?: string[]; warnings?: string[] } | undefined;
  const restartFields = saveResult?.restartFields?.length
    ? saveResult.restartFields
    : status?.health?.restartFields?.length
      ? status.health.restartFields
      : runtime.restartFields || [];
  const restartRequired = Boolean(saveResult?.restartRequired || status?.health?.restartRequired || runtime.restartRequired || restartFields.length);
  const github = config.github || {};
  const feishu = config.feishu || {};
  const recording = config.recording || {};
  const operatorAuth = config.operator_auth || {};
  const monitor = status?.monitor;
  const githubRepoLabel = form.githubOwner || form.githubRepo ? `${form.githubOwner || "-"}/${form.githubRepo || "-"} (${form.githubBranch || "main"})` : "-";
  const updateBadgeTone = updateView?.inProgress ? "orange" : updateView?.updateAvailable ? "blue" : updateView?.dirty ? "red" : "green";
  const updateBadgeText = updateView?.inProgress ? "升级中" : updateView?.updateAvailable ? "发现新版本" : updateView?.dirty ? "工作区有改动" : "已是最新";
  const hotReloadItems = [
    "弹幕轮询间隔",
    "重连间隔",
    "去重缓存上限",
    "飞书白名单",
    "GitHub 发布路径",
    "运营登录策略",
    "公开页面 URL",
    "自动切片配置"
  ];
  const nextRoundItems = [
    "默认活动名称",
    "候选人与别名",
    "多人弹幕策略",
    "默认清晰度",
    "录屏直播流 URL",
    "room_id / camera_id"
  ];
  const restartImpactItems = restartFields.length ? restartFields : ["监听地址与端口", "主数据目录", "服务进程级目录"];
  return (
    <section className="grid gap-4">
      <PageHeading
        kicker="Runtime Config"
        title="系统配置"
        description="低频配置集中在这里；活动 URL 与日常操作请在活动监控和运营工作区完成。保存后会热应用可切换项，并标注下一场生效或需安全重启的影响。"
      />
      {save.error && <p className="mb-4 rounded-2xl border border-red-400/30 bg-red-400/10 px-5 py-4 text-sm text-red-100">{String((save.error as Error).message || save.error)}</p>}
      {Boolean(save.data) && (
        <p className="mb-4 rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-5 py-4 text-sm text-emerald-100">
          配置已保存。{restartRequired ? "部分配置需要安全重启。" : "可热应用配置已生效。"}{!!saveResult?.warnings?.length && ` 提醒：${saveResult.warnings.join("；")}`}
        </p>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(250px,.74fr)] gap-4 max-[1680px]:grid-cols-3 max-2xl:grid-cols-2 max-lg:grid-cols-1">
        <SettingsColumn icon={<LinkSimple size={24} weight="bold" />} title="连接与账号">
          <div className="grid gap-4">
            <SettingsBlock
              icon={<Broadcast size={18} weight="bold" />}
              title="芒果 TV 扫码登录"
              action={(
                <StatusBadge tone={mgtvView?.cookieConfigured ? "green" : mgtvView?.status === "pending" ? "orange" : "neutral"}>
                  {mgtvView?.cookieConfigured ? "已登录" : mgtvView?.status === "pending" ? "等待扫码" : "未登录"}
                </StatusBadge>
              )}
            >
              <div className="flex items-start justify-between gap-3 max-sm:flex-col">
                <div className="min-w-0 flex-1">
                  <SettingsRow label="账号" value={mgtvView?.user?.nickname || mgtvView?.user?.uid || "-"} />
                  <SettingsRow label="VIP 状态" value={mgtvView?.user?.isVip ? `是${mgtvView.user.vipType ? ` · ${mgtvView.user.vipType}` : ""}` : mgtvView?.cookieConfigured ? "否/未知" : "未知"} />
                  <SettingsRow label="登录方式" value={mgtvView?.loginProtocolAvailable ? mgtvView.loginProtocol || "mgtv_http_qr" : "待检测"} />
                  {(mgtvView?.error || startMgtvAuth.error || mgtvAuth.error) && (
                    <p className="mt-3 rounded-xl border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs text-red-100">{String(mgtvView?.error || (startMgtvAuth.error as Error)?.message || (mgtvAuth.error as Error)?.message)}</p>
                  )}
                </div>
                <div className="grid size-28 shrink-0 place-items-center rounded-2xl border border-white/10 bg-white/[0.035] p-2 max-sm:h-28 max-sm:w-full">
                  {mgtvView?.screenshot ? <img className="max-h-28 rounded-xl" src={mgtvView.screenshot} alt="芒果 TV 登录二维码" /> : <span className="text-center text-xs text-ops-muted">二维码将在扫码登录时显示</span>}
                </div>
              </div>
              <p className="mt-3 text-xs leading-6 text-ops-muted">用于检测高清/VIP 权限与解析可录制播放流；登录态只保存在服务器配置中。</p>
              <div className="mt-4 grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                <SettingsButton variant="primary" disabled={startMgtvAuth.isPending || mgtvView?.status === "pending"} onClick={() => startMgtvAuth.mutate()}>
                  {mgtvView?.cookieConfigured ? "重新扫码" : "发起扫码登录"}
                </SettingsButton>
                <SettingsButton onClick={() => queryClient.invalidateQueries({ queryKey: ["mgtv-auth"] })}>刷新状态</SettingsButton>
              </div>
            </SettingsBlock>

            <SettingsBlock
              icon={<Robot size={18} weight="bold" />}
              title="飞书 Bot"
              action={(
                <StatusBadge tone={feishuView?.status === "bound" || feishuView?.appSecretConfigured ? "green" : feishuView?.status === "pending" ? "orange" : "neutral"}>
                  {feishuView?.status === "pending" ? "等待授权" : feishuView?.appSecretConfigured ? "已绑定" : "未绑定"}
                </StatusBadge>
              )}
            >
              <SettingsToggle label="启用飞书 Bot" checked={Boolean(form.feishuEnabled)} onChange={(value) => update("feishuEnabled", value)} compact />
              <div className="mt-4 grid gap-1">
                <SettingsRow label="连接状态" value={feishuView?.workerAlive ? "长连接运行中" : "未运行"} tone={feishuView?.workerAlive ? "green" : "neutral"} />
                <SettingsRow label="App ID" value={maskSecret(feishuView?.appId || form.feishuAppId || "") || "-"} />
                <SettingsRow label="授权 open_id" value={maskSecret(feishuView?.openId || "") || "-"} />
                <SettingsRow label="租户" value={feishuView?.tenantBrand || "-"} />
                {feishuView?.userCode && <p className="mt-2 rounded-xl border border-orange-400/30 bg-orange-400/10 px-3 py-2 font-mono text-xs text-ops-gold">授权码：{feishuView.userCode}</p>}
                {feishuView?.verificationUrl && <a className="mt-2 rounded-xl border border-blue-400/30 bg-blue-400/10 px-3 py-2 text-xs font-black text-blue-100" href={feishuView.verificationUrl} target="_blank" rel="noreferrer">打开飞书授权页</a>}
                {(feishuView?.error || startFeishuBinding.error || feishuBinding.error || sendFeishuTestCard.error) && (
                  <Notice tone="red">{String(feishuView?.error || (startFeishuBinding.error as Error)?.message || (feishuBinding.error as Error)?.message || (sendFeishuTestCard.error as Error)?.message)}</Notice>
                )}
                {sendFeishuTestCard.isSuccess && (
                  <Notice tone={sendFeishuTestCard.data?.failedCount ? "orange" : "green"}>
                    测试卡片已发送到 {sendFeishuTestCard.data?.count || 0} 个飞书会话。
                    {sendFeishuTestCard.data?.failedCount ? ` 已跳过 ${sendFeishuTestCard.data.failedCount} 个失效目标。` : ""}
                    {sendFeishuTestCard.data?.prunedOpenIdCount ? ` 已自动清理 ${sendFeishuTestCard.data.prunedOpenIdCount} 个旧 App open_id。` : ""}
                  </Notice>
                )}
              </div>
              <div className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))] gap-3">
                <SettingsButton variant="primary" disabled={startFeishuBinding.isPending || feishuView?.status === "pending"} onClick={() => startFeishuBinding.mutate()}>
                  {feishuView?.appSecretConfigured ? "重新绑定" : "发起绑定"}
                </SettingsButton>
                <SettingsButton variant="blue" disabled={sendFeishuTestCard.isPending} onClick={() => sendFeishuTestCard.mutate()}>发送测试卡片</SettingsButton>
              </div>
              <div className="mt-4 grid gap-3">
                <Field label="飞书连接模式">
                  <select className="ops-input" value={form.feishuMode || "websocket"} onChange={(event) => update("feishuMode", event.target.value)}>
                    <option value="websocket">WebSocket 长连接</option>
                    <option value="webhook">HTTP 回调</option>
                  </select>
                </Field>
                <Field label="飞书 App ID"><input className="ops-input" value={form.feishuAppId || ""} onChange={(event) => update("feishuAppId", event.target.value)} /></Field>
                <Field label="App Secret（留空保留）"><input className="ops-input" type="password" value={form.feishuAppSecret || ""} onChange={(event) => update("feishuAppSecret", event.target.value)} /></Field>
                <Field label="Verification Token（Webhook 留空保留）"><input className="ops-input" type="password" value={form.feishuVerificationToken || ""} onChange={(event) => update("feishuVerificationToken", event.target.value)} /></Field>
                <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                  <Field label="允许 open_id"><textarea className="ops-input min-h-24" value={form.feishuOpenIds || ""} onChange={(event) => update("feishuOpenIds", event.target.value)} /></Field>
                  <Field label="允许 chat_id"><textarea className="ops-input min-h-24" value={form.feishuChatIds || ""} onChange={(event) => update("feishuChatIds", event.target.value)} /></Field>
                </div>
              </div>
            </SettingsBlock>

            <SettingsBlock
              icon={<GlobeHemisphereWest size={18} weight="bold" />}
              title="GitHub 发布"
              action={<StatusBadge tone={github.token_configured ? "green" : form.githubEnabled ? "orange" : "neutral"}>{github.token_configured ? "Token 已配置" : form.githubEnabled ? "待配置" : "未启用"}</StatusBadge>}
            >
              <SettingsToggle label="启用 GitHub 发布" checked={Boolean(form.githubEnabled)} onChange={(value) => update("githubEnabled", value)} compact />
              <div className="mt-4 grid gap-1">
                <SettingsRow label="仓库" value={githubRepoLabel} />
                <SettingsRow label="结果文件路径" value={form.githubPath || "-"} />
                <SettingsRow label="公开页面 URL" value={form.publicResultsUrl || "-"} />
              </div>
              <div className="mt-4 grid gap-3">
                <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                  <Field label="Owner"><input className="ops-input" value={form.githubOwner || ""} onChange={(event) => update("githubOwner", event.target.value)} /></Field>
                  <Field label="Repo"><input className="ops-input" value={form.githubRepo || ""} onChange={(event) => update("githubRepo", event.target.value)} /></Field>
                </div>
                <div className="grid grid-cols-[130px_minmax(0,1fr)] gap-3 max-sm:grid-cols-1">
                  <Field label="分支"><input className="ops-input" value={form.githubBranch || ""} onChange={(event) => update("githubBranch", event.target.value)} /></Field>
                  <Field label="结果文件路径"><input className="ops-input" value={form.githubPath || ""} onChange={(event) => update("githubPath", event.target.value)} /></Field>
                </div>
                <Field label="公开结果页 URL"><input className="ops-input" value={form.publicResultsUrl || ""} onChange={(event) => update("publicResultsUrl", event.target.value)} /></Field>
                <Field label="Fine-grained Token（留空保留）"><input className="ops-input" type="password" value={form.githubToken || ""} onChange={(event) => update("githubToken", event.target.value)} /></Field>
              </div>
            </SettingsBlock>
          </div>
        </SettingsColumn>

        <SettingsColumn icon={<Broadcast size={24} weight="bold" />} title="采集与录制">
          <div className="grid gap-4">
            <SettingsBlock icon={<CheckCircle size={18} weight="bold" />} title="节目、候选人与计票">
              <div className="grid gap-3">
                <Field label="默认活动名称"><input className="ops-input" value={form.voteActivity || ""} onChange={(event) => update("voteActivity", event.target.value)} /></Field>
                <Field label="多人弹幕策略">
                  <select className="ops-input" value={form.votePolicy || "all"} onChange={(event) => update("votePolicy", event.target.value)}>
                    <option value="all">all · 每位各计 1 票</option>
                    <option value="review">review · 多人弹幕待审</option>
                  </select>
                </Field>
                <Field label="候选人与别名（每行：正式名, 别名1, 别名2）">
                  <textarea className="ops-input min-h-28" value={form.candidatesText || ""} onChange={(event) => update("candidatesText", event.target.value)} />
                </Field>
              </div>
            </SettingsBlock>

            <SettingsBlock icon={<ChatCircleDots size={18} weight="bold" />} title="弹幕采集参数">
              <div className="grid gap-3">
                <Field label="历史弹幕接口"><input className="ops-input" value={form.historyApi || ""} onChange={(event) => update("historyApi", event.target.value)} /></Field>
                <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                  <Field label="轮询间隔（秒）"><input className="ops-input" type="number" min={1} value={form.pollSeconds || 2} onChange={(event) => update("pollSeconds", Number(event.target.value))} /></Field>
                  <Field label="重连间隔（秒）"><input className="ops-input" type="number" min={1} value={form.reconnectSeconds || 5} onChange={(event) => update("reconnectSeconds", Number(event.target.value))} /></Field>
                </div>
                <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                  <Field label="内存去重缓存"><input className="ops-input" type="number" value={form.dedupHotCacheSize || 200000} onChange={(event) => update("dedupHotCacheSize", Number(event.target.value))} /></Field>
                  <Field label="去重记录上限"><input className="ops-input" type="number" value={form.dedupMaxRecords || 100000000} onChange={(event) => update("dedupMaxRecords", Number(event.target.value))} /></Field>
                </div>
                <Field label="SQLite 去重路径"><input className="ops-input" value={form.dedupDbPath || ""} onChange={(event) => update("dedupDbPath", event.target.value)} /></Field>
                <span className="w-fit rounded-full bg-emerald-400/10 px-3 py-1 text-xs font-black text-emerald-200">空闲时热切换</span>
              </div>
            </SettingsBlock>

            <SettingsBlock icon={<VideoCamera size={18} weight="bold" />} title="直播录制参数">
              <SettingsToggle label="启用默认录屏" checked={Boolean(form.recordingEnabled)} onChange={(value) => update("recordingEnabled", value)} compact />
              <SettingsToggle label="录制完成后自动按时长切片" checked={form.autoSplitEnabled !== false} onChange={(value) => update("autoSplitEnabled", value)} compact />
              <div className="mt-4 grid gap-3">
                <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                  <Field label="默认清晰度"><input className="ops-input" value={form.preferredQuality || "auto"} onChange={(event) => update("preferredQuality", event.target.value)} /></Field>
                  <Field label="自动切片间隔（分钟）"><input className="ops-input" type="number" min={5} max={720} value={form.autoSplitMinutes || 60} onChange={(event) => update("autoSplitMinutes", Number(event.target.value))} /></Field>
                </div>
                <Field label="ffmpeg 路径"><input className="ops-input" value={form.ffmpegPath || ""} onChange={(event) => update("ffmpegPath", event.target.value)} /></Field>
                <Field label="录制目录"><input className="ops-input" value={form.recordingDirectory || ""} onChange={(event) => update("recordingDirectory", event.target.value)} /></Field>
                <Field label="录屏直播流 URL（留空保留）"><input className="ops-input" value={form.streamUrl || ""} onChange={(event) => update("streamUrl", event.target.value)} /></Field>
                <span className="w-fit rounded-full bg-emerald-400/10 px-3 py-1 text-xs font-black text-emerald-200">空闲时热切换</span>
              </div>
            </SettingsBlock>

            <SettingsBlock
              icon={<Lightning size={18} weight="bold" />}
              title="活动页与直播源"
              action={<StatusBadge tone={monitor?.config?.enabled ? "green" : "neutral"}>{monitor?.config?.enabled ? "监控中" : "未启用"}</StatusBadge>}
            >
              <div className="grid gap-3">
                <Field label="默认直播 URL"><input className="ops-input" value={form.mgtvUrl || ""} onChange={(event) => update("mgtvUrl", event.target.value)} /></Field>
                <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                  <Field label="room_id"><input className="ops-input" value={form.roomId || ""} onChange={(event) => update("roomId", event.target.value)} /></Field>
                  <Field label="camera_id"><input className="ops-input" value={form.cameraId || ""} onChange={(event) => update("cameraId", event.target.value)} /></Field>
                </div>
                <Field label="room_id 前缀"><input className="ops-input" value={form.flag || "liveshow"} onChange={(event) => update("flag", event.target.value)} /></Field>
                <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-3">
                  <SettingsRow label="检测状态" value={monitor?.state?.message || "由活动监控页管理"} tone={monitor?.state?.status === "source_ready" ? "green" : "neutral"} />
                  <SettingsRow label="当前清晰度" value={monitor?.state?.quality || recording.last_detected_quality || "-"} />
                  <SettingsRow label="可用清晰度" value={(monitor?.state?.availableQualities || recording.available_qualities || []).join(" / ") || "-"} />
                </div>
              </div>
            </SettingsBlock>
          </div>
        </SettingsColumn>

        <SettingsColumn icon={<ShieldCheck size={24} weight="bold" />} title="安全、存储与更新">
          <div className="grid gap-4">
            <SettingsBlock
              icon={<ShieldCheck size={18} weight="bold" />}
              title="运营端密码"
              action={<StatusBadge tone={form.authEnabled ? "green" : "neutral"}>{form.authEnabled ? "已启用" : "未启用"}</StatusBadge>}
            >
              <SettingsToggle label="启用运营端密码" checked={Boolean(form.authEnabled)} onChange={(value) => update("authEnabled", value)} compact />
              <div className="mt-4 grid gap-3">
                <Field label="设置新密码（留空保留）"><input className="ops-input" type="password" value={form.newPassword || ""} onChange={(event) => update("newPassword", event.target.value)} placeholder={operatorAuth.password_configured ? "已配置，留空保留" : "至少 10 个字符"} /></Field>
                <div className="grid grid-cols-3 gap-3 max-sm:grid-cols-1">
                  <Field label="会话小时"><input className="ops-input" type="number" value={form.sessionHours || 12} onChange={(event) => update("sessionHours", Number(event.target.value))} /></Field>
                  <Field label="失败上限"><input className="ops-input" type="number" value={form.maxFailures || 5} onChange={(event) => update("maxFailures", Number(event.target.value))} /></Field>
                  <Field label="限速窗口（秒）"><input className="ops-input" type="number" value={form.failureWindowSeconds || 300} onChange={(event) => update("failureWindowSeconds", Number(event.target.value))} /></Field>
                </div>
                <SettingsToggle label="Secure Cookie" checked={Boolean(form.secureCookie)} onChange={(value) => update("secureCookie", value)} compact />
              </div>
            </SettingsBlock>

            <SettingsBlock icon={<Database size={18} weight="bold" />} title="存储目录">
              <div className="grid gap-3">
                <Field label="数据目录"><input className="ops-input" value={form.storageDirectory || ""} onChange={(event) => update("storageDirectory", event.target.value)} /></Field>
                <Field label="录制目录"><input className="ops-input" value={form.recordingDirectory || ""} onChange={(event) => update("recordingDirectory", event.target.value)} /></Field>
                <div className="grid gap-2 text-xs">
                  <SettingsRow label="数据目录可用" value={formatBytes(status?.disk?.data?.freeBytes)} />
                  <SettingsRow label="录制目录可用" value={formatBytes(status?.disk?.recordings?.freeBytes)} />
                </div>
              </div>
            </SettingsBlock>

            <SettingsBlock icon={<GlobeHemisphereWest size={18} weight="bold" />} title="监听地址和端口">
              <div className="grid gap-3">
                <div className="grid grid-cols-[1fr_120px] gap-3 max-sm:grid-cols-1">
                  <Field label="绑定地址"><input className="ops-input" value={form.listenHost || ""} onChange={(event) => update("listenHost", event.target.value)} /></Field>
                  <Field label="HTTP 端口"><input className="ops-input" type="number" value={form.listenPort || 8080} onChange={(event) => update("listenPort", Number(event.target.value))} /></Field>
                </div>
                <Field label="外部访问地址"><input className="ops-input" value={form.publicBaseUrl || ""} onChange={(event) => update("publicBaseUrl", event.target.value)} /></Field>
                <span className="w-fit rounded-full bg-orange-400/10 px-3 py-1 text-xs font-black text-ops-gold">需要安全重启</span>
              </div>
            </SettingsBlock>

            <SettingsBlock
              icon={<UploadSimple size={18} weight="bold" />}
              title="程序更新"
              action={<StatusBadge tone={updateBadgeTone}>{updateBadgeText}</StatusBadge>}
            >
              <div className="grid grid-cols-2 gap-3 text-xs leading-6 text-ops-muted">
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
                <SettingsButton disabled={updateStatus.isFetching} onClick={() => queryClient.invalidateQueries({ queryKey: ["update-status"] })}>检查更新</SettingsButton>
                <SettingsButton variant="primary" disabled={!updateView?.canApply || updateView?.inProgress || applyUpdate.isPending} onClick={() => applyUpdate.mutate()}>一键升级</SettingsButton>
                <SettingsButton variant="orange" disabled={!restartRequired || restartService.isPending} onClick={() => restartService.mutate()}>安全重启</SettingsButton>
              </div>
            </SettingsBlock>
          </div>
        </SettingsColumn>

        <aside className="grid content-start gap-4 max-[1680px]:col-span-3 max-2xl:col-span-2 max-lg:col-span-1">
          <SettingsImpactCard tone="green" title="立即生效（热重载）" count={hotReloadItems.length} items={hotReloadItems} />
          <SettingsImpactCard tone="blue" title="下一场生效" count={nextRoundItems.length} items={nextRoundItems} />
          <SettingsImpactCard tone="orange" title="需要安全重启" count={restartImpactItems.length} items={restartImpactItems} note={restartRequired ? "重启期间服务会短暂不可用，建议空窗期执行。" : "当前暂无待重启配置。"} />
        </aside>
      </div>

      <div className="glass grid grid-cols-[minmax(0,1fr)_220px_220px_220px] items-center gap-3 rounded-3xl p-4 max-xl:grid-cols-2 max-sm:grid-cols-1">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-12 shrink-0 place-items-center rounded-2xl border border-white/10 bg-white/[0.05] text-ops-muted">
            <Database size={24} />
          </span>
          <div className="min-w-0">
            <strong className="block truncate text-sm text-slate-100">配置已加载</strong>
            <span className="block truncate text-xs text-ops-muted">运行状态：{restartRequired ? `待重启 · ${restartFields.join(", ") || "配置变更"}` : "可热应用配置正常"} · 当前版本 {updateView?.currentShort || "-"}</span>
          </div>
        </div>
        <SettingsButton variant="primary" disabled={save.isPending} onClick={() => save.mutate()}>
          <Lightning size={18} weight="bold" />
          保存并热应用
        </SettingsButton>
        <SettingsButton variant="orange" disabled={!restartRequired || restartService.isPending} onClick={() => restartService.mutate()}>
          <WarningCircle size={18} weight="bold" />
          安全重启服务
        </SettingsButton>
        <SettingsButton onClick={() => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })}>
          <DownloadSimple size={18} weight="bold" />
          重新读取配置
        </SettingsButton>
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
      auto_split_enabled: form.autoSplitEnabled !== false,
      auto_split_seconds: Math.max(5, Number(form.autoSplitMinutes || 60)) * 60,
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

function SettingsToggle({ label, checked, onChange, compact = false }: { label: string; checked: boolean; onChange: (value: boolean) => void; compact?: boolean }) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className={`flex items-center justify-between gap-4 rounded-2xl border border-white/10 bg-black/20 text-left transition hover:bg-white/[0.04] active:translate-y-px ${compact ? "px-3 py-2.5" : "p-4"}`}>
      <strong className="text-sm text-white">{label}</strong>
      <span className={`h-7 w-12 rounded-full p-1 ${checked ? "bg-ops-orange" : "bg-white/10"}`}>
        <i className={`block size-5 rounded-full bg-white transition ${checked ? "translate-x-5" : ""}`} />
      </span>
    </button>
  );
}

function SettingsColumn({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="glass relative min-w-0 overflow-hidden rounded-3xl p-4">
      <div className="mb-4 flex items-center gap-3 border-b border-white/10 pb-4">
        <span className="grid size-10 place-items-center rounded-2xl bg-orange-400/10 text-ops-orange">{icon}</span>
        <h3 className="text-xl font-black tracking-[-0.045em] text-slate-100">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function SettingsBlock({ icon, title, action, children }: { icon: ReactNode; title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="min-w-0 rounded-3xl border border-white/10 bg-black/20 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,.04)]">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-orange-400/10 text-ops-orange">{icon}</span>
          <strong className="truncate text-base font-black text-slate-100">{title}</strong>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      {children}
    </section>
  );
}

function SettingsRow({ label, value, tone = "neutral" }: { label: string; value: ReactNode; tone?: "green" | "orange" | "blue" | "red" | "neutral" }) {
  const toneClass = {
    green: "text-emerald-200",
    orange: "text-ops-gold",
    blue: "text-blue-200",
    red: "text-red-200",
    neutral: "text-slate-100"
  }[tone];
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 border-b border-white/[0.06] py-2 text-xs last:border-b-0 max-sm:grid-cols-1 max-sm:gap-1">
      <span className="text-ops-muted">{label}</span>
      <span className={`min-w-0 truncate font-medium ${toneClass}`} title={typeof value === "string" ? value : undefined}>{value || "-"}</span>
    </div>
  );
}

function Notice({ tone, children }: { tone: "green" | "orange" | "red" | "blue"; children: ReactNode }) {
  const toneClass = {
    green: "border-emerald-400/30 bg-emerald-400/10 text-emerald-100",
    orange: "border-orange-400/30 bg-orange-400/10 text-ops-gold",
    red: "border-red-400/30 bg-red-400/10 text-red-100",
    blue: "border-blue-400/30 bg-blue-400/10 text-blue-100"
  }[tone];
  return (
    <p className={`mt-2 min-w-0 max-w-full whitespace-pre-wrap break-words rounded-xl border px-3 py-2 text-xs leading-5 [overflow-wrap:anywhere] ${toneClass}`}>
      {children}
    </p>
  );
}

function SettingsButton({ children, onClick, disabled, variant = "ghost" }: { children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: "primary" | "orange" | "blue" | "ghost" }) {
  const variantClass = {
    primary: "orange-glow border-orange-300/30 bg-gradient-to-br from-[#ff9d35] to-[#ff7417] text-[#190d05]",
    orange: "border-orange-400/35 bg-orange-400/10 text-ops-gold hover:bg-orange-400/15",
    blue: "border-blue-400/30 bg-blue-400/15 text-blue-100 hover:bg-blue-400/20",
    ghost: "border-white/10 bg-white/[0.04] text-slate-100 hover:bg-white/[0.075]"
  }[variant];
  return (
    <button
      type="button"
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-black transition active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45 ${variantClass}`}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function SettingsImpactCard({ tone, title, count, items, note }: { tone: "green" | "blue" | "orange"; title: string; count: number; items: string[]; note?: string }) {
  const toneClass = tone === "green"
    ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200 marker:text-emerald-300"
    : tone === "blue"
      ? "border-blue-400/20 bg-blue-400/10 text-blue-200 marker:text-blue-300"
      : "border-orange-400/25 bg-orange-400/10 text-ops-gold marker:text-ops-orange";
  return (
    <section className={`rounded-3xl border p-4 ${toneClass}`}>
      <div className="flex items-center justify-between gap-3">
        <strong className="text-base font-black tracking-[-0.03em]">{title}</strong>
        <span className="rounded-full bg-white/10 px-3 py-1 font-mono text-xs font-black">{count} 项</span>
      </div>
      <ul className="mt-4 grid gap-2 pl-4 text-xs leading-6 marker:content-['•']">
        {items.map((item) => <li key={item} className="pl-2">{item}</li>)}
      </ul>
      {note && <p className="mt-4 text-xs leading-6 opacity-75">{note}</p>}
    </section>
  );
}

function maskSecret(value: string) {
  const raw = String(value || "");
  if (!raw) return "";
  if (raw.length <= 8) return raw;
  return `${raw.slice(0, 4)}${"*".repeat(Math.min(10, raw.length - 8))}${raw.slice(-4)}`;
}

function MachineStatusPage({ initial }: { initial?: SystemStatus }) {
  const [refreshSeconds, setRefreshSeconds] = useState(15);
  const status = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus, initialData: initial, refetchInterval: refreshSeconds ? refreshSeconds * 1000 : false });
  const metrics = useQuery({ queryKey: ["system-metrics", "15m"], queryFn: () => getSystemMetrics("15m"), refetchInterval: refreshSeconds ? refreshSeconds * 1000 : false });
  const logs = useQuery({ queryKey: ["system-logs", "machine", 8], queryFn: () => getSystemLogs(8), refetchInterval: refreshSeconds ? refreshSeconds * 1000 : false });
  const restartService = useMutation({
    mutationFn: () => apiPost("/api/restart"),
    onSuccess: () => {
      status.refetch();
      metrics.refetch();
      logs.refetch();
    }
  });
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
  const metricPoints = metrics.data?.points?.length
    ? metrics.data.points
    : history.map((item) => ({
      time: item.at,
      cpuPercent: item.cpu,
      memoryPercent: item.memory,
      rxBytesPerSecond: item.network,
      txBytesPerSecond: 0,
      danmakuPerSecond: item.danmaku
    }));
  const latestMetric = metricPoints.at(-1);
  const cpuPercent = clampPercent(payload?.cpu?.loadPercent ?? latestMetric?.cpuPercent ?? 0);
  const memoryTotal = Number(payload?.memory?.totalBytes || 0);
  const memoryUsed = Number(payload?.memory?.usedBytes || 0);
  const memoryPercent = memoryTotal ? clampPercent((memoryUsed / memoryTotal) * 100) : clampPercent(latestMetric?.memoryPercent || 0);
  const memoryAvailable = Number(payload?.memory?.availableBytes || Math.max(0, memoryTotal - memoryUsed));
  const dataDisk = payload?.disk?.data;
  const recordingDisk = payload?.disk?.recordings;
  const dataDiskPercent = diskUsagePercent(dataDisk);
  const recordingDiskPercent = diskUsagePercent(recordingDisk);
  const rxRate = Number(latestMetric?.rxBytesPerSecond || 0);
  const txRate = Number(latestMetric?.txBytesPerSecond || 0);
  const health = payload?.health?.status || "unknown";
  const healthOk = health === "ok";
  const logsItems = (logs.data?.events || logs.data?.items || []).slice(0, 6);
  const services = payload?.services || {};
  const serviceRows = [
    {
      name: "弹幕采集器",
      description: "采集直播间弹幕并写入数据",
      status: services.collector?.status || "idle",
      meta: services.collector?.activeRoundId ? "绑定当前场次" : "等待场次",
      icon: <ChatCircleDots size={18} weight="bold" />
    },
    {
      name: "录制进程",
      description: "独立录屏与后处理切片",
      status: services.recorder?.status || "idle",
      meta: services.recorder?.activeCount ? `${services.recorder.activeCount} 路录制` : services.recorder?.enabled ? "已启用" : "未启用",
      icon: <VideoCamera size={18} weight="bold" />
    },
    {
      name: "飞书长连接",
      description: "推送通知与接收卡片指令",
      status: services.feishu?.status || "disabled",
      meta: services.feishu?.status === "connected" ? "已连接" : "待连接",
      icon: <PaperPlaneTilt size={18} weight="bold" />
    },
    {
      name: "GitHub 发布",
      description: "发布结果到 GitHub Pages",
      status: services.github?.status || "disabled",
      meta: services.github?.status === "enabled" ? "正常" : "未启用",
      icon: <GlobeHemisphereWest size={18} weight="bold" />
    },
    {
      name: "活动监控",
      description: "检测开播、直播源和自动策略",
      status: services.monitor?.status || "disabled",
      meta: services.monitor?.taskRunning ? "后台运行" : services.monitor?.enabled ? "已启用" : "未启用",
      icon: <Broadcast size={18} weight="bold" />
    },
    {
      name: "自动更新器",
      description: "检查并应用程序更新",
      status: services.updater?.status || "idle",
      meta: services.updater?.status === "running" ? "执行中" : "空闲",
      icon: <UploadSimple size={18} weight="bold" />
    }
  ];
  const confirmRestart = () => {
    if (window.confirm("确认重启全部服务？正在采集或录制时请谨慎操作。")) {
      restartService.mutate();
    }
  };
  return (
    <section className="grid gap-4">
      <div className="flex items-start justify-between gap-5 max-lg:flex-col">
        <div>
          <h2 className="text-4xl font-black tracking-[-0.06em] max-sm:text-3xl">机器状态监控</h2>
          <p className="mt-2 max-w-3xl text-sm leading-7 text-ops-muted">
            实时监控服务器与服务运行状态，保障直播运营稳定可靠。
          </p>
        </div>
        <div className="flex w-auto flex-wrap items-center justify-end gap-3 max-sm:w-full max-sm:flex-col max-sm:items-stretch">
          <select className="ops-input min-h-11 w-auto min-w-44 max-sm:w-full" value={refreshSeconds} onChange={(event) => setRefreshSeconds(Number(event.target.value))}>
            <option value={0}>停止自动刷新</option>
            <option value={5}>自动刷新：5 秒</option>
            <option value={15}>自动刷新：15 秒</option>
            <option value={30}>自动刷新：30 秒</option>
          </select>
          <button
            type="button"
            className="orange-glow inline-flex min-h-11 items-center justify-center gap-2 rounded-2xl bg-ops-orange px-5 text-sm font-black text-[#1b0d03] transition hover:brightness-110 disabled:opacity-60"
            disabled={status.isFetching || metrics.isFetching || logs.isFetching}
            onClick={() => {
              status.refetch();
              metrics.refetch();
              logs.refetch();
            }}
          >
            <UploadSimple size={17} weight="bold" />
            立即刷新
          </button>
        </div>
      </div>

      {(status.error || metrics.error || logs.error || restartService.error) && (
        <div className="rounded-2xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100">
          {String((status.error as Error)?.message || (metrics.error as Error)?.message || (logs.error as Error)?.message || (restartService.error as Error)?.message)}
        </div>
      )}

      <div className="grid grid-cols-4 gap-4 max-2xl:grid-cols-2 max-md:grid-cols-1">
        <MachineHeroCard icon={<Clock size={30} />} tone="orange" label="系统时间" value={formatMachineDateTime(payload?.systemTime)} detail={payload?.timezone || "Asia/Shanghai"} />
        <MachineHeroCard icon={<Lightning size={30} />} tone="green" label="服务运行时长" value={formatDuration(payload?.uptimeSeconds)} detail={`自 ${formatMachineDateTime(payload?.startedAt)} 启动`} />
        <MachineHeroCard icon={<MonitorPlay size={30} />} tone="neutral" label="当前进程" value={payload?.process?.name || "mgtv-danmaku"} detail={`${payload?.host?.hostname || "本机"} · PID ${payload?.process?.pid || "-"} · RSS ${formatMachineBytes(payload?.process?.rssBytes || payload?.memory?.processRssBytes)}`} />
        <MachineHeroCard icon={<ShieldCheck size={30} weight="fill" />} tone={healthOk ? "green" : health === "error" ? "red" : "orange"} label="健康状态" value={healthOk ? "正常" : health === "warning" ? "需关注" : health === "error" ? "异常" : "未知"} detail={healthOk ? "所有核心服务运行正常" : `错误 ${payload?.health?.recentErrorCount || 0} 条 · ${payload?.health?.restartRequired ? "需要重启" : "查看日志"}`} />
      </div>

      <div className="grid grid-cols-4 gap-4 max-[1500px]:grid-cols-2 max-lg:grid-cols-1">
        <MachinePanel title="CPU" icon={<Pulse size={18} weight="bold" />}>
          <div className="grid grid-cols-[150px_minmax(0,1fr)] gap-4 max-sm:grid-cols-1">
            <MachineDonut value={cpuPercent} tone="green">
              <strong className="font-mono text-4xl font-black tracking-[-0.06em]">{Math.round(cpuPercent)}%</strong>
              <span className="text-xs text-ops-muted">使用率</span>
            </MachineDonut>
            <div className="grid content-center gap-3 text-sm">
              <MachineKv label="型号" value={payload?.cpu?.model || "未上报"} />
              <MachineKv label="负载（1m / 5m / 15m）" value={(payload?.cpu?.loadAverage || []).map((n) => Number(n).toFixed(2)).join(" / ") || "-"} />
              <MachineKv label="核心数" value={`${payload?.cpu?.count || "-"} vCPU`} />
              <MachineKv label="CPU 温度" value={formatCpuTemperature(payload?.cpu)} tone={payload?.cpu?.temperatureAvailable ? "green" : "neutral"} />
            </div>
          </div>
          <MachineFooterStats items={[["架构", payload?.cpu?.architecture || payload?.host?.machine || "-"], ["采样", formatMachineShortTime(payload?.generatedAt)], ["刷新", refreshSeconds ? `${refreshSeconds} 秒` : "手动"]]} />
        </MachinePanel>

        <MachinePanel title="内存" icon={<Database size={18} weight="bold" />}>
          <div className="grid grid-cols-[150px_minmax(0,1fr)] gap-4 max-sm:grid-cols-1">
            <MachineDonut value={memoryPercent} tone="green">
              <strong className="font-mono text-3xl font-black tracking-[-0.06em]">{formatMachineBytes(memoryUsed)}</strong>
              <span className="text-xs text-ops-muted">/ {formatMachineBytes(memoryTotal)} 使用中</span>
            </MachineDonut>
            <div className="grid content-center gap-3 text-sm">
              <MachineKv label="内存使用率" value={`${memoryPercent.toFixed(1)}%`} />
              <MachineKv label="进程 RSS" value={formatMachineBytes(payload?.memory?.processRssBytes || payload?.process?.rssBytes)} />
              <MachineKv label="可用内存" value={formatMachineBytes(memoryAvailable)} />
            </div>
          </div>
          <MachineFooterStats items={[["总内存", formatMachineBytes(memoryTotal)], ["已使用", formatMachineBytes(memoryUsed)], ["Python", payload?.python || "-"]]} />
        </MachinePanel>

        <MachinePanel title="网络" icon={<Broadcast size={18} weight="bold" />}>
          <div className="grid gap-3 text-sm">
            <MachineKv label="入站速度" value={formatByteRate(rxRate)} tone="blue" />
            <MachineKv label="出站速度" value={formatByteRate(txRate)} tone="orange" />
            <MachineKv label="累计流量" value={`入 ${formatMachineBytes(payload?.network?.rxBytes)} / 出 ${formatMachineBytes(payload?.network?.txBytes)}`} />
            <MachineKv label="网络采集" value={payload?.network?.available ? "可用" : "当前系统未上报"} />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 rounded-2xl border border-white/10 bg-black/20 p-3 text-xs max-sm:grid-cols-1">
            <MachineTinyStatus label="飞书 WebSocket" value={services.feishu?.status === "connected" ? "已连接" : "未连接"} tone={services.feishu?.status === "connected" ? "green" : "neutral"} />
            <MachineTinyStatus label="直播源" value={services.recordingSource?.configured ? "已配置" : "待配置"} tone={services.recordingSource?.configured ? "green" : "neutral"} />
          </div>
        </MachinePanel>

        <MachinePanel title="磁盘" icon={<Database size={18} weight="bold" />}>
          <div className="grid gap-4">
            <DiskUsageBar label="/data（数据目录）" percent={dataDiskPercent} used={dataDisk?.usedBytes} total={dataDisk?.totalBytes} />
            <DiskUsageBar label="/data/recordings（录制目录）" percent={recordingDiskPercent} used={recordingDisk?.usedBytes} total={recordingDisk?.totalBytes} />
          </div>
          <MachineFooterStats items={[["数据可用", formatMachineBytes(dataDisk?.freeBytes)], ["录制可用", formatMachineBytes(recordingDisk?.freeBytes)], ["最近备份", payload?.backup?.available ? formatMachineShortTime(payload.backup.latestAt) : "暂无"]]} />
        </MachinePanel>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(380px,.95fr)] gap-4 max-xl:grid-cols-1">
        <MachinePanel title="服务运行状态" icon={<Gauge size={18} weight="bold" />}>
          <div className="grid gap-2">
            {serviceRows.map((item) => (
              <ServiceStatusRow key={item.name} {...item} />
            ))}
          </div>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button type="button" className="ops-mini-button min-h-10 px-4" onClick={() => logs.refetch()}>刷新日志</button>
            <button type="button" className="ops-mini-button min-h-10 border-orange-400/35 text-ops-gold disabled:opacity-50" disabled={restartService.isPending} onClick={confirmRestart}>
              {restartService.isPending ? "正在重启" : "重启全部服务"}
            </button>
          </div>
        </MachinePanel>

        <MachinePanel title="最近告警" icon={<WarningCircle size={18} weight="bold" />}>
          <div className="grid gap-2">
            {logsItems.map((event) => <MachineLogRow key={event.id || `${event.time}-${event.summary}`} event={event} />)}
            {!logsItems.length && (
              <div className="rounded-2xl border border-white/10 bg-black/20 px-4 py-6 text-center text-sm text-ops-muted">
                暂无系统事件。服务运行一段时间后会在这里显示最近日志。
              </div>
            )}
          </div>
        </MachinePanel>
      </div>

      <MachinePanel title="性能趋势（最近 15 分钟）" icon={<Pulse size={18} weight="bold" />}>
        <div className="grid grid-cols-4 gap-4 max-[1500px]:grid-cols-2 max-md:grid-cols-1">
          <MachineTrendCard
            label="CPU 使用率（%）"
            value={`${Math.round(cpuPercent)}%`}
            series={[{ name: "CPU", color: "#4aa3ff", values: metricPoints.map((item) => Number(item.cpuPercent || 0)) }]}
            maxValue={100}
            points={metricPoints}
          />
          <MachineTrendCard
            label="内存使用率（%）"
            value={`${memoryPercent.toFixed(1)}%`}
            series={[{ name: "内存", color: "#58d985", values: metricPoints.map((item) => Number(item.memoryPercent || 0)) }]}
            maxValue={100}
            points={metricPoints}
          />
          <MachineTrendCard
            label="网络流量（B/s）"
            value={`入 ${formatByteRate(rxRate)} · 出 ${formatByteRate(txRate)}`}
            series={[
              { name: "入站", color: "#4aa3ff", values: metricPoints.map((item) => Number(item.rxBytesPerSecond || 0)) },
              { name: "出站", color: "#ff861f", values: metricPoints.map((item) => Number(item.txBytesPerSecond || 0)) }
            ]}
            points={metricPoints}
          />
          <MachineTrendCard
            label="弹幕速率（条/秒）"
            value={`${Number(latestMetric?.danmakuPerSecond || 0).toFixed(1)} 条/秒`}
            series={[{ name: "弹幕", color: "#b967ff", values: metricPoints.map((item) => Number(item.danmakuPerSecond || 0)) }]}
            points={metricPoints}
          />
        </div>
        <p className="mt-4 flex items-center gap-2 rounded-2xl border border-blue-400/20 bg-blue-400/10 px-4 py-3 text-xs leading-6 text-blue-100">
          <span className="grid size-5 place-items-center rounded-full bg-blue-400/20 font-mono">i</span>
          所有指标每 {refreshSeconds || "手动"} 秒更新一次；若数据异常，请检查网络、录制目录和相关服务状态。
        </p>
      </MachinePanel>
    </section>
  );
}

function MachineHeroCard({ icon, tone, label, value, detail }: { icon: ReactNode; tone: "orange" | "green" | "blue" | "red" | "neutral"; label: string; value: ReactNode; detail: ReactNode }) {
  const toneClass = machineToneClass(tone);
  return (
    <article className="glass min-w-0 rounded-3xl p-5">
      <div className="flex min-w-0 items-center gap-4">
        <span className={`grid size-14 shrink-0 place-items-center rounded-2xl ${toneClass}`}>{icon}</span>
        <div className="min-w-0">
          <span className="block text-sm text-ops-muted">{label}</span>
          <strong className="mt-1 block truncate text-2xl font-black tracking-[-0.04em] max-sm:text-xl">{value}</strong>
          <span className="mt-1 block truncate text-xs text-ops-muted">{detail}</span>
        </div>
      </div>
    </article>
  );
}

function MachinePanel({ title, icon, children, className = "" }: { title: string; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`glass relative min-w-0 overflow-hidden rounded-3xl p-5 ${className}`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-lg font-black tracking-[-0.04em]">
          {icon && <span className="text-ops-muted">{icon}</span>}
          {title}
        </h3>
      </div>
      {children}
    </section>
  );
}

function MachineDonut({ value, tone, children }: { value: number; tone: "green" | "orange" | "blue" | "red"; children: ReactNode }) {
  const safe = clampPercent(value);
  const color = tone === "green" ? "#58d985" : tone === "blue" ? "#4aa3ff" : tone === "red" ? "#ff6f61" : "#ff861f";
  return (
    <div className="grid place-items-center">
      <div
        className="grid size-36 place-items-center rounded-full"
        style={{ background: `conic-gradient(${color} ${safe * 3.6}deg, rgba(255,255,255,.10) 0deg)` }}
      >
        <div className="grid size-[6.7rem] place-items-center rounded-full bg-[#0a1117] text-center shadow-[inset_0_0_28px_rgba(0,0,0,.45)]">
          {children}
        </div>
      </div>
    </div>
  );
}

function MachineKv({ label, value, tone = "neutral" }: { label: string; value: ReactNode; tone?: "neutral" | "green" | "blue" | "orange" | "red" }) {
  const color = tone === "green" ? "text-ops-green" : tone === "blue" ? "text-blue-200" : tone === "orange" ? "text-ops-gold" : tone === "red" ? "text-red-200" : "text-slate-200";
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 border-b border-white/[0.08] pb-2 last:border-b-0 last:pb-0">
      <span className="min-w-0 truncate text-ops-muted">{label}</span>
      <strong className={`min-w-0 truncate text-right font-mono text-sm ${color}`}>{value}</strong>
    </div>
  );
}

function MachineFooterStats({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/10 pt-3 max-sm:grid-cols-1">
      {items.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <span className="block truncate text-[11px] text-ops-subtle">{label}</span>
          <strong className="mt-1 block truncate text-xs text-slate-200">{value}</strong>
        </div>
      ))}
    </div>
  );
}

function MachineTinyStatus({ label, value, tone }: { label: string; value: string; tone: "green" | "neutral" }) {
  return (
    <span className="flex min-w-0 items-center justify-between gap-2">
      <span className="truncate text-ops-muted">{label}</span>
      <strong className={`inline-flex items-center gap-1.5 ${tone === "green" ? "text-ops-green" : "text-slate-300"}`}>
        <span className={`size-2 rounded-full ${tone === "green" ? "bg-ops-green" : "bg-white/25"}`} />
        {value}
      </strong>
    </span>
  );
}

function DiskUsageBar({ label, percent, used, total }: { label: string; percent: number; used?: number; total?: number }) {
  const tone = percent >= 85 ? "red" : percent >= 70 ? "orange" : "green";
  const color = tone === "red" ? "bg-red-400" : tone === "orange" ? "bg-ops-orange" : "bg-ops-green";
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span className="truncate text-slate-200">{label}</span>
        <strong className={tone === "red" ? "text-red-200" : tone === "orange" ? "text-ops-gold" : "text-ops-green"}>{Math.round(percent)}%</strong>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-white/10">
        <span className={`block h-full rounded-full ${color}`} style={{ width: `${clampPercent(percent)}%` }} />
      </div>
      <p className="mt-2 text-xs text-ops-muted">{formatMachineBytes(used)} / {formatMachineBytes(total)}</p>
    </div>
  );
}

function ServiceStatusRow({ name, description, status, meta, icon }: { name: string; description: string; status: string; meta: string; icon: ReactNode }) {
  const tone = serviceTone(status);
  return (
    <div className="grid grid-cols-[34px_minmax(0,1fr)_minmax(90px,.25fr)_96px] items-center gap-3 rounded-2xl border border-white/10 bg-black/20 px-3 py-2.5 text-sm max-sm:grid-cols-[32px_minmax(0,1fr)]">
      <span className="grid size-8 place-items-center rounded-xl bg-white/[0.06] text-slate-200">{icon}</span>
      <div className="min-w-0">
        <strong className="block truncate text-slate-100">{name}</strong>
        <span className="mt-0.5 block truncate text-xs text-ops-muted">{description}</span>
      </div>
      <span className="truncate font-mono text-xs text-ops-muted max-sm:col-start-2">{meta}</span>
      <span className={`inline-flex min-h-8 items-center justify-center rounded-xl border px-3 text-xs font-black ${tone}`}>{serviceStatusLabel(status)}</span>
    </div>
  );
}

function MachineLogRow({ event }: { event: SystemLogEvent }) {
  const level = String(event.level || "INFO").toUpperCase();
  const tone = level === "ERROR" ? "red" : level === "WARN" ? "orange" : "green";
  const icon = tone === "red" ? "!" : tone === "orange" ? "!" : "✓";
  const color = tone === "red" ? "bg-red-400 text-[#270805]" : tone === "orange" ? "bg-ops-orange text-[#1b0d03]" : "bg-ops-green text-[#062413]";
  return (
    <div className="grid grid-cols-[34px_minmax(0,1fr)_120px] items-center gap-3 rounded-2xl border border-white/10 bg-black/20 px-3 py-2.5 text-sm max-sm:grid-cols-[32px_minmax(0,1fr)]">
      <span className={`grid size-8 place-items-center rounded-full font-black ${color}`}>{icon}</span>
      <div className="min-w-0">
        <strong className={`block truncate ${tone === "orange" ? "text-ops-gold" : "text-slate-100"}`}>{event.summary || "系统事件"}</strong>
        <span className="mt-0.5 block truncate text-xs text-ops-muted">{event.detail || event.source || "-"}</span>
      </div>
      <span className="truncate text-right font-mono text-xs text-ops-muted max-sm:col-start-2 max-sm:text-left">{formatMachineShortTime(event.time)}</span>
    </div>
  );
}

function MachineTrendCard({ label, value, series, points, maxValue }: { label: string; value: string; series: Array<{ name: string; color: string; values: number[] }>; points: Array<{ time?: string }>; maxValue?: number }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <span className="text-sm font-bold text-slate-200">{label}</span>
        <strong className="text-right font-mono text-sm text-blue-200">{value}</strong>
      </div>
      <MachineSparkline series={series} maxValue={maxValue} />
      <div className="mt-2 flex items-center justify-between gap-2 font-mono text-[11px] text-ops-subtle">
        <span>{formatMachineMinute(points.at(0)?.time)}</span>
        <span>{formatMachineMinute(points.at(-1)?.time)}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-ops-muted">
        {series.map((item) => (
          <span key={item.name} className="inline-flex items-center gap-1.5">
            <i className="size-2 rounded-full" style={{ backgroundColor: item.color }} />
            {item.name}
          </span>
        ))}
      </div>
    </div>
  );
}

function MachineSparkline({ series, maxValue }: { series: Array<{ name: string; color: string; values: number[] }>; maxValue?: number }) {
  const width = 320;
  const height = 104;
  const allValues = series.flatMap((item) => item.values.length > 1 ? item.values : [item.values[0] || 0, item.values[0] || 0]);
  const max = Math.max(1, maxValue ?? Math.max(...allValues, 1));
  const makePath = (values: number[]) => {
    const points = values.length > 1 ? values : [values[0] || 0, values[0] || 0];
    return points.map((value, index) => {
      const x = points.length === 1 ? 0 : (index / (points.length - 1)) * width;
      const y = height - (Math.max(0, value) / max) * (height - 18) - 9;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
  };
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-28 w-full overflow-visible">
      {[24, 52, 80].map((y) => <line key={y} x1="0" x2={width} y1={y} y2={y} stroke="rgba(255,255,255,.08)" strokeDasharray="4 4" />)}
      {series.map((item) => (
        <path key={item.name} d={makePath(item.values)} fill="none" stroke={item.color} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      ))}
    </svg>
  );
}

function machineToneClass(tone: "orange" | "green" | "blue" | "red" | "neutral") {
  return {
    orange: "bg-orange-400/12 text-ops-orange",
    green: "bg-emerald-400/12 text-ops-green",
    blue: "bg-blue-400/12 text-ops-blue",
    red: "bg-red-400/12 text-ops-red",
    neutral: "bg-white/[0.08] text-slate-200"
  }[tone];
}

function serviceTone(status: string) {
  const normalized = String(status || "").toLowerCase();
  if (["running", "recording", "connected", "enabled", "source_ready", "ok"].includes(normalized)) return "border-emerald-400/25 bg-emerald-400/10 text-emerald-200";
  if (["error", "failed"].includes(normalized)) return "border-red-400/25 bg-red-400/10 text-red-200";
  if (["warning", "checking", "waiting", "armed"].includes(normalized)) return "border-orange-400/25 bg-orange-400/10 text-ops-gold";
  return "border-white/10 bg-white/[0.04] text-slate-300";
}

function serviceStatusLabel(status: string) {
  const normalized = String(status || "").toLowerCase();
  const labels: Record<string, string> = {
    running: "运行中",
    recording: "录制中",
    connected: "已连接",
    enabled: "已启用",
    idle: "空闲",
    disabled: "未启用",
    source_ready: "源就绪",
    checking: "检测中",
    waiting: "等待中",
    armed: "待命",
    error: "异常",
    failed: "失败"
  };
  return labels[normalized] || status || "未知";
}

function clampPercent(value: unknown) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, number));
}

function diskUsagePercent(disk?: { totalBytes?: number; usedBytes?: number }) {
  const total = Number(disk?.totalBytes || 0);
  if (!total) return 0;
  return clampPercent((Number(disk?.usedBytes || 0) / total) * 100);
}

function formatMachineBytes(value: unknown) {
  const number = Number(value || 0);
  return number > 0 ? formatBytes(number) : "0 B";
}

function formatByteRate(value: unknown) {
  return `${formatMachineBytes(value)}/s`;
}

function formatCpuTemperature(cpu?: SystemStatus["cpu"]) {
  if (cpu?.temperatureAvailable && cpu.temperatureCelsius != null) {
    const label = cpu.temperatureLabel ? ` · ${cpu.temperatureLabel}` : "";
    return `${Number(cpu.temperatureCelsius).toFixed(1)}°C${label}`;
  }
  return cpu?.temperature?.error || "未上报";
}

function formatMachineDateTime(value?: string) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatMachineShortTime(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatMachineMinute(value?: string) {
  if (!value) return "--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
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
  const [selectedId, setSelectedId] = useState("");
  const [followLogs, setFollowLogs] = useState(true);
  const [cursor, setCursor] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [copied, setCopied] = useState(false);
  const timeRange = useMemo(() => logTimeRange(filters.range), [filters.range]);
  const queryString = useMemo(() => {
    const query = new URLSearchParams();
    query.set("limit", String(pageSize));
    query.set("cursor", String(cursor));
    if (filters.q.trim()) query.set("q", filters.q.trim());
    if (filters.level) query.set("level", filters.level);
    if (filters.source) query.set("source", filters.source);
    if (timeRange.from) query.set("from", timeRange.from);
    if (timeRange.to) query.set("to", timeRange.to);
    return query.toString();
  }, [cursor, filters, pageSize, timeRange.from, timeRange.to]);
  const logs = useQuery({
    queryKey: ["system-logs", filters, cursor, pageSize],
    queryFn: () => apiGet<SystemLogsResponse>(`/api/system/logs?${queryString}`),
    initialData: cursor === 0 && !filters.q && !filters.level && !filters.source && filters.range === "1h"
      ? { events: initialLogs, items: initialLogs, total: initialLogs.length, cursor: 0, limit: pageSize }
      : undefined,
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
  const items = logs.data?.items || logs.data?.events || [];
  const total = Number(logs.data?.total ?? items.length);
  const currentCursor = Number(logs.data?.cursor ?? cursor);
  const currentPage = Math.floor(currentCursor / pageSize) + 1;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const selected = items.find((item) => (item.id || `${item.time}-${item.summary}`) === selectedId) || items[0];
  const sources = logs.data?.availableSources?.length ? logs.data.availableSources : logs.data?.sources || [];
  const sourceLabels = logs.data?.sourceLabels || {};
  const levels = ["", ...Array.from(new Set([...(logs.data?.availableLevels || []), "INFO", "WARN", "ERROR"]))];
  const levelCounts = logs.data?.levelCounts || {};
  const timelineItems = logs.data?.timeline?.length
    ? logs.data.timeline
    : items.slice(0, 6).reverse().map((event) => ({
      id: event.id,
      time: event.time,
      level: event.level,
      source: event.source,
      sourceLabel: event.sourceLabel,
      summary: event.summary,
      roundId: event.roundId
    }));
  const updateFilter = (patch: Partial<typeof filters>) => {
    setFilters((value) => ({ ...value, ...patch }));
    setCursor(0);
    setSelectedId("");
  };
  const exportLogs = () => {
    window.open(`/api/system/logs/export?${queryString}`, "_blank", "noopener,noreferrer");
  };
  const copySelected = async () => {
    if (!selected) return;
    const text = JSON.stringify(selected, null, 2);
    try {
      await navigator.clipboard?.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };
  const gotoPage = (page: number) => {
    const safePage = Math.max(1, Math.min(pageCount, page));
    setCursor((safePage - 1) * pageSize);
    setSelectedId("");
  };
  return (
    <section className="grid gap-4">
      <div className="flex items-end justify-between gap-5 max-xl:flex-col max-xl:items-start">
        <div>
          <h2 className="text-4xl font-black tracking-[-0.06em] max-sm:text-3xl">系统日志</h2>
          <p className="mt-2 max-w-3xl text-sm leading-7 text-ops-muted">按时间查看系统运行日志，支持搜索、过滤、导出，帮助排查问题与审计操作。</p>
        </div>
        <div className="grid grid-cols-3 gap-3 max-sm:w-full max-sm:grid-cols-1">
          <LogActionButton tone={followLogs ? "blue" : "neutral"} icon={<Lightning size={18} />} onClick={() => setFollowLogs((value) => !value)}>
            {followLogs ? "日志实时跟随" : "暂停跟随"}
          </LogActionButton>
          <LogActionButton tone="neutral" icon={<DownloadSimple size={18} />} onClick={exportLogs}>
            导出日志
          </LogActionButton>
          <LogActionButton tone="orange" icon={<Sparkle size={18} weight="fill" />} disabled={summary.isPending} onClick={() => summary.mutate()}>
            生成排障摘要
          </LogActionButton>
        </div>
      </div>

      <div className="glass rounded-3xl p-4">
        <div className="grid grid-cols-[minmax(240px,1fr)_minmax(260px,auto)_minmax(300px,1.3fr)_minmax(180px,auto)] gap-4 max-2xl:grid-cols-2 max-lg:grid-cols-1">
          <label className="grid gap-2">
            <span className="text-xs font-bold text-ops-muted">搜索</span>
            <span className="relative block">
              <MagnifyingGlass className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ops-muted" size={18} />
              <input
                className="ops-input pl-11"
                value={filters.q}
                onChange={(event) => updateFilter({ q: event.target.value })}
                placeholder="搜索错误、场次 ID、关键词..."
              />
            </span>
          </label>
          <div className="grid gap-2">
            <span className="flex items-center gap-2 text-xs font-bold text-ops-muted"><FunnelSimple size={15} />级别</span>
            <div className="flex flex-wrap gap-2">
              {levels.map((level) => (
                <LogFilterButton
                  key={level || "all"}
                  active={filters.level === level}
                  tone={level === "ERROR" ? "red" : level === "WARN" ? "orange" : level === "INFO" ? "blue" : "orange"}
                  onClick={() => updateFilter({ level })}
                >
                  {level || "全部"}
                  {level && levelCounts[level] ? <span className="font-mono text-[10px] opacity-75">{levelCounts[level]}</span> : null}
                </LogFilterButton>
              ))}
            </div>
          </div>
          <div className="grid gap-2">
            <span className="text-xs font-bold text-ops-muted">来源</span>
            <div className="flex gap-2 overflow-x-auto pb-1">
              <LogFilterButton active={!filters.source} tone="neutral" onClick={() => updateFilter({ source: "" })}>全部</LogFilterButton>
              {sources.map((source) => (
                <LogFilterButton key={source} active={filters.source === source} tone="neutral" onClick={() => updateFilter({ source })}>
                  {sourceLabels[source] || source}
                </LogFilterButton>
              ))}
            </div>
          </div>
          <div className="grid gap-2">
            <span className="flex items-center gap-2 text-xs font-bold text-ops-muted"><CalendarBlank size={15} />时间范围</span>
            <select className="ops-input" value={filters.range} onChange={(event) => updateFilter({ range: event.target.value })}>
              <option value="1h">最近 1 小时</option>
              <option value="6h">最近 6 小时</option>
              <option value="24h">最近 24 小时</option>
              <option value="all">全部时间</option>
            </select>
          </div>
        </div>
      </div>

      {summary.data && (
        <div className="rounded-3xl border border-orange-400/30 bg-orange-400/10 p-5 text-sm leading-7 text-ops-gold">
          <div className="flex items-start justify-between gap-4 max-sm:flex-col">
            <div>
              <strong className="block text-base text-ops-gold">排障摘要</strong>
              <p className="mt-2 text-slate-100">{summary.data.summary}</p>
            </div>
            <span className="rounded-full border border-orange-400/30 bg-black/20 px-3 py-1 font-mono text-xs">共 {summary.data.total || 0} 条</span>
          </div>
          <ul className="mt-3 grid gap-2 text-slate-200">
            {(summary.data.suggestions || []).map((item) => <li key={item} className="flex gap-2"><CheckCircle className="mt-0.5 shrink-0 text-ops-green" size={16} />{item}</li>)}
          </ul>
        </div>
      )}
      {summary.error && <p className="rounded-2xl border border-red-400/30 bg-red-400/10 px-5 py-4 text-sm text-red-100">{String((summary.error as Error).message || summary.error)}</p>}
      {logs.error && <p className="rounded-2xl border border-red-400/30 bg-red-400/10 px-5 py-4 text-sm text-red-100">日志读取失败：{String((logs.error as Error).message || logs.error)}</p>}

      <div className="grid grid-cols-[minmax(0,1fr)_440px] gap-4 max-2xl:grid-cols-[minmax(0,1fr)_390px] max-xl:grid-cols-1">
        <section className="glass min-w-0 overflow-hidden rounded-3xl">
          <div className="grid grid-cols-[190px_90px_120px_minmax(0,1fr)] gap-4 border-b border-white/10 px-5 py-4 text-xs font-bold text-ops-muted max-lg:hidden">
            <span>时间</span>
            <span>级别</span>
            <span>来源</span>
            <span>摘要</span>
          </div>
          <div className="min-h-[430px]">
            {logs.isFetching && !items.length ? (
              <div className="grid min-h-[430px] place-items-center text-sm text-ops-muted">正在读取日志...</div>
            ) : items.length ? (
              <div className="divide-y divide-white/[0.07]">
                {items.map((event) => {
                  const id = event.id || `${event.time}-${event.summary}`;
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setSelectedId(id)}
                      className="block w-full text-left transition hover:bg-white/[0.035] focus:outline-none focus-visible:bg-white/[0.05]"
                    >
                      <LogRow event={event} active={(selected?.id || `${selected?.time}-${selected?.summary}`) === id} />
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="grid min-h-[430px] place-items-center p-6 text-center">
                <div>
                  <FileText className="mx-auto text-ops-muted" size={42} />
                  <strong className="mt-3 block text-lg">暂无匹配日志</strong>
                  <p className="mt-2 text-sm text-ops-muted">试着放宽时间范围，或清空级别和来源筛选。</p>
                </div>
              </div>
            )}
          </div>
          <div className="flex items-center justify-between gap-4 border-t border-white/10 px-5 py-4 max-md:flex-col max-md:items-stretch">
            <p className="text-sm text-ops-muted">共 <span className="font-mono text-slate-200">{total.toLocaleString("zh-CN")}</span> 条日志</p>
            <div className="flex flex-wrap items-center justify-end gap-2 max-md:justify-between">
              <button className="ops-mini-button" type="button" disabled={currentPage <= 1} onClick={() => gotoPage(currentPage - 1)}><CaretLeft size={15} />上一页</button>
              {logPaginationItems(currentPage, pageCount).map((item, index) => item === "gap" ? (
                <span key={`gap-${index}`} className="px-2 font-mono text-ops-muted">...</span>
              ) : (
                <button key={item} type="button" onClick={() => gotoPage(item)} className={`grid size-9 place-items-center rounded-xl border font-mono text-sm font-black ${item === currentPage ? "border-orange-400/60 bg-orange-400/15 text-ops-gold" : "border-white/10 bg-white/[0.035] text-slate-300"}`}>
                  {item}
                </button>
              ))}
              <button className="ops-mini-button" type="button" disabled={currentPage >= pageCount} onClick={() => gotoPage(currentPage + 1)}>下一页<CaretRight size={15} /></button>
              <select
                className="ops-input h-10 w-auto min-w-28 py-1 text-sm"
                value={pageSize}
                onChange={(event) => {
                  setPageSize(Number(event.target.value));
                  setCursor(0);
                }}
              >
                <option value={20}>20 条/页</option>
                <option value={50}>50 条/页</option>
                <option value={100}>100 条/页</option>
              </select>
            </div>
          </div>
        </section>

        <LogDetailPanel event={selected} copied={copied} onCopy={copySelected} onSummarize={() => summary.mutate()} />
      </div>

      <LogTimelinePanel items={timelineItems} />
    </section>
  );
}

function LogRow({ event, active }: { event: SystemLogEvent; active?: boolean }) {
  const level = String(event.level || "INFO").toUpperCase();
  const activeClass = active ? "bg-red-400/[0.14] shadow-[inset_3px_0_0_#ff6f61]" : "";
  return (
    <article className={`grid grid-cols-[190px_90px_120px_minmax(0,1fr)] items-center gap-4 px-5 py-3.5 text-sm max-lg:grid-cols-[1fr_auto] max-lg:gap-2 ${activeClass}`}>
      <time className="font-mono text-xs text-slate-300 max-lg:order-1">{formatLogTimestamp(event.time)}</time>
      <LogLevelBadge level={level} className="max-lg:order-2 max-lg:justify-self-end" />
      <span className="truncate text-slate-300 max-lg:order-3 max-lg:col-span-2">{event.sourceLabel || event.source || "系统"}</span>
      <div className="min-w-0 max-lg:order-4 max-lg:col-span-2">
        <strong className={`block truncate ${level === "ERROR" ? "text-red-100" : "text-slate-100"}`}>{event.summary || event.detail || "无摘要"}</strong>
        {(event.roundId || event.detail) && <span className="mt-1 block truncate text-xs text-ops-muted">{event.roundId || event.detail}</span>}
      </div>
    </article>
  );
}

function LogActionButton({ children, icon, tone, disabled, onClick }: { children: ReactNode; icon: ReactNode; tone: "orange" | "blue" | "neutral"; disabled?: boolean; onClick?: () => void }) {
  const toneClass = tone === "orange"
    ? "border-orange-400/40 bg-orange-400/[0.14] text-ops-gold hover:bg-orange-400/20"
    : tone === "blue"
      ? "border-blue-400/35 bg-blue-400/[0.14] text-blue-100 hover:bg-blue-400/20"
      : "border-white/10 bg-white/[0.045] text-slate-200 hover:bg-white/[0.075]";
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border px-4 text-sm font-black transition active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45 ${toneClass}`}
    >
      {icon}
      <span className="whitespace-nowrap">{children}</span>
    </button>
  );
}

function LogFilterButton({ children, active, tone, onClick }: { children: ReactNode; active: boolean; tone: "orange" | "blue" | "red" | "neutral"; onClick: () => void }) {
  const activeClass = tone === "red"
    ? "border-red-400/45 bg-red-400/15 text-red-100"
    : tone === "blue"
      ? "border-blue-400/45 bg-blue-400/15 text-blue-100"
      : tone === "orange"
        ? "border-orange-400/45 bg-orange-400/15 text-ops-gold"
        : "border-white/20 bg-white/[0.08] text-slate-100";
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "inline-flex min-h-9 shrink-0 items-center gap-2 rounded-xl border px-3 text-xs font-black transition active:translate-y-px",
        active ? activeClass : "border-white/10 bg-black/20 text-ops-muted hover:border-white/20 hover:text-slate-200"
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function LogDetailPanel({ event, copied, onCopy, onSummarize }: { event?: SystemLogEvent; copied: boolean; onCopy: () => void; onSummarize: () => void }) {
  const level = String(event?.level || "INFO").toUpperCase();
  const remediation = event?.remediation || [];
  return (
    <aside className="glass min-w-0 rounded-3xl p-5">
      <div className="mb-5 flex items-start justify-between gap-3">
        <h3 className="text-lg font-black tracking-[-0.04em]">日志详情</h3>
        {event && <LogLevelBadge level={level} />}
      </div>
      {event ? (
        <div className="grid gap-4">
          <div className="grid gap-3">
            <LogDetailField label="时间" value={formatLogTimestamp(event.time)} />
            <LogDetailField label="来源" value={event.sourceLabel || event.source || "系统"} />
            <LogDetailField label="场次 ID" value={String(event.roundId || "-")} />
            <LogDetailField label="日志 ID" value={String(event.id || "-")} />
            <LogDetailField label="主机" value={String(event.host || "-")} />
          </div>

          {(event.command || event.detail || event.errorMessage) && (
            <div className="grid gap-3">
              {event.command && <LogCodeBlock label="命令" value={String(event.command)} onCopy={onCopy} copied={copied} />}
              {(event.errorMessage || event.detail) && <LogCodeBlock label={level === "ERROR" ? "错误信息" : "详细信息"} value={String(event.errorMessage || event.detail || "")} />}
            </div>
          )}

          <div className="rounded-2xl border border-white/10 bg-black/22 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <strong className="text-sm">原始事件</strong>
              <button type="button" className="ops-mini-button" onClick={onCopy}>
                <CopySimple size={15} />
                {copied ? "已复制" : "复制"}
              </button>
            </div>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-5 text-slate-300">{JSON.stringify(event, null, 2)}</pre>
          </div>

          <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/[0.08] p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <strong className="text-sm text-slate-100">建议排查</strong>
              <a className="text-xs font-bold text-blue-200 hover:text-blue-100" href="/docs/precise-result-agent" target="_blank" rel="noreferrer">查看排查文档</a>
            </div>
            {remediation.length ? (
              <ul className="grid gap-2 text-sm leading-6 text-slate-200">
                {remediation.map((item) => (
                  <li key={item} className="flex gap-2">
                    <CheckCircle className="mt-0.5 shrink-0 text-ops-green" size={16} />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm leading-6 text-ops-muted">这条日志暂无针对性排查建议。可筛选同来源日志继续观察。</p>
            )}
          </div>

          <button type="button" className="inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl border border-orange-400/45 bg-orange-400/15 px-4 text-sm font-black text-ops-gold transition hover:bg-orange-400/20 active:translate-y-px" onClick={onSummarize}>
            <Sparkle size={18} weight="fill" />
            生成排障摘要
          </button>
        </div>
      ) : (
        <div className="grid min-h-[360px] place-items-center text-center text-ops-muted">
          <div>
            <FileText className="mx-auto" size={42} />
            <p className="mt-3 text-sm">选择一条日志查看详情。</p>
          </div>
        </div>
      )}
    </aside>
  );
}

function LogDetailField({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[92px_minmax(0,1fr)] items-start gap-4 text-sm">
      <span className="text-ops-muted">{label}</span>
      <strong className="min-w-0 break-words font-mono text-sm font-semibold text-slate-200">{value}</strong>
    </div>
  );
}

function LogCodeBlock({ label, value, copied, onCopy }: { label: string; value: string; copied?: boolean; onCopy?: () => void }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-xs font-bold text-ops-muted">{label}</span>
        {onCopy && <button type="button" className="ops-mini-button" onClick={onCopy}><CopySimple size={15} />{copied ? "已复制" : "复制"}</button>}
      </div>
      <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded-2xl border border-white/10 bg-black/28 p-3 font-mono text-[11px] leading-5 text-slate-300">{value || "-"}</pre>
    </div>
  );
}

function LogLevelBadge({ level, className = "" }: { level: string; className?: string }) {
  const normalized = String(level || "INFO").toUpperCase();
  const tone = normalized === "ERROR"
    ? "border-red-400/35 bg-red-400/15 text-red-100"
    : normalized === "WARN"
      ? "border-yellow-400/35 bg-yellow-400/15 text-yellow-100"
      : "border-blue-400/35 bg-blue-400/15 text-blue-100";
  return <span className={`inline-flex min-h-7 items-center justify-center rounded-lg border px-3 font-mono text-xs font-black ${tone} ${className}`}>{normalized}</span>;
}

function LogTimelinePanel({ items }: { items: NonNullable<SystemLogsResponse["timeline"]> }) {
  return (
    <section className="glass rounded-3xl p-5">
      <div className="mb-5 flex items-center justify-between gap-4 max-sm:flex-col max-sm:items-start">
        <h3 className="flex items-center gap-2 text-lg font-black tracking-[-0.04em]">
          <Clock size={18} />
          事件时间线
        </h3>
        <span className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-bold text-ops-muted">最近 {items.length || 0} 个关键事件</span>
      </div>
      {items.length ? (
        <div className="relative grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-4 max-md:grid-cols-1">
          <div className="absolute left-8 right-8 top-7 border-t border-dashed border-white/25 max-md:bottom-8 max-md:left-7 max-md:right-auto max-md:top-8 max-md:border-l max-md:border-t-0" />
          {items.map((item, index) => {
            const level = String(item.level || "INFO").toUpperCase();
            const tone = logLevelTone(level);
            return (
              <article key={item.id || `${item.time}-${index}`} className="relative grid justify-items-center gap-2 text-center max-md:grid-cols-[56px_minmax(0,1fr)] max-md:justify-items-start max-md:text-left">
                <span className={`relative z-[1] grid size-14 place-items-center rounded-full border text-lg shadow-[0_0_0_8px_rgba(7,10,13,.92)] ${tone.icon}`}>
                  {level === "ERROR" ? <WarningCircle size={24} weight="fill" /> : level === "WARN" ? <WarningCircle size={24} /> : <Play size={22} weight="fill" />}
                </span>
                <div className="min-w-0 max-md:pt-1">
                  <time className={`block font-mono text-xs ${level === "ERROR" ? "text-red-200" : "text-ops-muted"}`}>{formatLogTimeOnly(item.time)}</time>
                  <strong className="mt-1 block truncate text-sm text-slate-100">{item.summary || "系统事件"}</strong>
                  <span className="mt-1 block truncate text-xs text-ops-muted">{item.sourceLabel || item.source || "系统"}</span>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="grid min-h-28 place-items-center text-sm text-ops-muted">暂无可展示的事件时间线。</div>
      )}
    </section>
  );
}

function logLevelTone(level: string) {
  const normalized = String(level || "INFO").toUpperCase();
  if (normalized === "ERROR") return { icon: "border-red-400/45 bg-red-400/[0.18] text-red-100" };
  if (normalized === "WARN") return { icon: "border-yellow-400/45 bg-yellow-400/[0.16] text-yellow-100" };
  return { icon: "border-blue-400/45 bg-blue-400/[0.16] text-blue-100" };
}

function logPaginationItems(current: number, total: number): Array<number | "gap"> {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  const pages = new Set([1, total, current, current - 1, current + 1].filter((item) => item >= 1 && item <= total));
  const sorted = Array.from(pages).sort((a, b) => a - b);
  const result: Array<number | "gap"> = [];
  sorted.forEach((page, index) => {
    const previous = sorted[index - 1];
    if (previous && page - previous > 1) result.push("gap");
    result.push(page);
  });
  return result;
}

function formatLogTimestamp(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const main = date.toLocaleString("zh-CN", { hour12: false });
  const milliseconds = String(date.getMilliseconds()).padStart(3, "0");
  return `${main}.${milliseconds}`;
}

function formatLogTimeOnly(value?: string) {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
