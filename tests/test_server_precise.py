import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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

    async def test_feishu_start_form_uses_submitted_fields_and_config_default(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "storage": {"directory": str(Path(temp) / "data")},
                "mgtv": {
                    "url": "https://www.mgtv.com/z/1001668/5366.html",
                    "dedup_db_path": str(Path(temp) / "fingerprints.sqlite3"),
                },
                "vote": {
                    "activity": "歌手 2026",
                    "multi_candidate_policy": "all",
                    "candidates": [{"id": "c1", "name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": False},
                "feishu": {
                    "enabled": True,
                    "allowed_open_ids": ["ou_operator"],
                    "allowed_chat_ids": ["oc_control_room"],
                },
            }
            service = VoteService(config)
            calls = []

            async def fake_start_round(name, url=None, activity=None):
                calls.append({"name": name, "url": url, "activity": activity})
                return SimpleNamespace(id="round-1", name=name, activity=activity)

            service.start_round = fake_start_round
            try:
                card = await service.handle_feishu_card_action(
                    "start_custom",
                    "ou_operator",
                    "oc_control_room",
                    form_value={
                        "activity": "",
                        "round_name": "突围赛",
                        "live_url": "https://www.mgtv.com/z/1001668/5366.html",
                    },
                )
                self.assertEqual(calls, [{
                    "name": "突围赛",
                    "url": "https://www.mgtv.com/z/1001668/5366.html",
                    "activity": "歌手 2026",
                }])
                self.assertEqual(service.user_selection["ou_operator"], "round-1")
                self.assertIn("已开始：歌手 2026 / 突围赛", str(card))
            finally:
                service.collector.fingerprints.close()

    async def test_round_result_png_export_and_public_url(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "listen": {"public_base_url": "https://danmaku.example.com"},
                "storage": {"directory": str(Path(temp) / "data")},
                "mgtv": {"dedup_db_path": str(Path(temp) / "fingerprints.sqlite3")},
                "vote": {
                    "activity": "歌手 2026",
                    "multi_candidate_policy": "all",
                    "candidates": [{"id": "c1", "name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": False},
                "feishu": {"enabled": False},
            }
            service = VoteService(config)
            try:
                meta = await service.store.create_round("歌手 2026", "第一轮", "", service.default_candidates, "all")
                body, filename = service.export_round_result_png(meta.id, "rough")
                self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual(filename, f"mgtv-result-{meta.id}-rough.png")
                self.assertEqual(
                    service.round_result_png_url(meta.id, "rough"),
                    f"https://danmaku.example.com/exports/rounds/{meta.id}/result.png?result=rough",
                )
            finally:
                service.collector.fingerprints.close()

    async def test_feishu_send_png_action_uploads_image_to_current_chat(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "storage": {"directory": str(Path(temp) / "data")},
                "mgtv": {"dedup_db_path": str(Path(temp) / "fingerprints.sqlite3")},
                "vote": {
                    "activity": "歌手 2026",
                    "multi_candidate_policy": "all",
                    "candidates": [{"id": "c1", "name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": False},
                "feishu": {
                    "enabled": True,
                    "allowed_open_ids": ["ou_operator"],
                    "allowed_chat_ids": ["oc_control_room"],
                },
            }
            service = VoteService(config)
            sent = []

            async def fake_send_image(receive_id, receive_id_type, content, filename="result.png"):
                sent.append({
                    "receive_id": receive_id,
                    "receive_id_type": receive_id_type,
                    "content": content,
                    "filename": filename,
                })

            service.feishu.send_image = fake_send_image
            try:
                meta = await service.store.create_round("歌手 2026", "第一轮", "", service.default_candidates, "all")
                await service.store.stop_active()
                card = await service.handle_feishu_card_action("send_png", "ou_operator", "oc_control_room")
                self.assertEqual(len(sent), 1)
                self.assertEqual(sent[0]["receive_id"], "oc_control_room")
                self.assertEqual(sent[0]["receive_id_type"], "chat_id")
                self.assertTrue(sent[0]["content"].startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual(sent[0]["filename"], f"mgtv-result-{meta.id}-rough.png")
                self.assertIn("已发送 第一轮 的粗略结果 PNG 到当前会话", str(card))
            finally:
                service.collector.fingerprints.close()

    async def test_stopped_round_keeps_clean_name_and_exposes_time_range(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "storage": {"directory": str(Path(temp) / "data")},
                "mgtv": {"dedup_db_path": str(Path(temp) / "fingerprints.sqlite3")},
                "vote": {
                    "activity": "歌手 2026",
                    "multi_candidate_policy": "all",
                    "candidates": [{"id": "c1", "name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": False},
                "feishu": {"enabled": False},
            }
            service = VoteService(config)
            try:
                meta = await service.store.create_round("歌手 2026", "第一轮", "", service.default_candidates, "all")
                stopped = await service.store.stop_active()
                self.assertEqual(stopped.name, "第一轮")
                self.assertEqual(stopped.baseName, "第一轮")
                public = service.public_state()["sessions"][0]
                self.assertEqual(public["displayName"], "第一轮")
                self.assertIn("timeRange", public)
                self.assertIn(" – ", public["timeRange"])
                exported = service.store.export_round_jsonl(meta.id).splitlines()[0]
                exported_meta = json.loads(exported)
                self.assertEqual(exported_meta["name"], "第一轮")
                self.assertEqual(exported_meta["displayName"], "第一轮")
                self.assertIn("compactTimeRange", exported_meta)
            finally:
                service.collector.fingerprints.close()

    async def test_legacy_embedded_time_range_name_is_cleaned_on_load(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data_dir = root / "data"
            data_dir.mkdir()
            state = {
                "schemaVersion": 1,
                "updatedAt": "2026-07-05T03:32:40.783Z",
                "activeRoundId": None,
                "globalSeq": 0,
                "roundOrder": ["round-1"],
                "rounds": [
                    {
                        "id": "round-1",
                        "activity": "歌手 2026",
                        "baseName": "第 1 轮",
                        "name": "第 1 轮 · 20260705 11:32:26-20260705 11:32:40",
                        "status": "stopped",
                        "startedAt": "2026-07-05T03:32:26.324Z",
                        "updatedAt": "2026-07-05T03:32:40.783Z",
                        "stoppedAt": "2026-07-05T03:32:40.783Z",
                        "pageUrl": "",
                        "pageTitle": "",
                        "candidates": [{"id": "c1", "name": "甲", "aliases": ["甲"]}],
                        "multiCandidatePolicy": "all",
                        "voteCounts": {"c1": 0},
                        "messageCount": 0,
                        "reviewCount": 0,
                        "preciseResult": None,
                        "precisePublishedAt": None,
                        "sliceStartSeq": 1,
                        "sliceEndSeq": 0,
                        "sliceStartTime": "2026-07-05T03:32:26.324Z",
                        "sliceEndTime": "2026-07-05T03:32:40.783Z",
                    }
                ],
            }
            (data_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
            config = {
                "storage": {"directory": str(data_dir)},
                "mgtv": {"dedup_db_path": str(root / "fingerprints.sqlite3")},
                "vote": {
                    "activity": "歌手 2026",
                    "multi_candidate_policy": "all",
                    "candidates": [{"id": "c1", "name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": False},
                "feishu": {"enabled": False},
            }
            service = VoteService(config)
            try:
                meta = service.store.require_round("round-1")
                self.assertEqual(meta.name, "第 1 轮")
                public = service.public_state()["sessions"][0]
                self.assertEqual(public["displayName"], "第 1 轮")
                self.assertEqual(public["timeRange"], "2026/07/05 11:32:26 – 11:32:40")
            finally:
                service.collector.fingerprints.close()
