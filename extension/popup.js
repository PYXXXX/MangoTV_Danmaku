const $ = (selector) => document.querySelector(selector);
const elements = {
  candidateInput: $("#candidates"),
  multiPolicy: $("#multiPolicy"),
  sessionName: $("#sessionName"),
  start: $("#start"),
  stop: $("#stop"),
  status: $("#status"),
  messageCount: $("#messageCount"),
  reviewCount: $("#reviewCount"),
  sessionSelect: $("#sessionSelect"),
  renameInput: $("#renameInput"),
  rename: $("#rename"),
  roundStatus: $("#roundStatus"),
  resultList: $("#resultList"),
  dashboard: $("#dashboard"),
  export: $("#export"),
  error: $("#error"),
  publishEnabled: $("#publishEnabled"),
  githubOwner: $("#githubOwner"),
  githubRepo: $("#githubRepo"),
  githubBranch: $("#githubBranch"),
  githubPath: $("#githubPath"),
  githubToken: $("#githubToken"),
  publishInterval: $("#publishInterval"),
  publishNow: $("#publishNow"),
  publishStatus: $("#publishStatus")
};

let pollTimer = null;
let publisherInitialized = false;

function storageGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function storageSet(values) {
  return new Promise((resolve) => chrome.storage.local.set(values, resolve));
}

function sendToActiveTab(message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab?.id || !tab.url?.startsWith("https://www.mgtv.com/z/")) {
        reject(new Error("请先打开芒果 TV 直播页面，再操作采集。"));
        return;
      }
      chrome.tabs.sendMessage(tab.id, message, (response) => {
        if (chrome.runtime.lastError) reject(new Error("采集脚本未就绪，请刷新直播页后重试。"));
        else if (!response?.ok) reject(new Error(response?.error || "操作失败"));
        else resolve(response);
      });
    });
  });
}

function sendToBackground(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (!response?.ok) reject(new Error(response?.error || "同步失败"));
      else resolve(response);
    });
  });
}

function showError(error) {
  elements.error.hidden = !error;
  elements.error.textContent = error?.message || "";
}

function setLive(isLive) {
  elements.status.textContent = isLive ? "采集中" : "已保存";
  elements.status.className = `status ${isLive ? "live" : "idle"}`;
  elements.start.disabled = isLive;
  elements.stop.disabled = !isLive;
}

