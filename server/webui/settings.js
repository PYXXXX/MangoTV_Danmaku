const settingsEl = Object.fromEntries([
  "settingsToggle", "settingsPanel", "settingsClose", "settingsForm", "configStatus", "settingsFeedback", "saveSettings", "restartService",
  "cfgActivity", "cfgPolicy", "cfgCandidates",
  "cfgLiveUrl", "cfgRoomId", "cfgCameraId", "cfgHistoryApi", "cfgFlag", "cfgPollSeconds",
  "cfgReconnectSeconds", "cfgCountInitial", "cfgDedupHot", "cfgDedupMax", "cfgDedupDb",
  "mgtvUrlHint",
  "cfgGithubEnabled", "cfgGithubOwner", "cfgGithubRepo", "cfgGithubBranch", "cfgGithubPath",
  "cfgGithubToken", "githubSecretState",
  "cfgFeishuEnabled", "cfgFeishuMode", "cfgFeishuAppId", "cfgFeishuSecret", "cfgFeishuToken",
  "cfgFeishuOpenIds", "cfgFeishuChatIds", "cfgFeishuPublicUrl", "feishuSecretState",
  "feishuBindStatus", "feishuBindMessage", "feishuBindAppId", "feishuBindOpenId", "feishuBindTenant",
  "feishuBindWorker", "feishuBindingPending", "feishuBindingLink", "feishuBindingCode",
  "feishuBindingExpires", "feishuBindingFeedback", "startFeishuBinding",
  "cfgAuthEnabled", "cfgNewPassword", "cfgSessionHours", "cfgSecureCookie", "cfgMaxFailures",
  "cfgFailureWindow", "authSecretState",
  "updateCurrentCommit", "updateRemoteCommit", "updateBranch", "updateStatus", "updateFeedback",
  "updateProgressWrap", "updateProgressStage", "updateProgressPercent", "updateProgressBar",
  "updateProgressDetail", "updateProgressSpeed", "updateProgressLog", "checkUpdate", "applyUpdate",
  "cfgListenHost", "cfgListenPort", "cfgPublicBaseUrl", "cfgStorageDir"
].map((id) => [id, document.getElementById(id)]));

let settingsSnapshot = null;
let updatePollTimer = null;
let feishuBindingPollTimer = null;
let feishuBindingLastStatus = "";

function setField(id, value) {
  settingsEl[id].value = value == null ? "" : String(value);
}

function setChecked(id, value) {
  settingsEl[id].checked = Boolean(value);
}

function listText(value) {
  return Array.isArray(value) ? value.join("\n") : String(value || "");
}

function parseList(value) {
  return Array.from(new Set(String(value || "").split(/[,，\s]+/).map((item) => item.trim()).filter(Boolean)));
}

function candidatesText(candidates) {
  return (candidates || []).map((candidate) => {
    const aliases = (candidate.aliases || []).filter((alias) => alias !== candidate.name);
    return [candidate.name, ...aliases].join(", ");
  }).join("\n");
}

function parseCandidates(value) {
  return String(value || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const parts = line.split(/[,，]/).map((item) => item.trim()).filter(Boolean);
    return { name: parts[0] || "", aliases: Array.from(new Set(parts)) };
  });
}

function settingsDebug(message, ...args) {
  if (window.console && typeof window.console.debug === "function") {
    window.console.debug("[settings] " + message, ...args);
  }
}

