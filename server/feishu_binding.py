"""Feishu one-click app registration flow used by the operator Web UI.

This follows the same public app-registration flow used by larksuite/cli and
cc-connect: initialise the registration endpoint, request a PersonalAgent
device code, show the verification URL to the operator, then poll until Feishu
returns app credentials.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from aiohttp import ClientSession


ACCOUNTS_FEISHU = "https://accounts.feishu.cn"
ACCOUNTS_LARK = "https://accounts.larksuite.com"
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
    accounts_base: str = ACCOUNTS_FEISHU


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


async def registration_call(
    session: ClientSession,
    action: str,
    data: dict[str, str] | None = None,
    *,
    accounts_base: str = ACCOUNTS_FEISHU,
) -> dict[str, Any]:
    payload_data = {"action": action}
    if data:
        payload_data.update(data)
    async with session.post(f"{accounts_base}{APP_REGISTRATION_PATH}", data=payload_data) as response:
        payload = await read_json_payload(response, "飞书绑定")
    if response.status >= 400 and not payload.get("error"):
        raise FeishuBindingError(f"飞书绑定失败：HTTP {response.status}")
    return payload


async def read_json_payload(response: Any, action: str) -> dict[str, Any]:
    try:
        payload = await response.json(content_type=None)
    except Exception as exc:
        raise FeishuBindingError(f"{action}失败：飞书授权服务没有返回有效 JSON") from exc
    if not isinstance(payload, dict):
        raise FeishuBindingError(f"{action}失败：飞书授权服务返回格式无效")
    return payload


async def begin_binding(session: ClientSession) -> FeishuBindingBegin:
    init_payload = await registration_call(session, "init")
    if init_payload.get("error"):
        message = init_payload.get("error_description") or init_payload.get("error")
        raise FeishuBindingError(f"飞书绑定初始化失败：{message}")
    methods = init_payload.get("supported_auth_methods")
    if isinstance(methods, list) and methods and "client_secret" not in {str(item).lower() for item in methods}:
        raise FeishuBindingError("飞书绑定初始化失败：当前环境不支持 client_secret 授权方式")

    data = {
        "archetype": "PersonalAgent",
        "auth_method": "client_secret",
        "request_user_info": "open_id tenant_brand",
    }
    payload = await registration_call(session, "begin", data)
    if payload.get("error"):
        message = payload.get("error_description") or payload.get("error")
        raise FeishuBindingError(f"飞书绑定初始化失败：{message}")
    user_code = str(payload.get("user_code") or "")
    device_code = str(payload.get("device_code") or "")
    if not user_code or not device_code:
        raise FeishuBindingError("飞书绑定初始化失败：未返回 user_code 或 device_code")
    verification_url = str(payload.get("verification_uri_complete") or "").strip() or build_verification_url(user_code)
    expires_in = as_int(payload.get("expires_in"), 300)
    interval = max(1, as_int(payload.get("interval"), 5))
    return FeishuBindingBegin(
        device_code=device_code,
        user_code=user_code,
        verification_url=verification_url,
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
            tenant_brand=str(user_info.get("tenant_brand") or "feishu").lower(),
        )

    user_info = payload.get("user_info") if isinstance(payload.get("user_info"), dict) else {}
    tenant_brand = str(user_info.get("tenant_brand") or "").lower()
    if tenant_brand == "lark" and accounts_base != ACCOUNTS_LARK:
        return await poll_binding_once(session, device_code, accounts_base=ACCOUNTS_LARK)

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
