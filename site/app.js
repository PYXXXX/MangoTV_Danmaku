const elements = {
  activitySelect: document.querySelector("#activitySelect"),
  sessionSelect: document.querySelector("#sessionSelect"),
  resultButtons: Array.from(document.querySelectorAll("#resultMode [data-result-type]")),
  liveState: document.querySelector("#liveState"),
  liveText: document.querySelector("#liveState span"),
  program: document.querySelector("#program"),
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

function sessionDisplayName(session) {
  return session.displayName || session.baseName || session.name || "未命名场次";
}

function sessionTimeRange(session) {
  return session.timeRange || "";
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
  const session = filtered.find((item) => item.id === selectedSessionId)
    || filtered.find((item) => item.id === publicState.activeSessionId)
    || filtered[0];
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
  const total = renderRanking(session, current.data);
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
  elements.updated.textContent = `数据发布于 ${new Date(publicState.publishedAt).toLocaleString("zh-CN", { hour12: false })}`;
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

load();
setInterval(load, 30000);
