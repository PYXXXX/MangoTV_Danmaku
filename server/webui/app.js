const $ = (selector) => document.querySelector(selector);

const el = {
  navItems: Array.from(document.querySelectorAll("[data-page-target]")),
  pages: Array.from(document.querySelectorAll(".app-page")),
  globalActivityPill: $("#globalActivityPill"),
  globalCollectPill: $("#globalCollectPill"),
  globalFeishuPill: $("#globalFeishuPill"),
  subtitle: $("#subtitle"),
  activitySelect: $("#activitySelect"),
  roundSelect: $("#roundSelect"),
  resultButtons: Array.from(document.querySelectorAll("#resultMode [data-result-type]")),
  liveState: $("#liveState"),
  liveText: $("#liveState span"),
  startForm: $("#startForm"),
  activityName: $("#activityName"),
  roundName: $("#roundName"),
  liveUrl: $("#liveUrl"),
  postRecordForm: $("#postRecordForm"),
  postActivityName: $("#postActivityName"),
  postRoundName: $("#postRoundName"),
  postLiveUrl: $("#postLiveUrl"),
  endRound: $("#endRound"),
  publish: $("#publish"),
  preciseForm: $("#preciseForm"),
  preciseFile: $("#preciseFile"),
  renameInput: $("#renameInput"),
  rename: $("#rename"),
  refresh: $("#refresh"),
  downloadSlice: $("#downloadSlice"),
  downloadRaw: $("#downloadRaw"),
  downloadPng: $("#downloadPng"),
  deleteRound: $("#deleteRound"),
  deleteActivity: $("#deleteActivity"),
  recordingStatus: $("#recordingStatus"),
  recordingPlayer: $("#recordingPlayer"),
  markerLabel: $("#markerLabel"),
  addMarker: $("#addMarker"),
  markerList: $("#markerList"),
  clipStart: $("#clipStart"),
  clipEnd: $("#clipEnd"),
  clipLabel: $("#clipLabel"),
  createClip: $("#createClip"),
  clipList: $("#clipList"),
  messages: $("#messages"),
  votes: $("#votes"),
  reviews: $("#reviews"),
  ranking: $("#ranking"),
  resultHeading: $("#resultHeading"),
  updated: $("#updated"),
  roundCount: $("#roundCount"),
  roundList: $("#roundList"),
  monitorActivity: $("#monitorActivity"),
  monitorUrl: $("#monitorUrl"),
  monitorEnabled: $("#monitorEnabled"),
  monitorAutoSource: $("#monitorAutoSource"),
  monitorRecordVideo: $("#monitorRecordVideo"),
  monitorRecordDanmaku: $("#monitorRecordDanmaku"),
  monitorFeishuNotify: $("#monitorFeishuNotify"),
  monitorSave: $("#monitorSave"),
  monitorCheck: $("#monitorCheck"),
  monitorState: $("#monitorState"),
  monitorHint: $("#monitorHint"),
  monitorTimeline: $("#monitorTimeline"),
  liveStatusChip: $("#liveStatusChip"),
  timelineActivity: $("#timelineActivity"),
  timelineSource: $("#timelineSource"),
  timelineRecording: $("#timelineRecording"),
  timelineDanmaku: $("#timelineDanmaku"),
  detectFromOps: $("#detectFromOps"),
  publishStatusChip: $("#publishStatusChip"),
  previewActivity: $("#previewActivity"),
  previewRound: $("#previewRound"),
  syncFeishu: $("#syncFeishu"),
  copyPublicLink: $("#copyPublicLink"),
  refreshSystem: $("#refreshSystem"),
  sysTime: $("#sysTime"),
  sysUptime: $("#sysUptime"),
  sysProcess: $("#sysProcess"),
  sysHealth: $("#sysHealth"),
  cpuGauge: $("#cpuGauge"),
  cpuDetail: $("#cpuDetail"),
  memGauge: $("#memGauge"),
  memDetail: $("#memDetail"),
  netGauge: $("#netGauge"),
  netDetail: $("#netDetail"),
  diskGauge: $("#diskGauge"),
  diskDetail: $("#diskDetail"),
  serviceGrid: $("#serviceGrid"),
  alertList: $("#alertList"),
  refreshLogs: $("#refreshLogs"),
  copyLogSummary: $("#copyLogSummary"),
  logSearch: $("#logSearch"),
  logLevel: $("#logLevel"),
  logSource: $("#logSource"),
  logFollow: $("#logFollow"),
  systemLogRows: $("#systemLogRows"),
  logInspector: $("#logInspector"),
  eventTimeline: $("#eventTimeline"),
  log: $("#log")
};

let state = null;
let selectedActivity = null;
let selectedRoundId = null;
const selectedResultByRound = {};
let systemStatus = null;
let systemLogs = [];
let selectedLogIndex = 0;
const logs = ["管理台已就绪。"];

function formatCount(value) {
  const number = Number(value || 0);
  if (number < 1000) return number.toLocaleString("zh-CN");
  const units = [
    { value: 1000000000, suffix: "b" },
    { value: 1000000, suffix: "m" },
    { value: 1000, suffix: "k" }
  ];
  const unit = units.find((item) => number >= item.value);
  const scaled = number / unit.value;
  const digits = scaled < 10 ? 1 : 0;
  return scaled.toFixed(digits).replace(/\.0$/, "") + unit.suffix;
}

function addLog(text) {
  logs.unshift("[" + new Date().toLocaleTimeString("zh-CN", { hour12: false }) + "] " + text);
  logs.splice(20);
  el.log.textContent = logs.join("\n\n");
}

