"""Unit-style smoke tests for automatic do-not-disturb scene detection.

Usage:
    .venv/bin/python -u Maid/test_auto_do_not_disturb.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_auto_dnd import evaluate_auto_do_not_disturb


SCREEN = [
    {
        "x": 0,
        "y": 0,
        "width": 1512,
        "height": 982,
    }
]


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _snapshot(
    *,
    app_name: str,
    bundle_id: str,
    title: str,
    width: int,
    height: int,
    extra_windows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    windows = [
        {
            "window_id": 77,
            "title": title,
            "owner_name": app_name,
            "pid": 1234,
            "bundle_id": bundle_id,
            "layer": 0,
            "alpha": 1.0,
            "memory_usage": 0,
            "is_onscreen": True,
            "is_frontmost_owner": True,
            "bounds": {
                "x": 0,
                "y": 0,
                "width": width,
                "height": height,
            },
        }
    ]
    if extra_windows:
        windows.extend(extra_windows)
    return {
        "frontmost_app": {
            "localized_name": app_name,
            "bundle_id": bundle_id,
            "pid": 1234,
            "active": True,
        },
        "windows": windows,
    }


def main():
    fullscreen = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="Safari",
            bundle_id="com.apple.Safari",
            title="Video",
            width=1512,
            height=982,
        ),
        screen_bounds_list=SCREEN,
    )
    _assert(fullscreen.active, "expected fullscreen scene to enable auto DND")
    _assert(
        fullscreen.reason_key == "frontmost_fullscreen",
        f"unexpected fullscreen reason: {fullscreen!r}",
    )

    meeting = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="Zoom",
            bundle_id="us.zoom.xos",
            title="Daily Sync",
            width=1100,
            height=760,
        ),
        screen_bounds_list=SCREEN,
    )
    _assert(meeting.active, "expected meeting scene to enable auto DND")
    _assert(
        meeting.reason_key == "meeting_focus",
        f"unexpected meeting reason: {meeting!r}",
    )

    screen_share = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="Google Chrome",
            bundle_id="com.google.Chrome",
            title="Weekly review - sharing screen",
            width=960,
            height=720,
        ),
        screen_bounds_list=SCREEN,
    )
    _assert(screen_share.active, "expected screen-share title to enable auto DND")
    _assert(
        screen_share.reason_key == "screen_share",
        f"unexpected share reason: {screen_share!r}",
    )

    browser_meeting = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="Google Chrome",
            bundle_id="com.google.Chrome",
            title="Daily sync - Google Meet",
            width=1260,
            height=780,
        ),
        screen_bounds_list=SCREEN,
    )
    _assert(browser_meeting.active, "expected browser meeting title to enable auto DND")
    _assert(
        browser_meeting.reason_key == "meeting_focus",
        f"unexpected browser meeting reason: {browser_meeting!r}",
    )

    focus_mode = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            title="Notes",
            width=960,
            height=620,
        ),
        screen_bounds_list=SCREEN,
        focus_status={
            "available": True,
            "authorization_status": "authorized",
            "authorized": True,
            "is_focused": True,
        },
    )
    _assert(focus_mode.active, "expected system focus to enable auto DND")
    _assert(
        focus_mode.reason_key == "system_focus",
        f"unexpected focus-mode reason: {focus_mode!r}",
    )

    share_beats_focus = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="Google Chrome",
            bundle_id="com.google.Chrome",
            title="Weekly review - sharing screen",
            width=960,
            height=720,
        ),
        screen_bounds_list=SCREEN,
        focus_status={
            "available": True,
            "authorization_status": "authorized",
            "authorized": True,
            "is_focused": True,
        },
    )
    _assert(share_beats_focus.active, "expected active auto DND when share + focus coexist")
    _assert(
        share_beats_focus.reason_key == "screen_share",
        f"expected explicit share to outrank focus: {share_beats_focus!r}",
    )

    global_share = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            title="Notes",
            width=960,
            height=620,
            extra_windows=[
                {
                    "window_id": 91,
                    "title": "Weekly review - you are screen sharing",
                    "owner_name": "Google Chrome",
                    "pid": 2222,
                    "bundle_id": "com.google.Chrome",
                    "layer": 0,
                    "alpha": 1.0,
                    "memory_usage": 0,
                    "is_onscreen": True,
                    "is_frontmost_owner": False,
                    "bounds": {
                        "x": 0,
                        "y": 0,
                        "width": 640,
                        "height": 96,
                    },
                }
            ],
        ),
        screen_bounds_list=SCREEN,
    )
    _assert(global_share.active, "expected global share overlay to enable auto DND")
    _assert(
        global_share.reason_key == "screen_share",
        f"unexpected global share reason: {global_share!r}",
    )

    global_recording = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            title="Notes",
            width=960,
            height=620,
            extra_windows=[
                {
                    "window_id": 92,
                    "title": "Screen Recording",
                    "owner_name": "QuickTime Player",
                    "pid": 3333,
                    "bundle_id": "com.apple.quicktimeplayerx",
                    "layer": 0,
                    "alpha": 1.0,
                    "memory_usage": 0,
                    "is_onscreen": True,
                    "is_frontmost_owner": False,
                    "bounds": {
                        "x": 0,
                        "y": 0,
                        "width": 720,
                        "height": 240,
                    },
                }
            ],
        ),
        screen_bounds_list=SCREEN,
    )
    _assert(global_recording.active, "expected background recording window to enable auto DND")
    _assert(
        global_recording.reason_key == "presentation_focus",
        f"unexpected background recording reason: {global_recording!r}",
    )

    background_meeting_only = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            title="Notes",
            width=960,
            height=620,
            extra_windows=[
                {
                    "window_id": 93,
                    "title": "Daily Sync",
                    "owner_name": "Zoom",
                    "pid": 4444,
                    "bundle_id": "us.zoom.xos",
                    "layer": 0,
                    "alpha": 1.0,
                    "memory_usage": 0,
                    "is_onscreen": True,
                    "is_frontmost_owner": False,
                    "bounds": {
                        "x": 0,
                        "y": 0,
                        "width": 1100,
                        "height": 760,
                    },
                }
            ],
        ),
        screen_bounds_list=SCREEN,
    )
    _assert(
        not background_meeting_only.active,
        f"background meeting alone should not trigger auto DND: {background_meeting_only!r}",
    )

    camera_active = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            title="Notes",
            width=960,
            height=620,
        ),
        screen_bounds_list=SCREEN,
        camera_status={
            "available": True,
            "active": True,
            "device_count": 1,
            "active_device_names": ["FaceTime HD Camera"],
        },
    )
    _assert(camera_active.active, "expected camera in use to enable auto DND")
    _assert(
        camera_active.reason_key == "camera_active",
        f"unexpected camera reason: {camera_active!r}",
    )
    _assert(
        "FaceTime HD Camera" in camera_active.detail,
        f"expected camera device name in detail: {camera_active!r}",
    )

    camera_beats_focus = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            title="Notes",
            width=960,
            height=620,
        ),
        screen_bounds_list=SCREEN,
        focus_status={
            "available": True,
            "authorization_status": "authorized",
            "authorized": True,
            "is_focused": True,
        },
        camera_status={
            "available": True,
            "active": True,
            "device_count": 1,
            "active_device_names": [],
        },
    )
    _assert(camera_beats_focus.active, "expected active auto DND when camera + focus coexist")
    _assert(
        camera_beats_focus.reason_key == "camera_active",
        f"expected camera to outrank focus: {camera_beats_focus!r}",
    )

    share_beats_camera = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="Google Chrome",
            bundle_id="com.google.Chrome",
            title="Weekly review - sharing screen",
            width=960,
            height=720,
        ),
        screen_bounds_list=SCREEN,
        camera_status={
            "available": True,
            "active": True,
            "device_count": 1,
            "active_device_names": ["FaceTime HD Camera"],
        },
    )
    _assert(share_beats_camera.active, "expected active auto DND when share + camera coexist")
    _assert(
        share_beats_camera.reason_key == "screen_share",
        f"expected explicit share to outrank camera: {share_beats_camera!r}",
    )

    camera_idle = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            title="Notes",
            width=960,
            height=620,
        ),
        screen_bounds_list=SCREEN,
        camera_status={
            "available": True,
            "active": False,
            "device_count": 1,
            "active_device_names": [],
        },
    )
    _assert(not camera_idle.active, f"idle camera should not trigger auto DND: {camera_idle!r}")

    camera_unavailable = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            title="Notes",
            width=960,
            height=620,
        ),
        screen_bounds_list=SCREEN,
        camera_status={
            "available": False,
            "active": False,
            "device_count": 0,
            "active_device_names": [],
        },
    )
    _assert(
        not camera_unavailable.active,
        f"unavailable camera probe should not trigger auto DND: {camera_unavailable!r}",
    )

    normal = evaluate_auto_do_not_disturb(
        _snapshot(
            app_name="TextEdit",
            bundle_id="com.apple.TextEdit",
            title="Notes",
            width=960,
            height=620,
        ),
        screen_bounds_list=SCREEN,
        camera_status={
            "available": True,
            "active": False,
            "device_count": 0,
            "active_device_names": [],
        },
    )
    _assert(not normal.active, f"unexpected auto DND for normal window: {normal!r}")

    print("ok")


if __name__ == "__main__":
    main()
