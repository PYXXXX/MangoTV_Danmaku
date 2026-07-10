"""Render public vote results as a PNG poster."""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont


BEIJING_TZ = ZoneInfo("Asia/Shanghai")
DATA_SOURCE_URL = "https://pyxxxx.github.io/MangoTV_Danmaku/"
DISCLAIMER_TEXT = "非官方正式统计，不代表湖南卫视 & 芒果 TV 立场，仅供娱乐参考。"
NOTO_CJK_URL = (
    "https://github.com/notofonts/noto-cjk/raw/"
    "f8d157532fbfaeda587e826d4cd5b21a49186f7c/"
    "Sans/SubsetOTF/SC/NotoSansSC-Regular.otf"
)
NOTO_CJK_SHA256 = "faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9"
NOTO_CJK_FILENAME = "NotoSansSC-Regular.otf"
MAX_FONT_DOWNLOAD_BYTES = 12 * 1024 * 1024
_FONT_DOWNLOAD_LOCK = threading.Lock()


@dataclass(frozen=True)
class FontSet:
    title: ImageFont.FreeTypeFont | ImageFont.ImageFont
    subtitle: ImageFont.FreeTypeFont | ImageFont.ImageFont
    label: ImageFont.FreeTypeFont | ImageFont.ImageFont
    body: ImageFont.FreeTypeFont | ImageFont.ImageFont
    number: ImageFont.FreeTypeFont | ImageFont.ImageFont
    small: ImageFont.FreeTypeFont | ImageFont.ImageFont


def _system_font_candidates(bold: bool = False) -> list[str]:
    bold_candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ] if bold else []
    return bold_candidates + [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ]


