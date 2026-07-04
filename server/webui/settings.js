const settingsEl = Object.fromEntries([
  "settingsToggle", "settingsPanel", "settingsClose", "settingsForm", "configStatus", "settingsFeedback", "saveSettings", "restartService",
  "cfgActivity", "cfgPolicy", "cfgCandidates",
  "cfgLiveUrl", "cfgRoomId", "cfgCameraId", "cfgHistoryApi", "cfgFlag", "cfgPollSeconds",
  "cfgReconnectSeconds", "cfgCountInitial", "cfgDedupHot", "cfgDedupMax", "cfgDedupDb",
  "cfgGithubEnabled", "cfgGithubOwner", "cfgGithubRepo", "cfgGithubBranch", "cfgGithubPath",
  "cfgGithubToken", "githubSecretState",
  "cfgFeishuEnabled", "cfgFeishuMode", "cfgFeishuAppId", "cfgFeishuSecret", "cfgFeishuToken",
  "cfgFeishuOpenIds", "cfgFeishuChatIds", "cfgFeishuPublicUrl", "feishuSecretState",
  "cfgAuthEnabled", "cfgNewPassword", "cfgSessionHours", "cfgSecureCookie", "cfgMaxFailures",
  "cfgFailureWindow", "authSecretState",
  "cfgListenHost", "cfgListenPort", "cfgPublicBaseUrl", "cfgStorageDir"
].map((id) => [id, document.getElementById(id)]));

let settingsSnapshot = null;

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

function updateConfigStatus(runtime) {
  const fields = (runtime && runtime.restartFields) || [];
  settingsEl.configStatus.className = "config-status " + (fields.length ? "restart" : "ready");
  settingsEl.configStatus.textContent = fields.length ? ("需重启 · " + fields.join("、")) : "热重载已就绪";
  settingsEl.restartService.hidden = !fields.length;
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

settingsEl.settingsToggle.addEventListener("click", async () => {
  settingsEl.settingsPanel.hidden = false;
  settingsEl.settingsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    await loadSettings();
  } catch (error) {
    settingsEl.settingsFeedback.className = "panel-copy error";
    settingsEl.settingsFeedback.textContent = error.message;
  }
});

settingsEl.settingsClose.addEventListener("click", () => {
  settingsEl.settingsPanel.hidden = true;
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

loadSettings(false).catch(() => {
  settingsEl.configStatus.className = "config-status";
  settingsEl.configStatus.textContent = "配置读取失败";
});
