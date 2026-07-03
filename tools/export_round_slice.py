#!/usr/bin/env python3
"""Export one server-side round slice from the append-only raw message log."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_state(data_dir: Path) -> dict[str, Any]:
    state_path = data_dir / "state.json"
    if not state_path.exists():
        raise FileNotFoundError(f"找不到 {state_path}")
    return json.loads(state_path.read_text(encoding="utf-8"))


def find_round(state: dict[str, Any], query: str | None) -> dict[str, Any]:
    rounds = state.get("rounds", [])
    if not rounds:
        raise ValueError("没有可导出的场次")
    if not query:
        return rounds[0]
    for item in rounds:
        if query == item.get("id") or query in item.get("name", ""):
            return item
    raise ValueError(f"找不到场次：{query}")


def iter_records(data_dir: Path, round_meta: dict[str, Any], global_seq: int):
    raw_path = data_dir / "raw_messages.jsonl"
    if not raw_path.exists():
        return
    start = int(round_meta.get("sliceStartSeq") or 1)
    end = int(round_meta.get("sliceEndSeq") or global_seq)
    round_id = round_meta["id"]
    with raw_path.open("r", encoding="utf-8") as handle:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="导出服务器模式的某个场次切片 JSONL")
    parser.add_argument("--data-dir", type=Path, default=Path("server/data"), help="服务器数据目录")
    parser.add_argument("--round", dest="round_query", help="场次 ID 或名称关键词；默认导出最新场次")
    parser.add_argument("--out", type=Path, required=True, help="输出 JSONL 文件")
    args = parser.parse_args()

    state = load_state(args.data_dir)
    round_meta = find_round(state, args.round_query)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output:
        output.write(json.dumps({"type": "meta", **round_meta}, ensure_ascii=False, separators=(",", ":")) + "\n")
        for record in iter_records(args.data_dir, round_meta, int(state.get("globalSeq") or 0)):
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"已导出：{round_meta.get('name')} -> {args.out}")


if __name__ == "__main__":
    main()

