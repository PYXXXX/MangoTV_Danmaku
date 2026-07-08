"""Validation, redaction, and persistence for operator-managed settings."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from server.operator_auth import hash_password, new_session_secret
except ModuleNotFoundError:
    from operator_auth import hash_password, new_session_secret


PLACEHOLDERS = {
    "",
    "xxx",
    "cli_xxx",
    "github_pat_xxx",
    "你的应用密钥",
}


class SettingsValidationError(ValueError):
    pass


@dataclass
class SettingsUpdate:
    config: dict[str, Any]
    restart_fields: list[str]
    warnings: list[str]
    reauth_required: bool = False


def has_real_value(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and text not in PLACEHOLDERS and "your-" not in text)


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "是"}


def as_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise SettingsValidationError(f"{label} 必须是整数") from exc
    if not minimum <= result <= maximum:
        raise SettingsValidationError(f"{label} 必须在 {minimum} 到 {maximum} 之间")
    return result


def as_float(value: Any, label: str, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SettingsValidationError(f"{label} 必须是数字") from exc
    if not minimum <= result <= maximum:
        raise SettingsValidationError(f"{label} 必须在 {minimum} 到 {maximum} 之间")
    return result


def as_url(value: Any, label: str, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if not text and not required:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SettingsValidationError(f"{label} 必须是有效的 HTTP/HTTPS URL")
    return text


def as_id_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = re.split(r"[,，\s]+", str(value or ""))
    return list(dict.fromkeys(item for item in items if item))


def as_candidates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SettingsValidationError("候选人必须是列表")
    result: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_aliases: dict[str, str] = {}
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise SettingsValidationError(f"第 {index} 位候选人格式无效")
        name = str(item.get("name") or "").strip()
        aliases = as_id_list(item.get("aliases") or [])
        if not name:
            raise SettingsValidationError(f"第 {index} 位候选人缺少正式姓名")
        if name.casefold() in seen_names:
            raise SettingsValidationError(f"候选人“{name}”重复")
        seen_names.add(name.casefold())
        if name not in aliases:
            aliases.insert(0, name)
        for alias in aliases:
            key = alias.casefold()
            owner = seen_aliases.get(key)
            if owner and owner != name:
                raise SettingsValidationError(f"别名“{alias}”同时属于 {owner} 和 {name}")
            seen_aliases[key] = name
        candidate = {"name": name, "aliases": aliases}
        candidate_id = str(item.get("id") or "").strip()
        if candidate_id:
            candidate["id"] = candidate_id
        result.append(candidate)
    if not result:
        raise SettingsValidationError("至少需要一位候选人")
    return result


def _safe_relative_path(value: Any, label: str) -> str:
    text = str(value or "").strip().lstrip("/")
    path = Path(text)
    if not text or ".." in path.parts:
        raise SettingsValidationError(f"{label} 必须是仓库内的安全相对路径")
    return text


def _merge_secret(target: dict[str, Any], source: dict[str, Any], key: str) -> None:
    supplied = str(source.get(key) or "").strip()
    if supplied:
        target[key] = supplied


def build_settings_update(
    current: dict[str, Any],
    payload: dict[str, Any],
    *,
    active_round: bool,
) -> SettingsUpdate:
    if not isinstance(payload, dict):
        raise SettingsValidationError("配置请求必须是 JSON 对象")
    updated = copy.deepcopy(current)
    warnings: list[str] = []
    reauth_required = False

    if "listen" in payload:
        source = payload.get("listen")
        if not isinstance(source, dict):
            raise SettingsValidationError("listen 配置格式无效")
        target = dict(updated.get("listen") or {})
        host = str(source.get("host") or "").strip()
        if not host:
            raise SettingsValidationError("监听地址不能为空")
        target.update({
            "host": host,
            "port": as_int(source.get("port"), "监听端口", 1, 65535),
            "public_base_url": as_url(source.get("public_base_url"), "外部访问地址", required=False),
        })
        updated["listen"] = target

    if "storage" in payload:
        source = payload.get("storage")
        if not isinstance(source, dict):
            raise SettingsValidationError("storage 配置格式无效")
        directory = str(source.get("directory") or "").strip()
        if not directory:
            raise SettingsValidationError("数据目录不能为空")
        updated["storage"] = {"directory": directory}

    if "mgtv" in payload:
        source = payload.get("mgtv")
        if not isinstance(source, dict):
            raise SettingsValidationError("mgtv 配置格式无效")
        target = dict(updated.get("mgtv") or {})
        target.update({
            "url": as_url(source.get("url"), "直播 URL"),
            "history_api": as_url(source.get("history_api"), "弹幕历史接口"),
            "flag": str(source.get("flag") or "liveshow").strip(),
            "room_id": str(source.get("room_id") or "").strip(),
            "camera_id": str(source.get("camera_id") or "").strip(),
            "poll_seconds": as_float(source.get("poll_seconds"), "轮询间隔", 0.25, 60),
            "reconnect_seconds": as_float(source.get("reconnect_seconds"), "重连间隔", 1, 300),
            "count_initial_history": as_bool(source.get("count_initial_history")),
            "dedup_hot_cache_size": as_int(source.get("dedup_hot_cache_size"), "内存去重缓存", 1_000, 10_000_000),
            "dedup_max_records": as_int(source.get("dedup_max_records"), "去重记录上限", 10_000, 1_000_000_000),
            "dedup_db_path": str(source.get("dedup_db_path") or "server/data/fingerprints.sqlite3").strip(),
        })
        if not target["flag"]:
            raise SettingsValidationError("room_id 前缀不能为空")
        updated["mgtv"] = target

    if "recording" in payload:
        source = payload.get("recording")
        if not isinstance(source, dict):
            raise SettingsValidationError("recording 配置格式无效")
        target = dict(updated.get("recording") or {})
        target.update({
            "enabled": as_bool(source.get("enabled")),
            "preferred_quality": str(source.get("preferred_quality") or "auto").strip() or "auto",
            "ffmpeg_path": str(source.get("ffmpeg_path") or "").strip(),
            "directory": str(source.get("directory") or "").strip(),
            "auto_split_enabled": as_bool(source.get("auto_split_enabled", target.get("auto_split_enabled", True))),
            "auto_split_seconds": as_int(source.get("auto_split_seconds", target.get("auto_split_seconds", 3600)), "自动切片间隔", 300, 12 * 3600),
        })
        supplied_stream_url = str(source.get("stream_url") or "").strip()
        if supplied_stream_url:
            target["stream_url"] = as_url(supplied_stream_url, "录屏直播流 URL", required=False)
        if target["enabled"] and not target.get("stream_url"):
            warnings.append("已启用录屏但未配置直播流 URL；开始场次时会尝试自动检测播放源")
        updated["recording"] = target

    if "monitor" in payload:
        source = payload.get("monitor")
        if not isinstance(source, dict):
            raise SettingsValidationError("monitor 配置格式无效")
        current_monitor = updated.get("monitor") or {}
        current_vote = updated.get("vote") or {}
        current_mgtv = updated.get("mgtv") or {}
        enabled = as_bool(source.get("enabled"))
        activity = str(source.get("activity") or current_monitor.get("activity") or current_vote.get("activity") or "").strip()
        url = str(source.get("url") or current_monitor.get("url") or current_mgtv.get("url") or "").strip()
        target = dict(current_monitor)
        target.update({
            "enabled": enabled,
            "activity": activity,
            "url": as_url(url, "活动链接", required=False),
            "auto_detect_source": as_bool(source.get("auto_detect_source", target.get("auto_detect_source", True))),
            "auto_record_video": as_bool(source.get("auto_record_video", target.get("auto_record_video", False))),
            "auto_record_danmaku": as_bool(source.get("auto_record_danmaku", target.get("auto_record_danmaku", True))),
            "feishu_notify": as_bool(source.get("feishu_notify", target.get("feishu_notify", True))),
            "poll_seconds": as_int(source.get("poll_seconds", target.get("poll_seconds", 45)), "活动监控间隔", 10, 3600),
            "round_name": str(source.get("round_name") or target.get("round_name") or "").strip(),
        })
        if enabled:
            if not target["activity"]:
                raise SettingsValidationError("启用活动监控前必须填写活动名称")
            if not target["url"]:
                raise SettingsValidationError("启用活动监控前必须填写活动链接")
            if not target["auto_record_video"] and not target["auto_record_danmaku"]:
                warnings.append("活动监控已启用，但未选择自动录制视频或弹幕；系统只会检测直播源并更新状态")
        updated["monitor"] = target

    if "mgtv_auth" in payload:
        source = payload.get("mgtv_auth")
        if not isinstance(source, dict):
            raise SettingsValidationError("mgtv_auth 配置格式无效")
        target = dict(updated.get("mgtv_auth") or {})
        target.update({
            "enabled": as_bool(source.get("enabled", True)),
        })
        updated["mgtv_auth"] = target

    if "vote" in payload:
        source = payload.get("vote")
        if not isinstance(source, dict):
            raise SettingsValidationError("vote 配置格式无效")
        activity = str(source.get("activity") or "").strip()
        policy = str(source.get("multi_candidate_policy") or "").strip()
        if not activity:
            raise SettingsValidationError("默认活动名称不能为空")
        if policy not in {"all", "review"}:
            raise SettingsValidationError("多人弹幕策略只能是 all 或 review")
        updated["vote"] = {
            "activity": activity,
            "multi_candidate_policy": policy,
            "candidates": as_candidates(source.get("candidates")),
        }

    if "github" in payload:
        source = payload.get("github")
        if not isinstance(source, dict):
            raise SettingsValidationError("github 配置格式无效")
        target = dict(updated.get("github") or {})
        target.update({
            "enabled": as_bool(source.get("enabled")),
            "owner": str(source.get("owner") or "").strip(),
            "repo": str(source.get("repo") or "").strip(),
            "branch": str(source.get("branch") or "main").strip(),
            "path": _safe_relative_path(source.get("path") or "site/data/results.json", "GitHub 结果路径"),
        })
        _merge_secret(target, source, "token")
        if target["enabled"]:
            missing = [key for key in ("owner", "repo", "branch", "path") if not target.get(key)]
            if missing or not has_real_value(target.get("token")):
                raise SettingsValidationError("启用 GitHub 发布前必须填写仓库、分支、路径和有效 Token")
        updated["github"] = target

    if "feishu" in payload:
        source = payload.get("feishu")
        if not isinstance(source, dict):
            raise SettingsValidationError("feishu 配置格式无效")
        target = dict(updated.get("feishu") or {})
        mode = str(source.get("connection_mode") or "websocket").strip()
        if mode not in {"websocket", "webhook"}:
            raise SettingsValidationError("飞书连接模式只能是 websocket 或 webhook")
        target.update({
            "enabled": as_bool(source.get("enabled")),
            "connection_mode": mode,
            "app_id": str(source.get("app_id") or "").strip(),
            "allowed_open_ids": as_id_list(source.get("allowed_open_ids")),
            "allowed_chat_ids": as_id_list(source.get("allowed_chat_ids")),
            "public_results_url": as_url(source.get("public_results_url"), "公开结果页 URL", required=False),
        })
        _merge_secret(target, source, "app_secret")
        _merge_secret(target, source, "verification_token")
        if target["enabled"]:
            if not has_real_value(target.get("app_id")) or not has_real_value(target.get("app_secret")):
                raise SettingsValidationError("启用飞书前必须填写有效 App ID 和 App Secret")
            if mode == "webhook" and not has_real_value(target.get("verification_token")):
                raise SettingsValidationError("飞书 HTTP 回调模式必须填写 Verification Token")
            if not target["allowed_open_ids"] and not target["allowed_chat_ids"]:
                raise SettingsValidationError("启用飞书前必须填写至少一个 allowed_open_ids 或 allowed_chat_ids；可先在飞书发送“我的ID”获取")
            elif "*" in target["allowed_open_ids"] or "*" in target["allowed_chat_ids"]:
                warnings.append("飞书白名单包含 *，正式节目应改为真实 open_id/chat_id")
        updated["feishu"] = target

    if "operator_auth" in payload:
        source = payload.get("operator_auth")
        if not isinstance(source, dict):
            raise SettingsValidationError("operator_auth 配置格式无效")
        target = dict(updated.get("operator_auth") or {})
        target.update({
            "enabled": as_bool(source.get("enabled")),
            "session_hours": as_int(source.get("session_hours"), "会话时长", 1, 168),
            "secure_cookie": as_bool(source.get("secure_cookie")),
            "max_failures": as_int(source.get("max_failures"), "失败次数上限", 3, 20),
            "failure_window_seconds": as_int(source.get("failure_window_seconds"), "限速窗口", 60, 3600),
        })
        new_password = str(source.get("new_password") or "")
        if new_password:
            if len(new_password) < 10:
                raise SettingsValidationError("新运营密码至少需要 10 个字符")
            target["password_hash"] = hash_password(new_password)
            target["session_secret"] = new_session_secret()
            reauth_required = True
        if target["enabled"] and (
            not has_real_value(target.get("password_hash"))
            or not has_real_value(target.get("session_secret"))
        ):
            raise SettingsValidationError("首次启用运营密码时必须设置新密码")
        updated["operator_auth"] = target

    restart_paths = [
        ("listen.host", ("listen", "host")),
        ("listen.port", ("listen", "port")),
        ("storage.directory", ("storage", "directory")),
    ]
    restart_fields = [
        label
        for label, (group, key) in restart_paths
        if (current.get(group) or {}).get(key) != (updated.get(group) or {}).get(key)
    ]
    if restart_fields:
        warnings.append("以下配置已保存，需重启服务生效：" + "、".join(restart_fields))

    if active_round:
        old_vote = current.get("vote") or {}
        new_vote = updated.get("vote") or {}
        old_mgtv = current.get("mgtv") or {}
        new_mgtv = updated.get("mgtv") or {}
        if old_vote != new_vote:
            warnings.append("候选人、活动和多人策略只对下一场生效；当前场次保持启动时口径")
        source_keys = {"url", "room_id", "camera_id", "flag", "count_initial_history"}
        if any(old_mgtv.get(key) != new_mgtv.get(key) for key in source_keys):
            warnings.append("直播源和首批历史策略只对下一场生效；当前采集连接不切换")
        if (current.get("recording") or {}) != (updated.get("recording") or {}):
            warnings.append("录屏配置只对下一场生效；当前录制进程不切换")

    return SettingsUpdate(updated, restart_fields, warnings, reauth_required)


def public_settings(config: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(config)
    github = dict(result.get("github") or {})
    github["token"] = ""
    github["token_configured"] = has_real_value((config.get("github") or {}).get("token"))
    result["github"] = github

    feishu = dict(result.get("feishu") or {})
    feishu["app_secret"] = ""
    feishu["verification_token"] = ""
    original_feishu = config.get("feishu") or {}
    feishu["app_secret_configured"] = has_real_value(original_feishu.get("app_secret"))
    feishu["verification_token_configured"] = has_real_value(original_feishu.get("verification_token"))
    result["feishu"] = feishu

    recording = dict(result.get("recording") or {})
    original_recording = config.get("recording") or {}
    recording["stream_url"] = ""
    recording["stream_url_configured"] = has_real_value(original_recording.get("stream_url"))
    result["recording"] = recording

    mgtv_auth = dict(result.get("mgtv_auth") or {})
    original_mgtv_auth = config.get("mgtv_auth") or {}
    mgtv_auth["cookies"] = []
    mgtv_auth["cookie_header"] = ""
    mgtv_auth["user_info"] = {}
    mgtv_auth["cookie_configured"] = has_real_value(original_mgtv_auth.get("cookie_header")) or bool(original_mgtv_auth.get("cookies"))
    result["mgtv_auth"] = mgtv_auth

    auth = dict(result.get("operator_auth") or {})
    auth.pop("password_hash", None)
    auth.pop("session_secret", None)
    auth["new_password"] = ""
    original_auth = config.get("operator_auth") or {}
    auth["password_configured"] = (
        has_real_value(original_auth.get("password_hash"))
        and has_real_value(original_auth.get("session_secret"))
    )
    result["operator_auth"] = auth
    return {"config": result, "runtime": runtime}


def save_config_atomic(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    backup_path = path.with_name(path.name + ".bak")
    if path.exists():
        shutil.copy2(path, backup_path)
        os.chmod(backup_path, stat.S_IRUSR | stat.S_IWUSR)
    payload = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
    temp_path.replace(path)
