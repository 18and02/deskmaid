"""Automatic do-not-disturb scene detection for the desktop maid."""

from __future__ import annotations

from dataclasses import dataclass, field
import time

from maid_tools_desktop_window_open import _list_windows_sync

try:
    from Intents import (
        INFocusStatusAuthorizationStatusAuthorized,
        INFocusStatusAuthorizationStatusDenied,
        INFocusStatusAuthorizationStatusNotDetermined,
        INFocusStatusAuthorizationStatusRestricted,
        INFocusStatusCenter,
    )

    HAVE_SYSTEM_FOCUS = True
    _SYSTEM_FOCUS_ERR = None
except Exception as exc:  # pragma: no cover - surfaced by runtime probe
    HAVE_SYSTEM_FOCUS = False
    _SYSTEM_FOCUS_ERR = exc
    INFocusStatusCenter = None
    INFocusStatusAuthorizationStatusNotDetermined = 0
    INFocusStatusAuthorizationStatusRestricted = 1
    INFocusStatusAuthorizationStatusDenied = 2
    INFocusStatusAuthorizationStatusAuthorized = 3

try:
    from AppKit import NSScreen

    HAVE_NSSCREEN = True
    _NSSCREEN_ERR = None
except Exception as exc:  # pragma: no cover - surfaced by runtime probe
    HAVE_NSSCREEN = False
    _NSSCREEN_ERR = exc
    NSScreen = None


_MEETING_APP_BUNDLE_IDS = {
    "com.apple.facetime",
    "com.cisco.webexmeetingsapp",
    "com.hnc.discord",
    "com.larksuite.lark",
    "com.microsoft.teams",
    "com.microsoft.teams2",
    "com.tencent.meeting",
    "us.zoom.xos",
}
_MEETING_APP_NAME_KEYWORDS = (
    "discord",
    "facetime",
    "lark",
    "meeting",
    "teams",
    "webex",
    "zoom",
    "会议",
    "腾讯会议",
    "飞书",
)
_MEETING_TITLE_KEYWORDS = (
    "google meet",
    "meet.google.com",
    "slack huddle",
    "teams.microsoft.com",
    "webex meeting",
    "zoom meeting",
    "腾讯会议",
    "飞书会议",
)
_PRESENTATION_APP_BUNDLE_IDS = {
    "com.apple.keynote",
    "com.apple.quicktimeplayerx",
    "com.apple.screensharing",
    "com.microsoft.powerpoint",
    "com.obsproject.obs-studio",
}
_PRESENTATION_APP_NAME_KEYWORDS = (
    "keynote",
    "loom",
    "obs",
    "powerpoint",
    "quicktime",
    "screen sharing",
    "screen studio",
    "screenflow",
    "演示",
    "录屏",
)
_SCREEN_SHARE_KEYWORDS = (
    "presenting",
    "presenting to everyone",
    "sharing screen",
    "sharing this tab",
    "sharing this window",
    "screen sharing",
    "share screen",
    "you are screen sharing",
    "you're presenting",
    "共享此标签页",
    "共享此窗口",
    "共享屏幕",
    "正在演示",
    "正在共享",
)
_SCREEN_SHARE_OVERLAY_KEYWORDS = (
    "presenting to everyone",
    "sharing this tab",
    "sharing this window",
    "you are screen sharing",
    "you're presenting",
    "共享此标签页",
    "共享此窗口",
    "共享屏幕",
    "正在演示",
    "正在共享",
)
_RECORDING_KEYWORDS = (
    "screen recording",
    "recording this screen",
    "screenflow",
    "录屏",
    "屏幕录制",
    "正在录制",
)
_RECORDING_OVERLAY_KEYWORDS = (
    "recording this screen",
    "录屏",
    "屏幕录制",
    "正在录制",
)
_FULLSCREEN_AREA_RATIO = 0.93
_FULLSCREEN_WIDTH_RATIO = 0.95
_FULLSCREEN_HEIGHT_RATIO = 0.94
_MEETING_AREA_RATIO = 0.55
_MEETING_WIDTH_RATIO = 0.68
_MEETING_HEIGHT_RATIO = 0.58
_PRESENTATION_AREA_RATIO = 0.72
_PRESENTATION_WIDTH_RATIO = 0.82
_PRESENTATION_HEIGHT_RATIO = 0.76
_SIGNAL_WINDOW_AREA_RATIO = 0.02
_SIGNAL_WINDOW_WIDTH_RATIO = 0.18
_SIGNAL_WINDOW_HEIGHT_RATIO = 0.10

