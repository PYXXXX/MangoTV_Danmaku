"""Feishu one-click app registration flow used by the operator Web UI.

This mirrors the public flow used by larksuite/cli `config init --new`:
request an app-registration device code, show the verification URL to the
operator, then poll until Feishu returns app credentials.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from aiohttp import ClientSession


ACCOUNTS_FEISHU = "https://accounts.feishu.cn"
OPEN_FEISHU = "https://open.feishu.cn"
APP_REGISTRATION_PATH = "/oauth/v1/app/registration"


class FeishuBindingError(RuntimeError):
    """Raised when the Feishu binding flow cannot proceed."""


@dataclass(frozen=True)
class FeishuBindingBegin:
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int
    expires_at: float


@dataclass(frozen=True)
class FeishuBindingResult:
    app_id: str
    app_secret: str
    open_id: str
    tenant_brand: str


def build_verification_url(user_code: str, version: str = "mgtv-danmaku") -> str:
    base = f"{OPEN_FEISHU}/page/cli?{urlencode({'user_code': user_code})}"
    return base + "&" + urlencode({"lpv": version, "ocv": version, "from": "mgtv-danmaku"})


def as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def read_json_payload(response: Any, action: str) -> dict[str, Any]:
    try:
        payload = await response.json(content_type=None)
    except Exception as exc:
        raise FeishuBindingError(f"{action}失败：飞书授权服务没有返回有效 JSON") from exc
    if not isinstance(payload, dict):
        raise FeishuBindingError(f"{action}失败：飞书授权服务返回格式无效")
    return payload


async def begin_binding(session: ClientSession) -> FeishuBindingBegin:
    data = {
        "action": "begin",
        "archetype": "PersonalAgent",
        "auth_method": "client_secret",
        "request_user_info": "open_id tenant_brand",
    }
    async with session.post(f"{ACCOUNTS_FEISHU}{APP_REGISTRATION_PATH}", data=data) as response:
        payload = await read_json_payload(response, "飞书绑定初始化")
    if response.status >= 400 or payload.get("error"):
        message = payload.get("error_description") or payload.get("error") or f"HTTP {response.status}"
        raise FeishuBindingError(f"飞书绑定初始化失败：{message}")
    user_code = str(payload.get("user_code") or "")
    device_code = str(payload.get("device_code") or "")
    if not user_code or not device_code:
        raise FeishuBindingError("飞书绑定初始化失败：未返回 user_code 或 device_code")
    expires_in = as_int(payload.get("expires_in"), 300)
    interval = max(1, as_int(payload.get("interval"), 5))
    return FeishuBindingBegin(
        device_code=device_code,
        user_code=user_code,
        verification_url=build_verification_url(user_code),
        expires_in=expires_in,
        interval=interval,
        expires_at=time.time() + expires_in,
    )


async def poll_binding_once(session: ClientSession, device_code: str, *, accounts_base: str = ACCOUNTS_FEISHU) -> FeishuBindingResult | None:
    data = {"action": "poll", "device_code": device_code}
    async with session.post(f"{accounts_base}{APP_REGISTRATION_PATH}", data=data) as response:
        payload = await read_json_payload(response, "飞书绑定轮询")

    error = str(payload.get("error") or "")
    if response.status >= 400 and not error:
        raise FeishuBindingError(f"飞书绑定失败：HTTP {response.status}")
    if not error and payload.get("client_id"):
        user_info = payload.get("user_info") if isinstance(payload.get("user_info"), dict) else {}
        app_id = str(payload.get("client_id") or "")
        app_secret = str(payload.get("client_secret") or "")
        if not app_id or not app_secret:
            raise FeishuBindingError("飞书已授权，但没有返回完整 app_id/app_secret")
        return FeishuBindingResult(
            app_id=app_id,
            app_secret=app_secret,
            open_id=str(user_info.get("open_id") or ""),
            tenant_brand=str(user_info.get("tenant_brand") or "feishu"),
        )

    if error in {"authorization_pending", ""}:
        return None
    if error == "slow_down":
        await asyncio.sleep(5)
        return None
    if error == "access_denied":
        raise FeishuBindingError("用户取消了飞书绑定授权")
    if error in {"expired_token", "invalid_grant"}:
        raise FeishuBindingError("飞书绑定链接已过期，请重新发起绑定")
    message = payload.get("error_description") or error or f"HTTP {response.status}"
    raise FeishuBindingError(f"飞书绑定失败：{message}")
