"""Password hashing and signed sessions for the operator Web UI."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import deque
from typing import Any
from urllib.parse import urlsplit


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
COOKIE_NAME = "mgtv_operator_session"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, iterations: int = PASSWORD_ITERATIONS, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("密码不能为空")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PASSWORD_SCHEME}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        iterations = int(raw_iterations)
        if scheme != PASSWORD_SCHEME or not 100_000 <= iterations <= 5_000_000:
            return False
        salt = _b64decode(raw_salt)
        expected = _b64decode(raw_digest)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def new_session_secret() -> str:
    return secrets.token_urlsafe(32)


def safe_next_url(value: str | None) -> str:
    value = str(value or "/")
    if "\\" in value or any(character in value for character in "\r\n\0"):
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return "/"
    result = parsed.path
    if parsed.query:
        result += f"?{parsed.query}"
    return result


class OperatorAuth:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.enabled = bool(config.get("enabled"))
        self.password_hash = str(config.get("password_hash") or "")
        self.session_secret = str(config.get("session_secret") or "")
        self.session_hours = max(1, min(int(config.get("session_hours") or 12), 168))
        self.secure_cookie = bool(config.get("secure_cookie"))
        self.max_failures = max(3, min(int(config.get("max_failures") or 5), 20))
        self.failure_window_seconds = max(60, min(int(config.get("failure_window_seconds") or 300), 3600))
        self._failures: dict[str, deque[float]] = {}
        if self.enabled:
            if not self.password_hash or not self.session_secret:
                raise RuntimeError(
                    "运营端密码保护已启用但配置不完整，请运行 python tools/setup_operator_password.py"
                )
            if not self.password_hash.startswith(f"{PASSWORD_SCHEME}$"):
                raise RuntimeError("运营端 password_hash 格式无效，请重新运行密码配置向导")

    @property
    def cookie_max_age(self) -> int:
        return self.session_hours * 3600

    def verify_password(self, password: str) -> bool:
        return verify_password(password, self.password_hash)

    def make_session_token(self, *, now: int | None = None) -> str:
        issued_at = int(time.time() if now is None else now)
        expires_at = issued_at + self.cookie_max_age
        payload = f"v1.{expires_at}.{secrets.token_urlsafe(12)}".encode("utf-8")
        signature = hmac.new(self.session_secret.encode("utf-8"), payload, hashlib.sha256).digest()
        return f"{_b64encode(payload)}.{_b64encode(signature)}"

    def verify_session_token(self, token: str, *, now: int | None = None) -> bool:
        try:
            raw_payload, raw_signature = token.split(".", 1)
            payload = _b64decode(raw_payload)
            signature = _b64decode(raw_signature)
            expected = hmac.new(self.session_secret.encode("utf-8"), payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                return False
            version, raw_expiry, _ = payload.decode("utf-8").split(".", 2)
            current_time = int(time.time() if now is None else now)
            return version == "v1" and current_time <= int(raw_expiry)
        except (TypeError, ValueError, UnicodeDecodeError):
            return False

    def request_is_authenticated(self, request: Any) -> bool:
        if not self.enabled:
            return True
        return self.verify_session_token(request.cookies.get(COOKIE_NAME, ""))

    def set_session_cookie(self, response: Any) -> None:
        response.set_cookie(
            COOKIE_NAME,
            self.make_session_token(),
            max_age=self.cookie_max_age,
            httponly=True,
            secure=self.secure_cookie,
            samesite="Strict",
            path="/",
        )

    def clear_session_cookie(self, response: Any) -> None:
        response.del_cookie(
            COOKIE_NAME,
            path="/",
            secure=self.secure_cookie,
            httponly=True,
            samesite="Strict",
        )

    def _recent_failures(self, key: str, *, now: float | None = None) -> deque[float]:
        current_time = time.monotonic() if now is None else now
        cutoff = current_time - self.failure_window_seconds
        failures = self._failures.get(key, deque())
        while failures and failures[0] < cutoff:
            failures.popleft()
        if failures:
            self._failures[key] = failures
        else:
            self._failures.pop(key, None)
        return failures

    def is_rate_limited(self, key: str, *, now: float | None = None) -> bool:
        return len(self._recent_failures(key, now=now)) >= self.max_failures

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        failures = self._recent_failures(key, now=current_time)
        failures.append(current_time)
        self._failures[key] = failures

    def clear_failures(self, key: str) -> None:
        self._failures.pop(key, None)
