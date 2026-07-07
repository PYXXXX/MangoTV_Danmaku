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
import platform
import re
import resource
import secrets
import shutil
import signal
import sqlite3
import time
import unicodedata
import copy
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientSession, ClientTimeout, FormData, web

try:
    from server import feishu_binding
    from server.precise_results import parse_precise_result, validate_precise_result
    from server.result_image import render_result_png
    from server.feishu_cards import build_control_card, build_recording_card, build_round_list_card
    from server.mgtv_auth import MgtvAuthManager
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
    from result_image import render_result_png
    from feishu_cards import build_control_card, build_recording_card, build_round_list_card
    from mgtv_auth import MgtvAuthManager
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


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_beijing_range(start: str, end: str) -> str:
    start_dt = parse_iso(start).astimezone(BEIJING_TZ)
    end_dt = parse_iso(end).astimezone(BEIJING_TZ)
    return f"{start_dt:%Y%m%d %H:%M:%S}-{end_dt:%Y%m%d %H:%M:%S}"


def format_beijing_display_range(start: str | None, end: str | None = None) -> str:
    if not start:
        return ""
    start_dt = parse_iso(start).astimezone(BEIJING_TZ)
    if not end:
        return f"{start_dt:%Y/%m/%d %H:%M:%S} 起"
    end_dt = parse_iso(end).astimezone(BEIJING_TZ)
    if start_dt.date() == end_dt.date():
        return f"{start_dt:%Y/%m/%d %H:%M:%S} – {end_dt:%H:%M:%S}"
    return f"{start_dt:%Y/%m/%d %H:%M:%S} – {end_dt:%Y/%m/%d %H:%M:%S}"