function switchPage(pageId) {
  el.pages.forEach((page) => {
    const active = page.id === pageId;
    page.classList.toggle("active", active);
    if (page.id === "settingsPanel") page.hidden = !active;
  });
  el.navItems.forEach((item) => item.classList.toggle("active", item.dataset.pageTarget === pageId));
  if (pageId === "machinePage") loadSystemStatus().catch((error) => addLog("机器状态读取失败：" + error.message));
  if (pageId === "logsPage") loadSystemLogs().catch((error) => addLog("系统日志读取失败：" + error.message));
}

function formatBytes(value) {
  const number = Number(value || 0);
  if (!number) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let scaled = number;
  let index = 0;
  while (scaled >= 1024 && index < units.length - 1) {
    scaled /= 1024;
    index += 1;
  }
  return scaled.toFixed(scaled >= 10 || index === 0 ? 0 : 1) + " " + units[index];
}

function formatDuration(seconds) {
  const total = Math.max(0, Number(seconds || 0));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return days + "天 " + String(hours).padStart(2, "0") + "小时";
  if (hours) return hours + "小时 " + String(minutes).padStart(2, "0") + "分";
  return minutes + "分钟";
}

function percent(used, total) {
  return total ? Math.round((Number(used || 0) / Number(total || 1)) * 100) : 0;
}

function configuredDefaults() {
  return (state && state.defaults) || {};
}

function defaultActivityName() {
  return configuredDefaults().activity || selectedActivity || "未分类活动";
}

function defaultRoundName() {
  return "第 " + (((state && state.sessions && state.sessions.length) || 0) + 1) + " 轮";
}

function defaultFullRecordingName() {
  return defaultActivityName() + " 全程录制";
}

function currentMonitor() {
  return (systemStatus && systemStatus.monitor) || {};
}

function currentMonitorConfig() {
  return currentMonitor().config || {};
}

function currentMonitorState() {
  return currentMonitor().state || {};
}

function applyMonitorInputs() {
  const config = currentMonitorConfig();
  if (!config || Object.keys(config).length === 0) return;
  if (el.monitorActivity && document.activeElement !== el.monitorActivity) {
    el.monitorActivity.value = config.activity || "";
  }
  if (el.monitorUrl && document.activeElement !== el.monitorUrl) {
    el.monitorUrl.value = config.url || "";
  }
  if (el.monitorEnabled) el.monitorEnabled.checked = Boolean(config.enabled);
  if (el.monitorAutoSource) el.monitorAutoSource.checked = config.autoDetectSource !== false;
  if (el.monitorRecordVideo) el.monitorRecordVideo.checked = Boolean(config.autoRecordVideo);
  if (el.monitorRecordDanmaku) el.monitorRecordDanmaku.checked = config.autoRecordDanmaku !== false;
  if (el.monitorFeishuNotify) el.monitorFeishuNotify.checked = config.feishuNotify !== false;
}

function applyStartDefaults() {
  const activity = defaultActivityName();
  if (el.activityName && document.activeElement !== el.activityName && !el.activityName.value.trim()) {
    el.activityName.value = activity;
  }
  if (el.postActivityName && document.activeElement !== el.postActivityName && !el.postActivityName.value.trim()) {
    el.postActivityName.value = activity;
  }
  if (el.activityName) {
    el.activityName.placeholder = activity ? ("默认：" + activity) : "例如：歌手 2026";
  }
  if (el.postActivityName) {
    el.postActivityName.placeholder = activity ? ("默认：" + activity) : "例如：歌手 2026";
  }
  if (el.roundName) {
    el.roundName.placeholder = "默认：" + defaultRoundName();
  }
  if (el.postRoundName) {
    el.postRoundName.placeholder = "默认：" + defaultFullRecordingName();
  }
  if (el.postLiveUrl && !el.postLiveUrl.value && configuredDefaults().mgtvUrl) {
    el.postLiveUrl.placeholder = configuredDefaults().mgtvUrl;
  }
  if (el.monitorActivity && document.activeElement !== el.monitorActivity && !el.monitorActivity.value.trim()) {
    el.monitorActivity.value = activity === "未分类活动" ? "" : activity;
  }
  if (el.monitorUrl && document.activeElement !== el.monitorUrl && !el.monitorUrl.value.trim() && configuredDefaults().mgtvUrl) {
    el.monitorUrl.value = configuredDefaults().mgtvUrl;
  }
}

function renderMonitor(round) {
  const defaults = configuredDefaults();
  const monitorConfig = currentMonitorConfig();
  const monitorState = currentMonitorState();
  const activity = monitorConfig.activity || defaults.activity || selectedActivity || "未分类活动";
  const url = monitorConfig.url || defaults.mgtvUrl || "";
  applyMonitorInputs();
  if (el.globalActivityPill) {
    el.globalActivityPill.textContent = activity && activity !== "未分类活动" ? activity + " · 监控策略" : "等待活动";
    el.globalActivityPill.className = "status-pill " + (activity && activity !== "未分类活动" ? "warn" : "");
  }
  if (el.globalCollectPill) {
    const running = round && round.status === "running";
    el.globalCollectPill.textContent = running ? "弹幕采集中" : "弹幕待命";
    el.globalCollectPill.className = "status-pill " + (running ? "ok" : "");
  }
  if (el.monitorState) {
    const status = monitorState.status || (url ? "armed" : "blocked");
    const labelMap = {
      disabled: "监控未启用",
      blocked: "等待活动链接",
      armed: "监控已就绪",
      checking: "正在检测直播源",
      waiting: "等待直播开始",
      source_ready: "直播源已就绪",
      running: "自动采集中",
      error: "监控异常"
    };
    el.monitorState.textContent = labelMap[status] || (url ? "活动页已配置" : "等待活动链接");
    el.monitorState.className = "update-status " + (status === "running" || status === "source_ready" ? "ready" : (status === "error" || status === "blocked" ? "" : "available"));
  }
  if (el.monitorHint) {
    el.monitorHint.textContent = monitorState.message || (url
      ? "后台会按策略自动检测活动页，直播开始后可自动开启弹幕/录屏场次。"
      : "保存后会同步到系统默认活动和默认直播 URL；开轮次时自动使用这组信息。");
  }
  if (el.timelineActivity) el.timelineActivity.textContent = url ? (activity + " · 已配置") : "等待配置";
  if (el.timelineSource) {
    const recording = round && round.recording;
    el.timelineSource.textContent = monitorState.quality
      ? ("已解析 " + monitorState.quality)
      : (recording && recording.sourceUrl ? "已解析录制源" : "直播开始后自动解析");
  }
  if (el.timelineRecording) {
    const recording = round && round.recording;
    el.timelineRecording.textContent = recording ? (recording.status || "已创建录制记录") : "未录制";
  }
  if (el.timelineDanmaku) el.timelineDanmaku.textContent = formatCount(round && round.messageCount) + " 条";
}

