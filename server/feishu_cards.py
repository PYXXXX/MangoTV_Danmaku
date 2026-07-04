"""Dependency-free Feishu interactive card rendering for vote operations."""

from __future__ import annotations

from typing import Any


def plain_text(content: str) -> dict[str, str]:
    return {"tag": "plain_text", "content": content}


def button(text: str, action: str, button_type: str = "default", **extra: str) -> dict[str, Any]:
    value = {"action": action, **extra}
    return {"tag": "button", "text": plain_text(text), "type": button_type, "value": value}


def action_row(*buttons: dict[str, Any]) -> dict[str, Any]:
    return {"tag": "action", "actions": list(buttons)}


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
    return f"{session.get('activity', '未分类活动')} / {session.get('name', '未命名场次')}"


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
                "点击“开始默认场次”会使用 WebUI 中配置的默认活动、候选人与直播源，"
                "自动创建下一轮。需要自定义活动名或候选人时，请先在 WebUI 的系统配置里保存。"
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
    elements.append(action_row(
        button("查看/切换场次", "show_rounds"),
        button("发布粗略结果", "publish_rough", "primary"),
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
            "content": f"**当前查看**\n{session_title(current)}\n\n从下拉列表选择场次后，卡片会自动回到控制台。",
        })
        options = []
        for item in sessions[:50]:
            marker = "采集中" if item.get("status") == "running" else "已结束"
            precise = " / 精确" if (item.get("results") or {}).get("precise") else " / 粗略"
            options.append({
                "text": plain_text(f"{item.get('activity', '未分类活动')} / {item.get('name', '未命名场次')} ({marker}{precise})"),
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
