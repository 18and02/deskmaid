"""Window and open-target desktop bridge helpers for the maid."""

from __future__ import annotations

from pathlib import Path
import threading
from urllib.parse import urlparse

from maid_tools_shared import (
    _format_error,
    _normalize_calendar_names,
    _normalize_optional_text,
    _normalize_required_text,
    _run_applescript,
)

NSApplicationActivateAllWindows = None
NSApplicationActivateIgnoringOtherApps = None
NSPasteboard = None
NSPasteboardItem = None
NSPasteboardTypeString = None
NSRunningApplication = None
NSWorkspace = None
NSWorkspaceOpenConfiguration = None
NSData = None
NSURL = None

try:
    from AppKit import (
        NSApplicationActivateAllWindows,
        NSApplicationActivateIgnoringOtherApps,
        NSPasteboard,
        NSPasteboardItem,
        NSPasteboardTypeString,
        NSRunningApplication,
        NSWorkspace,
        NSWorkspaceOpenConfiguration,
    )
    from Foundation import NSData, NSURL

    HAVE_APPKIT_BRIDGES = True
    _APPKIT_BRIDGES_ERR = None
except Exception as exc:  # pragma: no cover - import failure is surfaced by tool
    HAVE_APPKIT_BRIDGES = False
    _APPKIT_BRIDGES_ERR = exc

HAVE_OPEN_APP = HAVE_APPKIT_BRIDGES
_OPEN_APP_ERR = _APPKIT_BRIDGES_ERR

CGWindowListCopyWindowInfo = None
kCGNullWindowID = None
kCGWindowAlpha = None
kCGWindowBounds = None
kCGWindowIsOnscreen = None
kCGWindowLayer = None
kCGWindowListExcludeDesktopElements = None
kCGWindowListOptionAll = None
kCGWindowListOptionOnScreenOnly = None
kCGWindowMemoryUsage = None
kCGWindowName = None
kCGWindowNumber = None
kCGWindowOwnerName = None
kCGWindowOwnerPID = None

try:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowAlpha,
        kCGWindowBounds,
        kCGWindowIsOnscreen,
        kCGWindowLayer,
        kCGWindowListExcludeDesktopElements,
        kCGWindowListOptionAll,
        kCGWindowListOptionOnScreenOnly,
        kCGWindowMemoryUsage,
        kCGWindowName,
        kCGWindowNumber,
        kCGWindowOwnerName,
        kCGWindowOwnerPID,
    )

    HAVE_WINDOW_LIST_BRIDGES = True
    _WINDOW_LIST_BRIDGES_ERR = None
except Exception as exc:  # pragma: no cover - import failure is surfaced by tool
    HAVE_WINDOW_LIST_BRIDGES = False
    _WINDOW_LIST_BRIDGES_ERR = exc


DEFAULT_WINDOW_LIST_LIMIT = 60
MAX_WINDOW_LIST_LIMIT = 200


def _require_appkit_bridges(feature: str):
    if not HAVE_APPKIT_BRIDGES:
        raise RuntimeError(f"{feature} unavailable: {_APPKIT_BRIDGES_ERR}")


def _require_window_list_bridges(feature: str):
    if not HAVE_WINDOW_LIST_BRIDGES:
        raise RuntimeError(f"{feature} unavailable: {_WINDOW_LIST_BRIDGES_ERR}")


def _frontmost_app_payload(app=None) -> dict[str, object]:
    _require_appkit_bridges("desktop bridge")
    if app is None:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()

    bundle_id = None
    localized_name = None
    pid = None
    active = None
    if app is not None:
        try:
            bundle_id = app.bundleIdentifier()
        except Exception:
            bundle_id = None
        try:
            localized_name = app.localizedName()
        except Exception:
            localized_name = None
        try:
            pid = int(app.processIdentifier())
        except Exception:
            pid = None
        try:
            active = bool(app.isActive())
        except Exception:
            active = None

    return {
        "localized_name": str(localized_name) if localized_name else None,
        "bundle_id": str(bundle_id) if bundle_id else None,
        "pid": pid,
        "active": active,
    }


def _get_frontmost_app_sync() -> dict[str, object]:
    return _frontmost_app_payload()


def _running_app_payload_for_pid(pid: int | None) -> dict[str, object] | None:
    _require_appkit_bridges("desktop bridge")
    if pid is None:
        return None
    try:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
    except Exception:
        app = None
    if app is None:
        return None
    return _frontmost_app_payload(app)


