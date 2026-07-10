import unittest

from server.mgtv_auth import (
    MgtvAuthManager,
    cookie_header_from_cookies,
    cookies_from_header,
    discover_mgtv_camera_id,
    cookie_values,
    logged_in_from_cookies,
    mgtv_camera_page_url,
    mgtv_live_source_sign,
    parse_mgtv_activity_camera,
    parse_mgtv_activity_id,
)


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
        self.assertEqual(cookie_values("HDCN=token; uuid=user")["uuid"], "user")

    def test_live_source_signature_and_url_parsing_match_web_client_contract(self):
        params = {
            "cameraId": "5366",
            "activityId": "1001668",
            "platform": "4",
            "appVersion": "imgotv-pch5-9.0.4-1",
            "clientKey": "pcweb",
            "auth_mode": "1",
            "local_definition": "",
            "init_definition": "2",
            "did": "32d00e1e-acba-499f-9741-3607e989ecaa",
            "uid": "",
            "token": "",
            "_t": "1783345527290",
            "deviceId": "32d00e1e-acba-499f-9741-3607e989ecaa",
            "definition": "1080",
        }
        self.assertEqual(mgtv_live_source_sign(params), "6D108FC7CAF4BB944D5DE95C91E46E58")
        self.assertEqual(
            parse_mgtv_activity_camera("https://www.mgtv.com/z/1001668/5366.html?fpa=12437&fpos&lastp=ch_home&_source_=B"),
            ("1001668", "5366"),
        )
        self.assertEqual(parse_mgtv_activity_camera("https://example.com/z/1001668/5366.html"), ("", ""))
        self.assertEqual(
            parse_mgtv_activity_id("https://www.mgtv.com/z/1001668.html?fpa=12437&fpos&lastp=ch_home&_source_=B"),
            "1001668",
        )
        self.assertEqual(
            discover_mgtv_camera_id(r'{"routePath":"\u002Fz\u002F1001668\u002F5366.html"}', "1001668"),
            "5366",
        )
        self.assertEqual(
            mgtv_camera_page_url("https://www.mgtv.com/z/1001668.html?fpa=1", "1001668", "5366"),
            "https://www.mgtv.com/z/1001668/5366.html?fpa=1",
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
        self.assertEqual(status["loginProtocol"], "mgtv_http_qr")
        self.assertTrue(status["loginProtocolAvailable"])
        self.assertNotIn("cookies", status)
        self.assertNotIn("cookie_header", status)

class MgtvAuthAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_detect_stream_selects_direct_live_source_without_browser(self):
        manager = MgtvAuthManager({
            "cookie_header": "HDCN=ticket-token; uuid=user-id; __STKUUID=device-id",
            "device_id": "device-id",
        })

        async def fake_request_json(session, url, **kwargs):
            self.assertIn("/v1/live/source", url)
            params = kwargs["params"]
            self.assertEqual(params["activityId"], "1001668")
            self.assertEqual(params["cameraId"], "5366")
            self.assertEqual(params["uid"], "user-id")
            self.assertEqual(params["token"], "ticket-token")
            self.assertEqual(params["definition"], "1080")
            self.assertEqual(params["sign"], mgtv_live_source_sign({key: value for key, value in params.items() if key not in {"_support", "sign"}}))
            return {
                "code": 200,
                "msg": "ok",
                "data": {
                    "servertime": 100,
                    "streamBeginTimeStamp": 200,
                    "endTimeStamp": 300,
                    "streamBeginTime": "2026-07-10 18:25:00",
                    "sources": [
                        {"name": "720P", "definition": 3, "url": "https://example.com/720.m3u8"},
                        {"name": "1080P ·50帧", "definition": 5, "needPay": "1", "url": "https://example.com/1080.m3u8"},
                    ]
                },
            }

        manager._request_json = fake_request_json
        result = await manager.detect_stream("https://www.mgtv.com/z/1001668/5366.html", "1080P")
        self.assertTrue(result["ok"])
        self.assertEqual(result["streamUrl"], "https://example.com/1080.m3u8")
        self.assertEqual(result["actualQuality"], "1080P ·50帧")
        self.assertEqual(result["availableQualities"], ["720P", "1080P ·50帧"])
        self.assertEqual(result["pageUrl"], "https://www.mgtv.com/z/1001668/5366.html")
        self.assertEqual(result["liveStatus"], "upcoming")
        self.assertEqual(result["streamBeginTimestamp"], 200)

    async def test_detect_stream_accepts_activity_url_after_resolution(self):
        manager = MgtvAuthManager({"device_id": "device-id"})

        async def fake_resolve_live_url(page_url, *, timeout_seconds=12):
            self.assertIn("/z/1001668.html", page_url)
            return {
                "ok": True,
                "pageUrl": "https://www.mgtv.com/z/1001668/5366.html?fpa=1",
                "activityId": "1001668",
                "cameraId": "5366",
                "resolved": True,
                "resolvedFrom": page_url,
            }

        async def fake_request_json(session, url, **kwargs):
            self.assertEqual(kwargs["params"]["cameraId"], "5366")
            return {
                "code": 200,
                "msg": "ok",
                "data": {"sources": [{"name": "720P", "url": "https://example.com/720.m3u8"}]},
            }

        manager.resolve_live_url = fake_resolve_live_url
        manager._request_json = fake_request_json
        result = await manager.detect_stream("https://www.mgtv.com/z/1001668.html?fpa=1", "720P")
        self.assertTrue(result["ok"])
        self.assertEqual(result["availableQualities"], ["720P"])
        self.assertEqual(result["pageUrl"], "https://www.mgtv.com/z/1001668/5366.html?fpa=1")
        self.assertEqual(result["resolvedFrom"], "https://www.mgtv.com/z/1001668.html?fpa=1")


if __name__ == "__main__":
    unittest.main()
