#!/usr/bin/env python3
"""Configure password protection for the local operator Web UI."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.operator_auth import hash_password, new_session_secret
from tools.setup_feishu_bot import load_config, save_config


DEFAULT_CONFIG = PROJECT_ROOT / "server" / "config.json"
DEFAULT_EXAMPLE = PROJECT_ROOT / "server" / "config.example.json"


def configure_auth(
    config: dict[str, Any],
    password: str,
    *,
    session_hours: int = 12,
    secure_cookie: bool = False,
) -> dict[str, Any]:
    if len(password) < 10:
        raise ValueError("运营密码至少需要 10 个字符")
    current = dict(config.get("operator_auth") or {})
    current.update({
        "enabled": True,
        "password_hash": hash_password(password),
        "session_secret": new_session_secret(),
        "session_hours": max(1, min(int(session_hours), 168)),
        "secure_cookie": bool(secure_cookie),
        "max_failures": int(current.get("max_failures") or 5),
        "failure_window_seconds": int(current.get("failure_window_seconds") or 300),
    })
    config["operator_auth"] = current
    return config


def prompt_password() -> str:
    while True:
        password = getpass.getpass("请输入新的运营密码（至少 10 个字符）: ")
        if len(password) < 10:
            print("密码太短，请至少输入 10 个字符。")
            continue
        confirmation = getpass.getpass("请再次输入密码: ")
        if password != confirmation:
            print("两次输入不一致，请重试。")
            continue
        return password


def prompt_bool(label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes", "是", "true", "1"}:
            return True
        if raw in {"n", "no", "否", "false", "0"}:
            return False
        print("请输入 y 或 n。")


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description="设置运营端登录密码")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="本地配置文件，默认 server/config.json")
    parser.add_argument("--example", default=str(DEFAULT_EXAMPLE), help="配置不存在时使用的示例文件")
    parser.add_argument("--disable", action="store_true", help="关闭运营端密码保护")
    parser.add_argument("--session-hours", type=int, help="登录会话有效小时数，范围 1-168，默认 12")
    cookie_group = parser.add_mutually_exclusive_group()
    cookie_group.add_argument("--secure-cookie", action="store_true", help="仅通过 HTTPS 发送登录 Cookie")
    cookie_group.add_argument("--insecure-cookie", action="store_true", help="允许本地 HTTP 发送登录 Cookie")
    args = parser.parse_args()

    config_path = resolve_path(args.config)
    example_path = resolve_path(args.example)
    if config_path.resolve() == example_path.resolve():
        raise SystemExit("请勿把真实认证配置写入 server/config.example.json；请使用默认的 server/config.json。")
    config, created = load_config(config_path, example_path)
    current = dict(config.get("operator_auth") or {})

    if args.disable:
        current["enabled"] = False
        config["operator_auth"] = current
        action = "已关闭运营端密码保护"
    else:
        base_url = str((config.get("listen") or {}).get("public_base_url") or "")
        if args.secure_cookie:
            secure_cookie = True
        elif args.insecure_cookie:
            secure_cookie = False
        else:
            configured = bool(current.get("enabled") and "secure_cookie" in current)
            default_secure = bool(current.get("secure_cookie")) if configured else (
                base_url.startswith("https://") and "your-" not in base_url
            )
            secure_cookie = prompt_bool("运营端是否只通过 HTTPS 提交登录 Cookie", default_secure)
        session_hours = args.session_hours or int(current.get("session_hours") or 12)
        password = prompt_password()
        configure_auth(
            config,
            password,
            session_hours=session_hours,
            secure_cookie=secure_cookie,
        )
        action = "已启用运营端密码保护"

    backup = save_config(config_path, config, make_backup=not created)
    print(f"{action}：{config_path}")
    if backup:
        print(f"旧配置备份：{backup}")
    if not args.disable:
        cookie_mode = "仅 HTTPS" if config["operator_auth"]["secure_cookie"] else "允许本地 HTTP"
        print(f"会话有效期：{config['operator_auth']['session_hours']} 小时；Cookie：{cookie_mode}")
        print("重启服务后生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