function renderOpsChrome(round, current, total) {
  const active = round && round.status === "running";
  if (el.liveStatusChip) {
    el.liveStatusChip.textContent = active ? "监控中" : (round ? "场次已保存" : "等待场次");
    el.liveStatusChip.className = "update-status " + (active ? "available" : "ready");
  }
  if (el.publishStatusChip) {
    el.publishStatusChip.textContent = current.type === "precise" ? "精确已发布" : (round ? "粗略结果" : "待同步");
    el.publishStatusChip.className = "update-status " + (round ? "ready" : "");
  }
  if (el.previewActivity) el.previewActivity.textContent = (round && round.activity) || defaultActivityName();
  if (el.previewRound) el.previewRound.textContent = round ? roundDisplayName(round) : "等待场次";
  if (el.globalFeishuPill && systemStatus) {
    const status = systemStatus.services && systemStatus.services.feishu && systemStatus.services.feishu.status;
    el.globalFeishuPill.textContent = status === "connected" ? "飞书已连接" : (status === "enabled" ? "飞书已启用" : "飞书未启用");
    el.globalFeishuPill.className = "status-pill " + (status === "connected" ? "ok" : "");
  }
  if (el.timelineActivity) el.timelineActivity.textContent = round ? ((round.activity || "未分类活动") + " / " + roundDisplayName(round)) : "等待场次";
  if (el.timelineSource) el.timelineSource.textContent = round && round.pageUrl ? "已解析活动页" : "待检测";
  if (el.timelineRecording) {
    const rec = round && round.recording;
    el.timelineRecording.textContent = rec ? ((rec.status || "未知") + (rec.hasVideo ? " · 可回看" : "")) : "未录制";
  }
  if (el.timelineDanmaku) el.timelineDanmaku.textContent = formatCount(round && round.messageCount) + " 条";
}

function requireLogin(response) {
  if (response.status === 401) {
    const next = window.location.pathname + window.location.search;
    window.location.assign("/login?next=" + encodeURIComponent(next));
    throw new Error("登录已过期，正在跳转");
  }
  return response;
}

async function sendCommand(text) {
  const response = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text })
  });
  requireLogin(response);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "HTTP " + response.status);
  addLog(payload.reply || "操作完成");
  await load();
  return payload.reply;
}

async function deleteJson(url) {
  const response = await fetch(url, { method: "DELETE" });
  requireLogin(response);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "HTTP " + response.status);
  return payload;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {})
  });
  requireLogin(response);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "HTTP " + response.status);
  return data;
}

function confirmPublishAfterDelete(kind) {
  return window.confirm(
    "是否立即同步远端公开发布页？\n\n"
    + "选择“确定”：删除" + kind + "后立刻发布粗略结果，公开页会同步移除。\n"
    + "选择“取消”：只更新运营端，稍后可手动点击“发布粗略结果”同步。"
  );
}

function deleteUrl(path, publish) {
  return path + "?publish=" + (publish ? "1" : "0");
}

function publishStatusText(payload) {
  if (!payload || !payload.publishRequested) return "未同步远端公开页";
  return payload.publishUrl ? ("远端同步状态：" + payload.publishUrl) : "已请求同步远端公开页";
}

function selectedRound() {
  const sessions = (state && state.sessions) || [];
  const filtered = selectedActivity
    ? sessions.filter((item) => (item.activity || "未分类活动") === selectedActivity)
    : sessions;
  return filtered.find((item) => item.id === selectedRoundId)
    || filtered.find((item) => item.id === (state && state.activeSessionId))
    || filtered[0]
    || null;
}

function selectedResult(round) {
  if (!round) return { type: "rough", data: null };
  const available = round.results || {};
  const requested = selectedResultByRound[round.id] || round.defaultResultType || "rough";
  const type = requested === "precise" && available.precise ? "precise" : "rough";
  const fallback = { voteCounts: round.voteCounts || {}, messageCount: round.messageCount || 0, reviewCount: round.reviewCount || 0 };
  return { type, data: available[type] || fallback };
}

function renderRanking(round, result) {
  if (!round) {
    el.ranking.innerHTML = '<div class="empty">结果将在这里显示</div>';
    return 0;
  }
  const rows = (round.candidates || [])
    .map((candidate) => Object.assign({}, candidate, { count: (result && result.voteCounts && result.voteCounts[candidate.id]) || 0 }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "zh-CN"));
  const max = Math.max(1, ...rows.map((item) => item.count));
  const total = rows.reduce((sum, item) => sum + item.count, 0);
  el.ranking.replaceChildren(...rows.map((item, index) => {
    const row = document.createElement("article"); row.className = "row";
    const rank = document.createElement("span"); rank.className = "rank"; rank.textContent = String(index + 1).padStart(2, "0");
    const name = document.createElement("span"); name.className = "name"; name.textContent = item.name;
    const track = document.createElement("div"); track.className = "track";
    const bar = document.createElement("div"); bar.className = "bar"; bar.style.width = ((item.count / max) * 100) + "%"; track.append(bar);
    const count = document.createElement("strong"); count.className = "count"; count.textContent = formatCount(item.count); count.title = item.count.toLocaleString("zh-CN");
    row.append(rank, name, track, count);
    return row;
  }));
  return total;
}

