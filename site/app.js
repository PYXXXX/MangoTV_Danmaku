const elements = {
  pageTitle: document.querySelector("#pageTitle"),
  resultBadge: document.querySelector("#resultBadge"),
  precisionBadge: document.querySelector("#precisionBadge"),
  updatedBadge: document.querySelector("#updatedBadge"),
  currentRound: document.querySelector("#currentRound"),
  currentRoundMeta: document.querySelector("#currentRoundMeta"),
  winnerCard: document.querySelector("#winnerCard"),
  activitySelect: document.querySelector("#activitySelect"),
  sessionSelect: document.querySelector("#sessionSelect"),
  resultButtons: Array.from(document.querySelectorAll("#resultMode [data-result-type]")),
  liveState: document.querySelector("#liveState"),
  liveText: document.querySelector("#liveState span"),
  program: document.querySelector("#program"),
  publicActivityNav: document.querySelector("#publicActivityNav"),
  exportPng: document.querySelector("#exportPng"),
  exportPngSide: document.querySelector("#exportPngSide"),
  copyShare: document.querySelector("#copyShare"),
  timeline: document.querySelector("#timeline"),
  recentPublish: document.querySelector("#recentPublish"),
  messages: document.querySelector("#messages"),
  votes: document.querySelector("#votes"),
  reviews: document.querySelector("#reviews"),
  ranking: document.querySelector("#ranking"),
  updated: document.querySelector("#updated")
};

let publicState = null;
let selectedActivity = null;
let selectedSessionId = null;
const selectedResultBySession = {};
let currentView = null;
const DATA_SOURCE_URL = "https://pyxxxx.github.io/MangoTV_Danmaku/";

function formatCount(value) {
  const number = Number(value || 0);
  if (number < 1000) return number.toLocaleString("zh-CN");
  const units = [
    { value: 1_000_000_000, suffix: "b" },
    { value: 1_000_000, suffix: "m" },
    { value: 1_000, suffix: "k" }
  ];
  const unit = units.find((item) => number >= item.value);
  const scaled = number / unit.value;
  const digits = scaled < 10 ? 1 : 0;
  return scaled.toFixed(digits).replace(/\.0$/, "") + unit.suffix;
}

function selectedResult(session) {
  const available = session.results || {};
  const requested = selectedResultBySession[session.id] || session.defaultResultType || "rough";
  const type = requested === "precise" && available.precise ? "precise" : "rough";
  return {
    type,
    data: available[type] || { voteCounts: session.voteCounts || {}, messageCount: session.messageCount || 0, reviewCount: session.reviewCount || 0 }
  };
}

function selectedSession() {
  const sessions = publicState?.sessions || [];
  if (!sessions.length) return null;
  const activities = Array.from(new Set(sessions.map((item) => item.activity || "未分类活动")));
  if (!selectedActivity || !activities.includes(selectedActivity)) {
    const active = sessions.find((item) => item.id === publicState.activeSessionId);
    selectedActivity = active?.activity || activities[0];
  }
  const filtered = sessions.filter((item) => (item.activity || "未分类活动") === selectedActivity);
  return filtered.find((item) => item.id === selectedSessionId)
    || filtered.find((item) => item.id === publicState.activeSessionId)
    || filtered[0]
    || null;
}

function renderRanking(session, result) {
  const rows = (session.candidates || [])
    .map((candidate) => ({ ...candidate, count: result?.voteCounts?.[candidate.id] || 0 }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "zh-CN"));
  const max = Math.max(1, ...rows.map((item) => item.count));
  const total = rows.reduce((sum, item) => sum + item.count, 0);
  elements.ranking.replaceChildren(...rows.map((item, index) => {
    const row = document.createElement("article"); row.className = "row";
    const rank = document.createElement("span"); rank.className = "rank"; rank.textContent = String(index + 1).padStart(2, "0");
    const name = document.createElement("span"); name.className = "name"; name.textContent = item.name;
    const track = document.createElement("div"); track.className = "track";
    const bar = document.createElement("div"); bar.className = "bar"; bar.style.width = `${(item.count / max) * 100}%`; track.append(bar);
    const count = document.createElement("strong"); count.className = "count"; count.textContent = formatCount(item.count); count.title = item.count.toLocaleString("zh-CN");
    row.append(rank, name, track, count);
    return row;
  }));
  return total;
}