function parseMgtvLiveUrl(value, flag = "liveshow") {
  const text = String(value || "").trim();
  if (!text) return null;
  const match = text.match(/\/z\/[^/?#]+\/([^/?#]+)/);
  if (!match) return null;
  const cameraId = match[1].replace(/\.html$/i, "").trim();
  if (!cameraId) return null;
  const roomFlag = String(flag || "liveshow").trim() || "liveshow";
  return {
    cameraId,
    roomId: roomFlag + "-" + cameraId,
    historyApi: "https://lb.bz.mgtv.com/get_history",
    flag: roomFlag
  };
}

function applyMgtvUrlAutofill() {
  const flag = settingsEl.cfgFlag.value.trim() || "liveshow";
  const parsed = parseMgtvLiveUrl(settingsEl.cfgLiveUrl.value, flag);
  if (!parsed) {
    if (settingsEl.mgtvUrlHint) {
      settingsEl.mgtvUrlHint.textContent = "未识别到 /z/{活动ID}/{camera_id}.html，可手动填写 room_id 或 camera_id。";
      settingsEl.mgtvUrlHint.className = "field-hint muted";
    }
    return false;
  }
  setField("cfgFlag", parsed.flag);
  setField("cfgCameraId", parsed.cameraId);
  setField("cfgRoomId", parsed.roomId);
  if (!settingsEl.cfgHistoryApi.value.trim()) setField("cfgHistoryApi", parsed.historyApi);
  if (settingsEl.mgtvUrlHint) {
    settingsEl.mgtvUrlHint.textContent = "已自动识别 camera_id=" + parsed.cameraId + "，room_id=" + parsed.roomId + "。";
    settingsEl.mgtvUrlHint.className = "field-hint success";
  }
  return true;
}

function updateConfigStatus(runtime) {
  const fields = (runtime && runtime.restartFields) || [];
  settingsEl.configStatus.className = "config-status " + (fields.length ? "restart" : "ready");
  settingsEl.configStatus.textContent = fields.length ? ("需重启 · " + fields.join("、")) : "热重载已就绪";
  settingsEl.restartService.hidden = !fields.length;
}

function shortCommit(value) {
  return value ? String(value).slice(0, 12) : "未读取";
}

function stageText(stage) {
  return {
    idle: "等待升级",
    queued: "排队中",
    preflight: "前置检查",
    fetch: "拉取代码",
    verify: "校验快进",
    merge: "切换版本",
    dependencies: "更新依赖",
    finalize: "收尾检查",
    restart: "等待重启",
    complete: "已完成",
    failed: "升级失败"
  }[stage] || "升级中";
}

function renderUpdateProgress(progress) {
  if (!progress || progress.status === "idle") {
    settingsEl.updateProgressWrap.hidden = true;
    settingsEl.updateProgressBar.style.width = "0%";
    return;
  }
  const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
  settingsEl.updateProgressWrap.hidden = false;
  settingsEl.updateProgressStage.textContent = stageText(progress.stage);
  settingsEl.updateProgressPercent.textContent = Math.round(percent) + "%";
  settingsEl.updateProgressBar.style.width = percent + "%";
  settingsEl.updateProgressDetail.textContent = progress.detail || "正在升级……";
  settingsEl.updateProgressSpeed.textContent = progress.speed || "-";
  settingsEl.updateProgressLog.textContent = ((progress.logs || []).slice(-8).join("\n")) || progress.detail || "正在升级……";
}

function renderUpdateStatus(payload) {
  settingsEl.updateCurrentCommit.textContent = shortCommit(payload && (payload.currentShort || payload.currentSha));
  settingsEl.updateRemoteCommit.textContent = shortCommit(payload && (payload.remoteShort || payload.remoteSha));
  settingsEl.updateBranch.textContent = payload && payload.remote
    ? [payload.remote, payload.remoteBranch || payload.branch || "main"].join("/")
    : "未读取";

  renderUpdateProgress(payload && payload.progress);
  settingsEl.applyUpdate.hidden = true;
  settingsEl.updateStatus.className = "update-status";

  if (!payload || payload.ok === false) {
    settingsEl.updateStatus.classList.add("error");
    settingsEl.updateStatus.textContent = "检查失败";
    settingsEl.updateFeedback.textContent = (payload && payload.error) || "暂时无法读取远端版本。";
    return;
  }

  const blockers = payload.blockers || [];
  if (payload.inProgress) {
    settingsEl.updateStatus.classList.add("available");
    settingsEl.updateStatus.textContent = "升级中";
    settingsEl.checkUpdate.disabled = true;
    settingsEl.applyUpdate.hidden = true;
    settingsEl.updateFeedback.textContent = "升级正在执行：" + ((payload.progress && payload.progress.detail) || "请稍候……");
    return;
  }
  settingsEl.checkUpdate.disabled = false;

  if (!payload.updateAvailable) {
    settingsEl.updateStatus.classList.add("ready");
    settingsEl.updateStatus.textContent = "已是最新";
    settingsEl.updateFeedback.textContent = "当前部署已经与远端目标分支一致。"
      + (blockers.length ? (" 但若之后出现新版本，当前状态会阻止自动升级：" + blockers.join("；")) : "");
    return;
  }

  if (payload.canApply) {
    settingsEl.updateStatus.classList.add("available");
    settingsEl.updateStatus.textContent = "发现新版本";
    settingsEl.applyUpdate.hidden = false;
    settingsEl.updateFeedback.textContent = "发现远端新 commit，可一键升级。升级会拉取代码、更新依赖并自动重启服务。"
      + (payload.restartWillApplyConfig ? " 本次重启也会让待重启配置一并生效。" : "");
    return;
  }

  settingsEl.updateStatus.classList.add("blocked");
  settingsEl.updateStatus.textContent = "暂不可升级";
  settingsEl.updateFeedback.textContent = blockers.length
    ? ("发现新版本，但当前被阻止：" + blockers.join("；"))
    : "发现新版本，但当前环境暂不可自动升级。";
}

function feishuBindingStatusText(status) {
  return {
    idle: "未绑定",
    pending: "等待授权",
    bound: "已绑定",
    failed: "绑定失败",
    expired: "已过期"
  }[status] || "未知";
}

function renderFeishuBinding(payload) {
  const status = (payload && payload.status) || "idle";
  const className = status === "bound" ? "ready" : (status === "pending" ? "available" : (status === "failed" || status === "expired" ? "error" : ""));
  settingsEl.feishuBindStatus.className = "update-status " + className;
  settingsEl.feishuBindStatus.textContent = feishuBindingStatusText(status);
  settingsEl.feishuBindMessage.textContent = (payload && (payload.error || payload.warning || payload.message))
    || "点击“发起绑定”后会打开飞书授权页；授权完成后本页会自动保存 App ID/Secret 并热重载 Bot。";
  settingsEl.feishuBindAppId.textContent = (payload && payload.appId) || "未配置";
  settingsEl.feishuBindOpenId.textContent = (payload && payload.openId) || "-";
  settingsEl.feishuBindTenant.textContent = (payload && payload.tenantBrand) || "-";
  settingsEl.feishuBindWorker.textContent = payload && payload.workerAlive ? "运行中" : "未运行";
  settingsEl.startFeishuBinding.disabled = status === "pending";
  settingsEl.startFeishuBinding.textContent = status === "pending" ? "等待飞书授权…" : "发起飞书绑定";

  const pending = status === "pending";
  settingsEl.feishuBindingPending.hidden = !pending;
  if (pending) {
    settingsEl.feishuBindingLink.href = payload.verificationUrl || "#";
    settingsEl.feishuBindingLink.textContent = payload.verificationUrl ? "打开飞书授权链接" : "等待授权链接";
    settingsEl.feishuBindingCode.textContent = payload.userCode || "-";
    const seconds = Math.max(0, Math.ceil(((payload.expiresAt || 0) * 1000 - Date.now()) / 1000));
    settingsEl.feishuBindingExpires.textContent = seconds ? (Math.floor(seconds / 60) + "分" + String(seconds % 60).padStart(2, "0") + "秒") : "即将过期";
    settingsEl.feishuBindingFeedback.textContent = "请完成飞书页面里的授权/安装步骤；本页会每 2 秒自动检查结果。";
  } else if (status === "bound") {
    const openCount = ((payload && payload.allowedOpenIds) || []).length;
    const chatCount = ((payload && payload.allowedChatIds) || []).length;
    settingsEl.feishuBindingFeedback.textContent = "绑定已完成。当前 open_id 白名单 " + openCount + " 项，chat_id 白名单 " + chatCount + " 项；群控请把机器人加入运营群后发送“我的ID”。";
  } else {
    settingsEl.feishuBindingFeedback.textContent = "绑定成功后，请把机器人添加到运营群，并在群里发送“我的ID”获取 chat_id，再填入下方白名单。";
  }
}

function stopFeishuBindingPolling() {
  if (feishuBindingPollTimer) {
    clearInterval(feishuBindingPollTimer);
    feishuBindingPollTimer = null;
  }
}

function startFeishuBindingPolling() {
  stopFeishuBindingPolling();
  feishuBindingPollTimer = setInterval(() => {
    loadFeishuBinding(false).catch((error) => {
      settingsEl.feishuBindStatus.className = "update-status error";
      settingsEl.feishuBindStatus.textContent = "读取失败";
      settingsEl.feishuBindMessage.textContent = error.message;
      stopFeishuBindingPolling();
    });
  }, 2000);
}

async function loadFeishuBinding(showErrors = true) {
  const response = await fetch("/api/feishu/binding?t=" + Date.now(), { cache: "no-store" });
  requireLogin(response);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "飞书绑定状态读取失败");
  const previous = feishuBindingLastStatus;
  feishuBindingLastStatus = payload.status || "";
  renderFeishuBinding(payload);
  if (payload.status === "pending") {
    startFeishuBindingPolling();
  } else {
    stopFeishuBindingPolling();
    if (payload.status === "bound" && previous === "pending") {
      await loadSettings(false);
    }
  }
  return payload;
}

function stopUpdatePolling() {
  if (updatePollTimer) {
    clearInterval(updatePollTimer);
    updatePollTimer = null;
  }
}

function startUpdatePolling() {
  stopUpdatePolling();
  updatePollTimer = setInterval(async () => {
    try {
      const response = await fetch("/api/update/status?t=" + Date.now(), { cache: "no-store" });
      requireLogin(response);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "版本状态读取失败");
      renderUpdateStatus(payload);
      const progress = payload.progress || {};
      if (!payload.inProgress) {
        stopUpdatePolling();
        settingsEl.checkUpdate.disabled = false;
        settingsEl.applyUpdate.disabled = false;
        if (progress.status === "complete" && progress.restartScheduled) {
          settingsEl.updateFeedback.textContent = "升级完成，服务正在重启，页面稍后自动刷新。";
          setTimeout(() => window.location.reload(), 5000);
        }
      }
    } catch (error) {
      settingsEl.updateStatus.className = "update-status available";
      settingsEl.updateStatus.textContent = "等待服务";
      settingsEl.updateFeedback.textContent = "服务可能正在重启：" + error.message + "。页面稍后自动刷新。";
      stopUpdatePolling();
      setTimeout(() => window.location.reload(), 5000);
    }
  }, 1000);
}

