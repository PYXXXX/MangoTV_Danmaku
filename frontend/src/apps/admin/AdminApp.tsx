import {
  Database,
  Lightning,
  Pulse,
  ShieldCheck
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { apiPatch, apiPost, getBootstrap, getSystemLogs, getSystemStatus } from "../../api/client";
import type { ActivityItem, RoundSession, SystemLogEvent, SystemStatus } from "../../api/types";
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

function ActivityMonitorPage({ activity, status }: { activity?: ActivityItem | null; status?: SystemStatus }) {
  const queryClient = useQueryClient();
  const monitor = status?.monitor;
  const config = monitor?.config || {};
  const state = monitor?.state || {};
  const activityId = activity?.id || "default";
  const [form, setForm] = useState({
    name: activity?.name || config.activity || "歌手 2026",
    url: activity?.url || config.url || "",
    monitorEnabled: Boolean(activity?.monitorEnabled || config.enabled),
    autoDetectSource: config.autoDetectSource ?? true,
    autoRecordVideo: config.autoRecordVideo ?? false,
    autoRecordDanmaku: config.autoRecordDanmaku ?? true,
    feishuNotify: config.feishuNotify ?? true,
    pollSeconds: config.pollSeconds || 45,
    preferredQuality: config.preferredQuality || "auto"
  });

  useEffect(() => {
    setForm({
      name: activity?.name || config.activity || "歌手 2026",
      url: activity?.url || config.url || "",
      monitorEnabled: Boolean(activity?.monitorEnabled || config.enabled),
      autoDetectSource: config.autoDetectSource ?? true,
      autoRecordVideo: config.autoRecordVideo ?? false,
      autoRecordDanmaku: config.autoRecordDanmaku ?? true,
      feishuNotify: config.feishuNotify ?? true,
      pollSeconds: config.pollSeconds || 45,
      preferredQuality: config.preferredQuality || "auto"
    });
  }, [activity?.id, activity?.name, activity?.url, config.activity, config.url, config.enabled, config.autoDetectSource, config.autoRecordVideo, config.autoRecordDanmaku, config.feishuNotify, config.pollSeconds, config.preferredQuality]);

  const save = useMutation({
    mutationFn: (override?: Partial<typeof form>) => apiPost("/api/activities", { ...form, ...override }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const detect = useMutation({
    mutationFn: () => apiPost(`/api/activities/${encodeURIComponent(activityId)}/source/detect`, { url: form.url, quality: form.preferredQuality }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const stop = useMutation({
    mutationFn: () => apiPost(`/api/activities/${encodeURIComponent(activityId)}/monitor/stop`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const busy = save.isPending || detect.isPending || stop.isPending;
  const error = save.error || detect.error || stop.error;
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
            <Field label="活动名称">
              <input className="ops-input" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </Field>
            <Field label="活动链接（官方活动页或直播页）">
              <input className="ops-input" value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} placeholder="https://www.mgtv.com/z/1001668.html" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <button type="button" className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm font-black text-slate-100" disabled={busy} onClick={() => save.mutate({})}>
                保存活动
              </button>
              <button type="button" className="rounded-xl bg-ops-orange px-4 py-3 text-sm font-black text-[#1b0d03]" disabled={busy} onClick={() => save.mutate({ monitorEnabled: true })}>
                保存并监控
              </button>
            </div>
            <p className="text-sm leading-7 text-ops-muted">{state.message || "保存活动链接后，监控器会按策略轮询直播状态。"}</p>
            {error && <p className="rounded-xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100">{String((error as Error).message || error)}</p>}
          </div>
        </Card>

        <Card title="监控策略" className="min-h-[360px]">
          <div className="grid gap-4">
            <Toggle label="监控直播状态" description="监控开播状态，开播后按下方策略执行。" checked={form.monitorEnabled} onChange={(monitorEnabled) => setForm({ ...form, monitorEnabled })} />
            <Toggle label="开播后自动检测直播源" description="自动刷新活动页并解析可录制播放源。" checked={form.autoDetectSource} onChange={(autoDetectSource) => setForm({ ...form, autoDetectSource })} />
            <Toggle label="检测成功后录制视频" description="需要 ffmpeg 和可直录 m3u8，1080P/VIP 依赖芒果登录态。" checked={form.autoRecordVideo} onChange={(autoRecordVideo) => setForm({ ...form, autoRecordVideo })} />
            <Toggle label="检测成功后录制弹幕" description="保存完整原始弹幕，并在实时/后处理场景复用。" checked={form.autoRecordDanmaku} onChange={(autoRecordDanmaku) => setForm({ ...form, autoRecordDanmaku })} />
            <Toggle label="状态变化通知飞书" description="开播、录制异常、发布结果等事件会推送飞书卡片。" checked={form.feishuNotify} onChange={(feishuNotify) => setForm({ ...form, feishuNotify })} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="检测间隔（秒）">
                <input className="ops-input" type="number" min={10} max={3600} value={form.pollSeconds} onChange={(event) => setForm({ ...form, pollSeconds: Number(event.target.value) })} />
              </Field>
              <Field label="默认清晰度">
                <select className="ops-input" value={form.preferredQuality} onChange={(event) => setForm({ ...form, preferredQuality: event.target.value })}>
                  <option value="auto">自动最高可用</option>
                  <option value="1080P">1080P</option>
                  <option value="720P">720P</option>
                  <option value="540P">540P</option>
                </select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <button type="button" className="rounded-xl border border-emerald-400/30 bg-emerald-400/15 px-4 py-3 text-sm font-black text-emerald-100" disabled={busy} onClick={() => save.mutate({ monitorEnabled: true })}>开始监控</button>
              <button type="button" className="rounded-xl border border-red-400/30 bg-red-400/15 px-4 py-3 text-sm font-black text-red-100" disabled={busy} onClick={() => stop.mutate()}>停止监控</button>
            </div>
          </div>
        </Card>

        <Card title="运行状态" className="min-h-[360px]">
          <Timeline
            items={[
              { title: "等待开播", description: state.lastCheckAt || "监控器已准备", tone: config.enabled ? "active" : "idle" },
              { title: "已解析活动页", description: config.url || "未配置活动链接", tone: config.url ? "done" : "idle" },
              { title: "直播源检测", description: state.lastError || state.quality || "开播后自动解析", tone: state.lastError ? "warn" : state.quality ? "done" : "idle" }
            ]}
          />
          <div className="mt-5 grid grid-cols-2 gap-3">
            <MiniMetric label="活动场次" value={formatCount(activity?.roundCount)} />
            <MiniMetric label="累计弹幕" value={formatCount(activity?.messageCount)} />
          </div>
        </Card>
      </div>
    </section>
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

function Toggle({ label, description, checked, onChange }: { label: string; description: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="flex items-center justify-between border-b border-white/[0.07] py-3 text-left">
      <span>
        <strong className="block text-sm text-white">{label}</strong>
        <span className="text-xs text-ops-muted">{description}</span>
      </span>
      <span className={`h-7 w-12 rounded-full p-1 ${checked ? "bg-ops-orange" : "bg-white/10"}`}>
        <i className={`block size-5 rounded-full bg-white transition ${checked ? "translate-x-5" : ""}`} />
      </span>
    </button>
  );
}

function OperationsPage({ rounds, activeRound, defaultActivity }: { rounds: RoundSession[]; activeRound: RoundSession | null; defaultActivity: string }) {
  const queryClient = useQueryClient();
  const resultType = useUiStore((state) => state.resultType);
  const setResultType = useUiStore((state) => state.setResultType);
  const result = selectedResult(activeRound, resultType);
  const rows = rankingRows(activeRound, result.data);
  const total = rows.reduce((sum, row) => sum + row.votes, 0);
  const [roundForm, setRoundForm] = useState({
    activity: defaultActivity || activeRound?.activity || "歌手 2026",
    name: "",
    url: ""
  });
  const [renameValue, setRenameValue] = useState("");
  useEffect(() => {
    setRoundForm((current) => ({
      ...current,
      activity: current.activity || defaultActivity || activeRound?.activity || "歌手 2026"
    }));
  }, [defaultActivity, activeRound?.activity]);
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
  const renameRound = useMutation({
    mutationFn: () => apiPatch("/api/rounds/" + encodeURIComponent(activeRound?.id || ""), { name: renameValue }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["studio-bootstrap"] })
  });
  const operationError = startRound.error || endRound.error || publish.error || pushFeishu.error || renameRound.error;
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
              <div className="mb-4 grid gap-3 rounded-2xl border border-white/10 bg-black/20 p-4">
                <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
                  <Field label="活动名称">
                    <input className="ops-input" value={roundForm.activity} onChange={(event) => setRoundForm({ ...roundForm, activity: event.target.value })} />
                  </Field>
                  <Field label="场次名称">
                    <input className="ops-input" value={roundForm.name} onChange={(event) => setRoundForm({ ...roundForm, name: event.target.value })} placeholder={`默认：第 ${rounds.length + 1} 轮`} />
                  </Field>
                  <Field label="直播 URL（可选）">
                    <input className="ops-input" value={roundForm.url} onChange={(event) => setRoundForm({ ...roundForm, url: event.target.value })} placeholder="默认使用活动监控链接" />
                  </Field>
                </div>
                <div className="flex flex-wrap gap-3">
                  <button type="button" className="rounded-xl bg-ops-orange px-5 py-3 text-sm font-black text-[#1b0d03]" onClick={() => startRound.mutate()} disabled={startRound.isPending}>开始新一轮</button>
                  <button type="button" className="rounded-xl border border-red-400/35 bg-red-400/15 px-5 py-3 text-sm font-black text-red-100" onClick={() => endRound.mutate()} disabled={!activeRound || activeRound.status !== "running" || endRound.isPending}>结束并发布粗略结果</button>
                </div>
                {operationError && <p className="rounded-xl border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-100">{String((operationError as Error).message || operationError)}</p>}
              </div>
              <RankingTable rows={rows} />
            </div>
            <div className="grid content-start gap-3">
              <button type="button" onClick={() => publish.mutate()} disabled={!activeRound || publish.isPending} className="rounded-xl border border-emerald-400/35 bg-emerald-400/15 px-4 py-3 text-sm font-black text-emerald-100">发布公开页</button>
              <a className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-center text-sm font-black text-slate-100" href={activeRound ? `/api/rounds/${encodeURIComponent(activeRound.id)}/result.png?result=${result.type}` : "#"}>导出 PNG</a>
              <a className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-center text-sm font-black text-slate-100" href={activeRound ? `/api/rounds/${encodeURIComponent(activeRound.id)}.jsonl` : "#"}>导出弹幕</a>
              <div className="rounded-2xl border border-white/10 bg-black/20 p-4 text-sm text-ops-muted">
                <b className="mb-2 block text-white">当前场次</b>
                {activeRound ? `${activeRound.activity || "未分类活动"} / ${roundName(activeRound)}` : "等待场次"}
              </div>
              <div className="grid gap-2 rounded-2xl border border-white/10 bg-black/20 p-4">
                <Field label="重命名所选场次">
                  <input className="ops-input" value={renameValue} onChange={(event) => setRenameValue(event.target.value)} placeholder={activeRound ? roundName(activeRound) : "等待场次"} />
                </Field>
                <button type="button" className="rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm font-black text-slate-100" disabled={!activeRound || !renameValue.trim() || renameRound.isPending} onClick={() => renameRound.mutate()}>重命名</button>
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
            <button className="rounded-xl bg-blue-500 px-4 py-3 text-sm font-black text-white" type="button" disabled={pushFeishu.isPending} onClick={() => pushFeishu.mutate()}>同步到飞书</button>
            <button className="rounded-xl bg-emerald-500 px-4 py-3 text-sm font-black text-white" type="button" disabled={!activeRound || publish.isPending} onClick={() => publish.mutate()}>发布公开页</button>
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
              <strong className="block text-sm">芒果 TV 扫码登录</strong>
              <p className="mt-2 text-xs leading-6 text-ops-muted">登录态：{config.mgtv_auth?.cookie_configured ? "已保存" : "未配置"}。扫码流程继续使用活动监控页的直播源检测能力。</p>
            </div>
            <SettingsToggle label="启用飞书 Bot" checked={Boolean(form.feishuEnabled)} onChange={(value) => update("feishuEnabled", value)} />
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
