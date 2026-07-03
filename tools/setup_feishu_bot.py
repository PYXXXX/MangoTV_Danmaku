#!/usr/bin/env python3
"""Interactive Feishu bot configuration wizard.

The wizard edits the local server/config.json file only. Real app secrets and
operator IDs should never be copied into server/config.example.json.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "server" / "config.json"
DEFAULT_EXAMPLE = PROJECT_ROOT / "server" / "config.example.json"

PLACEHOLDER_VALUES = {
    "",
    "xxx",
    "cli_xxx",
    "ou_xxx",
    "oc_xxx",
    "你的应用密钥",
    "your-domain.example.com",
    "https://your-name.github.io/MangoTV_Danmaku/",
}


def is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return text in PLACEHOLDER_VALUES or text.startswith("your-") or text.startswith("https://your-")


def existing_text(value: Any) -> str:
    return "" if is_placeholder(value) else str(value).strip()


def parse_id_list(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    if text == "*":
        return ["*"]
    return [item for item in re.split(r"[,，\s]+", text) if item]


def format_id_list(value: Any) -> str:
    if isinstance(value, str):
        items = parse_id_list(value)
    elif isinstance(value, Iterable):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        return ""
    return ", ".join(item for item in items if not is_placeholder(item))


class Wizard:
    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        secret_fn: Callable[[str], str] = getpass.getpass,
        output_fn: Callable[[str], None] = print,
    ):
        self.input_fn = input_fn
        self.secret_fn = secret_fn
        self.output_fn = output_fn

    def say(self, message: str = "") -> None:
        self.output_fn(message)

    def section(self, title: str) -> None:
        self.say()
        self.say(f"== {title} ==")

    def ask_text(
        self,
        label: str,
        *,
        default: str = "",
        required: bool = False,
        secret: bool = False,
        help_text: str = "",
    ) -> str:
        default = default.strip()
        if help_text:
            self.say(help_text)
        while True:
            if secret and default:
                prompt = f"{label} [已配置，回车保留]: "
            elif default:
                prompt = f"{label} [{default}]: "
            else:
                prompt = f"{label}: "
            raw = self.secret_fn(prompt) if secret else self.input_fn(prompt)
            value = raw.strip() or default
            if value or not required:
                return value
            self.say("此项不能为空。")

    def ask_bool(self, label: str, *, default: bool = True, help_text: str = "") -> bool:
        if help_text:
            self.say(help_text)
        suffix = "Y/n" if default else "y/N"
        while True:
            raw = self.input_fn(f"{label} [{suffix}]: ").strip().lower()
            if not raw:
                return default
            if raw in {"y", "yes", "是", "启用", "true", "1"}:
                return True
            if raw in {"n", "no", "否", "禁用", "false", "0"}:
                return False
            self.say("请输入 y 或 n。")

    def ask_choice(
        self,
        title: str,
        choices: list[tuple[str, str]],
        *,
        default: str,
        help_text: str = "",
    ) -> str:
        if help_text:
            self.say(help_text)
        self.say(title)
        for index, (key, description) in enumerate(choices, 1):
            marker = "（默认）" if key == default else ""
            self.say(f"  {index}. {description} [{key}]{marker}")
        keys = {key for key, _ in choices}
        while True:
            raw = self.input_fn(f"请选择 [{default}]: ").strip()
            if not raw:
                return default
            if raw in keys:
                return raw
            if raw.isdigit():
                index = int(raw)
                if 1 <= index <= len(choices):
                    return choices[index - 1][0]
            self.say("请输入编号或方括号里的选项值。")


def load_config(config_path: Path, example_path: Path) -> tuple[dict[str, Any], bool]:
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8")), False
    if not example_path.exists():
        raise FileNotFoundError(f"找不到示例配置：{example_path}")
    return json.loads(example_path.read_text(encoding="utf-8")), True


def save_config(config_path: Path, config: dict[str, Any], *, make_backup: bool) -> Path | None:
    backup_path: Path | None = None
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if make_backup and config_path.exists():
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = config_path.with_name(f"{config_path.name}.bak-{suffix}")
        backup_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            os.chmod(backup_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return backup_path


def configure_feishu(config: dict[str, Any], wizard: Wizard) -> tuple[dict[str, Any], str]:
    feishu = dict(config.get("feishu") or {})
    listen = config.get("listen") if isinstance(config.get("listen"), dict) else {}

    wizard.section("飞书 Bot")
    wizard.say("这个向导只写入本机 server/config.json，不会修改示例配置，也不会把真实密钥提交到仓库。")
    enabled = wizard.ask_bool("是否启用飞书 Bot", default=True)
    feishu["enabled"] = enabled
    if not enabled:
        config["feishu"] = feishu
        return config, "disabled"

    mode = str(feishu.get("connection_mode") or "websocket")
    if mode not in {"websocket", "webhook"}:
        mode = "websocket"
    mode = wizard.ask_choice(
        "选择接入方式：",
        [
            ("websocket", "推荐：WebSocket 长连接；不需要公网回调地址"),
            ("webhook", "兼容：HTTP 回调；需要公网 HTTPS 与 verification_token"),
        ],
        default=mode,
    )
    feishu["connection_mode"] = mode

    feishu["app_id"] = wizard.ask_text(
        "App ID",
        default=existing_text(feishu.get("app_id")),
        required=True,
        help_text="飞书开放平台 → 你的企业自建应用 → 凭证与基础信息 → App ID，通常以 cli_ 开头。",
    )
    feishu["app_secret"] = wizard.ask_text(
        "App Secret",
        default=existing_text(feishu.get("app_secret")),
        required=True,
        secret=True,
        help_text="同一页面复制 App Secret；输入时不会回显。",
    )

    if mode == "webhook":
        feishu["verification_token"] = wizard.ask_text(
            "Verification Token",
            default=existing_text(feishu.get("verification_token")),
            required=True,
            help_text="HTTP 回调模式需要。飞书开放平台 → 事件与回调 → Verification Token。",
        )

    public_default = existing_text(feishu.get("public_results_url"))
    if not public_default:
        public_default = existing_text(listen.get("public_base_url") if isinstance(listen, dict) else "")
    feishu["public_results_url"] = wizard.ask_text(
        "公开结果页 URL",
        default=public_default,
        required=False,
        help_text="飞书卡片里的“打开公开结果页”按钮会使用这个地址；没有线上页可暂时留空。",
    )

    existing_users = format_id_list(feishu.get("allowed_open_ids"))
    existing_chats = format_id_list(feishu.get("allowed_chat_ids"))
    has_exact_ids = bool(existing_users and existing_users != "*" or existing_chats and existing_chats != "*")
    default_strategy = "exact" if has_exact_ids else "temporary"
    strategy = wizard.ask_choice(
        "配置运营白名单：",
        [
            ("temporary", "首次联调：临时写入 *，连通后向 Bot 发送“我的ID”获取真实 ID"),
            ("exact", "正式使用：现在填写运营人员 open_id 和运营群 chat_id"),
            ("open", "留空兼容：允许所有能触达 Bot 的用户操作（不建议正式节目使用）"),
        ],
        default=default_strategy,
    )
    if strategy == "temporary":
        feishu["allowed_open_ids"] = ["*"]
        feishu["allowed_chat_ids"] = ["*"]
    elif strategy == "open":
        feishu["allowed_open_ids"] = []
        feishu["allowed_chat_ids"] = []
    else:
        user_ids = wizard.ask_text(
            "allowed_open_ids（多个用逗号分隔）",
            default="" if existing_users == "*" else existing_users,
            required=True,
            help_text="不知道自己的 open_id 时：先选“首次联调”，启动后向 Bot 发送“我的ID”，再重新运行本向导锁定。",
        )
        chat_ids = wizard.ask_text(
            "allowed_chat_ids（群聊控制建议填写；只允许私聊可留空）",
            default="" if existing_chats == "*" else existing_chats,
            required=False,
        )
        feishu["allowed_open_ids"] = parse_id_list(user_ids)
        feishu["allowed_chat_ids"] = parse_id_list(chat_ids)

    config["feishu"] = feishu
    return config, strategy


def print_next_steps(wizard: Wizard, config_path: Path, strategy: str, mode: str) -> None:
    wizard.section("下一步")
    wizard.say(f"1. 启动服务：python server/vote_server.py --config {config_path}")
    if mode == "websocket":
        wizard.say("2. 在飞书开放平台确认：事件与回调均选择“使用长连接接收”。")
    else:
        wizard.say("2. 在飞书开放平台配置 HTTP 回调地址：<你的域名>/feishu/events。")
    wizard.say("3. 私聊 Bot 或在运营群 @Bot 发送：菜单")
    if strategy == "temporary":
        wizard.say("4. 首次联调成功后发送：我的ID；拿到 open_id/chat_id 后重新运行本向导，选择“正式使用”。")


def main() -> int:
    parser = argparse.ArgumentParser(description="交互式配置飞书交互卡片 Bot")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="要写入的本地配置文件，默认 server/config.json")
    parser.add_argument("--example", default=str(DEFAULT_EXAMPLE), help="配置不存在时使用的示例文件")
    parser.add_argument("--no-backup", action="store_true", help="覆盖已有配置时不生成 .bak 备份")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    example_path = Path(args.example).expanduser()
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not example_path.is_absolute():
        example_path = PROJECT_ROOT / example_path
    if config_path.resolve() == example_path.resolve():
        raise SystemExit("请不要把真实飞书凭证写入 server/config.example.json；请使用默认的 server/config.json。")

    wizard = Wizard()
    config, created = load_config(config_path, example_path)
    if created:
        wizard.say(f"未找到 {config_path}，将从 {example_path} 创建。")
    else:
        wizard.say(f"读取已有配置：{config_path}")
    config, strategy = configure_feishu(config, wizard)
    mode = str((config.get("feishu") or {}).get("connection_mode") or "websocket")
    backup = save_config(config_path, config, make_backup=not args.no_backup and not created)
    wizard.say()
    wizard.say(f"已保存：{config_path}")
    if backup:
        wizard.say(f"已备份旧配置：{backup}")
    print_next_steps(wizard, config_path, strategy, mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
