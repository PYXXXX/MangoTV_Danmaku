import unittest

try:
    from aiohttp.test_utils import AioHTTPTestCase
    from server.operator_auth import OperatorAuth, hash_password
    from server.vote_server import create_app
except ModuleNotFoundError:
    AioHTTPTestCase = None
    hash_password = None
    OperatorAuth = None
    create_app = None

AuthHttpTestBase = AioHTTPTestCase or unittest.IsolatedAsyncioTestCase


class FakeCollector:
    def running(self):
        return False


class FakeStore:
    active_round_id = None

    def public_state(self):
        return {"activeSessionId": None, "sessions": []}


class FakeFeishu:
    def enabled(self):
        return False


class FakeService:
    def __init__(self, auth_enabled=True):
        self.config = {
            "feishu": {"enabled": False},
            "operator_auth": {
                "enabled": auth_enabled,
                "password_hash": hash_password(
                    "correct horse battery staple",
                    iterations=100_000,
                    salt=b"0123456789abcdef",
                ),
                "session_secret": "test-session-secret",
                "session_hours": 12,
                "secure_cookie": False,
                "max_failures": 5,
            },
        }
        self.collector = FakeCollector()
        self.store = FakeStore()
        self.feishu = FakeFeishu()
        self.feishu_connection = None
        self.operator_auth = OperatorAuth(self.config["operator_auth"])

    def settings_runtime(self):
        return {
            "feishuWorkerAlive": False,
            "restartRequired": False,
            "restartFields": [],
        }


@unittest.skipIf(AioHTTPTestCase is None, "aiohttp 未安装，跳过认证 HTTP 测试")
class OperatorAuthHttpTest(AuthHttpTestBase):
    async def get_application(self):
        return create_app(FakeService())

    async def test_login_page_stylesheet_is_cache_busted(self):
        login = await self.client.get("/login")
        self.assertEqual(login.status, 200)
        page = await login.text()
        self.assertIn('/webui/styles.css?v=', page)
        self.assertNotIn("{{STATIC_VERSION}}", page)

    async def test_protected_routes_login_and_logout(self):
        home = await self.client.get("/", allow_redirects=False)
        self.assertEqual(home.status, 302)
        self.assertTrue(home.headers["Location"].startswith("/login?next="))

        api = await self.client.get("/api/results.json")
        self.assertEqual(api.status, 401)
        self.assertEqual((await api.json())["error"], "登录已过期，请重新登录")

        health = await self.client.get("/healthz")
        self.assertEqual(health.status, 200)

        wrong = await self.client.post(
            "/auth/login",
            data={"password": "wrong password", "next": "/"},
            allow_redirects=False,
        )
        self.assertEqual(wrong.status, 401)
        self.assertIn("密码错误", await wrong.text())

        login = await self.client.post(
            "/auth/login",
            data={"password": "correct horse battery staple", "next": "/admin"},
            allow_redirects=False,
        )
        self.assertEqual(login.status, 303)
        self.assertEqual(login.headers["Location"], "/admin")
        raw_cookie = login.headers["Set-Cookie"].split(";", 1)[0]

        authenticated = await self.client.get("/", headers={"Cookie": raw_cookie})
        self.assertEqual(authenticated.status, 200)
        page = await authenticated.text()
        self.assertIn("直播运营工作台", page)
        self.assertIn("退出登录", page)
        self.assertIn('/webui/styles.css?v=', page)
        self.assertIn('/webui/app.js?v=', page)
        self.assertIn('/webui/settings.js?v=', page)
        self.assertNotIn("{{STATIC_VERSION}}", page)

        logout = await self.client.post(
            "/auth/logout",
            headers={"Cookie": raw_cookie},
            allow_redirects=False,
        )
        self.assertEqual(logout.status, 303)
        self.assertIn("Max-Age=0", logout.headers["Set-Cookie"])


@unittest.skipIf(AioHTTPTestCase is None, "aiohttp 未安装，跳过认证 HTTP 测试")
class DisabledOperatorAuthHttpTest(AuthHttpTestBase):
    async def get_application(self):
        return create_app(FakeService(auth_enabled=False))

    async def test_disabled_auth_preserves_existing_access(self):
        home = await self.client.get("/")
        self.assertEqual(home.status, 200)
        page = await home.text()
        self.assertNotIn("退出登录", page)
        self.assertIn('/webui/styles.css?v=', page)
        self.assertIn('/webui/app.js?v=', page)
        self.assertIn('/webui/settings.js?v=', page)
        self.assertNotIn("{{STATIC_VERSION}}", page)
        api = await self.client.get("/api/results.json")
        self.assertEqual(api.status, 200)


if __name__ == "__main__":
    unittest.main()