def _font_has_cjk(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> bool:
    """Reject fonts that render every Chinese character as the same tofu box."""
    signatures: set[tuple[tuple[int, int], bytes]] = set()
    for char in "汉字歌手":
        mask = font.getmask(char)
        signatures.add((mask.size, bytes(mask)))
    return len(signatures) >= 3


def _valid_cached_font(path: Path) -> bool:
    if not path.is_file():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest == NOTO_CJK_SHA256


def _download_cjk_font(cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / NOTO_CJK_FILENAME
    if _valid_cached_font(target):
        return target
    target.unlink(missing_ok=True)
    temp = target.with_suffix(".tmp")
    temp.unlink(missing_ok=True)
    request = Request(NOTO_CJK_URL, headers={"User-Agent": "MangoTV-Danmaku/1.0"})
    digest = hashlib.sha256()
    total = 0
    try:
        with urlopen(request, timeout=45) as response, temp.open("wb") as output:  # nosec B310 -- pinned HTTPS + SHA-256
            while chunk := response.read(256 * 1024):
                total += len(chunk)
                if total > MAX_FONT_DOWNLOAD_BYTES:
                    raise RuntimeError("中文字体文件异常过大，已拒绝写入")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != NOTO_CJK_SHA256:
            raise RuntimeError("中文字体完整性校验失败")
        temp.replace(target)
        os.chmod(target, 0o644)
        return target
    except (OSError, URLError):
        temp.unlink(missing_ok=True)
        raise
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def ensure_result_font(cache_dir: str | Path | None = None, *, bold: bool = False) -> Path:
    configured = str(os.environ.get("MGTV_RESULT_FONT_PATH") or "").strip()
    candidates = ([configured] if configured else []) + _system_font_candidates(bold)
    for path in candidates:
        if not Path(path).exists():
            continue
        try:
            font = ImageFont.truetype(path, size=24, index=0)
        except OSError:
            continue
        if _font_has_cjk(font):
            return Path(path)
    base = Path(cache_dir) if cache_dir else Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "mgtv-danmaku" / "fonts"
    try:
        with _FONT_DOWNLOAD_LOCK:
            downloaded = _download_cjk_font(base)
        font = ImageFont.truetype(str(downloaded), size=24, index=0)
        if not _font_has_cjk(font):
            raise RuntimeError("下载的字体不包含可用中文字符")
        return downloaded
    except Exception as exc:
        raise RuntimeError(
            "未找到支持中文的结果图字体，且自动获取 Noto Sans SC 失败；"
            "请安装 fonts-noto-cjk 或通过 MGTV_RESULT_FONT_PATH 指定中文字体"
        ) from exc


def _load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size, index=0)


@lru_cache(maxsize=8)
def _fonts(font_cache_dir: str = "") -> FontSet:
    regular_path = ensure_result_font(font_cache_dir or None)
    bold_path = ensure_result_font(font_cache_dir or None, bold=True)
    return FontSet(
        title=_load_font(bold_path, 58),
        subtitle=_load_font(regular_path, 22),
        label=_load_font(regular_path, 20),
        body=_load_font(regular_path, 30),
        number=_load_font(bold_path, 38),
        small=_load_font(regular_path, 18),
    )


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    text = str(text or "")
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "…"
    while text and _text_width(draw, text + ellipsis, font) > max_width:
        text = text[:-1]
    return text + ellipsis if text else ellipsis


def _format_count(value: Any) -> str:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        number = 0
    return f"{number:,}"


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _format_beijing(value: str | None = None) -> str:
    return _parse_iso(value).astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _selected_result(session: dict[str, Any], requested: str | None = None) -> tuple[str, dict[str, Any]]:
    results = session.get("results") if isinstance(session.get("results"), dict) else {}
    result_type = requested if requested in {"rough", "precise"} else str(session.get("defaultResultType") or "rough")
    if result_type == "precise" and not results.get("precise"):
        result_type = "rough"
    data = results.get(result_type) or {
        "voteCounts": session.get("voteCounts") or {},
        "messageCount": session.get("messageCount") or 0,
        "reviewCount": session.get("reviewCount") or 0,
    }
    return result_type, data


def _metric_counts(session: dict[str, Any], result_type: str, result: dict[str, Any], total_votes: int) -> tuple[str, str, str]:
    if result_type == "precise":
        audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
        messages = audit.get("inputMessages", session.get("messageCount") or 0)
        reviews = audit.get("unresolvedReviewMessages", session.get("reviewCount") or 0)
    else:
        messages = result.get("messageCount", session.get("messageCount") or 0)
        reviews = result.get("reviewCount", session.get("reviewCount") or 0)
    return _format_count(messages), _format_count(total_votes), _format_count(reviews)


def _poster_headings(session: dict[str, Any]) -> tuple[str, str, str]:
    activity = str(session.get("activity") or "未分类活动")
    display_name = str(session.get("displayName") or session.get("baseName") or session.get("name") or "未命名场次")
    time_range = str(session.get("timeRange") or "")
    return activity, f"场次：{display_name}", f"采集时间：{time_range}" if time_range else ""


def render_result_png(
    state: dict[str, Any],
    round_id: str,
    requested_result: str | None = None,
    font_cache_dir: str | Path | None = None,
) -> tuple[bytes, str]:
    sessions = state.get("sessions") or []
    session = next((item for item in sessions if item.get("id") == round_id), None)
    if not session:
        raise KeyError(f"找不到场次：{round_id}")

    result_type, result = _selected_result(session, requested_result)
    counts = result.get("voteCounts") if isinstance(result.get("voteCounts"), dict) else {}
    candidates = session.get("candidates") or []
    rows = sorted(
        [
            {
                "name": str(candidate.get("name") or "未命名"),
                "count": int(counts.get(candidate.get("id"), 0) or 0),
            }
            for candidate in candidates
        ],
        key=lambda item: (-item["count"], item["name"]),
    )
    total_votes = sum(item["count"] for item in rows)
    max_votes = max([1, *(item["count"] for item in rows)])
    messages, votes, reviews = _metric_counts(session, result_type, result, total_votes)

    width = 1200
    row_height = 82
    visible_rows = max(1, len(rows[:12]))
    height = max(900, 510 + visible_rows * row_height)
    fonts = _fonts(str(font_cache_dir or ""))
    image = Image.new("RGB", (width, height), "#0d0e10")
    draw = ImageDraw.Draw(image)

    # Soft orange glow, cheap but pleasant enough for a generated poster.
    for radius, alpha in [(540, 22), (420, 24), (300, 28), (180, 32)]:
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        glow = ImageDraw.Draw(overlay)
        glow.ellipse((width - radius, -radius // 2, width + radius // 2, radius), fill=(255, 122, 26, alpha))
        image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))

    left = 68
    right = width - 68
    orange = "#ff7a1a"
    muted = "#777a81"
    line = "#2a2c30"
    text = "#f5f5f3"

    draw.text((left, 58), "LIVE OPS DATA", fill=orange, font=fonts.small)
    activity_title, round_line, time_line = _poster_headings(session)
    draw.text((left, 88), _fit_text(draw, activity_title, fonts.title, right - left - 210), fill=text, font=fonts.title)
    status = "精确结果 · 已清洗" if result_type == "precise" else ("LIVE · 粗略统计中" if session.get("status") == "running" else "粗略结果 · 本轮已结束")
    draw.text((left, 166), _fit_text(draw, round_line, fonts.subtitle, right - left - 190), fill=muted, font=fonts.subtitle)
    if time_line:
        draw.text((left, 196), _fit_text(draw, time_line, fonts.small, right - left - 190), fill=muted, font=fonts.small)
    badge_w = _text_width(draw, status, fonts.small) + 34
    draw.rounded_rectangle((right - badge_w, 70, right, 112), radius=21, fill="#2a211b", outline="#5d3c24")
    draw.text((right - badge_w + 17, 82), status, fill="#ff9a50", font=fonts.small)
    draw.line((left, 220, right, 220), fill=line, width=1)

    metric_y = 256
    metric_width = (right - left) // 3
    metric_items = [("弹幕样本", messages), ("有效计票", votes), ("语义待审", reviews)]
    for idx, (label, value) in enumerate(metric_items):
        x = left + idx * metric_width
        if idx:
            draw.line((x - 24, metric_y - 12, x - 24, metric_y + 80), fill=line, width=1)
        draw.text((x, metric_y), label, fill=muted, font=fonts.small)
        draw.text((x, metric_y + 30), value, fill=text, font=fonts.number)

    ranking_y = 390
    draw.text((left, ranking_y - 54), "结果排行", fill=text, font=fonts.body)
    draw.text((right - 160, ranking_y - 48), "票数", fill=muted, font=fonts.small)
    if not rows:
        draw.text((left, ranking_y + 60), "暂无候选人。", fill=muted, font=fonts.body)
    for index, item in enumerate(rows[:12], 1):
        y = ranking_y + (index - 1) * row_height
        draw.line((left, y + row_height - 10, right, y + row_height - 10), fill="#222428", width=1)
        rank = str(index).zfill(2)
        name = _fit_text(draw, item["name"], fonts.body, 280)
        count = _format_count(item["count"])
        draw.text((left, y + 18), rank, fill="#686b72", font=fonts.small)
        draw.text((left + 70, y + 11), name, fill=text, font=fonts.body)
        bar_x = left + 365
        bar_y = y + 35
        bar_w = 445
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 12), radius=6, fill="#24262a")
        fill_w = max(4, int(bar_w * item["count"] / max_votes)) if item["count"] else 4
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + 12), radius=6, fill=orange)
        draw.text((right - _text_width(draw, count, fonts.number), y + 13), count, fill=text, font=fonts.number)

    footer_y = height - 118
    draw.rounded_rectangle((left, footer_y, right, footer_y + 54), radius=14, fill="#17181b", outline="#2c2e33")
    draw.text((left + 18, footer_y + 16), DISCLAIMER_TEXT, fill="#b9bbc1", font=fonts.small)
    draw.line((left, height - 44, right, height - 44), fill="#222428", width=1)
    publish_text = f"数据发布于 {_format_beijing(state.get('publishedAt'))}"
    export_text = f"导出时间 {_format_beijing()}"
    source_text = f"数据来源：{DATA_SOURCE_URL}"
    draw.text((left, height - 58), source_text, fill="#858890", font=fonts.small)
    draw.text((left, height - 30), "页面仅展示聚合人气统计，不包含观众昵称与原始弹幕", fill="#666970", font=fonts.small)
    draw.text((right - _text_width(draw, export_text, fonts.small), height - 30), export_text, fill="#666970", font=fonts.small)
    draw.text((right - _text_width(draw, publish_text, fonts.small), height - 58), publish_text, fill="#666970", font=fonts.small)

    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    filename = f"mgtv-result-{session.get('id')}-{result_type}.png"
    return out.getvalue(), filename