function sortedRows(session, result) {
  return (session.candidates || [])
    .map((candidate) => ({ ...candidate, count: result?.voteCounts?.[candidate.id] || 0 }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "zh-CN"));
}

function renderWinner(rows, total) {
  if (!rows.length || !rows[0].count) {
    elements.winnerCard.textContent = "结果将在这里显示";
    return;
  }
  const leader = rows[0];
  const percent = total ? ((leader.count / total) * 100).toFixed(1) : "0.0";
  elements.winnerCard.innerHTML = "";
  const label = document.createElement("span");
  label.textContent = "当前领先";
  const name = document.createElement("strong");
  name.textContent = leader.name;
  const meta = document.createElement("small");
  meta.textContent = formatCount(leader.count) + " 票 · " + percent + "%";
  elements.winnerCard.append(label, name, meta);
}

function renderTimeline(sessions, selectedId) {
  elements.timeline.replaceChildren(...(sessions.length ? sessions.map((session) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = session.id === selectedId ? "active" : "";
    const title = document.createElement("strong");
    title.textContent = (session.results && session.results.precise ? "精确已校验 · " : "") + sessionDisplayName(session);
    const meta = document.createElement("span");
    meta.textContent = (session.status === "running" ? "进行中" : "已发布")
      + (sessionTimeRange(session) ? (" · " + sessionTimeRange(session)) : "")
      + " · " + formatCount(session.messageCount) + " 样本";
    button.append(title, meta);
    button.addEventListener("click", () => {
      selectedSessionId = session.id;
      selectedActivity = session.activity || "未分类活动";
      render();
    });
    return button;
  }) : [Object.assign(document.createElement("div"), { className: "empty", textContent: "暂无场次" })]));
}

function renderRecentPublish(sessions) {
  if (!elements.recentPublish) return;
  const rows = sessions
    .slice()
    .sort((a, b) => String(b.updatedAt || b.endedAt || b.startedAt || "").localeCompare(String(a.updatedAt || a.endedAt || a.startedAt || "")))
    .slice(0, 5);
  if (!rows.length) {
    elements.recentPublish.textContent = "等待发布记录";
    return;
  }
  elements.recentPublish.replaceChildren(...rows.map((session) => {
    const line = document.createElement("p");
    const result = session.results?.precise ? "精确结果已发布" : "粗略结果已发布";
    const time = session.endedAt || session.updatedAt || session.startedAt || publicState?.publishedAt || "";
    line.textContent = `${sessionDisplayName(session)} · ${result}${time ? ` · ${new Date(time).toLocaleTimeString("zh-CN", { hour12: false })}` : ""}`;
    return line;
  }));
}

function sessionDisplayName(session) {
  return session.displayName || session.baseName || session.name || "未命名场次";
}

function sessionTimeRange(session) {
  return session.timeRange || "";
}

