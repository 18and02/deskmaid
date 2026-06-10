"""System permission and runtime self-checks for the desktop maid."""

from __future__ import annotations

import ctypes
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from typing import NotRequired, TypedDict

from maid_claude_cli import find_claude_cli_path
from maid_permission_recovery import (
    accessibility_permission_hint,
    automation_permission_hint,
    enrich_permission_health_check,
    clean_permission_detail,
    looks_like_accessibility_denied,
    looks_like_automation_denied,
    looks_like_timeout,
    permission_refresh_hint,
    timeout_recovery_hint,
)


STATUS_LABELS = {
    "ok": "已就绪",
    "warning": "留意",
    "error": "未就绪",
}


class HealthCheck(TypedDict):
    key: str
    title: str
    status: str
    status_label: str
    summary: str
    detail: str
    hint: str
    tools: list[str]
    actions: NotRequired[list[dict[str, object]]]


class HealthSnapshot(TypedDict):
    checked_at: float
    ok_count: int
    warning_count: int
    error_count: int
    summary_text: str
    checks: list[HealthCheck]


def _make_check(
    key: str,
    title: str,
    status: str,
    summary: str,
    detail: str = "",
    hint: str = "",
    tools: list[str] | None = None,
) -> HealthCheck:
    return {
        "key": key,
        "title": title,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "summary": summary,
        "detail": detail.strip(),
        "hint": hint.strip(),
        "tools": list(tools or []),
    }


def _clean_detail(detail: str) -> str:
    return clean_permission_detail(detail)


def _run_osascript(args: list[str], timeout_s: float = 8.0) -> str:
    proc = subprocess.run(
        ["osascript", *args],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        detail = _clean_detail(proc.stderr or proc.stdout)
        raise RuntimeError(detail or f"osascript exited with code {proc.returncode}")
    return (proc.stdout or "").strip()


def _run_jxa_json(script: str, timeout_s: float = 8.0) -> dict[str, object]:
    raw = _run_osascript(
        [
            "-l",
            "JavaScript",
            "-e",
            script,
        ],
        timeout_s=timeout_s,
    )
    if not raw.strip():
        raise RuntimeError("osascript returned no output")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"osascript returned invalid JSON: {raw!r}") from exc

def _format_names(names: list[str], empty_label: str) -> str:
    if not names:
        return empty_label
    preview = names[:4]
    label = "，".join(preview)
    extra = len(names) - len(preview)
    if extra > 0:
        label += f" 等 {len(names)} 项"
    return label


def _probe_appkit_bridge() -> HealthCheck:
    tools = [
        "open_app",
        "open_url",
        "get_frontmost_app",
        "read_clipboard_text",
        "set_clipboard_text",
    ]
    try:
        from AppKit import (  # noqa: F401
            NSPasteboard,
            NSRunningApplication,
            NSWorkspace,
            NSWorkspaceOpenConfiguration,
        )
    except Exception as exc:
        return _make_check(
            "appkit_bridge",
            "AppKit 桥接",
            "error",
            "PyObjC / AppKit 不可用",
            detail=_clean_detail(str(exc)),
            hint="检查当前虚拟环境里的 PyObjC 依赖是否完整。",
            tools=tools,
        )
    return _make_check(
        "appkit_bridge",
        "AppKit 桥接",
        "ok",
        "本地 AppKit / NSWorkspace 可用",
        detail="打开应用、打开链接、前台应用检测和系统剪贴板桥接都具备底层依赖。",
        tools=tools,
    )


def _probe_window_bridge() -> HealthCheck:
    tools = ["list_windows", "focus_window"]
    try:
        from Quartz import (  # noqa: F401
            CGWindowListCopyWindowInfo,
            kCGWindowBounds,
            kCGWindowName,
            kCGWindowNumber,
            kCGWindowOwnerName,
            kCGWindowOwnerPID,
        )
    except Exception as exc:
        return _make_check(
            "window_bridge",
            "Quartz 窗口桥接",
            "error",
            "Quartz 窗口枚举不可用",
            detail=_clean_detail(str(exc)),
            hint="检查当前虚拟环境里的 pyobjc-framework-Quartz 是否完整。",
            tools=tools,
        )
    return _make_check(
        "window_bridge",
        "Quartz 窗口桥接",
        "ok",
        "窗口枚举可用",
        detail="当前桌面窗口列表和基于 window_id 的窗口聚焦具备底层依赖。",
        tools=tools,
    )