_AUTO_DND_PRIORITY_SCREEN_SHARE = 100
_AUTO_DND_PRIORITY_SYSTEM_FOCUS = 90
_AUTO_DND_PRIORITY_PRESENTATION = 80
_AUTO_DND_PRIORITY_MEETING = 70
_AUTO_DND_PRIORITY_FULLSCREEN = 60

_FOCUS_AUTHORIZATION_LABELS = {
    INFocusStatusAuthorizationStatusNotDetermined: "not_determined",
    INFocusStatusAuthorizationStatusRestricted: "restricted",
    INFocusStatusAuthorizationStatusDenied: "denied",
    INFocusStatusAuthorizationStatusAuthorized: "authorized",
}


@dataclass(frozen=True)
class AutoDoNotDisturbState:
    active: bool = False
    reason_key: str = ""
    reason_text: str = ""
    detail: str = ""
    frontmost_app_name: str = ""
    frontmost_bundle_id: str = ""
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class _AutoDoNotDisturbCandidate:
    priority: int
    reason_key: str
    reason_text: str
    detail: str = ""


def _normalize_text(value) -> str:
    return str(value or "").strip()


def _focus_authorization_label(status_code: int) -> str:
    return _FOCUS_AUTHORIZATION_LABELS.get(status_code, f"unknown:{status_code}")


def _probe_focus_status() -> dict[str, object]:
    if not HAVE_SYSTEM_FOCUS or INFocusStatusCenter is None:
        return {
            "available": False,
            "authorization_status": "unavailable",
            "authorized": False,
            "is_focused": False,
        }

    try:
        center = INFocusStatusCenter.defaultCenter()
    except Exception:
        return {
            "available": False,
            "authorization_status": "unavailable",
            "authorized": False,
            "is_focused": False,
        }

    try:
        authorization_status_code = int(center.authorizationStatus())
    except Exception:
        authorization_status_code = INFocusStatusAuthorizationStatusNotDetermined

    authorization_status = _focus_authorization_label(authorization_status_code)
    is_authorized = authorization_status_code == INFocusStatusAuthorizationStatusAuthorized
    is_focused = False
    if is_authorized:
        try:
            focus_status = center.focusStatus()
        except Exception:
            focus_status = None
        if focus_status is not None:
            try:
                is_focused = bool(focus_status.isFocused())
            except Exception:
                is_focused = False

    return {
        "available": True,
        "authorization_status": authorization_status,
        "authorized": is_authorized,
        "is_focused": is_focused,
    }


def _rect_area(bounds: dict[str, object]) -> int:
    width = max(0, int(bounds.get("width") or 0))
    height = max(0, int(bounds.get("height") or 0))
    return width * height


def _rect_intersection_area(a: dict[str, object], b: dict[str, object]) -> int:
    ax1 = int(a.get("x") or 0)
    ay1 = int(a.get("y") or 0)
    ax2 = ax1 + max(0, int(a.get("width") or 0))
    ay2 = ay1 + max(0, int(a.get("height") or 0))

    bx1 = int(b.get("x") or 0)
    by1 = int(b.get("y") or 0)
    bx2 = bx1 + max(0, int(b.get("width") or 0))
    by2 = by1 + max(0, int(b.get("height") or 0))

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0
    return (ix2 - ix1) * (iy2 - iy1)


def _coverage_ratios(
    window_bounds: dict[str, object],
    screen_bounds: dict[str, object],
) -> dict[str, float]:
    screen_width = max(1, int(screen_bounds.get("width") or 0))
    screen_height = max(1, int(screen_bounds.get("height") or 0))
    screen_area = max(1, _rect_area(screen_bounds))
    intersection_area = _rect_intersection_area(window_bounds, screen_bounds)
    return {
        "width_ratio": max(0.0, float(window_bounds.get("width") or 0) / float(screen_width)),
        "height_ratio": max(0.0, float(window_bounds.get("height") or 0) / float(screen_height)),
        "area_ratio": max(0.0, float(intersection_area) / float(screen_area)),
    }


def _all_screen_bounds() -> list[dict[str, int]]:
    if not HAVE_NSSCREEN:
        return []
    try:
        screens = NSScreen.screens() or []
    except Exception:
        return []

    bounds_list: list[dict[str, int]] = []
    for screen in screens:
        try:
            frame = screen.frame()
        except Exception:
            continue
        bounds_list.append(
            {
                "x": int(frame.origin.x),
                "y": int(frame.origin.y),
                "width": int(frame.size.width),
                "height": int(frame.size.height),
            }
        )
    return bounds_list


