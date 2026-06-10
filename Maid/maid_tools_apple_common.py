"""Shared formatting helpers for Calendar, Reminders, and Mail tool domains."""

from __future__ import annotations

from datetime import datetime, timedelta

from maid_tools_shared import _local_now, _normalize_calendar_names

def _trim_preview_block(text: str, limit: int = 1200) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return "（空）"
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _format_address_line(values: list[str] | None) -> str:
    addresses = _normalize_calendar_names(values)
    return "，".join(addresses) if addresses else "（无）"


def _format_size_bytes(value: object) -> str:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _format_attachment_preview_lines(attachments: list[dict[str, object]] | None) -> list[str]:
    rows = attachments or []
    if not rows:
        return ["附件: （无）"]

    lines = [f"附件: {len(rows)} 个"]
    for item in rows[:6]:
        name = str(item.get("name") or "").strip() or "未命名附件"
        size_label = _format_size_bytes(item.get("size_bytes"))
        suffix = f" ({size_label})" if size_label else ""
        lines.append(f"  - {name}{suffix}")
    extra_count = len(rows) - 6
    if extra_count > 0:
        lines.append(f"  - 以及另外 {extra_count} 个")
    return lines


def _format_frontmost_app_label(
    app: dict[str, object] | None,
    *,
    fallback: str = "（未知应用）",
) -> str:
    payload = dict(app or {})
    localized_name = str(payload.get("localized_name") or "").strip()
    bundle_id = str(payload.get("bundle_id") or "").strip()
    if localized_name and bundle_id:
        return f"{localized_name} ({bundle_id})"
    return localized_name or bundle_id or fallback


def _format_text_length_label(
    text: object = None,
    *,
    length: object | None = None,
) -> str:
    try:
        count = int(length if length is not None else len(str(text or "")))
    except (TypeError, ValueError):
        count = len(str(text or ""))
    return f"{count} 字"


def _format_receipt_text_snippet(text: object, limit: int = 32) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return "（空）"
    single_line = normalized.replace("\n", " / ")
    if len(single_line) <= limit:
        return single_line
    return single_line[: max(0, limit - 1)].rstrip() + "…"


def _format_mailbox_label(
    account: object,
    mailbox: object,
    *,
    fallback: str = "（未定位到保存邮箱）",
) -> str:
    account_text = str(account or "").strip()
    mailbox_text = str(mailbox or "").strip()
    return " / ".join(part for part in (account_text, mailbox_text) if part) or fallback


def _format_mail_subject_label(message: dict[str, object]) -> str:
    subject = str(message.get("subject") or "").strip()
    if subject:
        return subject
    if str(message.get("mode") or "").strip() == "reply":
        return "（回复主题由 Mail 自动生成）"
    return "（无主题）"


def _format_mail_attachment_receipt_line(message: dict[str, object]) -> str | None:
    rows = [
        item
        for item in (message.get("attachments") or [])
        if isinstance(item, dict)
    ]
    names = [
        str(item.get("name") or "").strip()
        for item in rows
        if str(item.get("name") or "").strip()
    ]
    try:
        count = int(message.get("attachment_count") or len(rows))
    except (TypeError, ValueError):
        count = len(rows)

    if count <= 0 and not names:
        return None
    if count <= 1 and names:
        return f"附件: {names[0]}"
    if count <= 1:
        return "附件: 1 个"

    shown = names[:2]
    if not shown:
        return f"附件: {count} 个"
    suffix = " 等" if count > len(shown) else ""
    return f"附件: {count} 个（{'，'.join(shown)}{suffix}）"


def _format_mail_receipt_lines(
    message: dict[str, object],
    *,
    include_sender: bool = False,
    include_mailbox: bool = False,
) -> list[str]:
    lines = [f"主题: {_format_mail_subject_label(message)}"]
    if include_sender:
        sender = str(message.get("sender") or "").strip()
        if sender:
            lines.append(f"发件人: {sender}")
    lines.append(f"收件人: {_format_address_line(message.get('to'))}")
    cc = _normalize_calendar_names(message.get("cc"))
    if cc:
        lines.append(f"抄送: {'，'.join(cc)}")
    bcc = _normalize_calendar_names(message.get("bcc"))
    if bcc:
        lines.append(f"密送: {'，'.join(bcc)}")
    attachment_line = _format_mail_attachment_receipt_line(message)
    if attachment_line:
        lines.append(attachment_line)
    if include_mailbox:
        mailbox_label = _format_mailbox_label(
            message.get("account"),
            message.get("mailbox"),
            fallback="",
        )
        if mailbox_label:
            lines.append(f"邮箱: {mailbox_label}")
    return lines


def _format_boolean_label(value: object) -> str:
    return "是" if bool(value) else "否"


def _parse_preview_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_local_now().tzinfo)
    return parsed.astimezone()


def _format_preview_datetime(value: object, *, date_only: bool = False) -> str:
    parsed = _parse_preview_datetime(value)
    if parsed is None:
        return str(value or "").strip() or "（无）"
    if date_only:
        return parsed.strftime("%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d %H:%M")


def _format_calendar_time_window(
    start: object,
    end: object,
    *,
    all_day: bool,
) -> str:
    if all_day:
        start_dt = _parse_preview_datetime(start)
        end_dt = _parse_preview_datetime(end)
        if start_dt is None:
            return "（无）"
        if end_dt is None:
            return f"{start_dt.strftime('%Y-%m-%d')} 全天"
        end_display = (end_dt - timedelta(seconds=1)).date()
        if end_display <= start_dt.date():
            return f"{start_dt.strftime('%Y-%m-%d')} 全天"
        return (
            f"{start_dt.strftime('%Y-%m-%d')} 至 "
            f"{end_display.isoformat()} 全天"
        )
    start_label = _format_preview_datetime(start)
    end_label = _format_preview_datetime(end)
    if end_label == "（无）":
        return start_label
    return f"{start_label} - {end_label}"


def _format_priority_label(value: object) -> str:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        return "（无）"
    if priority <= 0:
        return "无"
    if priority <= 3:
        return f"{priority}（高）"
    if priority <= 6:
        return f"{priority}（中）"
    return f"{priority}（低）"


def _format_receipt_datetime(value: object, *, date_only: bool = False) -> str:
    parsed = _parse_preview_datetime(value)
    if parsed is None:
        return str(value or "").strip() or "（无）"
    if date_only:
        return parsed.strftime("%m-%d")
    return parsed.strftime("%m-%d %H:%M")


def _format_calendar_receipt_window(
    start: object,
    end: object,
    *,
    all_day: bool,
) -> str:
    if all_day:
        start_dt = _parse_preview_datetime(start)
        end_dt = _parse_preview_datetime(end)
        if start_dt is None:
            return "（无）"
        if end_dt is None:
            return f"{start_dt.strftime('%m-%d')} 全天"
        end_display = (end_dt - timedelta(seconds=1)).date()
        start_display = start_dt.date()
        if end_display <= start_display:
            return f"{start_dt.strftime('%m-%d')} 全天"
        return f"{start_dt.strftime('%m-%d')} 至 {end_display.strftime('%m-%d')} 全天"
    start_label = _format_receipt_datetime(start)
    end_label = _format_receipt_datetime(end)
    if end_label == "（无）":
        return start_label
    return f"{start_label} - {end_label}"


def _format_receipt_priority(value: object) -> str:
    raw = _format_priority_label(value)
    if raw in {"无", "（无）"}:
        return ""
    return raw