def _probe_osascript_runtime() -> HealthCheck:
    tools = [
        "list_calendar_events",
        "list_reminders",
        "read_unread_mail_headers",
        "paste_text",
        "press_keys",
        "focus_window",
    ]
    script = 'function run() { return JSON.stringify({ ok: true }); }'
    try:
        result = _run_jxa_json(script, timeout_s=6.0)
    except Exception as exc:
        return _make_check(
            "osascript_runtime",
            "osascript / JXA 运行时",
            "error",
            "AppleScript / JXA 运行时不可用",
            detail=_clean_detail(str(exc)),
            hint="确认系统的 osascript 可执行，且当前环境没有拦住脚本执行。",
            tools=tools,
        )
    if not bool(result.get("ok")):
        return _make_check(
            "osascript_runtime",
            "osascript / JXA 运行时",
            "error",
            "AppleScript / JXA 返回了异常结果",
            detail=_clean_detail(json.dumps(result, ensure_ascii=False, sort_keys=True)),
            hint="重试一次；如果仍异常，优先排查 osascript 本身是否可正常运行。",
            tools=tools,
        )
    return _make_check(
        "osascript_runtime",
        "osascript / JXA 运行时",
        "ok",
        "AppleScript / JXA 可执行",
        detail="Calendar / Reminders / Mail 相关脚本桥接具备运行时依赖。",
        tools=tools,
    )


def _probe_claude_code_cli() -> HealthCheck:
    tools = []
    cli_path = find_claude_cli_path()
    if cli_path is None:
        return _make_check(
            "claude_code_cli",
            "Claude Code 运行时",
            "error",
            "还没找到 Claude Code CLI",
            detail="当前 Agent SDK 会话无法定位到 `claude` 可执行文件。",
            hint=(
                "开发态请安装 `claude`，或设置 `MAID_CLAUDE_CLI_PATH`；"
                "打包态请重新构建 .app，确认内置 CLI 已被带进 bundle。"
            ),
            tools=tools,
        )

    detail = f"CLI: {cli_path}"
    if not cli_path.is_absolute():
        detail += "\n来源: PATH"
    return _make_check(
        "claude_code_cli",
        "Claude Code 运行时",
        "ok",
        "Claude Code CLI 可用",
        detail=detail,
        tools=tools,
    )


def _find_bundle_root(executable: Path) -> Path | None:
    for candidate in [executable, *executable.parents]:
        if candidate.suffix == ".app":
            return candidate
    return None


def _probe_bundle_runtime() -> HealthCheck:
    tools = [
        "open_app",
        "focus_window",
        "paste_text",
        "press_keys",
        "list_calendar_events",
        "list_reminders",
        "read_unread_mail_headers",
        "read_mail_message",
        "create_mail_draft",
        "send_mail_draft",
    ]
    executable = Path(sys.executable).resolve()
    bundle_root = _find_bundle_root(executable)
    frozen = bool(getattr(sys, "frozen", False))
    if bundle_root is None:
        return _make_check(
            "bundle_runtime",
            "打包后运行时宿主",
            "warning",
            "当前不是从 .app bundle 里运行",
            detail=f"当前解释器: {executable}\nfrozen={frozen!r}",
            hint="打包出 .app 后，从 bundle 里的可执行文件重新跑一次权限自检。",
            tools=tools,
        )

    info_path = bundle_root / "Contents" / "Info.plist"
    bundle_executable = ""
    try:
        with info_path.open("rb") as fh:
            info = plistlib.load(fh)
        bundle_executable = str(info.get("CFBundleExecutable") or "").strip()
    except Exception as exc:
        return _make_check(
            "bundle_runtime",
            "打包后运行时宿主",
            "error",
            "当前像是在 bundle 里，但运行时元数据读不出来",
            detail=_clean_detail(str(exc)),
            hint="先确认打包产物完整，再重跑一次自检。",
            tools=tools,
        )

    detail_parts = [
        f"bundle: {bundle_root}",
        f"executable: {executable}",
        f"CFBundleExecutable: {bundle_executable or '（缺失）'}",
        f"frozen: {frozen!r}",
    ]
    detail = "\n".join(detail_parts)
    if bundle_executable and executable.name != bundle_executable:
        return _make_check(
            "bundle_runtime",
            "打包后运行时宿主",
            "error",
            "当前进程名和 bundle 里的可执行文件名对不上",
            detail=detail,
            hint="检查打包脚本是否真的把主程序装进了 bundle。",
            tools=tools,
        )

    if not frozen:
        return _make_check(
            "bundle_runtime",
            "打包后运行时宿主",
            "warning",
            "当前在 bundle 路径里，但还不是 frozen 打包运行时",
            detail=detail,
            hint="如果你期待的是 PyInstaller / py2app 产物，确认入口确实来自打包后的可执行文件。",
            tools=tools,
        )

    return _make_check(
        "bundle_runtime",
        "打包后运行时宿主",
        "ok",
        "当前进程确实跑在 .app bundle 里",
        detail=detail,
        tools=tools,
    )