def _best_screen_bounds_for_window(
    window_bounds: dict[str, object],
    screen_bounds_list: list[dict[str, int]],
) -> dict[str, int]:
    if not screen_bounds_list:
        return {
            "x": 0,
            "y": 0,
            "width": max(1, int(window_bounds.get("width") or 0)),
            "height": max(1, int(window_bounds.get("height") or 0)),
        }

    best = screen_bounds_list[0]
    best_area = -1
    for candidate in screen_bounds_list:
        overlap = _rect_intersection_area(window_bounds, candidate)
        if overlap > best_area:
            best = candidate
            best_area = overlap
    return best


def _select_frontmost_window(snapshot: dict[str, object]) -> dict[str, object] | None:
    frontmost_app = dict(snapshot.get("frontmost_app") or {})
    frontmost_pid = int(frontmost_app.get("pid") or 0) or None
    windows = _window_rows(snapshot)
    if not windows:
        return None

    candidates = []
    for window in windows:
        pid = int(window.get("pid") or 0) or None
        if frontmost_pid is not None and pid == frontmost_pid:
            candidates.append(window)
            continue
        if bool(window.get("is_frontmost_owner")):
            candidates.append(window)

    if not candidates:
        return None

    def rank(window: dict[str, object]) -> tuple[int, int, int]:
        bounds = dict(window.get("bounds") or {})
        return (
            1 if bool(window.get("is_onscreen")) else 0,
            1 if int(window.get("layer") or 0) == 0 else 0,
            _rect_area(bounds),
        )

    return max(candidates, key=rank)


def _window_rows(snapshot: dict[str, object]) -> list[dict[str, object]]:
    return [
        dict(window or {})
        for window in (snapshot.get("windows") or [])
        if isinstance(window, dict)
    ]


def _matches_any_keyword(value: str, keywords: tuple[str, ...]) -> bool:
    normalized = _normalize_text(value).lower()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in keywords)


def _is_meeting_or_share_app(app_name: str, bundle_id: str, title: str = "") -> bool:
    normalized_bundle = _normalize_text(bundle_id).lower()
    if normalized_bundle in _MEETING_APP_BUNDLE_IDS:
        return True
    return _matches_any_keyword(app_name, _MEETING_APP_NAME_KEYWORDS) or _matches_any_keyword(
        title,
        _MEETING_TITLE_KEYWORDS,
    )


def _is_presentation_or_recording_app(app_name: str, bundle_id: str) -> bool:
    normalized_bundle = _normalize_text(bundle_id).lower()
    if normalized_bundle in _PRESENTATION_APP_BUNDLE_IDS:
        return True
    return _matches_any_keyword(app_name, _PRESENTATION_APP_NAME_KEYWORDS)


def _window_has_signal_coverage(coverage: dict[str, float]) -> bool:
    return bool(
        coverage["area_ratio"] >= _SIGNAL_WINDOW_AREA_RATIO
        or coverage["width_ratio"] >= _SIGNAL_WINDOW_WIDTH_RATIO
        or coverage["height_ratio"] >= _SIGNAL_WINDOW_HEIGHT_RATIO
    )


def _window_context(
    window: dict[str, object],
    screen_bounds_list: list[dict[str, int]],
) -> dict[str, object]:
    owner_name = _normalize_text(window.get("owner_name"))
    bundle_id = _normalize_text(window.get("bundle_id"))
    title = _normalize_text(window.get("title"))
    bounds = dict(window.get("bounds") or {})
    screen_bounds = _best_screen_bounds_for_window(bounds, screen_bounds_list)
    coverage = _coverage_ratios(bounds, screen_bounds)
    return {
        "window": window,
        "owner_name": owner_name,
        "bundle_id": bundle_id,
        "title": title,
        "coverage": coverage,
    }


def _format_signal_detail(
    owner_name: str,
    title: str,
    coverage: dict[str, float],
) -> str:
    detail = owner_name or "窗口"
    if title:
        detail += f": {title}"
    if _window_has_signal_coverage(coverage):
        detail += f" ({coverage['area_ratio']:.0%} screen)"
    return detail


