#!/usr/bin/env python3
"""Merge deterministic votes with compact Codex review decisions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path} 第 {line_number} 行 JSON 无效: {exc}") from exc
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="合并规则票与 Codex 语义审核结果")
    parser.add_argument("directory", type=Path, nargs="?", default=Path("output"))
    args = parser.parse_args()

    preliminary = json.loads((args.directory / "preliminary.json").read_text(encoding="utf-8"))
    accepted = read_jsonl(args.directory / "accepted.jsonl")
    decisions = read_jsonl(args.directory / "codex_decisions.jsonl")
    candidates = {item["id"]: item for item in preliminary["candidates"]}
    review_ids = {
        item["i"]
        for path in sorted((args.directory / "review_batches").glob("batch-*.jsonl"))
        for item in read_jsonl(path)
    }

    decision_by_id: dict[int, dict[str, Any]] = {}
    invalid: list[dict[str, Any]] = []
    for decision in decisions:
        record_id = decision.get("i")
        candidate_ids = decision.get("c")
        if record_id not in review_ids or not isinstance(candidate_ids, list) or any(cid not in candidates for cid in candidate_ids):
            invalid.append(decision)
            continue
        decision_by_id[record_id] = decision

    counts: Counter[str] = Counter()
    for record in accepted:
        counts.update(record.get("c", []))
    for decision in decision_by_id.values():
        counts.update(set(decision.get("c", [])))

    ranking = sorted(
        ({"id": cid, "name": item["name"], "votes": counts[cid]} for cid, item in candidates.items()),
        key=lambda item: (-item["votes"], item["name"]),
    )
    result = {
        "sessionId": preliminary.get("sessionId"),
        "sessionName": preliminary.get("sessionName", "未命名场次"),
        "ranking": ranking,
        "ruleAcceptedMessages": len(accepted),
        "semanticReviewedMessages": len(decision_by_id),
        "unresolvedReviewMessages": len(review_ids - decision_by_id.keys()),
        "invalidDecisionLines": len(invalid),
    }
    (args.directory / "final_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    report = ["# 弹幕投票统计", "", f"场次：{result['sessionName']}（`{result['sessionId']}`）", "", "| 排名 | 艺人 | 票数 |", "|---:|---|---:|"]
    report.extend(f"| {index} | {item['name']} | {item['votes']} |" for index, item in enumerate(ranking, 1))
    report.extend([
        "",
        f"规则直接判定：{result['ruleAcceptedMessages']} 条；Codex 语义审核：{result['semanticReviewedMessages']} 条；未完成审核：{result['unresolvedReviewMessages']} 条。",
    ])
    (args.directory / "final_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