function populateSettings(payload) {
  settingsSnapshot = payload;
  const config = payload.config || {};
  const listen = config.listen || {};
  const storage = config.storage || {};
  const mgtv = config.mgtv || {};
  const vote = config.vote || {};
  const github = config.github || {};
  const feishu = config.feishu || {};
  const auth = config.operator_auth || {};

  setField("cfgActivity", vote.activity);
  setField("cfgPolicy", vote.multi_candidate_policy || "all");
  setField("cfgCandidates", candidatesText(vote.candidates));

  setField("cfgLiveUrl", mgtv.url);
  setField("cfgRoomId", mgtv.room_id);
  setField("cfgCameraId", mgtv.camera_id);
  setField("cfgHistoryApi", mgtv.history_api);
  setField("cfgFlag", mgtv.flag || "liveshow");
  setField("cfgPollSeconds", mgtv.poll_seconds);
  setField("cfgReconnectSeconds", mgtv.reconnect_seconds);
  setChecked("cfgCountInitial", mgtv.count_initial_history);
  setField("cfgDedupHot", mgtv.dedup_hot_cache_size);
  setField("cfgDedupMax", mgtv.dedup_max_records);
  setField("cfgDedupDb", mgtv.dedup_db_path);

  setChecked("cfgGithubEnabled", github.enabled);
  setField("cfgGithubOwner", github.owner);
  setField("cfgGithubRepo", github.repo);
  setField("cfgGithubBranch", github.branch || "main");
  setField("cfgGithubPath", github.path || "site/data/results.json");
  setField("cfgGithubToken", "");
  settingsEl.githubSecretState.textContent = github.token_configured ? "Token 已配置" : "Token 未配置";
  settingsEl.cfgGithubToken.placeholder = github.token_configured ? "已配置，留空保留" : "输入 Token";

  setChecked("cfgFeishuEnabled", feishu.enabled);
  setField("cfgFeishuMode", feishu.connection_mode || "websocket");
  setField("cfgFeishuAppId", feishu.app_id);
  setField("cfgFeishuSecret", "");
  setField("cfgFeishuToken", "");
  setField("cfgFeishuOpenIds", listText(feishu.allowed_open_ids));
  setField("cfgFeishuChatIds", listText(feishu.allowed_chat_ids));
  setField("cfgFeishuPublicUrl", feishu.public_results_url);
  settingsEl.feishuSecretState.textContent = [
    feishu.app_secret_configured ? "App Secret 已配置" : "App Secret 未配置",
    feishu.verification_token_configured ? "Verification Token 已配置" : "Verification Token 未配置"
  ].join(" · ");
  settingsEl.cfgFeishuSecret.placeholder = feishu.app_secret_configured ? "已配置，留空保留" : "输入 App Secret";
  settingsEl.cfgFeishuToken.placeholder = feishu.verification_token_configured ? "已配置，留空保留" : "webhook 模式填写";

  setChecked("cfgAuthEnabled", auth.enabled);
  setField("cfgNewPassword", "");
  setField("cfgSessionHours", auth.session_hours || 12);
  setChecked("cfgSecureCookie", auth.secure_cookie);
  setField("cfgMaxFailures", auth.max_failures || 5);
  setField("cfgFailureWindow", auth.failure_window_seconds || 300);
  settingsEl.authSecretState.textContent = auth.password_configured ? "运营密码已配置" : "运营密码未配置";
  settingsEl.cfgNewPassword.placeholder = auth.password_configured ? "留空保留现有密码" : "首次启用必须设置";

  setField("cfgListenHost", listen.host);
  setField("cfgListenPort", listen.port);
  setField("cfgPublicBaseUrl", listen.public_base_url);
  setField("cfgStorageDir", storage.directory);
  updateConfigStatus(payload.runtime || {});
}

