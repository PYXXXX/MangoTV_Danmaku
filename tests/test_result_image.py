import tempfile
import unittest
from pathlib import Path

from server.result_image import DATA_SOURCE_URL, DISCLAIMER_TEXT, _font_has_cjk, _fonts, render_result_png


class ResultImageTest(unittest.TestCase):
    def test_result_font_can_render_distinct_chinese_glyphs(self):
        with tempfile.TemporaryDirectory() as temp:
            fonts = _fonts(str(Path(temp) / "fonts"))
            self.assertTrue(_font_has_cjk(fonts.title))
            self.assertTrue(_font_has_cjk(fonts.body))
            self.assertTrue(_font_has_cjk(fonts.small))

    def test_render_result_png_contains_png_signature(self):
        state = {
            "publishedAt": "2026-07-05T01:00:00Z",
            "sessions": [
                {
                    "id": "round-1",
                    "activity": "歌手 2026",
                    "name": "第一轮",
                    "status": "stopped",
                    "messageCount": 120,
                    "reviewCount": 3,
                    "candidates": [
                        {"id": "c1", "name": "甲"},
                        {"id": "c2", "name": "乙"},
                    ],
                    "voteCounts": {"c1": 8, "c2": 5},
                    "defaultResultType": "rough",
                    "results": {
                        "rough": {
                            "voteCounts": {"c1": 8, "c2": 5},
                            "messageCount": 120,
                            "reviewCount": 3,
                        },
                        "precise": None,
                    },
                }
            ],
        }
        body, filename = render_result_png(state, "round-1")
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(body), 10_000)
        self.assertEqual(filename, "mgtv-result-round-1-rough.png")
        self.assertEqual(DATA_SOURCE_URL, "https://pyxxxx.github.io/MangoTV_Danmaku/")
        self.assertEqual(DISCLAIMER_TEXT, "非官方正式统计，不代表湖南卫视 & 芒果 TV 立场，仅供娱乐参考。")

    def test_render_result_png_prefers_precise_when_requested(self):
        state = {
            "publishedAt": "2026-07-05T01:00:00Z",
            "sessions": [
                {
                    "id": "round-1",
                    "activity": "歌手 2026",
                    "name": "第一轮",
                    "status": "stopped",
                    "messageCount": 120,
                    "reviewCount": 3,
                    "candidates": [{"id": "c1", "name": "甲"}],
                    "voteCounts": {"c1": 8},
                    "defaultResultType": "rough",
                    "results": {
                        "rough": {"voteCounts": {"c1": 8}, "messageCount": 120, "reviewCount": 3},
                        "precise": {
                            "voteCounts": {"c1": 7},
                            "audit": {
                                "inputMessages": 100,
                                "unresolvedReviewMessages": 0,
                            },
                        },
                    },
                }
            ],
        }
        body, filename = render_result_png(state, "round-1", "precise")
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(filename, "mgtv-result-round-1-precise.png")


if __name__ == "__main__":
    unittest.main()