def _collect_high_signal_window_candidates(
    windows: list[dict[str, object]],
    screen_bounds_list: list[dict[str, int]],
) -> list[_AutoDoNotDisturbCandidate]:
    candidates: list[_AutoDoNotDisturbCandidate] = []
    for window in windows:
        if not bool(window.get("is_onscreen", True)):
            continue

        context = _window_context(window, screen_bounds_list)
        owner_name = str(context["owner_name"] or "")
        bundle_id = str(context["bundle_id"] or "")
        title = str(context["title"] or "")
        coverage = dict(context["coverage"] or {})
        signal_coverage = _window_has_signal_coverage(coverage)

        is_explicit_share_overlay = _matches_any_keyword(title, _SCREEN_SHARE_OVERLAY_KEYWORDS)
        is_share_title = is_explicit_share_overlay or (
            _matches_any_keyword(title, _SCREEN_SHARE_KEYWORDS)
            and (
                _is_meeting_or_share_app(owner_name, bundle_id, title)
                or signal_coverage
            )
        )
        if is_share_title:
            candidates.append(
                _AutoDoNotDisturbCandidate(
                    priority=_AUTO_DND_PRIORITY_SCREEN_SHARE + int(coverage["area_ratio"] * 10),
                    reason_key="screen_share",
                    reason_text="共享/演示场景",
                    detail=_format_signal_detail(owner_name, title, coverage),
                )
            )
            continue

        if _is_presentation_or_recording_app(owner_name, bundle_id) and (
            _matches_any_keyword(title, _RECORDING_OVERLAY_KEYWORDS)
            or (
                _matches_any_keyword(title, _RECORDING_KEYWORDS)
                and signal_coverage
            )
            or coverage["area_ratio"] >= _PRESENTATION_AREA_RATIO
            or (
                coverage["width_ratio"] >= _PRESENTATION_WIDTH_RATIO
                and coverage["height_ratio"] >= _PRESENTATION_HEIGHT_RATIO
            )
        ):
            candidates.append(
                _AutoDoNotDisturbCandidate(
                    priority=_AUTO_DND_PRIORITY_PRESENTATION + int(coverage["area_ratio"] * 10),
                    reason_key="presentation_focus",
                    reason_text="演示/录屏场景",
                    detail=_format_signal_detail(owner_name, title, coverage),
                )
            )
    return candidates


def _make_state(
    candidate: _AutoDoNotDisturbCandidate,
    *,
    frontmost_app_name: str,
    frontmost_bundle_id: str,
    updated_at: float,
) -> AutoDoNotDisturbState:
    return AutoDoNotDisturbState(
        active=True,
        reason_key=candidate.reason_key,
        reason_text=candidate.reason_text,
        detail=candidate.detail,
        frontmost_app_name=frontmost_app_name,
        frontmost_bundle_id=frontmost_bundle_id,
        updated_at=updated_at,
    )