function roundDisplayName(round) {
  return round && (round.displayName || round.baseName || round.name) || "未命名场次";
}

function roundTimeRange(round) {
  return round && round.timeRange ? round.timeRange : "";
}

function formatSeconds(value) {
  const total = Math.max(0, Number(value || 0));
  const minutes = Math.floor(total / 60);
  const seconds = Math.floor(total % 60);
  const tenths = Math.floor((total % 1) * 10);
  return minutes + ":" + String(seconds).padStart(2, "0") + "." + tenths;
}

function clipActionUrl(round, clip, suffix) {
  const base = "/api/rounds/" + encodeURIComponent(round.id) + "/recording/clips/" + encodeURIComponent(clip.id);
  return base + suffix;
}

function renderClipItem(round, clip) {
  const item = document.createElement("article");
  item.className = "clip-item";
  const title = document.createElement("strong");
  title.textContent = formatSeconds(clip.startSeconds) + " – " + formatSeconds(clip.endSeconds) + " · " + (clip.label || "片段");
  const actions = document.createElement("div");
  actions.className = "clip-actions";
  const video = document.createElement("a");
  video.href = clip.url || clipActionUrl(round, clip, ".mp4");
  video.download = "";
  video.textContent = "下载视频";
  const danmaku = document.createElement("a");
  danmaku.href = clip.danmakuUrl || clipActionUrl(round, clip, ".jsonl");
  danmaku.download = "";
  danmaku.textContent = "导出片段弹幕";
  const raw = document.createElement("a");
  raw.href = clip.rawDanmakuUrl || clipActionUrl(round, clip, "/raw.jsonl");
  raw.download = "";
  raw.textContent = "导出原始弹幕";
  const analyze = document.createElement("button");
  analyze.type = "button";
  analyze.className = "secondary";
  analyze.textContent = "生成分析场次";
  analyze.addEventListener("click", async () => {
    try {
      const payload = await postJson(clip.analysisUrl || clipActionUrl(round, clip, "/analysis-round"), {});
      selectedRoundId = payload.roundId;
      addLog("已从片段生成分析场次：" + (payload.roundName || payload.roundId) + "（" + formatCount(payload.messageCount) + " 条弹幕）");
      await load();
    } catch (error) {
      addLog("生成分析场次失败：" + error.message);
    }
  });
  actions.append(video, danmaku, raw, analyze);
  item.append(title, actions);
  return item;
}

function renderRecording(round) {
  const recording = round && round.recording;
  const hasVideo = Boolean(recording && recording.hasVideo && recording.videoUrl);
  el.addMarker.disabled = !hasVideo;
  el.createClip.disabled = !hasVideo;
  if (!round) {
    el.recordingStatus.textContent = "选择场次后显示录屏状态。";
    el.recordingPlayer.removeAttribute("src");
    el.markerList.textContent = "暂无标记";
    el.clipList.textContent = "暂无片段";
    return;
  }
  if (!recording) {
    el.recordingStatus.textContent = "该场次暂无录屏。请在系统配置中启用录制并配置可录制的直播流 URL。";
    el.recordingPlayer.removeAttribute("src");
    el.markerList.textContent = "暂无标记";
    el.clipList.textContent = "暂无片段";
    return;
  }
  el.recordingStatus.textContent = "录屏状态：" + (recording.status || "未知")
    + (recording.error ? (" · " + recording.error) : "")
    + (recording.sourceUrl ? " · 已配置录制源" : " · 未配置录制源");
  const currentSrc = el.recordingPlayer.getAttribute("src") || "";
  if (hasVideo && currentSrc !== recording.videoUrl) {
    el.recordingPlayer.src = recording.videoUrl;
  } else if (!hasVideo) {
    el.recordingPlayer.removeAttribute("src");
  }
  const markers = recording.markers || [];
  el.markerList.replaceChildren(...(markers.length ? markers.map((marker) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.textContent = formatSeconds(marker.atSeconds) + " · " + (marker.label || "未命名标记");
    button.addEventListener("click", () => {
      el.recordingPlayer.currentTime = Number(marker.atSeconds || 0);
      el.recordingPlayer.play().catch(() => {});
    });
    return button;
  }) : [document.createTextNode("暂无标记")]));
  const clips = recording.clips || [];
  el.clipList.replaceChildren(...(clips.length ? clips.map((clip) => renderClipItem(round, clip)) : [document.createTextNode("暂无片段")]));
}

function renderRounds(round) {
  const sessions = (state && state.sessions) || [];
  const activities = Array.from(new Set(sessions.map((item) => item.activity || "未分类活动")));
  if (!selectedActivity || !activities.includes(selectedActivity)) {
    selectedActivity = (round && (round.activity || "未分类活动")) || activities[0] || null;
  }
  el.activitySelect.disabled = !activities.length;
  el.activitySelect.replaceChildren(...(activities.length ? activities.map((activity) => {
    const option = document.createElement("option");
    option.value = activity;
    option.selected = activity === selectedActivity;
    option.textContent = activity;
    return option;
  }) : [new Option("暂无活动", "")]));
  const filtered = sessions.filter((item) => (item.activity || "未分类活动") === selectedActivity);
  el.roundSelect.disabled = !filtered.length;
  el.roundSelect.replaceChildren(...(filtered.length ? filtered.map((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.selected = item.id === (round && round.id);
    option.textContent = (item.status === "running" ? "● " : "") + roundDisplayName(item);
    return option;
  }) : [new Option("暂无场次", "")]));
  el.roundList.replaceChildren(...filtered.map((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "round-item " + (item.id === (round && round.id) ? "active" : "");
    button.dataset.id = item.id;
    const title = document.createElement("strong");
    title.textContent = (item.status === "running" ? "● " : "") + roundDisplayName(item);
    const meta = document.createElement("span");
    meta.textContent = (item.activity || "未分类活动")
      + (roundTimeRange(item) ? (" · " + roundTimeRange(item)) : "")
      + " · " + formatCount(item.messageCount) + " 样本"
      + (item.results && item.results.precise ? " · 精确已发布" : " · 仅粗略");
    button.append(title, meta);
    button.addEventListener("click", () => {
      selectedRoundId = item.id;
      render();
    });
    return button;
  }));
  el.roundCount.textContent = filtered.length + " 场";
}