def _probe_bundle_tcc_metadata() -> HealthCheck:
    tools = [
        "open_app",
        "focus_window",
        "paste_text",
        "press_keys",
        "list_calendar_events",
        "list_reminders",
        "read_unread_mail_headers",
        "read_mail_message",
        "create_mail_draft",
        "send_mail_draft",
    ]
    executable = Path(sys.executable).resolve()
    bundle_root = _find_bundle_root(executable)
    if bundle_root is None:
        return _make_check(
            "bundle_tcc_metadata",
            "打包后的 TCC 元数据",
            "warning",
            "当前不是从 .app bundle 里运行",
            detail=f"当前解释器: {executable}",
            hint="打包出 .app 后，从 bundle 里重新跑一次权限自检。",
            tools=tools,
        )

    info_path = bundle_root / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as fh:
            info = plistlib.load(fh)
    except FileNotFoundError:
        return _make_check(
            "bundle_tcc_metadata",
            "打包后的 TCC 元数据",
            "error",
            "没找到 bundle 里的 Info.plist",
            detail=str(info_path),
            hint="检查打包产物是否完整，尤其是 Contents/Info.plist。",
            tools=tools,
        )
    except Exception as exc:
        return _make_check(
            "bundle_tcc_metadata",
            "打包后的 TCC 元数据",
            "error",
            "bundle 里的 Info.plist 读不出来",
            detail=_clean_detail(str(exc)),
            hint="先修好打包产物，再回来重跑权限自检。",
            tools=tools,
        )

    bundle_id = str(info.get("CFBundleIdentifier") or "").strip()
    has_apple_events_usage = bool(
        str(info.get("NSAppleEventsUsageDescription") or "").strip()
    )
    lsui_element = info.get("LSUIElement")

    detail_parts = [
        f"bundle: {bundle_root.name}",
        f"bundle_id: {bundle_id or '（缺失）'}",
        f"LSUIElement: {lsui_element!r}",
        (
            "NSAppleEventsUsageDescription: 已设置"
            if has_apple_events_usage
            else "NSAppleEventsUsageDescription: 缺失"
        ),
    ]
    detail = "\n".join(detail_parts)

    if not bundle_id:
        return _make_check(
            "bundle_tcc_metadata",
            "打包后的 TCC 元数据",
            "error",
            "bundle 缺少 CFBundleIdentifier",
            detail=detail,
            hint="没有稳定 bundle id，TCC 授权记录会很别扭。",
            tools=tools,
        )

    if not has_apple_events_usage:
        return _make_check(
            "bundle_tcc_metadata",
            "打包后的 TCC 元数据",
            "error",
            "bundle 缺少 NSAppleEventsUsageDescription",
            detail=detail,
            hint="没有这项说明，Apple Events 自动化权限在打包后容易直接翻车。",
            tools=tools,
        )

    if lsui_element is True:
        summary = "bundle 的关键 TCC / 前台行为元数据看起来齐了（后台 accessory 形态）"
    else:
        summary = "bundle 的关键 TCC / 前台行为元数据看起来齐了（常规 Dock App 形态）"

    return _make_check(
        "bundle_tcc_metadata",
        "打包后的 TCC 元数据",
        "ok",
        summary,
        detail=detail,
        tools=tools,
    )


