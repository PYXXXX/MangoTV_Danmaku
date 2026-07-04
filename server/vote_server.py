#!/usr/bin/env python3
"""Server-side MGTV danmaku vote collector with Feishu remote control.

This service intentionally publishes only aggregate vote results. Raw danmaku
messages are stored locally as JSONL for audit/offline cleaning.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import html
import json
import os
import re
import secrets
import signal
import sqlite3
import time
import unicodedata
import copy
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientSession, ClientTimeout, web

try:
    from server import feishu_binding
    from server.precise_results import parse_precise_result, validate_precise_result
    from server.feishu_cards import build_control_card, build_round_list_card
    from server.operator_auth import OperatorAuth, safe_next_url
    from server.runtime_settings import (
        SettingsValidationError,
        build_settings_update,
        has_real_value,
        public_settings,
        save_config_atomic,
    )
    from server.updater import GitUpdater, UpdateError
except ModuleNotFoundError:  # Support `python server/vote_server.py`.
    import feishu_binding
    from precise_results import parse_precise_result, validate_precise_result
    from feishu_cards import build_control_card, build_round_list_card
    from operator_auth import OperatorAuth, safe_next_url
    from runtime_settings import SettingsValidationError, build_settings_update, has_real_value, public_settings, save_config_atomic
    from updater import GitUpdater, UpdateError


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def safe_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_beijing_range(start: str, end: str) -> str:
    start_dt = parse_iso(start).astimezone(BEIJING_TZ)
    end_dt = parse_iso(end).astimezone(BEIJING_TZ)
    return f"{start_dt:%Y%m%d %H:%M:%S}-{end_dt:%Y%m%d %H:%M:%S}"


class FingerprintCache:
    """Small in-memory LRU cache for hot duplicate checks.

    The full exact-ish dedup index lives in SQLite. This cache only avoids hitting
    SQLite for common near-term duplicates from repeated history snapshots.
    """

    def __init__(self, max_size: int = 200_000):
        self.max_size = max(1, int(max_size))
        self.items: OrderedDict[bytes, None] = OrderedDict()

    def clear(self) -> None:
        self.items.clear()

    def __len__(self) -> int:
        return len(self.items)

    def contains(self, key: bytes) -> bool:
        if key not in self.items:
            return False
        self.items.move_to_end(key)
        return True

    def add(self, key: bytes) -> None:
        self.items[key] = None
        self.items.move_to_end(key)
        while len(self.items) > self.max_size:
            self.items.popitem(last=False)

    def resize(self, max_size: int) -> None:
        self.max_size = max(1, int(max_size))
        while len(self.items) > self.max_size:
            self.items.popitem(last=False)


class PersistentDeduper:
    """SQLite-backed deduper with bounded memory and a large disk cap.

    At the requested 100M scale a Python set would consume many GB of memory.
    This class keeps only a hot LRU cache in RAM and stores fixed-size SHA-1
    fingerprint keys in SQLite. The cap is enforced by insertion order.
    """

    def __init__(self, db_path: Path, hot_cache_size: int = 200_000, max_records: int = 100_000_000):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.hot = FingerprintCache(hot_cache_size)
        self.max_records = max(1, int(max_records))
        self.seq = 0
        self.insertions_since_prune = 0
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("CREATE TABLE IF NOT EXISTS fingerprints (fp BLOB PRIMARY KEY, seq INTEGER NOT NULL)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_fingerprints_seq ON fingerprints(seq)")
        row = self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM fingerprints").fetchone()
        self.seq = int(row[0] or 0)

    def clear(self) -> None:
        self.hot.clear()
        self.conn.execute("DELETE FROM fingerprints")
        self.conn.commit()
        self.seq = 0
        self.insertions_since_prune = 0

    def close(self) -> None:
        self.conn.close()

    def reconfigure(self, hot_cache_size: int, max_records: int) -> None:
        self.hot.resize(hot_cache_size)
        self.max_records = max(1, int(max_records))
        self.prune()

    def key_for(self, fingerprint: str) -> bytes:
        return hashlib.sha1(fingerprint.encode("utf-8")).digest()

    def seen_or_add(self, fingerprint: str) -> bool:
        key = self.key_for(fingerprint)
        if self.hot.contains(key):
            return True
        self.seq += 1
        cursor = self.conn.execute("INSERT OR IGNORE INTO fingerprints(fp, seq) VALUES (?, ?)", (key, self.seq))
        self.conn.commit()
        self.hot.add(key)
        if cursor.rowcount == 0:
            return True
        self.insertions_since_prune += 1
        if self.insertions_since_prune >= 10_000:
            self.prune()
        return False

    def prune(self) -> None:
        self.insertions_since_prune = 0
        row = self.conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()
        count = int(row[0] or 0)
        overflow = count - self.max_records
        if overflow <= 0:
            return
        self.conn.execute(
            "DELETE FROM fingerprints WHERE fp IN (SELECT fp FROM fingerprints ORDER BY seq ASC LIMIT ?)",
            (overflow,),
        )
        self.conn.commit()


@dataclass
class Candidate:
    id: str
    name: str
    aliases: list[str]


@dataclass
class RoundMeta:
    id: str
    activity: str
    baseName: str
    name: str
    status: str
    startedAt: str
    updatedAt: str
    stoppedAt: str | None
    pageUrl: str
    pageTitle: str
    candidates: list[Candidate]
    multiCandidatePolicy: str
    messageCount: int = 0
    reviewCount: int = 0
    voteCounts: dict[str, int] = field(default_factory=dict)
    sliceStartSeq: int = 1
    sliceEndSeq: int | None = None
    sliceStartTime: str = ""
    sliceEndTime: str | None = None
    preciseResult: dict[str, Any] | None = None
    precisePublishedAt: str | None = None


@dataclass
class DanmakuMessage:
    ts: str
    nickname: str
    content: str
    matches: list[str]
    votes: list[str]
    needsReview: bool
    url: str


def candidates_from_config(items: list[dict[str, Any]]) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen_aliases: dict[str, str] = {}
    for index, item in enumerate(items, 1):
        name = normalize(item.get("name", ""))
        aliases = [normalize(alias) for alias in item.get("aliases", [])]
        aliases = [alias for alias in aliases if alias]
        if name and name not in aliases:
            aliases.insert(0, name)
        if not name or not aliases:
            continue
        candidate = Candidate(id=item.get("id") or f"c{index}", name=name, aliases=list(dict.fromkeys(aliases)))
        for alias in candidate.aliases:
            key = alias.casefold()
            owner = seen_aliases.get(key)
            if owner and owner != candidate.name:
                raise ValueError(f"别名“{alias}”同时属于 {owner} 和 {candidate.name}")
            seen_aliases[key] = candidate.name
        candidates.append(candidate)
    if not candidates:
        raise ValueError("候选人列表为空")
    return candidates


class StateStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.rounds_dir = self.directory / "rounds"
        self.rounds_dir.mkdir(exist_ok=True)
        self.raw_messages_path = self.directory / "raw_messages.jsonl"
        self.meta_path = self.directory / "state.json"
        self.lock = asyncio.Lock()
        self.rounds: dict[str, RoundMeta] = {}
        self.round_order: list[str] = []
        self.active_round_id: str | None = None
        self.global_seq = 0

    def load(self) -> None:
        if not self.meta_path.exists():
            if self.raw_messages_path.exists():
                self.global_seq = self._scan_last_seq()
            return
        raw = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.active_round_id = raw.get("activeRoundId")
        self.round_order = raw.get("roundOrder", [])
        self.global_seq = int(raw.get("globalSeq") or self._scan_last_seq())
        self.rounds = {}
        for item in raw.get("rounds", []):
            candidates = [Candidate(**candidate) for candidate in item.get("candidates", [])]
            item.setdefault("activity", "未分类活动")
            item.setdefault("baseName", item.get("name", "未命名场次"))
            item.setdefault("sliceStartSeq", 1)
            item.setdefault("sliceEndSeq", None if item.get("status") == "running" else self.global_seq)
            item.setdefault("sliceStartTime", item.get("startedAt", ""))
            item.setdefault("sliceEndTime", item.get("stoppedAt"))
            item.setdefault("preciseResult", None)
            item.setdefault("precisePublishedAt", None)
            payload = {**item, "candidates": candidates}
            self.rounds[item["id"]] = RoundMeta(**payload)

    def _scan_last_seq(self) -> int:
        if not self.raw_messages_path.exists():
            return 0
        last_seq = 0
        with self.raw_messages_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                last_seq = max(last_seq, int(item.get("seq") or 0))
        return last_seq

    async def save(self) -> None:
        payload = {
            "schemaVersion": 1,
            "updatedAt": now_iso(),
            "activeRoundId": self.active_round_id,
            "globalSeq": self.global_seq,
            "roundOrder": self.round_order,
            "rounds": [asdict(self.rounds[round_id]) for round_id in self.round_order if round_id in self.rounds],
        }
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.meta_path)

    async def create_round(self, activity: str, name: str, url: str, candidates: list[Candidate], policy: str) -> RoundMeta:
        async with self.lock:
            round_id = safe_id()
            base_name = normalize(name) or f"第 {len(self.round_order) + 1} 轮"
            started_at = now_iso()
            meta = RoundMeta(
                id=round_id,
                activity=normalize(activity) or "未分类活动",
                baseName=base_name,
                name=base_name,
                status="running",
                startedAt=started_at,
                updatedAt=started_at,
                stoppedAt=None,
                pageUrl=url,
                pageTitle="",
                candidates=candidates,
                multiCandidatePolicy=policy,
                voteCounts={candidate.id: 0 for candidate in candidates},
                sliceStartSeq=self.global_seq + 1,
                sliceEndSeq=None,
                sliceStartTime=started_at,
                sliceEndTime=None,
            )
            self.rounds[round_id] = meta
            self.round_order.insert(0, round_id)
            self.active_round_id = round_id
            await self.save()
            return meta

    async def stop_active(self) -> RoundMeta | None:
        async with self.lock:
            if not self.active_round_id:
                return None
            meta = self.rounds.get(self.active_round_id)
            if not meta:
                return None
            meta.status = "stopped"
            meta.stoppedAt = now_iso()
            meta.updatedAt = meta.stoppedAt
            meta.sliceEndSeq = self.global_seq
            meta.sliceEndTime = meta.stoppedAt
            meta.name = f"{meta.baseName} · {format_beijing_range(meta.sliceStartTime, meta.sliceEndTime)}"
            self.active_round_id = None
            await self.save()
            return meta

    async def rename_round(self, round_id: str, name: str) -> RoundMeta:
        async with self.lock:
            meta = self.require_round(round_id)
            meta.baseName = normalize(name) or meta.baseName
            meta.name = (
                f"{meta.baseName} · {format_beijing_range(meta.sliceStartTime, meta.sliceEndTime)}"
                if meta.sliceEndTime
                else meta.baseName
            )
            if meta.preciseResult:
                meta.preciseResult["sessionName"] = meta.name
            meta.updatedAt = now_iso()
            await self.save()
            return meta

    async def set_precise_result(self, round_id: str, result: dict[str, Any]) -> RoundMeta:
        async with self.lock:
            meta = self.require_round(round_id)
            if meta.status == "running":
                raise ValueError("场次仍在采集中，请先结束场次再上传精确结果")
            published_at = now_iso()
            result["publishedAt"] = published_at
            meta.preciseResult = result
            meta.precisePublishedAt = published_at
            meta.updatedAt = published_at
            await self.save()
            return meta

    def require_round(self, round_id: str) -> RoundMeta:
        meta = self.rounds.get(round_id)
        if not meta:
            raise KeyError(f"找不到场次：{round_id}")
        return meta

    def find_round(self, query: str | None) -> RoundMeta | None:
        if not query:
            return self.rounds.get(self.active_round_id or "") or (self.rounds.get(self.round_order[0]) if self.round_order else None)
        query = normalize(query)
        if query in self.rounds:
            return self.rounds[query]
        for round_id in self.round_order:
            meta = self.rounds[round_id]
            if query in meta.name:
                return meta
        return None

    async def append_message(self, round_id: str, message: DanmakuMessage) -> None:
        async with self.lock:
            meta = self.require_round(round_id)
            self.global_seq += 1
            seq = self.global_seq
            meta.messageCount += 1
            meta.reviewCount += 1 if message.needsReview else 0
            for candidate_id in message.votes:
                meta.voteCounts[candidate_id] = meta.voteCounts.get(candidate_id, 0) + 1
            meta.updatedAt = now_iso()
            record = {"type": "message", "seq": seq, "roundId": round_id, **asdict(message)}
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            with self.raw_messages_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            with (self.rounds_dir / f"{round_id}.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            await self.save()

    def iter_slice_records(self, round_id: str):
        meta = self.require_round(round_id)
        start = meta.sliceStartSeq
        end = meta.sliceEndSeq if meta.sliceEndSeq is not None else self.global_seq
        if not self.raw_messages_path.exists():
            return
        with self.raw_messages_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                seq = int(item.get("seq") or 0)
                if start <= seq <= end and item.get("roundId") == round_id:
                    yield item

    def export_round_jsonl(self, round_id: str) -> str:
        meta = self.require_round(round_id)
        lines = [json.dumps({"type": "meta", **asdict(meta)}, ensure_ascii=False, separators=(",", ":"))]
        lines.extend(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in self.iter_slice_records(round_id))
        return "\n".join(lines) + "\n"

    def public_state(self) -> dict[str, Any]:
        sessions = []
        for round_id in self.round_order:
            meta = self.rounds[round_id]
            rough_result = {
                "resultType": "rough",
                "voteCounts": meta.voteCounts,
                "messageCount": meta.messageCount,
                "reviewCount": meta.reviewCount,
                "generatedAt": meta.updatedAt,
            }
            precise_result = meta.preciseResult
            sessions.append({
                "id": meta.id,
                "activity": meta.activity,
                "baseName": meta.baseName,
                "name": meta.name,
                "status": meta.status,
                "startedAt": meta.startedAt,
                "updatedAt": meta.updatedAt,
                "stoppedAt": meta.stoppedAt,
                "pageTitle": meta.pageTitle,
                "candidates": [asdict(candidate) for candidate in meta.candidates],
                "messageCount": meta.messageCount,
                "reviewCount": meta.reviewCount,
                "voteCounts": meta.voteCounts,
                "defaultResultType": "precise" if precise_result else "rough",
                "results": {"rough": rough_result, "precise": precise_result},
                "sliceStartSeq": meta.sliceStartSeq,
                "sliceEndSeq": meta.sliceEndSeq,
                "sliceStartTime": meta.sliceStartTime,
                "sliceEndTime": meta.sliceEndTime,
            })
        return {
            "schemaVersion": 1,
            "publishedAt": now_iso(),
            "activeSessionId": self.active_round_id or (self.round_order[0] if self.round_order else None),
            "sessions": sessions,
        }


class VoteEngine:
    def __init__(self, store: StateStore):
        self.store = store

    def match(self, text: str, candidates: list[Candidate]) -> list[str]:
        lowered = normalize(text).casefold()
        return [
            candidate.id
            for candidate in candidates
            if any(alias.casefold() in lowered for alias in candidate.aliases)
        ]

    async def ingest(self, round_id: str, raw: dict[str, Any]) -> DanmakuMessage | None:
        meta = self.store.require_round(round_id)
        content = normalize(raw.get("content", ""))
        if not content:
            return None
        matches = self.match(content, meta.candidates)
        needs_review = len(matches) > 1
        votes = [] if (needs_review and meta.multiCandidatePolicy == "review") else matches
        message = DanmakuMessage(
            ts=raw.get("ts") or now_iso(),
            nickname=normalize(raw.get("nickname", "")),
            content=content,
            matches=matches,
            votes=votes,
            needsReview=needs_review,
            url=raw.get("url") or meta.pageUrl,
        )
        await self.store.append_message(round_id, message)
        return message


class GithubPublisher:
    def __init__(self, config: dict[str, Any], store: StateStore):
        self.config = config
        self.store = store

    async def publish(self, force: bool = False, result_kind: str = "rough") -> str:
        if not self.config.get("enabled"):
            return "GitHub 同步未启用"
        required = ["owner", "repo", "branch", "path", "token"]
        missing = [key for key in required if not self.config.get(key)]
        if missing:
            raise RuntimeError(f"GitHub 配置缺失：{', '.join(missing)}")
        owner = self.config["owner"]
        repo = self.config["repo"]
        branch = self.config.get("branch", "main")
        path = str(self.config.get("path", "site/data/results.json")).lstrip("/")
        token = self.config["token"]
        encoded_path = "/".join(part for part in path.split("/"))
        base = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with ClientSession(headers=headers) as session:
            sha = None
            async with session.get(base, params={"ref": branch}) as response:
                if response.status == 200:
                    sha = (await response.json()).get("sha")
                elif response.status != 404:
                    raise RuntimeError(f"GitHub 查询失败：{response.status} {await response.text()}")
            content = json.dumps(self.store.public_state(), ensure_ascii=False, indent=2) + "\n"
            payload = {
                "message": f"data: publish {result_kind} vote results {now_iso()}",
                "branch": branch,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            }
            if sha:
                payload["sha"] = sha
            async with session.put(base, json=payload) as response:
                if response.status not in (200, 201):
                    raise RuntimeError(f"GitHub 发布失败：{response.status} {await response.text()}")
                data = await response.json()
        return data.get("commit", {}).get("html_url", "GitHub 发布成功")


class MgtvCollector:
    def __init__(self, config: dict[str, Any], engine: VoteEngine):
        self.config = config
        self.engine = engine
        self.task: asyncio.Task[None] | None = None
        self.stop_event = asyncio.Event()
        self.round_id: str | None = None
        self.url: str | None = None
        self.room_id: str | None = None
        self.fingerprints = PersistentDeduper(
            db_path=Path(config.get("dedup_db_path", "server/data/fingerprints.sqlite3")),
            hot_cache_size=int(config.get("dedup_hot_cache_size", 200_000)),
            max_records=int(config.get("dedup_max_records", 100_000_000)),
        )

    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def apply_config(self, config: dict[str, Any]) -> None:
        self.config = config
        self.fingerprints.reconfigure(
            int(config.get("dedup_hot_cache_size", 200_000)),
            int(config.get("dedup_max_records", 100_000_000)),
        )

    async def start(self, round_id: str, url: str) -> None:
        await self.stop()
        self.round_id = round_id
        self.url = url
        self.room_id = self.resolve_room_id(url)
        self.fingerprints.clear()
        self.stop_event = asyncio.Event()
        self.task = asyncio.create_task(self._run_forever(), name=f"mgtv-collector-{round_id}")

    async def stop(self) -> None:
        if not self.task:
            return
        self.stop_event.set()
        try:
            await asyncio.wait_for(self.task, timeout=10)
        except asyncio.TimeoutError:
            self.task.cancel()
        finally:
            self.task = None

    def fingerprint(self, raw: dict[str, Any]) -> str:
        message_id = raw.get("message_id") or raw.get("messageId") or raw.get("msg_id") or raw.get("mid") or raw.get("id")
        if message_id:
            return f"id:{normalize(message_id)}"
        # The public history endpoint currently has no stable message id/cursor.
        # User id + nickname + content gives us a useful anti-dup/anti-spam key.
        key = f"{normalize(raw.get('user_id', raw.get('u', '')))}\n{normalize(raw.get('nickname', raw.get('n', '')))}\n{normalize(raw.get('content', raw.get('c', '')))}"
        return "sha1:" + hashlib.sha1(key.encode("utf-8")).hexdigest()

    def resolve_room_id(self, url: str) -> str:
        flag = self.config.get("flag", "liveshow")
        explicit = self.config.get("room_id")
        if explicit:
            return explicit
        camera_id = self.config.get("camera_id")
        if not camera_id:
            match = re.search(r"/z/[^/]+/([^/?#]+)", url)
            if match:
                camera_id = match.group(1).removesuffix(".html")
        if not camera_id:
            raise ValueError("无法从直播 URL 解析 cameraId，请在配置中设置 mgtv.camera_id 或 mgtv.room_id")
        return f"{flag}-{camera_id}"

    async def _run_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self._run_once()
            except Exception as exc:  # noqa: BLE001 - collector must self-heal
                print(f"[collector] reconnect after error: {exc}", flush=True)
                reconnect_seconds = float(self.config.get("reconnect_seconds", 5))
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=reconnect_seconds)
                except asyncio.TimeoutError:
                    pass

    async def _run_once(self) -> None:
        assert self.url and self.round_id and self.room_id
        count_initial = bool(self.config.get("count_initial_history", False))
        first_batch = True
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome Safari/537.36",
            "Referer": "https://www.mgtv.com/",
            "Origin": "https://www.mgtv.com",
        }
        async with ClientSession(headers=headers) as session:
            while not self.stop_event.is_set():
                api = self.config.get("history_api", "https://lb.bz.mgtv.com/get_history")
                async with session.get(api, params={"room_id": self.room_id}, timeout=10) as response:
                    if response.status != 200:
                        raise RuntimeError(f"history api HTTP {response.status}: {await response.text()}")
                    payload = await response.json(content_type=None)
                if isinstance(payload, dict) and payload.get("code") not in (None, 0, 200):
                    raise RuntimeError(f"history api code={payload.get('code')}: {payload.get('msg')}")
                items = self.extract_history_items(payload)
                # Oldest first makes the local JSONL easier to audit.
                for item in reversed(items):
                    raw = {
                        "ts": now_iso(),
                        "message_id": item.get("messageId") or item.get("message_id") or item.get("msg_id") or item.get("mid") or item.get("id") or "",
                        "user_id": item.get("u", ""),
                        "nickname": item.get("n", ""),
                        "content": item.get("c") or item.get("tp") or "",
                        "url": self.url,
                    }
                    if self.fingerprints.seen_or_add(self.fingerprint(raw)):
                        continue
                    if first_batch and not count_initial:
                        continue
                    await self.engine.ingest(self.round_id, raw)
                first_batch = False
                poll_seconds = float(self.config.get("poll_seconds", 2.0))
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=poll_seconds)
                except asyncio.TimeoutError:
                    pass

    def extract_history_items(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            merged: list[dict[str, Any]] = []
            for key in ("barrage", "backBarrage", "list", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    merged.extend(item for item in value if isinstance(item, dict))
            return merged
        return []


class FeishuBot:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.token: str | None = None
        self.token_expire_at = 0.0
        self.token_lock = asyncio.Lock()
        self.api_base = str(config.get("api_base_url") or "https://open.feishu.cn").rstrip("/")

    def enabled(self) -> bool:
        return bool(self.config.get("enabled"))

    async def tenant_token(self) -> str:
        async with self.token_lock:
            if self.token and time.time() < self.token_expire_at - 60:
                return self.token
            async with ClientSession() as session:
                async with session.post(
                    f"{self.api_base}/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": self.config["app_id"], "app_secret": self.config["app_secret"]},
                ) as response:
                    data = await response.json()
            if data.get("code") != 0:
                raise RuntimeError(f"飞书 token 获取失败：{data}")
            self.token = data["tenant_access_token"]
            self.token_expire_at = time.time() + int(data.get("expire", 7200))
            return self.token

    def is_allowed(self, open_id: str, chat_id: str = "") -> bool:
        users = self.config.get("allowed_open_ids") or []
        chats = self.config.get("allowed_chat_ids") or []
        if isinstance(users, str):
            users = [item.strip() for item in users.split(",") if item.strip()]
        if isinstance(chats, str):
            chats = [item.strip() for item in chats.split(",") if item.strip()]
        if not users and not chats:
            return True
        if users and "*" not in users and open_id not in users:
            return False
        if chat_id:
            return not chats or "*" in chats or chat_id in chats
        return not chats

    async def send_message(self, receive_id: str, receive_id_type: str, msg_type: str, content: dict[str, Any]) -> None:
        if not self.enabled() or not receive_id:
            return
        token = await self.tenant_token()
        async with ClientSession(headers={"Authorization": f"Bearer {token}"}) as session:
            async with session.post(
                f"{self.api_base}/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                json={"receive_id": receive_id, "msg_type": msg_type, "content": json.dumps(content, ensure_ascii=False)},
            ) as response:
                data = await response.json(content_type=None)
        if response.status not in (200, 201) or data.get("code") != 0:
            raise RuntimeError(f"飞书消息发送失败：HTTP {response.status} {data}")

    async def send_text(self, open_id: str, text: str) -> None:
        await self.send_message(open_id, "open_id", "text", {"text": text})

    async def send_card(self, receive_id: str, receive_id_type: str, card: dict[str, Any]) -> None:
        await self.send_message(receive_id, receive_id_type, "interactive", card)


class VoteService:
    def __init__(self, config: dict[str, Any], config_path: Path | None = None, repo_root: Path | None = None):
        self.config = config
        self.startup_config = json.loads(json.dumps(config))
        self.config_path = config_path
        self.repo_root = repo_root or Path(__file__).resolve().parents[1]
        self.config_lock = asyncio.Lock()
        self.update_lock = asyncio.Lock()
        self.last_update_result: dict[str, Any] | None = None
        self.last_update_status: dict[str, Any] | None = None
        self.update_task: asyncio.Task[Any] | None = None
        self.update_progress: dict[str, Any] = self._initial_update_progress()
        self.feishu_binding_task: asyncio.Task[Any] | None = None
        self.feishu_binding_state: dict[str, Any] = self._initial_feishu_binding_state()
        self.pending_restart_fields: list[str] = []
        self.store = StateStore(Path(config.get("storage", {}).get("directory", "server/data")))
        self.store.load()
        self.engine = VoteEngine(self.store)
        self.publisher = GithubPublisher(config.get("github", {}), self.store)
        self.collector = MgtvCollector(config.get("mgtv", {}), self.engine)
        self.feishu = FeishuBot(config.get("feishu", {}))
        self.operator_auth = OperatorAuth(config.get("operator_auth") or {})
        self.default_candidates = candidates_from_config(config.get("vote", {}).get("candidates", []))
        self.default_policy = config.get("vote", {}).get("multi_candidate_policy", "all")
        self.user_selection: dict[str, str] = {}
        self.feishu_connection: Any = None
        self.updater = GitUpdater(self.repo_root)

    def _initial_feishu_binding_state(self) -> dict[str, Any]:
        return {
            "status": "idle",
            "message": "",
            "error": "",
            "userCode": "",
            "verificationUrl": "",
            "expiresAt": 0,
            "boundAt": "",
            "openId": "",
            "tenantBrand": "",
            "warning": "",
            "deviceCode": "",
            "interval": 5,
            "accountsBase": feishu_binding.ACCOUNTS_FEISHU,
        }

    def _set_feishu_binding_state(self, **updates: Any) -> None:
        state = dict(self.feishu_binding_state or self._initial_feishu_binding_state())
        state.update(updates)
        self.feishu_binding_state = state

    def feishu_binding_view(self) -> dict[str, Any]:
        feishu_config = self.config.get("feishu") or {}
        state = dict(self.feishu_binding_state or self._initial_feishu_binding_state())
        state.pop("deviceCode", None)
        state.pop("accountsBase", None)
        if state.get("status") == "idle" and has_real_value(feishu_config.get("app_id")) and has_real_value(feishu_config.get("app_secret")):
            state["status"] = "bound"
            state["message"] = "飞书应用凭据已配置。"
        feishu_thread = getattr(self.feishu_connection, "thread", None)
        state.update({
            "enabled": bool(feishu_config.get("enabled")),
            "connectionMode": feishu_config.get("connection_mode", "websocket"),
            "appId": str(feishu_config.get("app_id") or ""),
            "appSecretConfigured": has_real_value(feishu_config.get("app_secret")),
            "allowedOpenIds": list(feishu_config.get("allowed_open_ids") or []),
            "allowedChatIds": list(feishu_config.get("allowed_chat_ids") or []),
            "workerAlive": bool(feishu_thread and feishu_thread.is_alive()),
        })
        return state

    def _initial_update_progress(self) -> dict[str, Any]:
        return {
            "status": "idle",
            "stage": "idle",
            "percent": 0,
            "detail": "尚未开始升级。",
            "speed": "",
            "updatedAt": "",
            "logs": [],
            "restartScheduled": False,
        }

    def _set_update_progress(self, event: dict[str, Any]) -> None:
        current = dict(self.update_progress or self._initial_update_progress())
        current["status"] = event.get("status", current.get("status") or "running")
        current["stage"] = event.get("stage", current.get("stage") or "running")
        if "percent" in event:
            current["percent"] = max(0, min(100, int(event["percent"])))
        if event.get("detail"):
            current["detail"] = str(event["detail"])
        if "speed" in event:
            current["speed"] = str(event.get("speed") or "")
        if "restartScheduled" in event:
            current["restartScheduled"] = bool(event["restartScheduled"])
        current["updatedAt"] = now_iso()
        logs = list(current.get("logs") or [])
        detail = str(current.get("detail") or "")
        if detail and (not logs or logs[-1] != detail):
            logs.append(detail)
            logs = logs[-8:]
        current["logs"] = logs
        self.update_progress = current

    def _restart_fields_for(self, config: dict[str, Any]) -> list[str]:
        paths = [
            ("listen.host", "listen", "host"),
            ("listen.port", "listen", "port"),
            ("storage.directory", "storage", "directory"),
            ("mgtv.dedup_db_path", "mgtv", "dedup_db_path"),
        ]
        return [
            label
            for label, group, key in paths
            if (self.startup_config.get(group) or {}).get(key) != (config.get(group) or {}).get(key)
        ]

    def settings_runtime(self) -> dict[str, Any]:
        feishu_thread = getattr(self.feishu_connection, "thread", None)
        return {
            "activeRoundId": self.store.active_round_id,
            "collectorRunning": self.collector.running(),
            "feishuWorkerAlive": bool(feishu_thread and feishu_thread.is_alive()),
            "restartRequired": bool(self.pending_restart_fields),
            "restartFields": self.pending_restart_fields,
            "configPath": str(self.config_path) if self.config_path else "",
        }

    def settings_view(self) -> dict[str, Any]:
        return public_settings(self.config, self.settings_runtime())

    async def start_feishu_binding(self, loop: asyncio.AbstractEventLoop) -> dict[str, Any]:
        if self.config_path is None:
            raise RuntimeError("当前服务未指定可写配置文件，无法保存飞书绑定结果")
        task = self.feishu_binding_task
        if task is not None and not task.done() and self.feishu_binding_state.get("status") == "pending":
            return self.feishu_binding_view()
        timeout = ClientTimeout(total=20, connect=8, sock_read=12)
        async with ClientSession(timeout=timeout) as session:
            started = await feishu_binding.begin_binding(session)
        self._set_feishu_binding_state(
            status="pending",
            message="请在飞书授权页面完成绑定，完成后本页会自动刷新。",
            error="",
            warning="",
            userCode=started.user_code,
            verificationUrl=started.verification_url,
            expiresAt=started.expires_at,
            boundAt="",
            openId="",
            tenantBrand="",
            deviceCode=started.device_code,
            interval=started.interval,
            accountsBase=started.accounts_base,
        )
        self.feishu_binding_task = loop.create_task(
            self._run_feishu_binding_poll(loop, started.device_code, started.expires_at, started.interval, started.accounts_base)
        )
        return self.feishu_binding_view()

    async def _run_feishu_binding_poll(
        self,
        loop: asyncio.AbstractEventLoop,
        device_code: str,
        expires_at: float,
        interval: int,
        accounts_base: str,
    ) -> None:
        try:
            timeout = ClientTimeout(total=20, connect=8, sock_read=12)
            async with ClientSession(timeout=timeout) as session:
                while time.time() < expires_at:
                    await asyncio.sleep(max(1, interval))
                    result = await feishu_binding.poll_binding_once(session, device_code, accounts_base=accounts_base)
                    if result is None:
                        continue
                    warning = await self._complete_feishu_binding(result, loop)
                    self._set_feishu_binding_state(
                        status="bound",
                        message="飞书绑定完成，配置已保存并热重载。",
                        error="",
                        warning=warning,
                        boundAt=now_iso(),
                        openId=result.open_id,
                        tenantBrand=result.tenant_brand,
                        verificationUrl="",
                        userCode="",
                        expiresAt=0,
                        deviceCode="",
                    )
                    return
            self._set_feishu_binding_state(
                status="expired",
                message="飞书绑定链接已过期，请重新发起绑定。",
                error="",
                verificationUrl="",
                userCode="",
                expiresAt=0,
                deviceCode="",
            )
        except feishu_binding.FeishuBindingError as exc:
            self._set_feishu_binding_state(
                status="failed",
                message="飞书绑定失败。",
                error=str(exc),
                verificationUrl="",
                userCode="",
                expiresAt=0,
                deviceCode="",
            )
        except (asyncio.TimeoutError, ClientError) as exc:
            self._set_feishu_binding_state(
                status="failed",
                message="飞书绑定失败。",
                error=f"连接飞书授权服务超时或失败：{exc}",
                verificationUrl="",
                userCode="",
                expiresAt=0,
                deviceCode="",
            )
        except Exception as exc:
            self._set_feishu_binding_state(
                status="failed",
                message="飞书绑定失败。",
                error=str(exc),
                verificationUrl="",
                userCode="",
                expiresAt=0,
                deviceCode="",
            )

    async def _complete_feishu_binding(self, result: Any, loop: asyncio.AbstractEventLoop) -> str:
        if self.config_path is None:
            raise RuntimeError("当前服务未指定可写配置文件，无法保存飞书绑定结果")
        warning = ""
        async with self.config_lock:
            new_config = copy.deepcopy(self.config)
            feishu_config = dict(new_config.get("feishu") or {})
            open_ids = list(feishu_config.get("allowed_open_ids") or [])
            if result.open_id and "*" not in open_ids and result.open_id not in open_ids:
                open_ids.append(result.open_id)
            public_url = str(feishu_config.get("public_results_url") or "").strip()
            if not public_url:
                public_url = str((new_config.get("listen") or {}).get("public_base_url") or "").strip()
            feishu_config.update({
                "enabled": True,
                "connection_mode": "websocket",
                "app_id": result.app_id,
                "app_secret": result.app_secret,
                "allowed_open_ids": open_ids,
                "public_results_url": public_url,
            })
            feishu_config.setdefault("allowed_chat_ids", list(feishu_config.get("allowed_chat_ids") or []))
            new_config["feishu"] = feishu_config
            save_config_atomic(self.config_path, new_config)
            self.config = new_config
            self.feishu = FeishuBot(feishu_config)
            try:
                started = await self.reload_feishu_connection(loop)
                if not started:
                    warning = "配置已保存，但飞书长连接未启动；请检查连接模式和依赖。"
            except Exception as exc:
                warning = f"配置已保存，但飞书长连接启动失败：{exc}"
            self.pending_restart_fields = self._restart_fields_for(new_config)
        return warning

    async def apply_settings(self, payload: dict[str, Any], loop: asyncio.AbstractEventLoop) -> dict[str, Any]:
        if self.config_path is None:
            raise RuntimeError("当前服务未指定可写配置文件，无法在线保存")
        async with self.config_lock:
            update = build_settings_update(
                self.config,
                payload,
                active_round=bool(self.store.active_round_id),
            )
            old_config = self.config
            new_config = update.config
            save_config_atomic(self.config_path, new_config)

            self.config = new_config
            self.default_candidates = candidates_from_config(new_config.get("vote", {}).get("candidates", []))
            self.default_policy = new_config.get("vote", {}).get("multi_candidate_policy", "all")
            self.publisher.config = new_config.get("github", {})

            runtime_mgtv = dict(new_config.get("mgtv", {}))
            old_db_path = (self.startup_config.get("mgtv") or {}).get(
                "dedup_db_path",
                "server/data/fingerprints.sqlite3",
            )
            if "mgtv.dedup_db_path" in self._restart_fields_for(new_config):
                runtime_mgtv["dedup_db_path"] = old_db_path
            self.collector.apply_config(runtime_mgtv)

            old_feishu = old_config.get("feishu") or {}
            new_feishu = new_config.get("feishu") or {}
            if old_feishu != new_feishu:
                self.feishu = FeishuBot(new_feishu)
                await self.reload_feishu_connection(loop)

            self.operator_auth = OperatorAuth(new_config.get("operator_auth") or {})
            self.pending_restart_fields = self._restart_fields_for(new_config)
            return {
                "ok": True,
                "warnings": update.warnings,
                "restartRequired": bool(self.pending_restart_fields),
                "restartFields": self.pending_restart_fields,
                "reauthRequired": update.reauth_required,
                "settings": self.settings_view(),
            }

    def request_safe_restart(self, loop: asyncio.AbstractEventLoop) -> list[str]:
        if self.store.active_round_id or self.collector.running():
            raise SettingsValidationError("场次正在采集，必须先结束本轮才能重启服务")
        if not self.pending_restart_fields:
            raise SettingsValidationError("当前没有需要重启生效的配置")
        fields = list(self.pending_restart_fields)
        loop.call_later(0.8, os.kill, os.getpid(), signal.SIGTERM)
        return fields

    def update_blockers(self) -> list[str]:
        blockers: list[str] = []
        if self.store.active_round_id or self.collector.running():
            blockers.append("场次正在采集，需先结束本轮")
        if self.update_lock.locked() or (self.update_task is not None and not self.update_task.done()):
            blockers.append("已有升级任务正在执行")
        return blockers

    async def update_status(self) -> dict[str, Any]:
        in_progress = self.update_task is not None and not self.update_task.done()
        if in_progress and self.last_update_status is not None:
            status = dict(self.last_update_status)
        else:
            status = await self.updater.status()
            self.last_update_status = dict(status)
        blockers = self.update_blockers()
        if status.get("dirty") and not in_progress:
            blockers.append("部署目录存在未提交或未跟踪文件")
        status.update({
            "inProgress": in_progress,
            "canApply": bool(status.get("updateAvailable")) and not blockers,
            "blockers": blockers,
            "restartWillApplyConfig": bool(self.pending_restart_fields),
            "lastUpdate": self.last_update_result,
            "progress": self.update_progress,
        })
        return status

    async def apply_update(self, loop: asyncio.AbstractEventLoop) -> dict[str, Any]:
        blockers = self.update_blockers()
        if blockers:
            raise SettingsValidationError("；".join(blockers))
        status = await self.updater.status()
        self.last_update_status = dict(status)
        if status.get("dirty"):
            raise SettingsValidationError("部署目录存在未提交或未跟踪文件，已拒绝自动升级")
        self.update_progress = self._initial_update_progress()
        self._set_update_progress({
            "status": "running",
            "stage": "queued",
            "percent": 1,
            "detail": "升级任务已启动，正在排队执行……",
        })
        self.update_task = loop.create_task(self._run_update_task(loop))
        return {
            "ok": True,
            "started": True,
            "message": "升级任务已启动。",
            "progress": self.update_progress,
        }

    async def _run_update_task(self, loop: asyncio.AbstractEventLoop) -> None:
        async with self.update_lock:
            try:
                result = await self.updater.apply_update(progress=self._set_update_progress)
                self.last_update_result = {
                    "updated": result.get("updated"),
                    "from": result.get("from"),
                    "to": result.get("to"),
                    "steps": result.get("steps", []),
                    "requestedAt": now_iso(),
                }
                if result.get("updated"):
                    self._set_update_progress({
                        "status": "complete",
                        "stage": "restart",
                        "percent": 100,
                        "detail": "升级完成，服务正在自动重启……",
                        "speed": "",
                        "restartScheduled": True,
                    })
                    loop.call_later(0.8, os.kill, os.getpid(), signal.SIGTERM)
                else:
                    self._set_update_progress({
                        "status": "complete",
                        "stage": "complete",
                        "percent": 100,
                        "detail": "当前已经是最新版本，无需重启。",
                        "speed": "",
                    })
            except Exception as exc:
                self.last_update_result = {
                    "updated": False,
                    "error": str(exc),
                    "requestedAt": now_iso(),
                }
                self._set_update_progress({
                    "status": "failed",
                    "stage": "failed",
                    "percent": self.update_progress.get("percent", 0),
                    "detail": str(exc),
                    "speed": "",
                })

    def start_feishu_connection(self, loop: asyncio.AbstractEventLoop) -> bool:
        try:
            from server.feishu_ws import FeishuLongConnection
        except ModuleNotFoundError:
            from feishu_ws import FeishuLongConnection

        self.feishu_connection = FeishuLongConnection(self.config.get("feishu", {}), self)
        return self.feishu_connection.start(loop)

    async def reload_feishu_connection(self, loop: asyncio.AbstractEventLoop) -> bool:
        if self.feishu_connection is not None:
            await asyncio.to_thread(self.feishu_connection.stop)
        return self.start_feishu_connection(loop)

    def feishu_card(self, open_id: str, notice: str = "") -> dict[str, Any]:
        public_url = str(self.config.get("feishu", {}).get("public_results_url") or "")
        return build_control_card(self.store.public_state(), self.user_selection.get(open_id), notice, public_url)

    async def handle_feishu_text(
        self,
        text: str,
        open_id: str,
        chat_id: str,
        receive_id: str,
        receive_id_type: str,
    ) -> None:
        if not self.feishu.is_allowed(open_id, chat_id):
            await self.feishu.send_card(receive_id, receive_id_type, build_control_card(self.store.public_state(), notice="无操作权限。"))
            return
        normalized = normalize(text)
        if normalized in {"菜单", "卡片", "控制台", "/menu"}:
            reply = "控制台已刷新。"
        elif normalized in {"我的id", "我的ID", "配置id", "配置ID", "id", "ids", "/id"}:
            reply = (
                "当前飞书来源 ID：\n"
                f"open_id: {open_id or '未获取到'}\n"
                f"chat_id: {chat_id or '私聊无群 ID'}\n"
                "把这些值填入 server/config.json 的 allowed_open_ids / allowed_chat_ids，"
                "或重新运行 python tools/setup_feishu_bot.py 选择“正式使用”。"
            )
        else:
            reply = await self.handle_command(normalized, open_id)
        await self.feishu.send_card(receive_id, receive_id_type, self.feishu_card(open_id, reply))

    async def handle_feishu_card_action(self, action: str, open_id: str, chat_id: str, option: str = "") -> dict[str, Any]:
        if not self.feishu.is_allowed(open_id, chat_id):
            return build_control_card(self.store.public_state(), notice="无操作权限。")
        notice = "状态已刷新。"
        try:
            if action == "show_rounds":
                return build_round_list_card(self.store.public_state(), self.user_selection.get(open_id))
            if action == "control":
                return self.feishu_card(open_id)
            if action == "select_round":
                meta = self.store.find_round(option)
                if not meta:
                    notice = "找不到所选场次。"
                else:
                    self.user_selection[open_id] = meta.id
                    notice = f"已切换到：{meta.name}"
            elif action == "start_default":
                if self.store.active_round_id:
                    notice = "已有场次正在采集，请先结束本轮。"
                else:
                    name = f"第 {len(self.store.round_order) + 1} 轮"
                    meta = await self.start_round(name)
                    self.user_selection[open_id] = meta.id
                    notice = f"已开始：{meta.activity} / {meta.name}"
            elif action == "end_round":
                meta = await self.end_round(publish=True)
                notice = "当前没有进行中的场次。" if not meta else f"已结束并发布粗略结果：{meta.name}"
                if meta:
                    self.user_selection[open_id] = meta.id
            elif action == "publish_rough":
                url = await self.publisher.publish(force=True, result_kind="rough")
                notice = f"粗略结果发布完成：{url}"
            elif action != "refresh":
                notice = "未识别的卡片操作。"
        except Exception as exc:
            notice = f"操作失败：{exc}"
        return self.feishu_card(open_id, notice)

    async def start_round(self, name: str, url: str | None = None, activity: str | None = None) -> RoundMeta:
        if self.store.active_round_id:
            await self.end_round(publish=True)
        url = url or self.config.get("mgtv", {}).get("url")
        activity = activity or self.config.get("vote", {}).get("activity") or "未分类活动"
        meta = await self.store.create_round(activity, name, url, self.default_candidates, self.default_policy)
        await self.collector.start(meta.id, url)
        return meta

    async def end_round(self, publish: bool = True) -> RoundMeta | None:
        await self.collector.stop()
        meta = await self.store.stop_active()
        if publish and meta:
            await self.publisher.publish(force=True, result_kind="rough")
        return meta

    async def publish_precise_file(self, round_id: str, filename: str, content: bytes) -> tuple[RoundMeta, str]:
        if not content:
            raise ValueError("上传文件为空")
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("精确结果文件不能超过 2 MB")
        meta = self.store.require_round(round_id)
        payload = parse_precise_result(filename, content)
        result = validate_precise_result(payload, meta, content, filename)
        meta = await self.store.set_precise_result(round_id, result)
        url = await self.publisher.publish(force=True, result_kind="precise")
        return meta, url

    def result_text(self, meta: RoundMeta | None = None) -> str:
        meta = meta or self.store.find_round(None)
        if not meta:
            return "暂无场次。"
        result_label = "精确结果" if meta.preciseResult else "粗略结果"
        counts = meta.preciseResult.get("voteCounts", {}) if meta.preciseResult else meta.voteCounts
        rows = sorted(
            ((candidate.name, counts.get(candidate.id, 0)) for candidate in meta.candidates),
            key=lambda row: (-row[1], row[0]),
        )
        lines = [f"【{meta.activity} / {meta.name}】{meta.status} · {result_label}", f"弹幕样本：{meta.messageCount}，语义待审：{meta.reviewCount}"]
        lines.extend(f"{index}. {name}：{count}" for index, (name, count) in enumerate(rows, 1))
        return "\n".join(lines)

    def round_list_text(self) -> str:
        if not self.store.round_order:
            return "暂无场次。"
        lines = ["场次列表："]
        for index, round_id in enumerate(self.store.round_order, 1):
            meta = self.store.rounds[round_id]
            marker = "●" if meta.status == "running" else " "
            lines.append(f"{index}. {marker} {meta.activity} / {meta.name}｜{meta.id}｜样本 {meta.messageCount}")
        return "\n".join(lines)

    async def handle_command(self, text: str, open_id: str = "") -> str:
        text = normalize(text)
        if not text or text in {"帮助", "help", "/help"}:
            return (
                "请直接使用卡片按钮操作。常用流程：开始默认场次 → 结束并发布粗略结果 → 在 WebUI 上传精确结果。"
            )
        if text.startswith("开始"):
            rest = normalize(text[2:])
            if not rest:
                rest = f"第 {len(self.store.round_order) + 1} 轮"
            parts = rest.split()
            url = next((part for part in parts if part.startswith("http://") or part.startswith("https://")), None)
            label = normalize(rest.replace(url or "", "")) or f"第 {len(self.store.round_order) + 1} 轮"
            if "|" in label:
                activity, name = (normalize(part) for part in label.split("|", 1))
            else:
                activity = self.config.get("vote", {}).get("activity") or "未分类活动"
                name = label
            meta = await self.start_round(name, url, activity)
            self.user_selection[open_id] = meta.id
            return f"已开始：{meta.activity} / {meta.name}\n{meta.pageUrl}"
        if text == "结束":
            meta = await self.end_round(publish=True)
            return "没有正在进行的场次。" if not meta else f"已结束并发布：\n{self.result_text(meta)}"
        if text == "状态":
            active = self.store.rounds.get(self.store.active_round_id or "")
            return f"采集器：{'运行中' if self.collector.running() else '未运行'}\n{self.result_text(active)}"
        if text.startswith("结果"):
            query = normalize(text[2:])
            meta = self.store.find_round(query) if query else self.store.find_round(self.user_selection.get(open_id))
            return self.result_text(meta)
        if text == "场次":
            return self.round_list_text()
        if text.startswith("切换"):
            query = normalize(text[2:])
            meta = self.store.find_round(query)
            if not meta:
                return f"找不到场次：{query}"
            self.user_selection[open_id] = meta.id
            return f"已切换查看：\n{self.result_text(meta)}"
        if text.startswith("命名"):
            name = normalize(text[2:])
            if not name:
                return "请发送：命名 <新名称>"
            target_id = self.user_selection.get(open_id) or self.store.active_round_id or (self.store.round_order[0] if self.store.round_order else "")
            meta = await self.store.rename_round(target_id, name)
            await self.publisher.publish(force=True, result_kind="rough")
            return f"已重命名：{meta.name}"
        if text in {"发布", "发布粗略"}:
            url = await self.publisher.publish(force=True, result_kind="rough")
            return f"粗略结果发布完成：{url}"
        if text == "候选人":
            return "\n".join(f"{candidate.name}：{', '.join(candidate.aliases)}" for candidate in self.default_candidates)
        return "已为你刷新控制台。请直接点击卡片按钮操作。"


def _safe_static_version(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "-", str(value or "").strip()).strip("-._")
    return text or f"runtime-{int(time.time())}"


def _git_dir_for(repo_root: Path) -> Path:
    git_path = repo_root / ".git"
    if git_path.is_dir():
        return git_path
    try:
        content = git_path.read_text(encoding="utf-8").strip()
    except OSError:
        return git_path
    if content.startswith("gitdir:"):
        target = Path(content.split(":", 1)[1].strip())
        return target if target.is_absolute() else (repo_root / target).resolve()
    return git_path


def static_asset_version(repo_root: Path) -> str:
    configured = os.environ.get("MGTV_STATIC_VERSION")
    if configured:
        return _safe_static_version(configured)
    git_dir = _git_dir_for(repo_root)
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            ref_path = git_dir / ref
            if ref_path.exists():
                commit = ref_path.read_text(encoding="utf-8").strip()
            else:
                commit = ""
                for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
                    if line and not line.startswith("#"):
                        parts = line.split(" ", 1)
                        if len(parts) == 2 and parts[1] == ref:
                            commit = parts[0]
                            break
        else:
            commit = head
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
            return commit[:12].lower()
    except OSError:
        pass
    return f"runtime-{int(time.time())}-{secrets.token_hex(4)}"


def create_app(service: VoteService) -> web.Application:
    webui_dir = Path(__file__).with_name("webui")
    precise_doc = Path(__file__).resolve().parents[1] / "docs" / "PRECISE_RESULT_AGENT.md"
    index_template = (webui_dir / "index.html").read_text(encoding="utf-8")
    login_template = (webui_dir / "login.html").read_text(encoding="utf-8")
    version_root = getattr(service, "repo_root", Path(__file__).resolve().parents[1])
    static_version = static_asset_version(Path(version_root))

    def render_static_version(template: str) -> str:
        return template.replace("{{STATIC_VERSION}}", html.escape(static_version, quote=True))

    @web.middleware
    async def security_headers(request: web.Request, handler: Any) -> web.StreamResponse:
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            exc.headers.setdefault("X-Content-Type-Options", "nosniff")
            exc.headers.setdefault("X-Frame-Options", "DENY")
            exc.headers.setdefault("Referrer-Policy", "no-referrer")
            exc.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
                "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            raise
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        return response

    @web.middleware
    async def operator_auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        auth = service.operator_auth
        if not auth.enabled:
            return await handler(request)
        public_paths = {"/login", "/auth/login", "/healthz", "/feishu/events", "/webui/styles.css"}
        if request.path in public_paths or auth.request_is_authenticated(request):
            return await handler(request)
        if request.path.startswith("/api/"):
            return web.json_response({"error": "登录已过期，请重新登录"}, status=401, headers={"Cache-Control": "no-store"})
        next_url = quote(str(request.rel_url), safe="")
        raise web.HTTPFound(location=f"/login?next={next_url}")

    app = web.Application(
        client_max_size=3 * 1024 * 1024,
        middlewares=[security_headers, operator_auth_middleware],
    )

    def login_response(error: str = "", next_url: str = "/", status: int = 200) -> web.Response:
        safe_next = safe_next_url(next_url)
        error_block = f'<p class="auth-error" role="alert">{html.escape(error)}</p>' if error else ""
        body = (
            render_static_version(login_template)
            .replace("{{NEXT_URL}}", html.escape(safe_next, quote=True))
            .replace("{{ERROR_BLOCK}}", error_block)
        )
        return web.Response(
            text=body,
            content_type="text/html",
            status=status,
            headers={"Cache-Control": "no-store"},
        )

    async def webui_index(_: web.Request) -> web.Response:
        auth_control = ""
        if service.operator_auth.enabled:
            auth_control = (
                '<form class="logout-form" action="/auth/logout" method="post">'
                '<button class="logout-button" type="submit">退出登录</button>'
                "</form>"
            )
        body = (
            render_static_version(index_template)
            .replace("<!-- OPERATOR_AUTH_CONTROL -->", auth_control)
        )
        return web.Response(text=body, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def login_page(request: web.Request) -> web.StreamResponse:
        auth = service.operator_auth
        next_url = safe_next_url(request.query.get("next"))
        if not auth.enabled:
            raise web.HTTPFound(location="/")
        if auth.request_is_authenticated(request):
            raise web.HTTPFound(location=next_url)
        return login_response(next_url=next_url)

    async def login_submit(request: web.Request) -> web.StreamResponse:
        auth = service.operator_auth
        if not auth.enabled:
            raise web.HTTPFound(location="/")
        data = await request.post()
        next_url = safe_next_url(str(data.get("next") or "/"))
        client_key = request.remote or "unknown"
        if auth.is_rate_limited(client_key):
            return login_response("尝试次数过多，请稍后再试。", next_url, status=429)
        password = str(data.get("password") or "")
        if not auth.verify_password(password):
            auth.record_failure(client_key)
            return login_response("密码错误，请重试。", next_url, status=401)
        auth.clear_failures(client_key)
        response = web.HTTPSeeOther(location=next_url)
        auth.set_session_cookie(response)
        raise response

    async def logout(_: web.Request) -> web.StreamResponse:
        response = web.HTTPSeeOther(location="/login")
        service.operator_auth.clear_session_cookie(response)
        raise response

    async def health(_: web.Request) -> web.Response:
        runtime = service.settings_runtime()
        return web.json_response({
            "ok": True,
            "collectorRunning": service.collector.running(),
            "activeRoundId": service.store.active_round_id,
            "feishuEnabled": service.feishu.enabled(),
            "feishuConnectionMode": service.config.get("feishu", {}).get("connection_mode", "websocket"),
            "feishuWorkerAlive": runtime["feishuWorkerAlive"],
            "restartRequired": runtime["restartRequired"],
            "restartFields": runtime["restartFields"],
        })

    async def get_settings(_: web.Request) -> web.Response:
        return web.json_response(
            service.settings_view(),
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def update_settings(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            result = await service.apply_settings(payload, asyncio.get_running_loop())
        except SettingsValidationError as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except (OSError, RuntimeError) as exc:
            return web.json_response({"error": str(exc)}, status=500, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            result,
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def get_feishu_binding(_: web.Request) -> web.Response:
        return web.json_response(
            service.feishu_binding_view(),
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def start_feishu_binding(_: web.Request) -> web.Response:
        try:
            result = await service.start_feishu_binding(asyncio.get_running_loop())
        except (asyncio.TimeoutError, ClientError) as exc:
            return web.json_response({"error": f"连接飞书授权服务超时或失败：{exc}"}, status=504, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except feishu_binding.FeishuBindingError as exc:
            return web.json_response({"error": str(exc)}, status=502, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except (OSError, RuntimeError) as exc:
            return web.json_response({"error": str(exc)}, status=500, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            result,
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def restart_service(_: web.Request) -> web.Response:
        try:
            fields = service.request_safe_restart(asyncio.get_running_loop())
        except SettingsValidationError as exc:
            return web.json_response({"error": str(exc)}, status=409, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            {"ok": True, "message": "服务正在安全重启", "fields": fields},
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def update_status(_: web.Request) -> web.Response:
        try:
            status = await service.update_status()
        except UpdateError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=502, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            status,
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def apply_update(_: web.Request) -> web.Response:
        try:
            result = await service.apply_update(asyncio.get_running_loop())
        except SettingsValidationError as exc:
            return web.json_response({"error": str(exc)}, status=409, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except UpdateError as exc:
            return web.json_response({"error": str(exc)}, status=502, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            result,
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def precise_result_doc(_: web.Request) -> web.FileResponse:
        return web.FileResponse(precise_doc, headers={"Content-Type": "text/markdown; charset=utf-8"})

    async def results(_: web.Request) -> web.Response:
        return web.json_response(service.store.public_state(), dumps=lambda data: json.dumps(data, ensure_ascii=False))

    async def round_export(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        try:
            body = service.store.export_round_jsonl(round_id)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.Response(
            text=body,
            content_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="mgtv-round-{round_id}.jsonl"'},
        )

    async def command(request: web.Request) -> web.Response:
        data = await request.json()
        reply = await service.handle_command(data.get("text", ""))
        return web.json_response({"reply": reply}, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))

    async def precise_upload(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        try:
            if not request.content_type.startswith("multipart/"):
                raise ValueError("请求必须使用 multipart/form-data")
            reader = await request.multipart()
            field = await reader.next()
            if field is None or field.name != "file" or not field.filename:
                raise ValueError("请通过 file 字段上传 .json 或 .xml 文件")
            content = await field.read(decode=False)
            meta, url = await service.publish_precise_file(round_id, field.filename, content)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except (ValueError, web.HTTPBadRequest) as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=502, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            {"ok": True, "roundId": meta.id, "publishedAt": meta.precisePublishedAt, "publishUrl": url},
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
        )

    async def feishu_events(request: web.Request) -> web.Response:
        body = await request.json()
        token = service.config.get("feishu", {}).get("verification_token")
        supplied_token = body.get("token") or body.get("header", {}).get("token") or body.get("event", {}).get("token")
        if token and supplied_token != token:
            return web.json_response({"error": "invalid token"}, status=403)
        if body.get("type") == "url_verification":
            return web.json_response({"challenge": body.get("challenge")})
        header = body.get("header", {})
        event = body.get("event", {})
        if header.get("event_type") == "card.action.trigger" or body.get("type") == "card.action.trigger":
            action = event.get("action", {})
            value = action.get("value") or {}
            operator = event.get("operator") or {}
            context = event.get("context") or {}
            card = await service.handle_feishu_card_action(
                str(value.get("action") or ""),
                str(operator.get("open_id") or ""),
                str(context.get("open_chat_id") or ""),
                str(action.get("option") or ""),
            )
            return web.json_response({"card": {"type": "raw", "data": card}}, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        if header.get("event_type") not in {"im.message.receive_v1", None}:
            return web.json_response({"ok": True})
        message = event.get("message", {})
        if message.get("message_type") != "text":
            return web.json_response({"ok": True})
        content = json.loads(message.get("content") or "{}")
        text = re.sub(r"@_user_\d+\s*", "", content.get("text", "")).strip()
        open_id = event.get("sender", {}).get("sender_id", {}).get("open_id", "")
        chat_id = message.get("chat_id", "")
        chat_type = message.get("chat_type", "")
        receive_id = chat_id if chat_type == "group" else open_id
        receive_id_type = "chat_id" if chat_type == "group" else "open_id"
        await service.handle_feishu_text(text, open_id, chat_id, receive_id, receive_id_type)
        return web.json_response({"ok": True})

    app.router.add_get("/", webui_index)
    app.router.add_get("/admin", webui_index)
    app.router.add_get("/login", login_page)
    app.router.add_post("/auth/login", login_submit)
    app.router.add_post("/auth/logout", logout)
    app.router.add_get("/webui/index.html", webui_index)
    app.router.add_static("/webui", webui_dir)
    app.router.add_get("/healthz", health)
    app.router.add_get("/docs/precise-result-agent", precise_result_doc)
    app.router.add_get("/api/results.json", results)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_post("/api/settings", update_settings)
    app.router.add_get("/api/feishu/binding", get_feishu_binding)
    app.router.add_post("/api/feishu/binding/start", start_feishu_binding)
    app.router.add_post("/api/restart", restart_service)
    app.router.add_get("/api/update/status", update_status)
    app.router.add_post("/api/update/apply", apply_update)
    app.router.add_get("/api/rounds/{round_id}.jsonl", round_export)
    app.router.add_post("/api/rounds/{round_id}/precise-result", precise_upload)
    app.router.add_post("/api/command", command)
    app.router.add_post("/feishu/events", feishu_events)
    return app


async def amain() -> None:
    parser = argparse.ArgumentParser(description="MGTV server-side danmaku vote collector")
    parser.add_argument("--config", default="server/config.example.json")
    args = parser.parse_args()
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    service = VoteService(config, config_path=config_path)
    feishu_ws_started = service.start_feishu_connection(asyncio.get_running_loop())
    app = create_app(service)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.get("listen", {}).get("host", "0.0.0.0"), int(config.get("listen", {}).get("port", 8080)))
    await site.start()
    print(f"vote server listening on {config.get('listen', {}).get('host', '0.0.0.0')}:{config.get('listen', {}).get('port', 8080)}", flush=True)
    if feishu_ws_started:
        print("feishu bot connected with WebSocket long connection", flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await service.collector.stop()
    if service.feishu_connection is not None:
        await asyncio.to_thread(service.feishu_connection.stop)
    service.collector.fingerprints.close()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
