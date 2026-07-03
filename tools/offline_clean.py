#!/usr/bin/env python3
"""Clean an exported MGTV JSONL session and isolate only semantic edge cases."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


NEGATIVE_PATTERNS = (
    r"不投", r"别投", r"不要投", r"不支持", r"不选", r"别选", r"不留", r"别留",
    r"淘汰", r"出局", r"离开", r"不喜欢", r"不想.*留", r"凭什么.*留",
)
AMBIGUOUS_PATTERNS = (r"还是", r"谁", r"哪个", r"都留", r"都投", r"除了", r"vs", r"pk")
GENERIC_ALIAS_MARKERS = ("老师", "哥", "姐", "弟", "妹", "宝", "们")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = re.sub(r"[\u200b-\u200f\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([!！?？。~～])\1{2,}", r"\1\1", text)
    return text


def read_export(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行不是合法 JSON: {exc}") from exc
            if item.get("type") == "meta" and meta is None:
                meta = item
            elif item.get("type") == "message":
                messages.append(item)
    if not meta:
        raise ValueError("文件缺少 type=meta 的首行")
    if not meta.get("candidates"):
        raise ValueError("场次元数据中没有候选人配置")
    return meta, messages


def candidate_matches(text: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lowered = text.casefold()
    matches = []
    for candidate in candidates:
        aliases = [normalize(alias) for alias in candidate.get("aliases", []) if normalize(alias)]
        hit_aliases = [alias for alias in aliases if alias.casefold() in lowered]
        if hit_aliases:
            matches.append({"id": candidate["id"], "name": candidate["name"], "aliases": hit_aliases})
    return matches


def review_reason(text: str, matches: list[dict[str, Any]]) -> str | None:
    if len(matches) > 1:
        return "multiple_candidates"
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in NEGATIVE_PATTERNS):
        return "negation_or_rejection"
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in AMBIGUOUS_PATTERNS):
        return "question_or_comparison"
    match = matches[0]
    formal_name = normalize(match["name"])
    if formal_name not in text:
        aliases = match["aliases"]
        if any(len(alias) <= 1 or any(marker in alias for marker in GENERIC_ALIAS_MARKERS) for alias in aliases):
            return "generic_alias"
    return None


def compact_record(index: int, message: dict[str, Any], text: str, match_ids: list[str], reason: str) -> dict[str, Any]:
    # Nicknames and timestamps do not help semantic voting, so review batches omit them to save tokens.
    return {"i": index, "t": text, "m": match_ids, "q": reason}


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def make_batches(records: list[dict[str, Any]], max_chars: int) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for record in records:
        size = len(json.dumps(record, ensure_ascii=False, separators=(",", ":"))) + 1
        if current and current_chars + size > max_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(record)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def build_prompt(meta: dict[str, Any], context: str, batch_count: int) -> str:
    candidate_lines = "\n".join(
        f'- `{item["id"]}` = {item["name"]}；别名：{", ".join(item.get("aliases", []))}'
        for item in meta["candidates"]
    )
    context = context.strip() or "（未提供额外节目背景）"
    batch_instruction = (
        f"请依次读取 `review_batches/batch-001.jsonl` 至 `batch-{batch_count:03d}.jsonl`，"
        "把所有结果写入 `codex_decisions.jsonl`。不要修改其他文件。"
        if batch_count
        else "本场没有歧义样本，无需调用 Codex；可以直接运行合并脚本。"
    )
    return f"""# Codex 弹幕语义审核任务

目标：只审核规则引擎留下的歧义弹幕。明确票已经本地统计，不要重读 `clean_messages.jsonl` 或原始导出文件，以免浪费 token。

## 候选人

{candidate_lines}

## 节目背景与本场规则

{context}

## 判定口径

1. 只有弹幕明确表达对某位候选人的支持、投票、留下意愿，或按本场规则“提及即计票”且语境并非否定/比较/引用时，才输出该候选人 ID。
2. 否定、反讽、质疑、让其淘汰、只是在比较选项但没有明确选择，输出空数组。
3. 一条弹幕可以给多人计票，但必须逐人明确成立。
4. 不凭空补全未出现且上下文无法确认的人名。
5. 每条输入只输出一行 JSON，不写解释性段落。

输入字段：`i` 记录号，`t` 文本，`m` 规则命中的候选人，`q` 进入审核的原因。
输出字段：`i` 原记录号，`c` 最终计票候选人 ID 数组，`r` 简短原因码（support / reject / comparison / unclear / alias_error）。

输出示例：
`{{"i":12,"c":["c1"],"r":"support"}}`

{batch_instruction}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗芒果直播弹幕，并只把歧义样本交给 Codex")
    parser.add_argument("input", type=Path, help="扩展导出的 JSONL 文件")
    parser.add_argument("--context", type=Path, help="节目背景和计票口径的 UTF-8 文本/Markdown")
    parser.add_argument("--out", type=Path, default=Path("output"), help="输出目录，默认 output")
    parser.add_argument("--batch-chars", type=int, default=12000, help="每个 Codex 审核批次的最大字符数")
    args = parser.parse_args()

    meta, messages = read_export(args.input)
    args.out.mkdir(parents=True, exist_ok=True)
    batch_dir = args.out / "review_batches"
    batch_dir.mkdir(exist_ok=True)
    for stale in batch_dir.glob("batch-*.jsonl"):
        stale.unlink()

    clean_records: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for index, message in enumerate(messages, 1):
        text = normalize(message.get("content", ""))
        if not text:
            continue
        matches = candidate_matches(text, meta["candidates"])
        match_ids = [item["id"] for item in matches]
        clean_records.append({
            "i": index,
            "ts": message.get("ts", ""),
            "u": normalize(message.get("nickname", "")),
            "t": text,
            "m": match_ids,
        })
        if not matches:
            continue
        reason = review_reason(text, matches)
        if reason:
            review.append(compact_record(index, message, text, match_ids, reason))
            continue
        for candidate_id in match_ids:
            counts[candidate_id] += 1
        accepted.append({"i": index, "c": match_ids, "r": "rule_clear"})

    write_jsonl(args.out / "clean_messages.jsonl", clean_records)
    write_jsonl(args.out / "accepted.jsonl", accepted)
    batches = make_batches(review, max(1000, args.batch_chars))
    for number, batch in enumerate(batches, 1):
        write_jsonl(batch_dir / f"batch-{number:03d}.jsonl", batch)

    context = args.context.read_text(encoding="utf-8") if args.context else ""
    (args.out / "codex_prompt.md").write_text(build_prompt(meta, context, len(batches)), encoding="utf-8")
    summary = {
        "sessionId": meta.get("id"),
        "sessionName": meta.get("name", "未命名场次"),
        "inputMessages": len(messages),
        "cleanMessages": len(clean_records),
        "nonMatchingMessages": len(clean_records) - len(accepted) - len(review),
        "ruleAcceptedMessages": len(accepted),
        "reviewMessages": len(review),
        "reviewBatches": len(batches),
        "estimatedReviewInputTokensUpperBound": sum(len(json.dumps(item, ensure_ascii=False)) for item in review),
        "ruleVoteCounts": dict(counts),
        "candidates": meta["candidates"],
    }
    (args.out / "preliminary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
