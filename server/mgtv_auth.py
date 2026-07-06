"""MangoTV login and recording source helpers.

MangoTV web login/playback APIs are not public and may change without notice.
This module uses the same HTTP QR-code flow and live source endpoint that the
web client currently calls. It never attempts to bypass login, VIP, paywall, or
DRM restrictions; account permissions are determined by MangoTV's own response.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlparse

from aiohttp import ClientSession, ClientTimeout, CookieJar


MANGO_USER_API = "https://u.api.mgtv.com/user/get_login_user?needVipIcon=1"
MANGO_QR_API = "https://oauth.mgtv.com/2.0/getqrcode"
MANGO_QR_POLLING_API = "https://oauth.mgtv.com/2.0/polling"
MANGO_TICKET_API = "https://i.mgtv.com/account/getByTicket"
MANGO_LIVE_SOURCE_API = "https://pwlp.bz.mgtv.com/v1/live/source"
MANGO_LIVE_SOURCE_SIGN_SALT = "LMFwh1k1m@pvt#Pt"
MANGO_PCWEB_VERSION = "9.0.4-1"


def cookie_header_from_cookies(cookies: list[dict[str, Any]]) -> str:
    pairs = []
    seen = set()
    for item in cookies:
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        domain = str(item.get("domain") or "")
        if not name or name in seen or "mgtv" not in domain:
            continue
        seen.add(name)
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def logged_in_from_cookies(cookies: list[dict[str, Any]]) -> bool:
    names = {str(item.get("name") or "") for item in cookies}
    return "HDCN" in names and "uuid" in names


def cookies_from_header(cookie_header: str) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for item in str(cookie_header or "").split(";"):
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            continue
        cookies.append({
            "name": name,
            "value": value.strip(),
            "domain": ".mgtv.com",
            "path": "/",
            "secure": True,
        })
    return cookies


def cookie_values(cookie_header: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in str(cookie_header or "").split(";"):
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        if name:
            result[name] = value.strip()
    return result


def mgtv_live_source_sign(params: dict[str, Any]) -> str:
    payload = "".join(
        f"{key}{params[key]}"
        for key in sorted(params)
        if params[key] is not None
    )
    return hashlib.md5(f"{MANGO_LIVE_SOURCE_SIGN_SALT}{payload}{MANGO_LIVE_SOURCE_SIGN_SALT}".encode()).hexdigest().upper()


def parse_mgtv_activity_camera(page_url: str) -> tuple[str, str]:
    parsed = urlparse(str(page_url or ""))
    match = re.search(r"/z2?/([^/?#]+)/([^/?#]+)", parsed.path)
    if not match:
        return "", ""
    activity_id = match.group(1).strip()
    camera_id = re.sub(r"\.html$", "", match.group(2).strip(), flags=re.I)
    return activity_id, camera_id


def _json_data(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    match = re.match(r"^[\w$.]+\((.*)\)\s*;?$", text, flags=re.S)
    if match:
        text = match.group(1)
    import json

    return json.loads(text)


def _cookie_header_from_simple_cookie(cookie: SimpleCookie[str]) -> str:
    return "; ".join(f"{name}={morsel.value}" for name, morsel in cookie.items())


@dataclass
class MgtvQrLoginSession:
    status: str = "idle"
    message: str = ""
    error: str = ""
    screenshot: str = ""
    started_at: float = 0
    expires_at: float = 0
    uid: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    user_info: dict[str, Any] = field(default_factory=dict)
    task: asyncio.Task[Any] | None = None


class MgtvAuthManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config or {}
        self.login = MgtvQrLoginSession()
        self._lock = asyncio.Lock()

    def configured_cookies(self) -> list[dict[str, Any]]:
        cookies = self.config.get("cookies")
        return cookies if isinstance(cookies, list) else []

    def browser_cookies(self) -> list[dict[str, Any]]:
        cookies = self.configured_cookies()
        if cookies:
            return cookies
        return cookies_from_header(str(self.config.get("cookie_header") or ""))

    def cookie_header(self) -> str:
        explicit = str(self.config.get("cookie_header") or "").strip()
        if explicit:
            return explicit
        return cookie_header_from_cookies(self.configured_cookies())

    def logged_in(self) -> bool:
        return bool(self.cookie_header()) or logged_in_from_cookies(self.configured_cookies())

    def public_status(self) -> dict[str, Any]:
        return {
            "status": self.login.status,
            "message": self.login.message,
            "error": self.login.error,
            "screenshot": self.login.screenshot if self.login.status == "pending" else "",
            "expiresAt": int(self.login.expires_at),
            "cookieConfigured": self.logged_in(),
            "loginProtocol": "mgtv_http_qr",
            "loginProtocolAvailable": True,
            "user": self.redacted_user_info(self.config.get("user_info") or self.login.user_info),
        }

    @staticmethod
    def redacted_user_info(info: Any) -> dict[str, Any]:
        if not isinstance(info, dict):
            return {}
        data = info.get("data") if isinstance(info.get("data"), dict) else info
        vipinfo = data.get("vipinfo") if isinstance(data.get("vipinfo"), dict) else {}
        try:
            vip_type = int(vipinfo.get("type") or data.get("vip_id") or 0)
        except (TypeError, ValueError):
            vip_type = 0
        return {
            "uid": str(data.get("uid") or data.get("uuid") or ""),
            "nickname": str(data.get("nickname") or data.get("nickName") or ""),
            "isVip": bool(data.get("isvip") or data.get("isVip") or vip_type > 0),
            "vipType": str(vip_type or ""),
        }

    async def _request_json(self, session: ClientSession, url: str, **kwargs: Any) -> dict[str, Any]:
        async with session.get(url, **kwargs) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}: {text[:120]}")
            data = _json_data(text)
            return data if isinstance(data, dict) else {}

    async def _image_data_url(self, session: ClientSession, url: str) -> str:
        secure_url = str(url or "").replace("http://", "https://", 1)
        async with session.get(secure_url) as response:
            content = await response.read()
            content_type = response.headers.get("Content-Type") or "image/jpeg"
            if response.status >= 400 or not content_type.startswith("image/"):
                raise RuntimeError("二维码图片获取失败")
            return f"data:{content_type};base64," + base64.b64encode(content).decode("ascii")

    async def fetch_user_info(self, cookie_header: str) -> dict[str, Any]:
        if not cookie_header:
            return {}
        headers = {"Cookie": cookie_header, "User-Agent": "Mozilla/5.0"}
        timeout = ClientTimeout(total=12, connect=5, sock_read=8)
        async with ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(MANGO_USER_API) as response:
                return await response.json(content_type=None)

    async def start_qr_login(self, on_success: Any, *, timeout_seconds: int = 180) -> dict[str, Any]:
        async with self._lock:
            if self.login.task and not self.login.task.done() and self.login.status == "pending":
                return self.public_status()
            self.login = MgtvQrLoginSession(
                status="pending",
                message="正在向芒果 TV 获取登录二维码，请稍候。",
                started_at=time.time(),
                expires_at=time.time() + timeout_seconds,
            )
            self.login.task = asyncio.create_task(self._run_qr_login(on_success, timeout_seconds), name="mgtv-qr-login")
            return self.public_status()

    async def _run_qr_login(self, on_success: Any, timeout_seconds: int) -> None:
        timeout = ClientTimeout(total=20, connect=8, sock_read=12)
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://i.mgtv.com/account/login",
        }
        try:
            async with ClientSession(headers=headers, timeout=timeout, cookie_jar=CookieJar(unsafe=True)) as session:
                device_id = str(self.config.get("device_id") or "0")
                qr = await self._request_json(session, MANGO_QR_API, params={"invoker": "pc", "deviceid": device_id})
                msg = qr.get("msg") if isinstance(qr.get("msg"), dict) else {}
                uid = str(msg.get("uid") or "")
                pic_url = str(msg.get("pic_url") or "")
                if qr.get("err") != 0 or qr.get("status") != "00000" or not uid or not pic_url:
                    raise RuntimeError(str(qr.get("msg") or "二维码接口返回异常"))
                self.login.uid = uid
                self.login.screenshot = await self._image_data_url(session, pic_url)
                self.login.message = "请用芒果 TV App 扫描二维码并确认登录。"
                deadline = time.time() + timeout_seconds
                while time.time() < deadline:
                    await asyncio.sleep(2)
                    poll = await self._request_json(session, MANGO_QR_POLLING_API, params={"invoker": "pc", "uid": uid})
                    poll_msg = poll.get("msg") if isinstance(poll.get("msg"), dict) else {}
                    code = str(poll_msg.get("code") or "")
                    if code == "203":
                        self.login.message = "请用芒果 TV App 扫描二维码。"
                        continue
                    if code == "208":
                        self.login.message = "扫码成功，请在手机上确认登录。"
                        continue
                    if code != "201":
                        if poll.get("err") == 1 and str(poll.get("status")) == "10045":
                            self.login.status = "expired"
                            self.login.error = "二维码已过期，请重新发起扫码登录。"
                            self.login.screenshot = ""
                            return
                        continue

                    ticket = str(poll_msg.get("ticket") or "")
                    if not ticket:
                        raise RuntimeError("扫码成功但未返回登录 ticket")
                    login_result = await self._request_json(session, MANGO_TICKET_API, params={"ticket": ticket})
                    if int(login_result.get("code") or 0) != 200:
                        raise RuntimeError(str(login_result.get("msg") or "ticket 登录失败"))

                    cookie = session.cookie_jar.filter_cookies("https://www.mgtv.com/")
                    cookie_header = _cookie_header_from_simple_cookie(cookie)
                    if not cookie_header:
                        cookie = session.cookie_jar.filter_cookies("https://i.mgtv.com/")
                        cookie_header = _cookie_header_from_simple_cookie(cookie)
                    cookies = cookies_from_header(cookie_header)
                    user_info = await self.fetch_user_info(cookie_header)
                    self.login.cookies = cookies
                    self.login.user_info = user_info
                    await on_success(cookies, cookie_header, user_info)
                    self.config["cookies"] = cookies
                    self.config["cookie_header"] = cookie_header
                    self.config["user_info"] = user_info
                    self.login.status = "bound"
                    self.login.message = "芒果 TV 扫码登录成功，登录态已保存。"
                    self.login.screenshot = ""
                    return
                self.login.status = "expired"
                self.login.error = "扫码登录已超时，请重新发起。"
                self.login.screenshot = ""
        except Exception as exc:  # noqa: BLE001 - API flow must report friendly failure
            self.login.status = "failed"
            self.login.error = f"芒果 TV 扫码登录失败：{exc}"
            self.login.screenshot = ""

    async def detect_stream(self, page_url: str, preferred_quality: str = "auto", *, timeout_seconds: int = 25) -> dict[str, Any]:
        activity_id, camera_id = parse_mgtv_activity_camera(page_url)
        preferred_quality = preferred_quality or "auto"
        if not activity_id or not camera_id:
            return {
                "ok": False,
                "error": "无法从直播 URL 解析 activity_id/camera_id，请使用 /z/{activityId}/{cameraId}.html 格式。",
                "loginRequired": not self.logged_in(),
                "vipRequired": "unknown",
                "quality": preferred_quality,
            }
        cookie_header = self.cookie_header()
        values = cookie_values(cookie_header)
        uid = values.get("uuid") or values.get("UUID") or ""
        token = values.get("HDCN") or values.get("ticket") or values.get("Ticket") or ""
        did = str(self.config.get("device_id") or values.get("__STKUUID") or uuid.uuid4())
        definition = "".join(ch for ch in preferred_quality if ch.isdigit())
        params: dict[str, Any] = {
            "cameraId": camera_id,
            "activityId": activity_id,
            "platform": "4",
            "appVersion": f"imgotv-pch5-{MANGO_PCWEB_VERSION}",
            "clientKey": "pcweb",
            "auth_mode": "1",
            "local_definition": "",
            "init_definition": "2",
            "did": did,
            "uid": uid,
            "token": token,
            "_t": str(int(time.time() * 1000)),
            "deviceId": did,
            "definition": definition,
        }
        params["_support"] = "10000000"
        params["sign"] = mgtv_live_source_sign({key: value for key, value in params.items() if key != "_support"})
        timeout = ClientTimeout(total=timeout_seconds, connect=8, sock_read=max(8, timeout_seconds - 2))
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": page_url,
            "Cookie": cookie_header,
        }
        try:
            async with ClientSession(headers=headers, timeout=timeout) as session:
                data = await self._request_json(session, MANGO_LIVE_SOURCE_API, params=params)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"播放源检测失败：{exc}",
                "loginRequired": not self.logged_in(),
                "vipRequired": "unknown",
                "quality": preferred_quality,
            }

        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
        selected = self._select_source(sources, preferred_quality)
        stream_url = str(selected.get("url") or "") if selected else ""
        code = str(data.get("code") or "")
        message = str(data.get("msg") or "")
        if not stream_url:
            pay_source = selected or next((item for item in sources if str(item.get("needPay") or "") == "1"), None)
            vip_required = bool(pay_source and str(pay_source.get("needPay") or "") == "1") or code in {"2040352", "2040101", "2040114", "2040117", "2040202", "2040363", "2040353"}
            available = [str(item.get("name") or item.get("definition") or "") for item in sources if item.get("url")]
            return {
                "ok": False,
                "error": message or "未获取到可直录播放流。可能需要登录/VIP，或当前清晰度不可用。",
                "loginRequired": not self.logged_in(),
                "vipRequired": vip_required,
                "quality": preferred_quality,
                "actualQuality": str(selected.get("name") or "") if selected else "",
                "availableQualities": [item for item in available if item],
                "candidates": len(sources),
                "code": code,
            }
        return {
            "ok": True,
            "streamUrl": stream_url,
            "streamUrlConfigured": True,
            "quality": preferred_quality,
            "actualQuality": str(selected.get("name") or self._guess_quality(stream_url)),
            "loginRequired": False,
            "vipRequired": str(selected.get("needPay") or "") == "1",
            "candidates": len(sources),
            "code": code,
            "message": "已通过芒果直播源接口检测到可交给 ffmpeg 直录的播放流。",
        }

    @staticmethod
    def _guess_quality(url: str) -> str:
        lowered = url.lower()
        for label in ("2160", "1080", "720", "540", "480", "360"):
            if label in lowered:
                return label + "P"
        return "unknown"

    def _select_source(self, sources: list[Any], preferred_quality: str) -> dict[str, Any]:
        candidates = [item for item in sources if isinstance(item, dict)]
        if not candidates:
            return {}
        if preferred_quality and preferred_quality != "auto":
            digits = "".join(ch for ch in preferred_quality if ch.isdigit())
            if digits:
                match = next(
                    (
                        item
                        for item in candidates
                        if digits in str(item.get("name") or "")
                        or digits in str(item.get("definition") or "")
                    ),
                    None,
                )
                if match:
                    return match
        return next((item for item in candidates if item.get("url")), candidates[0])
