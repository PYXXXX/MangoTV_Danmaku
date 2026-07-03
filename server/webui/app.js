const $ = (selector) => document.querySelector(selector);

const el = {
  subtitle: $("#subtitle"),
  activitySelect: $("#activitySelect"),
  roundSelect: $("#roundSelect"),
  liveState: $("#liveState"),
  liveText: $("#liveState span"),
  startForm: $("#startForm"),
  activityName: $("#activityName"),
  roundName: $("#roundName"),
  liveUrl: $("#liveUrl"),
  endRound: $("#endRound"),
  publish: $("#publish"),
  renameInput: $("#renameInput"),
  rename: $("#rename"),
  refresh: $("#refresh"),
  downloadSlice: $("#downloadSlice"),
  messages: $("#messages"),
  votes: $("#votes"),
  reviews: $("#reviews"),
  ranking: $("#ranking"),
  updated: $("#updated"),
  roundCount: $("#roundCount"),
  roundList: $("#roundList"),
  log: $("#log")
};

let state = null;
let selectedActivity = null;
let selectedRoundId = null;
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

async function sendCommand(text) {
  const response = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text })
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "HTTP " + response.status);
  addLog(payload.reply || "操作完成");
  await load();
  return payload.reply;
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

function renderRanking(round) {
  if (!round) {
    el.ranking.innerHTML = '<div class="empty">结果将在这里显示</div>';
    return 0;
  }
  const rows = (round.candidates || [])
    .map((candidate) => Object.assign({}, candidate, { count: (round.voteCounts && round.voteCounts[candidate.id]) || 0 }))
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
    option.textContent = (item.status === "running" ? "● " : "") + item.name;
    return option;
  }) : [new Option("暂无场次", "")]));
  el.roundList.replaceChildren(...filtered.map((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "round-item " + (item.id === (round && round.id) ? "active" : "");
    button.dataset.id = item.id;
    const title = document.createElement("strong");
    title.textContent = (item.status === "running" ? "● " : "") + item.name;
    const meta = document.createElement("span");
    meta.textContent = (item.activity || "未分类活动") + " · " + formatCount(item.messageCount) + " 样本";
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
  const total = renderRanking(round);
  const active = round && round.status === "running";
  el.liveState.classList.toggle("active", Boolean(active));
  el.liveText.textContent = active ? "LIVE · 采集中" : (round ? "场次已保存" : "等待场次");
  el.subtitle.textContent = round ? ((round.activity || "未分类活动") + " / " + round.name + " · " + round.status) : "等待开始场次";
  el.messages.textContent = formatCount(round && round.messageCount);
  el.messages.title = Number((round && round.messageCount) || 0).toLocaleString("zh-CN");
  el.votes.textContent = formatCount(total);
  el.votes.title = total.toLocaleString("zh-CN");
  el.reviews.textContent = formatCount(round && round.reviewCount);
  el.reviews.title = Number((round && round.reviewCount) || 0).toLocaleString("zh-CN");
  el.updated.textContent = state && state.publishedAt ? ("数据更新于 " + new Date(state.publishedAt).toLocaleString("zh-CN", { hour12: false })) : "尚未同步";
  if (document.activeElement !== el.renameInput) el.renameInput.value = (round && round.name) || "";
  if (round) {
    el.downloadSlice.href = "/api/rounds/" + encodeURIComponent(round.id) + ".jsonl";
    el.downloadSlice.classList.remove("disabled");
  } else {
    el.downloadSlice.href = "#";
    el.downloadSlice.classList.add("disabled");
  }
}

async function load() {
  const resultsResponse = await fetch("/api/results.json?t=" + Date.now(), { cache: "no-store" });
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

el.startForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const activity = el.activityName.value.trim() || selectedActivity || "未分类活动";
  const name = el.roundName.value.trim() || ("第 " + (((state && state.sessions && state.sessions.length) || 0) + 1) + " 轮");
  const url = el.liveUrl.value.trim();
  await sendCommand("开始 " + activity + "|" + name + (url ? (" " + url) : ""));
  el.activityName.value = "";
  el.roundName.value = "";
});

el.endRound.addEventListener("click", () => sendCommand("结束").catch((error) => addLog(error.message)));
el.publish.addEventListener("click", () => sendCommand("发布").catch((error) => addLog(error.message)));
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
el.roundSelect.addEventListener("change", () => {
  selectedRoundId = el.roundSelect.value;
  render();
});
el.activitySelect.addEventListener("change", () => {
  selectedActivity = el.activitySelect.value;
  selectedRoundId = null;
  render();
});

load().catch((error) => addLog(error.message));
setInterval(() => load().catch((error) => addLog(error.message)), 3000);
