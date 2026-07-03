(() => {
  "use strict";

  const MESSAGE_SELECTOR = ".u-hotchat-list .barrageContent, .barrageContent";
  const ROW_SELECTOR = "li";
  const NICKNAME_SELECTOR = ".u-hc-name";
  const FLUSH_SIZE = 50;
  const FLUSH_INTERVAL_MS = 2000;
  const PAGE_SESSION_KEY = "mgtvVoteSessionId";

  let running = false;
  let session = null;
  let settings = null;
  let observer = null;
  let buffer = [];
  let seen = new WeakSet();
  let flushTimer = null;
  let flushChain = Promise.resolve();

  const storage = {
    get(keys) {
      return new Promise((resolve) => chrome.storage.local.get(keys, resolve));
    },
    set(values) {
      return new Promise((resolve) => chrome.storage.local.set(values, resolve));
    }
  };

  function normalize(text) {
    return String(text || "").normalize("NFKC").replace(/\s+/g, " ").trim();
  }

  function parseCandidates(candidateText) {
    return String(candidateText || "")
      .split(/\n+/)
      .map((line, index) => {
        const parts = line.split(/[,，;；|]/).map(normalize).filter(Boolean);
        return parts.length
          ? { id: `c${index + 1}`, name: parts[0], aliases: [...new Set(parts)] }
          : null;
      })
      .filter(Boolean);
  }

  function matchCandidates(content) {
    const normalized = normalize(content).toLocaleLowerCase("zh-CN");
    return settings.candidates.filter((candidate) =>
      candidate.aliases.some((alias) => normalized.includes(alias.toLocaleLowerCase("zh-CN")))
    );
  }

  function extractMessage(element) {
    if (!(element instanceof Element) || seen.has(element)) return null;
    seen.add(element);

    const content = normalize(element.getAttribute("title") || element.textContent);
    if (!content) return null;
    const row = element.closest(ROW_SELECTOR);
    const nickname = normalize(row?.querySelector(NICKNAME_SELECTOR)?.textContent).replace(/[：:]$/, "");
    const matches = matchCandidates(content);
    const allMatches = matches.map((item) => item.id);
    const voteMatches = settings.multiCandidatePolicy === "review" && allMatches.length > 1 ? [] : allMatches;

    return {
      ts: new Date().toISOString(),
      nickname,
      content,
      matches: allMatches,
      votes: voteMatches,
      needsReview: allMatches.length > 1,
      url: location.href
    };
  }

  function collect(root) {
    if (!running) return;
    const elements = [];
    if (root instanceof Element && root.matches(MESSAGE_SELECTOR)) elements.push(root);
    if (root instanceof Element || root instanceof Document) {
      elements.push(...root.querySelectorAll(MESSAGE_SELECTOR));
    }
    for (const element of elements) {
      const message = extractMessage(element);
      if (message) buffer.push(message);
    }
    if (buffer.length >= FLUSH_SIZE) void flush();
  }

  async function flushOnce() {
    if (!session || buffer.length === 0) return;
    const batch = buffer.splice(0, buffer.length);
    const metaKey = `session:${session.id}:meta`;
    const state = await storage.get([metaKey]);
    const meta = state[metaKey] || session;
    const chunkIndex = meta.chunkCount || 0;
    const chunkKey = `session:${session.id}:chunk:${chunkIndex}`;

    for (const message of batch) {
      meta.messageCount = (meta.messageCount || 0) + 1;
      meta.reviewCount = (meta.reviewCount || 0) + (message.needsReview ? 1 : 0);
      for (const candidateId of message.votes) {
        meta.voteCounts[candidateId] = (meta.voteCounts[candidateId] || 0) + 1;
      }
    }
    meta.chunkCount = chunkIndex + 1;
    meta.updatedAt = new Date().toISOString();
    session = meta;
    await storage.set({ [chunkKey]: batch, [metaKey]: meta, currentSessionId: session.id });
    void requestPublish(false);
  }

  function flush() {
    flushChain = flushChain.then(flushOnce, flushOnce);
    return flushChain;
  }

  function requestPublish(force = false) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "PUBLISH_STATE", force }, (response) => {
        resolve(response || { ok: false, error: chrome.runtime.lastError?.message || "同步请求失败" });
      });
    });
  }

  function attachObserver() {
    observer?.disconnect();
    observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) collect(node);
      }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    collect(document);
  }

  async function start(newSettings) {
    if (running) await stop("restarted");
    const candidates = parseCandidates(newSettings.candidateText);
    if (!candidates.length) throw new Error("请至少配置一位候选人");
    const aliasOwners = new Map();
    for (const candidate of candidates) {
      for (const alias of candidate.aliases) {
        const key = alias.toLocaleLowerCase("zh-CN");
        const owner = aliasOwners.get(key);
        if (owner && owner !== candidate.name) {
          throw new Error(`别名“${alias}”同时属于 ${owner} 和 ${candidate.name}，请修改后重试`);
        }
        aliasOwners.set(key, candidate.name);
      }
    }

    settings = { ...newSettings, candidates };
    const existing = await storage.get(["sessionsIndex", "currentSessionId"]);
    const previousSessions = existing.sessionsIndex?.length
      ? existing.sessionsIndex
      : (existing.currentSessionId ? [existing.currentSessionId] : []);
    const id = `${new Date().toISOString().replace(/[:.]/g, "-")}-${Math.random().toString(36).slice(2, 8)}`;
    session = {
      id,
      name: normalize(newSettings.sessionName) || `第 ${previousSessions.length + 1} 轮`,
      status: "running",
      startedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      stoppedAt: null,
      pageUrl: location.href,
      pageTitle: document.title,
      candidates,
      multiCandidatePolicy: settings.multiCandidatePolicy || "all",
      messageCount: 0,
      reviewCount: 0,
      voteCounts: Object.fromEntries(candidates.map((item) => [item.id, 0])),
      chunkCount: 0
    };
    seen = new WeakSet();
    buffer = [];
    flushChain = Promise.resolve();
    running = true;
    sessionStorage.setItem(PAGE_SESSION_KEY, id);
    await storage.set({
      settings: {
        candidateText: newSettings.candidateText,
        multiCandidatePolicy: newSettings.multiCandidatePolicy
      },
      currentSessionId: id,
      selectedSessionId: id,
      sessionsIndex: [id, ...previousSessions.filter((sessionId) => sessionId !== id)],
      [`session:${id}:meta`]: session
    });
    attachObserver();
    flushTimer = setInterval(() => void flush(), FLUSH_INTERVAL_MS);
    void requestPublish(false);
    return session;
  }

  async function stop(reason = "manual") {
    if (!session) return null;
    running = false;
    observer?.disconnect();
    observer = null;
    clearInterval(flushTimer);
    flushTimer = null;
    await flush();
    session.status = "stopped";
    session.stopReason = reason;
    session.stoppedAt = new Date().toISOString();
    session.updatedAt = session.stoppedAt;
    await storage.set({ [`session:${session.id}:meta`]: session });
    await requestPublish(true);
    sessionStorage.removeItem(PAGE_SESSION_KEY);
    return session;
  }

  async function markReloadedSessionStopped() {
    const sessionId = sessionStorage.getItem(PAGE_SESSION_KEY);
    if (!sessionId) return;
    const key = `session:${sessionId}:meta`;
    const state = await storage.get([key]);
    const meta = state[key];
    if (meta?.status === "running") {
      const now = new Date().toISOString();
      meta.status = "stopped";
      meta.stopReason = "page_reload";
      meta.stoppedAt = now;
      meta.updatedAt = now;
      await storage.set({ [key]: meta });
      await requestPublish(true);
    }
    sessionStorage.removeItem(PAGE_SESSION_KEY);
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    const reply = async () => {
      if (message.type === "PING") return { ok: true, running, sessionId: session?.id || null };
      if (message.type === "START") return { ok: true, session: await start(message.settings) };
      if (message.type === "STOP") return { ok: true, session: await stop() };
      if (message.type === "FLUSH") {
        await flush();
        return { ok: true };
      }
      return { ok: false, error: "未知指令" };
    };
    reply().then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  });

  window.addEventListener("beforeunload", () => {
    if (running) void flush();
  });

  void markReloadedSessionStopped();
})();
