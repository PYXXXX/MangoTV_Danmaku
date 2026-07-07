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


def start_round_form(
    default_activity: str,
    next_round_name: str,
    default_url: str = "",
    *,
    form_name: str = "start_round_form",
    submit_name: str = "start_round_submit",
    action: str = "start_custom",
    title: str = "自定义开始场次",
    intro: str = "活动名已按系统配置预填；场次名和直播 URL 可按需修改。",
    submit_text: str = "按表单开始采集",
) -> dict[str, Any]:
    return {
        "tag": "form",
        "name": form_name,
        "elements": [
            {"tag": "markdown", "content": f"**{title}**\n{intro}"},
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
                                "text": plain_text(submit_text),
                                "type": "primary",
                                "name": submit_name,
                                "form_action_type": "submit",
                                "value": {"action": action},
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


def nav_row(active: str = "") -> dict[str, Any]:
    labels = [
        ("活动监控", "show_monitor"),
        ("运营工作区", "show_ops"),
        ("录制后处理", "show_recording"),
        ("发布与结果", "show_publish"),
        ("系统状态", "show_system"),
    ]
    return action_row(*[
        button(label, action, "primary" if active == action else "default")
        for label, action in labels
    ])


def notice_elements(notice: str) -> list[dict[str, Any]]:
    if not notice:
        return []
    return [{"tag": "markdown", "content": f"**操作结果**\n{notice}"}, {"tag": "hr"}]


def card_note() -> dict[str, Any]:
    return {"tag": "note", "elements": [plain_text("坚持全卡片交互：按钮需要飞书企业自建应用已配置 card.action.trigger 卡片回调；若提示未配置，请联系管理员。")]}


def bytes_human(value: Any) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        size = 0
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    if unit == 0:
        return f"{int(size)} {units[unit]}"
    return f"{size:.1f} {units[unit]}"


def public_url_from_state(state: dict[str, Any], fallback: str = "") -> str:
    defaults = state.get("defaults") if isinstance(state.get("defaults"), dict) else {}
    return str(fallback or defaults.get("publicResultsUrl") or defaults.get("publicBaseUrl") or "")


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
    monitor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = select_session(state, selected_round_id)
    defaults = state.get("defaults") if isinstance(state.get("defaults"), dict) else {}
    default_activity = str(defaults.get("activity") or "未分类活动")
    active_id = state.get("activeSessionId")
    running = next((item for item in state.get("sessions") or [] if item.get("id") == active_id and item.get("status") == "running"), None)
    template, status_text, status_hint = top_status(state, session)
    monitor_config = (monitor or {}).get("config") or {}
    monitor_state = (monitor or {}).get("state") or {}
    elements: list[dict[str, Any]] = [nav_row()]
    elements.append({
        "tag": "markdown",
        "content": (
            f"**{status_text}｜{default_activity}**\n"
            f"{status_hint}\n"
            f"当前场次：{session_title(session)}\n"
            f"最近更新时间：{state.get('updatedAt') or '等待同步'}\n"
            f"活动监控：{'已开启' if monitor_config.get('enabled') else '未开启'}"
            f"{'｜' + str(monitor_state.get('message') or '') if monitor_state.get('message') else ''}"
        ),
    })
    elements.append({"tag": "hr"})
    elements.extend(notice_elements(notice))
    if not session:
        elements.append({
            "tag": "markdown",
            "content": (
                "**建议下一步**\n"
                f"默认活动：**{default_activity}**\n"
                "如果你正在实时盯直播，进“运营工作区”开一轮；如果需要无人值守，先到“活动监控”检查监控和录制策略。"
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
    primary = button("进入运营工作区", "show_ops", "primary")
    if running:
        elements.append(action_row(primary, button("结束并发布粗略结果", "end_round", "danger"), button("刷新", "refresh")))
    else:
        elements.append(action_row(primary, button("开始默认实时场次", "start_realtime", "primary"), button("刷新", "refresh")))
    elements.append(action_row(
        button("查看/切换场次", "show_rounds"),
        button("发布与结果", "show_publish"),
        button("录制后处理", "show_recording"),
    ))
    public_url = public_url_from_state(state, public_url)
    if public_url:
        elements.append({
            "tag": "action",
            "actions": [{"tag": "button", "text": plain_text("打开公开结果页"), "type": "default", "url": public_url}],
        })
    elements.append(card_note())
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": template, "title": plain_text("直播运营工作台")},
        "elements": elements,
    }


def build_ops_card(
    state: dict[str, Any],
    selected_round_id: str | None = None,
    notice: str = "",
) -> dict[str, Any]:
    session = select_session(state, selected_round_id)
    defaults = state.get("defaults") if isinstance(state.get("defaults"), dict) else {}
    default_activity = str(defaults.get("activity") or "未分类活动")
    default_url = str(defaults.get("mgtvUrl") or "")
    next_round_name = f"第 {len(state.get('sessions') or []) + 1} 轮"
    active_id = state.get("activeSessionId")
    running = next((item for item in state.get("sessions") or [] if item.get("id") == active_id and item.get("status") == "running"), None)
    elements: list[dict[str, Any]] = [nav_row("show_ops")]
    elements.extend(notice_elements(notice))
    if running:
        elements.append({
            "tag": "markdown",
            "content": (
                f"**实时运营中｜{session_title(running)}**\n"
                f"{'采集时间：' + session_time_range(running) if session_time_range(running) else '采集时间：刚刚开始'}\n"
                f"弹幕样本：**{int(running.get('messageCount') or 0)}**，语义待审：**{int(running.get('reviewCount') or 0)}**"
            ),
        })
        elements.append(action_row(button("结束并发布粗略结果", "end_round", "danger"), button("刷新工作区", "show_ops")))
    else:
        elements.append({
            "tag": "markdown",
            "content": (
                "**实时运营**\n"
                "适合你正在看直播的场景：开一轮、实时切片弹幕、结束后发布粗略结果。\n\n"
                "**录制采集**\n"
                "适合无人值守：同时录制视频和完整弹幕，之后在“录制后处理”里打标、切片和分析。"
            ),
        })
        elements.append(action_row(
            button("开始默认实时场次", "start_realtime", "primary"),
            button("开始默认录制采集", "start_record", "default"),
            button("刷新工作区", "show_ops"),
        ))
        elements.append(start_round_form(
            default_activity,
            next_round_name,
            default_url,
            form_name="start_realtime_form",
            submit_name="start_realtime_submit",
            action="start_realtime",
            title="开始实时运营场次",
            intro="只采集和分析弹幕，不主动录制视频。活动名默认来自系统配置。",
            submit_text="开始实时场次",
        ))
        elements.append(start_round_form(
            default_activity,
            f"全程录制 {len(state.get('sessions') or []) + 1}",
            default_url,
            form_name="start_record_form",
            submit_name="start_record_submit",
            action="start_record",
            title="开始全程录制与弹幕",
            intro="会同时开启视频录制和弹幕采集；录制源以系统配置/自动检测结果为准。",
            submit_text="开始录制采集",
        ))
    if session:
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": f"**当前选中**\n{session_title(session)}"})
        elements.append(action_row(button("发送结果 PNG", "send_png"), button("发布与结果", "show_publish"), button("切换场次", "show_rounds")))
    elements.append(card_note())
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": "blue", "title": plain_text("运营工作区")},
        "elements": elements,
    }


def build_monitor_card(
    state: dict[str, Any],
    monitor: dict[str, Any],
    notice: str = "",
) -> dict[str, Any]:
    config = monitor.get("config") if isinstance(monitor.get("config"), dict) else {}
    status = monitor.get("state") if isinstance(monitor.get("state"), dict) else {}
    elements: list[dict[str, Any]] = [nav_row("show_monitor")]
    elements.extend(notice_elements(notice))
    elements.append({
        "tag": "markdown",
        "content": (
            f"**活动监控｜{config.get('activity') or '未分类活动'}**\n"
            f"状态：**{status.get('message') or status.get('status') or '未启动'}**\n"
            f"活动链接：{config.get('url') or '未配置'}\n"
            f"自动检测直播源：{'开启' if config.get('autoDetectSource') else '关闭'}\n"
            f"自动录制视频：{'开启' if config.get('autoRecordVideo') else '关闭'}｜弹幕采集：{'开启' if config.get('autoRecordDanmaku') else '关闭'}\n"
            f"飞书通知：{'开启' if config.get('feishuNotify') else '关闭'}｜轮询间隔：{config.get('pollSeconds') or '-'} 秒"
        ),
    })
    if status.get("lastCheckAt") or status.get("lastError"):
        elements.append({
            "tag": "markdown",
            "content": f"最近检查：{status.get('lastCheckAt') or '-'}\n最近错误：{status.get('lastError') or '无'}",
        })
    elements.append(action_row(button("刷新监控状态", "show_monitor", "primary"), button("进入运营工作区", "show_ops")))
    elements.append({"tag": "note", "elements": [plain_text("监控策略请在 WebUI 系统配置中调整；飞书侧负责查看状态与接收提醒。")]})
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": "turquoise" if config.get("enabled") else "grey", "title": plain_text("活动监控")},
        "elements": elements,
    }


def build_publish_card(
    state: dict[str, Any],
    selected_round_id: str | None = None,
    notice: str = "",
    public_url: str = "",
) -> dict[str, Any]:
    session = select_session(state, selected_round_id)
    elements: list[dict[str, Any]] = [nav_row("show_publish")]
    elements.extend(notice_elements(notice))
    if not session:
        elements.append({"tag": "markdown", "content": "**暂无可发布场次**\n请先在运营工作区开始并结束一轮。"})
    else:
        label, _ = result_counts(session)
        precise_ready = bool((session.get("results") or {}).get("precise"))
        elements.append({
            "tag": "markdown",
            "content": (
                f"**{session_title(session)}**\n"
                f"{'采集时间：' + session_time_range(session) if session_time_range(session) else ''}\n"
                f"当前结果：**{label}**｜精确结果：{'已发布' if precise_ready else '未上传'}\n"
                f"弹幕样本：**{int(session.get('messageCount') or 0)}**｜有效候选人：**{len(session.get('candidates') or [])}**"
            ),
        })
        elements.append({"tag": "markdown", "content": ranking_markdown(session)})
        elements.append(action_row(
            button("发送当前场次 PNG", "send_png", "primary"),
            button("发布粗略结果", "publish_rough", "default"),
            button("切换场次", "show_rounds", "default"),
        ))
        if session.get("status") != "running":
            elements.append(action_row(
                button(
                    "删除所选场次",
                    "delete_round",
                    "danger",
                    confirm=danger_confirm("删除所选场次？", "删除后会立即同步公开页，运营端和飞书也会移除此场次。"),
                ),
                button(
                    "删除当前活动",
                    "delete_activity",
                    "danger",
                    confirm=danger_confirm("删除当前活动？", "会删除当前活动下全部已结束场次，并立即同步公开页；若仍有采集中场次，系统会拒绝删除。"),
                ),
            ))
    public_url = public_url_from_state(state, public_url)
    if public_url:
        elements.append({
            "tag": "action",
            "actions": [{"tag": "button", "text": plain_text("打开公开结果页"), "type": "default", "url": public_url}],
        })
    elements.append(card_note())
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": "green", "title": plain_text("发布与结果")},
        "elements": elements,
    }


def build_system_card(system: dict[str, Any], notice: str = "") -> dict[str, Any]:
    services = system.get("services") if isinstance(system.get("services"), dict) else {}
    memory = system.get("memory") if isinstance(system.get("memory"), dict) else {}
    cpu = system.get("cpu") if isinstance(system.get("cpu"), dict) else {}
    disk = system.get("disk") if isinstance(system.get("disk"), dict) else {}
    health = system.get("health") if isinstance(system.get("health"), dict) else {}
    data_disk = disk.get("data") if isinstance(disk.get("data"), dict) else {}
    recording_disk = disk.get("recordings") if isinstance(disk.get("recordings"), dict) else {}
    service_lines = []
    for key, label in [
        ("monitor", "活动监控"),
        ("collector", "弹幕采集"),
        ("recorder", "直播录制"),
        ("feishu", "飞书 Bot"),
        ("github", "GitHub 发布"),
        ("updater", "程序升级"),
    ]:
        item = services.get(key) if isinstance(services.get(key), dict) else {}
        service_lines.append(f"- {label}：**{item.get('status') or 'unknown'}**{('｜' + str(item.get('message'))) if item.get('message') else ''}")
    elements: list[dict[str, Any]] = [nav_row("show_system")]
    elements.extend(notice_elements(notice))
    elements.append({
        "tag": "markdown",
        "content": (
            f"**机器状态｜{health.get('status') or 'unknown'}**\n"
            f"系统时间：{system.get('systemTime') or '-'}\n"
            f"运行时长：{int(system.get('uptimeSeconds') or 0)} 秒\n"
            f"CPU：{cpu.get('count') or '-'} 核｜负载：{cpu.get('loadPercent') if cpu.get('loadPercent') is not None else '-'}%\n"
            f"内存：进程 {bytes_human(memory.get('processRssBytes'))} / 总计 {bytes_human(memory.get('totalBytes'))}\n"
            f"数据盘可用：{bytes_human(data_disk.get('freeBytes'))}｜录制盘可用：{bytes_human(recording_disk.get('freeBytes'))}"
        ),
    })
    if health.get("restartRequired"):
        elements.append({"tag": "markdown", "content": f"**需重启生效配置**\n{', '.join(health.get('restartFields') or [])}"})
    elements.append({"tag": "markdown", "content": "**服务状态**\n" + "\n".join(service_lines)})
    elements.append(action_row(button("刷新系统状态", "show_system", "primary"), button("返回首页", "control")))
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": "red" if health.get("status") == "error" else ("orange" if health.get("status") == "warning" else "green"), "title": plain_text("系统状态")},
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
    elements: list[dict[str, Any]] = [nav_row("show_recording")]
    elements.extend(notice_elements(notice))
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
                lines.append(f"- {clip.get('label') or '未命名片段'}：{clip.get('startSeconds', 0)}s-{clip.get('endSeconds', 0)}s")
            elements.append({"tag": "markdown", "content": "\n".join(lines)})
            elements.append(action_row(button("生成最近片段分析场次", "analyze_latest_clip", "primary")))
        elements.append(recording_marker_form())
        elements.append(recording_clip_form())
    elements.append(action_row(button("返回运营工作区", "show_ops", "primary"), button("刷新状态", "show_recording"), button("发布与结果", "show_publish")))
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
    elements: list[dict[str, Any]] = [nav_row()]
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
    elements.append(action_row(button("返回首页", "control", "primary"), button("运营工作区", "show_ops"), button("发布与结果", "show_publish")))
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": "blue", "title": plain_text("场次管理")},
        "elements": elements,
    }
