import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from server.feishu_binding import (
    ACCOUNTS_LARK,
    APP_REGISTRATION_PATH,
    FeishuBindingError,
    FeishuBindingResult,
    begin_binding,
    build_verification_url,
    poll_binding_once,
)
from server.vote_server import VoteService


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, content_type=None):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def post(self, url, data):
        self.posts.append((url, data))
        if not self.responses:
            raise AssertionError("unexpected POST")
        return self.responses.pop(0)


class FeishuBindingTest(unittest.IsolatedAsyncioTestCase):
    def test_build_verification_url_matches_cli_page(self):
        url = build_verification_url("ABC-123", version="test-version")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "open.feishu.cn")
        self.assertEqual(parsed.path, "/page/cli")
        self.assertEqual(query["user_code"], ["ABC-123"])
        self.assertEqual(query["from"], ["mgtv-danmaku"])
        self.assertEqual(query["lpv"], ["test-version"])
        self.assertEqual(query["ocv"], ["test-version"])

    async def test_begin_binding_posts_expected_device_registration_payload(self):
        session = FakeSession([
            FakeResponse({"supported_auth_methods": ["client_secret"]}),
            FakeResponse({
                "device_code": "device-1",
                "user_code": "USER-1",
                "verification_uri_complete": "https://open.feishu.cn/page/cli?user_code=USER-1&from=server",
                "expires_in": 600,
                "interval": 3,
            })
        ])
        result = await begin_binding(session)
        self.assertEqual(result.device_code, "device-1")
        self.assertEqual(result.user_code, "USER-1")
        self.assertEqual(result.interval, 3)
        self.assertEqual(result.verification_url, "https://open.feishu.cn/page/cli?user_code=USER-1&from=server")
        self.assertEqual(session.posts[0][0], "https://accounts.feishu.cn" + APP_REGISTRATION_PATH)
        self.assertEqual(session.posts[0][1], {"action": "init"})
        self.assertEqual(session.posts[1][0], "https://accounts.feishu.cn" + APP_REGISTRATION_PATH)
        self.assertEqual(session.posts[1][1]["action"], "begin")
        self.assertEqual(session.posts[1][1]["archetype"], "PersonalAgent")
        self.assertEqual(session.posts[1][1]["auth_method"], "client_secret")
        self.assertEqual(session.posts[1][1]["request_user_info"], "open_id tenant_brand")

    async def test_begin_binding_falls_back_to_cli_url(self):
        session = FakeSession([
            FakeResponse({}),
            FakeResponse({
                "device_code": "device-1",
                "user_code": "USER-1",
            }),
        ])
        result = await begin_binding(session)
        self.assertIn("user_code=USER-1", result.verification_url)

    async def test_poll_pending_returns_none(self):
        session = FakeSession([FakeResponse({"error": "authorization_pending"})])
        self.assertIsNone(await poll_binding_once(session, "device-1"))
        self.assertEqual(session.posts[0][1], {"action": "poll", "device_code": "device-1"})

    async def test_poll_success_returns_credentials_and_user_info(self):
        session = FakeSession([
            FakeResponse({
                "client_id": "cli_app",
                "client_secret": "secret-value",
                "user_info": {"open_id": "ou_operator", "tenant_brand": "feishu"},
            })
        ])
        result = await poll_binding_once(session, "device-1")
        self.assertEqual(result.app_id, "cli_app")
        self.assertEqual(result.app_secret, "secret-value")
        self.assertEqual(result.open_id, "ou_operator")
        self.assertEqual(result.tenant_brand, "feishu")

    async def test_poll_switches_to_lark_accounts_when_tenant_brand_requires_it(self):
        session = FakeSession([
            FakeResponse({"error": "authorization_pending", "user_info": {"tenant_brand": "lark"}}),
            FakeResponse({
                "client_id": "cli_lark",
                "client_secret": "secret-value",
                "user_info": {"open_id": "ou_operator", "tenant_brand": "lark"},
            }),
        ])
        result = await poll_binding_once(session, "device-1")
        self.assertIsNotNone(result)
        self.assertEqual(result.app_id, "cli_lark")
        self.assertEqual(result.tenant_brand, "lark")
        self.assertEqual(session.posts[1][0], ACCOUNTS_LARK + APP_REGISTRATION_PATH)

    async def test_poll_denied_raises_friendly_error(self):
        session = FakeSession([FakeResponse({"error": "access_denied"})])
        with self.assertRaisesRegex(FeishuBindingError, "取消"):
            await poll_binding_once(session, "device-1")

    async def test_complete_binding_persists_secret_but_status_redacts_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.json"
            config = {
                "listen": {"host": "127.0.0.1", "port": 8080, "public_base_url": "https://operator.example.com"},
                "storage": {"directory": str(root / "data")},
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
                    "activity": "测试活动",
                    "multi_candidate_policy": "all",
                    "candidates": [{"name": "甲", "aliases": ["甲"]}],
                },
                "github": {"enabled": False},
                "feishu": {
                    "enabled": False,
                    "connection_mode": "websocket",
                    "allowed_open_ids": ["ou_existing"],
                    "allowed_chat_ids": [],
                },
                "operator_auth": {"enabled": False},
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            service = VoteService(config, config_path=config_path, repo_root=root)

            async def fake_reload(loop):
                return True

            service.reload_feishu_connection = fake_reload
            await service._complete_feishu_binding(
                FeishuBindingResult(
                    app_id="cli_bound",
                    app_secret="secret-bound",
                    open_id="ou_operator",
                    tenant_brand="feishu",
                ),
                asyncio.get_running_loop(),
            )

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["feishu"]["enabled"])
            self.assertEqual(saved["feishu"]["connection_mode"], "websocket")
            self.assertEqual(saved["feishu"]["app_id"], "cli_bound")
            self.assertEqual(saved["feishu"]["app_secret"], "secret-bound")
            self.assertEqual(saved["feishu"]["allowed_open_ids"], ["ou_existing", "ou_operator"])
            self.assertEqual(saved["feishu"]["public_results_url"], "https://operator.example.com")

            view = service.feishu_binding_view()
            rendered = json.dumps(view)
            self.assertNotIn("secret-bound", rendered)
            self.assertTrue(view["appSecretConfigured"])

    def test_complete_binding_replaces_open_ids_when_app_changes(self):
        async def run_case():
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config_path = root / "config.json"
                config = {
                    "listen": {"public_base_url": "https://operator.example.com"},
                    "storage": {"directory": str(root / "data")},
                    "mgtv": {"dedup_db_path": str(root / "fingerprints.sqlite3")},
                    "vote": {
                        "activity": "测试活动",
                        "multi_candidate_policy": "all",
                        "candidates": [{"name": "甲", "aliases": ["甲"]}],
                    },
                    "github": {"enabled": False},
                    "feishu": {
                        "enabled": True,
                        "connection_mode": "websocket",
                        "app_id": "cli_old",
                        "app_secret": "old-secret",
                        "allowed_open_ids": ["ou_old_a", "ou_old_b"],
                        "allowed_chat_ids": ["oc_control"],
                    },
                    "operator_auth": {"enabled": False},
                }
                config_path.write_text(json.dumps(config), encoding="utf-8")
                service = VoteService(config, config_path=config_path, repo_root=root)
                service.reload_feishu_connection = lambda loop: asyncio.sleep(0, result=True)

                warning = await service._complete_feishu_binding(
                    FeishuBindingResult(
                        app_id="cli_new",
                        app_secret="secret-new",
                        open_id="ou_new_operator",
                        tenant_brand="feishu",
                    ),
                    asyncio.get_running_loop(),
                )

                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertIn("App ID 已变更", warning)
                self.assertEqual(saved["feishu"]["allowed_open_ids"], ["ou_new_operator"])
                self.assertEqual(saved["feishu"]["allowed_chat_ids"], ["oc_control"])

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
