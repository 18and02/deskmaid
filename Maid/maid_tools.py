"""Local in-process MCP tools for the desktop maid."""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

import maid_tools_apple_apps as _apple_tools
import maid_tools_desktop as _desktop_tools
from maid_tools_shared import _run_applescript, _run_jxa_json


for _name, _value in vars(_apple_tools).items():
    if _name.startswith("__"):
        continue
    if _name in {
        "asyncio",
        "json",
        "time",
        "datetime",
        "timedelta",
        "Annotated",
        "NotRequired",
        "Required",
        "TypedDict",
        "tool",
    }:
        continue
    if _name in globals():
        continue
    globals()[_name] = _value

for _desktop_name in getattr(_desktop_tools, "__all__", ()):
    if _desktop_name in globals():
        continue
    globals()[_desktop_name] = getattr(_desktop_tools, _desktop_name)

del _desktop_name, _name, _value


TOOL_PREFERENCE_PROMPT = """\

# 本地工具偏好
- 当主人要你在 macOS 上打开、切到或唤起某个应用时，优先使用 `open_app` 工具。
- 对于“打开应用”这类事，不要改用 Bash 的 `open` 命令，除非 `open_app` 明确不适用。
- 当主人要你打开一个网页、URL、深链或本地文件链接时，优先使用 `open_url` 工具。
- 对于“打开这个链接 / 跳去这个网页”这类事，不要改用 Bash。
- 当主人要你判断当前正在操作哪个 macOS 应用时，优先使用 `get_frontmost_app` 工具。
- 对于“看看我现在正停在哪个应用 / 前台是什么”这类事，不要凭空猜。
- 当主人要你看看当前桌面上有哪些窗口、哪些应用开着窗口时，优先使用 `list_windows` 工具。
- 对于“列一下我现在开的窗口”这类事，不要凭空猜。
- 当主人要你切到某个指定窗口、把某个应用窗口抬到前台时，优先使用 `focus_window` 工具。
- 对于“切到这个窗口 / 把这个窗口带到前面”这类事，不要只回答你做了，除非工具真的成功了。
- 当主人要你读取系统剪贴板里的纯文本内容时，优先使用 `read_clipboard_text` 工具。
- 对于“看看我刚复制了什么文字”这类事，不要改用 Bash。
- 当主人要你把一段文字写进系统剪贴板时，优先使用 `set_clipboard_text` 工具。
- 对于“先帮我复制这段文字”这类事，不要改用 Bash。
- 当主人要你把一段文字输入到当前前台应用里时，优先使用 `paste_text` 工具。
- 对于“把这段内容贴进去 / 输入到当前窗口”这类事，不要凭空假装已经完成。
- 当主人要你按回车、Tab、Esc 或发送常见快捷键时，优先使用 `press_keys` 工具。
- 对于“按一下快捷键 / 帮我回车确认”这类事，不要改用 Bash。
- 当主人要你查看 macOS 日历里的安排、会议或接下来有什么日程时，优先使用 `list_calendar_events` 工具。
- 对于“看日历 / 查今天或接下来几天安排”这类事，不要凭空猜，也不要改用 Bash。
- 当主人要你查看 macOS 提醒事项、待办列表或最近到期的提醒时，优先使用 `list_reminders` 工具。
- 对于“看提醒事项 / 查待办”这类事，不要凭空猜，也不要改用 Bash。
- 当主人要你在 macOS 日历里新建日程、安排会议、改时间、改标题、改地点或删除日程时，优先使用 `create_calendar_event`、`update_calendar_event`、`delete_calendar_event` 工具。
- 对于“写入日历 / 改日历 / 删日历事件”这类事，不要改用 Bash。
- 当主人要你在 macOS 提醒事项里新增待办、改提醒内容、改截止时间、标记完成或删除提醒时，优先使用 `create_reminder`、`update_reminder`、`delete_reminder` 工具。
- 对于“写入提醒事项 / 改提醒 / 完成提醒 / 删提醒”这类事，不要改用 Bash。
- 当主人要你查看 macOS Mail 里的未读邮件标题、发件人或收件箱概况时，优先使用 `read_unread_mail_headers` 工具。
- 对于“看未读邮件 / 查收件箱”这类事，不要凭空猜，也不要改用 Bash。
- 当主人要你打开某封邮件、读邮件正文或查看一封指定邮件的内容时，优先使用 `read_mail_message` 工具。
- 对于“读这封邮件 / 看邮件正文”这类事，不要凭空猜，也不要改用 Bash。
- 当主人要你把某封邮件标记为已读时，优先使用 `mark_mail_read` 工具。
- 对于“把这封邮件设为已读”这类事，不要凭空猜，也不要改用 Bash。
- 当主人要你起草一封邮件、生成回复草稿、先存成草稿但不要发送时，优先使用 `create_mail_draft` 工具。
- 对于“帮我写邮件草稿 / 起一个回复草稿 / 附上本地文件做邮件附件”这类事，不要凭空猜，也不要改用 Bash。
- 当主人要你把已经写好的邮件草稿正式发出去时，优先使用 `send_mail_draft` 工具。
- 对于“发这封草稿 / 确认后发送邮件”这类事，不要改用 Bash，也不要绕过人工确认直接发送。
"""


def format_write_tool_receipt(tool_name: str, payload: dict[str, object]) -> str | None:
    if not tool_name or not isinstance(payload, dict):
        return None

    receipt = _desktop_tools.format_write_tool_receipt(tool_name, payload)
    if receipt is not None:
        return receipt
    return _apple_tools.format_write_tool_receipt(tool_name, payload)


MAID_MCP_SERVERS = {
    "deskmaid_local": create_sdk_mcp_server(
        name="deskmaid_local",
        tools=[
            open_app,
            open_url,
            get_frontmost_app,
            list_windows,
            focus_window,
            read_clipboard_text,
            set_clipboard_text,
            paste_text,
            press_keys,
            list_calendar_events,
            list_reminders,
            create_calendar_event,
            update_calendar_event,
            delete_calendar_event,
            create_reminder,
            update_reminder,
            delete_reminder,
            read_unread_mail_headers,
            read_mail_message,
            mark_mail_read,
            create_mail_draft,
            send_mail_draft,
        ],
    )
}