function formatDateTime(value) {
  if (!value) return new Date().toLocaleString("zh-CN", { hour12: false });
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function fitText(ctx, text, maxWidth) {
  text = String(text || "");
  if (ctx.measureText(text).width <= maxWidth) return text;
  while (text && ctx.measureText(text + "…").width > maxWidth) text = text.slice(0, -1);
  return text ? text + "…" : "…";
}

function drawRoundRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function renderCurrentPng() {
  if (!currentView) return;
  const { session, result, resultType, rows, total } = currentView;
  const width = 1200;
  const rowHeight = 82;
  const visibleRows = Math.max(1, Math.min(rows.length, 12));
  const height = Math.max(900, 510 + visibleRows * rowHeight);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  const left = 68;
  const right = width - 68;
  const orange = "#ff7a1a";
  const muted = "#777a81";
  const line = "#2a2c30";
  const text = "#f5f5f3";
  const fontStack = '"PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif';
  ctx.fillStyle = "#0d0e10";
  ctx.fillRect(0, 0, width, height);
  const glow = ctx.createRadialGradient(width - 70, 40, 20, width - 70, 40, 520);
  glow.addColorStop(0, "rgba(255,122,26,.26)");
  glow.addColorStop(1, "rgba(255,122,26,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, width, 520);

  ctx.fillStyle = orange;
  ctx.font = `700 18px ui-monospace, monospace`;
  ctx.fillText("LIVE OPS DATA", left, 76);
  ctx.fillStyle = text;
  ctx.font = `700 58px ${fontStack}`;
  ctx.fillText("直播运营数据看板", left, 138);

  const status = resultType === "precise" ? "精确结果 · 已清洗" : (session.status === "running" ? "LIVE · 粗略统计中" : "粗略结果 · 本轮已结束");
  const displayName = sessionDisplayName(session);
  const program = `${session.activity || "未分类活动"} / ${displayName}${session.pageTitle ? ` · ${session.pageTitle}` : ""}`;
  ctx.fillStyle = muted;
  ctx.font = `22px ${fontStack}`;
  ctx.fillText(fitText(ctx, program, right - left - 190), left, 184);
  if (sessionTimeRange(session)) {
    ctx.font = `18px ${fontStack}`;
    ctx.fillText(fitText(ctx, `采集时间：${sessionTimeRange(session)}`, right - left - 190), left, 214);
  }
  ctx.font = `18px ${fontStack}`;
  const badgeWidth = ctx.measureText(status).width + 34;
  ctx.fillStyle = "#2a211b";
  drawRoundRect(ctx, right - badgeWidth, 70, badgeWidth, 42, 21);
  ctx.fill();
  ctx.strokeStyle = "#5d3c24";
  ctx.stroke();
  ctx.fillStyle = "#ff9a50";
  ctx.fillText(status, right - badgeWidth + 17, 97);
  ctx.strokeStyle = line;
  ctx.beginPath();
  ctx.moveTo(left, 220);
  ctx.lineTo(right, 220);
  ctx.stroke();

  const messageCount = resultType === "precise" ? result?.audit?.inputMessages : result?.messageCount;
  const reviewCount = resultType === "precise" ? result?.audit?.unresolvedReviewMessages : result?.reviewCount;
  const metrics = [["弹幕样本", formatCount(messageCount)], ["有效计票", formatCount(total)], ["语义待审", formatCount(reviewCount)]];
  const metricY = 256;
  const metricWidth = (right - left) / 3;
  metrics.forEach(([label, value], index) => {
    const x = left + index * metricWidth;
    if (index) {
      ctx.strokeStyle = line;
      ctx.beginPath();
      ctx.moveTo(x - 24, metricY - 12);
      ctx.lineTo(x - 24, metricY + 80);
      ctx.stroke();
    }
    ctx.fillStyle = muted;
    ctx.font = `18px ${fontStack}`;
    ctx.fillText(label, x, metricY + 18);
    ctx.fillStyle = text;
    ctx.font = `700 38px ui-monospace, monospace`;
    ctx.fillText(value, x, metricY + 65);
  });

  const rankingY = 390;
  ctx.fillStyle = text;
  ctx.font = `30px ${fontStack}`;
  ctx.fillText("结果排行", left, rankingY - 30);
  ctx.fillStyle = muted;
  ctx.font = `18px ${fontStack}`;
  ctx.fillText("票数", right - 160, rankingY - 28);
  const maxVotes = Math.max(1, ...rows.map((item) => item.count));
  if (!rows.length) {
    ctx.fillStyle = muted;
    ctx.font = `30px ${fontStack}`;
    ctx.fillText("暂无候选人。", left, rankingY + 60);
  }
  rows.slice(0, 12).forEach((item, index) => {
    const y = rankingY + index * rowHeight;
    ctx.strokeStyle = "#222428";
    ctx.beginPath();
    ctx.moveTo(left, y + rowHeight - 10);
    ctx.lineTo(right, y + rowHeight - 10);
    ctx.stroke();
    ctx.fillStyle = "#686b72";
    ctx.font = `18px ui-monospace, monospace`;
    ctx.fillText(String(index + 1).padStart(2, "0"), left, y + 38);
    ctx.fillStyle = text;
    ctx.font = `30px ${fontStack}`;
    ctx.fillText(fitText(ctx, item.name, 280), left + 70, y + 38);
    const barX = left + 365;
    const barY = y + 35;
    const barW = 445;
    ctx.fillStyle = "#24262a";
    drawRoundRect(ctx, barX, barY, barW, 12, 6);
    ctx.fill();
    const fillW = item.count ? Math.max(4, Math.round(barW * item.count / maxVotes)) : 4;
    ctx.fillStyle = orange;
    drawRoundRect(ctx, barX, barY, fillW, 12, 6);
    ctx.fill();
    const count = formatCount(item.count);
    ctx.font = `700 38px ui-monospace, monospace`;
    ctx.fillStyle = text;
    ctx.fillText(count, right - ctx.measureText(count).width, y + 42);
  });

  const footerY = height - 118;
  ctx.fillStyle = "#17181b";
  drawRoundRect(ctx, left, footerY, right - left, 54, 14);
  ctx.fill();
  ctx.strokeStyle = "#2c2e33";
  ctx.stroke();
  ctx.fillStyle = "#b9bbc1";
  ctx.font = `18px ${fontStack}`;
  ctx.fillText("统计数据不代表湖南卫视 & 芒果 TV 立场，仅供娱乐参考。", left + 18, footerY + 34);
  ctx.strokeStyle = "#222428";
  ctx.beginPath();
  ctx.moveTo(left, height - 44);
  ctx.lineTo(right, height - 44);
  ctx.stroke();
  ctx.fillStyle = "#858890";
  ctx.fillText(`数据来源：${DATA_SOURCE_URL}`, left, height - 58);
  ctx.fillStyle = "#666970";
  ctx.fillText("页面仅展示聚合票数，不包含观众昵称与原始弹幕", left, height - 30);
  const publishText = `数据发布于 ${formatDateTime(publicState?.publishedAt)}`;
  const exportText = `导出时间 ${formatDateTime()}`;
  ctx.fillText(publishText, right - ctx.measureText(publishText).width, height - 58);
  ctx.fillText(exportText, right - ctx.measureText(exportText).width, height - 30);

  const link = document.createElement("a");
  link.download = `mgtv-result-${session.id}-${resultType}.png`;
  link.href = canvas.toDataURL("image/png");
  link.click();
}

function render() {
  const sessions = publicState?.sessions || [];
  if (!sessions.length) return;
  const activities = Array.from(new Set(sessions.map((item) => item.activity || "未分类活动")));
  if (!selectedActivity || !activities.includes(selectedActivity)) {
    const active = sessions.find((item) => item.id === publicState.activeSessionId);
    selectedActivity = active?.activity || activities[0];
  }
  elements.activitySelect.disabled = false;
  elements.activitySelect.replaceChildren(...activities.map((activity) => {
    const option = document.createElement("option");
    option.value = activity;
    option.textContent = activity;
    option.selected = activity === selectedActivity;
    return option;
  }));
  const filtered = sessions.filter((item) => (item.activity || "未分类活动") === selectedActivity);
  const session = selectedSession();
  if (!session) return;
  selectedSessionId = session.id;
  elements.sessionSelect.disabled = false;
  elements.sessionSelect.replaceChildren(...filtered.map((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.status === "running" ? "● " : ""}${sessionDisplayName(item)}`;
    option.selected = item.id === selectedSessionId;
    return option;
  }));
  const current = selectedResult(session);
  const rows = sortedRows(session, current.data);
  const total = renderRanking(session, current.data);
  currentView = { session, result: current.data, resultType: current.type, rows, total };
  elements.exportPng.disabled = false;
  if (elements.exportPngSide) elements.exportPngSide.disabled = false;
  elements.pageTitle.textContent = `${session.activity || selectedActivity || "直播活动"} · 直播弹幕投票统计`;
  if (elements.publicActivityNav) elements.publicActivityNav.textContent = session.activity || selectedActivity || "直播活动";
  elements.currentRound.textContent = sessionDisplayName(session);
  elements.currentRoundMeta.textContent = sessionTimeRange(session) || (session.status === "running" ? "正在采集" : "暂无场次时间");
  elements.resultBadge.textContent = current.type === "precise" ? "精确结果" : "粗略结果";
  elements.precisionBadge.textContent = session.results?.precise ? "精确结果已发布" : "精确结果待发布";
  elements.updatedBadge.textContent = publicState?.publishedAt
    ? `数据更新于 ${new Date(publicState.publishedAt).toLocaleString("zh-CN", { hour12: false })}`
    : "尚未同步";
  renderWinner(rows, total);
  renderTimeline(filtered, session.id);
  renderRecentPublish(sessions);
  const active = session.status === "running";
  elements.liveState.classList.toggle("active", active);
  elements.liveText.textContent = current.type === "precise" ? "精确结果 · 已清洗" : (active ? "LIVE · 粗略统计中" : "粗略结果 · 本轮已结束");
  const hasPrecise = Boolean(session.results?.precise);
  elements.resultButtons.forEach((button) => {
    const type = button.dataset.resultType;
    const selected = type === current.type;
    button.disabled = type === "precise" && !hasPrecise;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
    button.title = type === "precise" && !hasPrecise ? "精确结果尚未发布" : "";
  });
  const range = sessionTimeRange(session);
  elements.program.textContent = `${session.activity || "未分类活动"} / ${sessionDisplayName(session)}${session.pageTitle ? ` · ${session.pageTitle}` : ""}${range ? ` · 采集时间：${range}` : ""}`;
  const messageCount = current.type === "precise" ? current.data?.audit?.inputMessages : current.data?.messageCount;
  const reviewCount = current.type === "precise" ? current.data?.audit?.unresolvedReviewMessages : current.data?.reviewCount;
  elements.messages.textContent = formatCount(messageCount);
  elements.messages.title = Number(messageCount || 0).toLocaleString("zh-CN");
  elements.votes.textContent = formatCount(total);
  elements.votes.title = total.toLocaleString("zh-CN");
  elements.reviews.textContent = formatCount(reviewCount);
  elements.reviews.title = Number(reviewCount || 0).toLocaleString("zh-CN");
  elements.updated.textContent = publicState?.publishedAt
    ? `数据发布于 ${new Date(publicState.publishedAt).toLocaleString("zh-CN", { hour12: false })}`
    : "尚未同步";
}

async function load() {
  try {
    const response = await fetch(`./data/results.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    publicState = await response.json();
    render();
  } catch (error) {
    elements.liveText.textContent = "数据暂不可用";
    elements.updated.textContent = `读取失败：${error.message}`;
    elements.exportPng.disabled = true;
    if (elements.exportPngSide) elements.exportPngSide.disabled = true;
  }
}

elements.sessionSelect.addEventListener("change", () => {
  selectedSessionId = elements.sessionSelect.value;
  render();
});
elements.activitySelect.addEventListener("change", () => {
  selectedActivity = elements.activitySelect.value;
  selectedSessionId = null;
  render();
});
elements.resultButtons.forEach((button) => button.addEventListener("click", () => {
  if (selectedSessionId && !button.disabled) selectedResultBySession[selectedSessionId] = button.dataset.resultType;
  render();
}));
elements.exportPng.addEventListener("click", renderCurrentPng);
if (elements.exportPngSide) elements.exportPngSide.addEventListener("click", renderCurrentPng);
if (elements.copyShare) elements.copyShare.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(window.location.href);
  } catch (_) {
    // Clipboard is optional on static hosting.
  }
});

load();
setInterval(load, 30000);
