import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.vote_server import (
    Candidate,
    DanmakuMessage,
    PersistentDeduper,
    StateStore,
    VoteService,
    append_jsonl_rotating,
)


class PersistenceHardeningTest(unittest.IsolatedAsyncioTestCase):
    async def test_batch_persistence_and_delete_purge_global_log(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StateStore(Path(temp))
            candidate = Candidate("c1", "甲", ["甲"])
            meta = await store.create_round("活动", "第一轮", "", [candidate], "all")
            messages = [
                DanmakuMessage(
                    ts=f"2026-07-10T00:00:0{index}Z",
                    nickname=f"用户{index}",
                    content="甲",
                    matches=["c1"],
                    votes=["c1"],
                    needsReview=False,
                    url="",
                )
                for index in range(3)
            ]
            await store.append_messages(meta.id, messages)
            self.assertEqual(meta.messageCount, 3)
            self.assertEqual(meta.voteCounts["c1"], 3)
            self.assertEqual(len(store.raw_messages_path.read_text(encoding="utf-8").splitlines()), 3)

            await store.stop_active()
            await store.delete_round(meta.id)
            self.assertEqual(store.raw_messages_path.read_text(encoding="utf-8"), "")

    async def test_png_cache_reuses_render_and_invalidates_on_round_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = {
                "storage": {"directory": str(root / "data")},
                "mgtv": {"dedup_db_path": str(root / "dedup.sqlite3")},
                "vote": {
                    "activity": "活动",
                    "multi_candidate_policy": "all",
                    "candidates": [{"id": "c1", "name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": False},
                "feishu": {"enabled": False},
            }
            service = VoteService(config)
            try:
                meta = await service.store.create_round("活动", "第一轮", "", service.default_candidates, "all")
                with patch("server.vote_server.render_result_png", return_value=(b"png", "result.png")) as render:
                    first = await service.export_round_result_png_async(meta.id, "rough")
                    second = await service.export_round_result_png_async(meta.id, "rough")
                    self.assertEqual(first, second)
                    self.assertEqual(render.call_count, 1)

                    await service.store.append_message(
                        meta.id,
                        DanmakuMessage("2026-07-10T00:00:00Z", "用户", "甲", ["c1"], ["c1"], False, ""),
                    )
                    await service.export_round_result_png_async(meta.id, "rough")
                    self.assertEqual(render.call_count, 2)
                self.assertNotIn("mgtvUrl", service.public_state()["defaults"])
                self.assertIn("mgtvUrl", service.public_state(include_private=True)["defaults"])
            finally:
                service.collector.fingerprints.close()
                service.recording_collector.fingerprints.close()


class UtilityHardeningTest(unittest.TestCase):
    def test_dedup_batch_preserves_duplicate_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            deduper = PersistentDeduper(Path(temp) / "dedup.sqlite3", hot_cache_size=100, max_records=1000)
            try:
                self.assertEqual(deduper.seen_or_add_many(["a", "b", "a"]), [False, False, True])
                self.assertEqual(deduper.seen_or_add_many(["a", "c"]), [True, False])
            finally:
                deduper.close()

    def test_system_event_log_rotates_and_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "system-events.jsonl"
            for index in range(30):
                append_jsonl_rotating(path, {"index": index, "detail": "x" * 80}, max_bytes=1024, backups=2)
            self.assertTrue(path.exists())
            self.assertTrue(path.with_name(path.name + ".1").exists())
            self.assertLessEqual(path.stat().st_size, 1024)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            latest = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(latest[-1]["index"], 29)


if __name__ == "__main__":
    unittest.main()