function readSettingsForm() {
  return {
    listen: {
      host: settingsEl.cfgListenHost.value.trim(),
      port: Number(settingsEl.cfgListenPort.value),
      public_base_url: settingsEl.cfgPublicBaseUrl.value.trim()
    },
    storage: {
      directory: settingsEl.cfgStorageDir.value.trim()
    },
    mgtv: {
      url: settingsEl.cfgLiveUrl.value.trim(),
      room_id: settingsEl.cfgRoomId.value.trim(),
      camera_id: settingsEl.cfgCameraId.value.trim(),
      history_api: settingsEl.cfgHistoryApi.value.trim(),
      flag: settingsEl.cfgFlag.value.trim(),
      poll_seconds: Number(settingsEl.cfgPollSeconds.value),
      reconnect_seconds: Number(settingsEl.cfgReconnectSeconds.value),
      count_initial_history: settingsEl.cfgCountInitial.checked,
      dedup_hot_cache_size: Number(settingsEl.cfgDedupHot.value),
      dedup_max_records: Number(settingsEl.cfgDedupMax.value),
      dedup_db_path: settingsEl.cfgDedupDb.value.trim()
    },
    vote: {
      activity: settingsEl.cfgActivity.value.trim(),
      multi_candidate_policy: settingsEl.cfgPolicy.value,
      candidates: parseCandidates(settingsEl.cfgCandidates.value)
    },
    github: {
      enabled: settingsEl.cfgGithubEnabled.checked,
      owner: settingsEl.cfgGithubOwner.value.trim(),
      repo: settingsEl.cfgGithubRepo.value.trim(),
      branch: settingsEl.cfgGithubBranch.value.trim(),
      path: settingsEl.cfgGithubPath.value.trim(),
      token: settingsEl.cfgGithubToken.value
    },
    feishu: {
      enabled: settingsEl.cfgFeishuEnabled.checked,
      connection_mode: settingsEl.cfgFeishuMode.value,
      app_id: settingsEl.cfgFeishuAppId.value.trim(),
      app_secret: settingsEl.cfgFeishuSecret.value,
      verification_token: settingsEl.cfgFeishuToken.value,
      allowed_open_ids: parseList(settingsEl.cfgFeishuOpenIds.value),
      allowed_chat_ids: parseList(settingsEl.cfgFeishuChatIds.value),
      public_results_url: settingsEl.cfgFeishuPublicUrl.value.trim()
    },
    operator_auth: {
      enabled: settingsEl.cfgAuthEnabled.checked,
      new_password: settingsEl.cfgNewPassword.value,
      session_hours: Number(settingsEl.cfgSessionHours.value),
      secure_cookie: settingsEl.cfgSecureCookie.checked,
      max_failures: Number(settingsEl.cfgMaxFailures.value),
      failure_window_seconds: Number(settingsEl.cfgFailureWindow.value)
    }
  };
}

