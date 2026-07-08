import unittest
import asyncio

from server.feishu_cards import (
    build_control_card,
    build_monitor_card,
    build_ops_card,
    build_publish_card,
    build_recording_card,
    build_round_list_card,
    build_system_card,
)
from server.feishu_ws import FeishuLongConnection


def walk_card(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_card(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_card(child)


def card_actions(card):
    return [
        item["value"]["action"]
        for item in walk_card(card)
        if item.get("tag") == "button" and isinstance(item.get("value"), dict) and item["value"].get("action")
    ]


def card_tags(card):
    return [item.get("tag") for item in walk_card(card) if item.get("tag")]


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
        card = build_control_card(self.state, "r1", "状态已刷新", "https://example.com/results")
        self.assertEqual(card["header"]["template"], "orange")
        self.assertEqual(card["header"]["title"]["content"], "直播运营工作台")
        actions = [
            action["value"]["action"]
            for element in card["elements"]
            for action in element.get("actions", [])
            if action.get("tag") == "button" and action.get("value")
        ]
        self.assertIn("end_round", actions)
        self.assertIn("show_publish", actions)
        self.assertIn("show_monitor", actions)
        self.assertIn("show_ops", actions)
        self.assertIn("show_system", actions)
        self.assertNotIn("start_default", actions)
        rendered = str(card)
        self.assertIn("● 采集中", rendered)
        self.assertIn("结束并发布粗略结果", rendered)
        self.assertIn("查看/切换场次", rendered)
        self.assertIn("card.action.trigger", rendered)
        self.assertIn("120", rendered)
        self.assertIn("打开公开结果页", rendered)
        self.assertIn("录制后处理", rendered)
        self.assertIn("show_recording", actions)

    def test_control_card_contains_confirmed_delete_actions_for_stopped_round(self):
        card = build_publish_card(self.state, "r0", "状态已刷新", "https://example.com/results")
        rendered = str(card)
        actions = [
            action["value"]["action"]
            for element in card["elements"]
            for action in element.get("actions", [])
            if action.get("tag") == "button" and action.get("value")
        ]
        self.assertIn("delete_round", actions)
        self.assertIn("delete_activity", actions)
        self.assertIn("确认删除", rendered)
        self.assertIn("删除所选场次", rendered)
        self.assertIn("删除当前活动", rendered)

    def test_ops_card_uses_callback_safe_buttons_with_runtime_defaults(self):
        state = {
            "activeSessionId": None,
            "defaults": {
                "activity": "歌手 2026",
                "mgtvUrl": "https://www.mgtv.com/z/1001668/5366.html",
            },
            "sessions": [],
        }
        card = build_ops_card(state)
        rendered = str(card)
        self.assertNotIn("form", card_tags(card))
        actions = card_actions(card)
        self.assertIn("start_realtime", actions)
        self.assertIn("start_record", actions)
        self.assertIn("歌手 2026", rendered)
        self.assertIn("第 1 轮", rendered)
        self.assertIn("https://www.mgtv.com/z/1001668/5366.html", rendered)
        self.assertIn("WebUI 运营工作区", rendered)

    def test_monitor_publish_and_system_cards_match_workspace_navigation(self):
        monitor_card = build_monitor_card(self.state, {
            "config": {
                "enabled": True,
                "activity": "歌手 2026",
                "url": "https://www.mgtv.com/z/1001668.html",
                "autoDetectSource": True,
                "autoRecordVideo": True,
                "autoRecordDanmaku": True,
                "feishuNotify": True,
                "pollSeconds": 30,
            },
            "state": {"status": "waiting", "message": "等待直播开始"},
        })
        publish_card = build_publish_card(self.state, "r1", public_url="https://example.com/results")
        system_card = build_system_card({
            "systemTime": "2026-07-07T15:00:00+08:00",
            "uptimeSeconds": 60,
            "cpu": {"count": 2, "loadPercent": 12.5},
            "memory": {"processRssBytes": 1024 * 1024, "totalBytes": 4 * 1024 * 1024 * 1024},
            "disk": {"data": {"freeBytes": 10}, "recordings": {"freeBytes": 20}},
            "services": {"monitor": {"status": "waiting"}, "collector": {"status": "idle"}, "recorder": {"status": "idle"}},
            "health": {"status": "ok", "restartRequired": False, "restartFields": []},
        })
        rendered = str(monitor_card) + str(publish_card) + str(system_card)
        self.assertIn("活动监控", rendered)
        self.assertIn("发布与结果", rendered)
        self.assertIn("系统状态", rendered)
        self.assertIn("发送当前场次 PNG", rendered)
        self.assertIn("刷新系统状态", rendered)

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

    def test_recording_card_avoids_unsupported_post_processing_forms(self):
        state = {
            "activeSessionId": None,
            "sessions": [
                {
                    "id": "r0",
                    "activity": "歌手 2026",
                    "displayName": "全程录制",
                    "status": "stopped",
                    "messageCount": 10,
                    "reviewCount": 0,
                    "candidates": [{"id": "c1", "name": "甲"}],
                    "results": {"rough": {"voteCounts": {"c1": 1}}, "precise": None},
                    "recording": {
                        "status": "finished",
                        "hasVideo": True,
                        "videoUrl": "/api/rounds/r0/recording/video",
                        "markers": [{"label": "口播", "atSeconds": 12}],
                        "clips": [{"id": "clip1", "label": "片段一", "startSeconds": 10, "endSeconds": 20}],
                    },
                }
            ],
        }
        card = build_recording_card(state, "r0")
        rendered = str(card)
        self.assertIn("录制后处理", rendered)
        self.assertNotIn("form", card_tags(card))
        self.assertIn("打标与手动切片请在 WebUI 完成", rendered)
        self.assertIn("analyze_latest_clip", rendered)
        self.assertIn("打开回看视频", rendered)

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