def strip_embedded_time_range(name: str, base_name: str) -> str:
    base = normalize(base_name)
    value = normalize(name)
    if not base or not value.startswith(base + " · "):
        return value
    suffix = value[len(base) + 3 :]
    if re.fullmatch(r"\d{8} \d{2}:\d{2}:\d{2}-\d{8} \d{2}:\d{2}:\d{2}", suffix):
        return base
    return value


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
        self.raw_rounds_dir = self.directory / "raw_rounds"
        self.raw_rounds_dir.mkdir(exist_ok=True)
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
            item["name"] = strip_embedded_time_range(item.get("name", ""), item.get("baseName", ""))
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

    async def create_derived_round(
        self,
        *,
        activity: str,
        name: str,
        url: str,
        candidates: list[Candidate],
        policy: str,
        records: list[dict[str, Any]],
        source_round_id: str,
        slice_start_time: str,
        slice_end_time: str,
    ) -> RoundMeta:
        async with self.lock:
            round_id = safe_id()
            base_name = normalize(name) or f"片段分析 {len(self.round_order) + 1}"
            created_at = now_iso()
            seq_values = [int(item.get("seq") or 0) for item in records if int(item.get("seq") or 0) > 0]
            meta = RoundMeta(
                id=round_id,
                activity=normalize(activity) or "未分类活动",
                baseName=base_name,
                name=base_name,
                status="stopped",
                startedAt=slice_start_time,
                updatedAt=created_at,
                stoppedAt=slice_end_time,
                pageUrl=url,
                pageTitle="",
                candidates=candidates,
                multiCandidatePolicy=policy,
                voteCounts={candidate.id: 0 for candidate in candidates},
                sliceStartSeq=min(seq_values) if seq_values else self.global_seq + 1,
                sliceEndSeq=max(seq_values) if seq_values else self.global_seq,
                sliceStartTime=slice_start_time,
                sliceEndTime=slice_end_time,
            )
            output_records = []
            for item in records:
                record = dict(item)
                record["roundId"] = round_id
                record["sourceRoundId"] = source_round_id
                record["sourceSeq"] = item.get("seq")
                record["derivedAt"] = created_at
                for candidate_id in record.get("votes") or []:
                    meta.voteCounts[candidate_id] = meta.voteCounts.get(candidate_id, 0) + 1
                meta.reviewCount += 1 if record.get("needsReview") else 0
                output_records.append(record)
            meta.messageCount = len(output_records)
            self.rounds[round_id] = meta
            self.round_order.insert(0, round_id)
            path = self.rounds_dir / f"{round_id}.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for record in output_records:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
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
            meta.name = meta.baseName
            self.active_round_id = None
            await self.save()
            return meta

    async def rename_round(self, round_id: str, name: str) -> RoundMeta:
        async with self.lock:
            meta = self.require_round(round_id)
            meta.baseName = normalize(name) or meta.baseName
            meta.name = meta.baseName
            if meta.preciseResult:
                meta.preciseResult["sessionName"] = meta.name
            meta.updatedAt = now_iso()
            await self.save()
            return meta

    async def delete_round(self, round_id: str) -> RoundMeta:
        async with self.lock:
            meta = self.require_round(round_id)
            if meta.status == "running" or self.active_round_id == round_id:
                raise ValueError("场次正在采集中，请先结束本轮再删除")
            self.rounds.pop(round_id, None)
            self.round_order = [item for item in self.round_order if item != round_id]
            await self.save()
            round_file = self.rounds_dir / f"{round_id}.jsonl"
            try:
                round_file.unlink()
            except FileNotFoundError:
                pass
            try:
                (self.raw_rounds_dir / f"{round_id}.jsonl").unlink()
            except FileNotFoundError:
                pass
            return meta

    async def delete_activity(self, activity: str) -> list[RoundMeta]:
        target = normalize(activity) or "未分类活动"
        async with self.lock:
            matches = [
                self.rounds[round_id]
                for round_id in self.round_order
                if (self.rounds[round_id].activity or "未分类活动") == target
            ]
            if not matches:
                raise KeyError(f"找不到活动：{target}")
            running = [meta.name for meta in matches if meta.status == "running" or self.active_round_id == meta.id]
            if running:
                raise ValueError(f"活动中仍有场次正在采集，请先结束：{', '.join(running)}")
            match_ids = {meta.id for meta in matches}
            self.rounds = {round_id: meta for round_id, meta in self.rounds.items() if round_id not in match_ids}
            self.round_order = [round_id for round_id in self.round_order if round_id not in match_ids]
            await self.save()
            for round_id in match_ids:
                try:
                    (self.rounds_dir / f"{round_id}.jsonl").unlink()
                except FileNotFoundError:
                    pass
                try:
                    (self.raw_rounds_dir / f"{round_id}.jsonl").unlink()
                except FileNotFoundError:
                    pass
            return matches

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

    async def append_raw_danmaku_batch(
        self,
        round_id: str,
        *,
        poll_seq: int,
        observed_at: str,
        room_id: str,
        url: str,
        items: list[dict[str, Any]],
    ) -> None:
        if not items:
            return
        async with self.lock:
            self.require_round(round_id)
            path = self.raw_rounds_dir / f"{round_id}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                for index, item in enumerate(items):
                    record = {
                        "type": "raw_danmaku",
                        "roundId": round_id,
                        "pollSeq": poll_seq,
                        "itemIndex": index,
                        "observedAt": observed_at,
                        "roomId": room_id,
                        "url": url,
                        "raw": item,
                    }
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def iter_slice_records(self, round_id: str):
        meta = self.require_round(round_id)
        start = meta.sliceStartSeq
        end = meta.sliceEndSeq if meta.sliceEndSeq is not None else self.global_seq
        round_path = self.rounds_dir / f"{round_id}.jsonl"
        path = round_path if round_path.exists() else self.raw_messages_path
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
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

    def iter_round_records_by_time(self, round_id: str, start_time: str, end_time: str):
        start_dt = parse_iso(start_time)
        end_dt = parse_iso(end_time)
        for item in self.iter_slice_records(round_id):
            try:
                ts = parse_iso(str(item.get("ts") or ""))
            except ValueError:
                continue
            if start_dt <= ts <= end_dt:
                yield item

    def iter_raw_round_records_by_time(self, round_id: str, start_time: str, end_time: str):
        start_dt = parse_iso(start_time)
        end_dt = parse_iso(end_time)
        path = self.raw_rounds_dir / f"{round_id}.jsonl"
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    observed = parse_iso(str(item.get("observedAt") or ""))
                except (json.JSONDecodeError, ValueError):
                    continue
                if start_dt <= observed <= end_dt:
                    yield item

    def export_round_jsonl(self, round_id: str) -> str:
        meta = self.require_round(round_id)
        lines = [json.dumps({
            "type": "meta",
            **asdict(meta),
            "displayName": meta.baseName,
            "timeRange": format_beijing_display_range(meta.sliceStartTime, meta.sliceEndTime),
            "compactTimeRange": format_beijing_range(meta.sliceStartTime, meta.sliceEndTime) if meta.sliceEndTime else "",
        }, ensure_ascii=False, separators=(",", ":"))]
        lines.extend(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in self.iter_slice_records(round_id))
        return "\n".join(lines) + "\n"

    def export_round_raw_jsonl(self, round_id: str) -> str:
        meta = self.require_round(round_id)
        lines = [json.dumps({
            "type": "meta",
            **asdict(meta),
            "displayName": meta.baseName,
            "timeRange": format_beijing_display_range(meta.sliceStartTime, meta.sliceEndTime),
            "rawTrack": "observed_api_items",
        }, ensure_ascii=False, separators=(",", ":"))]
        path = self.raw_rounds_dir / f"{round_id}.jsonl"
        if path.exists():
            lines.extend(line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
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
                "displayName": meta.baseName,
                "timeRange": format_beijing_display_range(meta.sliceStartTime, meta.sliceEndTime),
                "compactTimeRange": format_beijing_range(meta.sliceStartTime, meta.sliceEndTime) if meta.sliceEndTime else "",
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
        self.fingerprints = self._new_deduper(config)

    def _dedup_db_path(self, config: dict[str, Any]) -> Path:
        return Path(config.get("dedup_db_path", "server/data/fingerprints.sqlite3"))

    def _new_deduper(self, config: dict[str, Any]) -> PersistentDeduper:
        return PersistentDeduper(
            db_path=self._dedup_db_path(config),
            hot_cache_size=int(config.get("dedup_hot_cache_size", 200_000)),
            max_records=int(config.get("dedup_max_records", 100_000_000)),
        )

    def _sync_deduper_for_config(self) -> None:
        target_path = self._dedup_db_path(self.config)
        if self.fingerprints.db_path == target_path:
            self.fingerprints.reconfigure(
                int(self.config.get("dedup_hot_cache_size", 200_000)),
                int(self.config.get("dedup_max_records", 100_000_000)),
            )
            return
        self.fingerprints.close()
        self.fingerprints = self._new_deduper(self.config)

    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def apply_config(self, config: dict[str, Any]) -> None:
        self.config = config
        if self.running():
            self.fingerprints.reconfigure(
                int(config.get("dedup_hot_cache_size", 200_000)),
                int(config.get("dedup_max_records", 100_000_000)),
            )
        else:
            self._sync_deduper_for_config()

    async def start(self, round_id: str, url: str) -> None:
        await self.stop()
        self._sync_deduper_for_config()
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
        poll_seq = 0
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
                poll_seq += 1
                await self.engine.store.append_raw_danmaku_batch(
                    self.round_id,
                    poll_seq=poll_seq,
                    observed_at=now_iso(),
                    room_id=self.room_id,
                    url=self.url,
                    items=items,
                )
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

    async def upload_image(self, content: bytes, filename: str = "result.png") -> str:
        if not self.enabled():
            return ""
        token = await self.tenant_token()
        form = FormData()
        form.add_field("image_type", "message")
        form.add_field("image", content, filename=filename, content_type="image/png")
        async with ClientSession(headers={"Authorization": f"Bearer {token}"}) as session:
            async with session.post(f"{self.api_base}/open-apis/im/v1/images", data=form) as response:
                data = await response.json(content_type=None)
        if response.status not in (200, 201) or data.get("code") != 0:
            raise RuntimeError(f"飞书图片上传失败：HTTP {response.status} {data}")
        image_key = str(((data.get("data") or {}).get("image_key")) or "")
        if not image_key:
            raise RuntimeError(f"飞书图片上传失败：未返回 image_key")
        return image_key

    async def send_image(self, receive_id: str, receive_id_type: str, content: bytes, filename: str = "result.png") -> None:
        image_key = await self.upload_image(content, filename)
        if image_key:
            await self.send_message(receive_id, receive_id_type, "image", {"image_key": image_key})


class RecordingManager:
    def __init__(self, config: dict[str, Any], storage_dir: Path):
        self.storage_dir = storage_dir
        self.config = config or {}
        self.records: dict[str, dict[str, Any]] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.directory = self._desired_directory(self.config)
        self.meta_path = self.directory / "recordings.json"
        self._switch_directory(self.directory)

    def _desired_directory(self, config: dict[str, Any]) -> Path:
        return Path(config.get("directory") or self.storage_dir / "recordings")

    def _switch_directory(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.directory / "recordings.json"
        self.records = {}
        self.load()

    def _sync_directory_for_config(self) -> None:
        desired = self._desired_directory(self.config)
        if desired != self.directory and not self.processes:
            self._switch_directory(desired)

    def apply_config(self, config: dict[str, Any]) -> None:
        self.config = config or {}
        self._sync_directory_for_config()

    def enabled(self) -> bool:
        return bool(self.config.get("enabled"))

    def ffmpeg_path(self) -> str:
        return str(self.config.get("ffmpeg_path") or shutil.which("ffmpeg") or "ffmpeg")

    def default_source_url(self) -> str:
        return str(self.config.get("stream_url") or self.config.get("source_url") or "")

    def load(self) -> None:
        if not self.meta_path.exists():
            return
        try:
            raw = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        self.records = {item.get("roundId", ""): item for item in raw.get("recordings", []) if item.get("roundId")}
        for item in self.records.values():
            if item.get("status") == "recording":
                item["status"] = "interrupted"
                item["endedAt"] = item.get("endedAt") or now_iso()
        self.save()

    def save(self) -> None:
        payload = {"schemaVersion": 1, "updatedAt": now_iso(), "recordings": list(self.records.values())}
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.meta_path)

    def round_dir(self, round_id: str) -> Path:
        path = self.directory / round_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def record_for(self, round_id: str) -> dict[str, Any] | None:
        return self.records.get(round_id)

    def public_records(self) -> list[dict[str, Any]]:
        records = []
        for record in self.records.values():
            item = dict(record)
            path = Path(str(item.get("path") or ""))
            round_id = quote(str(item.get("roundId") or ""), safe="")
            item["hasVideo"] = path.exists()
            item["videoUrl"] = f"/api/rounds/{round_id}/recording/video" if path.exists() else ""
            clips = []
            for clip in item.get("clips") or []:
                clip_item = dict(clip)
                clip_id = quote(str(clip_item.get("id") or ""), safe="")
                clip_item.setdefault("url", f"/api/rounds/{round_id}/recording/clips/{clip_id}.mp4")
                clip_item["danmakuUrl"] = f"/api/rounds/{round_id}/recording/clips/{clip_id}.jsonl"
                clip_item["rawDanmakuUrl"] = f"/api/rounds/{round_id}/recording/clips/{clip_id}/raw.jsonl"
                clip_item["analysisUrl"] = f"/api/rounds/{round_id}/recording/clips/{clip_id}/analysis-round"
                clips.append(clip_item)
            item["clips"] = clips
            item["clipCount"] = len(clips)
            records.append(item)
        return sorted(records, key=lambda item: item.get("startedAt") or "", reverse=True)

    async def start(self, meta: RoundMeta, source_url: str = "", *, force: bool = False) -> dict[str, Any] | None:
        self._sync_directory_for_config()
        if not force and not self.enabled():
            return None
        source = source_url or self.default_source_url()
        record_dir = self.round_dir(meta.id)
        output = record_dir / "recording.mp4"
        record = {
            "roundId": meta.id,
            "activity": meta.activity,
            "roundName": meta.name,
            "sourceUrl": source,
            "path": str(output),
            "status": "pending",
            "startedAt": now_iso(),
            "endedAt": "",
            "error": "",
            "markers": [],
            "clips": [],
        }
        self.records[meta.id] = record
        self.save()
        if not source:
            record["status"] = "skipped"
            record["error"] = "未配置录制源 URL"
            self.save()
            return record
        args = [
            self.ffmpeg_path(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            source,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            record["status"] = "failed"
            record["error"] = f"无法启动 ffmpeg：{exc}"
            record["endedAt"] = now_iso()
            self.save()
            return record
        self.processes[meta.id] = process
        record["status"] = "recording"
        record["pid"] = process.pid
        self.save()
        asyncio.create_task(self._watch(meta.id, process), name=f"recording-watch-{meta.id}")
        return record

    async def _watch(self, round_id: str, process: asyncio.subprocess.Process) -> None:
        _, stderr = await process.communicate()
        if self.processes.get(round_id) is process:
            self.processes.pop(round_id, None)
        record = self.records.get(round_id)
        if not record:
            return
        if record.get("status") == "recording":
            record["status"] = "finished" if process.returncode == 0 else "failed"
            record["endedAt"] = record.get("endedAt") or now_iso()
            if process.returncode not in (0, None):
                record["error"] = (stderr or b"").decode("utf-8", errors="replace")[-1200:]
            self.save()

    async def stop(self, round_id: str) -> dict[str, Any] | None:
        record = self.records.get(round_id)
        process = self.processes.pop(round_id, None)
        if process and process.returncode is None:
            if process.stdin:
                try:
                    process.stdin.write(b"q")
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionError):
                    pass
            try:
                await asyncio.wait_for(process.wait(), timeout=12)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
        if record:
            record["status"] = "finished" if Path(str(record.get("path") or "")).exists() else record.get("status", "stopped")
            record["endedAt"] = record.get("endedAt") or now_iso()
            self.save()
        return record

    async def stop_all(self) -> None:
        for round_id in list(self.processes):
            await self.stop(round_id)

    def add_marker(self, round_id: str, label: str, at_seconds: float) -> dict[str, Any]:
        record = self.records.get(round_id)
        if not record:
            raise KeyError(f"找不到录制：{round_id}")
        marker = {
            "id": safe_id(),
            "label": normalize(label) or "未命名标记",
            "atSeconds": max(0, float(at_seconds)),
            "createdAt": now_iso(),
        }
        record.setdefault("markers", []).append(marker)
        self.save()
        return marker

    async def create_clip(self, round_id: str, start_seconds: float, end_seconds: float, label: str = "") -> dict[str, Any]:
        record = self.records.get(round_id)
        if not record:
            raise KeyError(f"找不到录制：{round_id}")
        source = Path(str(record.get("path") or ""))
        if not source.exists():
            raise FileNotFoundError("录制文件不存在")
        start = max(0.0, float(start_seconds))
        end = max(start + 0.1, float(end_seconds))
        clip_id = safe_id()
        filename = f"clip-{clip_id}.mp4"
        output = self.round_dir(round_id) / filename
        args = [
            self.ffmpeg_path(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            str(source),
            "-c",
            "copy",
            str(output),
        ]
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError((stderr or b"").decode("utf-8", errors="replace")[-1200:] or "ffmpeg 截取失败")
        clip = {
            "id": clip_id,
            "label": normalize(label) or f"{start:.1f}s-{end:.1f}s",
            "startSeconds": start,
            "endSeconds": end,
            "path": str(output),
            "url": f"/api/rounds/{quote(round_id, safe='')}/recording/clips/{quote(clip_id, safe='')}.mp4",
            "createdAt": now_iso(),
        }
        record.setdefault("clips", []).append(clip)
        self.save()
        return clip

    def video_path(self, round_id: str) -> Path:
        record = self.records.get(round_id)
        if not record:
            raise KeyError(f"找不到录制：{round_id}")
        path = Path(str(record.get("path") or ""))
        if not path.exists():
            raise FileNotFoundError("录制文件不存在")
        return path

    def clip_path(self, round_id: str, clip_id: str) -> Path:
        record = self.records.get(round_id)
        if not record:
            raise KeyError(f"找不到录制：{round_id}")
        clip = self.clip_for(round_id, clip_id)
        path = Path(str(clip.get("path") or ""))
        if not path.exists():
            raise FileNotFoundError("片段文件不存在")
        return path

    def clip_for(self, round_id: str, clip_id: str) -> dict[str, Any]:
        record = self.records.get(round_id)
        if not record:
            raise KeyError(f"找不到录制：{round_id}")
        clip = next((item for item in record.get("clips") or [] if item.get("id") == clip_id), None)
        if not clip:
            raise KeyError(f"找不到片段：{clip_id}")
        return dict(clip)

    def delete_round(self, round_id: str) -> None:
        self.records.pop(round_id, None)
        self.processes.pop(round_id, None)
        shutil.rmtree(self.directory / round_id, ignore_errors=True)
        self.save()


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
        self.recorder = RecordingManager(config.get("recording", {}), self.store.directory)
        self.mgtv_auth = MgtvAuthManager(config.get("mgtv_auth", {}))
        self.feishu = FeishuBot(config.get("feishu", {}))
        self.operator_auth = OperatorAuth(config.get("operator_auth") or {})
        self.default_candidates = candidates_from_config(config.get("vote", {}).get("candidates", []))
        self.default_policy = config.get("vote", {}).get("multi_candidate_policy", "all")
        self.user_selection: dict[str, str] = {}
        self.feishu_connection: Any = None
        self.updater = GitUpdater(self.repo_root)
        self.started_at = now_iso()
        self.system_events: list[dict[str, Any]] = []
        self.monitor_task: asyncio.Task[Any] | None = None
        self.monitor_auto_started = False
        self.monitor_last_url = ""
        self.monitor_state: dict[str, Any] = self._initial_monitor_state()
        self.monitor_last_notified_key = ""
        self.add_system_event("info", "service", "服务已启动", "直播运营工作台后端进程已初始化。")

    def add_system_event(
        self,
        level: str,
        source: str,
        summary: str,
        detail: str = "",
        **extra: Any,
    ) -> None:
        """Keep a small redacted in-memory event stream for the WebUI log page."""
        event = {
            "time": now_iso(),
            "level": level.upper() if level else "INFO",
            "source": source or "service",
            "summary": normalize(summary),
            "detail": self._redact_log_text(detail),
        }
        for key, value in extra.items():
            if value is not None:
                event[key] = self._redact_log_text(str(value)) if isinstance(value, str) else value
        self.system_events.append(event)
        self.system_events = self.system_events[-300:]
        try:
            log_path = self.store.directory / "system-events.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass

    @staticmethod
    def _redact_log_text(value: str) -> str:
        text = str(value or "")
        patterns = [
            (r"(?i)(app_secret|token|cookie|session|device_code|user_code|password)(['\":=\s]+)[^,\s\"']+", r"\1\2***"),
            (r"(?i)(Authorization:\s*Bearer\s+)[^\s]+", r"\1***"),
        ]
        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text)
        return text

    def _initial_monitor_state(self) -> dict[str, Any]:
        return {
            "status": "disabled",
            "message": "活动监控未启用。",
            "lastCheckAt": "",
            "lastSuccessAt": "",
            "lastError": "",
            "roundId": "",
            "activity": "",
            "url": "",
            "quality": "",
            "taskRunning": False,
            "autoStarted": False,
        }

    def monitor_config(self) -> dict[str, Any]:
        monitor = dict(self.config.get("monitor") or {})
        vote = self.config.get("vote") or {}
        mgtv = self.config.get("mgtv") or {}
        return {
            "enabled": bool(monitor.get("enabled")),
            "activity": str(monitor.get("activity") or vote.get("activity") or "未分类活动"),
            "url": str(monitor.get("url") or mgtv.get("url") or ""),
            "autoDetectSource": bool(monitor.get("auto_detect_source", True)),
            "autoRecordVideo": bool(monitor.get("auto_record_video", False)),
            "autoRecordDanmaku": bool(monitor.get("auto_record_danmaku", True)),
            "feishuNotify": bool(monitor.get("feishu_notify", True)),
            "pollSeconds": max(10, min(3600, int(monitor.get("poll_seconds") or 45))),
            "roundName": str(monitor.get("round_name") or ""),
        }

    def _set_monitor_state(self, **updates: Any) -> None:
        state = dict(self.monitor_state or self._initial_monitor_state())
        previous_status = state.get("status") or ""
        state.update(updates)
        state["taskRunning"] = bool(self.monitor_task is not None and not self.monitor_task.done())
        state["autoStarted"] = bool(self.monitor_auto_started)
        self.monitor_state = state
        if updates and previous_status and previous_status != state.get("status"):
            self.add_system_event("info", "monitor", "活动监控状态变化", f"{previous_status} → {state.get('status')}: {state.get('message') or ''}")

    def monitor_status_view(self) -> dict[str, Any]:
        self._set_monitor_state()
        return {
            "config": self.monitor_config(),
            "state": dict(self.monitor_state),
        }

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
            "monitor": self.monitor_status_view(),
            "restartRequired": bool(self.pending_restart_fields),
            "restartFields": self.pending_restart_fields,
            "configPath": str(self.config_path) if self.config_path else "",
        }

    def settings_view(self) -> dict[str, Any]:
        return public_settings(self.config, self.settings_runtime())

    def public_state(self) -> dict[str, Any]:
        state = self.store.public_state()
        state["defaults"] = {
            "activity": str((self.config.get("vote") or {}).get("activity") or "未分类活动"),
            "mgtvUrl": str((self.config.get("mgtv") or {}).get("url") or ""),
            "publicBaseUrl": self.public_base_url(),
            "publicResultsUrl": str((self.config.get("feishu") or {}).get("public_results_url") or self.public_base_url() or ""),
        }
        recordings = {item.get("roundId"): item for item in self.recorder.public_records()}
        for session in state.get("sessions") or []:
            session["recording"] = recordings.get(session.get("id"))
        return state

    def _process_rss_bytes(self) -> int:
        proc_status = Path("/proc/self/status")
        if proc_status.exists():
            for line in proc_status.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        return int(parts[1]) * 1024
        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if platform.system() == "Darwin":
            return rss
        return rss * 1024

    def _memory_snapshot(self) -> dict[str, Any]:
        total = 0
        available = 0
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            raw: dict[str, int] = {}
            for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                key, _, value = line.partition(":")
                parts = value.strip().split()
                if parts and parts[0].isdigit():
                    raw[key] = int(parts[0]) * 1024
            total = raw.get("MemTotal", 0)
            available = raw.get("MemAvailable", raw.get("MemFree", 0))
        elif hasattr(os, "sysconf"):
            try:
                pages = int(os.sysconf("SC_PHYS_PAGES"))
                page_size = int(os.sysconf("SC_PAGE_SIZE"))
                total = pages * page_size
            except (OSError, ValueError):
                total = 0
        used = max(0, total - available) if total and available else 0
        return {
            "totalBytes": total,
            "availableBytes": available,
            "usedBytes": used,
            "processRssBytes": self._process_rss_bytes(),
        }

    @staticmethod
    def _disk_snapshot(path: Path) -> dict[str, Any]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(path)
            return {
                "path": str(path),
                "totalBytes": usage.total,
                "usedBytes": usage.used,
                "freeBytes": usage.free,
                "ok": True,
            }
        except OSError as exc:
            return {"path": str(path), "ok": False, "error": str(exc)}

    @staticmethod
    def _network_snapshot() -> dict[str, Any]:
        proc_net = Path("/proc/net/dev")
        if not proc_net.exists():
            return {"available": False, "rxBytes": 0, "txBytes": 0}
        rx_total = 0
        tx_total = 0
        for line in proc_net.read_text(encoding="utf-8", errors="ignore").splitlines()[2:]:
            name, _, stats = line.partition(":")
            iface = name.strip()
            if iface == "lo":
                continue
            parts = stats.split()
            if len(parts) >= 16:
                rx_total += int(parts[0])
                tx_total += int(parts[8])
        return {"available": True, "rxBytes": rx_total, "txBytes": tx_total}

    def system_status(self) -> dict[str, Any]:
        runtime = self.settings_runtime()
        config = self.config or {}
        recording = config.get("recording") or {}
        recording_dir = self.recorder.directory
        storage_dir = self.store.directory
        data_disk = self._disk_snapshot(storage_dir)
        recording_disk = self._disk_snapshot(recording_dir)
        load_average = list(os.getloadavg()) if hasattr(os, "getloadavg") else []
        feishu_thread = getattr(self.feishu_connection, "thread", None)
        active_recordings = [item for item in self.recorder.public_records() if item.get("status") == "recording"]
        update_in_progress = self.update_task is not None and not self.update_task.done()
        monitor = self.monitor_status_view()
        health = "warning" if self.pending_restart_fields else "ok"
        recent_errors = [event for event in self.system_events[-50:] if event.get("level") == "ERROR"]
        if recent_errors:
            health = "error"
        return {
            "ok": True,
            "generatedAt": now_iso(),
            "systemTime": datetime.now(BEIJING_TZ).isoformat(timespec="seconds"),
            "timezone": "Asia/Shanghai",
            "platform": platform.platform(),
            "python": platform.python_version(),
            "startedAt": self.started_at,
            "uptimeSeconds": max(0, int((parse_iso(now_iso()) - parse_iso(self.started_at)).total_seconds())),
            "process": {
                "pid": os.getpid(),
                "name": "mgtv-danmaku",
                "rssBytes": self._process_rss_bytes(),
            },
            "cpu": {
                "count": os.cpu_count() or 0,
                "loadAverage": load_average,
                "loadPercent": round((load_average[0] / max(1, os.cpu_count() or 1)) * 100, 1) if load_average else None,
            },
            "memory": self._memory_snapshot(),
            "network": self._network_snapshot(),
            "disk": {
                "data": data_disk,
                "recordings": recording_disk,
            },
            "services": {
                "collector": {"status": "running" if self.collector.running() else "idle", "activeRoundId": self.store.active_round_id},
                "recorder": {"status": "recording" if active_recordings else "idle", "activeCount": len(active_recordings), "enabled": self.recorder.enabled()},
                "feishu": {"status": "connected" if feishu_thread and feishu_thread.is_alive() else ("enabled" if self.feishu.enabled() else "disabled")},
                "github": {"status": "enabled" if (config.get("github") or {}).get("enabled") else "disabled"},
                "updater": {"status": "running" if update_in_progress else "idle", "progress": self.update_progress},
                "monitor": {
                    "status": (monitor.get("state") or {}).get("status") or "disabled",
                    "message": (monitor.get("state") or {}).get("message") or "",
                    "enabled": (monitor.get("config") or {}).get("enabled") or False,
                    "taskRunning": (monitor.get("state") or {}).get("taskRunning") or False,
                },
                "recordingSource": {
                    "configured": bool(recording.get("stream_url")),
                    "quality": recording.get("last_detected_quality") or recording.get("preferred_quality") or "auto",
                    "detectedAt": recording.get("last_detected_at") or "",
                },
            },
            "monitor": monitor,
            "health": {
                "status": health,
                "restartRequired": runtime["restartRequired"],
                "restartFields": runtime["restartFields"],
                "recentErrorCount": len(recent_errors),
            },
        }

    def system_logs(self, limit: int = 120) -> dict[str, Any]:
        wanted = max(1, min(300, limit))
        events = self._persisted_system_events(wanted)
        if not events:
            events = list(self.system_events[-wanted:])
        events = list(reversed(events[-wanted:]))
        if self.update_progress.get("logs"):
            update_events = [
                {
                    "time": self.update_progress.get("updatedAt") or now_iso(),
                    "level": "INFO" if self.update_progress.get("stage") != "failed" else "ERROR",
                    "source": "updater",
                    "summary": self._redact_log_text(item),
                    "detail": "",
                }
                for item in reversed(self.update_progress.get("logs") or [])
            ]
            events = update_events + events
        return {
            "ok": True,
            "generatedAt": now_iso(),
            "events": events[:limit],
            "sources": sorted({str(event.get("source") or "service") for event in events}),
        }

    def _persisted_system_events(self, limit: int) -> list[dict[str, Any]]:
        path = self.store.directory / "system-events.jsonl"
        if not path.exists():
            return []
        lines: list[str] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        lines.append(line)
                        if len(lines) > limit:
                            lines = lines[-limit:]
        except OSError:
            return []
        events: list[dict[str, Any]] = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                events.append(item)
        return events

    def start_background_tasks(self, loop: asyncio.AbstractEventLoop) -> None:
        if self.monitor_task is None or self.monitor_task.done():
            self.monitor_task = loop.create_task(self._monitor_loop(), name="mgtv-activity-monitor")
            self._set_monitor_state(taskRunning=True)
            self.add_system_event("info", "monitor", "活动监控后台任务已启动")

    async def stop_background_tasks(self) -> None:
        task = self.monitor_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.monitor_task = None
        self._set_monitor_state(taskRunning=False)

    async def _monitor_loop(self) -> None:
        while True:
            try:
                await self.monitor_tick_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._set_monitor_state(
                    status="error",
                    message="活动监控执行失败，稍后自动重试。",
                    lastCheckAt=now_iso(),
                    lastError=str(exc),
                )
                self.add_system_event("error", "monitor", "活动监控执行失败", str(exc))
            config = self.monitor_config()
            await asyncio.sleep(config["pollSeconds"] if config["enabled"] else 10)

    async def notify_monitor(self, text: str) -> None:
        monitor = self.monitor_config()
        if not monitor["feishuNotify"] or not self.feishu.enabled():
            return
        targets = self.feishu_push_targets()
        if not targets:
            self.add_system_event("warn", "feishu", "活动监控未推送飞书", "未配置 allowed_chat_ids 或 allowed_open_ids")
            return
        receive_id, receive_type = targets[0]
        await self.feishu.send_card(receive_id, receive_type, self.feishu_card("", text))

    def feishu_push_targets(self) -> list[tuple[str, str]]:
        feishu = self.config.get("feishu") or {}
        chat_ids = feishu.get("allowed_chat_ids") or []
        open_ids = feishu.get("allowed_open_ids") or []
        if isinstance(chat_ids, str):
            chat_ids = [item.strip() for item in chat_ids.split(",") if item.strip()]
        if isinstance(open_ids, str):
            open_ids = [item.strip() for item in open_ids.split(",") if item.strip()]
        chat_ids = [item for item in chat_ids if item and item != "*"]
        open_ids = [item for item in open_ids if item and item != "*"]
        return [(str(chat_id), "chat_id") for chat_id in chat_ids] + [(str(open_id), "open_id") for open_id in open_ids]

    async def push_feishu_control_card(self, notice: str = "WebUI 已同步控制卡片。") -> dict[str, Any]:
        if not self.feishu.enabled():
            raise RuntimeError("飞书 Bot 未启用")
        targets = self.feishu_push_targets()
        if not targets:
            raise RuntimeError("未配置可主动推送的 allowed_chat_ids 或 allowed_open_ids")
        sent: list[dict[str, str]] = []
        card = self.feishu_card("", notice)
        for receive_id, receive_type in targets:
            await self.feishu.send_card(receive_id, receive_type, card)
            sent.append({"receiveId": receive_id, "receiveIdType": receive_type})
        self.add_system_event("info", "feishu", "已主动同步飞书控制卡片", f"targets={len(sent)}")
        return {"ok": True, "sent": sent, "count": len(sent)}

    async def notify_monitor_status_once(self, *, force: bool = False) -> None:
        monitor = self.monitor_config()
        state = self.monitor_state or {}
        status = str(state.get("status") or "")
        message = str(state.get("message") or "")
        key = f"{status}|{message}|{state.get('roundId') or ''}"
        if not force and (not monitor["feishuNotify"] or key == self.monitor_last_notified_key):
            return
        self.monitor_last_notified_key = key
        if status in {"waiting", "source_ready", "running", "error"} or force:
            await self.notify_monitor(f"活动监控：{message or status}")

    async def monitor_tick_once(self) -> dict[str, Any]:
        config = self.monitor_config()
        activity = normalize(config["activity"]) or "未分类活动"
        url = normalize(config["url"])
        if self.monitor_last_url != url:
            self.monitor_last_url = url
            self.monitor_auto_started = False
        if not config["enabled"]:
            self._set_monitor_state(
                status="disabled",
                message="活动监控未启用。",
                activity=activity,
                url=url,
                lastError="",
                roundId="",
            )
            await self.notify_monitor_status_once()
            return self.monitor_status_view()
        if not url:
            self._set_monitor_state(
                status="blocked",
                message="活动监控已启用，但缺少活动链接。",
                activity=activity,
                url=url,
                lastCheckAt=now_iso(),
                lastError="缺少活动链接",
            )
            await self.notify_monitor_status_once()
            return self.monitor_status_view()

        active = self.store.find_round(self.store.active_round_id)
        if active:
            self._set_monitor_state(
                status="running",
                message=f"正在采集：{active.activity} / {active.name}",
                activity=active.activity,
                url=url,
                roundId=active.id,
                lastCheckAt=now_iso(),
                lastError="",
            )
            await self.notify_monitor_status_once()
            return self.monitor_status_view()

        self._set_monitor_state(
            status="checking",
            message="正在检测直播源与机位。",
            activity=activity,
            url=url,
            lastCheckAt=now_iso(),
            lastError="",
        )

        source_ready = False
        quality = ""
        try:
            if config["autoDetectSource"] or config["autoRecordVideo"]:
                detected = await self.detect_mgtv_recording_source(url, str((self.config.get("recording") or {}).get("preferred_quality") or "auto"))
                source_ready = bool(detected.get("ok"))
                quality = str(detected.get("actualQuality") or detected.get("quality") or "")
                if not source_ready:
                    self.monitor_auto_started = False
                    self._set_monitor_state(
                        status="waiting",
                        message=str(detected.get("error") or "直播源暂不可用，等待下一次检测。"),
                        lastError=str(detected.get("error") or ""),
                        quality=quality,
                    )
                    await self.notify_monitor_status_once()
                    return self.monitor_status_view()
            else:
                resolved = await self.resolve_mgtv_live_url(url, persist=True)
                source_ready = bool(resolved.get("ok"))
                if not source_ready:
                    self.monitor_auto_started = False
                    self._set_monitor_state(
                        status="waiting",
                        message=str(resolved.get("error") or "直播机位暂不可用，等待下一次检测。"),
                        lastError=str(resolved.get("error") or ""),
                    )
                    await self.notify_monitor_status_once()
                    return self.monitor_status_view()
        except Exception as exc:
            self.monitor_auto_started = False
            self._set_monitor_state(
                status="waiting",
                message=f"直播源暂不可用，等待下一次检测：{exc}",
                lastError=str(exc),
            )
            await self.notify_monitor_status_once()
            return self.monitor_status_view()

        self._set_monitor_state(
            status="source_ready",
            message="已检测到可用直播源。",
            lastSuccessAt=now_iso(),
            lastError="",
            quality=quality,
        )

        should_auto_start = bool(config["autoRecordVideo"] or config["autoRecordDanmaku"])
        if not should_auto_start:
            await self.notify_monitor_status_once()
            return self.monitor_status_view()
        if self.monitor_auto_started:
            self._set_monitor_state(
                status="armed",
                message="本次直播已自动启动过场次；如需重新开始，请先关闭再开启监控。",
            )
            await self.notify_monitor_status_once()
            return self.monitor_status_view()

        name = normalize(config["roundName"]) or f"{activity} 全程录制"
        meta = await self.start_round(
            name,
            url,
            activity,
            record_video=config["autoRecordVideo"],
            collect_danmaku=config["autoRecordDanmaku"],
        )
        self.monitor_auto_started = True
        self._set_monitor_state(
            status="running",
            message=f"已自动开始：{meta.activity} / {meta.name}",
            roundId=meta.id,
            activity=meta.activity,
            url=url,
            lastSuccessAt=now_iso(),
            lastError="",
        )
        self.add_system_event("info", "monitor", "活动监控已自动开始场次", f"{meta.activity} / {meta.name}", roundId=meta.id)
        try:
            await self.notify_monitor_status_once(force=True)
        except Exception as exc:
            self.add_system_event("warn", "feishu", "活动监控飞书通知失败", str(exc), roundId=meta.id)
        return self.monitor_status_view()

    def public_base_url(self) -> str:
        return str((self.config.get("listen") or {}).get("public_base_url") or "").rstrip("/")

    def round_result_png_url(self, round_id: str, result_type: str | None = None) -> str:
        base = self.public_base_url()
        if not base or not round_id:
            return ""
        url = f"{base}/exports/rounds/{quote(round_id, safe='')}/result.png"
        if result_type in {"rough", "precise"}:
            url += f"?result={result_type}"
        return url

    def export_round_result_png(self, round_id: str, result_type: str | None = None) -> tuple[bytes, str]:
        return render_result_png(self.public_state(), round_id, result_type)

    async def _save_mgtv_login(self, cookies: list[dict[str, Any]], cookie_header: str, user_info: dict[str, Any]) -> None:
        if self.config_path is None:
            return
        async with self.config_lock:
            target = copy.deepcopy(self.config)
            auth = dict(target.get("mgtv_auth") or {})
            auth.update({
                "cookies": cookies,
                "cookie_header": cookie_header,
                "user_info": user_info,
                "bound_at": now_iso(),
            })
            target["mgtv_auth"] = auth
            save_config_atomic(self.config_path, target)
            self.config = target
            self.mgtv_auth.config = auth

    async def start_mgtv_qr_login(self) -> dict[str, Any]:
        return await self.mgtv_auth.start_qr_login(self._save_mgtv_login)

    async def resolve_mgtv_live_url(self, url: str, *, persist: bool = False) -> dict[str, Any]:
        result = await self.mgtv_auth.resolve_live_url(url)
        if not result.get("ok"):
            return result
        page_url = str(result.get("pageUrl") or url)
        camera_id = str(result.get("cameraId") or "")
        activity_id = str(result.get("activityId") or "")
        if persist and camera_id:
            async with self.config_lock:
                target = copy.deepcopy(self.config)
                mgtv = dict(target.get("mgtv") or {})
                mgtv["url"] = page_url
                mgtv["camera_id"] = camera_id
                mgtv["activity_id"] = activity_id
                flag = str(mgtv.get("flag") or "liveshow")
                mgtv["room_id"] = f"{flag}-{camera_id}"
                target["mgtv"] = mgtv
                if self.config_path is not None:
                    save_config_atomic(self.config_path, target)
                self.config = target
                self.collector.apply_config(mgtv)
        return result

    async def detect_mgtv_recording_source(self, url: str | None = None, quality: str | None = None) -> dict[str, Any]:
        recording = self.config.get("recording") or {}
        page_url = url or self.config.get("mgtv", {}).get("url") or ""
        preferred = quality or str(recording.get("preferred_quality") or "auto")
        if not page_url:
            return {"ok": False, "error": "未配置芒果直播页 URL", "quality": preferred}
        result = await self.mgtv_auth.detect_stream(page_url, preferred)
        if result.get("ok") and result.get("streamUrl"):
            async with self.config_lock:
                target = copy.deepcopy(self.config)
                rec = dict(target.get("recording") or {})
                rec["stream_url"] = result["streamUrl"]
                rec["last_detected_quality"] = result.get("actualQuality") or result.get("quality") or ""
                rec["last_detected_at"] = now_iso()
                target["recording"] = rec
                mgtv = dict(target.get("mgtv") or {})
                if result.get("pageUrl"):
                    mgtv["url"] = result["pageUrl"]
                if result.get("cameraId"):
                    mgtv["camera_id"] = result["cameraId"]
                    flag = str(mgtv.get("flag") or "liveshow")
                    mgtv["room_id"] = f"{flag}-{result['cameraId']}"
                if result.get("activityId"):
                    mgtv["activity_id"] = result["activityId"]
                target["mgtv"] = mgtv
                if self.config_path is not None:
                    save_config_atomic(self.config_path, target)
                self.config = target
                self.recorder.apply_config(rec)
                self.collector.apply_config(mgtv)
            self.add_system_event(
                "info",
                "mgtv",
                "直播源检测成功",
                f"quality={result.get('actualQuality') or result.get('quality') or preferred}, camera_id={result.get('cameraId') or ''}",
            )
        elif result.get("error"):
            self.add_system_event("warn", "mgtv", "直播源检测失败，等待重试", str(result.get("error") or ""))
        redacted = dict(result)
        if redacted.get("streamUrl"):
            redacted["streamUrl"] = "已解析，已隐藏"
        return redacted

    def recording_clip_time_range(self, round_id: str, clip_id: str) -> tuple[dict[str, Any], dict[str, Any], str, str]:
        record = self.recorder.record_for(round_id)
        if not record:
            raise KeyError(f"找不到录制：{round_id}")
        clip = self.recorder.clip_for(round_id, clip_id)
        start = parse_iso(str(record.get("startedAt") or self.store.require_round(round_id).sliceStartTime))
        start_time = iso_z(start + timedelta(seconds=max(0.0, float(clip.get("startSeconds") or 0))))
        end_time = iso_z(start + timedelta(seconds=max(0.0, float(clip.get("endSeconds") or 0))))
        return record, clip, start_time, end_time

    def export_recording_clip_danmaku(self, round_id: str, clip_id: str, *, raw: bool = False) -> tuple[str, str]:
        meta = self.store.require_round(round_id)
        _record, clip, start_time, end_time = self.recording_clip_time_range(round_id, clip_id)
        iterator = (
            self.store.iter_raw_round_records_by_time(round_id, start_time, end_time)
            if raw
            else self.store.iter_round_records_by_time(round_id, start_time, end_time)
        )
        lines = [json.dumps({
            "type": "meta",
            **asdict(meta),
            "sourceRoundId": round_id,
            "clipId": clip_id,
            "clipLabel": clip.get("label") or "",
            "clipStartSeconds": clip.get("startSeconds"),
            "clipEndSeconds": clip.get("endSeconds"),
            "displayName": meta.baseName,
            "timeRange": format_beijing_display_range(start_time, end_time),
            "rawTrack": "observed_api_items" if raw else "",
            "derivedFromRecordingClip": True,
        }, ensure_ascii=False, separators=(",", ":"))]
        lines.extend(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in iterator)
        suffix = "-raw" if raw else ""
        filename = f"mgtv-round-{round_id}-clip-{clip_id}{suffix}.jsonl"
        return "\n".join(lines) + "\n", filename

    async def create_analysis_round_from_clip(self, round_id: str, clip_id: str, name: str = "") -> RoundMeta:
        source = self.store.require_round(round_id)
        _record, clip, start_time, end_time = self.recording_clip_time_range(round_id, clip_id)
        records = [dict(item) for item in self.store.iter_round_records_by_time(round_id, start_time, end_time)]
        clip_label = normalize(name) or normalize(clip.get("label") or "") or f"{clip.get('startSeconds', 0):.1f}s-{clip.get('endSeconds', 0):.1f}s"
        derived_name = f"{source.baseName} / {clip_label}"
        return await self.store.create_derived_round(
            activity=source.activity,
            name=derived_name,
            url=source.pageUrl,
            candidates=source.candidates,
            policy=source.multiCandidatePolicy,
            records=records,
            source_round_id=round_id,
            slice_start_time=start_time,
            slice_end_time=end_time,
        )

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
            self.collector.apply_config(runtime_mgtv)
            self.recorder.apply_config(new_config.get("recording", {}) or {})
            self.mgtv_auth.config = new_config.get("mgtv_auth", {}) or {}
            self.pending_restart_fields = self._restart_fields_for(new_config)
            if (old_config.get("monitor") or {}) != (new_config.get("monitor") or {}):
                self.monitor_auto_started = False
                monitor = self.monitor_config()
                self._set_monitor_state(
                    status="armed" if monitor["enabled"] else "disabled",
                    message="活动监控配置已热应用。" if monitor["enabled"] else "活动监控未启用。",
                    activity=monitor["activity"],
                    url=monitor["url"],
                    lastError="",
                )
            self.add_system_event(
                "info",
                "settings",
                "配置已热应用" if not self.pending_restart_fields else "配置已保存，等待安全重启",
                "restartFields=" + ",".join(self.pending_restart_fields),
            )

            old_feishu = old_config.get("feishu") or {}
            new_feishu = new_config.get("feishu") or {}
            if old_feishu != new_feishu:
                self.feishu = FeishuBot(new_feishu)
                await self.reload_feishu_connection(loop)

            self.operator_auth = OperatorAuth(new_config.get("operator_auth") or {})
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
        selected_id = self.user_selection.get(open_id)
        return build_control_card(self.public_state(), selected_id, notice, public_url)

    async def handle_feishu_text(
        self,
        text: str,
        open_id: str,
        chat_id: str,
        receive_id: str,
        receive_id_type: str,
    ) -> None:
        if not self.feishu.is_allowed(open_id, chat_id):
            await self.feishu.send_card(receive_id, receive_id_type, build_control_card(self.public_state(), notice="无操作权限。"))
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

    def feishu_start_form_defaults(self, form_value: dict[str, Any] | None) -> tuple[str, str, str]:
        values = form_value if isinstance(form_value, dict) else {}
        default_activity = str((self.config.get("vote") or {}).get("activity") or "未分类活动")
        activity = normalize(values.get("activity") or default_activity) or default_activity
        name = normalize(values.get("round_name") or "") or f"第 {len(self.store.round_order) + 1} 轮"
        url = normalize(values.get("live_url") or "")
        return activity, name, url

    async def handle_feishu_card_action(
        self,
        action: str,
        open_id: str,
        chat_id: str,
        option: str = "",
        form_value: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.feishu.is_allowed(open_id, chat_id):
            return build_control_card(self.public_state(), notice="无操作权限。")
        notice = "状态已刷新。"
        try:
            if action == "show_rounds":
                return build_round_list_card(self.public_state(), self.user_selection.get(open_id))
            if action == "show_recording":
                return build_recording_card(self.public_state(), self.user_selection.get(open_id))
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
            elif action == "start_custom":
                if self.store.active_round_id:
                    notice = "已有场次正在采集，请先结束本轮。"
                else:
                    activity, name, url = self.feishu_start_form_defaults(form_value)
                    meta = await self.start_round(name, url or None, activity)
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
            elif action == "send_png":
                target = self.store.find_round(self.user_selection.get(open_id))
                if target is None:
                    target = self.store.find_round(None)
                if target is None:
                    notice = "暂无可导出的场次。"
                else:
                    result_type = "precise" if target.preciseResult else "rough"
                    content, filename = self.export_round_result_png(target.id, result_type)
                    receive_id = chat_id or open_id
                    receive_type = "chat_id" if chat_id else "open_id"
                    await self.feishu.send_image(receive_id, receive_type, content, filename)
                    self.user_selection[open_id] = target.id
                    label = "精确结果" if result_type == "precise" else "粗略结果"
                    notice = f"已发送 {target.name} 的{label} PNG 到当前会话。"
            elif action == "add_marker":
                target = self.store.find_round(self.user_selection.get(open_id))
                if target is None:
                    target = self.store.find_round(None)
                if target is None:
                    return build_recording_card(self.public_state(), notice="暂无可标记的场次。")
                values = form_value if isinstance(form_value, dict) else {}
                at_seconds = float(values.get("at_seconds") or 0)
                label = normalize(values.get("label") or "") or f"飞书标记 {at_seconds:.1f}s"
                marker = self.recorder.add_marker(target.id, label, at_seconds)
                self.user_selection[open_id] = target.id
                return build_recording_card(self.public_state(), target.id, f"已添加标记：{marker['label']} @ {marker['atSeconds']:.1f}s")
            elif action == "create_clip":
                target = self.store.find_round(self.user_selection.get(open_id))
                if target is None:
                    target = self.store.find_round(None)
                if target is None:
                    return build_recording_card(self.public_state(), notice="暂无可截取的场次。")
                values = form_value if isinstance(form_value, dict) else {}
                start_seconds = float(values.get("start_seconds") or 0)
                end_seconds = float(values.get("end_seconds") or 0)
                label = normalize(values.get("label") or "")
                clip = await self.recorder.create_clip(target.id, start_seconds, end_seconds, label)
                self.user_selection[open_id] = target.id
                return build_recording_card(self.public_state(), target.id, f"已截取片段：{clip['label']}")
            elif action == "analyze_latest_clip":
                target = self.store.find_round(self.user_selection.get(open_id))
                if target is None:
                    target = self.store.find_round(None)
                if target is None:
                    return build_recording_card(self.public_state(), notice="暂无可分析的场次。")
                record = self.recorder.record_for(target.id)
                clips = (record or {}).get("clips") or []
                if not clips:
                    return build_recording_card(self.public_state(), target.id, "当前场次暂无片段，请先截取。")
                clip = clips[-1]
                meta = await self.create_analysis_round_from_clip(target.id, str(clip.get("id") or ""), "")
                self.user_selection[open_id] = meta.id
                notice = f"已生成分析场次：{meta.activity} / {meta.name}（{meta.messageCount} 条弹幕）"
                return build_recording_card(self.public_state(), meta.id, notice)
            elif action == "delete_round":
                target = self.store.find_round(self.user_selection.get(open_id))
                if target is None:
                    target = self.store.find_round(None)
                if target is None:
                    notice = "暂无可删除的场次。"
                else:
                    meta, url = await self.delete_round(target.id, publish=True)
                    if self.user_selection.get(open_id) == meta.id:
                        self.user_selection.pop(open_id, None)
                    notice = f"已删除场次：{meta.activity} / {meta.name}。公开结果状态：{url}"
            elif action == "delete_activity":
                target = self.store.find_round(self.user_selection.get(open_id))
                if target is None:
                    target = self.store.find_round(None)
                if target is None:
                    notice = "暂无可删除的活动。"
                else:
                    activity = target.activity or "未分类活动"
                    metas, url = await self.delete_activity(activity, publish=True)
                    if self.user_selection.get(open_id) in {meta.id for meta in metas}:
                        self.user_selection.pop(open_id, None)
                    notice = f"已删除活动：{activity}，共 {len(metas)} 个场次。公开结果状态：{url}"
            elif action != "refresh":
                notice = "未识别的卡片操作。"
        except Exception as exc:
            notice = f"操作失败：{exc}"
        return self.feishu_card(open_id, notice)

    async def start_round(
        self,
        name: str,
        url: str | None = None,
        activity: str | None = None,
        *,
        record_video: bool | None = None,
        collect_danmaku: bool = True,
    ) -> RoundMeta:
        url = url or self.config.get("mgtv", {}).get("url")
        if not url:
            raise ValueError("未配置直播 URL")
        if record_video is False and collect_danmaku is False:
            raise ValueError("至少需要启用弹幕采集或视频录制中的一项")
        resolution = await self.resolve_mgtv_live_url(str(url), persist=True)
        if not resolution.get("ok"):
            raise ValueError(str(resolution.get("error") or "直播 URL 无法解析出可采集的机位"))
        url = str(resolution.get("pageUrl") or url)
        recording = self.config.get("recording") or {}
        should_record_video = bool(recording.get("enabled")) if record_video is None else bool(record_video)
        recording_source = str(recording.get("stream_url") or "")
        if should_record_video:
            detected = await self.detect_mgtv_recording_source(url, str(recording.get("preferred_quality") or "auto"))
            if not detected.get("ok"):
                raise ValueError(str(detected.get("error") or "录制源检测失败"))
            recording_source = str((self.config.get("recording") or {}).get("stream_url") or "")
        if self.store.active_round_id:
            await self.end_round(publish=True)
        activity = activity or self.config.get("vote", {}).get("activity") or "未分类活动"
        meta = await self.store.create_round(activity, name, url, self.default_candidates, self.default_policy)
        if should_record_video:
            record = await self.recorder.start(meta, recording_source, force=True)
            if record and record.get("status") in {"failed", "skipped"}:
                self.add_system_event("warn", "recorder", "录屏未能启动", record.get("error") or record.get("status") or "", roundId=meta.id)
        if collect_danmaku:
            await self.collector.start(meta.id, url)
        self.add_system_event(
            "info",
            "collector",
            "场次已开始",
            f"{meta.activity} / {meta.name} · video={'on' if should_record_video else 'off'} · danmaku={'on' if collect_danmaku else 'off'}",
            roundId=meta.id,
        )
        return meta

    async def end_round(self, publish: bool = True) -> RoundMeta | None:
        await self.collector.stop()
        meta = await self.store.stop_active()
        if meta:
            await self.recorder.stop(meta.id)
        if publish and meta:
            await self.publisher.publish(force=True, result_kind="rough")
        if meta:
            self.add_system_event("info", "collector", "场次已结束", f"{meta.activity} / {meta.name}", roundId=meta.id)
        return meta

    async def delete_round(self, round_id: str, publish: bool = True) -> tuple[RoundMeta, str]:
        meta = await self.store.delete_round(round_id)
        self.recorder.delete_round(round_id)
        publish_url = ""
        if publish:
            try:
                publish_url = await self.publisher.publish(force=True, result_kind="rough")
            except RuntimeError as exc:
                publish_url = f"公开结果同步失败：{exc}"
                self.add_system_event("warn", "github", "删除场次后公开页同步失败", str(exc), roundId=round_id)
        self.add_system_event("info", "collector", "场次已删除", f"{meta.activity} / {meta.name}", roundId=meta.id)
        return meta, publish_url

    async def delete_activity(self, activity: str, publish: bool = True) -> tuple[list[RoundMeta], str]:
        metas = await self.store.delete_activity(activity)
        for meta in metas:
            self.recorder.delete_round(meta.id)
        publish_url = ""
        if publish:
            try:
                publish_url = await self.publisher.publish(force=True, result_kind="rough")
            except RuntimeError as exc:
                publish_url = f"公开结果同步失败：{exc}"
                self.add_system_event("warn", "github", "删除活动后公开页同步失败", str(exc))
        self.add_system_event("info", "collector", "活动已删除", f"{activity} · {len(metas)} 个场次")
        return metas, publish_url

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
        lines = [f"【{meta.activity} / {meta.name}】{meta.status} · {result_label}"]
        if meta.sliceStartTime:
            lines.append(f"采集时间：{format_beijing_display_range(meta.sliceStartTime, meta.sliceEndTime)}")
        lines.append(f"弹幕样本：{meta.messageCount}，语义待审：{meta.reviewCount}")
        lines.extend(f"{index}. {name}：{count}" for index, (name, count) in enumerate(rows, 1))
        return "\n".join(lines)

    def round_list_text(self) -> str:
        if not self.store.round_order:
            return "暂无场次。"
        lines = ["场次列表："]
        for index, round_id in enumerate(self.store.round_order, 1):
            meta = self.store.rounds[round_id]
            marker = "●" if meta.status == "running" else " "
            time_range = format_beijing_display_range(meta.sliceStartTime, meta.sliceEndTime)
            lines.append(f"{index}. {marker} {meta.activity} / {meta.name}｜{meta.id}｜{time_range}｜样本 {meta.messageCount}")
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
        public_export = request.path.startswith("/exports/rounds/") and request.path.endswith("/result.png")
        if request.path in public_paths or public_export or auth.request_is_authenticated(request):
            return await handler(request)
        if request.path.startswith("/api/"):
            return web.json_response({"error": "登录已过期，请重新登录"}, status=401, headers={"Cache-Control": "no-store"})
        next_url = quote(str(request.rel_url), safe="")
        raise web.HTTPFound(location=f"/login?next={next_url}")

    app = web.Application(
        client_max_size=3 * 1024 * 1024,
        middlewares=[security_headers, operator_auth_middleware],
    )

    async def start_background(app_: web.Application) -> None:
        if hasattr(service, "start_background_tasks"):
            service.start_background_tasks(asyncio.get_running_loop())

    async def cleanup_background(app_: web.Application) -> None:
        if hasattr(service, "stop_background_tasks"):
            await service.stop_background_tasks()

    app.on_startup.append(start_background)
    app.on_cleanup.append(cleanup_background)

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
            "monitor": runtime.get("monitor"),
            "restartRequired": runtime["restartRequired"],
            "restartFields": runtime["restartFields"],
        })

    async def system_status(_: web.Request) -> web.Response:
        return web.json_response(
            service.system_status(),
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def system_logs(request: web.Request) -> web.Response:
        try:
            limit = int(request.query.get("limit", "120"))
        except ValueError:
            limit = 120
        return web.json_response(
            service.system_logs(limit),
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

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
        state = service.public_state() if hasattr(service, "public_state") else service.store.public_state()
        return web.json_response(state, dumps=lambda data: json.dumps(data, ensure_ascii=False))

    async def mgtv_auth_status(_: web.Request) -> web.Response:
        return web.json_response(
            service.mgtv_auth.public_status(),
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def start_mgtv_auth(_: web.Request) -> web.Response:
        result = await service.start_mgtv_qr_login()
        return web.json_response(result, dumps=lambda payload: json.dumps(payload, ensure_ascii=False), headers={"Cache-Control": "no-store"})

    async def check_mgtv_source(request: web.Request) -> web.Response:
        data = await request.json()
        result = await service.detect_mgtv_recording_source(
            str(data.get("url") or ""),
            str(data.get("quality") or ""),
        )
        status = 200 if result.get("ok") else 409
        return web.json_response(result, status=status, dumps=lambda payload: json.dumps(payload, ensure_ascii=False), headers={"Cache-Control": "no-store"})

    async def resolve_mgtv_url(request: web.Request) -> web.Response:
        data = await request.json()
        result = await service.resolve_mgtv_live_url(str(data.get("url") or ""), persist=bool(data.get("persist")))
        status = 200 if result.get("ok") else 409
        return web.json_response(result, status=status, dumps=lambda payload: json.dumps(payload, ensure_ascii=False), headers={"Cache-Control": "no-store"})

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

    async def round_raw_export(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        try:
            body = service.store.export_round_raw_jsonl(round_id)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.Response(
            text=body,
            content_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="mgtv-round-{round_id}-raw.jsonl"'},
        )

    async def round_result_png(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        requested = str(request.query.get("result") or "")
        result_type = requested if requested in {"rough", "precise"} else None
        try:
            body, filename = service.export_round_result_png(round_id, result_type)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.Response(
            body=body,
            content_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    async def command(request: web.Request) -> web.Response:
        data = await request.json()
        reply = await service.handle_command(data.get("text", ""))
        return web.json_response({"reply": reply}, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))

    async def start_round_api(request: web.Request) -> web.Response:
        data = await request.json()
        try:
            meta = await service.start_round(
                str(data.get("name") or ""),
                str(data.get("url") or "") or None,
                str(data.get("activity") or "") or None,
                record_video=bool(data.get("recordVideo")) if "recordVideo" in data else None,
                collect_danmaku=bool(data.get("collectDanmaku", True)),
            )
        except (ValueError, RuntimeError) as exc:
            return web.json_response({"error": str(exc)}, status=409, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            {"ok": True, "roundId": meta.id, "activity": meta.activity, "name": meta.name, "pageUrl": meta.pageUrl},
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def push_feishu_card(_: web.Request) -> web.Response:
        try:
            result = await service.push_feishu_control_card()
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=409, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=502, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(result, dumps=lambda payload: json.dumps(payload, ensure_ascii=False), headers={"Cache-Control": "no-store"})

    async def recordings(_: web.Request) -> web.Response:
        return web.json_response(
            {
                "enabled": service.recorder.enabled(),
                "sourceUrlConfigured": bool(service.recorder.default_source_url()),
                "recordings": service.recorder.public_records(),
            },
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
            headers={"Cache-Control": "no-store"},
        )

    async def round_recording(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        record = service.recorder.record_for(round_id)
        if not record:
            return web.json_response({"error": f"找不到录制：{round_id}"}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        payload = dict(record)
        path = Path(str(payload.get("path") or ""))
        payload["hasVideo"] = path.exists()
        payload["videoUrl"] = f"/api/rounds/{quote(round_id, safe='')}/recording/video" if path.exists() else ""
        return web.json_response(payload, dumps=lambda data: json.dumps(data, ensure_ascii=False), headers={"Cache-Control": "no-store"})

    async def round_recording_video(request: web.Request) -> web.StreamResponse:
        round_id = request.match_info["round_id"]
        try:
            return web.FileResponse(service.recorder.video_path(round_id), headers={"Cache-Control": "no-store"})
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except FileNotFoundError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))

    async def add_recording_marker(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        data = await request.json()
        try:
            marker = service.recorder.add_marker(round_id, str(data.get("label") or ""), float(data.get("atSeconds") or 0))
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response({"ok": True, "marker": marker}, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))

    async def create_recording_clip(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        data = await request.json()
        try:
            clip = await service.recorder.create_clip(
                round_id,
                float(data.get("startSeconds") or 0),
                float(data.get("endSeconds") or 0),
                str(data.get("label") or ""),
            )
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except FileNotFoundError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=502, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response({"ok": True, "clip": clip}, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))

    async def recording_clip(request: web.Request) -> web.StreamResponse:
        round_id = request.match_info["round_id"]
        clip_id = request.match_info["clip_id"]
        try:
            return web.FileResponse(service.recorder.clip_path(round_id, clip_id), headers={"Cache-Control": "no-store"})
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except FileNotFoundError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))

    async def recording_clip_export(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        clip_id = request.match_info["clip_id"]
        try:
            body, filename = service.export_recording_clip_danmaku(round_id, clip_id, raw=False)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.Response(
            text=body,
            content_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def recording_clip_raw_export(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        clip_id = request.match_info["clip_id"]
        try:
            body, filename = service.export_recording_clip_danmaku(round_id, clip_id, raw=True)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.Response(
            text=body,
            content_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def create_clip_analysis_round(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        clip_id = request.match_info["clip_id"]
        data = await request.json()
        try:
            meta = await service.create_analysis_round_from_clip(round_id, clip_id, str(data.get("name") or ""))
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            {
                "ok": True,
                "roundId": meta.id,
                "roundName": meta.name,
                "messageCount": meta.messageCount,
                "exportUrl": f"/api/rounds/{quote(meta.id, safe='')}.jsonl",
            },
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
        )

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
            service.add_system_event("info", "publisher", "精确结果已发布", f"{meta.activity} / {meta.name}", roundId=meta.id)
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

    def should_publish_after_delete(request: web.Request) -> bool:
        value = str(request.query.get("publish", "1")).strip().lower()
        return value not in {"0", "false", "no", "off"}

    async def delete_round(request: web.Request) -> web.Response:
        round_id = request.match_info["round_id"]
        publish_requested = should_publish_after_delete(request)
        try:
            meta, url = await service.delete_round(round_id, publish=publish_requested)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=409, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except RuntimeError as exc:
            return web.json_response({"error": f"场次已删除，但公开结果同步失败：{exc}"}, status=502, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            {
                "ok": True,
                "deletedRoundId": meta.id,
                "deletedRoundName": meta.name,
                "publishRequested": publish_requested,
                "publishUrl": url,
            },
            dumps=lambda payload: json.dumps(payload, ensure_ascii=False),
        )

    async def delete_activity(request: web.Request) -> web.Response:
        activity = request.match_info["activity"]
        publish_requested = should_publish_after_delete(request)
        try:
            metas, url = await service.delete_activity(activity, publish=publish_requested)
        except KeyError as exc:
            return web.json_response({"error": str(exc)}, status=404, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=409, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        except RuntimeError as exc:
            return web.json_response({"error": f"活动已删除，但公开结果同步失败：{exc}"}, status=502, dumps=lambda payload: json.dumps(payload, ensure_ascii=False))
        return web.json_response(
            {
                "ok": True,
                "deletedActivity": normalize(activity) or "未分类活动",
                "deletedRoundIds": [meta.id for meta in metas],
                "deletedRoundCount": len(metas),
                "publishRequested": publish_requested,
                "publishUrl": url,
            },
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
            action_name = str(value.get("action") or "")
            if not action_name and action.get("name") == "start_round_submit":
                action_name = "start_custom"
            elif not action_name and action.get("name") == "add_marker_submit":
                action_name = "add_marker"
            elif not action_name and action.get("name") == "create_clip_submit":
                action_name = "create_clip"
            form_value = action.get("form_value") or action.get("formValue")
            operator = event.get("operator") or {}
            context = event.get("context") or {}
            card = await service.handle_feishu_card_action(
                action_name,
                str(operator.get("open_id") or ""),
                str(context.get("open_chat_id") or ""),
                str(action.get("option") or ""),
                form_value if isinstance(form_value, dict) else None,
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
    app.router.add_get("/api/system/status", system_status)
    app.router.add_get("/api/system/logs", system_logs)
    app.router.add_get("/docs/precise-result-agent", precise_result_doc)
    app.router.add_get("/api/results.json", results)
    app.router.add_get("/api/settings", get_settings)
    app.router.add_post("/api/settings", update_settings)
    app.router.add_get("/api/mgtv/auth", mgtv_auth_status)
    app.router.add_post("/api/mgtv/auth/start", start_mgtv_auth)
    app.router.add_post("/api/mgtv/url/resolve", resolve_mgtv_url)
    app.router.add_post("/api/mgtv/source/check", check_mgtv_source)
    app.router.add_get("/api/feishu/binding", get_feishu_binding)
    app.router.add_post("/api/feishu/binding/start", start_feishu_binding)
    app.router.add_post("/api/restart", restart_service)
    app.router.add_get("/api/update/status", update_status)
    app.router.add_post("/api/update/apply", apply_update)
    app.router.add_get("/api/recordings", recordings)
    app.router.add_post("/api/rounds/start", start_round_api)
    app.router.add_get("/api/rounds/{round_id}.jsonl", round_export)
    app.router.add_get("/api/rounds/{round_id}/raw.jsonl", round_raw_export)
    app.router.add_get("/api/rounds/{round_id}/result.png", round_result_png)
    app.router.add_get("/api/rounds/{round_id}/recording", round_recording)
    app.router.add_get("/api/rounds/{round_id}/recording/video", round_recording_video)
    app.router.add_post("/api/rounds/{round_id}/recording/markers", add_recording_marker)
    app.router.add_post("/api/rounds/{round_id}/recording/clips", create_recording_clip)
    app.router.add_get("/api/rounds/{round_id}/recording/clips/{clip_id}.mp4", recording_clip)
    app.router.add_get("/api/rounds/{round_id}/recording/clips/{clip_id}.jsonl", recording_clip_export)
    app.router.add_get("/api/rounds/{round_id}/recording/clips/{clip_id}/raw.jsonl", recording_clip_raw_export)
    app.router.add_post("/api/rounds/{round_id}/recording/clips/{clip_id}/analysis-round", create_clip_analysis_round)
    app.router.add_get("/exports/rounds/{round_id}/result.png", round_result_png)
    app.router.add_post("/api/rounds/{round_id}/precise-result", precise_upload)
    app.router.add_delete("/api/rounds/{round_id}", delete_round)
    app.router.add_delete("/api/activities/{activity}", delete_activity)
    app.router.add_post("/api/command", command)
    app.router.add_post("/api/feishu/push-card", push_feishu_card)
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
    await service.stop_background_tasks()
    await service.collector.stop()
    await service.recorder.stop_all()
    if service.feishu_connection is not None:
        await asyncio.to_thread(service.feishu_connection.stop)
    service.collector.fingerprints.close()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(amain())