async function loadSettings(showFeedback = true) {
  const response = await fetch("/api/settings?t=" + Date.now(), { cache: "no-store" });
  requireLogin(response);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "配置读取失败");
  populateSettings(payload);
  if (showFeedback) {
    settingsEl.settingsFeedback.className = "panel-copy";
    settingsEl.settingsFeedback.textContent = "已读取服务器当前配置。敏感字段不会回显。";
  }
}

async function checkUpdate(offerApply = false) {
  if (settingsEl.checkUpdate.disabled && !offerApply) return;
  settingsEl.checkUpdate.disabled = true;
  settingsEl.updateStatus.className = "update-status";
  settingsEl.updateStatus.textContent = "检查中";
  settingsEl.updateFeedback.textContent = "正在读取远端 commit……";
  try {
    const response = await fetch("/api/update/status?t=" + Date.now(), { cache: "no-store" });
    requireLogin(response);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "版本检查失败");
    renderUpdateStatus(payload);
    if (payload.inProgress) startUpdatePolling();
    if (offerApply && payload.updateAvailable && payload.canApply) {
      const confirmed = window.confirm("发现新版本 " + shortCommit(payload.remoteSha) + "，是否立即升级并自动重启服务？");
      if (confirmed) await applyUpdate(false);
    }
  } catch (error) {
    renderUpdateStatus({ ok: false, error: error.message });
    addLog("版本检查失败：" + error.message);
  } finally {
    if (!updatePollTimer) settingsEl.checkUpdate.disabled = false;
  }
}