def _probe_bundle_signature_identity() -> HealthCheck:
    tools = []
    executable = Path(sys.executable).resolve()
    bundle_root = _find_bundle_root(executable)
    if bundle_root is None:
        return _make_check(
            "bundle_signature_identity",
            "打包后的签名身份",
            "warning",
            "当前不是从 .app bundle 里运行",
            detail=f"当前解释器: {executable}",
            hint="打包出 .app 后，从 bundle 里重新跑一次权限自检。",
            tools=tools,
        )

    proc = subprocess.run(
        ["codesign", "-dv", "--verbose=4", str(bundle_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    raw = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        return _make_check(
            "bundle_signature_identity",
            "打包后的签名身份",
            "warning",
            "无法读取 bundle 的 codesign 信息",
            detail=_clean_detail(raw),
            hint="先确认本机能正常执行 `codesign -dv`，再回来刷新。",
            tools=tools,
        )

    info: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        info[key.strip()] = value.strip()

    signature = str(info.get("Signature") or "").strip()
    team_id = str(info.get("TeamIdentifier") or "").strip()
    identifier = str(info.get("Identifier") or "").strip()
    detail = "\n".join(
        [
            f"bundle: {bundle_root.name}",
            f"identifier: {identifier or '（缺失）'}",
            f"signature: {signature or '（未知）'}",
            f"team_id: {team_id or '（缺失）'}",
        ]
    )

    if signature.lower() == "adhoc" or not team_id or team_id == "not set":
        return _make_check(
            "bundle_signature_identity",
            "打包后的签名身份",
            "warning",
            "当前 bundle 仍是 ad-hoc 签名，自动化页里未必会稳定显示成 Deskmaid",
            detail=detail,
            hint=(
                "要让 TCC / 自动化更稳定地记成 Deskmaid，建议用 Apple Development "
                "或 Developer ID 证书重签并重新启动，再从 /Applications 里的 app "
                "直接触发一次 Calendar / Reminders / Mail。"
            ),
            tools=tools,
        )

    return _make_check(
        "bundle_signature_identity",
        "打包后的签名身份",
        "ok",
        "bundle 已有稳定签名身份，TCC / 自动化记录更容易稳定归到 Deskmaid",
        detail=detail,
        tools=tools,
    )


def _probe_current_process_accessibility() -> HealthCheck:
    tools = ["focus_window", "paste_text", "press_keys"]
    executable = Path(sys.executable).name or sys.executable
    try:
        library = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        library.AXIsProcessTrusted.restype = ctypes.c_bool
        trusted = bool(library.AXIsProcessTrusted())
    except Exception as exc:
        return _make_check(
            "current_process_accessibility",
            "辅助功能（当前进程）",
            "warning",
            "当前进程的辅助功能状态不可判定",
            detail=_clean_detail(str(exc)),
            hint="如果以后切到原生 AX API，这项需要能正常检测到。",
            tools=tools,
        )

    if trusted:
        return _make_check(
            "current_process_accessibility",
            "辅助功能（当前进程）",
            "ok",
            "当前 Python 进程已获辅助功能授权",
            detail=f"当前解释器: {executable}",
            tools=tools,
        )

    return _make_check(
        "current_process_accessibility",
        "辅助功能（当前进程）",
        "warning",
        "当前 Python 进程没有辅助功能授权",
        detail=f"当前解释器: {executable}",
        hint=accessibility_permission_hint(),
        tools=tools,
    )


def _probe_system_events_ui() -> HealthCheck:
    tools = ["paste_text", "press_keys", "focus_window"]
    script = (
        'tell application "System Events" '
        "to tell first application process whose frontmost is true "
        "to return count of windows"
    )
    try:
        raw = _run_osascript(["-e", script], timeout_s=8.0).strip()
    except Exception as exc:
        detail = _clean_detail(str(exc))
        if looks_like_accessibility_denied(detail):
            return _make_check(
                "system_events_ui",
                "System Events UI 脚本",
                "error",
                "辅助功能未授权",
                detail=detail,
                hint=accessibility_permission_hint(),
                tools=tools,
            )
        if looks_like_automation_denied(detail):
            return _make_check(
                "system_events_ui",
                "System Events UI 脚本",
                "error",
                "System Events 自动化未授权",
                detail=detail,
                hint=automation_permission_hint("System Events"),
                tools=tools,
            )
        if looks_like_timeout(detail):
            return _make_check(
                "system_events_ui",
                "System Events UI 脚本",
                "warning",
                "System Events 检查超时了",
                detail=detail,
                hint=timeout_recovery_hint(),
                tools=tools,
            )
        return _make_check(
            "system_events_ui",
            "System Events UI 脚本",
            "error",
            "System Events 检查失败",
            detail=detail,
            hint=permission_refresh_hint(),
            tools=tools,
        )

    try:
        window_count = int(raw or "0")
    except ValueError:
        window_count = None

    detail = (
        f"前台应用当前可见窗口数: {window_count}"
        if window_count is not None
        else f"脚本返回: {raw or '（空）'}"
    )
    return _make_check(
        "system_events_ui",
        "System Events UI 脚本",
        "ok",
        "键盘输入和窗口抬前所需的 UI 脚本可用",
        detail=detail,
        tools=tools,
    )


_CALENDAR_PROBE_JXA = r"""
function run() {
  var app = Application("Calendar");
  var calendars = app.calendars();
  var names = [];
  for (var i = 0; i < calendars.length; i++) {
    names.push(String(calendars[i].name() || ""));
  }
  return JSON.stringify({
    count: calendars.length,
    names: names
  });
}
""".strip()


_REMINDERS_PROBE_JXA = r"""
function run() {
  var app = Application("Reminders");
  var lists = app.lists();
  var names = [];
  for (var i = 0; i < lists.length; i++) {
    names.push(String(lists[i].name() || ""));
  }
  return JSON.stringify({
    count: lists.length,
    names: names
  });
}
""".strip()


_MAIL_PROBE_JXA = r"""
function run() {
  var app = Application("Mail");
  var accounts = app.accounts();
  var names = [];
  for (var i = 0; i < accounts.length; i++) {
    names.push(String(accounts[i].name() || ""));
  }
  return JSON.stringify({
    count: accounts.length,
    names: names
  });
}
""".strip()


def _probe_app_automation(
    key: str,
    title: str,
    app_name: str,
    script: str,
    empty_summary: str,
    empty_hint: str,
    tools: list[str],
) -> HealthCheck:
    try:
        result = _run_jxa_json(script, timeout_s=10.0)
    except Exception as exc:
        detail = _clean_detail(str(exc))
        if looks_like_automation_denied(detail):
            return _make_check(
                key,
                title,
                "error",
                f"{app_name} 自动化未授权",
                detail=detail,
                hint=automation_permission_hint(app_name),
                tools=tools,
            )
        if looks_like_timeout(detail):
            return _make_check(
                key,
                title,
                "warning",
                f"{app_name} 检查超时了",
                detail=detail,
                hint=timeout_recovery_hint(),
                tools=tools,
            )
        return _make_check(
            key,
            title,
            "error",
            f"{app_name} 检查失败",
            detail=detail,
            hint=f"确认 `{app_name}` 能正常打开；如果你刚改过权限，{permission_refresh_hint()}",
            tools=tools,
        )

    names = [
        str(name).strip()
        for name in (result.get("names") or [])
        if str(name).strip()
    ]
    count = int(result.get("count", len(names)) or 0)
    detail = _format_names(names, "没有列出具体名称")
    if count <= 0:
        return _make_check(
            key,
            title,
            "warning",
            empty_summary,
            detail=detail,
            hint=empty_hint,
            tools=tools,
        )
    return _make_check(
        key,
        title,
        "ok",
        f"{app_name} 自动化可用",
        detail=f"发现 {count} 项: {detail}",
        tools=tools,
    )


def _format_summary_text(ok_count: int, warning_count: int, error_count: int) -> str:
    return f"已就绪 {ok_count} 项，留意 {warning_count} 项，未就绪 {error_count} 项。"


def collect_permission_health() -> HealthSnapshot:
    raw_checks = [
        _probe_appkit_bridge(),
        _probe_window_bridge(),
        _probe_osascript_runtime(),
        _probe_claude_code_cli(),
        _probe_bundle_runtime(),
        _probe_bundle_tcc_metadata(),
        _probe_bundle_signature_identity(),
        _probe_current_process_accessibility(),
        _probe_system_events_ui(),
        _probe_app_automation(
            "calendar_automation",
            "Calendar 自动化",
            "Calendar",
            _CALENDAR_PROBE_JXA,
            "Calendar 可访问，但还没有任何日历",
            "先在 Calendar.app 里准备至少一个日历，再回来刷新。",
            [
                "list_calendar_events",
                "create_calendar_event",
                "update_calendar_event",
                "delete_calendar_event",
            ],
        ),
        _probe_app_automation(
            "reminders_automation",
            "Reminders 自动化",
            "Reminders",
            _REMINDERS_PROBE_JXA,
            "Reminders 可访问，但还没有任何提醒列表",
            "先在 Reminders.app 里准备至少一个列表，再回来刷新。",
            [
                "list_reminders",
                "create_reminder",
                "update_reminder",
                "delete_reminder",
            ],
        ),
        _probe_app_automation(
            "mail_automation",
            "Mail 自动化",
            "Mail",
            _MAIL_PROBE_JXA,
            "Mail 可访问，但还没有任何邮箱账号",
            "先在 Mail.app 里登录至少一个邮箱账号，再回来刷新。",
            [
                "read_unread_mail_headers",
                "read_mail_message",
                "mark_mail_read",
                "create_mail_draft",
                "send_mail_draft",
            ],
        ),
    ]
    checks = [enrich_permission_health_check(check) for check in raw_checks]

    ok_count = sum(1 for check in checks if check["status"] == "ok")
    warning_count = sum(1 for check in checks if check["status"] == "warning")
    error_count = sum(1 for check in checks if check["status"] == "error")
    return {
        "checked_at": time.time(),
        "ok_count": ok_count,
        "warning_count": warning_count,
        "error_count": error_count,
        "summary_text": _format_summary_text(ok_count, warning_count, error_count),
        "checks": checks,
    }