function safeFilename(text) {
  return String(text || "session").replace(/[\\/:*?"<>|]/g, "_").slice(0, 60);
}

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

function renderRanking(meta) {
  if (!meta) {
    elements.resultList.innerHTML = '<li class="empty">结果将在这里出现</li>';
    return;
  }
  const rows = (meta.candidates || [])
    .map((candidate) => ({ ...candidate, count: meta.voteCounts?.[candidate.id] || 0 }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "zh-CN"));
  elements.resultList.replaceChildren(...rows.map((item, index) => {
    const li = document.createElement("li");
    const rank = document.createElement("span"); rank.className = "result-rank"; rank.textContent = String(index + 1).padStart(2, "0");
    const name = document.createElement("span"); name.className = "result-name"; name.textContent = item.name;
    const count = document.createElement("strong"); count.textContent = formatCount(item.count); count.title = item.count.toLocaleString("zh-CN");
    li.append(rank, name, count);
    return li;
  }));
}

function initializePublisher(config = {}) {
  if (publisherInitialized) return;
  publisherInitialized = true;
  elements.publishEnabled.checked = Boolean(config.enabled);
  elements.githubOwner.value = config.owner || "";
  elements.githubRepo.value = config.repo || "";
  elements.githubBranch.value = config.branch || "main";
  elements.githubPath.value = config.path || "site/data/results.json";
  elements.githubToken.value = config.token || "";
  elements.publishInterval.value = String(config.intervalSeconds || 120);
}

function renderPublisherStatus(status) {
  if (!status) {
    elements.publishStatus.textContent = "未同步";
    elements.publishStatus.className = "publish-status";
    return;
  }
  const time = new Date(status.lastPublishedAt).toLocaleTimeString("zh-CN", { hour12: false });
  elements.publishStatus.textContent = status.ok ? `最近同步成功 · ${time}` : `同步失败 · ${status.error}`;
  elements.publishStatus.className = `publish-status ${status.ok ? "success" : "failed"}`;
}

async function refresh() {
  const state = await storageGet(null);
  const ids = state.sessionsIndex?.length
    ? state.sessionsIndex
    : (state.currentSessionId ? [state.currentSessionId] : []);
  const selectedId = state.selectedSessionId || state.currentSessionId || ids[0];
  const currentMeta = state.currentSessionId ? state[`session:${state.currentSessionId}:meta`] : null;
  const selectedMeta = selectedId ? state[`session:${selectedId}:meta`] : null;

  elements.sessionSelect.disabled = !ids.length;
  elements.renameInput.disabled = !selectedMeta;
  elements.rename.disabled = !selectedMeta;
  elements.export.disabled = !selectedMeta;
  elements.sessionSelect.replaceChildren(...(ids.length ? ids.map((id) => {
    const meta = state[`session:${id}:meta`];
    const option = document.createElement("option");
    option.value = id;
    option.textContent = `${meta?.status === "running" ? "● " : ""}${meta?.name || "未命名场次"}`;
    option.selected = id === selectedId;
    return option;
  }) : [new Option("暂无场次", "") ]));

  elements.messageCount.textContent = formatCount(selectedMeta?.messageCount);
  elements.messageCount.title = Number(selectedMeta?.messageCount || 0).toLocaleString("zh-CN");
  elements.reviewCount.textContent = formatCount(selectedMeta?.reviewCount);
  elements.reviewCount.title = Number(selectedMeta?.reviewCount || 0).toLocaleString("zh-CN");
  elements.roundStatus.textContent = selectedMeta
    ? (selectedMeta.status === "running" ? "正在采集" : `已结束 · ${new Date(selectedMeta.stoppedAt || selectedMeta.updatedAt).toLocaleTimeString("zh-CN", { hour12: false })}`)
    : "暂无场次";
  if (document.activeElement !== elements.renameInput) elements.renameInput.value = selectedMeta?.name || "";
  setLive(currentMeta?.status === "running");
  renderRanking(selectedMeta);
  initializePublisher(state.publisherSettings);
  renderPublisherStatus(state.publisherStatus);
}

elements.start.addEventListener("click", async () => {
  showError(null);
  try {
    const response = await sendToActiveTab({
      type: "START",
      settings: {
        sessionName: elements.sessionName.value,
        candidateText: elements.candidateInput.value,
        multiCandidatePolicy: elements.multiPolicy.value
      }
    });
    await storageSet({ selectedSessionId: response.session.id });
    elements.sessionName.value = "";
    await refresh();
  } catch (error) {
    showError(error);
  }
});

elements.stop.addEventListener("click", async () => {
  showError(null);
  try {
    const { currentSessionId } = await storageGet(["currentSessionId"]);
    await sendToActiveTab({ type: "STOP" });
    if (currentSessionId) await storageSet({ selectedSessionId: currentSessionId });
    await refresh();
  } catch (error) {
    showError(error);
  }
});

elements.sessionSelect.addEventListener("change", async () => {
  await storageSet({ selectedSessionId: elements.sessionSelect.value });
  await refresh();
});

elements.rename.addEventListener("click", async () => {
  showError(null);
  try {
    const { selectedSessionId } = await storageGet(["selectedSessionId"]);
    if (!selectedSessionId || !elements.renameInput.value.trim()) throw new Error("请输入场次名称");
    const key = `session:${selectedSessionId}:meta`;
    const state = await storageGet([key]);
    const meta = state[key];
    if (!meta) throw new Error("找不到所选场次");
    meta.name = elements.renameInput.value.trim();
    meta.updatedAt = new Date().toISOString();
    await storageSet({ [key]: meta });
    await sendToBackground({ type: "PUBLISH_STATE", force: true });
    await refresh();
  } catch (error) {
    showError(error);
  }
});

elements.dashboard.addEventListener("click", () => {
  chrome.tabs.create({ url: chrome.runtime.getURL("dashboard.html") });
});

elements.export.addEventListener("click", async () => {
  showError(null);
  try {
    try { await sendToActiveTab({ type: "FLUSH" }); } catch (_) { /* historical sessions need no active tab */ }
    const state = await storageGet(null);
    const sessionId = state.selectedSessionId || state.currentSessionId;
    if (!sessionId) throw new Error("还没有可导出的采集场次。");
    const meta = state[`session:${sessionId}:meta`];
    if (!meta) throw new Error("找不到场次数据。");
    const lines = [JSON.stringify({ type: "meta", ...meta })];
    for (let index = 0; index < (meta.chunkCount || 0); index += 1) {
      const chunk = state[`session:${sessionId}:chunk:${index}`] || [];
      for (const item of chunk) lines.push(JSON.stringify({ type: "message", ...item }));
    }
    const blob = new Blob([`${lines.join("\n")}\n`], { type: "application/x-ndjson" });
    const url = URL.createObjectURL(blob);
    chrome.downloads.download({ url, filename: `mgtv-danmaku-${safeFilename(meta.name)}-${sessionId}.jsonl`, saveAs: true }, () => {
      window.setTimeout(() => URL.revokeObjectURL(url), 30000);
    });
  } catch (error) {
    showError(error);
  }
});

elements.publishNow.addEventListener("click", async () => {
  showError(null);
  elements.publishNow.disabled = true;
  try {
    const config = {
      enabled: elements.publishEnabled.checked,
      owner: elements.githubOwner.value.trim(),
      repo: elements.githubRepo.value.trim(),
      branch: elements.githubBranch.value.trim() || "main",
      path: elements.githubPath.value.trim() || "site/data/results.json",
      token: elements.githubToken.value.trim(),
      intervalSeconds: Math.max(30, Number(elements.publishInterval.value) || 120)
    };
    await storageSet({ publisherSettings: config });
    await sendToBackground({ type: "PUBLISH_STATE", force: true });
    await refresh();
  } catch (error) {
    showError(error);
  } finally {
    elements.publishNow.disabled = false;
  }
});

(async () => {
  const { settings } = await storageGet(["settings"]);
  elements.candidateInput.value = settings?.candidateText || "张远, 远远\n窦靖童, 童童\n陈楚生, 陈老师\n妮达";
  elements.multiPolicy.value = settings?.multiCandidatePolicy || "all";
  await refresh();
  pollTimer = window.setInterval(refresh, 1000);
})();

window.addEventListener("unload", () => clearInterval(pollTimer));