function render() {
  const round = selectedRound();
  if (round) selectedRoundId = round.id;
  renderRounds(round);
  const current = selectedResult(round);
  const total = renderRanking(round, current.data);
  const active = round && round.status === "running";
  el.liveState.classList.toggle("active", Boolean(active));
  el.liveText.textContent = current.type === "precise" ? "精确结果 · 已清洗" : (active ? "LIVE · 粗略统计中" : (round ? "粗略结果 · 已保存" : "等待场次"));
  el.resultHeading.textContent = current.type === "precise" ? "精确结果" : "粗略结果";
  const hasRound = Boolean(round);
  const hasPrecise = Boolean(round && round.results && round.results.precise);
  el.resultButtons.forEach((button) => {
    const type = button.dataset.resultType;
    const selected = type === current.type;
    button.disabled = !hasRound || (type === "precise" && !hasPrecise);
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
    button.title = type === "precise" && !hasPrecise ? "精确结果尚未发布" : "";
  });
  el.subtitle.textContent = round
    ? ((round.activity || "未分类活动") + " / " + roundDisplayName(round) + (roundTimeRange(round) ? (" · 采集时间：" + roundTimeRange(round)) : "") + " · " + round.status)
    : "等待开始场次";
  const messageCount = current.type === "precise" ? current.data?.audit?.inputMessages : current.data?.messageCount;
  const reviewCount = current.type === "precise" ? current.data?.audit?.unresolvedReviewMessages : current.data?.reviewCount;
  el.messages.textContent = formatCount(messageCount);
  el.messages.title = Number(messageCount || 0).toLocaleString("zh-CN");
  el.votes.textContent = formatCount(total);
  el.votes.title = total.toLocaleString("zh-CN");
  el.reviews.textContent = formatCount(reviewCount);
  el.reviews.title = Number(reviewCount || 0).toLocaleString("zh-CN");
  el.updated.textContent = state && state.publishedAt ? ("数据更新于 " + new Date(state.publishedAt).toLocaleString("zh-CN", { hour12: false })) : "尚未同步";
  renderMonitor(round);
  renderOpsChrome(round, current, total);
  if (document.activeElement !== el.renameInput) el.renameInput.value = (round && roundDisplayName(round)) || "";
  if (round) {
    el.downloadSlice.href = "/api/rounds/" + encodeURIComponent(round.id) + ".jsonl";
    el.downloadSlice.classList.remove("disabled");
    el.downloadRaw.href = "/api/rounds/" + encodeURIComponent(round.id) + "/raw.jsonl";
    el.downloadRaw.classList.remove("disabled");
    el.downloadPng.href = "/api/rounds/" + encodeURIComponent(round.id) + "/result.png?result=" + encodeURIComponent(current.type);
    el.downloadPng.classList.remove("disabled");
    el.deleteRound.disabled = round.status === "running";
    el.deleteActivity.disabled = !selectedActivity;
  } else {
    el.downloadSlice.href = "#";
    el.downloadSlice.classList.add("disabled");
    el.downloadRaw.href = "#";
    el.downloadRaw.classList.add("disabled");
    el.downloadPng.href = "#";
    el.downloadPng.classList.add("disabled");
    el.deleteRound.disabled = true;
    el.deleteActivity.disabled = true;
  }
  renderRecording(round);
  applyStartDefaults();
}

async function load() {
  const resultsResponse = await fetch("/api/results.json?t=" + Date.now(), { cache: "no-store" });
  requireLogin(resultsResponse);
  if (!resultsResponse.ok) throw new Error("结果读取失败：HTTP " + resultsResponse.status);
  state = await resultsResponse.json();
  try {
    const healthResponse = await fetch("/healthz?t=" + Date.now(), { cache: "no-store" });
    if (healthResponse.ok) {
      const health = await healthResponse.json();
      if (health.activeRoundId && !selectedRoundId) selectedRoundId = health.activeRoundId;
    }
  } catch (_) {
    // Health is useful but not required for rendering.
  }
  render();
}

async function loadSystemStatus() {
  const response = await fetch("/api/system/status?t=" + Date.now(), { cache: "no-store" });
  requireLogin(response);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "HTTP " + response.status);
  systemStatus = payload;
  renderSystemStatus(payload);
  renderMonitor(selectedRound());
}

function serviceLabel(name, service) {
  const map = {
    collector: "弹幕采集器",
    recorder: "录制进程",
    feishu: "飞书长连接",
    github: "GitHub 发布",
    updater: "程序更新",
    monitor: "活动监控",
    recordingSource: "直播源"
  };
  const status = service && (service.status || service.quality || (service.configured ? "已配置" : "未配置")) || "未知";
  const item = document.createElement("div");
  item.className = "service-item";
  const label = document.createElement("span");
  label.textContent = map[name] || name;
  const value = document.createElement("strong");
  value.textContent = String(status);
  item.append(label, value);
  return item;
}