def _running_app_payload_for_bundle_id(bundle_id: str | None) -> dict[str, object] | None:
    _require_appkit_bridges("desktop bridge")
    target = str(bundle_id or "").strip()
    if not target:
        return None
    try:
        matches = NSRunningApplication.runningApplicationsWithBundleIdentifier_(target) or []
    except Exception:
        matches = []
    if not matches:
        return None
    return _frontmost_app_payload(matches[0])


def _running_app_payload_for_owner_name(owner_name: str | None) -> dict[str, object] | None:
    _require_appkit_bridges("desktop bridge")
    target = str(owner_name or "").strip()
    if not target:
        return None
    try:
        apps = NSWorkspace.sharedWorkspace().runningApplications() or []
    except Exception:
        apps = []
    matches = []
    for app in apps:
        try:
            localized_name = str(app.localizedName() or "").strip()
        except Exception:
            localized_name = ""
        if localized_name == target:
            matches.append(app)
    if not matches:
        return None
    active_matches = []
    for app in matches:
        try:
            if bool(app.isActive()):
                active_matches.append(app)
        except Exception:
            continue
    return _frontmost_app_payload((active_matches or matches)[0])


def _parse_list_windows_args(args: dict[str, object]) -> dict[str, object]:
    safe_limit = int(args.get("limit", DEFAULT_WINDOW_LIST_LIMIT))
    if safe_limit < 1:
        safe_limit = 1
    if safe_limit > MAX_WINDOW_LIST_LIMIT:
        safe_limit = MAX_WINDOW_LIST_LIMIT
    return {
        "owner_names": _normalize_calendar_names(
            args.get("owner_names") or args.get("owners") or args.get("apps")
        ),
        "title_contains": _normalize_optional_text(
            args.get("title_contains") or args.get("title")
        ),
        "on_screen_only": bool(args.get("on_screen_only", True)),
        "include_desktop_elements": bool(args.get("include_desktop_elements", False)),
        "include_nonzero_layer": bool(args.get("include_nonzero_layer", False)),
        "limit": safe_limit,
    }


def _list_windows_sync(
    owner_names: list[str] | None = None,
    title_contains: str | None = None,
    on_screen_only: bool = True,
    include_desktop_elements: bool = False,
    include_nonzero_layer: bool = False,
    limit: int = DEFAULT_WINDOW_LIST_LIMIT,
) -> dict[str, object]:
    _require_window_list_bridges("list_windows")
    frontmost_app = _get_frontmost_app_sync()
    frontmost_pid = int(frontmost_app.get("pid") or 0) or None

    safe_limit = int(limit)
    if safe_limit < 1:
        safe_limit = 1
    if safe_limit > MAX_WINDOW_LIST_LIMIT:
        safe_limit = MAX_WINDOW_LIST_LIMIT

    owner_filters = _normalize_calendar_names(owner_names)
    title_filter = str(title_contains or "").strip().lower()

    options = kCGWindowListOptionOnScreenOnly if on_screen_only else kCGWindowListOptionAll
    if not include_desktop_elements:
        options |= kCGWindowListExcludeDesktopElements

    raw_windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) or []
    windows: list[dict[str, object]] = []
    for raw_item in raw_windows:
        item = dict(raw_item or {})
        owner_name = str(item.get(kCGWindowOwnerName) or "").strip()
        title = str(item.get(kCGWindowName) or "").strip()
        try:
            pid = int(item.get(kCGWindowOwnerPID) or 0) or None
        except (TypeError, ValueError):
            pid = None
        try:
            window_id = int(item.get(kCGWindowNumber) or 0) or None
        except (TypeError, ValueError):
            window_id = None
        try:
            layer = int(item.get(kCGWindowLayer) or 0)
        except (TypeError, ValueError):
            layer = 0
        bounds = dict(item.get(kCGWindowBounds) or {})
        try:
            width = int(bounds.get("Width") or 0)
        except (TypeError, ValueError):
            width = 0
        try:
            height = int(bounds.get("Height") or 0)
        except (TypeError, ValueError):
            height = 0
        if width <= 0 or height <= 0:
            continue
        if owner_filters and owner_name not in owner_filters:
            continue
        if title_filter and title_filter not in title.lower():
            continue
        if not include_nonzero_layer and layer != 0:
            continue

        app_payload = _running_app_payload_for_pid(pid) or {}
        try:
            alpha = float(item.get(kCGWindowAlpha) or 0.0)
        except (TypeError, ValueError):
            alpha = 0.0
        try:
            memory_usage = int(item.get(kCGWindowMemoryUsage) or 0)
        except (TypeError, ValueError):
            memory_usage = 0

        windows.append(
            {
                "window_id": window_id,
                "title": title,
                "owner_name": owner_name or str(app_payload.get("localized_name") or ""),
                "pid": pid,
                "bundle_id": app_payload.get("bundle_id"),
                "layer": layer,
                "alpha": alpha,
                "memory_usage": memory_usage,
                "is_onscreen": bool(item.get(kCGWindowIsOnscreen)),
                "is_frontmost_owner": bool(frontmost_pid is not None and pid == frontmost_pid),
                "bounds": {
                    "x": int(bounds.get("X") or 0),
                    "y": int(bounds.get("Y") or 0),
                    "width": width,
                    "height": height,
                },
            }
        )
        if len(windows) >= safe_limit:
            break

    return {
        "frontmost_app": frontmost_app,
        "owner_filters": owner_filters,
        "title_filter": title_contains,
        "on_screen_only": bool(on_screen_only),
        "include_desktop_elements": bool(include_desktop_elements),
        "include_nonzero_layer": bool(include_nonzero_layer),
        "limit": safe_limit,
        "count": len(windows),
        "windows": windows,
    }


