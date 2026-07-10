import json
import tempfile
import unittest
from pathlib import Path

from server.vote_server import MgtvCollector, VoteService, synchronize_direct_mgtv_source


DIRECT_URL = "https://www.mgtv.com/z/1001668/5366.html?fpa=12437&fpos&lastp=ch_home&_source_=B"
ACTIVITY_URL = "https://www.mgtv.com/z/1001668.html?fpa=12437&fpos&lastp=ch_home&_source_=B"


class DirectLiveSourceTest(unittest.IsolatedAsyncioTestCase):
    def test_direct_url_repairs_stale_camera_room_and_monitor_url(self):
        config = {
            "mgtv": {
                "url": DIRECT_URL,
                "flag": "liveshow",
                "camera_id": "",
                "room_id": "liveshow-0000",
            },
            "monitor": {"url": ACTIVITY_URL},
        }

        changed, warning = synchronize_direct_mgtv_source(config)

        self.assertTrue(changed)
        self.assertIn("camera_id=5366", warning)
        self.assertEqual(config["mgtv"]["camera_id"], "5366")
        self.assertEqual(config["mgtv"]["room_id"], "liveshow-5366")
        self.assertEqual(config["monitor"]["url"], DIRECT_URL)

    def test_direct_monitor_url_overrides_old_mgtv_source(self):
        config = {
            "mgtv": {"url": ACTIVITY_URL, "flag": "liveshow", "room_id": "liveshow-0000"},
            "monitor": {"url": DIRECT_URL},
        }

        changed, _warning = synchronize_direct_mgtv_source(config)

        self.assertTrue(changed)
        self.assertEqual(config["mgtv"]["url"], DIRECT_URL)
        self.assertEqual(config["mgtv"]["camera_id"], "5366")
        self.assertEqual(config["mgtv"]["room_id"], "liveshow-5366")

    def test_collector_prefers_camera_in_url_over_stale_explicit_room(self):
        with tempfile.TemporaryDirectory() as temp:
            collector = MgtvCollector(
                {
                    "flag": "liveshow",
                    "room_id": "liveshow-0000",
                    "dedup_db_path": str(Path(temp) / "fingerprints.sqlite3"),
                },
                engine=None,
            )
            try:
                self.assertEqual(collector.resolve_room_id(DIRECT_URL), "liveshow-5366")
            finally:
                collector.fingerprints.close()

    async def test_monitor_does_not_auto_start_on_upcoming_preview_stream(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.json"
            config = {
                "storage": {"directory": str(root / "data")},
                "mgtv": {
                    "url": DIRECT_URL,
                    "flag": "liveshow",
                    "room_id": "liveshow-0000",
                    "dedup_db_path": str(root / "fingerprints.sqlite3"),
                },
                "monitor": {
                    "enabled": True,
                    "activity": "歌手 2026",
                    "url": ACTIVITY_URL,
                    "auto_detect_source": True,
                    "auto_record_video": True,
                    "auto_record_danmaku": True,
                    "feishu_notify": False,
                    "poll_seconds": 45,
                },
                "recording": {"enabled": False, "directory": str(root / "recordings"), "preferred_quality": "auto"},
                "vote": {
                    "activity": "歌手 2026",
                    "multi_candidate_policy": "all",
                    "candidates": [{"name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": False},
                "feishu": {"enabled": False},
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            service = VoteService(config, config_path=config_path)

            async def fake_detect(url: str, quality: str):
                self.assertEqual(url, DIRECT_URL)
                return {
                    "ok": True,
                    "cameraId": "5366",
                    "actualQuality": "576P",
                    "availableQualities": ["576P"],
                    "liveStatus": "upcoming",
                    "streamBeginTime": "2026-07-10 18:25:00",
                    "streamBeginTimestamp": 200,
                    "streamEndTime": "2026-07-11 05:00:00",
                    "streamEndTimestamp": 300,
                }

            service.detect_mgtv_recording_source = fake_detect
            try:
                result = await service.monitor_tick_once()
                self.assertEqual(result["state"]["status"], "waiting")
                self.assertEqual(result["state"]["cameraId"], "5366")
                self.assertEqual(result["state"]["roomId"], "liveshow-5366")
                self.assertIsNone(service.store.active_round_id)
                self.assertFalse(service.monitor_auto_started)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["monitor"]["url"], DIRECT_URL)
                self.assertEqual(saved["mgtv"]["room_id"], "liveshow-5366")

                realtime = await service.store.create_round(
                    "歌手 2026",
                    "实时第一轮",
                    DIRECT_URL,
                    service.default_candidates,
                    service.default_policy,
                )

                async def fake_live_detect(url: str, quality: str):
                    return {
                        "ok": True,
                        "cameraId": "5366",
                        "actualQuality": "576P",
                        "availableQualities": ["576P"],
                        "liveStatus": "live",
                    }

                async def fake_start(name: str, url: str, activity: str, **kwargs):
                    self.assertEqual(service.store.active_round_id, realtime.id)
                    self.assertTrue(kwargs["use_cached_recording_source"])
                    return await service.store.create_round(
                        activity,
                        name,
                        url,
                        service.default_candidates,
                        service.default_policy,
                        activate=False,
                        kind="recording",
                        visibility="private",
                    )

                service.detect_mgtv_recording_source = fake_live_detect
                service.start_independent_recording = fake_start
                result = await service.monitor_tick_once()
                self.assertEqual(result["state"]["status"], "running")
                self.assertTrue(service.monitor_auto_started)
                self.assertEqual(service.store.active_round_id, realtime.id)
            finally:
                await service.stop_background_tasks()


if __name__ == "__main__":
    unittest.main()