function renderSystemStatus(payload) {
  if (!payload) return;
  el.sysTime.textContent = payload.systemTime ? new Date(payload.systemTime).toLocaleString("zh-CN", { hour12: false }) : "--";
  el.sysUptime.textContent = formatDuration(payload.uptimeSeconds);
  el.sysProcess.textContent = (payload.process && payload.process.name || "mgtv-danmaku") + " #" + (payload.process && payload.process.pid || "-");
  const health = payload.health && payload.health.status || "ok";
  el.sysHealth.textContent = health === "ok" ? "正常" : (health === "warning" ? "需关注" : "异常");
  const loadPercent = payload.cpu && payload.cpu.loadPercent;
  el.cpuGauge.textContent = loadPercent == null ? "--" : Math.round(loadPercent) + "%";
  el.cpuDetail.textContent = "CPU 核心：" + (payload.cpu && payload.cpu.count || "-")
    + " · Load Avg：" + ((payload.cpu && payload.cpu.loadAverage || []).map((item) => Number(item).toFixed(2)).join(" / ") || "-");
  const memory = payload.memory || {};
  const memPct = percent(memory.usedBytes, memory.totalBytes);
  el.memGauge.textContent = memory.totalBytes ? memPct + "%" : formatBytes(memory.processRssBytes);
  el.memDetail.textContent = memory.totalBytes
    ? (formatBytes(memory.usedBytes) + " / " + formatBytes(memory.totalBytes) + " · 进程 " + formatBytes(memory.processRssBytes))
    : ("进程 RSS " + formatBytes(memory.processRssBytes));
  const net = payload.network || {};
  el.netGauge.textContent = net.available ? formatBytes((net.rxBytes || 0) + (net.txBytes || 0)) : "不可用";
  el.netDetail.textContent = net.available ? ("入站 " + formatBytes(net.rxBytes) + " · 出站 " + formatBytes(net.txBytes)) : "当前系统不暴露 /proc/net/dev，无法读取流量计数。";
  const dataDisk = payload.disk && payload.disk.data || {};
  const recDisk = payload.disk && payload.disk.recordings || {};
  const diskPct = percent(dataDisk.usedBytes, dataDisk.totalBytes);
  el.diskGauge.textContent = dataDisk.ok ? diskPct + "%" : "异常";
  el.diskDetail.textContent = "数据目录 " + (dataDisk.ok ? (formatBytes(dataDisk.freeBytes) + " 可用") : (dataDisk.error || "不可读"))
    + " · 录制目录 " + (recDisk.ok ? (formatBytes(recDisk.freeBytes) + " 可用") : (recDisk.error || "不可读"));
  const services = payload.services || {};
  el.serviceGrid.replaceChildren(...Object.keys(services).map((name) => serviceLabel(name, services[name])));
  const errors = (systemLogs || []).filter((event) => event.level === "ERROR" || event.level === "WARN").slice(0, 5);
  el.alertList.replaceChildren(...(errors.length ? errors.map((event) => document.createTextNode((event.level || "INFO") + " · " + (event.summary || "") + "\n")) : [document.createTextNode("暂无告警")]));
}

async function loadSystemLogs() {
  const response = await fetch("/api/system/logs?limit=160&t=" + Date.now(), { cache: "no-store" });
  requireLogin(response);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "HTTP " + response.status);
  systemLogs = payload.events || [];
  renderLogFilters(payload.sources || []);
  renderSystemLogs();
}

function renderLogFilters(sources) {
  const current = el.logSource.value;
  el.logSource.replaceChildren(new Option("全部来源", ""), ...sources.map((source) => new Option(source, source)));
  if (sources.includes(current)) el.logSource.value = current;
}

function filteredLogs() {
  const query = (el.logSearch.value || "").trim().toLowerCase();
  const level = el.logLevel.value;
  const source = el.logSource.value;
  return (systemLogs || []).filter((event) => {
    if (level && event.level !== level) return false;
    if (source && event.source !== source) return false;
    const text = [event.summary, event.detail, event.source, event.roundId].join(" ").toLowerCase();
    return !query || text.includes(query);
  });
}

function renderSystemLogs() {
  const rows = filteredLogs();
  selectedLogIndex = Math.min(selectedLogIndex, Math.max(0, rows.length - 1));
  el.systemLogRows.replaceChildren(...(rows.length ? rows.map((event, index) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "log-row " + (index === selectedLogIndex ? "active" : "");
    const time = document.createElement("time");
    time.textContent = event.time ? new Date(event.time).toLocaleString("zh-CN", { hour12: false }) : "-";
    const level = document.createElement("span");
    level.className = "log-level " + (event.level || "INFO");
    level.textContent = event.level || "INFO";
    const source = document.createElement("span");
    source.className = "log-source";
    source.textContent = event.source || "service";
    const summary = document.createElement("strong");
    summary.textContent = event.summary || event.detail || "无摘要";
    row.append(time, level, source, summary);
    row.addEventListener("click", () => {
      selectedLogIndex = index;
      renderSystemLogs();
    });
    return row;
  }) : [Object.assign(document.createElement("div"), { className: "empty", textContent: "暂无匹配日志" })]));
  const selected = rows[selectedLogIndex];
  el.logInspector.textContent = selected
    ? [
      "时间：" + (selected.time ? new Date(selected.time).toLocaleString("zh-CN", { hour12: false }) : "-"),
      "级别：" + (selected.level || "INFO"),
      "来源：" + (selected.source || "service"),
      selected.roundId ? ("场次：" + selected.roundId) : "",
      "摘要：" + (selected.summary || "-"),
      "详情：" + (selected.detail || "无")
    ].filter(Boolean).join("\n")
    : "选择一条日志查看详情。";
  el.eventTimeline.replaceChildren(...rows.slice(0, 6).map((event) => {
    const item = document.createElement("div");
    const dot = document.createElement("span");
    if (event.level === "INFO") dot.className = "ok";
    const title = document.createElement("strong");
    title.textContent = event.summary || "事件";
    const meta = document.createElement("small");
    meta.textContent = (event.source || "service") + " · " + (event.time ? new Date(event.time).toLocaleTimeString("zh-CN", { hour12: false }) : "");
    item.append(dot, title, meta);
    return item;
  }));
}

