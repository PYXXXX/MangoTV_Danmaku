const ranking = document.querySelector("#ranking");
const status = document.querySelector("#status");
const live = document.querySelector(".live");
const messages = document.querySelector("#messages");
const votes = document.querySelector("#votes");
const reviews = document.querySelector("#reviews");
const pageTitle = document.querySelector("#pageTitle");
const updated = document.querySelector("#updated");
const sessionSelect = document.querySelector("#sessionSelect");

function storageGet(keys) {
  return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
}

function storageSet(values) {
  return new Promise((resolve) => chrome.storage.local.set(values, resolve));
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
  const rows = (meta.candidates || [])
    .map((candidate) => ({ ...candidate, count: meta.voteCounts[candidate.id] || 0 }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "zh-CN"));
  const max = Math.max(1, ...rows.map((item) => item.count));
  const total = rows.reduce((sum, item) => sum + item.count, 0);

  ranking.replaceChildren(...rows.map((item, index) => {
    const row = document.createElement("article");
    row.className = "row";
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

async function render() {
  const state = await storageGet(null);
  const ids = state.sessionsIndex?.length
    ? state.sessionsIndex
    : (state.currentSessionId ? [state.currentSessionId] : []);
  const selectedId = state.selectedSessionId || state.currentSessionId || ids[0];
  const meta = selectedId ? state[`session:${selectedId}:meta`] : null;
  if (!meta) return;

  sessionSelect.replaceChildren(...ids.map((id) => {
    const item = state[`session:${id}:meta`];
    const option = document.createElement("option");
    option.value = id;
    option.textContent = `${item?.status === "running" ? "● " : ""}${item?.name || "未命名场次"}`;
    option.selected = id === selectedId;
    return option;
  }));
  const total = renderRanking(meta);
  const active = meta.status === "running";
  status.textContent = active ? "LIVE · 采集中" : "场次已保存";
  live.classList.toggle("active", active);
  messages.textContent = formatCount(meta.messageCount);
  messages.title = Number(meta.messageCount || 0).toLocaleString("zh-CN");
  votes.textContent = formatCount(total);
  votes.title = total.toLocaleString("zh-CN");
  reviews.textContent = formatCount(meta.reviewCount);
  reviews.title = Number(meta.reviewCount || 0).toLocaleString("zh-CN");
  pageTitle.textContent = `${meta.name} · ${meta.pageTitle || meta.pageUrl}`;
  updated.textContent = new Date(meta.updatedAt).toLocaleTimeString("zh-CN", { hour12: false });
}

sessionSelect.addEventListener("change", async () => {
  await storageSet({ selectedSessionId: sessionSelect.value });
  await render();
});

render();
setInterval(render, 1000);
