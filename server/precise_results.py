"""Dependency-free parser and validator for operator-uploaded precise results."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUDIT_FIELDS = (
    "inputMessages", "cleanMessages", "ruleAcceptedMessages",
    "semanticReviewedMessages", "unresolvedReviewMessages", "invalidDecisionLines",
)


def normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text or ""))).strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_precise_result(filename: str, content: bytes) -> dict[str, Any]:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"JSON 文件无效：{exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON 顶层必须是对象")
        return payload
    if suffix == ".xml":
        if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
            raise ValueError("XML 不允许包含 DOCTYPE 或 ENTITY")
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError(f"XML 文件无效：{exc}") from exc
        if root.tag != "preciseResult":
            raise ValueError("XML 根节点必须是 preciseResult")
        session, counts, audit = root.find("session"), root.find("counts"), root.find("audit")
        if session is None or counts is None or audit is None:
            raise ValueError("XML 缺少 session、counts 或 audit 节点")
        try:
            return {
                "schemaVersion": int(root.get("schemaVersion", "0")),
                "resultType": root.get("resultType", ""),
                "sessionId": session.get("id", ""),
                "activity": session.get("activity", ""),
                "sessionName": session.get("name", ""),
                "generatedAt": session.get("generatedAt", ""),
                "counts": [
                    {"candidateId": item.get("id", ""), "name": item.get("name", ""), "votes": int(item.get("votes", ""))}
                    for item in counts.findall("candidate")
                ],
                "audit": {key: int(audit.get(key, "0")) for key in AUDIT_FIELDS},
            }
        except ValueError as exc:
            raise ValueError("XML 的版本、票数与审核统计必须是整数") from exc
    raise ValueError("只接受 .json 或 .xml 文件")


def validate_precise_result(payload: dict[str, Any], meta: Any, content: bytes, filename: str) -> dict[str, Any]:
    if payload.get("schemaVersion") != 1 or payload.get("resultType") != "precise":
        raise ValueError("文件必须声明 schemaVersion=1 且 resultType=precise")
    if normalize(payload.get("sessionId")) != meta.id:
        raise ValueError(f"sessionId 与所选场次不一致，应为 {meta.id}")
    if normalize(payload.get("activity")) != meta.activity:
        raise ValueError(f"activity 与所选活动不一致，应为 {meta.activity}")
    if normalize(payload.get("sessionName")) != meta.name:
        raise ValueError("sessionName 与所选场次名称不一致")
    counts, audit = payload.get("counts"), payload.get("audit")
    if not isinstance(counts, list) or not isinstance(audit, dict):
        raise ValueError("文件缺少 counts 数组或 audit 对象")
    expected = {candidate.id: candidate for candidate in meta.candidates}
    vote_counts: dict[str, int] = {}
    for row in counts:
        if not isinstance(row, dict):
            raise ValueError("counts 中的每一项必须是对象")
        candidate_id = normalize(row.get("candidateId"))
        if candidate_id not in expected or candidate_id in vote_counts:
            raise ValueError(f"候选人 ID 无效或重复：{candidate_id}")
        if normalize(row.get("name")) != expected[candidate_id].name:
            raise ValueError(f"候选人 {candidate_id} 的姓名不匹配")
        votes = row.get("votes")
        if isinstance(votes, bool) or not isinstance(votes, int) or votes < 0:
            raise ValueError(f"候选人 {candidate_id} 的 votes 必须是非负整数")
        vote_counts[candidate_id] = votes
    if set(vote_counts) != set(expected):
        raise ValueError("counts 必须完整包含本场全部候选人")
    normalized_audit: dict[str, int] = {}
    for key in AUDIT_FIELDS:
        value = audit.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"audit.{key} 必须是非负整数")
        normalized_audit[key] = value
    if normalized_audit["inputMessages"] != meta.messageCount:
        raise ValueError(f"audit.inputMessages 必须等于本场弹幕样本数 {meta.messageCount}")
    if normalized_audit["cleanMessages"] > normalized_audit["inputMessages"]:
        raise ValueError("audit.cleanMessages 不能超过 inputMessages")
    if normalized_audit["ruleAcceptedMessages"] + normalized_audit["semanticReviewedMessages"] > normalized_audit["cleanMessages"]:
        raise ValueError("规则判定数与语义审核数之和不能超过 cleanMessages")
    if normalized_audit["unresolvedReviewMessages"] or normalized_audit["invalidDecisionLines"]:
        raise ValueError("仍有未完成审核或无效决策，不能作为精确结果发布")
    generated_at = normalize(payload.get("generatedAt")) or now_iso()
    try:
        datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generatedAt 必须是 ISO-8601 时间") from exc
    return {
        "schemaVersion": 1,
        "resultType": "precise",
        "sessionId": meta.id,
        "activity": meta.activity,
        "sessionName": meta.name,
        "generatedAt": generated_at,
        "voteCounts": vote_counts,
        "audit": normalized_audit,
        "source": {
            "format": Path(filename).suffix.lower().lstrip("."),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    }
