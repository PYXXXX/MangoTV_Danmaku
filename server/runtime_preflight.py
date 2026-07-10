"""Runtime config migration, writability preflight, and log redaction helpers."""

from __future__ import annotations

import copy
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


LEGACY_RUNTIME_ROOT = Path("/var/lib/mgtv-danmaku")
DEFAULT_DEDUP_PATH = "server/data/fingerprints.sqlite3"
SENSITIVE_KEYS = {
    "access_key",
    "access_token",
    "app_secret",
    "authorization",
    "cookie",
    "device_code",
    "password",
    "refresh_token",
    "session",
    "session_key",
    "ticket",
    "token",
    "user_code",
}


@dataclass
class RuntimeMigrationResult:
    config: dict[str, Any]
    changed: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class RuntimePreflightResult:
    ok: bool
    config: dict[str, Any]
    changed: bool = False
    checks: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class RuntimePreflightError(RuntimeError):
    pass


def repo_root_default() -> Path:
    return Path(__file__).resolve().parents[1]


def redact_sensitive_text(value: str) -> str:
    """Redact common secret query params and key-value fragments before logging."""
    text = str(value or "")

    def redact_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return raw
        netloc = parsed.netloc
        changed = False
        if parsed.username is not None or parsed.password is not None:
            host = parsed.hostname or ""
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            netloc = f"***@{host}"
            try:
                port = parsed.port
            except ValueError:
                port = None
            if port is not None:
                netloc += f":{port}"
            changed = True
        pairs = []
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() in SENSITIVE_KEYS:
                pairs.append((key, "***"))
                changed = True
            else:
                pairs.append((key, item))
        if not changed:
            return raw
        return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(pairs), parsed.fragment))

    text = re.sub(r"(?:https?|wss?)://[^\s\"'<>]+", redact_url, text)
    key_pattern = "|".join(sorted(re.escape(key) for key in SENSITIVE_KEYS))
    text = re.sub(
        rf"(?i)\b({key_pattern})(['\"\s:=]+)([^,\s\"'&]+)",
        lambda match: f"{match.group(1)}{match.group(2)}***",
        text,
    )
    text = re.sub(r"(?i)(Authorization:\s*Bearer\s+)[^\s]+", r"\1***", text)
    text = re.sub(r"\bgithub_pat_[A-Za-z0-9_]{12,}\b", "github_pat_***", text)
    text = re.sub(r"\bgh[pousr]_[A-Za-z0-9]{12,}\b", "gh*_***", text)
    return text


def resolve_runtime_path(value: Any, *, config_path: Path | None = None, repo_root: Path | None = None) -> Path:
    path = Path(str(value or "").strip())
    if path.is_absolute():
        return path
    root = Path(repo_root or repo_root_default())
    if path.parts and path.parts[0] == "server":
        return (root / path).resolve()
    if config_path is not None:
        return (Path(config_path).parent / path).resolve()
    return (root / path).resolve()


def derive_runtime_data_dir(config: dict[str, Any], *, config_path: Path | None = None, repo_root: Path | None = None) -> Path:
    storage = config.get("storage") if isinstance(config.get("storage"), dict) else {}
    directory = str(storage.get("directory") or "").strip()
    if directory:
        return resolve_runtime_path(directory, config_path=config_path, repo_root=repo_root)
    if config_path is not None:
        return (Path(config_path).parent / "data").resolve()
    return (Path(repo_root or repo_root_default()) / "server" / "data").resolve()


def preferred_dedup_db_path(config: dict[str, Any], *, config_path: Path | None = None, repo_root: Path | None = None) -> Path:
    data_dir = derive_runtime_data_dir(config, config_path=config_path, repo_root=repo_root)
    return data_dir / "fingerprints.sqlite3"


def _is_legacy_dedup_path(value: Any, *, config_path: Path | None = None, repo_root: Path | None = None) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    normalized = text.replace("\\", "/").lstrip("./")
    if normalized == DEFAULT_DEDUP_PATH:
        return True
    try:
        resolved = resolve_runtime_path(text, config_path=config_path, repo_root=repo_root)
    except OSError:
        return False
    try:
        if resolved == LEGACY_RUNTIME_ROOT or LEGACY_RUNTIME_ROOT in resolved.parents:
            return True
    except RuntimeError:
        return False
    return False


