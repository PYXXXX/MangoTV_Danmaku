import unittest

from server.mgtv_auth import MgtvAuthManager, cookie_header_from_cookies, cookies_from_header, logged_in_from_cookies


class MgtvAuthHelpersTest(unittest.TestCase):
    def test_cookie_header_keeps_only_mgtv_cookies_and_detects_login(self):
        cookies = [
            {"name": "HDCN", "value": "token", "domain": ".mgtv.com"},
            {"name": "uuid", "value": "user", "domain": ".mgtv.com"},
            {"name": "ignored", "value": "x", "domain": ".example.com"},
        ]
        self.assertEqual(cookie_header_from_cookies(cookies), "HDCN=token; uuid=user")
        self.assertTrue(logged_in_from_cookies(cookies))
        self.assertEqual(
            cookies_from_header("HDCN=token; uuid=user")[0],
            {"name": "HDCN", "value": "token", "domain": ".mgtv.com", "path": "/", "secure": True},
        )

    def test_public_status_redacts_user_info_and_never_returns_cookies(self):
        manager = MgtvAuthManager({
            "cookies": [{"name": "HDCN", "value": "secret", "domain": ".mgtv.com"}],
            "cookie_header": "HDCN=secret; uuid=secret-user",
            "user_info": {"data": {"uid": "123", "nickname": "运营号", "isvip": 1, "phone": "hidden"}},
        })
        status = manager.public_status()
        self.assertTrue(status["cookieConfigured"])
        self.assertEqual(status["user"], {"uid": "123", "nickname": "运营号", "isVip": True, "vipType": ""})
        self.assertNotIn("cookies", status)
        self.assertNotIn("cookie_header", status)


if __name__ == "__main__":
    unittest.main()
