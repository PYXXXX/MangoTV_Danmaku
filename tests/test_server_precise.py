import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    from server.vote_server import DanmakuMessage, VoteService
except ModuleNotFoundError:
    VoteService = None
    DanmakuMessage = None


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

    async def test_delete_round_and_activity_remove_stopped_sessions(self):
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
                first = await service.store.create_round("歌手 2026", "第一轮", "", service.default_candidates, "all")
                await service.store.stop_active()
                second = await service.store.create_round("歌手 2026", "第二轮", "", service.default_candidates, "all")
                await service.store.stop_active()
                other = await service.store.create_round("另一活动", "第一轮", "", service.default_candidates, "all")
                await service.store.stop_active()

                deleted, publish_url = await service.delete_round(first.id)
                self.assertEqual(deleted.id, first.id)
                self.assertEqual(publish_url, "GitHub 同步未启用")
                self.assertNotIn(first.id, service.store.rounds)
                self.assertFalse((Path(temp) / "data" / "rounds" / f"{first.id}.jsonl").exists())

                metas, publish_url = await service.delete_activity("歌手 2026")
                self.assertEqual([meta.id for meta in metas], [second.id])
                self.assertEqual(publish_url, "GitHub 同步未启用")
                self.assertNotIn(second.id, service.store.rounds)
                self.assertIn(other.id, service.store.rounds)
                self.assertEqual([item["activity"] for item in service.public_state()["sessions"]], ["另一活动"])
            finally:
                service.collector.fingerprints.close()

    async def test_delete_running_round_is_rejected(self):
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
                with self.assertRaisesRegex(ValueError, "正在采集"):
                    await service.delete_round(meta.id)
                with self.assertRaisesRegex(ValueError, "仍有场次正在采集"):
                    await service.delete_activity("歌手 2026")
                self.assertIn(meta.id, service.store.rounds)
            finally:
                service.collector.fingerprints.close()

    async def test_delete_round_can_skip_public_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "storage": {"directory": str(Path(temp) / "data")},
                "mgtv": {"dedup_db_path": str(Path(temp) / "fingerprints.sqlite3")},
                "vote": {
                    "activity": "歌手 2026",
                    "multi_candidate_policy": "all",
                    "candidates": [{"id": "c1", "name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": True},
                "feishu": {"enabled": False},
            }
            service = VoteService(config)
            calls = []

            async def fake_publish(force=False, result_kind="rough"):
                calls.append({"force": force, "result_kind": result_kind})
                return "published"

            service.publisher.publish = fake_publish
            try:
                meta = await service.store.create_round("歌手 2026", "第一轮", "", service.default_candidates, "all")
                await service.store.stop_active()
                deleted, publish_url = await service.delete_round(meta.id, publish=False)
                self.assertEqual(deleted.id, meta.id)
                self.assertEqual(publish_url, "")
                self.assertEqual(calls, [])
            finally:
                service.collector.fingerprints.close()

    async def test_raw_danmaku_track_exports_observed_items(self):
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
                meta = await service.store.create_round("歌手 2026", "第一轮", "https://example.com/live", service.default_candidates, "all")
                await service.store.append_raw_danmaku_batch(
                    meta.id,
                    poll_seq=1,
                    observed_at="2026-07-05T01:00:00Z",
                    room_id="liveshow-5366",
                    url="https://example.com/live",
                    items=[{"u": "user-1", "n": "观众", "c": "甲加油", "extra": {"x": 1}}],
                )
                exported = service.store.export_round_raw_jsonl(meta.id)
                self.assertIn('"rawTrack":"observed_api_items"', exported)
                self.assertIn('"pollSeq":1', exported)
                self.assertIn('"roomId":"liveshow-5366"', exported)
                self.assertIn('"c":"甲加油"', exported)
                self.assertIn('"extra":{"x":1}', exported)
            finally:
                service.collector.fingerprints.close()

    async def test_recording_manager_skips_when_enabled_without_stream_url_and_accepts_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "storage": {"directory": str(Path(temp) / "data")},
                "recording": {"enabled": True, "stream_url": "", "directory": str(Path(temp) / "recordings")},
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
                record = await service.recorder.start(meta, "")
                self.assertEqual(record["status"], "skipped")
                self.assertIn("未配置录制源", record["error"])
                marker = service.recorder.add_marker(meta.id, "高能片段", 12.5)
                self.assertEqual(marker["label"], "高能片段")
                self.assertEqual(marker["atSeconds"], 12.5)
                self.assertEqual(service.recorder.public_records()[0]["clipCount"], 0)
            finally:
                service.collector.fingerprints.close()

    async def test_recording_clip_exports_danmaku_and_creates_analysis_round(self):
        with tempfile.TemporaryDirectory() as temp:
            config = {
                "storage": {"directory": str(Path(temp) / "data")},
                "recording": {"enabled": True, "stream_url": "", "directory": str(Path(temp) / "recordings")},
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
                meta = await service.store.create_round("歌手 2026", "全程录制", "", service.default_candidates, "all")
                for seconds, content in [(5, "片段前"), (15, "甲中间"), (25, "片段后")]:
                    await service.store.append_message(
                        meta.id,
                        DanmakuMessage(
                            ts=f"2026-07-05T01:00:{seconds:02d}Z",
                            nickname="观众",
                            content=content,
                            matches=["c1"] if "甲" in content else [],
                            votes=["c1"] if "甲" in content else [],
                            needsReview=False,
                            url="https://www.mgtv.com/z/1001668/5366.html",
                        ),
                    )
                await service.store.append_raw_danmaku_batch(
                    meta.id,
                    poll_seq=1,
                    observed_at="2026-07-05T01:00:15Z",
                    room_id="liveshow-5366",
                    url=meta.pageUrl,
                    items=[{"c": "甲中间"}],
                )
                await service.store.append_raw_danmaku_batch(
                    meta.id,
                    poll_seq=2,
                    observed_at="2026-07-05T01:00:25Z",
                    room_id="liveshow-5366",
                    url=meta.pageUrl,
                    items=[{"c": "片段后"}],
                )
                await service.store.stop_active()
                service.recorder.records[meta.id] = {
                    "roundId": meta.id,
                    "activity": meta.activity,
                    "roundName": meta.name,
                    "sourceUrl": "",
                    "path": str(Path(temp) / "recordings" / meta.id / "recording.mp4"),
                    "status": "finished",
                    "startedAt": "2026-07-05T01:00:00Z",
                    "endedAt": "2026-07-05T01:01:00Z",
                    "error": "",
                    "markers": [],
                    "clips": [{
                        "id": "clip-1",
                        "label": "第一段",
                        "startSeconds": 10,
                        "endSeconds": 20,
                        "path": str(Path(temp) / "recordings" / meta.id / "clip-1.mp4"),
                        "url": f"/api/rounds/{meta.id}/recording/clips/clip-1.mp4",
                        "createdAt": "2026-07-05T01:02:00Z",
                    }],
                }

                exported, filename = service.export_recording_clip_danmaku(meta.id, "clip-1")
                self.assertIn("clip-1", filename)
                self.assertIn("甲中间", exported)
                self.assertNotIn("片段前", exported)
                self.assertNotIn("片段后", exported)
                raw_exported, _ = service.export_recording_clip_danmaku(meta.id, "clip-1", raw=True)
                self.assertIn('"rawTrack":"observed_api_items"', raw_exported)
                self.assertIn("甲中间", raw_exported)
                self.assertNotIn("片段后", raw_exported)

                derived = await service.create_analysis_round_from_clip(meta.id, "clip-1")
                self.assertEqual(derived.status, "stopped")
                self.assertEqual(derived.messageCount, 1)
                self.assertEqual(derived.voteCounts["c1"], 1)
                self.assertIn("第一段", derived.name)
                derived_export = service.store.export_round_jsonl(derived.id)
                self.assertIn('"sourceRoundId"', derived_export)
                self.assertIn("甲中间", derived_export)
            finally:
                service.collector.fingerprints.close()

    async def test_mgtv_source_detection_persists_stream_but_redacts_response(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = {
                "storage": {"directory": str(root / "data")},
                "recording": {"enabled": True, "stream_url": "", "preferred_quality": "1080P", "directory": str(root / "recordings")},
                "mgtv": {"url": "https://www.mgtv.com/z/1001668/5366.html", "dedup_db_path": str(root / "fingerprints.sqlite3")},
                "vote": {
                    "activity": "歌手 2026",
                    "multi_candidate_policy": "all",
                    "candidates": [{"id": "c1", "name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": False},
                "feishu": {"enabled": False},
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            service = VoteService(config, config_path=config_path)

            async def fake_detect_stream(page_url, preferred_quality):
                self.assertEqual(page_url, config["mgtv"]["url"])
                self.assertEqual(preferred_quality, "1080P")
                return {
                    "ok": True,
                    "streamUrl": "https://secure.example.com/live.m3u8?token=secret",
                    "actualQuality": "1080P",
                    "message": "已检测到播放源。",
                }

            service.mgtv_auth.detect_stream = fake_detect_stream
            try:
                result = await service.detect_mgtv_recording_source(quality="1080P")
                self.assertEqual(result["streamUrl"], "已解析，已隐藏")
                self.assertNotIn("secret", json.dumps(result))
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["recording"]["stream_url"], "https://secure.example.com/live.m3u8?token=secret")
                self.assertEqual(service.recorder.config["stream_url"], "https://secure.example.com/live.m3u8?token=secret")
            finally:
                service.collector.fingerprints.close()

    async def test_feishu_delete_round_action_removes_selected_round(self):
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
            try:
                meta = await service.store.create_round("歌手 2026", "第一轮", "", service.default_candidates, "all")
                await service.store.stop_active()
                service.user_selection["ou_operator"] = meta.id
                card = await service.handle_feishu_card_action("delete_round", "ou_operator", "oc_control_room")
                self.assertNotIn(meta.id, service.store.rounds)
                self.assertNotIn("ou_operator", service.user_selection)
                self.assertIn("已删除场次：歌手 2026 / 第一轮", str(card))
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
