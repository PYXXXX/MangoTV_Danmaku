import json
import tempfile
import unittest
from pathlib import Path

from server.runtime_settings import (
    SettingsValidationError,
    build_settings_update,
    public_settings,
    save_config_atomic,
)

try:
    from aiohttp.test_utils import AioHTTPTestCase
    from server.vote_server import VoteService, create_app
except ModuleNotFoundError:
    AioHTTPTestCase = None
    VoteService = None
    create_app = None


def base_config(root: Path) -> dict:
    return {
        "listen": {"host": "127.0.0.1", "port": 8080, "public_base_url": "http://127.0.0.1:8080"},
        "storage": {"directory": str(root / "data")},
        "recording": {
            "enabled": False,
            "stream_url": "https://secure.example.com/live.m3u8?token=secret",
            "preferred_quality": "1080P",
            "ffmpeg_path": "ffmpeg",
            "directory": str(root / "recordings"),
        },
        "monitor": {
            "enabled": False,
            "activity": "旧活动",
            "url": "https://www.mgtv.com/z/1.html",
            "auto_detect_source": True,
            "auto_record_video": False,
            "auto_record_danmaku": True,
            "feishu_notify": True,
            "poll_seconds": 45,
            "round_name": "",
        },
        "mgtv_auth": {
            "enabled": True,
            "cookies": [{"name": "HDCN", "value": "secret-cookie", "domain": ".mgtv.com"}],
            "cookie_header": "HDCN=secret-cookie; uuid=secret-uuid",
            "user_info": {"data": {"uid": "123", "nickname": "测试用户", "phone": "secret-phone"}},
        },
        "mgtv": {
            "url": "https://www.mgtv.com/z/1/2.html",
            "history_api": "https://lb.bz.mgtv.com/get_history",
            "flag": "liveshow",
            "room_id": "liveshow-2",
            "camera_id": "",
            "poll_seconds": 2,
            "reconnect_seconds": 5,
            "count_initial_history": False,
            "dedup_hot_cache_size": 2000,
            "dedup_max_records": 10000,
            "dedup_db_path": str(root / "fingerprints.sqlite3"),
        },
        "vote": {
            "activity": "旧活动",
            "multi_candidate_policy": "all",
            "candidates": [{"name": "甲", "aliases": ["甲"]}],
        },
        "github": {
            "enabled": False,
            "owner": "owner",
            "repo": "repo",
            "branch": "main",
            "path": "site/data/results.json",
            "token": "github_pat_real_secret_value_123456",
        },
        "feishu": {
            "enabled": False,
            "connection_mode": "websocket",
            "app_id": "cli_real",
            "app_secret": "feishu-secret",
            "verification_token": "verify-secret",
            "allowed_open_ids": ["ou_1"],
            "allowed_chat_ids": ["oc_1"],
            "public_results_url": "https://example.com/results",
        },
        "operator_auth": {
            "enabled": False,
            "password_hash": "",
            "session_secret": "",
            "session_hours": 12,
            "secure_cookie": True,
            "max_failures": 5,
            "failure_window_seconds": 300,
        },
    }