def _is_legacy_runtime_root_path(value: Any, *, config_path: Path | None = None, repo_root: Path | None = None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        resolved = resolve_runtime_path(text, config_path=config_path, repo_root=repo_root)
    except OSError:
        return False
    return resolved == LEGACY_RUNTIME_ROOT or LEGACY_RUNTIME_ROOT in resolved.parents


def _can_prepare_parent(path: Path) -> tuple[bool, str]:
    parent = Path(path).parent
    probe = parent / f".mgtv-write-test-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        parent.mkdir(parents=True, exist_ok=True)
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("ok")
            handle.flush()
            os.fsync(handle.fileno())
        probe.unlink(missing_ok=True)
        return True, ""
    except OSError as exc:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return False, str(exc)


def migrate_runtime_config(
    config: dict[str, Any],
    *,
    config_path: Path | None = None,
    repo_root: Path | None = None,
) -> RuntimeMigrationResult:
    """Migrate known legacy runtime paths while preserving valid custom paths."""
    updated = copy.deepcopy(config)
    mgtv = dict(updated.get("mgtv") or {})
    current_text = str(mgtv.get("dedup_db_path") or "").strip()
    current_path = resolve_runtime_path(current_text or DEFAULT_DEDUP_PATH, config_path=config_path, repo_root=repo_root)
    legacy = _is_legacy_dedup_path(current_text, config_path=config_path, repo_root=repo_root)
    legacy_runtime_root = _is_legacy_runtime_root_path(current_text, config_path=config_path, repo_root=repo_root)
    current_ok = False if legacy_runtime_root else _can_prepare_parent(current_path)[0]

    if legacy and not current_ok:
        target = preferred_dedup_db_path(updated, config_path=config_path, repo_root=repo_root)
        if str(target) != current_text:
            mgtv["dedup_db_path"] = str(target)
            updated["mgtv"] = mgtv
            return RuntimeMigrationResult(
                updated,
                changed=True,
                warnings=[f"已将旧去重库路径迁移到可写数据目录：{target}"],
            )
    return RuntimeMigrationResult(updated)


def _check_writable(path: Path, label: str) -> dict[str, str]:
    ok, error = _can_prepare_parent(path)
    if not ok:
        raise RuntimePreflightError(f"{label} 不可写或无法创建：{path.parent}（{error}）")
    return {"label": label, "path": str(path.parent), "status": "ok"}


def run_runtime_preflight(
    config: dict[str, Any],
    *,
    config_path: Path | None = None,
    repo_root: Path | None = None,
    migrate: bool = True,
) -> RuntimePreflightResult:
    migration = migrate_runtime_config(config, config_path=config_path, repo_root=repo_root) if migrate else RuntimeMigrationResult(copy.deepcopy(config))
    updated = migration.config
    data_dir = derive_runtime_data_dir(updated, config_path=config_path, repo_root=repo_root)
    mgtv = updated.get("mgtv") if isinstance(updated.get("mgtv"), dict) else {}
    recording = updated.get("recording") if isinstance(updated.get("recording"), dict) else {}
    dedup_path = resolve_runtime_path(mgtv.get("dedup_db_path") or DEFAULT_DEDUP_PATH, config_path=config_path, repo_root=repo_root)
    recording_dir = resolve_runtime_path(recording.get("directory") or str(data_dir / "recordings"), config_path=config_path, repo_root=repo_root)
    checks = [
        _check_writable(data_dir / ".preflight", "主数据目录"),
        _check_writable(dedup_path, "弹幕去重 SQLite 目录"),
        _check_writable(recording_dir / ".preflight", "录制目录"),
    ]
    if config_path is not None:
        _check_writable(Path(config_path), "配置文件目录")
    return RuntimePreflightResult(
        ok=True,
        config=updated,
        changed=migration.changed,
        checks=checks,
        warnings=migration.warnings,
    )
