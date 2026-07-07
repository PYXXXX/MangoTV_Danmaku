"""Dependency-free Feishu interactive card rendering for vote operations."""

from __future__ import annotations

from typing import Any


def plain_text(content: str) -> dict[str, str]:
    return {"tag": "plain_text", "content": content}


def button(
    text: str,
    action: str,
    button_type: str = "default",
    confirm: dict[str, Any] | None = None,
    **extra: str,
) -> dict[str, Any]:
    value = {"action": action, **extra}
    payload = {"tag": "button", "text": plain_text(text), "type": button_type, "value": value}
    if confirm:
        payload["confirm"] = confirm
    return payload


def action_row(*buttons: dict[str, Any]) -> dict[str, Any]:
    return {"tag": "action", "actions": list(buttons)}


def danger_confirm(title: str, text: str) -> dict[str, Any]:
    return {
        "title": plain_text(title),
        "text": plain_text(text),
        "confirm": plain_text("确认删除"),
        "cancel": plain_text("取消"),
    }


def text_input(name: str, placeholder: str, default_value: str = "") -> dict[str, Any]:
    field: dict[str, Any] = {
        "tag": "input",
        "name": name,
        "placeholder": plain_text(placeholder),
    }
    if default_value:
        field["default_value"] = default_value
    return field


def start_round_form(default_activity: str, next_round_name: str, default_url: str = "") -> dict[str, Any]:
    return {
        "tag": "form",
        "name": "start_round_form",
        "elements": [
            {"tag": "markdown", "content": "**自定义开始场次**\n活动名已按系统配置预填；场次名和直播 URL 可按需修改。"},
            {"tag": "markdown", "content": "活动名称"},
            text_input("activity", "例如：歌手 2026", default_activity),
            {"tag": "markdown", "content": "场次名称"},
            text_input("round_name", "留空自动使用下一轮名称", next_round_name),
            {"tag": "markdown", "content": "直播 URL（可选）"},
            text_input("live_url", "留空使用系统配置的默认直播 URL", default_url),
            {
                "tag": "column_set",
                "horizontal_align": "left",
                "columns": [
                    {
                        "tag": "column",
                        "width": "auto",
                        "vertical_align": "center",
                        "elements": [
                            {
                                "tag": "button",
                                "text": plain_text("按表单开始采集"),
                                "type": "primary",
                                "name": "start_round_submit",
                                "form_action_type": "submit",
                                "value": {"action": "start_custom"},
                            }
                        ],
                    },
                    {
                        "tag": "column",
                        "width": "auto",
                        "vertical_align": "center",
                        "elements": [
                            {
                                "tag": "button",
                                "text": plain_text("刷新状态"),
                                "type": "default",
                                "name": "start_round_refresh",
                                "value": {"action": "refresh"},
                            }
                        ],
                    },
                ],
            },
        ],
    }


def recording_marker_form() -> dict[str, Any]:
    return {
        "tag": "form",
        "name": "recording_marker_form",
        "elements": [
            {"tag": "markdown", "content": "**添加录屏标记**\n在回看播放器里确认秒数后，可在这里填写。"},
            {"tag": "markdown", "content": "时间点（秒）"},
            text_input("at_seconds", "例如：128.5"),
            {"tag": "markdown", "content": "标记名称"},
            text_input("label", "例如：主持人口播 / 高能片段"),
            {
                "tag": "button",
                "text": plain_text("添加标记"),
                "type": "primary",
                "name": "add_marker_submit",
                "form_action_type": "submit",
                "value": {"action": "add_marker"},
            },
        ],
    }


def recording_clip_form() -> dict[str, Any]:
    return {
        "tag": "form",
        "name": "recording_clip_form",
        "elements": [
            {"tag": "markdown", "content": "**截取片段并生成回看素材**\n填写开始/结束秒数后，系统会用 ffmpeg 截取视频片段。"},
            {"tag": "markdown", "content": "开始秒数"},
            text_input("start_seconds", "例如：120"),
            {"tag": "markdown", "content": "结束秒数"},
            text_input("end_seconds", "例如：180"),
            {"tag": "markdown", "content": "片段名称"},
            text_input("label", "例如：第一段竞演回放"),
            {
                "tag": "button",
                "text": plain_text("截取片段"),
                "type": "primary",
                "name": "create_clip_submit",
                "form_action_type": "submit",
                "value": {"action": "create_clip"},
            },
        ],
    }


def select_session(state: dict[str, Any], selected_round_id: str | None) -> dict[str, Any] | None:
    sessions = state.get("sessions") or []
    return (
        next((item for item in sessions if item.get("id") == selected_round_id), None)
        or next((item for item in sessions if item.get("id") == state.get("activeSessionId")), None)
        or (sessions[0] if sessions else None)
    )


