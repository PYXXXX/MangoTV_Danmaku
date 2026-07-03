import asyncio
import json
import tempfile
import unittest
from pathlib import Path

try:
    from server.vote_server import VoteService
except ModuleNotFoundError:
    VoteService = None


@unittest.skipIf(VoteService is None, "aiohttp 未安装，跳过服务端集成测试")
class ServerPreciseResultTest(unittest.IsolatedAsyncioTestCase):
    async def test_upload_sets_precise_as_public_default(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "storage": {"directory": str(Path(temp) / "data")},
                "mgtv": {"dedup_db_path": str(Path(temp) / "fingerprints.sqlite3")},
                "vote": {
                    "activity": "歌手 2026",
                    "multi_candidate_policy": "all",
                    "candidates": [
                        {"id": "c1", "name": "甲", "aliases": ["甲"]},
                        {"id": "c2", "name": "乙", "aliases": ["乙"]},
                    ],
                },
                "github": {"enabled": False},
                "feishu": {"enabled": False},
            }
            service = VoteService(config)
            try:
                self.assertFalse(service.start_feishu_connection(asyncio.get_running_loop()))
                service.feishu.config["allowed_open_ids"] = ["ou_operator"]
                service.feishu.config["allowed_chat_ids"] = ["oc_control_room"]
                self.assertTrue(service.feishu.is_allowed("ou_operator", "oc_control_room"))
                self.assertFalse(service.feishu.is_allowed("ou_other", "oc_control_room"))
                self.assertFalse(service.feishu.is_allowed("ou_operator", "oc_other"))
                meta = await service.store.create_round("歌手 2026", "第一轮", "", service.default_candidates, "all")
                meta = await service.store.stop_active()
                payload = {
                    "schemaVersion": 1,
                    "resultType": "precise",
                    "sessionId": meta.id,
                    "activity": meta.activity,
                    "sessionName": meta.name,
                    "generatedAt": meta.updatedAt,
                    "counts": [
                        {"candidateId": "c1", "name": "甲", "votes": 8},
                        {"candidateId": "c2", "name": "乙", "votes": 5},
                    ],
                    "audit": {
                        "inputMessages": 0,
                        "cleanMessages": 0,
                        "ruleAcceptedMessages": 0,
                        "semanticReviewedMessages": 0,
                        "unresolvedReviewMessages": 0,
                        "invalidDecisionLines": 0,
                    },
                }
                content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                updated, message = await service.publish_precise_file(meta.id, "precise_result.json", content)
                self.assertEqual(message, "GitHub 同步未启用")
                self.assertEqual(updated.preciseResult["voteCounts"], {"c1": 8, "c2": 5})
                public = service.store.public_state()["sessions"][0]
                self.assertEqual(public["defaultResultType"], "precise")
                self.assertEqual(public["results"]["rough"]["voteCounts"], {"c1": 0, "c2": 0})
                self.assertEqual(public["results"]["precise"]["voteCounts"], {"c1": 8, "c2": 5})
            finally:
                service.collector.fingerprints.close()
