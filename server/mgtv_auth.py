"""MangoTV login and recording source helpers.

The MangoTV web login/playback APIs are not public and may change without
notice. This module intentionally uses a browser-assisted flow for QR login
instead of hard-coding private QR endpoints. Playback source detection is also
best-effort and never attempts to bypass login, VIP, or DRM restrictions.
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import ClientSession


MANGO_HOME = "https://www.mgtv.com/"
MANGO_USER_API = "https://u.api.mgtv.com/user/get_login_user?needVipIcon=1"


def has_playwright() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


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


@dataclass
class MgtvQrLoginSession:
    status: str = "idle"
    message: str = ""
    error: str = ""
    screenshot: str = ""
    started_at: float = 0
    expires_at: float = 0
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
            "playwrightAvailable": has_playwright(),
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

    async def fetch_user_info(self, cookie_header: str) -> dict[str, Any]:
        if not cookie_header:
            return {}
        headers = {"Cookie": cookie_header, "User-Agent": "Mozilla/5.0"}
        async with ClientSession(headers=headers) as session:
            async with session.get(MANGO_USER_API, timeout=10) as response:
                return await response.json(content_type=None)

    async def start_qr_login(self, on_success: Any, *, timeout_seconds: int = 180) -> dict[str, Any]:
        async with self._lock:
            if self.login.task and not self.login.task.done() and self.login.status == "pending":
                return self.public_status()
            self.login = MgtvQrLoginSession(
                status="pending",
                message="正在打开芒果 TV 登录二维码，请稍候。",
                started_at=time.time(),
                expires_at=time.time() + timeout_seconds,
            )
            self.login.task = asyncio.create_task(self._run_qr_login(on_success, timeout_seconds), name="mgtv-qr-login")
            return self.public_status()

    async def _run_qr_login(self, on_success: Any, timeout_seconds: int) -> None:
        if not has_playwright():
            self.login.status = "failed"
            self.login.error = "服务器未安装 Playwright/Chromium，无法发起扫码登录。"
            return
        from playwright.async_api import async_playwright

        browser = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
                page = await context.new_page()
                await page.goto(MANGO_HOME, wait_until="domcontentloaded", timeout=30_000)
                await page.evaluate("() => { if (window.loginDialog) window.loginDialog(); }")
                await page.wait_for_timeout(2500)
                self.login.screenshot = await self._screenshot_data_url(page)
                self.login.message = "请用芒果 TV App 扫描二维码并确认登录。"
                deadline = time.time() + timeout_seconds
                while time.time() < deadline:
                    cookies = await context.cookies()
                    if logged_in_from_cookies(cookies):
                        cookie_header = cookie_header_from_cookies(cookies)
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
                    await page.wait_for_timeout(2000)
                    self.login.screenshot = await self._screenshot_data_url(page)
                self.login.status = "expired"
                self.login.error = "扫码登录已超时，请重新发起。"
                self.login.screenshot = ""
        except Exception as exc:  # noqa: BLE001 - browser-assisted login must report friendly failure
            self.login.status = "failed"
            self.login.error = f"芒果 TV 扫码登录失败：{exc}"
            self.login.screenshot = ""
        finally:
            if browser is not None:
                await browser.close()

    @staticmethod
    async def _screenshot_data_url(page: Any) -> str:
        raw = await page.screenshot(type="png", full_page=False)
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")

    async def detect_stream(self, page_url: str, preferred_quality: str = "auto", *, timeout_seconds: int = 25) -> dict[str, Any]:
        if not has_playwright():
            return {
                "ok": False,
                "error": "服务器未安装 Playwright/Chromium，无法检测播放源。",
                "loginRequired": not self.logged_in(),
                "vipRequired": "unknown",
                "quality": preferred_quality,
            }
        if not self.logged_in():
            return {
                "ok": False,
                "error": "尚未扫码登录芒果 TV，无法检测需要登录/VIP 的清晰度。",
                "loginRequired": True,
                "vipRequired": "unknown",
                "quality": preferred_quality,
            }
        from playwright.async_api import async_playwright

        browser = None
        found: list[str] = []
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(viewport={"width": 1280, "height": 860}, locale="zh-CN")
                cookies = self.browser_cookies()
                if cookies:
                    await context.add_cookies(cookies)
                page = await context.new_page()
                page.on("request", lambda req: found.append(req.url) if ".m3u8" in req.url.lower() else None)
                await page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(timeout_seconds * 1000)
                entries = await page.evaluate("""() => performance.getEntriesByType('resource').map((item) => item.name)""")
                for url in entries:
                    if isinstance(url, str) and ".m3u8" in url.lower() and url not in found:
                        found.append(url)
            stream_url = self._select_stream(found, preferred_quality)
            if not stream_url:
                return {
                    "ok": False,
                    "error": "未检测到可直录 m3u8。可能需要 VIP、当前清晰度不可用、播放源为 DRM，或芒果接口已变化。",
                    "loginRequired": False,
                    "vipRequired": "unknown",
                    "quality": preferred_quality,
                    "candidates": len(found),
                }
            return {
                "ok": True,
                "streamUrl": stream_url,
                "streamUrlConfigured": True,
                "quality": preferred_quality,
                "actualQuality": self._guess_quality(stream_url),
                "loginRequired": False,
                "vipRequired": "unknown",
                "candidates": len(found),
                "message": "已检测到可交给 ffmpeg 直录的播放流；VIP/DRM 状态以实际播放源检测结果为准。",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"播放源检测失败：{exc}",
                "loginRequired": False,
                "vipRequired": "unknown",
                "quality": preferred_quality,
            }
        finally:
            if browser is not None:
                await browser.close()

    @staticmethod
    def _guess_quality(url: str) -> str:
        lowered = url.lower()
        for label in ("2160", "1080", "720", "540", "480", "360"):
            if label in lowered:
                return label + "P"
        return "unknown"

    def _select_stream(self, urls: list[str], preferred_quality: str) -> str:
        unique = list(dict.fromkeys(urls))
        if not unique:
            return ""
        if preferred_quality and preferred_quality != "auto":
            digits = "".join(ch for ch in preferred_quality if ch.isdigit())
            if digits:
                match = next((url for url in unique if digits in url), "")
                if match:
                    return match
        return unique[-1]