async function applyUpdate(askConfirm = true) {
  if (askConfirm && !window.confirm("升级会短暂重启服务。请确认当前没有场次正在采集，是否继续？")) return;
  settingsEl.applyUpdate.disabled = true;
  settingsEl.checkUpdate.disabled = true;
  settingsEl.updateStatus.className = "update-status available";
  settingsEl.updateStatus.textContent = "升级中";
  settingsEl.updateFeedback.textContent = "正在拉取新 commit、安装依赖并准备重启……";
  try {
    const response = await fetch("/api/update/apply", { method: "POST" });
    requireLogin(response);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "升级失败");
    renderUpdateProgress(payload.progress);
    settingsEl.updateFeedback.textContent = payload.message || "升级任务已启动。";
    addLog(settingsEl.updateFeedback.textContent);
    startUpdatePolling();
  } catch (error) {
    settingsEl.updateStatus.className = "update-status error";
    settingsEl.updateStatus.textContent = "升级失败";
    settingsEl.updateFeedback.textContent = error.message || "升级请求中断，服务可能正在重启，请稍后刷新。";
    addLog("程序升级失败：" + settingsEl.updateFeedback.textContent);
    settingsEl.checkUpdate.disabled = false;
    settingsEl.applyUpdate.disabled = false;
  } finally {
    if (!updatePollTimer) {
      settingsEl.applyUpdate.disabled = false;
      settingsEl.checkUpdate.disabled = false;
    }
  }
}

async function handleStartFeishuBindingClick() {
  const button = settingsEl.startFeishuBinding || document.getElementById("startFeishuBinding");
  settingsDebug("start feishu binding clicked");
  if (!button || button.disabled) return;
  button.disabled = true;
  settingsEl.feishuBindStatus.className = "update-status available";
  settingsEl.feishuBindStatus.textContent = "发起中";
  settingsEl.feishuBindMessage.textContent = "正在向飞书申请授权链接……";
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 25000);
  try {
    const response = await fetch("/api/feishu/binding/start", { method: "POST", signal: controller.signal });
    requireLogin(response);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "飞书绑定发起失败");
    renderFeishuBinding(payload);
    if (payload.verificationUrl) window.open(payload.verificationUrl, "_blank", "noopener");
    if (payload.status === "pending") startFeishuBindingPolling();
  } catch (error) {
    settingsEl.feishuBindStatus.className = "update-status error";
    settingsEl.feishuBindStatus.textContent = "发起失败";
    settingsEl.feishuBindMessage.textContent = error.name === "AbortError"
      ? "连接飞书授权服务超时，请检查服务器是否能访问 accounts.feishu.cn。"
      : error.message;
    button.disabled = false;
  } finally {
    clearTimeout(timeoutId);
  }
}