class RuntimeSettingsTest(unittest.TestCase):
    def test_public_settings_redacts_all_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            view = public_settings(config, {"restartRequired": False})
            rendered = json.dumps(view)
            self.assertNotIn("github_pat_real_secret", rendered)
            self.assertNotIn("feishu-secret", rendered)
            self.assertNotIn("verify-secret", rendered)
            self.assertNotIn("secret-cookie", rendered)
            self.assertNotIn("secret-uuid", rendered)
            self.assertNotIn("secure.example.com", rendered)
            self.assertNotIn("secret-phone", rendered)
            self.assertTrue(view["config"]["github"]["token_configured"])
            self.assertTrue(view["config"]["feishu"]["app_secret_configured"])
            self.assertTrue(view["config"]["recording"]["stream_url_configured"])
            self.assertTrue(view["config"]["mgtv_auth"]["cookie_configured"])

    def test_secret_fields_are_preserved_when_web_form_leaves_them_blank(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            update = build_settings_update(
                config,
                {
                    "github": {
                        "enabled": True,
                        "owner": "owner",
                        "repo": "repo",
                        "branch": "main",
                        "path": "site/data/results.json",
                        "token": "",
                    },
                    "feishu": {
                        "enabled": True,
                        "connection_mode": "websocket",
                        "app_id": "cli_real",
                        "app_secret": "",
                        "verification_token": "",
                        "allowed_open_ids": ["ou_1"],
                        "allowed_chat_ids": ["oc_1"],
                        "public_results_url": "https://example.com/results",
                    },
                },
                active_round=False,
            )
            self.assertEqual(update.config["github"]["token"], config["github"]["token"])
            self.assertEqual(update.config["feishu"]["app_secret"], config["feishu"]["app_secret"])

    def test_recording_stream_url_is_preserved_when_web_form_leaves_it_blank(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            update = build_settings_update(
                config,
                {
                    "recording": {
                        "enabled": True,
                        "stream_url": "",
                        "preferred_quality": "720P",
                        "ffmpeg_path": "ffmpeg",
                        "directory": config["recording"]["directory"],
                    },
                    "mgtv_auth": {"enabled": True},
                },
                active_round=False,
            )
            self.assertEqual(update.config["recording"]["stream_url"], config["recording"]["stream_url"])
            self.assertEqual(update.config["recording"]["preferred_quality"], "720P")
            self.assertEqual(update.config["mgtv_auth"]["cookie_header"], config["mgtv_auth"]["cookie_header"])

    def test_enabled_feishu_requires_explicit_allowlist(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            with self.assertRaisesRegex(SettingsValidationError, "allowed_open_ids"):
                build_settings_update(
                    config,
                    {
                        "feishu": {
                            "enabled": True,
                            "connection_mode": "websocket",
                            "app_id": "cli_real",
                            "app_secret": "secret",
                            "verification_token": "",
                            "allowed_open_ids": [],
                            "allowed_chat_ids": [],
                            "public_results_url": "https://example.com/results",
                        },
                    },
                    active_round=False,
                )

    def test_monitor_settings_are_validated_and_hot_reloadable(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            update = build_settings_update(
                config,
                {
                    "monitor": {
                        "enabled": True,
                        "activity": "歌手 2026",
                        "url": "https://www.mgtv.com/z/1001668.html?fpa=12437",
                        "auto_detect_source": True,
                        "auto_record_video": True,
                        "auto_record_danmaku": True,
                        "feishu_notify": False,
                        "poll_seconds": 30,
                        "round_name": "歌手 2026 全程录制",
                    }
                },
                active_round=False,
            )
            self.assertEqual(update.restart_fields, [])
            self.assertTrue(update.config["monitor"]["enabled"])
            self.assertEqual(update.config["monitor"]["activity"], "歌手 2026")
            self.assertEqual(update.config["monitor"]["poll_seconds"], 30)

    def test_enabled_monitor_requires_activity_url(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            config["monitor"] = {}
            config["mgtv"]["url"] = ""
            config["vote"]["activity"] = ""
            with self.assertRaisesRegex(SettingsValidationError, "活动名称"):
                build_settings_update(
                    config,
                    {"monitor": {"enabled": True, "activity": "", "url": ""}},
                    active_round=False,
                )

    def test_active_round_warns_but_accepts_next_round_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            update = build_settings_update(
                config,
                {
                    "vote": {
                        "activity": "新活动",
                        "multi_candidate_policy": "review",
                        "candidates": [{"name": "乙", "aliases": ["乙", "小乙"]}],
                    }
                },
                active_round=True,
            )
            self.assertEqual(update.config["vote"]["activity"], "新活动")
            self.assertTrue(any("下一场" in warning for warning in update.warnings))

    def test_duplicate_alias_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            with self.assertRaisesRegex(SettingsValidationError, "同时属于"):
                build_settings_update(
                    config,
                    {
                        "vote": {
                            "activity": "活动",
                            "multi_candidate_policy": "all",
                            "candidates": [
                                {"name": "甲", "aliases": ["共同"]},
                                {"name": "乙", "aliases": ["共同"]},
                            ],
                        }
                    },
                    active_round=False,
                )

    def test_restart_fields_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            config = base_config(Path(temp))
            update = build_settings_update(
                config,
                {
                    "listen": {
                        "host": "0.0.0.0",
                        "port": 9090,
                        "public_base_url": "https://example.com",
                    }
                },
                active_round=False,
            )
            self.assertEqual(update.restart_fields, ["listen.host", "listen.port"])

    def test_dedup_and_recording_paths_are_hot_reloadable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root)
            update = build_settings_update(
                config,
                {
                    "mgtv": {
                        **config["mgtv"],
                        "dedup_db_path": str(root / "new-fingerprints.sqlite3"),
                    },
                    "recording": {
                        **config["recording"],
                        "stream_url": "",
                        "directory": str(root / "new-recordings"),
                    },
                },
                active_round=False,
            )
            self.assertEqual(update.restart_fields, [])
            self.assertFalse(any("需重启" in warning for warning in update.warnings))

    def test_atomic_save_keeps_last_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text('{"version": 1}\n', encoding="utf-8")
            save_config_atomic(path, {"version": 2})
            self.assertEqual(json.loads(path.read_text()), {"version": 2})
            self.assertEqual(json.loads((Path(temp) / "config.json.bak").read_text()), {"version": 1})


@unittest.skipIf(VoteService is None, "aiohttp 未安装，跳过服务热重载测试")
class VoteServiceSettingsTest(unittest.IsolatedAsyncioTestCase):
    async def test_apply_settings_updates_future_round_defaults_and_persists(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            service = VoteService(config, config_path=config_path)
            try:
                current = await service.store.create_round(
                    "旧活动",
                    "当前场",
                    config["mgtv"]["url"],
                    service.default_candidates,
                    service.default_policy,
                )
                result = await service.apply_settings(
                    {
                        "vote": {
                            "activity": "新活动",
                            "multi_candidate_policy": "review",
                            "candidates": [{"name": "乙", "aliases": ["乙", "小乙"]}],
                        },
                        "mgtv": {
                            **config["mgtv"],
                            "poll_seconds": 1,
                            "dedup_hot_cache_size": 3000,
                        },
                    },
                    __import__("asyncio").get_running_loop(),
                )
                self.assertTrue(result["ok"])
                self.assertEqual(service.default_candidates[0].name, "乙")
                self.assertEqual(current.candidates[0].name, "甲")
                self.assertEqual(service.collector.config["poll_seconds"], 1)
                self.assertEqual(service.collector.fingerprints.hot.max_size, 3000)
                self.assertEqual(json.loads(config_path.read_text())["vote"]["activity"], "新活动")
            finally:
                service.collector.fingerprints.close()

    async def test_apply_settings_hot_switches_dedup_and_recording_directories_when_idle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = base_config(root)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            service = VoteService(config, config_path=config_path)
            try:
                new_dedup = root / "new-fingerprints.sqlite3"
                new_recordings = root / "new-recordings"
                result = await service.apply_settings(
                    {
                        "mgtv": {
                            **config["mgtv"],
                            "dedup_db_path": str(new_dedup),
                        },
                        "recording": {
                            **config["recording"],
                            "stream_url": "",
                            "directory": str(new_recordings),
                        },
                    },
                    __import__("asyncio").get_running_loop(),
                )
                self.assertTrue(result["ok"])
                self.assertFalse(result["restartRequired"])
                self.assertEqual(service.collector.fingerprints.db_path, new_dedup)
                self.assertEqual(service.recorder.directory, new_recordings)
                self.assertTrue(new_recordings.exists())
            finally:
                service.collector.fingerprints.close()


SettingsHttpBase = AioHTTPTestCase or unittest.IsolatedAsyncioTestCase


@unittest.skipIf(AioHTTPTestCase is None, "aiohttp 未安装，跳过配置 API 测试")
class SettingsApiHttpTest(SettingsHttpBase):
    async def get_application(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = base_config(root)
        self.config_path = root / "config.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.service = VoteService(self.config, config_path=self.config_path)
        self.service.repo_root = root
        frontend_dist = root / "frontend" / "dist"
        frontend_dist.mkdir(parents=True)
        (frontend_dist / "admin.html").write_text(
            "<!doctype html><html><head><title>Studio</title></head><body>React Studio</body></html>",
            encoding="utf-8",
        )
        (frontend_dist / "public.html").write_text(
            "<!doctype html><html><head><title>Public</title></head><body>Public Results</body></html>",
            encoding="utf-8",
        )
        return create_app(self.service)

    async def asyncTearDown(self):
        self.service.collector.fingerprints.close()
        await super().asyncTearDown()
        self.temp.cleanup()

    async def test_settings_api_redacts_and_hot_applies(self):
        response = await self.client.get("/api/settings")
        self.assertEqual(response.status, 200)
        current = await response.json()
        self.assertEqual(current["config"]["github"]["token"], "")
        self.assertTrue(current["config"]["github"]["token_configured"])

        response = await self.client.post(
            "/api/settings",
            json={
                "vote": {
                    "activity": "在线活动",
                    "multi_candidate_policy": "review",
                    "candidates": [{"name": "丙", "aliases": ["丙", "小丙"]}],
                }
            },
        )
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertTrue(result["ok"])
        self.assertEqual(self.service.default_candidates[0].name, "丙")
        self.assertEqual(json.loads(self.config_path.read_text())["vote"]["activity"], "在线活动")

    async def test_observability_and_alias_contracts(self):
        self.service.add_system_event("warn", "recording", "录制空间低", "/data/recordings 剩余不足")
        self.service.add_system_event("error", "recorder", "ffmpeg 失败", "ffmpeg exited with code 1")
        self.config_path.with_name(self.config_path.name + ".bak").write_text(
            json.dumps({"backup": True}),
            encoding="utf-8",
        )

        response = await self.client.get("/api/system/status")
        self.assertEqual(response.status, 200)
        status = await response.json()
        self.assertTrue(status["ok"])
        self.assertIn("host", status)
        self.assertIn("backup", status)
        self.assertTrue(status["backup"]["available"])
        self.assertEqual(status["backup"]["name"], "config.json.bak")
        self.assertIn("model", status["cpu"])
        self.assertIn("architecture", status["cpu"])
        self.assertIn("temperature", status["cpu"])
        self.assertIn("temperatureAvailable", status["cpu"])
        self.assertIn("available", status["cpu"]["temperature"])

        response = await self.client.get("/api/system/host")
        self.assertEqual(response.status, 200)
        host = await response.json()
        self.assertTrue(host["ok"])
        self.assertIn("hostname", host)
        self.assertIn("paths", host)
        self.assertIn("cpu", host)
        self.assertIn("backup", host)
        self.assertIn("model", host["cpu"])
        self.assertIn("temperature", host["cpu"])
        self.assertTrue(host["backup"]["available"])
        self.assertEqual(host["backup"]["name"], "config.json.bak")

        response = await self.client.get("/api/system/metrics?window=15m")
        self.assertEqual(response.status, 200)
        metrics = await response.json()
        self.assertTrue(metrics["ok"])
        self.assertGreaterEqual(len(metrics["points"]), 1)
        self.assertIn("cpuPercent", metrics["points"][-1])

        response = await self.client.get("/api/system/logs?level=ERROR&q=ffmpeg&limit=1")
        self.assertEqual(response.status, 200)
        logs = await response.json()
        self.assertEqual(logs["total"], 1)
        self.assertEqual(logs["events"][0]["source"], "recorder")
        self.assertIn("id", logs["events"][0])
        self.assertIn("host", logs["events"][0])
        self.assertEqual(logs["events"][0]["sourceLabel"], "录制进程")
        self.assertIn("remediation", logs["events"][0])
        self.assertIn("ERROR", logs["levels"])
        self.assertIn("ERROR", logs["availableLevels"])
        self.assertIn("recorder", logs["availableSources"])
        self.assertEqual(logs["levelCounts"]["ERROR"], 1)
        self.assertEqual(logs["sourceLabels"]["recorder"], "录制进程")
        self.assertGreaterEqual(len(logs["timeline"]), 1)

        response = await self.client.get("/api/system/logs?from=not-a-date")
        self.assertEqual(response.status, 400)

        response = await self.client.get("/api/system/logs/export?level=WARN")
        self.assertEqual(response.status, 200)
        self.assertIn("录制空间低", await response.text())

        response = await self.client.post("/api/system/logs/summary", json={"level": "ERROR"})
        self.assertEqual(response.status, 200)
        summary = await response.json()
        self.assertEqual(summary["levelCounts"]["ERROR"], 1)
        self.assertEqual(summary["latestError"]["source"], "recorder")

        response = await self.client.get("/api/feishu/status")
        self.assertEqual(response.status, 200)
        feishu_status = await response.json()
        self.assertTrue(feishu_status["ok"])
        self.assertIn("connected", feishu_status)

        response = await self.client.post("/api/feishu/test-card")
        self.assertEqual(response.status, 409)

        payload = {
            "vote": {
                "activity": "校验活动",
                "multi_candidate_policy": "all",
                "candidates": [{"name": "丁", "aliases": ["丁"]}],
            }
        }
        response = await self.client.post("/api/settings/validate", json=payload)
        self.assertEqual(response.status, 200)
        validation = await response.json()
        self.assertTrue(validation["ok"])
        self.assertIn("hotReload", validation)

        response = await self.client.post("/api/settings/diff", json=payload)
        self.assertEqual(response.status, 200)
        diff = await response.json()
        self.assertTrue(diff["ok"])

    async def test_studio_routes_serve_react_entrypoints(self):
        root = await self.client.get("/")
        self.assertEqual(root.status, 200)
        self.assertIn("React Studio", await root.text())

        legacy = await self.client.get("/legacy")
        self.assertEqual(legacy.status, 200)
        self.assertIn("直播运营工作台", await legacy.text())

        admin_root = await self.client.get("/admin")
        self.assertEqual(admin_root.status, 200)
        self.assertIn("React Studio", await admin_root.text())

        admin = await self.client.get("/studio")
        self.assertEqual(admin.status, 200)
        self.assertIn("React Studio", await admin.text())

        public = await self.client.get("/studio/public")
        self.assertEqual(public.status, 200)
        self.assertIn("Public Results", await public.text())

        public_data = await self.client.get("/studio/data/results.json")
        self.assertEqual(public_data.status, 200)
        self.assertIn("sessions", await public_data.text())

    async def test_round_end_api_stops_only_active_round(self):
        meta = await self.service.store.create_round(
            "旧活动",
            "第一轮",
            "https://www.mgtv.com/z/1/2.html",
            self.service.default_candidates,
            self.service.default_policy,
        )

        missing = await self.client.post("/api/rounds/missing/end", json={"publish": False})
        self.assertEqual(missing.status, 404)

        response = await self.client.post(f"/api/rounds/{meta.id}/end", json={"publish": False})
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertTrue(result["ok"])
        self.assertEqual(result["roundId"], meta.id)
        self.assertFalse(result["published"])
        self.assertIsNone(self.service.store.active_round_id)

    async def test_studio_activity_and_round_contracts(self):
        response = await self.client.get("/api/studio/bootstrap")
        self.assertEqual(response.status, 200)
        bootstrap = await response.json()
        self.assertTrue(bootstrap["ok"])
        self.assertIn("activities", bootstrap)
        self.assertFalse(bootstrap["monitor"]["config"]["enabled"])
        self.assertFalse(bootstrap["monitor"]["state"]["taskRunning"])

        response = await self.client.post(
            "/api/activities",
            json={
                "name": "歌手 2026",
                "url": "https://www.mgtv.com/z/1001668/5366.html?fpa=12437&fpos&lastp=ch_home&_source_=B",
                "monitorEnabled": True,
                "policy": {
                    "autoDetectSource": True,
                    "autoRecordVideo": False,
                    "autoRecordDanmaku": True,
                    "feishuNotify": False,
                    "pollSeconds": 30,
                    "preferredQuality": "720P",
                },
            },
        )
        self.assertEqual(response.status, 200)
        activity_result = await response.json()
        self.assertTrue(activity_result["ok"])
        self.assertEqual(self.service.config["vote"]["activity"], "歌手 2026")
        self.assertEqual(self.service.config["monitor"]["url"], "https://www.mgtv.com/z/1001668/5366.html?fpa=12437&fpos&lastp=ch_home&_source_=B")
        self.assertEqual(self.service.config["mgtv"]["camera_id"], "5366")
        self.assertEqual(self.service.config["mgtv"]["room_id"], "liveshow-5366")
        self.assertTrue(self.service.config["monitor"]["enabled"])
        self.assertEqual(self.service.config["recording"]["preferred_quality"], "720P")

        response = await self.client.get("/api/activities")
        self.assertEqual(response.status, 200)
        activities = await response.json()
        self.assertEqual(activities["selectedId"], "1001668")
        self.assertEqual(activities["items"][0]["name"], "歌手 2026")

        response = await self.client.post("/api/activities/1001668/monitor/stop")
        self.assertEqual(response.status, 200)
        self.assertFalse(self.service.config["monitor"]["enabled"])
        response = await self.client.get("/api/studio/bootstrap")
        self.assertEqual(response.status, 200)
        stopped_bootstrap = await response.json()
        self.assertFalse(stopped_bootstrap["monitor"]["state"]["taskRunning"])

        meta = await self.service.store.create_round(
            "歌手 2026",
            "第一轮",
            "https://www.mgtv.com/z/1001668.html",
            self.service.default_candidates,
            self.service.default_policy,
        )
        await self.service.store.stop_active()

        response = await self.client.get("/api/rounds")
        self.assertEqual(response.status, 200)
        rounds = await response.json()
        self.assertEqual(rounds["items"][0]["id"], meta.id)

        response = await self.client.patch(f"/api/rounds/{meta.id}", json={"name": "选歌环节"})
        self.assertEqual(response.status, 200)
        renamed = await response.json()
        self.assertEqual(renamed["name"], "选歌环节")

        response = await self.client.patch(f"/api/rounds/{meta.id}", json={"name": "  "})
        self.assertEqual(response.status, 400)
        invalid_rename = await response.json()
        self.assertEqual(invalid_rename["error"], "场次名称不能为空")

        response = await self.client.get(f"/api/rounds/{meta.id}/results")
        self.assertEqual(response.status, 200)
        results = await response.json()
        self.assertEqual(results["roundId"], meta.id)
        self.assertEqual(results["ranking"][0]["name"], "甲")

        response = await self.client.post(f"/api/rounds/{meta.id}/publish", json={"resultKind": "rough"})
        self.assertEqual(response.status, 200)
        publish = await response.json()
        self.assertTrue(publish["ok"])

    async def test_manual_public_sync_does_not_require_selected_round(self):
        response = await self.client.post("/api/public/sync", json={"resultKind": "rough"})
        self.assertEqual(response.status, 409)

        calls = []

        async def fake_publish(force=False, result_kind="rough"):
            calls.append((force, result_kind))
            return "https://github.com/owner/repo/commit/manual-sync"

        self.service.config["github"]["enabled"] = True
        self.service.publisher.publish = fake_publish
        response = await self.client.post("/api/public/sync", json={"resultKind": "precise"})
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resultKind"], "precise")
        self.assertEqual(payload["sessionCount"], 0)
        self.assertEqual(calls, [(True, "precise")])

        response = await self.client.post("/api/public/sync", json={"resultKind": "invalid"})
        self.assertEqual(response.status, 400)

    async def test_recording_timeline_contract(self):
        meta = await self.service.store.create_round(
            "旧活动",
            "第一轮",
            "https://www.mgtv.com/z/1/2.html",
            self.service.default_candidates,
            self.service.default_policy,
        )
        video_path = Path(self.temp.name) / "complete.mp4"
        video_path.write_bytes(b"complete-video")
        self.service.recorder.records[meta.id] = {
            "roundId": meta.id,
            "activity": meta.activity,
            "roundName": meta.name,
            "path": str(video_path),
            "status": "finished",
            "startedAt": meta.startedAt,
            "endedAt": meta.startedAt,
            "markers": [{"id": "m1", "label": "开场", "atSeconds": 0}],
            "clips": [],
        }
        self.service.recorder.save()

        response = await self.client.get(f"/api/recordings/{meta.id}/timeline")
        self.assertEqual(response.status, 200)
        timeline = await response.json()
        self.assertEqual(timeline["roundId"], meta.id)
        self.assertEqual(timeline["markers"][0]["label"], "开场")

        response = await self.client.post(
            f"/api/recordings/{meta.id}/markers",
            json={"label": "副歌", "atSeconds": 12.5},
        )
        self.assertEqual(response.status, 200)
        marker_result = await response.json()
        self.assertEqual(marker_result["marker"]["label"], "副歌")

        response = await self.client.get(f"/api/recordings/{meta.id}")
        self.assertEqual(response.status, 200)
        recording = await response.json()
        self.assertEqual(recording["markers"][-1]["label"], "副歌")


if __name__ == "__main__":
    unittest.main()
