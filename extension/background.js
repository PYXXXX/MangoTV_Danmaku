"use strict";

let publishQueue = Promise.resolve();

const storage = {
  get(keys) {
    return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
  },
  set(values) {
    return new Promise((resolve) => chrome.storage.local.set(values, resolve));
  }
};

function utf8Base64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function cleanPath(path) {
  return String(path || "site/data/results.json").replace(/^\/+/, "");
}

function apiPath(path) {
  return cleanPath(path).split("/").map(encodeURIComponent).join("/");
}

function publicSession(meta) {
  return {
    id: meta.id,
    name: meta.name || "未命名场次",
    status: meta.status,
    startedAt: meta.startedAt,
    updatedAt: meta.updatedAt,
    stoppedAt: meta.stoppedAt || null,
    pageTitle: meta.pageTitle || "",
    candidates: meta.candidates || [],
    messageCount: meta.messageCount || 0,
    reviewCount: meta.reviewCount || 0,
    voteCounts: meta.voteCounts || {}
  };
}

async function buildPublicState(allState) {
  const sessionIds = allState.sessionsIndex?.length
    ? allState.sessionsIndex
    : (allState.currentSessionId ? [allState.currentSessionId] : []);
  const sessions = sessionIds
    .map((id) => allState[`session:${id}:meta`])
    .filter(Boolean)
    .map(publicSession);
  return {
    schemaVersion: 1,
    publishedAt: new Date().toISOString(),
    activeSessionId: allState.currentSessionId || sessions[0]?.id || null,
    sessions
  };
}

async function githubRequest(url, options, token) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
      ...(options?.headers || {})
    }
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(`GitHub ${response.status}: ${detail.message || response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
}

async function publishNow(force = false) {
  const allState = await storage.get(null);
  const config = allState.publisherSettings || {};
  if (!config.enabled) return { skipped: "disabled" };
  if (!config.owner || !config.repo || !config.token) {
    if (force) throw new Error("请先完整填写 GitHub 仓库和令牌配置");
    return { skipped: "unconfigured" };
  }

  const intervalMs = Math.max(30, Number(config.intervalSeconds) || 120) * 1000;
  const lastPublishedAt = Date.parse(allState.publisherStatus?.lastPublishedAt || 0);
  if (!force && Date.now() - lastPublishedAt < intervalMs) return { skipped: "throttled" };

  const branch = config.branch || "main";
  const path = cleanPath(config.path);
  const base = `https://api.github.com/repos/${encodeURIComponent(config.owner)}/${encodeURIComponent(config.repo)}/contents/${apiPath(path)}`;
  const queryUrl = `${base}?ref=${encodeURIComponent(branch)}`;
  let sha;
  try {
    const existing = await githubRequest(queryUrl, { method: "GET" }, config.token);
    sha = existing.sha;
  } catch (error) {
    if (!String(error.message).startsWith("GitHub 404:")) throw error;
  }

  const publicState = await buildPublicState(allState);
  const body = {
    message: `data: sync vote results ${publicState.publishedAt}`,
    content: utf8Base64(`${JSON.stringify(publicState, null, 2)}\n`),
    branch,
    ...(sha ? { sha } : {})
  };
  const result = await githubRequest(base, { method: "PUT", body: JSON.stringify(body) }, config.token);
  const status = {
    ok: true,
    lastPublishedAt: publicState.publishedAt,
    commitUrl: result?.commit?.html_url || "",
    error: ""
  };
  await storage.set({ publisherStatus: status });
  return status;
}

function queuePublish(force) {
  const run = () => publishNow(force).catch(async (error) => {
    const status = { ok: false, lastPublishedAt: new Date().toISOString(), commitUrl: "", error: error.message };
    await storage.set({ publisherStatus: status });
    throw error;
  });
  publishQueue = publishQueue.then(run, run);
  return publishQueue;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "PUBLISH_STATE") return false;
  queuePublish(Boolean(message.force))
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: error.message }));
  return true;
});