def _normalize_optional_int(value, field_name: str) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _parse_focus_window_args(args: dict[str, object]) -> dict[str, object]:
    title = _normalize_optional_text(args.get("title") or args.get("window_title"))
    title_contains = _normalize_optional_text(args.get("title_contains"))
    if title and title_contains:
        raise ValueError("title and title_contains cannot be used together")

    return {
        "window_id": _normalize_optional_int(
            args.get("window_id") if "window_id" in args else args.get("id"),
            "window_id",
        ),
        "pid": _normalize_optional_int(args.get("pid"), "pid"),
        "bundle_id": _normalize_optional_text(args.get("bundle_id")),
        "owner_name": _normalize_optional_text(
            args.get("owner_name")
            or args.get("app")
            or args.get("app_name")
            or args.get("owner")
        ),
        "title": title,
        "title_contains": title_contains,
    }


def _window_matches_focus_filters(
    window: dict[str, object],
    parsed: dict[str, object],
) -> bool:
    window_id = parsed.get("window_id")
    if window_id is not None and int(window.get("window_id") or 0) != int(window_id):
        return False

    pid = parsed.get("pid")
    if pid is not None and int(window.get("pid") or 0) != int(pid):
        return False

    bundle_id = str(parsed.get("bundle_id") or "").strip()
    if bundle_id and str(window.get("bundle_id") or "").strip() != bundle_id:
        return False

    owner_name = str(parsed.get("owner_name") or "").strip()
    if owner_name and str(window.get("owner_name") or "").strip() != owner_name:
        return False

    title = str(parsed.get("title") or "").strip()
    if title and str(window.get("title") or "").strip() != title:
        return False

    title_contains = str(parsed.get("title_contains") or "").strip().lower()
    if title_contains and title_contains not in str(window.get("title") or "").lower():
        return False

    return True


def _window_specific_focus_request(parsed: dict[str, object]) -> bool:
    return bool(
        parsed.get("window_id") is not None
        or str(parsed.get("title") or "").strip()
        or str(parsed.get("title_contains") or "").strip()
    )


