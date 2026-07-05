import unittest
import asyncio

from server.feishu_cards import build_control_card, build_round_list_card
from server.feishu_ws import FeishuLongConnection


class FeishuCardTest(unittest.TestCase):
    def setUp(self):
        self.state = {
            "activeSessionId": "r1",
            "sessions": [
                {
                    "id": "r1",
                    "activity": "歌手 2026",
                    "name": "第一轮",
                    "status": "running",
                    "messageCount": 120,
                    "reviewCount": 3,
                    "candidates": [
                        {"id": "c1", "name": "甲"},
                        {"id": "c2", "name": "乙"},
                    ],
                    "voteCounts": {"c1": 8, "c2": 5},
                    "results": {"rough": {"voteCounts": {"c1": 8, "c2": 5}}, "precise": None},
                },
                {
                    "id": "r0",
                    "activity": "歌手 2026",
                    "name": "测试轮",
                    "status": "stopped",
                    "messageCount": 60,
                    "reviewCount": 0,
                    "candidates": [{"id": "c1", "name": "甲"}],
                    "voteCounts": {"c1": 4},
                    "results": {"rough": {"voteCounts": {"c1": 4}}, "precise": {"voteCounts": {"c1": 3}}},
                },
            ],
        }

    def test_control_card_contains_safe_operations(self):
        card = build_control_card(self.state, "r1", "状态已刷新", "https://example.com/results", "https://example.com/result.png")
        self.assertEqual(card["header"]["template"], "orange")
        self.assertEqual(card["header"]["title"]["content"], "直播弹幕人气控制台")
        actions = [
            action["value"]["action"]
            for element in card["elements"]
            for action in element.get("actions", [])
            if action.get("tag") == "button" and action.get("value")
        ]
        self.assertIn("end_round", actions)
        self.assertIn("publish_rough", actions)
        self.assertNotIn("start_default", actions)
        rendered = str(card)
        self.assertIn("● 采集中", rendered)
        self.assertIn("结束并发布粗略结果", rendered)
        self.assertIn("查看/切换场次", rendered)
        self.assertIn("card.action.trigger", rendered)
        self.assertIn("120", rendered)
        self.assertIn("打开公开结果页", rendered)
        self.assertIn("导出当前场次 PNG", rendered)
        self.assertIn("https://example.com/result.png", rendered)

    def test_control_card_renders_start_form_with_runtime_defaults(self):
        state = {
            "activeSessionId": None,
            "defaults": {
                "activity": "歌手 2026",
                "mgtvUrl": "https://www.mgtv.com/z/1001668/5366.html",
            },
            "sessions": [],
        }
        card = build_control_card(state)
        rendered = str(card)
        self.assertIn("start_round_form", rendered)
        self.assertIn("start_round_submit", rendered)
        self.assertIn("start_custom", rendered)
        self.assertIn("歌手 2026", rendered)
        self.assertIn("第 1 轮", rendered)
        self.assertIn("https://www.mgtv.com/z/1001668/5366.html", rendered)

    def test_round_list_uses_select_callback(self):
        card = build_round_list_card(self.state, "r0")
        selector = next(
            action
            for element in card["elements"]
            for action in element.get("actions", [])
            if action.get("tag") == "select_static"
        )
        self.assertEqual(selector["tag"], "select_static")
        self.assertEqual(selector["value"]["action"], "select_round")
        self.assertEqual(selector["initial_option"], "r0")
        self.assertEqual(len(selector["options"]), 2)
        self.assertEqual(card["header"]["title"]["content"], "场次管理")

    def test_long_connection_requires_credentials_only_when_enabled(self):
        loop = asyncio.new_event_loop()
        try:
            self.assertFalse(FeishuLongConnection({"enabled": False}, object()).start(loop))
            with self.assertRaisesRegex(RuntimeError, "app_id"):
                FeishuLongConnection({"enabled": True, "connection_mode": "websocket"}, object()).start(loop)
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
