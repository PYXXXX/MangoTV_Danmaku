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
        "listen": {"host": "127.0.0.1", "port": 8080, "public_base_url": "https://example.com"},
        "storage": {"directory": str(root / "data")},
        "recording": {
            "enabled": False,
            "stream_url": "https://secure.example.com/live.m3u8?token=secret",
            "preferred_quality": "1080P",
            "ffmpeg_path": "ffmpeg",
            "directory": str(root / "recordings"),
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


if __name__ == "__main__":
    unittest.main()