el.startForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const activity = el.activityName.value.trim() || defaultActivityName();
  const name = el.roundName.value.trim() || defaultRoundName();
  const url = el.liveUrl.value.trim();
  await sendCommand("开始 " + activity + "|" + name + (url ? (" " + url) : ""));
  el.activityName.value = defaultActivityName();
  el.roundName.value = "";
});
el.postRecordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const activity = el.postActivityName.value.trim() || defaultActivityName();
  const name = el.postRoundName.value.trim() || defaultFullRecordingName();
  const url = el.postLiveUrl.value.trim() || configuredDefaults().mgtvUrl || "";
  try {
    await sendCommand("开始 " + activity + "|" + name + (url ? (" " + url) : ""));
    el.postRoundName.value = "";
    addLog("全程录制/弹幕场次已启动。结束后可在下方回看、打标和截片段。");
  } catch (error) {
    addLog("开始全程录制失败：" + error.message);
  }
});

el.endRound.addEventListener("click", () => sendCommand("结束").catch((error) => addLog(error.message)));
el.publish.addEventListener("click", () => sendCommand("发布粗略").catch((error) => addLog(error.message)));
el.preciseForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const round = selectedRound();
  const file = el.preciseFile.files && el.preciseFile.files[0];
  if (!round || !file) return addLog("请先选择场次和精确结果文件");
  const body = new FormData();
  body.append("file", file);
  try {
    const response = await fetch("/api/rounds/" + encodeURIComponent(round.id) + "/precise-result", { method: "POST", body });
    requireLogin(response);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "HTTP " + response.status);
    selectedResultByRound[round.id] = "precise";
    el.preciseFile.value = "";
    addLog("精确结果已校验并发布：" + (payload.publishUrl || payload.publishedAt));
    await load();
  } catch (error) {
    addLog("精确结果发布失败：" + error.message);
  }
});
el.refresh.addEventListener("click", () => load().then(() => addLog("已刷新")).catch((error) => addLog(error.message)));
el.rename.addEventListener("click", async () => {
  const round = selectedRound();
  const name = el.renameInput.value.trim();
  if (!round || !name) return;
  try {
    await sendCommand("切换 " + round.id);
    await sendCommand("命名 " + name);
  } catch (error) {
    addLog(error.message);
  }
});
el.deleteRound.addEventListener("click", async () => {
  const round = selectedRound();
  if (!round) return addLog("请先选择要删除的场次");
  if (round.status === "running") return addLog("场次正在采集中，请先结束本轮再删除");
  const label = (round.activity || "未分类活动") + " / " + roundDisplayName(round);
  if (!window.confirm("确认删除场次「" + label + "」？\n删除后会立即从运营端和飞书管理中移除；同步远端发布页后，公开页也会移除。")) return;
  const publish = confirmPublishAfterDelete("场次");
  try {
    const payload = await deleteJson(deleteUrl("/api/rounds/" + encodeURIComponent(round.id), publish));
    selectedRoundId = null;
    addLog("已删除场次：" + (payload.deletedRoundName || roundDisplayName(round)) + "\n" + publishStatusText(payload));
    await load();
  } catch (error) {
    addLog("删除场次失败：" + error.message);
  }
});
el.deleteActivity.addEventListener("click", async () => {
  const activity = selectedActivity;
  if (!activity) return addLog("请先选择要删除的活动");
  const sessions = (state && state.sessions) || [];
  const rounds = sessions.filter((item) => (item.activity || "未分类活动") === activity);
  const running = rounds.filter((item) => item.status === "running");
  if (running.length) return addLog("活动中仍有场次正在采集，请先结束后再删除");
  if (!window.confirm("确认删除活动「" + activity + "」下的 " + rounds.length + " 个场次？\n删除后会立即从运营端和飞书管理中移除；同步远端发布页后，公开页也会移除。")) return;
  const publish = confirmPublishAfterDelete("活动");
  try {
    const payload = await deleteJson(deleteUrl("/api/activities/" + encodeURIComponent(activity), publish));
    selectedActivity = null;
    selectedRoundId = null;
    addLog("已删除活动：" + (payload.deletedActivity || activity) + "（" + (payload.deletedRoundCount || 0) + " 个场次）\n" + publishStatusText(payload));
    await load();
  } catch (error) {
    addLog("删除活动失败：" + error.message);
  }
});
el.addMarker.addEventListener("click", async () => {
  const round = selectedRound();
  if (!round) return addLog("请先选择场次");
  const atSeconds = Number(el.recordingPlayer.currentTime || 0);
  const label = el.markerLabel.value.trim() || ("标记 " + formatSeconds(atSeconds));
  try {
    await postJson("/api/rounds/" + encodeURIComponent(round.id) + "/recording/markers", { label, atSeconds });
    el.markerLabel.value = "";
    addLog("已添加录屏标记：" + label + " @ " + formatSeconds(atSeconds));
    await load();
  } catch (error) {
    addLog("添加录屏标记失败：" + error.message);
  }
});
el.createClip.addEventListener("click", async () => {
  const round = selectedRound();
  if (!round) return addLog("请先选择场次");
  const startSeconds = Number(el.clipStart.value || 0);
  const endSeconds = Number(el.clipEnd.value || 0);
  if (!(endSeconds > startSeconds)) return addLog("截取结束时间必须大于开始时间");
  const label = el.clipLabel.value.trim() || (formatSeconds(startSeconds) + "-" + formatSeconds(endSeconds));
  try {
    const payload = await postJson("/api/rounds/" + encodeURIComponent(round.id) + "/recording/clips", {
      startSeconds,
      endSeconds,
      label
    });
    el.clipLabel.value = "";
    addLog("已截取片段：" + (payload.clip && payload.clip.label ? payload.clip.label : label));
    await load();
  } catch (error) {
    addLog("截取片段失败：" + error.message);
  }
});
el.roundSelect.addEventListener("change", () => {
  selectedRoundId = el.roundSelect.value;
  render();
});
el.resultButtons.forEach((button) => button.addEventListener("click", () => {
  const round = selectedRound();
  if (round && !button.disabled) selectedResultByRound[round.id] = button.dataset.resultType;
  render();
}));
el.activitySelect.addEventListener("change", () => {
  selectedActivity = el.activitySelect.value;
  selectedRoundId = null;
  render();
});