def evaluate_auto_do_not_disturb(
    snapshot: dict[str, object],
    *,
    screen_bounds_list: list[dict[str, int]] | None = None,
    focus_status: dict[str, object] | None = None,
    now: float | None = None,
) -> AutoDoNotDisturbState:
    updated_at = now or time.time()
    frontmost_app = dict(snapshot.get("frontmost_app") or {})
    frontmost_name = _normalize_text(frontmost_app.get("localized_name"))
    frontmost_bundle_id = _normalize_text(frontmost_app.get("bundle_id"))
    candidates: list[_AutoDoNotDisturbCandidate] = []
    target_screens = screen_bounds_list if screen_bounds_list is not None else _all_screen_bounds()
    windows = _window_rows(snapshot)
    normalized_focus_status = dict(focus_status or _probe_focus_status())
    if bool(normalized_focus_status.get("is_focused")):
        candidates.append(
            _AutoDoNotDisturbCandidate(
                priority=_AUTO_DND_PRIORITY_SYSTEM_FOCUS,
                reason_key="system_focus",
                reason_text="系统专注模式",
                detail="系统 Focus 当前处于开启状态。",
            )
        )
    candidates.extend(_collect_high_signal_window_candidates(windows, target_screens))

    window = _select_frontmost_window(snapshot)
    if window is None:
        if candidates:
            best_candidate = max(candidates, key=lambda item: item.priority)
            return _make_state(
                best_candidate,
                frontmost_app_name=frontmost_name,
                frontmost_bundle_id=frontmost_bundle_id,
                updated_at=updated_at,
            )
        return AutoDoNotDisturbState(
            active=False,
            frontmost_app_name=frontmost_name,
            frontmost_bundle_id=frontmost_bundle_id,
            updated_at=updated_at,
        )

    owner_name = _normalize_text(window.get("owner_name")) or frontmost_name
    bundle_id = _normalize_text(window.get("bundle_id")) or frontmost_bundle_id
    title = _normalize_text(window.get("title"))
    bounds = dict(window.get("bounds") or {})
    screen_bounds = _best_screen_bounds_for_window(bounds, target_screens)
    coverage = _coverage_ratios(bounds, screen_bounds)
    effective_app_name = owner_name or frontmost_name
    effective_bundle_id = bundle_id or frontmost_bundle_id

    if _matches_any_keyword(title, _SCREEN_SHARE_OVERLAY_KEYWORDS) or (
        _matches_any_keyword(title, _SCREEN_SHARE_KEYWORDS)
        and (
            _is_meeting_or_share_app(owner_name, bundle_id, title)
            or _window_has_signal_coverage(coverage)
        )
    ):
        detail = f"{owner_name}: {title or '共享状态'}"
        candidates.append(
            _AutoDoNotDisturbCandidate(
                priority=_AUTO_DND_PRIORITY_SCREEN_SHARE,
                reason_key="screen_share",
                reason_text="共享/演示场景",
                detail=detail,
            )
        )

    if _is_presentation_or_recording_app(owner_name, bundle_id) and (
        _matches_any_keyword(title, _RECORDING_KEYWORDS)
        or coverage["area_ratio"] >= _PRESENTATION_AREA_RATIO
        or (
            coverage["width_ratio"] >= _PRESENTATION_WIDTH_RATIO
            and coverage["height_ratio"] >= _PRESENTATION_HEIGHT_RATIO
        )
    ):
        detail = (
            f"{owner_name}"
            + (f": {title}" if title else "")
            + f" ({coverage['area_ratio']:.0%} screen)"
        )
        candidates.append(
            _AutoDoNotDisturbCandidate(
                priority=_AUTO_DND_PRIORITY_PRESENTATION,
                reason_key="presentation_focus",
                reason_text="演示/录屏场景",
                detail=detail,
            )
        )

    if _is_meeting_or_share_app(owner_name, bundle_id, title) and (
        coverage["area_ratio"] >= _MEETING_AREA_RATIO
        or coverage["width_ratio"] >= _MEETING_WIDTH_RATIO
        or coverage["height_ratio"] >= _MEETING_HEIGHT_RATIO
    ):
        detail = (
            f"{owner_name}"
            + (f": {title}" if title else "")
            + f" ({coverage['area_ratio']:.0%} screen)"
        )
        candidates.append(
            _AutoDoNotDisturbCandidate(
                priority=_AUTO_DND_PRIORITY_MEETING,
                reason_key="meeting_focus",
                reason_text="会议/通话场景",
                detail=detail,
            )
        )

    if (
        coverage["area_ratio"] >= _FULLSCREEN_AREA_RATIO
        or (
            coverage["width_ratio"] >= _FULLSCREEN_WIDTH_RATIO
            and coverage["height_ratio"] >= _FULLSCREEN_HEIGHT_RATIO
        )
    ):
        detail = (
            f"{owner_name}"
            + (f": {title}" if title else "")
            + f" ({coverage['width_ratio']:.0%} x {coverage['height_ratio']:.0%})"
        )
        candidates.append(
            _AutoDoNotDisturbCandidate(
                priority=_AUTO_DND_PRIORITY_FULLSCREEN,
                reason_key="frontmost_fullscreen",
                reason_text="前台全屏场景",
                detail=detail,
            )
        )

    if candidates:
        best_candidate = max(candidates, key=lambda item: item.priority)
        return _make_state(
            best_candidate,
            frontmost_app_name=effective_app_name,
            frontmost_bundle_id=effective_bundle_id,
            updated_at=updated_at,
        )

    return AutoDoNotDisturbState(
        active=False,
        frontmost_app_name=effective_app_name,
        frontmost_bundle_id=effective_bundle_id,
        updated_at=updated_at,
    )


def probe_auto_do_not_disturb() -> AutoDoNotDisturbState:
    snapshot = _list_windows_sync(
        on_screen_only=False,
        include_desktop_elements=False,
        include_nonzero_layer=True,
        limit=80,
    )
    return evaluate_auto_do_not_disturb(
        snapshot,
        focus_status=_probe_focus_status(),
    )
