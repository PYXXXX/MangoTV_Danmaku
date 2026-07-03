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
    template = "orange" if running else ("green" if session and (session.get("results") or {}).get("precise") else "blue")
    elements: list[dict[str, Any]] = []
    if notice:
        elements.append({"tag": "markdown", "content": f"**操作回执**\n{notice}"})
        elements.append({"tag": "hr"})
    if not session:
        elements.append({
            "tag": "markdown",
            "content": "**当前没有场次**\n点击下方按钮可按默认活动名创建场次；自定义名称请发送 `开始 活动名|场次名`。",
        })
    else:
        label, counts = result_counts(session)
        candidates = session.get("candidates") or []
        ranking = sorted(
            ((item.get("name", "未命名"), int(counts.get(item.get("id"), 0))) for item in candidates),
            key=lambda row: (-row[1], row[0]),
        )
        ranking_text = "\n".join(f"{index}. **{name}**  {votes}" for index, (name, votes) in enumerate(ranking, 1)) or "暂无候选人"
        status = "采集中" if selected_is_active else "已结束"
        elements.append({
            "tag": "markdown",
            "content": (
                f"**{session.get('activity', '未分类活动')} / {session.get('name', '未命名场次')}**\n"
                f"状态：{status}　结果：{label}\n"
                f"弹幕样本：**{int(session.get('messageCount') or 0)}**　语义待审：**{int(session.get('reviewCount') or 0)}**"
            ),
        })
        elements.extend([{"tag": "hr"}, {"tag": "markdown", "content": ranking_text}])
    if running:
        elements.append(action_row(
            button("结束本轮", "end_round", "danger"),
            button("刷新状态", "refresh", "default"),
        ))
    else:
        elements.append(action_row(
            button("开始默认场次", "start_default", "primary"),
            button("刷新状态", "refresh", "default"),
        ))
    elements.append(action_row(
        button("场次列表", "show_rounds"),
        button("发布粗略结果", "publish_rough", "primary"),
    ))
    if public_url:
        elements.append({
            "tag": "action",
            "actions": [{"tag": "button", "text": plain_text("打开公开结果页"), "type": "default", "url": public_url}],
        })
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": template, "title": plain_text("直播弹幕人气运营")},
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
        elements.append({"tag": "markdown", "content": "暂无场次。"})
    else:
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
    elements.append(action_row(button("返回控制台", "control", "primary")))
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {"template": "blue", "title": plain_text("活动与场次")},
        "elements": elements,
    }