def result_counts(session: dict[str, Any]) -> tuple[str, dict[str, int]]:
    results = session.get("results") or {}
    precise = results.get("precise")
    if precise:
        return "精确结果", precise.get("voteCounts") or {}
    rough = results.get("rough") or {}
    return "粗略结果", rough.get("voteCounts") or session.get("voteCounts") or {}


def top_status(state: dict[str, Any], session: dict[str, Any] | None) -> tuple[str, str, str]:
    active_id = state.get("activeSessionId")
    running = bool(session and session.get("id") == active_id and session.get("status") == "running")
    if running:
        return "orange", "● 采集中", "当前正在实时统计弹幕"
    if session:
        return "green", "■ 已结束", "当前查看历史场次"
    return "blue", "○ 空闲", "当前没有场次"


def session_title(session: dict[str, Any] | None) -> str:
    if not session:
        return "尚未创建场次"
    name = session.get("displayName") or session.get("baseName") or session.get("name") or "未命名场次"
    return f"{session.get('activity', '未分类活动')} / {name}"


def session_time_range(session: dict[str, Any] | None) -> str:
    if not session:
        return ""
    return str(session.get("timeRange") or "")


def ranking_markdown(session: dict[str, Any]) -> str:
    label, counts = result_counts(session)
    candidates = session.get("candidates") or []
    ranking = sorted(
        ((item.get("name", "未命名"), int(counts.get(item.get("id"), 0))) for item in candidates),
        key=lambda row: (-row[1], row[0]),
    )
    lines = [f"**票数排行（{label}）**"]
    if not ranking:
        lines.append("暂无候选人。")
    else:
        for index, (name, votes) in enumerate(ranking[:8], 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, f"{index}.")
            lines.append(f"{medal} **{name}**　{votes} 票")
    return "\n".join(lines)


def build_control_card(
    state: dict[str, Any],
    selected_round_id: str | None = None,
    notice: str = "",
    public_url: str = "",
) -> dict[str, Any]:
    session = select_session(state, selected_round_id)
    defaults = state.get("defaults") if isinstance(state.get("defaults"), dict) else {}
    default_activity = str(defaults.get("activity") or "未分类活动")
    default_url = str(defaults.get("mgtvUrl") or "")
    next_round_name = f"第 {len(state.get('sessions') or []) + 1} 轮"
    active_id = state.get("activeSessionId")
    running = next((item for item in state.get("sessions") or [] if item.get("id") == active_id and item.get("status") == "running"), None)
    selected_is_active = bool(session and running and session.get("id") == running.get("id"))
    template, status_text, status_hint = top_status(state, session)
    elements: list[dict[str, Any]] = []
    elements.append({
        "tag": "markdown",
        "content": (
            f"**{status_text}｜{session_title(session)}**\n"
            f"{status_hint}\n"
            f"{'采集时间：' + session_time_range(session) if session_time_range(session) else ''}\n"
            f"最近更新时间：{state.get('updatedAt') or '等待同步'}"
        ),
    })
    elements.append({"tag": "hr"})
    if notice:
        elements.append({"tag": "markdown", "content": f"**操作结果**\n{notice}"})
        elements.append({"tag": "hr"})
    if not session:
        elements.append({
            "tag": "markdown",
            "content": (
                "**下一步**\n"
                f"默认活动：**{default_activity}**\n"
                "可直接点“开始默认场次”，也可以在下面表单里修改活动名、场次名或直播 URL 后开始。"
            ),
        })
    else:
        label, _ = result_counts(session)
        precise_ready = bool((session.get("results") or {}).get("precise"))
        elements.append({
            "tag": "markdown",
            "content": (
                f"弹幕样本：**{int(session.get('messageCount') or 0)}**\n"
                f"语义待审：**{int(session.get('reviewCount') or 0)}**\n"
                f"当前结果：**{label}**\n"
                f"精确结果：{'已发布' if precise_ready else '未上传'}"
            ),
        })
        elements.extend([{"tag": "hr"}, {"tag": "markdown", "content": ranking_markdown(session)}])
    if running:
        elements.append(action_row(
            button("结束并发布粗略结果", "end_round", "danger"),
            button("刷新状态", "refresh", "default"),
        ))
    else:
        elements.append(action_row(
            button("开始默认场次", "start_default", "primary"),
            button("刷新状态", "refresh", "default"),
        ))
        elements.append(start_round_form(default_activity, next_round_name, default_url))
    elements.append(action_row(
        button("查看/切换场次", "show_rounds"),
        button("发布粗略结果", "publish_rough", "primary"),
    ))
    if session:
        elements.append(action_row(
            button("发送当前场次 PNG", "send_png", "default"),
            button("录制后处理", "show_recording", "default"),
        ))
        if session.get("status") != "running":
            elements.append(action_row(
                button(
                    "删除所选场次",
                    "delete_round",
                    "danger",
                    confirm=danger_confirm("删除所选场次？", "删除后该场次会从运营端、飞书和公开结果中移除，不能在面板内恢复。"),
                ),
                button(
                    "删除当前活动",
                    "delete_activity",
                    "danger",
                    confirm=danger_confirm("删除当前活动？", "会删除当前活动下全部已结束场次；若仍有采集中场次，系统会拒绝删除。"),
                ),
            ))
    if public_url:
        elements.append({
            "tag": "action",
            "actions": [{"tag": "button", "text": plain_text("打开公开结果页"), "type": "default", "url": public_url}],
        })
    elements.append({"tag": "note", "elements": [plain_text("按钮需要飞书企业自建应用已配置 card.action.trigger 卡片回调；若按钮提示未配置，请联系管理员。")]})
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": template, "title": plain_text("直播弹幕人气控制台")},
        "elements": elements,
    }