el.navItems.forEach((item) => item.addEventListener("click", () => switchPage(item.dataset.pageTarget)));
const settingsCloseButton = document.getElementById("settingsClose");
if (settingsCloseButton) settingsCloseButton.addEventListener("click", () => switchPage("activityPage"));
document.querySelectorAll("[data-work-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.workTab;
    document.querySelectorAll("[data-work-tab]").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll(".work-tab").forEach((tab) => tab.classList.toggle("active", tab.id === target));
  });
});

el.monitorSave.addEventListener("click", async () => {
  const activity = el.monitorActivity.value.trim() || defaultActivityName();
  const url = el.monitorUrl.value.trim() || configuredDefaults().mgtvUrl || "";
  if (!url) return addLog("请先填写活动链接");
  el.monitorSave.disabled = true;
  try {
    const settingsResponse = await fetch("/api/settings", { cache: "no-store" });
    requireLogin(settingsResponse);
    const settingsPayload = await settingsResponse.json();
    if (!settingsResponse.ok) throw new Error(settingsPayload.error || "配置读取失败");
    const currentSettings = settingsPayload.config || {};
    const vote = Object.assign({}, currentSettings.vote || {}, { activity });
    const mgtv = Object.assign({}, currentSettings.mgtv || {}, { url });
    const recording = Object.assign({}, currentSettings.recording || {}, { enabled: Boolean(el.monitorRecordVideo.checked) });
    const monitor = Object.assign({}, currentSettings.monitor || {}, {
      enabled: Boolean(el.monitorEnabled.checked),
      activity,
      url,
      auto_detect_source: Boolean(el.monitorAutoSource.checked),
      auto_record_video: Boolean(el.monitorRecordVideo.checked),
      auto_record_danmaku: Boolean(el.monitorRecordDanmaku.checked),
      feishu_notify: Boolean(el.monitorFeishuNotify.checked)
    });
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vote, mgtv, recording, monitor })
    });
    requireLogin(response);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "保存失败");
    if (typeof populateSettings === "function") populateSettings(payload.settings);
    el.monitorState.textContent = "监控策略已保存";
    el.monitorState.className = "update-status ready";
    addLog("活动监控策略已保存并热应用，后台会按策略自动检测与启动。");
    await load();
    await loadSystemStatus().catch(() => {});
  } catch (error) {
    addLog("活动监控保存失败：" + error.message);
  } finally {
    el.monitorSave.disabled = false;
  }
});

async function runSourceCheck() {
  const url = (el.monitorUrl && el.monitorUrl.value.trim()) || configuredDefaults().mgtvUrl || "";
  if (!url) return addLog("请先配置活动链接");
  try {
    const response = await fetch("/api/mgtv/source/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    });
    requireLogin(response);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "检测失败");
    addLog("直播源检测完成：" + (payload.actualQuality || payload.quality || "清晰度未知"));
    await load();
    await loadSystemStatus().catch(() => {});
  } catch (error) {
    addLog("直播源检测失败：" + error.message);
  }
}

el.monitorCheck.addEventListener("click", runSourceCheck);
el.detectFromOps.addEventListener("click", runSourceCheck);
el.syncFeishu.addEventListener("click", () => addLog("飞书卡片会随下一次飞书交互自动刷新；如需主动推送，请在飞书内点击控制卡片。"));
el.copyPublicLink.addEventListener("click", async () => {
  const url = "https://pyxxxx.github.io/MangoTV_Danmaku/";
  try {
    await navigator.clipboard.writeText(url);
    addLog("已复制公开链接：" + url);
  } catch (_) {
    addLog("公开链接：" + url);
  }
});
el.refreshSystem.addEventListener("click", () => loadSystemStatus().catch((error) => addLog(error.message)));
el.refreshLogs.addEventListener("click", () => loadSystemLogs().catch((error) => addLog(error.message)));
el.logSearch.addEventListener("input", renderSystemLogs);
el.logLevel.addEventListener("change", renderSystemLogs);
el.logSource.addEventListener("change", renderSystemLogs);
el.copyLogSummary.addEventListener("click", async () => {
  const summary = filteredLogs().slice(0, 12).map((event) => `[${event.level}] ${event.source}: ${event.summary}`).join("\n") || "暂无日志";
  try {
    await navigator.clipboard.writeText(summary);
    addLog("已复制排障摘要。");
  } catch (_) {
    addLog(summary);
  }
});

load().catch((error) => addLog(error.message));
setInterval(() => load().catch((error) => addLog(error.message)), 3000);
loadSystemStatus().catch(() => {});
loadSystemLogs().catch(() => {});
setInterval(() => {
  if (document.querySelector("#machinePage.active") || document.querySelector("#activityPage.active")) loadSystemStatus().catch(() => {});
  if (document.querySelector("#logsPage.active") && el.logFollow.checked) loadSystemLogs().catch(() => {});
}, 5000);