settingsDebug("startFeishuBinding button found", Boolean(settingsEl.startFeishuBinding || document.getElementById("startFeishuBinding")));
document.addEventListener("click", (event) => {
  const target = event.target && typeof event.target.closest === "function"
    ? event.target.closest("#startFeishuBinding")
    : (event.target && event.target.id === "startFeishuBinding" ? event.target : null);
  if (!target) return;
  event.preventDefault();
  handleStartFeishuBindingClick();
});

settingsEl.settingsToggle.addEventListener("click", async () => {
  settingsEl.settingsPanel.hidden = false;
  settingsEl.settingsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    await loadSettings();
    await loadFeishuBinding(false);
    checkUpdate(false).catch(() => {});
  } catch (error) {
    settingsEl.settingsFeedback.className = "panel-copy error";
    settingsEl.settingsFeedback.textContent = error.message;
  }
});

settingsEl.settingsClose.addEventListener("click", () => {
  settingsEl.settingsPanel.hidden = true;
  stopFeishuBindingPolling();
});

settingsEl.cfgLiveUrl.addEventListener("input", () => {
  applyMgtvUrlAutofill();
});

settingsEl.cfgLiveUrl.addEventListener("paste", () => {
  setTimeout(applyMgtvUrlAutofill, 0);
});

settingsEl.cfgFlag.addEventListener("input", () => {
  const parsed = parseMgtvLiveUrl(settingsEl.cfgLiveUrl.value, settingsEl.cfgFlag.value);
  if (parsed && (!settingsEl.cfgRoomId.value.trim() || settingsEl.cfgRoomId.value.includes("-" + parsed.cameraId))) {
    setField("cfgRoomId", parsed.roomId);
  }
});

settingsEl.settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  settingsEl.saveSettings.disabled = true;
  settingsEl.settingsFeedback.className = "panel-copy";
  settingsEl.settingsFeedback.textContent = "正在校验、保存并热应用……";
  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readSettingsForm())
    });
    requireLogin(response);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "配置保存失败");
    populateSettings(payload.settings);
    const warnings = payload.warnings || [];
    settingsEl.settingsFeedback.className = "panel-copy success";
    settingsEl.settingsFeedback.textContent = warnings.length
      ? ("配置已保存并应用。注意：" + warnings.join("；"))
      : "配置已保存并完成热重载。";
    addLog(settingsEl.settingsFeedback.textContent);
    if (payload.reauthRequired) {
      settingsEl.settingsFeedback.textContent += " 新密码已生效，即将重新登录。";
      setTimeout(() => window.location.assign("/login"), 1200);
    }
  } catch (error) {
    settingsEl.settingsFeedback.className = "panel-copy error";
    settingsEl.settingsFeedback.textContent = error.message;
    addLog("配置保存失败：" + error.message);
  } finally {
    settingsEl.saveSettings.disabled = false;
  }
});

settingsEl.restartService.addEventListener("click", async () => {
  if (!window.confirm("服务将短暂重启。请确认当前没有场次正在采集。")) return;
  settingsEl.restartService.disabled = true;
  try {
    const response = await fetch("/api/restart", { method: "POST" });
    requireLogin(response);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "服务重启失败");
    settingsEl.settingsFeedback.className = "panel-copy success";
    settingsEl.settingsFeedback.textContent = "服务正在重启，页面将在数秒后自动恢复。";
    setTimeout(() => window.location.reload(), 3500);
  } catch (error) {
    settingsEl.settingsFeedback.className = "panel-copy error";
    settingsEl.settingsFeedback.textContent = error.message;
    settingsEl.restartService.disabled = false;
  }
});

settingsEl.checkUpdate.addEventListener("click", () => {
  checkUpdate(true);
});

settingsEl.applyUpdate.addEventListener("click", () => {
  applyUpdate();
});

loadSettings(false).catch(() => {
  settingsEl.configStatus.className = "config-status";
  settingsEl.configStatus.textContent = "配置读取失败";
});
loadFeishuBinding(false).catch(() => {});
