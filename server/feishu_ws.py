"""Feishu WebSocket long-connection adapter built on the official Python SDK."""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
import json
import logging
import re
import threading
import time
from typing import Any


LOGGER = logging.getLogger(__name__)


class FeishuLongConnection:
    def __init__(self, config: dict[str, Any], service: Any):
        self.config = config
        self.service = service
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client: Any = None
        self.thread: threading.Thread | None = None
        self.sdk_loop: asyncio.AbstractEventLoop | None = None
        self._stopping = threading.Event()
        self._dedup: dict[str, float] = {}
        self._dedup_lock = threading.Lock()

    def start(self, loop: asyncio.AbstractEventLoop) -> bool:
        if not self.config.get("enabled") or self.config.get("connection_mode", "websocket") != "websocket":
            return False
        if not self.config.get("app_id") or not self.config.get("app_secret"):
            raise RuntimeError("飞书长连接缺少 app_id 或 app_secret")
        if importlib.util.find_spec("lark_oapi") is None:
            raise RuntimeError("飞书长连接需要安装 lark-oapi，请重新执行 pip install -r requirements-server.txt")
        self.loop = loop
        self._stopping.clear()
        self.thread = threading.Thread(target=self._run, name="feishu-websocket", daemon=True)
        self.thread.start()
        return True

    def stop(self, timeout: float = 8.0) -> None:
        self._stopping.set()
        client = self.client
        sdk_loop = self.sdk_loop
        if client is not None:
            client._auto_reconnect = False
        if client is not None and sdk_loop is not None and sdk_loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(client._disconnect(), sdk_loop)
                future.result(timeout=max(1.0, timeout / 2))
            except Exception:
                LOGGER.exception("关闭飞书长连接失败")
            sdk_loop.call_soon_threadsafe(sdk_loop.stop)
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self.client = None
        self.thread = None
        self.sdk_loop = None

    def _run(self) -> None:
        # Import inside the worker thread so the SDK owns a dedicated asyncio
        # loop instead of trying to reuse aiohttp's already-running main loop.
        import lark_oapi as lark
        import lark_oapi.ws.client as ws_client
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse

        loop = self.loop
        if loop is None:
            return
        sdk_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(sdk_loop)
        ws_client.loop = sdk_loop
        self.sdk_loop = sdk_loop

        def on_message(data: Any) -> None:
            try:
                event = data.event
                message = event.message
                sender_id = event.sender.sender_id
                content = json.loads(message.content or "{}")
                text = re.sub(r"@_user_\d+\s*", "", str(content.get("text", ""))).strip()
                open_id = getattr(sender_id, "open_id", "") or ""
                chat_id = getattr(message, "chat_id", "") or ""
                chat_type = getattr(message, "chat_type", "") or ""
                receive_id = chat_id if chat_type == "group" else open_id
                receive_type = "chat_id" if chat_type == "group" else "open_id"
                future = asyncio.run_coroutine_threadsafe(
                    self.service.handle_feishu_text(text, open_id, chat_id, receive_id, receive_type),
                    loop,
                )
                future.add_done_callback(self._log_future_error)
            except Exception:
                LOGGER.exception("处理飞书消息事件失败")

        def on_card_action(data: Any) -> Any:
            event = getattr(data, "event", None)
            action = getattr(event, "action", None)
            if not event or not action:
                return P2CardActionTriggerResponse({})
            value = getattr(action, "value", None) or {}
            action_name = str(value.get("action") or "")
            option = str(getattr(action, "option", "") or "")
            operator = getattr(event, "operator", None)
            context = getattr(event, "context", None)
            open_id = getattr(operator, "open_id", "") or ""
            chat_id = getattr(context, "open_chat_id", "") or ""
            message_id = getattr(context, "open_message_id", "") or ""
            dedup_key = f"{message_id}|{open_id}|{action_name}|{option}"
            if self._is_duplicate(dedup_key):
                return P2CardActionTriggerResponse({"toast": {"type": "info", "content": "操作已处理"}})
            future = asyncio.run_coroutine_threadsafe(
                self.service.handle_feishu_card_action(action_name, open_id, chat_id, option),
                loop,
            )
            try:
                card = future.result(timeout=2.4)
                return P2CardActionTriggerResponse({"card": {"type": "raw", "data": card}})
            except concurrent.futures.TimeoutError:
                receive_id = chat_id or open_id
                receive_type = "chat_id" if chat_id else "open_id"
                future.add_done_callback(lambda done: self._send_late_card(done, receive_id, receive_type))
                return P2CardActionTriggerResponse({"toast": {"type": "info", "content": "正在处理，完成后会发送新卡片"}})
            except Exception as exc:
                LOGGER.exception("处理飞书卡片操作失败")
                return P2CardActionTriggerResponse({"toast": {"type": "error", "content": str(exc)[:80]}})

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message)
            .register_p2_card_action_trigger(on_card_action)
            .build()
        )
        self.client = lark.ws.Client(
            self.config["app_id"],
            self.config["app_secret"],
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )
        try:
            self.client.start()
        except RuntimeError:
            if not self._stopping.is_set():
                raise
        finally:
            pending = asyncio.all_tasks(sdk_loop)
            for task in pending:
                task.cancel()
            if pending:
                sdk_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            sdk_loop.close()

    def _is_duplicate(self, key: str) -> bool:
        now = time.monotonic()
        with self._dedup_lock:
            self._dedup = {item: seen_at for item, seen_at in self._dedup.items() if now - seen_at < 5}
            if key in self._dedup:
                return True
            self._dedup[key] = now
            return False

    def _log_future_error(self, future: concurrent.futures.Future[Any]) -> None:
        try:
            future.result()
        except Exception:
            LOGGER.exception("飞书异步任务失败")

    def _send_late_card(self, future: concurrent.futures.Future[Any], receive_id: str, receive_type: str) -> None:
        try:
            card = future.result()
        except Exception:
            LOGGER.exception("飞书延迟卡片生成失败")
            return
        if self.loop and receive_id:
            sent = asyncio.run_coroutine_threadsafe(
                self.service.feishu.send_card(receive_id, receive_type, card),
                self.loop,
            )
            sent.add_done_callback(self._log_future_error)