def build_recording_card(
    state: dict[str, Any],
    selected_round_id: str | None = None,
    notice: str = "",
) -> dict[str, Any]:
    session = select_session(state, selected_round_id)
    defaults = state.get("defaults") if isinstance(state.get("defaults"), dict) else {}
    public_base_url = str(defaults.get("publicBaseUrl") or "").rstrip("/")
    elements: list[dict[str, Any]] = []
    if notice:
        elements.append({"tag": "markdown", "content": f"**操作结果**\n{notice}"})
        elements.append({"tag": "hr"})
    if not session:
        elements.append({"tag": "markdown", "content": "**暂无场次**\n请先开始或选择一个场次。"})
    else:
        recording = session.get("recording") or {}
        clips = recording.get("clips") or []
        markers = recording.get("markers") or []
        status = recording.get("status") or "未录制"
        has_video = "是" if recording.get("hasVideo") else "否"
        elements.append({
            "tag": "markdown",
            "content": (
                f"**{session_title(session)}｜录制后处理**\n"
                f"录制状态：**{status}**\n"
                f"视频可回看：**{has_video}**\n"
                f"标记：**{len(markers)}** 个，片段：**{len(clips)}** 个"
            ),
        })
        video_url = str(recording.get("videoUrl") or "")
        if video_url.startswith("/") and public_base_url:
            video_url = public_base_url + video_url
        if video_url:
            elements.append({
                "tag": "action",
                "actions": [{"tag": "button", "text": plain_text("打开回看视频"), "type": "default", "url": video_url}],
            })
        if clips:
            lines = ["**最近片段**"]
            for clip in clips[-5:]:
                lines.append(f"- {clip.get('label') or '未命名片段'}：{clip.get('startSeconds', 0)}s–{clip.get('endSeconds', 0)}s")
            elements.append({"tag": "markdown", "content": "\n".join(lines)})
            elements.append(action_row(button("生成最近片段分析场次", "analyze_latest_clip", "primary")))
        elements.append(recording_marker_form())
        elements.append(recording_clip_form())
    elements.append(action_row(button("返回控制台", "control", "primary"), button("刷新状态", "show_recording")))
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": "purple", "title": plain_text("录制后处理")},
        "elements": elements,
    }


def build_round_list_card(
    state: dict[str, Any],
    selected_round_id: str | None = None,
    notice: str = "",
) -> dict[str, Any]:
    sessions = state.get("sessions") or []
    elements: list[dict[str, Any]] = []
    if notice:
        elements.append({"tag": "markdown", "content": notice})
    if not sessions:
        elements.append({"tag": "markdown", "content": "**暂无场次**\n回到控制台后可直接开始默认场次。"})
    else:
        current = select_session(state, selected_round_id)
        elements.append({
            "tag": "markdown",
            "content": f"**当前查看**\n{session_title(current)}{chr(10) + '采集时间：' + session_time_range(current) if session_time_range(current) else ''}\n\n从下拉列表选择场次后，卡片会自动回到控制台。",
        })
        options = []
        for item in sessions[:50]:
            marker = "采集中" if item.get("status") == "running" else "已结束"
            precise = " / 精确" if (item.get("results") or {}).get("precise") else " / 粗略"
            name = item.get("displayName") or item.get("baseName") or item.get("name") or "未命名场次"
            options.append({
                "text": plain_text(f"{item.get('activity', '未分类活动')} / {name} ({marker}{precise})"),
                "value": item.get("id", ""),
            })
        selector: dict[str, Any] = {
            "tag": "select_static",
            "name": "round_select",
            "placeholder": plain_text("选择要查看的场次"),
            "options": options,
            "value": {"action": "select_round"},
        }
        if selected_round_id and any(item.get("value") == selected_round_id for item in options):
            selector["initial_option"] = selected_round_id
        elements.append({"tag": "action", "actions": [selector]})
    elements.append(action_row(button("返回控制台", "control", "primary"), button("刷新状态", "refresh")))
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": "blue", "title": plain_text("场次管理")},
        "elements": elements,
    }