def _focus_window_candidates(parsed: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
    snapshot = _list_windows_sync(
        on_screen_only=False,
        include_desktop_elements=False,
        include_nonzero_layer=True,
        limit=MAX_WINDOW_LIST_LIMIT,
    )
    windows = [
        window
        for window in (snapshot.get("windows") or [])
        if isinstance(window, dict) and _window_matches_focus_filters(window, parsed)
    ]
    return snapshot, windows


def _running_app_payload_for_focus(
    parsed: dict[str, object],
    candidates: list[dict[str, object]] | None = None,
) -> dict[str, object] | None:
    rows = candidates or []
    if rows:
        pid = rows[0].get("pid")
        payload = _running_app_payload_for_pid(int(pid) if pid is not None else None)
        if payload is not None:
            return payload
        bundle_id = str(rows[0].get("bundle_id") or "").strip()
        payload = _running_app_payload_for_bundle_id(bundle_id)
        if payload is not None:
            return payload
        owner_name = str(rows[0].get("owner_name") or "").strip()
        payload = _running_app_payload_for_owner_name(owner_name)
        if payload is not None:
            return payload

    if parsed.get("pid") is not None:
        payload = _running_app_payload_for_pid(int(parsed["pid"]))
        if payload is not None:
            return payload

    bundle_id = str(parsed.get("bundle_id") or "").strip()
    if bundle_id:
        payload = _running_app_payload_for_bundle_id(bundle_id)
        if payload is not None:
            return payload

    owner_name = str(parsed.get("owner_name") or "").strip()
    if owner_name:
        payload = _running_app_payload_for_owner_name(owner_name)
        if payload is not None:
            return payload

    return None


def _resolve_focus_window_target_sync(args: dict[str, object]) -> dict[str, object]:
    parsed = _parse_focus_window_args(args)
    if not any(parsed.values()):
        snapshot = _list_windows_sync(
            on_screen_only=False,
            include_desktop_elements=False,
            include_nonzero_layer=True,
            limit=MAX_WINDOW_LIST_LIMIT,
        )
        frontmost_app = dict(snapshot.get("frontmost_app") or {})
        frontmost_pid = _normalize_optional_int(frontmost_app.get("pid"), "pid")
        preferred_window = None
        if frontmost_pid is not None:
            matches = [
                window
                for window in (snapshot.get("windows") or [])
                if isinstance(window, dict)
                and _normalize_optional_int(window.get("pid"), "pid") == frontmost_pid
            ]
            if matches:
                frontmost_matches = [
                    item for item in matches if bool(item.get("is_frontmost_owner"))
                ]
                preferred_window = dict((frontmost_matches or matches)[0])
        return {
            "mode": "app",
            "selectors": parsed,
            "candidate_count": 0,
            "frontmost_app": snapshot.get("frontmost_app"),
            "app": frontmost_app,
            "window": preferred_window,
        }

    window_specific = _window_specific_focus_request(parsed)
    snapshot, candidates = _focus_window_candidates(parsed)

    if window_specific:
        if not candidates:
            raise LookupError("no visible or known window matched the provided focus filters")
        if len(candidates) > 1:
            labels = []
            for item in candidates[:8]:
                owner_name = str(item.get("owner_name") or "").strip() or "未知应用"
                title = str(item.get("title") or "").strip() or "（无标题）"
                labels.append(f"{owner_name}: {title}")
            extra_count = len(candidates) - 8
            if extra_count > 0:
                labels.append(f"以及另外 {extra_count} 个")
            raise LookupError(
                "multiple windows matched the provided focus filters; narrow it with window_id, pid, or exact title. Matches: "
                + "；".join(labels)
            )
        target_window = dict(candidates[0])
        app_payload = _running_app_payload_for_focus(parsed, candidates)
        if app_payload is None:
            raise LookupError("matched a window, but the owning app is no longer running")
        return {
            "mode": "window",
            "selectors": parsed,
            "candidate_count": len(candidates),
            "frontmost_app": snapshot.get("frontmost_app"),
            "app": app_payload,
            "window": target_window,
        }

    app_payload = _running_app_payload_for_focus(parsed, candidates)
    if app_payload is None:
        raise LookupError("no running app matched the provided focus filters")

    preferred_window = None
    if candidates:
        frontmost_candidates = [
            item for item in candidates if bool(item.get("is_frontmost_owner"))
        ]
        preferred_window = dict((frontmost_candidates or candidates)[0])
    return {
        "mode": "app",
        "selectors": parsed,
        "candidate_count": len(candidates),
        "frontmost_app": snapshot.get("frontmost_app"),
        "app": app_payload,
        "window": preferred_window,
    }


def _normalize_focus_accessibility_error(detail: str) -> str:
    lowered = detail.lower()
    if (
        "不允许辅助访问" in detail
        or "assistive access" in lowered
        or "accessibility" in lowered
    ):
        return (
            "focus_window needs Accessibility permission for System Events / osascript "
            "to raise a specific window"
        )
    return detail


def _raise_window_with_system_events(window: dict[str, object]):
    pid = _normalize_optional_int(window.get("pid"), "pid")
    if pid is None:
        raise ValueError("window is missing pid")

    title = str(window.get("title") or "")
    bounds = dict(window.get("bounds") or {})
    x = int(bounds.get("x") or 0)
    y = int(bounds.get("y") or 0)
    width = int(bounds.get("width") or 0)
    height = int(bounds.get("height") or 0)

    script = """
on run argv
  set targetPid to item 1 of argv as integer
  set targetTitle to item 2 of argv
  set targetX to item 3 of argv as integer
  set targetY to item 4 of argv as integer
  set targetWidth to item 5 of argv as integer
  set targetHeight to item 6 of argv as integer
  tell application "System Events"
    set targetProcess to first application process whose unix id is targetPid
    set frontmost of targetProcess to true
    set targetWindow to missing value
    try
      if targetTitle is not "" then
        set targetWindow to first window of targetProcess whose name is targetTitle and position is {targetX, targetY} and size is {targetWidth, targetHeight}
      else
        set targetWindow to first window of targetProcess whose position is {targetX, targetY} and size is {targetWidth, targetHeight}
      end if
    end try
    if targetWindow is missing value and targetTitle is not "" then
      try
        set targetWindow to first window of targetProcess whose name is targetTitle
      end try
    end if
    if targetWindow is missing value then
      set targetWindow to window 1 of targetProcess
    end if
    perform action "AXRaise" of targetWindow
  end tell
  return "ok"
end run
""".strip()
    try:
        _run_applescript(
            script,
            args=[
                str(pid),
                title,
                str(x),
                str(y),
                str(width),
                str(height),
            ],
            timeout_s=20.0,
        )
    except RuntimeError as exc:
        raise RuntimeError(_normalize_focus_accessibility_error(str(exc))) from exc


def _focus_window_sync(args: dict[str, object]) -> dict[str, object]:
    _require_appkit_bridges("focus_window")
    resolved = _resolve_focus_window_target_sync(args)
    app_payload = dict(resolved.get("app") or {})
    pid = _normalize_optional_int(app_payload.get("pid"), "pid")
    if pid is None:
        raise LookupError("resolved app is missing pid")

    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
    if app is None:
        raise LookupError("the target app is no longer running")

    activate_options = (
        int(NSApplicationActivateAllWindows)
        | int(NSApplicationActivateIgnoringOtherApps)
    )
    activated = bool(app.activateWithOptions_(activate_options))
    if not activated:
        raise RuntimeError("failed to activate the target app")

    window_payload = dict(resolved.get("window") or {})
    window_raised = None
    if str(resolved.get("mode") or "") == "window":
        _raise_window_with_system_events(window_payload)
        window_raised = True

    owner_name = str(
        window_payload.get("owner_name")
        or app_payload.get("localized_name")
        or ""
    ).strip() or None
    title = str(window_payload.get("title") or "").strip() or None
    window_id = _normalize_optional_int(window_payload.get("window_id"), "window_id")

    return {
        "ok": True,
        "status": "focused",
        "message": "focus_window succeeded; window_id alone is sufficient when it uniquely identifies the target window.",
        "mode": resolved.get("mode"),
        "window_id": window_id,
        "owner_name": owner_name,
        "title": title,
        "bundle_id": app_payload.get("bundle_id"),
        "activated": activated,
        "window_raised": window_raised,
        "app": app_payload,
        "window": window_payload if window_payload else None,
    }


def _looks_like_host_with_port(value: str) -> bool:
    if "://" in value:
        return False
    host, sep, port = value.partition(":")
    if not sep or not port.isdigit():
        return False
    host = host.strip().lower()
    return bool(host) and (
        host == "localhost"
        or host.startswith("127.")
        or host.startswith("[::1]")
        or "." in host
    )


def _resolve_url_target(target: str):
    _require_appkit_bridges("open_url")

    value = _normalize_required_text(target, "target")
    expanded = Path(value).expanduser()
    if expanded.exists():
        resolved_path = str(expanded.resolve())
        url = NSURL.fileURLWithPath_(resolved_path)
        return url, "path", str(url.absoluteString())

    if value.startswith("/") or value.startswith("~"):
        raise FileNotFoundError(f"local path not found: {expanded}")

    if _looks_like_host_with_port(value):
        candidate = f"http://{value}"
        matched_by = "host_port"
    elif "://" in value:
        candidate = value
        matched_by = "url"
    else:
        parsed = urlparse(value)
        if parsed.scheme:
            candidate = value
            matched_by = "url"
        elif " " in value:
            raise ValueError("target must be a URL or existing local path")
        elif value.lower().startswith(("localhost", "127.", "[::1]")):
            candidate = f"http://{value}"
            matched_by = "host"
        elif "." in value:
            candidate = f"https://{value}"
            matched_by = "bare_host"
        else:
            raise ValueError("target must include a scheme like https:// or be an existing local path")

    url = NSURL.URLWithString_(candidate)
    if url is None:
        raise ValueError(f"invalid URL target: {target!r}")
    absolute = url.absoluteString()
    resolved_url = str(absolute) if absolute else candidate
    return url, matched_by, resolved_url


def _open_url_sync(
    target: str,
    activate: bool = True,
) -> dict[str, object]:
    url, matched_by, resolved_url = _resolve_url_target(target)

    config = NSWorkspaceOpenConfiguration.configuration()
    config.setActivates_(bool(activate))

    done = threading.Event()
    outcome: dict[str, object] = {}

    def handler(app, err):
        outcome["app"] = app
        outcome["err"] = err
        done.set()

    workspace = NSWorkspace.sharedWorkspace()
    workspace.openURL_configuration_completionHandler_(
        url,
        config,
        handler,
    )

    if not done.wait(timeout=10.0):
        raise TimeoutError(f"timed out while opening {target!r}")

    err = outcome.get("err")
    if err is not None:
        raise RuntimeError(_format_error(err))

    opened_with = _frontmost_app_payload(outcome.get("app")) if outcome.get("app") is not None else None
    return {
        "target": target,
        "matched_by": matched_by,
        "resolved_url": resolved_url,
        "activate": bool(activate),
        "opened_with": opened_with,
    }


def _url_path(url) -> str | None:
    if url is None:
        return None
    try:
        path = url.path()
    except Exception:
        path = None
    if not path:
        return None
    return str(path)


def _resolve_app_target(target: str):
    if not HAVE_OPEN_APP:
        raise RuntimeError(f"open_app unavailable: {_OPEN_APP_ERR}")

    value = target.strip()
    if not value:
        raise ValueError("target is empty")

    workspace = NSWorkspace.sharedWorkspace()

    expanded = Path(value).expanduser()
    if expanded.exists():
        resolved = expanded.resolve()
        if resolved.suffix.lower() != ".app":
            raise ValueError(f"target path is not an .app bundle: {resolved}")
        return NSURL.fileURLWithPath_(str(resolved)), "path", str(resolved)

    if "/" in value or value.startswith("~"):
        raise FileNotFoundError(f"app bundle not found at {expanded}")

    bundle_url = workspace.URLForApplicationWithBundleIdentifier_(value)
    bundle_path = _url_path(bundle_url)
    if bundle_url is not None and bundle_path:
        return bundle_url, "bundle_id", bundle_path

    names = [value]
    if value.lower().endswith(".app"):
        names.append(value[:-4])
    seen = set()
    for name in names:
        candidate = name.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        path = workspace.fullPathForApplication_(candidate)
        if path:
            resolved_path = str(Path(str(path)).resolve())
            return NSURL.fileURLWithPath_(resolved_path), "name", resolved_path

    raise LookupError(f"could not find macOS app {value!r}")


def _open_app_sync(
    target: str,
    activate: bool = True,
    new_instance: bool = False,
) -> dict[str, object]:
    url, matched_by, resolved_path = _resolve_app_target(target)

    config = NSWorkspaceOpenConfiguration.configuration()
    config.setActivates_(bool(activate))
    config.setCreatesNewApplicationInstance_(bool(new_instance))

    done = threading.Event()
    outcome: dict[str, object] = {}

    def handler(app, err):
        outcome["app"] = app
        outcome["err"] = err
        done.set()

    workspace = NSWorkspace.sharedWorkspace()
    workspace.openApplicationAtURL_configuration_completionHandler_(
        url,
        config,
        handler,
    )

    if not done.wait(timeout=10.0):
        raise TimeoutError(f"timed out while opening {target!r}")

    err = outcome.get("err")
    if err is not None:
        raise RuntimeError(_format_error(err))

    app = outcome.get("app")
    bundle_id = None
    localized_name = None
    pid = None
    if app is not None:
        try:
            bundle_id = app.bundleIdentifier()
        except Exception:
            bundle_id = None
        try:
            localized_name = app.localizedName()
        except Exception:
            localized_name = None
        try:
            pid = int(app.processIdentifier())
        except Exception:
            pid = None

    return {
        "target": target,
        "matched_by": matched_by,
        "resolved_path": resolved_path,
        "localized_name": str(localized_name) if localized_name else None,
        "bundle_id": str(bundle_id) if bundle_id else None,
        "pid": pid,
        "activate": bool(activate),
        "new_instance": bool(new_instance),
    }
