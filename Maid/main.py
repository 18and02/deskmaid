"""Desktop Maid — macOS desktop agent shell.

Current baseline:
- transparent, always-on-top, non-activating panel with Retina-safe hit-testing
- drag-to-move body, idle micromotion, reminders, and alert bubble
- multi-line input, local-file attachments, AskUserQuestion, permission dialog
- resumable Claude Agent SDK session, long-term memory panel, thought trace
- desktop bridge + Calendar / Reminders / Mail tool flows

Run:
    .venv/bin/python -u Maid/main.py [flags]
        --sprite-set NAME       use a manifest/legacy sprite pack id
        --sprite NAME           (legacy) single-sprite: assets/NAME.png + NAME_blink.png
        --sprite-dpr N          device-pixel-ratio of sprites (default 2.0)
        --demo                  short reminder intervals for live testing
        --reminder-first N      seconds to the first reminder
        --reminder-every N      seconds between reminders

Quit: right-click body -> Quit  (q / esc also work when focused)
"""

import argparse
from concurrent.futures import Future
from ctypes import c_void_p
from dataclasses import dataclass
import json
import math
import os
import random
import sys
import time
from enum import Enum
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPoint, QObject, Signal, QThread, QUrl
from PySide6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QCursor, QAction, QTextCursor,
    QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QMenu, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
    QFileDialog, QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QRadioButton, QScrollArea, QSpinBox, QVBoxLayout,
)

from maid_api_key import (
    API_KEY_PATH_ENV_VAR,
    DEFAULT_API_KEY_PATH,
    ApiKeyStatus,
    api_key_status,
    save_api_key,
)
from maid_auto_dnd import AutoDoNotDisturbState, probe_auto_do_not_disturb
from maid_app_state import (
    APP_STATE_ENV_VAR,
    DEFAULT_APP_STATE_PATH,
    DEFAULT_ACTIVITY_REMINDER_MINUTES,
    DEFAULT_ACTIVITY_REMINDER_ENABLED,
    DEFAULT_CUSTOM_REMINDER_ENABLED,
    DEFAULT_CUSTOM_REMINDER_MINUTES,
    DEFAULT_CUSTOM_REMINDER_TEXT,
    DEFAULT_SPRITE_POSITION_X_PERCENT,
    DEFAULT_SPRITE_POSITION_Y_PERCENT,
    DEFAULT_SPRITE_SCREEN_MODE,
    DEFAULT_SPRITE_SIZE_PERCENT,
    DEFAULT_REMINDERS_ENABLED,
    DEFAULT_WATER_REMINDER_ENABLED,
    DEFAULT_WATER_REMINDER_MINUTES,
    AppStateSnapshot,
    AppStateStore,
    MAX_REMINDER_MINUTES,
    MAX_SPRITE_SIZE_PERCENT,
    MIN_REMINDER_MINUTES,
    MIN_SPRITE_SIZE_PERCENT,
    SPRITE_SCREEN_MODE_CURSOR,
    SPRITE_SCREEN_MODE_PRIMARY,
    load_app_state_snapshot,
)
from bubble import SpeechBubble
from maid_health import collect_permission_health
from maid_memory import (
    DEFAULT_MEMORY_STATE_PATH,
    MEMORY_KEYCHAIN_MODE_ENV_VAR,
    MEMORY_KEY_ENV_VAR,
    MEMORY_STATE_ENV_VAR,
)
from maid_outing import (
    departure_line as outing_departure_line,
    format_outing_return_message,
    load_outing_catalog,
    OutingCatalog,
    OutingResult,
    OutingSnapshot,
    OutingStateStore,
    outing_duration_seconds,
    pick_outing_result,
    RARITY_LABELS,
)
from maid_privacy import rewrite_prompt_for_privacy_action
from maid_permission_recovery import (
    build_permission_recovery_guide,
    perform_permission_recovery_action,
)
from maid_preferences import (
    BUDGET_MODE_DAILY_LIMIT_USD,
    AUTO_HIDE_REASON_KEYS,
    BUDGET_MODE_DESCRIPTIONS,
    BUDGET_MODE_LABELS,
    BUDGET_MODE_MAX_BUDGET_USD,
    BUDGET_MODE_OPTIONS,
    BUDGET_MODE_WEEKLY_LIMIT_USD,
    CURRENT_SETUP_VERSION,
    DEFAULT_LANGUAGE,
    DEFAULT_UI_LANGUAGE,
    LANGUAGE_DESCRIPTIONS,
    LANGUAGE_LABELS,
    LANGUAGE_OPTIONS,
    SYSTEM_LANGUAGE,
    UI_LANGUAGE_DESCRIPTIONS,
    UI_LANGUAGE_LABELS,
    UI_LANGUAGE_OPTIONS,
    detect_system_language,
    normalize_budget_mode,
    normalize_language,
    normalize_ui_language,
    resolve_ui_language,
)
from maid_sprite_packs import (
    available_sprite_pack_ids,
    DEFAULT_SPRITE_PACK_ID,
    describe_available_sprite_packs,
    diagnose_sprite_pack,
    ensure_user_sprite_pack_template,
    resolve_sprite_pack,
    SpritePackError,
    SpritePackBundle,
    SpritePackSummary,
    user_sprite_packs_dir,
)
from maid_chat import (
    AskUserQuestionDecision,
    AskUserQuestionRequest,
    ChatTraceEvent,
    clear_resumable_session,
    clear_remembered_tool_permissions,
    consume_budget_reset_notice,
    create_long_term_memory_item,
    delete_long_term_memory_item,
    get_budget_guard_snapshot,
    get_long_term_memory_items,
    get_resumable_session_id,
    get_remembered_tool_permissions,
    note_budget_resume,
    note_budget_suspend,
    PermissionDecision,
    PermissionRequest,
    ask_maid,
    record_budget_activity,
    set_ask_user_question_handler,
    set_permission_handler,
    shutdown_maid_session,
    update_long_term_memory_item,
)
from lines import (
    ACTIVITY_REMINDER_LINES,
    HUNGER_FULL_LINES,
    HUNGER_HUNGRY_LINES,
    HUNGER_PECKISH_LINES,
    HUNGER_STARVING_LINES,
    IDLE_QUIP_LINES,
    LIFECYCLE_LAUNCH_LINES,
    LIFECYCLE_QUIT_LINES,
    WATER_REMINDER_LINES,
)
from maid_hunger import (
    HUNGER_STAGE_HUNGRY,
    HUNGER_STAGE_NORMAL,
    HUNGER_STAGE_PECKISH,
    HUNGER_STAGE_STARVING,
    HungerAnnouncer,
    HungerState,
    evaluate_hunger,
    pick_hunger_line,
)

# --- macOS native window tweaks via PyObjC ---
try:
    import objc
    from AppKit import NSApplication, NSApplicationActivationPolicyRegular
    HAVE_OBJC = True
    _OBJC_ERR = None
except Exception as e:  # pragma: no cover
    HAVE_OBJC = False
    _OBJC_ERR = e

try:
    from AppKit import (
        NSStatusWindowLevel,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowStyleMaskNonactivatingPanel,
    )
except Exception:
    NSStatusWindowLevel = 25
    NSWindowCollectionBehaviorCanJoinAllSpaces = 1 << 0
    NSWindowCollectionBehaviorStationary = 1 << 4
    NSWindowCollectionBehaviorFullScreenAuxiliary = 1 << 8
    NSWindowStyleMaskNonactivatingPanel = 1 << 7

try:
    from AppKit import (
        NSApplicationDidChangeScreenParametersNotification,
        NSWorkspace,
        NSWorkspaceActiveSpaceDidChangeNotification,
        NSWorkspaceDidWakeNotification,
        NSWorkspaceDidActivateApplicationNotification,
        NSWorkspaceDidLaunchApplicationNotification,
        NSWorkspaceScreensDidSleepNotification,
        NSWorkspaceScreensDidWakeNotification,
        NSWorkspaceDidTerminateApplicationNotification,
        NSWorkspaceWillSleepNotification,
    )
    from Foundation import NSNotificationCenter

    HAVE_AUTO_DND_NATIVE_NOTIFICATIONS = True
    _AUTO_DND_NATIVE_NOTIFICATIONS_ERR = None
except Exception as e:  # pragma: no cover
    HAVE_AUTO_DND_NATIVE_NOTIFICATIONS = False
    _AUTO_DND_NATIVE_NOTIFICATIONS_ERR = e
    NSNotificationCenter = None
    NSWorkspace = None
    NSWorkspaceActiveSpaceDidChangeNotification = None
    NSWorkspaceDidWakeNotification = None
    NSWorkspaceDidActivateApplicationNotification = None
    NSWorkspaceDidLaunchApplicationNotification = None
    NSWorkspaceScreensDidSleepNotification = None
    NSWorkspaceScreensDidWakeNotification = None
    NSWorkspaceDidTerminateApplicationNotification = None
    NSWorkspaceWillSleepNotification = None
    NSApplicationDidChangeScreenParametersNotification = None


def _bundle_root_from_executable() -> Path | None:
    executable = Path(sys.executable).resolve()
    parts = executable.parts
    for index, part in enumerate(parts):
        if part.endswith(".app"):
            return Path(*parts[: index + 1])
    return None


def _resolve_assets_dir() -> Path:
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_path = Path(str(meipass)).resolve()
        candidates.append(meipass_path / "Maid" / "assets")
        candidates.append(meipass_path / "assets")

    bundle_root = _bundle_root_from_executable()
    if bundle_root is not None:
        candidates.append(bundle_root / "Contents" / "Resources" / "Maid" / "assets")
        candidates.append(bundle_root / "Contents" / "Resources" / "assets")

    candidates.append(Path(__file__).resolve().parent / "assets")

    for candidate in candidates:
        if (candidate / "maid_idle.png").is_file():
            return candidate
    return candidates[0]


ASSETS = _resolve_assets_dir()

ALPHA_THRESHOLD = 10
TICK_MS = 16
DEFAULT_ASSET_DPR = 2.0
DEFAULT_SPRITE_SET = DEFAULT_SPRITE_PACK_ID

# step 3: idle micromotion
PAD_TOP = 4
PAD_BOTTOM = 4
BREATH_PERIOD_S = 3.6
BREATH_AMP_LOGICAL = 3
BLINK_INTERVAL = (2.5, 5.5)
BLINK_DURATION = (0.10, 0.18)
DOUBLE_BLINK_CHANCE = 0.20
DOUBLE_BLINK_GAP = (0.12, 0.28)

# step 4-5: state machine + reminders
ALERT_DURATION_S = 5.0
DEMO_REMINDER_FIRST_S = 10
DEMO_REMINDER_INTERVAL_S = 20
DEFAULT_DEMO_INPUT_DELAY_S = 0.6

CHAT_ERROR_LINE = "我现在连不上脑子。先等一会。"
DND_ENABLED_LINE = "免打扰已经开了。主动提醒先别吵你。"
DND_DISABLED_LINE = "免打扰已经关了。她又能开口了。"
DND_DISABLED_AUTO_LINE = "手动免打扰关了，但当前场景还在自动免打扰。"
DEFERRED_ALERT_LINE = "刚才那句提醒先替你压住了。"
AUTO_DND_POLL_MS = 5000
AUTO_DND_EVENT_DEBOUNCE_MS = 120
BUDGET_NOTICE_POLL_MS = 60 * 1000
AUTO_HIDE_ENABLED_LINE = "共享/录屏时自动隐藏已经开了。"
AUTO_HIDE_DISABLED_LINE = "共享/录屏时自动隐藏已经关了。"
RECENT_PRIVACY_EVENTS_LIMIT = 6

# emote: a brief sprite flash (e.g. "excited") triggered by interaction.
# Not a state — it overlays on top of IDLE, but ALERT still wins.
EMOTE_DURATION_S = 1.5

# transitional overlays (similar to emote): brief, time-bound
ENTER_DURATION_S = 2.0     # opening animation on launch
EXIT_DURATION_S  = 1.5     # closing animation before actual quit

# IDLE mood substates: short ambient inserts triggered by activity / uptime.
SLEEPY_AFTER_S        = 60         # default: 60s of no user interaction -> sleepy
PECKISH_AFTER_S       = 30 * 60    # default: 30 min uptime -> peckish
SLEEPY_DURATION_S     = 8.0
PECKISH_DURATION_S    = 8.0
SLEEPY_REPEAT_S       = 2 * 60
PECKISH_REPEAT_S      = 15 * 60
DEMO_SLEEPY_AFTER_S   = 5
DEMO_PECKISH_AFTER_S  = 15
DEMO_SLEEPY_REPEAT_S  = 15
DEMO_PECKISH_REPEAT_S = 20

# Idle quips (脚本台词 §三): low-frequency spoken asides, only while idle.
# 频率刻意压低——仅在长时间无操作时触发，且两次之间至少间隔 ~20 分钟，否则从可爱变烦人。
IDLE_QUIP_AFTER_S       = 5 * 60   # must stay idle this long before the first quip
IDLE_QUIP_REPEAT_S      = 20 * 60  # minimum gap between consecutive quips
DEMO_IDLE_QUIP_AFTER_S  = 4
DEMO_IDLE_QUIP_REPEAT_S = 10


class MaidState(Enum):
    IDLE = "idle"
    ALERT = "alert"


@dataclass(frozen=True)
class ReminderRule:
    key: str
    label: str
    interval_s: float
    line: str
    first_delay_s: float | None = None
    enabled: bool = True
    line_options: tuple[str, ...] = ()


class ReminderScheduler(QObject):
    fired = Signal(str)
    manual_fired = Signal(str)

    def __init__(self, rules: list[ReminderRule] | None = None):
        super().__init__()
        self._rules: dict[str, ReminderRule] = {}
        self._configured_rules: list[ReminderRule] = []
        self._timers: dict[str, QTimer] = {}
        self.configure(rules or [])

    def configure(self, rules: list[ReminderRule]):
        self.stop()
        self._configured_rules = list(rules)
        self._rules = {}
        self._timers = {}
        for rule in self._configured_rules:
            if not rule.enabled or rule.interval_s <= 0 or not self._lines_for_rule(rule):
                continue
            key = str(rule.key or "").strip()
            if not key:
                continue
            self._rules[key] = rule
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda key=key: self._fire(key))
            first_s = rule.interval_s if rule.first_delay_s is None else rule.first_delay_s
            timer.start(max(0, int(first_s * 1000)))
            self._timers[key] = timer
            print(
                f"[sched] {rule.label} first in {first_s:.1f}s, "
                f"then every {rule.interval_s:.1f}s"
            )
        if not self._timers:
            print("[sched] no active reminders")

    def stop(self):
        for timer in self._timers.values():
            timer.stop()
            timer.deleteLater()
        self._timers = {}

    def active_rule_count(self) -> int:
        return len(self._timers)

    def _fire(self, key: str):
        rule = self._rules.get(key)
        if rule is None:
            return
        self.fired.emit(random.choice(self._lines_for_rule(rule)))
        timer = self._timers.get(key)
        if timer is not None:
            timer.start(max(1, int(rule.interval_s * 1000)))

    def _lines_for_rule(self, rule: ReminderRule) -> list[str]:
        lines = [str(line or "").strip() for line in rule.line_options]
        lines = [line for line in lines if line]
        if not lines and rule.line.strip():
            lines = [rule.line.strip()]
        return lines

    def _pick_line(self) -> str:
        candidates: list[str] = []
        for rule in self._configured_rules:
            if not rule.enabled and self._rules:
                continue
            candidates.extend(self._lines_for_rule(rule))
        if not candidates:
            candidates = [WATER_REMINDER_LINES[0]]
        return random.choice(candidates)

    def trigger_now(self):
        self.manual_fired.emit(self._pick_line())


def _reminder_rules_from_snapshot(
    snapshot: AppStateSnapshot,
    *,
    first_delay_s: float | None = None,
    interval_override_s: float | None = None,
) -> list[ReminderRule]:
    reminders_enabled = bool(getattr(snapshot, "reminders_enabled", DEFAULT_REMINDERS_ENABLED))

    def _interval(minutes: int) -> float:
        if interval_override_s is not None:
            return max(1.0, float(interval_override_s))
        return max(1.0, float(minutes) * 60.0)

    def _first(interval_s: float) -> float:
        if first_delay_s is not None:
            return max(0.0, float(first_delay_s))
        return interval_s

    water_interval = _interval(
        int(getattr(snapshot, "water_reminder_minutes", DEFAULT_WATER_REMINDER_MINUTES) or DEFAULT_WATER_REMINDER_MINUTES)
    )
    activity_interval = _interval(
        int(getattr(snapshot, "activity_reminder_minutes", DEFAULT_ACTIVITY_REMINDER_MINUTES) or DEFAULT_ACTIVITY_REMINDER_MINUTES)
    )
    custom_interval = _interval(
        int(getattr(snapshot, "custom_reminder_minutes", DEFAULT_CUSTOM_REMINDER_MINUTES) or DEFAULT_CUSTOM_REMINDER_MINUTES)
    )
    return [
        ReminderRule(
            key="water",
            label="water",
            interval_s=water_interval,
            first_delay_s=_first(water_interval),
            line=WATER_REMINDER_LINES[0],
            enabled=reminders_enabled
            and bool(getattr(snapshot, "water_reminder_enabled", DEFAULT_WATER_REMINDER_ENABLED)),
            line_options=tuple(WATER_REMINDER_LINES),
        ),
        ReminderRule(
            key="activity",
            label="activity",
            interval_s=activity_interval,
            first_delay_s=_first(activity_interval),
            line=ACTIVITY_REMINDER_LINES[0],
            enabled=reminders_enabled
            and bool(getattr(snapshot, "activity_reminder_enabled", DEFAULT_ACTIVITY_REMINDER_ENABLED)),
            line_options=tuple(ACTIVITY_REMINDER_LINES),
        ),
        ReminderRule(
            key="custom",
            label="custom",
            interval_s=custom_interval,
            first_delay_s=_first(custom_interval),
            line=str(getattr(snapshot, "custom_reminder_text", DEFAULT_CUSTOM_REMINDER_TEXT) or DEFAULT_CUSTOM_REMINDER_TEXT),
            enabled=reminders_enabled and bool(
                getattr(snapshot, "custom_reminder_enabled", False)
            ),
        ),
    ]


class ChatWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    trace = Signal(object)

    def __init__(self, prompt: str):
        super().__init__()
        self._prompt = prompt

    def _emit_trace(self, event: ChatTraceEvent):
        self.trace.emit(event)

    def run(self):
        try:
            result = ask_maid(self._prompt, trace_handler=self._emit_trace)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class PermissionHealthWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            snapshot = collect_permission_health()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(snapshot)


def _normalize_attachment_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        candidate = str(raw_path or "").strip()
        if not candidate:
            continue
        try:
            resolved = Path(candidate).expanduser().resolve()
        except Exception:
            resolved = Path(candidate).expanduser()
        if not resolved.exists() or not resolved.is_file():
            continue
        normalized_path = str(resolved)
        if normalized_path in seen:
            continue
        seen.add(normalized_path)
        normalized.append(normalized_path)
    return normalized


def _extract_local_file_paths(mime_data) -> list[str]:
    if mime_data is None or not mime_data.hasUrls():
        return []
    raw_paths = [
        url.toLocalFile()
        for url in mime_data.urls()
        if url.isLocalFile()
    ]
    return _normalize_attachment_paths(raw_paths)


def _display_local_path(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return text
    home = str(Path.home())
    if home and home != "/":
        return text.replace(home, "~")
    return text


def _build_prompt_with_attachments(prompt: str, attachments: list[str]) -> str:
    attachment_paths = _normalize_attachment_paths(attachments)
    if not attachment_paths:
        return prompt
    lines = [
        prompt,
        "",
        "附带的本地文件路径如下:",
    ]
    lines.extend(f"- {_display_local_path(path)}" for path in attachment_paths)
    lines.extend(
        [
            "",
            "如果你需要读取、总结、发送或附加这些文件，请直接使用这些路径。",
        ]
    )
    return "\n".join(lines)


class ChatComposerEdit(QPlainTextEdit):
    submit_requested = Signal()
    files_dropped = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)

    def keyPressEvent(self, ev):
        send_modifiers = Qt.ControlModifier | Qt.MetaModifier
        if (
            ev.key() in (Qt.Key_Return, Qt.Key_Enter)
            and ev.modifiers() & send_modifiers
        ):
            self.submit_requested.emit()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def dragEnterEvent(self, ev):
        if self.isReadOnly():
            super().dragEnterEvent(ev)
            return
        if _extract_local_file_paths(ev.mimeData()):
            ev.acceptProposedAction()
            return
        super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev):
        if self.isReadOnly():
            super().dragMoveEvent(ev)
            return
        if _extract_local_file_paths(ev.mimeData()):
            ev.acceptProposedAction()
            return
        super().dragMoveEvent(ev)

    def dropEvent(self, ev):
        if self.isReadOnly():
            super().dropEvent(ev)
            return
        paths = _extract_local_file_paths(ev.mimeData())
        if paths:
            self.files_dropped.emit(paths)
            ev.acceptProposedAction()
            return
        super().dropEvent(ev)


class ChatInputDialog(QDialog):
    submitted = Signal(str, object)
    _PRIVACY_REWRITE_BUTTONS = (
        ("hidden", "[已隐藏]", "把命中的真实值改成 [已隐藏]"),
        ("last4", "末四位", "把命中的真实值改成只保留末四位"),
        ("local_only", "仅本机处理", "改成仅本机处理的安全写法"),
    )
    _PRIVACY_REWRITE_STATUS = {
        "hidden": "已改成 [已隐藏] 写法，确认后再发。",
        "last4": "已改成末四位写法，确认后再发。",
        "local_only": "已改成仅本机处理写法，确认后再发。",
    }
    _STATUS_STYLES = {
        "muted": "color: #666;",
        "warning": "color: #8a5b12; font-weight: 600;",
        "success": "color: #1f6d3a; font-weight: 600;",
    }

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("输入")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.setAcceptDrops(True)
        self.resize(468, 276)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QPlainTextEdit#chatComposer {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d7d7d7;
                border-radius: 8px;
                padding: 8px;
            }
            QPlainTextEdit#chatComposer:focus {
                border: 1px solid #bdd6fb;
            }
            QLabel#attachmentsLabel {
                color: #666;
                font-weight: 600;
            }
            QFrame#privacyRewritePanel {
                background: #fffaf1;
                border: 1px solid #ead9bc;
                border-radius: 8px;
            }
            QLabel#privacyRewriteTitle {
                color: #7a4d0f;
                font-weight: 600;
            }
            QLabel#privacyRewriteHint {
                color: #8a5b12;
            }
            QPushButton#chatActionButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton#chatActionButton:hover {
                background: #f0f0f0;
            }
            QPushButton#chatPrimaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
                border-radius: 6px;
                padding: 5px 14px;
            }
            QPushButton#chatPrimaryButton:hover {
                background: #dcecff;
            }
            QPushButton#privacyRewriteButton {
                background: #ffffff;
                color: #7a4d0f;
                border: 1px solid #e0c083;
                border-radius: 6px;
                padding: 5px 12px;
                min-width: 78px;
            }
            QPushButton#privacyRewriteButton:hover {
                background: #fff0d8;
            }
            """
        )

        self._draft_text = ""
        self._draft_attachments: list[str] = []
        self._privacy_rewrite_source_text = ""
        self._applying_privacy_rewrite = False

        self._input = ChatComposerEdit(self)
        self._input.setObjectName("chatComposer")
        self._input.setPlaceholderText(
            "想说什么\nEnter 换行，Cmd/Ctrl+Enter 发送；把文件拖进来可附带"
        )
        self._input.setFixedHeight(108)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.submit_requested.connect(self._emit_submit)
        self._input.files_dropped.connect(self.add_attachments)

        self._attachments_label = QLabel("", self)
        self._attachments_label.setObjectName("attachmentsLabel")
        self._attachments_label.hide()

        self._attachments_host = QWidget(self)
        self._attachments_layout = QVBoxLayout(self._attachments_host)
        self._attachments_layout.setContentsMargins(0, 0, 0, 0)
        self._attachments_layout.setSpacing(6)

        self._attachments_scroll = QScrollArea(self)
        self._attachments_scroll.setWidgetResizable(True)
        self._attachments_scroll.setFrameShape(QFrame.NoFrame)
        self._attachments_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._attachments_scroll.setFixedHeight(92)
        self._attachments_scroll.setWidget(self._attachments_host)
        self._attachments_scroll.hide()

        self._attach = QPushButton("添附件", self)
        self._attach.setObjectName("chatActionButton")
        self._attach.clicked.connect(self._choose_attachments)

        self._send = QPushButton("发送", self)
        self._send.setObjectName("chatPrimaryButton")
        self._send.clicked.connect(self._emit_submit)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)
        self._set_status_text("")

        self._privacy_actions_host = QFrame(self)
        self._privacy_actions_host.setObjectName("privacyRewritePanel")
        self._privacy_actions_panel = QVBoxLayout(self._privacy_actions_host)
        self._privacy_actions_panel.setContentsMargins(10, 10, 10, 10)
        self._privacy_actions_panel.setSpacing(8)

        self._privacy_actions_title = QLabel("安全改写建议", self._privacy_actions_host)
        self._privacy_actions_title.setObjectName("privacyRewriteTitle")

        self._privacy_hint = QLabel("", self._privacy_actions_host)
        self._privacy_hint.setObjectName("privacyRewriteHint")
        self._privacy_hint.setWordWrap(True)
        self._privacy_hint.hide()

        self._privacy_actions_layout = QHBoxLayout()
        self._privacy_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._privacy_actions_layout.setSpacing(8)
        self._privacy_action_buttons: dict[str, QPushButton] = {}
        for action, label, tooltip in self._PRIVACY_REWRITE_BUTTONS:
            button = QPushButton(label, self._privacy_actions_host)
            button.setObjectName("privacyRewriteButton")
            button.setMinimumHeight(30)
            button.setToolTip(tooltip)
            button.clicked.connect(
                lambda _checked=False, action_name=action: self._apply_privacy_rewrite(action_name)
            )
            self._privacy_actions_layout.addWidget(button)
            self._privacy_action_buttons[action] = button
        self._privacy_actions_layout.addStretch(1)
        self._privacy_actions_panel.addWidget(self._privacy_actions_title)
        self._privacy_actions_panel.addWidget(self._privacy_hint)
        self._privacy_actions_panel.addLayout(self._privacy_actions_layout)
        self._privacy_actions_host.hide()

        buttons = QHBoxLayout()
        buttons.addWidget(self._attach)
        buttons.addStretch(1)
        buttons.addWidget(self._send)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._input)
        layout.addWidget(self._attachments_label)
        layout.addWidget(self._attachments_scroll)
        layout.addWidget(self._status)
        layout.addWidget(self._privacy_actions_host)
        layout.addLayout(buttons)

    def show_for(self, target: QWidget, text: str | None = None, auto_submit: bool = False):
        self.set_busy(False)
        self._set_status_text("")
        self.hide_privacy_rewrite_actions()
        incoming_text = "" if text is None else str(text)
        replace_text = bool(incoming_text)
        if replace_text:
            self._draft_text = incoming_text
        elif not self._draft_text and text is not None:
            self._draft_text = incoming_text

        display_text = self._draft_text
        if self._input.toPlainText() != display_text:
            self._input.setPlainText(display_text)
        self._refresh_attachments()
        self.reposition(target)
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus(Qt.OtherFocusReason)
        if replace_text and display_text:
            self._input.selectAll()
        else:
            cursor = self._input.textCursor()
            cursor.clearSelection()
            cursor.movePosition(QTextCursor.End)
            self._input.setTextCursor(cursor)
        if auto_submit:
            QTimer.singleShot(0, self._emit_submit)

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.bottom() + 12
        self.move(x, y)

    def set_busy(self, busy: bool, status: str = ""):
        self._input.setReadOnly(busy)
        self._attach.setEnabled(not busy)
        self._attachments_scroll.setEnabled(not busy)
        self._send.setEnabled(not busy)
        self._send.setText("稍等" if busy else "发送")
        for button in self._privacy_action_buttons.values():
            button.setEnabled(not busy)
        self._set_status_text(status)

    def clear_draft(self):
        self._draft_text = ""
        self._draft_attachments = []
        self.hide_privacy_rewrite_actions()
        self._input.clear()
        self._refresh_attachments()
        self._set_status_text("")

    def _set_status_text(self, text: str, *, tone: str = "muted"):
        self._status.setText(str(text or ""))
        self._status.setStyleSheet(
            self._STATUS_STYLES.get(tone, self._STATUS_STYLES["muted"])
        )

    def add_attachments(self, paths: list[str]):
        if self._input.isReadOnly():
            return
        existing = set(self._draft_attachments)
        updated = list(self._draft_attachments)
        for path in _normalize_attachment_paths(paths):
            if path in existing:
                continue
            existing.add(path)
            updated.append(path)
        if updated == self._draft_attachments:
            return
        self._draft_attachments = updated
        self._refresh_attachments()
        self._input.setFocus(Qt.OtherFocusReason)

    def dragEnterEvent(self, ev):
        if self._input.isReadOnly():
            super().dragEnterEvent(ev)
            return
        if _extract_local_file_paths(ev.mimeData()):
            ev.acceptProposedAction()
            return
        super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev):
        if self._input.isReadOnly():
            super().dragMoveEvent(ev)
            return
        if _extract_local_file_paths(ev.mimeData()):
            ev.acceptProposedAction()
            return
        super().dragMoveEvent(ev)

    def dropEvent(self, ev):
        if self._input.isReadOnly():
            super().dropEvent(ev)
            return
        paths = _extract_local_file_paths(ev.mimeData())
        if paths:
            self.add_attachments(paths)
            ev.acceptProposedAction()
            return
        super().dropEvent(ev)

    def _on_text_changed(self):
        self._draft_text = self._input.toPlainText()
        if self._applying_privacy_rewrite:
            return
        if not self._privacy_actions_host.isHidden():
            self._privacy_rewrite_source_text = self._draft_text

    def show_privacy_rewrite_actions(
        self,
        detail: str,
        actions: tuple[str, ...] | list[str],
    ):
        lines = [
            line.strip()
            for line in str(detail or "").splitlines()
            if line.strip()
        ]
        summary = lines[0] if lines else "这句被隐私边界拦下了。"
        self._set_status_text(summary, tone="warning")
        self._privacy_hint.setText(
            "这句没发出去。点下面任一按钮，就会直接把当前输入改成更安全的写法。"
        )
        self._privacy_hint.show()
        visible = False
        enabled_actions = {str(action or "").strip().lower() for action in actions}
        for action, button in self._privacy_action_buttons.items():
            show = action in enabled_actions
            button.setVisible(show)
            visible = visible or show
        self._privacy_actions_host.setVisible(visible)
        self._privacy_rewrite_source_text = self._input.toPlainText()
        self._input.setFocus(Qt.OtherFocusReason)

    def hide_privacy_rewrite_actions(self):
        self._privacy_hint.clear()
        self._privacy_hint.hide()
        self._privacy_actions_host.hide()
        for button in self._privacy_action_buttons.values():
            button.hide()
        self._privacy_rewrite_source_text = ""

    def _apply_privacy_rewrite(self, action: str):
        source_text = self._privacy_rewrite_source_text or self._input.toPlainText()
        rewritten = rewrite_prompt_for_privacy_action(source_text, action)
        if rewritten.value == source_text:
            self._set_status_text("这句里没有找到可快捷改写的高敏值。", tone="warning")
            return
        self._applying_privacy_rewrite = True
        try:
            self._input.setPlainText(rewritten.value)
        finally:
            self._applying_privacy_rewrite = False
        cursor = self._input.textCursor()
        cursor.clearSelection()
        cursor.movePosition(QTextCursor.End)
        self._input.setTextCursor(cursor)
        self._draft_text = rewritten.value
        self._set_status_text(
            self._PRIVACY_REWRITE_STATUS.get(
                rewritten.action,
                "已经改写当前输入，确认后再发。",
            ),
            tone="success",
        )
        self._input.setFocus(Qt.OtherFocusReason)

    def _choose_attachments(self):
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "选择要附带的文件",
        )
        if not paths:
            return
        self.add_attachments(paths)

    def _remove_attachment(self, path: str):
        self._draft_attachments = [
            current
            for current in self._draft_attachments
            if current != path
        ]
        self._refresh_attachments()

    def _refresh_attachments(self):
        while self._attachments_layout.count():
            item = self._attachments_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._draft_attachments:
            self._attachments_label.hide()
            self._attachments_scroll.hide()
            return

        self._attachments_label.setText(f"附件 {len(self._draft_attachments)} 个")
        self._attachments_label.show()
        for path in self._draft_attachments:
            self._attachments_layout.addWidget(self._build_attachment_row(path))
        self._attachments_layout.addStretch(1)
        self._attachments_scroll.show()

    def _build_attachment_row(self, path: str) -> QWidget:
        card = QFrame(self._attachments_host)
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet(
            """
            QFrame {
                background: #ffffff;
                border: 1px solid #d8d8d8;
                border-radius: 6px;
            }
            QLabel {
                color: #1f1f1f;
                border: none;
            }
            QLabel#attachmentMeta {
                color: #666666;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            """
        )

        name = QLabel(Path(path).name, card)
        name.setWordWrap(True)
        name.setToolTip(path)

        meta = QLabel(str(Path(path).parent), card)
        meta.setObjectName("attachmentMeta")
        meta.setWordWrap(True)
        meta.setToolTip(path)

        remove = QPushButton("移除", card)
        remove.clicked.connect(
            lambda _checked=False, target_path=path: self._remove_attachment(target_path)
        )

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        text.addWidget(name)
        text.addWidget(meta)

        row = QHBoxLayout(card)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)
        row.addLayout(text, 1)
        row.addWidget(remove)
        return card

    def _emit_submit(self):
        prompt = self._input.toPlainText().strip()
        if not prompt or self._input.isReadOnly():
            return
        self.hide_privacy_rewrite_actions()
        self.submitted.emit(prompt, list(self._draft_attachments))


def _build_permission_guardrail_view(request: PermissionRequest) -> dict[str, str]:
    risk_label = str(request.risk_label or "").strip()
    risk_limit = max(0, int(request.risk_limit or 0))
    risk_remaining = max(0, int(request.risk_remaining or 0))
    total_limit = max(0, int(request.total_limit or 0))
    total_remaining = max(0, int(request.total_remaining or 0))

    if not risk_label and risk_limit <= 0 and total_limit <= 0:
        return {}

    title = f"{risk_label or '工具'} · 单轮护栏"
    detail_parts: list[str] = []
    if risk_limit > 0:
        detail_parts.append(f"这档还剩 {risk_remaining} / {risk_limit} 次")
    if total_limit > 0:
        detail_parts.append(f"整轮工具还剩 {total_remaining} / {total_limit} 次")

    remember_line = (
        "允许后可以勾选“本次会话始终允许此工具”。"
        if request.allow_remember
        else "这类工具不会记住授权，每次都会再确认。"
    )
    detail = "；".join(detail_parts)
    if detail:
        detail = f"{detail}。\n{remember_line}"
    else:
        detail = remember_line

    return {
        "title": title,
        "detail": detail,
    }


class PermissionDialog(QDialog):
    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("权限确认")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(True)
        self.resize(520, 520)

        self._title = QLabel(self)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-weight: 600;")

        self._meta = QLabel(self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color: #666;")

        self._guardrail_box = QFrame(self)
        self._guardrail_box.setStyleSheet(
            """
            QFrame {
                background: #f6f7f9;
                border: 1px solid #d9dde3;
                border-radius: 8px;
            }
            """
        )
        self._guardrail_title = QLabel(self._guardrail_box)
        self._guardrail_title.setStyleSheet("font-weight: 600; color: #263244;")
        self._guardrail_title.setWordWrap(True)
        self._guardrail_detail = QLabel(self._guardrail_box)
        self._guardrail_detail.setStyleSheet("color: #566273;")
        self._guardrail_detail.setWordWrap(True)

        guardrail_layout = QVBoxLayout(self._guardrail_box)
        guardrail_layout.setContentsMargins(10, 10, 10, 10)
        guardrail_layout.setSpacing(4)
        guardrail_layout.addWidget(self._guardrail_title)
        guardrail_layout.addWidget(self._guardrail_detail)

        self._preview_label = QLabel("人工预览", self)
        self._preview_label.setStyleSheet("font-weight: 600;")

        self._preview = QPlainTextEdit(self)
        self._preview.setReadOnly(True)
        self._preview.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._preview.setPlaceholderText("发送前预览")

        self._details_label = QLabel("工具参数", self)
        self._details_label.setStyleSheet("font-weight: 600;")

        self._details = QPlainTextEdit(self)
        self._details.setReadOnly(True)
        self._details.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._details.setPlaceholderText("工具参数")

        self._remember = QCheckBox("本次会话始终允许此工具", self)

        self._deny = QPushButton("拒绝", self)
        self._deny.clicked.connect(self.reject)
        self._allow = QPushButton("允许", self)
        self._allow.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._deny)
        row.addWidget(self._allow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._title)
        layout.addWidget(self._meta)
        layout.addWidget(self._guardrail_box)
        layout.addWidget(self._preview_label)
        layout.addWidget(self._preview, 1)
        layout.addWidget(self._details_label)
        layout.addWidget(self._details, 1)
        layout.addWidget(self._remember)
        layout.addLayout(row)

    def ask_for(self, target: QWidget, request: PermissionRequest) -> PermissionDecision:
        title = request.title or f"Claude 想调用 {request.tool_name}"
        meta_parts = []
        if request.display_name and request.display_name != request.tool_name:
            meta_parts.append(request.display_name)
        meta_parts.append(f"tool={request.tool_name}")
        if request.blocked_path:
            meta_parts.append(f"path={request.blocked_path}")
        if request.decision_reason:
            meta_parts.append(request.decision_reason)
        if request.description:
            meta_parts.append(request.description)

        self._title.setText(title)
        self._meta.setText("\n".join(meta_parts))
        guardrail_view = _build_permission_guardrail_view(request)
        self._guardrail_box.setVisible(bool(guardrail_view))
        if guardrail_view:
            self._guardrail_title.setText(str(guardrail_view.get("title") or ""))
            self._guardrail_detail.setText(str(guardrail_view.get("detail") or ""))
        preview_text = (request.preview_text or "").strip()
        has_preview = bool(preview_text)
        self._preview_label.setVisible(has_preview)
        self._preview.setVisible(has_preview)
        self._preview.setPlainText(preview_text)
        self._details_label.setText("工具参数" if has_preview else "请求详情")
        self._details.setPlainText(
            json.dumps(request.input_data, ensure_ascii=False, indent=2, sort_keys=True)
        )
        self._remember.setChecked(False)
        self._remember.setVisible(request.allow_remember)
        self._remember.setEnabled(request.allow_remember)
        self._allow.setText(request.confirm_label or "允许")
        self._deny.setText("拒绝")
        self.reposition(target)
        self.raise_()
        self.activateWindow()
        accepted = self.exec() == QDialog.Accepted
        if accepted:
            return PermissionDecision(
                allow=True,
                remember_tool=request.allow_remember and self._remember.isChecked(),
            )
        return PermissionDecision(allow=False)

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.bottom() + 12
        self.move(x, y)


class AskUserQuestionDialog(QDialog):
    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("补一句")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(True)
        self.resize(520, 400)

        self._request: AskUserQuestionRequest | None = None
        self._index = 0
        self._answers: dict[str, str | list[str]] = {}
        self._option_buttons: list[QCheckBox | QRadioButton] = []

        self._header = QLabel(self)
        self._header.setWordWrap(True)
        self._header.setStyleSheet("font-weight: 600;")

        self._step = QLabel(self)
        self._step.setStyleSheet("color: #666;")

        self._question = QLabel(self)
        self._question.setWordWrap(True)

        self._options_host = QWidget(self)
        self._options_layout = QVBoxLayout(self._options_host)
        self._options_layout.setContentsMargins(0, 0, 0, 0)
        self._options_layout.setSpacing(8)

        self._options_scroll = QScrollArea(self)
        self._options_scroll.setWidgetResizable(True)
        self._options_scroll.setFrameShape(QFrame.NoFrame)
        self._options_scroll.setWidget(self._options_host)

        self._custom = QLineEdit(self)
        self._custom.setPlaceholderText("自己补一句")
        self._custom.textChanged.connect(self._on_custom_text_changed)
        self._custom.returnPressed.connect(self._advance)

        self._back = QPushButton("上一步", self)
        self._back.clicked.connect(self._go_back)

        self._skip = QPushButton("让 Claude 自己决定", self)
        self._skip.clicked.connect(self._skip_current)

        self._next = QPushButton("继续", self)
        self._next.clicked.connect(self._advance)

        row = QHBoxLayout()
        row.addWidget(self._back)
        row.addWidget(self._skip, 1)
        row.addWidget(self._next)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._header)
        layout.addWidget(self._step)
        layout.addWidget(self._question)
        layout.addWidget(self._options_scroll, 1)
        layout.addWidget(self._custom)
        layout.addLayout(row)

    def ask_for(self, target: QWidget, request: AskUserQuestionRequest) -> AskUserQuestionDecision:
        self._request = request
        self._index = 0
        self._answers = {}
        self._render_question()
        self.reposition(target)
        self.raise_()
        self.activateWindow()
        accepted = self.exec() == QDialog.Accepted
        if accepted:
            return AskUserQuestionDecision(answers=dict(self._answers))
        return AskUserQuestionDecision(
            cancelled=True,
            message="主人取消了这次澄清。",
        )

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.bottom() + 12
        self.move(x, y)

    def _render_question(self):
        assert self._request is not None
        question = self._request.questions[self._index]
        total = len(self._request.questions)

        self._clear_options()
        self._option_buttons = []

        self._header.setText(question.header)
        self._step.setText(f"第 {self._index + 1}/{total} 题")
        self._question.setText(question.question)
        self._back.setVisible(self._index > 0)
        self._next.setText("完成" if self._index + 1 >= total else "继续")

        saved_answer = self._answers.get(question.question)
        saved_values = self._coerce_saved_values(saved_answer)
        option_labels = {option.label for option in question.options}
        custom_text = ""
        for value in saved_values:
            if value not in option_labels:
                custom_text = value
                break

        for option in question.options:
            wrapper = QWidget(self._options_host)
            wrapper_layout = QVBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.setSpacing(2)

            if question.multi_select:
                button: QCheckBox | QRadioButton = QCheckBox(option.label, wrapper)
            else:
                button = QRadioButton(option.label, wrapper)
            button.setChecked(option.label in saved_values)
            button.toggled.connect(self._on_option_toggled)

            wrapper_layout.addWidget(button)
            if option.description:
                detail = QLabel(option.description, wrapper)
                detail.setWordWrap(True)
                detail.setStyleSheet("color: #666; margin-left: 20px;")
                wrapper_layout.addWidget(detail)
            self._options_layout.addWidget(wrapper)
            self._option_buttons.append(button)

        self._options_layout.addStretch(1)

        self._custom.blockSignals(True)
        self._custom.setText(custom_text)
        self._custom.blockSignals(False)
        self._custom.setFocus(Qt.OtherFocusReason)
        self._custom.selectAll()
        self._update_next_enabled()

    def _clear_options(self):
        while self._options_layout.count():
            item = self._options_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _current_question(self):
        assert self._request is not None
        return self._request.questions[self._index]

    def _coerce_saved_values(self, saved_answer: str | list[str] | None) -> list[str]:
        if isinstance(saved_answer, str):
            return [saved_answer]
        if isinstance(saved_answer, list):
            return [
                value
                for value in saved_answer
                if isinstance(value, str) and value
            ]
        return []

    def _collect_answer(self) -> str | list[str] | None:
        question = self._current_question()
        selected_labels = [
            button.text()
            for button in self._option_buttons
            if button.isChecked()
        ]
        custom_text = self._custom.text().strip()

        if question.multi_select:
            values = list(selected_labels)
            if custom_text:
                values.append(custom_text)
            return values or None

        if custom_text:
            return custom_text
        if selected_labels:
            return selected_labels[0]
        return None

    def _save_current_answer(self):
        question = self._current_question()
        answer = self._collect_answer()
        if answer is None:
            self._answers.pop(question.question, None)
        else:
            self._answers[question.question] = answer

    def _update_next_enabled(self):
        self._next.setEnabled(self._collect_answer() is not None)

    def _on_option_toggled(self, checked: bool):
        question = self._current_question()
        if checked and not question.multi_select and self._custom.text().strip():
            self._custom.blockSignals(True)
            self._custom.clear()
            self._custom.blockSignals(False)
        self._update_next_enabled()

    def _on_custom_text_changed(self, text: str):
        question = self._current_question()
        if not question.multi_select and text.strip():
            for button in self._option_buttons:
                was_blocked = button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(was_blocked)
        self._update_next_enabled()

    def _advance(self):
        answer = self._collect_answer()
        if answer is None:
            return
        self._save_current_answer()
        assert self._request is not None
        if self._index + 1 >= len(self._request.questions):
            self.accept()
            return
        self._index += 1
        self._render_question()

    def _skip_current(self):
        question = self._current_question()
        self._answers.pop(question.question, None)
        assert self._request is not None
        if self._index + 1 >= len(self._request.questions):
            self.accept()
            return
        self._index += 1
        self._render_question()

    def _go_back(self):
        self._save_current_answer()
        if self._index <= 0:
            return
        self._index -= 1
        self._render_question()


class ThoughtTraceDialog(QDialog):
    close_requested = Signal()
    _KIND_LABELS = {
        "run_started": "开始",
        "session": "会话",
        "memory_recall": "记忆",
        "memory_store": "记忆",
        "privacy": "隐私",
        "thinking": "思考",
        "assistant_text": "回复",
        "tool_use": "工具",
        "tool_result": "工具",
        "guardrail": "护栏",
        "permission_request": "权限",
        "permission_decision": "权限",
        "question_request": "澄清",
        "question_answer": "澄清",
        "task_started": "任务",
        "task_progress": "任务",
        "task_notification": "任务",
        "result": "完成",
        "error": "错误",
    }

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("思考流")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(520, 360)

        self._status = QLabel("等你开口。", self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #666;")

        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("这里会显示这轮对话的思考流。")
        self._log.document().setMaximumBlockCount(500)

        self._clear = QPushButton("清空", self)
        self._clear.clicked.connect(self.clear)
        self._close = QPushButton("关闭", self)
        self._close.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._clear)
        row.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._log, 1)
        layout.addLayout(row)

        self._last_session_id = None

    def begin_run(self, target: QWidget):
        self.clear()
        self._status.setText("思考中...")
        self.show_for(target)

    def show_for(self, target: QWidget):
        self.reposition(target)
        self.show()
        self.raise_()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.right() + 12
        y = tg.top()

        if screen is not None:
            geo = screen.availableGeometry()
            if x + self.width() > geo.right():
                x = tg.left() - self.width() - 12
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)

    def append_event(self, event: ChatTraceEvent):
        if event.session_id:
            self._last_session_id = event.session_id
        self._status.setText(self._status_text_for(event))

        label = self._KIND_LABELS.get(event.kind, "事件")
        stamp = time.strftime("%H:%M:%S", time.localtime(event.created_at))
        lines = [f"{stamp} [{label}] {event.title}"]

        detail = (event.detail or "").strip()
        if detail:
            for line in detail.splitlines():
                lines.append(f"    {line}")

        self._log.appendPlainText("\n".join(lines) + "\n")
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _status_text_for(self, event: ChatTraceEvent) -> str:
        if event.kind == "result":
            state = "本轮已完成"
        elif event.kind == "error":
            state = "本轮出错了"
        elif event.kind == "permission_request":
            state = "等你点头"
        elif event.kind == "question_request":
            state = "等你补一句"
        elif event.kind in {"tool_use", "tool_result", "task_started", "task_progress"}:
            state = "工具处理中"
        elif event.kind == "memory_recall":
            state = "在翻旧账"
        elif event.kind == "memory_store":
            state = "记下来了"
        elif event.kind == "privacy":
            state = "在收边界"
        elif event.kind == "guardrail":
            state = "护栏接管了"
        elif event.kind == "assistant_text":
            state = "正在组织回复"
        else:
            state = "思考中..."

        if self._last_session_id:
            return f"{state}  |  session={self._last_session_id}"
        return state

    def clear(self):
        self._last_session_id = None
        self._status.setText("等你开口。")
        self._log.clear()

    def closeEvent(self, ev):
        self.close_requested.emit()
        super().closeEvent(ev)


_HEALTH_STATUS_STYLE = {
    "ok": {
        "badge_bg": "#eaf6ee",
        "badge_fg": "#1f6d3a",
        "badge_border": "#bfdcc7",
        "card_bg": "#fcfefd",
        "card_border": "#cfe1d5",
    },
    "warning": {
        "badge_bg": "#fff5e6",
        "badge_fg": "#8a5b12",
        "badge_border": "#edd6b0",
        "card_bg": "#fffdf9",
        "card_border": "#ead9bc",
    },
    "error": {
        "badge_bg": "#fff0f0",
        "badge_fg": "#a33030",
        "badge_border": "#efc8c8",
        "card_bg": "#fffafa",
        "card_border": "#e8cdcd",
    },
}


def _format_health_checked_at(value) -> str:
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stamp))


_BUDGET_STAGE_LABELS = {
    "active": "活跃",
    "idle": "闲时",
    "away": "离开",
    "parked": "停放",
}

_BUDGET_STAGE_HINTS = {
    "active": "刚有交互，单轮预算先按当前档位原值走。",
    "idle": "挂着但暂时没动，单轮预算会先收紧到 80%。",
    "away": "离开得更久了，单轮预算会收紧到 60%。",
    "parked": "长时间挂着没动，单轮预算会收紧到 35%。",
}


def _float_or_none(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _format_budget_amount(value) -> str:
    amount = _float_or_none(value)
    if amount is None:
        return "n/a"
    return f"${amount:.2f}"


def _format_budget_duration(value) -> str:
    seconds = _float_or_none(value)
    if seconds is None or seconds <= 0.5:
        return "0秒"

    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total}秒"

    rounded_minutes = int(round(total / 60))
    if rounded_minutes < 60:
        return f"{rounded_minutes}分"

    minutes = total // 60
    hours, leftover_minutes = divmod(minutes, 60)
    if hours < 24:
        return (
            f"{hours}小时 {leftover_minutes}分"
            if leftover_minutes
            else f"{hours}小时"
        )

    days, leftover_hours = divmod(hours, 24)
    return (
        f"{days}天 {leftover_hours}小时"
        if leftover_hours
        else f"{days}天"
    )


def _format_elapsed_duration(value, *, english: bool = False) -> str:
    seconds = _float_or_none(value)
    if seconds is None or seconds <= 0.5:
        return "0s" if english else "0秒"

    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total}s" if english else f"{total}秒"

    minutes, leftover_seconds = divmod(total, 60)
    if minutes < 60:
        if english:
            return f"{minutes}m {leftover_seconds}s" if leftover_seconds else f"{minutes}m"
        return f"{minutes}分 {leftover_seconds}秒" if leftover_seconds else f"{minutes}分"

    hours, leftover_minutes = divmod(minutes, 60)
    if hours < 24:
        if english:
            return f"{hours}h {leftover_minutes}m" if leftover_minutes else f"{hours}h"
        return f"{hours}小时 {leftover_minutes}分" if leftover_minutes else f"{hours}小时"

    days, leftover_hours = divmod(hours, 24)
    if english:
        return f"{days}d {leftover_hours}h" if leftover_hours else f"{days}d"
    return f"{days}天 {leftover_hours}小时" if leftover_hours else f"{days}天"


def _bounded_percent(value, *, fallback: int, minimum: int = 0, maximum: int = 100) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = int(fallback)
    return max(minimum, min(maximum, normalized))


def _sprite_display_scale_for(
    sprite_pack: SpritePackBundle,
    snapshot: AppStateSnapshot,
) -> float:
    pack_scale = max(
        0.25,
        float(getattr(sprite_pack.metadata, "display_scale", 1.0) or 1.0),
    )
    user_percent = _bounded_percent(
        getattr(snapshot, "sprite_size_percent", DEFAULT_SPRITE_SIZE_PERCENT),
        fallback=DEFAULT_SPRITE_SIZE_PERCENT,
        minimum=MIN_SPRITE_SIZE_PERCENT,
        maximum=MAX_SPRITE_SIZE_PERCENT,
    )
    return max(0.1, pack_scale * (user_percent / 100.0))


def _budget_remaining_ratio(limit_usd, remaining_usd) -> float | None:
    limit = _float_or_none(limit_usd)
    remaining = _float_or_none(remaining_usd)
    if limit is None or remaining is None or limit <= 0:
        return None
    return max(0.0, min(1.0, remaining / limit))


def _format_budget_runs_left(value) -> str:
    runs = _float_or_none(value)
    if runs is None:
        return ""
    runs = max(0.0, runs)
    rounded = round(runs)
    if runs >= 10:
        return f"{runs:.0f}轮"
    if abs(runs - rounded) <= 0.05:
        return f"{int(rounded)}轮"
    return f"{runs:.1f}轮"


def _format_budget_reset_at(value) -> str:
    stamp = _float_or_none(value)
    if stamp is None or stamp <= 0:
        return ""
    return time.strftime("%m-%d %H:%M", time.localtime(stamp))


def _budget_pressure_tone(*levels: str) -> str:
    normalized = {
        str(level or "").strip().lower()
        for level in levels
        if str(level or "").strip()
    }
    if "blocked" in normalized or "critical" in normalized:
        return "error"
    if "warning" in normalized:
        return "warning"
    return "ok"


_BUDGET_MODE_LABELS_EN = {
    "cautious": "Cautious",
    "normal": "Standard",
    "open": "Open",
}

_BUDGET_MODE_DESCRIPTIONS_EN = {
    "cautious": "More conservative per run; good for staying resident all day.",
    "normal": "Balanced default for daily chat and tool use.",
    "open": "Leaves more room for complex tasks and spends faster.",
}

_BUDGET_STAGE_LABELS_EN = {
    "active": "Active",
    "idle": "Idle",
    "away": "Away",
    "parked": "Parked",
}

_BUDGET_STAGE_HINTS_EN = {
    "active": "There was recent activity, so the per-run cap stays at the current base tier.",
    "idle": "The app is sitting idle, so the per-run cap tightens to 80%.",
    "away": "It has been idle longer, so the per-run cap tightens to 60%.",
    "parked": "It has been parked for a long time, so the per-run cap tightens to 35%.",
}

_TOOL_RISK_LABELS_EN = {
    "low": "Low risk",
    "medium": "Medium risk",
    "high": "High risk",
    "critical": "Critical risk",
}

_TOOL_RISK_DESCRIPTIONS_EN = {
    "low": "Read-only overview or clarification tools can be tried more times.",
    "medium": "Light desktop actions or sensitive reads start to tighten one layer.",
    "high": "Data-changing actions or more sensitive reads get only a small per-run budget.",
    "critical": "Send, delete, and simulated input actions get a single shot per run.",
}

_MEMORY_TIER_LABELS_EN = {
    "full": "Full",
    "compact": "Compact",
    "minimal": "Saver",
}


def _resolved_ui_language(value: str | None) -> str:
    return resolve_ui_language(str(value or DEFAULT_UI_LANGUAGE))


def _ui_uses_english(value: str | None) -> bool:
    return _resolved_ui_language(value) == "en-US"


def _localized_reply_language_label(value: str, *, ui_language: str) -> str:
    normalized = normalize_language(value)
    if _ui_uses_english(ui_language):
        return "Chinese" if normalized == "zh-CN" else "English"
    return LANGUAGE_LABELS.get(normalized, LANGUAGE_LABELS[DEFAULT_LANGUAGE])


def _localized_reply_language_description(value: str, *, ui_language: str) -> str:
    normalized = normalize_language(value)
    if _ui_uses_english(ui_language):
        if normalized == "en-US":
            return "Default replies use English."
        return "Default replies use Chinese."
    return LANGUAGE_DESCRIPTIONS.get(normalized, LANGUAGE_DESCRIPTIONS[DEFAULT_LANGUAGE])


def _localized_ui_language_label(value: str, *, ui_language: str) -> str:
    normalized = normalize_ui_language(value)
    if _ui_uses_english(ui_language):
        if normalized == SYSTEM_LANGUAGE:
            return "Follow System"
        if normalized == "zh-CN":
            return "Chinese"
        return "English"
    return UI_LANGUAGE_LABELS.get(normalized, UI_LANGUAGE_LABELS[DEFAULT_UI_LANGUAGE])


def _localized_ui_language_description(value: str, *, ui_language: str) -> str:
    normalized = normalize_ui_language(value)
    if _ui_uses_english(ui_language):
        if normalized == SYSTEM_LANGUAGE:
            system_label = "Chinese" if detect_system_language() == "zh-CN" else "English"
            return f"Use the macOS language for dialogs. Current system language: {system_label}."
        if normalized == "zh-CN":
            return "Use Chinese for the interface and dialogs."
        return "Use English for the interface and dialogs."
    if normalized == SYSTEM_LANGUAGE:
        system_label = "中文" if detect_system_language() == "zh-CN" else "English"
        return f"界面和说明跟随 macOS 语言。当前系统语言: {system_label}。"
    return UI_LANGUAGE_DESCRIPTIONS.get(normalized, UI_LANGUAGE_DESCRIPTIONS[DEFAULT_UI_LANGUAGE])


def _localized_budget_mode_label(mode: str, *, ui_language: str) -> str:
    normalized = normalize_budget_mode(mode)
    if _ui_uses_english(ui_language):
        return _BUDGET_MODE_LABELS_EN.get(normalized, _BUDGET_MODE_LABELS_EN["normal"])
    return BUDGET_MODE_LABELS.get(normalized, BUDGET_MODE_LABELS["normal"])


def _localized_budget_mode_description(mode: str, *, ui_language: str) -> str:
    normalized = normalize_budget_mode(mode)
    if _ui_uses_english(ui_language):
        return _BUDGET_MODE_DESCRIPTIONS_EN.get(
            normalized,
            _BUDGET_MODE_DESCRIPTIONS_EN["normal"],
        )
    return BUDGET_MODE_DESCRIPTIONS.get(normalized, BUDGET_MODE_DESCRIPTIONS["normal"])


def _localized_budget_stage_label(stage: str, *, ui_language: str) -> str:
    normalized = str(stage or "active").strip().lower() or "active"
    if _ui_uses_english(ui_language):
        return _BUDGET_STAGE_LABELS_EN.get(normalized, _BUDGET_STAGE_LABELS_EN["active"])
    return _BUDGET_STAGE_LABELS.get(normalized, _BUDGET_STAGE_LABELS["active"])


def _localized_budget_stage_hint(stage: str, *, ui_language: str) -> str:
    normalized = str(stage or "active").strip().lower() or "active"
    if _ui_uses_english(ui_language):
        return _BUDGET_STAGE_HINTS_EN.get(normalized, _BUDGET_STAGE_HINTS_EN["active"])
    return _BUDGET_STAGE_HINTS.get(normalized, _BUDGET_STAGE_HINTS["active"])


def _localized_tool_risk_label(level: str, *, ui_language: str) -> str:
    normalized = str(level or "").strip().lower()
    if _ui_uses_english(ui_language):
        return _TOOL_RISK_LABELS_EN.get(normalized, _TOOL_RISK_LABELS_EN["high"])
    labels = {
        "low": "低风险",
        "medium": "中风险",
        "high": "高风险",
        "critical": "极高风险",
    }
    return labels.get(normalized, labels["high"])


def _localized_tool_risk_description(level: str, *, ui_language: str) -> str:
    normalized = str(level or "").strip().lower()
    if _ui_uses_english(ui_language):
        return _TOOL_RISK_DESCRIPTIONS_EN.get(
            normalized,
            _TOOL_RISK_DESCRIPTIONS_EN["high"],
        )
    descriptions = {
        "low": "只读概览或澄清类工具，允许多试几次。",
        "medium": "轻度桌面操作或敏感读取，先收一层。",
        "high": "会改数据或读取更敏感正文，单轮只给少量额度。",
        "critical": "发送、删除、模拟输入这类动作，单轮只放一脚。",
    }
    return descriptions.get(normalized, descriptions["high"])


def _localized_memory_tier_label(tier: str, *, ui_language: str) -> str:
    normalized = str(tier or "compact").strip().lower() or "compact"
    if _ui_uses_english(ui_language):
        return _MEMORY_TIER_LABELS_EN.get(normalized, _MEMORY_TIER_LABELS_EN["compact"])
    labels = {
        "full": "标准",
        "compact": "轻量",
        "minimal": "省预算",
    }
    return labels.get(normalized, labels["compact"])


def _build_budget_status_view(
    snapshot: dict[str, object],
    *,
    language: str = "zh-CN",
) -> dict[str, object]:
    if _ui_uses_english(language):
        return _build_budget_status_view_en(snapshot)
    normalized = dict(snapshot or {})
    mode = normalize_budget_mode(str(normalized.get("mode") or "normal"))
    mode_label = BUDGET_MODE_LABELS.get(mode, "标准")
    mode_description = BUDGET_MODE_DESCRIPTIONS.get(mode, "")

    per_run_limit_usd = _float_or_none(normalized.get("per_run_limit_usd"))
    effective_max_budget_usd = _float_or_none(
        normalized.get("effective_max_budget_usd")
    )
    daily_limit_usd = _float_or_none(normalized.get("daily_limit_usd"))
    daily_used_usd = _float_or_none(normalized.get("daily_used_usd")) or 0.0
    daily_remaining_usd = _float_or_none(normalized.get("daily_remaining_usd"))
    weekly_limit_usd = _float_or_none(normalized.get("weekly_limit_usd"))
    weekly_used_usd = _float_or_none(normalized.get("weekly_used_usd")) or 0.0
    weekly_remaining_usd = _float_or_none(normalized.get("weekly_remaining_usd"))
    raw_idle_seconds = _float_or_none(normalized.get("raw_idle_seconds")) or 0.0
    suspended_idle_seconds = (
        _float_or_none(normalized.get("suspended_idle_seconds")) or 0.0
    )
    folded_idle_seconds = (
        _float_or_none(normalized.get("folded_idle_seconds")) or 0.0
    )
    idle_throttle_factor = _float_or_none(normalized.get("idle_throttle_factor")) or 1.0
    idle_throttle_stage = str(normalized.get("idle_throttle_stage") or "active").strip()
    if not idle_throttle_stage:
        idle_throttle_stage = "active"
    idle_throttle_reason = str(normalized.get("idle_throttle_reason") or "").strip()
    daily_pressure_level = str(normalized.get("daily_pressure_level") or "ok").strip()
    weekly_pressure_level = str(normalized.get("weekly_pressure_level") or "ok").strip()
    daily_base_runs_left = _float_or_none(normalized.get("daily_base_runs_left"))
    weekly_base_runs_left = _float_or_none(normalized.get("weekly_base_runs_left"))
    remaining_allows_full_base_run = bool(
        normalized.get("remaining_allows_full_base_run", True)
    )
    remaining_shortfall_usd = (
        _float_or_none(normalized.get("remaining_shortfall_usd")) or 0.0
    )
    next_daily_reset_at = _float_or_none(normalized.get("next_daily_reset_at")) or 0.0
    next_weekly_reset_at = _float_or_none(normalized.get("next_weekly_reset_at")) or 0.0
    tool_risk_quotas = [
        dict(item)
        for item in (normalized.get("tool_risk_quotas") or [])
        if isinstance(item, dict)
    ]
    memory_budget_label = str(normalized.get("memory_budget_label") or "").strip()
    memory_budget_max_items = max(
        0,
        int(_float_or_none(normalized.get("memory_budget_max_items")) or 0),
    )
    memory_budget_clip_chars = max(
        0,
        int(_float_or_none(normalized.get("memory_budget_clip_chars")) or 0),
    )
    memory_budget_factor = _float_or_none(normalized.get("memory_budget_factor")) or 1.0
    memory_budget_reasons = [
        str(reason).strip()
        for reason in (normalized.get("memory_budget_reasons") or [])
        if str(reason).strip()
    ]
    blocked = bool(normalized.get("blocked"))
    blocked_scope = str(normalized.get("blocked_scope") or "").strip()

    stage_label = _BUDGET_STAGE_LABELS.get(idle_throttle_stage, "活跃")
    stage_hint = _BUDGET_STAGE_HINTS.get(
        idle_throttle_stage,
        "最近有交互，单轮预算不会因为闲时额外收紧。",
    )
    factor_percent = max(0, int(round(idle_throttle_factor * 100)))
    blocked_scope_label = "本周" if blocked_scope == "week" else "今天"
    tightened = bool(
        per_run_limit_usd is not None
        and effective_max_budget_usd is not None
        and effective_max_budget_usd < per_run_limit_usd - 1e-6
    )

    tighten_reasons: list[str] = []
    if idle_throttle_factor < 1.0 - 1e-6:
        tighten_reason_label = idle_throttle_reason or stage_label
        tighten_reasons.append(f"{tighten_reason_label} {factor_percent}%")
    if (
        per_run_limit_usd is not None
        and daily_remaining_usd is not None
        and daily_remaining_usd < per_run_limit_usd - 1e-6
    ):
        runs_left = _format_budget_runs_left(daily_base_runs_left)
        if runs_left:
            tighten_reasons.append(f"今日按基础档只够 {runs_left}")
        else:
            tighten_reasons.append(
                f"今日剩余 {_format_budget_amount(daily_remaining_usd)}"
            )
    if (
        per_run_limit_usd is not None
        and weekly_remaining_usd is not None
        and weekly_remaining_usd < per_run_limit_usd - 1e-6
    ):
        runs_left = _format_budget_runs_left(weekly_base_runs_left)
        if runs_left:
            tighten_reasons.append(f"本周按基础档只够 {runs_left}")
        else:
            tighten_reasons.append(
                f"本周剩余 {_format_budget_amount(weekly_remaining_usd)}"
            )
    if not remaining_allows_full_base_run and remaining_shortfall_usd > 1e-6:
        tighten_reasons.append(
            f"还差 {_format_budget_amount(remaining_shortfall_usd)} 才够一整轮基础档"
        )

    summary_text = str(normalized.get("summary") or "").strip()
    if not summary_text:
        summary_text = (
            f"今日 {_format_budget_amount(daily_used_usd)} / {_format_budget_amount(daily_limit_usd)}；"
            f"本周 {_format_budget_amount(weekly_used_usd)} / {_format_budget_amount(weekly_limit_usd)}"
        )

    daily_ratio = _budget_remaining_ratio(daily_limit_usd, daily_remaining_usd)
    weekly_ratio = _budget_remaining_ratio(weekly_limit_usd, weekly_remaining_usd)
    usage_tone = (
        "error"
        if blocked
        else _budget_pressure_tone(daily_pressure_level, weekly_pressure_level)
    )
    run_tone = "error" if blocked else "warning" if tightened else "ok"
    idle_tone = "warning" if idle_throttle_stage != "active" else "ok"
    reset_day_text = _format_budget_reset_at(next_daily_reset_at)
    reset_week_text = _format_budget_reset_at(next_weekly_reset_at)

    if blocked:
        status_text = f"现在已经撞到{blocked_scope_label}硬闸。{summary_text}。"
        if blocked_scope == "week" and reset_week_text:
            meta_text = (
                f"新一轮调用会先拦住；最早等 {reset_week_text} 的本周预算窗重置，"
                "或在设置里把预算档位调高。"
            )
        elif reset_day_text:
            meta_text = (
                f"新一轮调用会先拦住；最早等 {reset_day_text} 的今日预算窗重置，"
                "或在设置里把预算档位调高。"
            )
        else:
            meta_text = (
                "新一轮调用会先拦住；等预算窗自动重置，或在设置里把预算档位调高。"
            )
    elif tightened and not remaining_allows_full_base_run:
        status_text = f"这轮预算比基础档位更紧，而且剩余额度已经不足一整轮基础档。{summary_text}。"
        if tighten_reasons:
            meta_text = (
                f"当前主要是 {'；'.join(tighten_reasons)} 在把单轮上限往下压。"
            )
        else:
            meta_text = "当前剩余额度已经不够一整轮基础档了。"
    elif tightened:
        status_text = f"这轮预算比基础档位更紧。{summary_text}。"
        if tighten_reasons:
            meta_text = (
                f"当前主要是 {'；'.join(tighten_reasons)} 在把单轮上限往下压。"
            )
        else:
            meta_text = "当前有额外收紧；通常是闲时折算或日 / 周剩余额度把上限压低了。"
    elif usage_tone != "ok":
        status_text = f"现在还在预算内，但日 / 周余量已经开始变紧。{summary_text}。"
        daily_runs_text = _format_budget_runs_left(daily_base_runs_left)
        weekly_runs_text = _format_budget_runs_left(weekly_base_runs_left)
        budget_run_lines: list[str] = []
        if daily_runs_text:
            budget_run_lines.append(f"今天按基础档还够 {daily_runs_text}")
        elif daily_ratio is not None:
            budget_run_lines.append(f"今天还剩 {int(round(daily_ratio * 100))}%")
        if weekly_runs_text:
            budget_run_lines.append(f"本周按基础档还够 {weekly_runs_text}")
        elif weekly_ratio is not None:
            budget_run_lines.append(f"本周还剩 {int(round(weekly_ratio * 100))}%")
        meta_text = (
            "；".join(budget_run_lines) + "。"
            if budget_run_lines
            else "预算窗还没打满，但已经开始接近硬闸。"
        )
    else:
        status_text = f"现在还在预算内。{summary_text}。"
        meta_text = "闲时越久，单轮上限会越保守；跨天 / 跨周时预算窗会自动重置。"

    if blocked:
        run_summary = f"当前不会再发起新一轮调用，{blocked_scope_label}预算已经打满。"
        run_detail = (
            f"基础单轮上限 {_format_budget_amount(per_run_limit_usd)}；"
            f"当前生效上限 {_format_budget_amount(effective_max_budget_usd)}。"
        )
        if blocked_scope == "week" and reset_week_text:
            run_hint = (
                f"等 {reset_week_text} 的本周预算窗重置后会自动放开；"
                "也可以在设置里切更高档位。"
            )
        elif reset_day_text:
            run_hint = (
                f"等 {reset_day_text} 的今日预算窗重置后会自动放开；"
                "也可以在设置里切更高档位。"
            )
        else:
            run_hint = "预算窗重置后会自动放开；也可以在设置里切更高档位。"
        run_badge = "已打满"
    elif tightened:
        run_summary = (
            f"当前生效单轮上限 {_format_budget_amount(effective_max_budget_usd)} "
            f"（基础 {_format_budget_amount(per_run_limit_usd)}）。"
        )
        run_detail = (
            f"影响因素: {'；'.join(tighten_reasons)}。"
            if tighten_reasons
            else "当前这轮被额外收紧了。"
        )
        if not remaining_allows_full_base_run and remaining_shortfall_usd > 1e-6:
            run_hint = (
                "闲时收紧可以靠重新活跃立刻恢复，但预算窗还差 "
                f"{_format_budget_amount(remaining_shortfall_usd)} 才够一整轮基础档。"
            )
        else:
            run_hint = "只要重新活跃起来，或预算窗重置，这个上限就会松一点。"
        run_badge = "已收紧"
    else:
        run_summary = (
            f"当前生效单轮上限 {_format_budget_amount(effective_max_budget_usd)}。"
        )
        run_detail = (
            f"基础单轮上限 {_format_budget_amount(per_run_limit_usd)}，"
            "现在没有额外收紧。"
        )
        run_hint = "只要今日 / 本周剩余额度还够，这轮就按当前档位原值放行。"
        run_badge = "正常"

    if blocked:
        usage_badge = "已打满"
    elif not remaining_allows_full_base_run:
        usage_badge = "不足一轮"
    elif usage_tone == "error":
        usage_badge = "告急"
    elif usage_tone == "warning":
        usage_badge = "偏紧"
    else:
        usage_badge = "平稳"

    daily_runs_text = _format_budget_runs_left(daily_base_runs_left)
    weekly_runs_text = _format_budget_runs_left(weekly_base_runs_left)
    usage_summary = (
        f"今天已用 {_format_budget_amount(daily_used_usd)} / "
        f"{_format_budget_amount(daily_limit_usd)}，"
        f"还剩 {_format_budget_amount(daily_remaining_usd)}。"
    )
    if daily_runs_text:
        usage_summary += f" 按基础档还够 {daily_runs_text}。"

    usage_detail = (
        f"本周已用 {_format_budget_amount(weekly_used_usd)} / "
        f"{_format_budget_amount(weekly_limit_usd)}，"
        f"还剩 {_format_budget_amount(weekly_remaining_usd)}。"
    )
    if weekly_runs_text:
        usage_detail += f" 按基础档还够 {weekly_runs_text}。"

    reset_windows: list[str] = []
    if reset_day_text:
        reset_windows.append(f"今天窗 {reset_day_text}")
    if reset_week_text:
        reset_windows.append(f"本周窗 {reset_week_text}")
    reset_windows_text = "；".join(reset_windows)

    if blocked:
        usage_hint = (
            f"{reset_windows_text} 重置。"
            if reset_windows
            else "对应预算窗重置后会自动恢复。"
        )
    elif not remaining_allows_full_base_run and remaining_shortfall_usd > 1e-6:
        usage_hint = (
            f"现在剩余额度连一整轮基础档都不够，还差 "
            f"{_format_budget_amount(remaining_shortfall_usd)}。"
        )
        if reset_windows:
            usage_hint += f"{reset_windows_text} 重置。"
    elif usage_tone != "ok":
        usage_hint = (
            f"离硬闸不远了。{reset_windows_text} 重置。"
            if reset_windows
            else "离硬闸不远了，预算窗跨天 / 跨周会自动重置。"
        )
    else:
        usage_hint = (
            f"{reset_windows_text} 重置。"
            if reset_windows
            else "预算窗跨天 / 跨周会自动重置；重置后气泡里也会给一条回执。"
        )

    idle_detail_lines = [
        f"原始空闲: {_format_budget_duration(raw_idle_seconds)}",
        f"挂起折算: {_format_budget_duration(suspended_idle_seconds)}",
        f"按折后空闲: {_format_budget_duration(folded_idle_seconds)}",
    ]
    if idle_throttle_reason:
        idle_detail_lines.insert(0, f"当前判定: {idle_throttle_reason}")

    tool_risk_summary_parts: list[str] = []
    tool_risk_detail_lines: list[str] = []
    for quota in tool_risk_quotas:
        label = str(quota.get("label") or "").strip()
        limit = max(0, int(_float_or_none(quota.get("limit")) or 0))
        description = str(quota.get("description") or "").strip()
        examples = str(quota.get("examples") or "").strip()
        if label and limit > 0:
            tool_risk_summary_parts.append(f"{label} {limit} 次")
        line_parts = []
        if label and limit > 0:
            line_parts.append(f"{label}: {limit} 次")
        if description:
            line_parts.append(description)
        if examples:
            line_parts.append(f"例子: {examples}")
        if line_parts:
            tool_risk_detail_lines.append("；".join(line_parts))

    memory_budget_summary = ""
    if memory_budget_label and memory_budget_max_items > 0:
        factor_percent = int(round(memory_budget_factor * 100))
        memory_budget_summary = (
            f"若命中长期记忆，会走{memory_budget_label}档："
            f"最多带 {memory_budget_max_items} 条事实，"
            f"记忆预算系数 {factor_percent}%。"
        )
    elif memory_budget_label:
        memory_budget_summary = f"若命中长期记忆，会走{memory_budget_label}档。"

    memory_budget_detail = ""
    if memory_budget_clip_chars > 0:
        memory_budget_detail = f"单条事实上云前会先压到约 {memory_budget_clip_chars} 字。"
    if memory_budget_reasons:
        reason_text = "；".join(memory_budget_reasons)
        if memory_budget_detail:
            memory_budget_detail = f"{memory_budget_detail} {reason_text}"
        else:
            memory_budget_detail = reason_text

    cards = [
        {
            "tone": "ok",
            "title": "当前档位",
            "badge": mode_label,
            "summary": (
                f"基础单轮上限 {_format_budget_amount(per_run_limit_usd)}；"
                f"日 / 周硬闸 {_format_budget_amount(daily_limit_usd)} / "
                f"{_format_budget_amount(weekly_limit_usd)}。"
            ),
            "detail": mode_description or "这个档位决定基础单轮预算和日 / 周硬闸。",
            "hint": "这是起始预算；闲时折算和剩余额度还会继续把它往下压。",
        },
        {
            "tone": run_tone,
            "title": "这轮会跑到哪",
            "badge": run_badge,
            "summary": run_summary,
            "detail": run_detail,
            "hint": run_hint,
        },
        {
            "tone": usage_tone,
            "title": "预算窗",
            "badge": usage_badge,
            "summary": usage_summary,
            "detail": usage_detail,
            "hint": usage_hint,
        },
        {
            "tone": idle_tone,
            "title": "闲时折算",
            "badge": stage_label,
            "summary": (
                f"当前闲时阶段会按 {factor_percent}% 计算单轮预算。"
                if idle_throttle_stage != "active"
                else "最近刚有交互，当前没有因为闲时额外收紧。"
            ),
            "detail": "\n".join(idle_detail_lines),
            "hint": f"{stage_hint} 睡眠 / 锁屏等挂起时长只按 20% 计入。",
        },
        {
            "tone": (
                "warning"
                if blocked or not remaining_allows_full_base_run or idle_tone != "ok"
                else "ok"
            ),
            "title": "恢复节点",
            "badge": "看这里",
            "summary": (
                f"{reset_windows_text} 重置。"
                if reset_windows
                else "预算窗会按本地时间跨天 / 跨周自动重置。"
            ),
            "detail": (
                "闲时收紧不用等到重置；只要点一下、说一句，单轮上限就会先回到活跃档。"
                if idle_throttle_stage != "active"
                else "现在已经是活跃档；如果之后久挂不动，会再进入闲时 / 离开 / 停放三档。"
            ),
            "hint": (
                "被日 / 周硬闸拦住时，点击一下只能解除闲时收紧，不能跳过预算窗。"
                if blocked or not remaining_allows_full_base_run
                else "这张卡用来区分：哪些收紧是立刻能恢复的，哪些要等预算窗到点。"
            ),
        },
        {
            "tone": "ok",
            "title": "工具风险配额",
            "badge": "单轮护栏",
            "summary": (
                "；".join(tool_risk_summary_parts)
                if tool_risk_summary_parts
                else "当前还没有工具风险配额说明。"
            ),
            "detail": (
                "\n".join(tool_risk_detail_lines)
                if tool_risk_detail_lines
                else "工具会按风险分成几档，越高风险单轮能试的次数越少。"
            ),
            "hint": "这是每一轮对话里的工具次数护栏，不是按天累计的美元预算。",
        },
        {
            "tone": "warning" if memory_budget_label and memory_budget_factor < 1.0 else "ok",
            "title": "记忆省预算档",
            "badge": memory_budget_label or "未设置",
            "summary": (
                memory_budget_summary
                or "命中长期记忆时，会优先只带最相关的几条事实。"
            ),
            "detail": (
                memory_budget_detail
                or "这层策略只影响长期记忆上送的轻重，不影响本地记忆文件本身。"
            ),
            "hint": "命中 1 条短事实时一般不会额外压预算；多条记忆、谨慎档或预算偏紧时才会更明显地收一层。",
        },
    ]

    return {
        "status_text": status_text,
        "meta_text": meta_text,
        "cards": cards,
    }


def _build_budget_status_view_en(snapshot: dict[str, object]) -> dict[str, object]:
    normalized = dict(snapshot or {})
    mode = normalize_budget_mode(str(normalized.get("mode") or "normal"))
    mode_label = _localized_budget_mode_label(mode, ui_language="en-US")
    mode_description = _localized_budget_mode_description(mode, ui_language="en-US")

    per_run_limit_usd = _float_or_none(normalized.get("per_run_limit_usd"))
    effective_max_budget_usd = _float_or_none(
        normalized.get("effective_max_budget_usd")
    )
    daily_limit_usd = _float_or_none(normalized.get("daily_limit_usd"))
    daily_used_usd = _float_or_none(normalized.get("daily_used_usd")) or 0.0
    daily_remaining_usd = _float_or_none(normalized.get("daily_remaining_usd"))
    weekly_limit_usd = _float_or_none(normalized.get("weekly_limit_usd"))
    weekly_used_usd = _float_or_none(normalized.get("weekly_used_usd")) or 0.0
    weekly_remaining_usd = _float_or_none(normalized.get("weekly_remaining_usd"))
    raw_idle_seconds = _float_or_none(normalized.get("raw_idle_seconds")) or 0.0
    suspended_idle_seconds = (
        _float_or_none(normalized.get("suspended_idle_seconds")) or 0.0
    )
    folded_idle_seconds = (
        _float_or_none(normalized.get("folded_idle_seconds")) or 0.0
    )
    idle_throttle_factor = _float_or_none(normalized.get("idle_throttle_factor")) or 1.0
    idle_throttle_stage = str(normalized.get("idle_throttle_stage") or "active").strip() or "active"
    idle_throttle_reason = str(normalized.get("idle_throttle_reason") or "").strip()
    daily_pressure_level = str(normalized.get("daily_pressure_level") or "ok").strip()
    weekly_pressure_level = str(normalized.get("weekly_pressure_level") or "ok").strip()
    daily_base_runs_left = _float_or_none(normalized.get("daily_base_runs_left"))
    weekly_base_runs_left = _float_or_none(normalized.get("weekly_base_runs_left"))
    remaining_allows_full_base_run = bool(
        normalized.get("remaining_allows_full_base_run", True)
    )
    remaining_shortfall_usd = (
        _float_or_none(normalized.get("remaining_shortfall_usd")) or 0.0
    )
    next_daily_reset_at = _float_or_none(normalized.get("next_daily_reset_at")) or 0.0
    next_weekly_reset_at = _float_or_none(normalized.get("next_weekly_reset_at")) or 0.0
    tool_risk_quotas = [
        dict(item)
        for item in (normalized.get("tool_risk_quotas") or [])
        if isinstance(item, dict)
    ]
    memory_budget_tier = str(normalized.get("memory_budget_tier") or "compact").strip().lower() or "compact"
    memory_budget_max_items = max(
        0,
        int(_float_or_none(normalized.get("memory_budget_max_items")) or 0),
    )
    memory_budget_clip_chars = max(
        0,
        int(_float_or_none(normalized.get("memory_budget_clip_chars")) or 0),
    )
    memory_budget_factor = _float_or_none(normalized.get("memory_budget_factor")) or 1.0
    blocked = bool(normalized.get("blocked"))
    blocked_scope = str(normalized.get("blocked_scope") or "").strip()

    stage_label = _localized_budget_stage_label(idle_throttle_stage, ui_language="en-US")
    stage_hint = _localized_budget_stage_hint(idle_throttle_stage, ui_language="en-US")
    factor_percent = max(0, int(round(idle_throttle_factor * 100)))
    blocked_scope_label = "this week" if blocked_scope == "week" else "today"
    tightened = bool(
        per_run_limit_usd is not None
        and effective_max_budget_usd is not None
        and effective_max_budget_usd < per_run_limit_usd - 1e-6
    )

    tighten_reasons: list[str] = []
    if idle_throttle_factor < 1.0 - 1e-6:
        tighten_reason_label = idle_throttle_reason or stage_label
        tighten_reasons.append(f"{tighten_reason_label} at {factor_percent}%")
    if (
        per_run_limit_usd is not None
        and daily_remaining_usd is not None
        and daily_remaining_usd < per_run_limit_usd - 1e-6
    ):
        runs_left = _format_budget_runs_left(daily_base_runs_left)
        if runs_left:
            tighten_reasons.append(f"today only has {runs_left} left at the base tier")
        else:
            tighten_reasons.append(
                f"today only has {_format_budget_amount(daily_remaining_usd)} left"
            )
    if (
        per_run_limit_usd is not None
        and weekly_remaining_usd is not None
        and weekly_remaining_usd < per_run_limit_usd - 1e-6
    ):
        runs_left = _format_budget_runs_left(weekly_base_runs_left)
        if runs_left:
            tighten_reasons.append(f"this week only has {runs_left} left at the base tier")
        else:
            tighten_reasons.append(
                f"this week only has {_format_budget_amount(weekly_remaining_usd)} left"
            )
    if not remaining_allows_full_base_run and remaining_shortfall_usd > 1e-6:
        tighten_reasons.append(
            f"another {_format_budget_amount(remaining_shortfall_usd)} is needed for one full base-tier run"
        )

    summary_text = str(normalized.get("summary") or "").strip()
    if not summary_text:
        summary_text = (
            f"Today {_format_budget_amount(daily_used_usd)} / {_format_budget_amount(daily_limit_usd)}; "
            f"week {_format_budget_amount(weekly_used_usd)} / {_format_budget_amount(weekly_limit_usd)}"
        )

    daily_ratio = _budget_remaining_ratio(daily_limit_usd, daily_remaining_usd)
    weekly_ratio = _budget_remaining_ratio(weekly_limit_usd, weekly_remaining_usd)
    usage_tone = (
        "error"
        if blocked
        else _budget_pressure_tone(daily_pressure_level, weekly_pressure_level)
    )
    run_tone = "error" if blocked else "warning" if tightened else "ok"
    idle_tone = "warning" if idle_throttle_stage != "active" else "ok"
    reset_day_text = _format_budget_reset_at(next_daily_reset_at)
    reset_week_text = _format_budget_reset_at(next_weekly_reset_at)

    if blocked:
        status_text = f"The {blocked_scope_label} budget hard gate is already hit. {summary_text}."
        if blocked_scope == "week" and reset_week_text:
            meta_text = (
                f"New runs are blocked for now. The earliest automatic reset is the weekly window at {reset_week_text}, "
                "or you can raise the budget mode in Setup."
            )
        elif reset_day_text:
            meta_text = (
                f"New runs are blocked for now. The earliest automatic reset is the daily window at {reset_day_text}, "
                "or you can raise the budget mode in Setup."
            )
        else:
            meta_text = "New runs are blocked for now. Wait for the budget window to reset, or raise the budget mode in Setup."
    elif tightened and not remaining_allows_full_base_run:
        status_text = (
            f"This run is tighter than the base tier, and the remaining budget is not enough for one full base-tier run. {summary_text}."
        )
        meta_text = (
            f"The main pressure is: {'; '.join(tighten_reasons)}."
            if tighten_reasons
            else "There is not enough remaining budget for a full base-tier run."
        )
    elif tightened:
        status_text = f"This run is tighter than the base tier. {summary_text}."
        meta_text = (
            f"The main pressure is: {'; '.join(tighten_reasons)}."
            if tighten_reasons
            else "The per-run cap is being tightened by idle throttling or low daily / weekly headroom."
        )
    elif usage_tone != "ok":
        status_text = f"The session is still inside budget, but daily / weekly headroom is getting tight. {summary_text}."
        budget_run_lines: list[str] = []
        daily_runs_text = _format_budget_runs_left(daily_base_runs_left)
        weekly_runs_text = _format_budget_runs_left(weekly_base_runs_left)
        if daily_runs_text:
            budget_run_lines.append(f"today still covers {daily_runs_text} at the base tier")
        elif daily_ratio is not None:
            budget_run_lines.append(f"today still has about {int(round(daily_ratio * 100))}% left")
        if weekly_runs_text:
            budget_run_lines.append(f"this week still covers {weekly_runs_text} at the base tier")
        elif weekly_ratio is not None:
            budget_run_lines.append(f"this week still has about {int(round(weekly_ratio * 100))}% left")
        meta_text = "; ".join(budget_run_lines) + "." if budget_run_lines else "The budget is not blocked yet, but it is close to the hard gate."
    else:
        status_text = f"The session is still inside budget. {summary_text}."
        meta_text = "The longer the app stays idle, the more conservative the per-run cap becomes. Daily and weekly windows reset automatically."

    if blocked:
        run_summary = f"No new run will start right now because the {blocked_scope_label} budget is exhausted."
        run_detail = (
            f"Base per-run cap {_format_budget_amount(per_run_limit_usd)}; "
            f"effective cap {_format_budget_amount(effective_max_budget_usd)}."
        )
        if blocked_scope == "week" and reset_week_text:
            run_hint = (
                f"Access opens again after the weekly reset at {reset_week_text}, "
                "or sooner if you switch to a higher budget mode in Setup."
            )
        elif reset_day_text:
            run_hint = (
                f"Access opens again after the daily reset at {reset_day_text}, "
                "or sooner if you switch to a higher budget mode in Setup."
            )
        else:
            run_hint = "Access opens again after the budget window resets, or by switching to a higher budget mode in Setup."
        run_badge = "Blocked"
    elif tightened:
        run_summary = (
            f"Effective per-run cap {_format_budget_amount(effective_max_budget_usd)} "
            f"(base {_format_budget_amount(per_run_limit_usd)})."
        )
        run_detail = (
            f"Pressure sources: {'; '.join(tighten_reasons)}."
            if tighten_reasons
            else "This run is being tightened beyond the base tier."
        )
        if not remaining_allows_full_base_run and remaining_shortfall_usd > 1e-6:
            run_hint = (
                "Idle throttling clears as soon as the app becomes active again, but the budget window is still "
                f"short by {_format_budget_amount(remaining_shortfall_usd)} for one full base-tier run."
            )
        else:
            run_hint = "This cap loosens again after fresh activity or after the budget window resets."
        run_badge = "Tightened"
    else:
        run_summary = f"Effective per-run cap {_format_budget_amount(effective_max_budget_usd)}."
        run_detail = (
            f"Base per-run cap {_format_budget_amount(per_run_limit_usd)}; no extra tightening is active right now."
        )
        run_hint = "As long as daily and weekly headroom is sufficient, each run uses the current tier as-is."
        run_badge = "Normal"

    if blocked:
        usage_badge = "Blocked"
    elif not remaining_allows_full_base_run:
        usage_badge = "Short"
    elif usage_tone == "error":
        usage_badge = "Critical"
    elif usage_tone == "warning":
        usage_badge = "Tight"
    else:
        usage_badge = "Stable"

    daily_runs_text = _format_budget_runs_left(daily_base_runs_left)
    weekly_runs_text = _format_budget_runs_left(weekly_base_runs_left)
    usage_summary = (
        f"Today used {_format_budget_amount(daily_used_usd)} / {_format_budget_amount(daily_limit_usd)}, "
        f"with {_format_budget_amount(daily_remaining_usd)} left."
    )
    if daily_runs_text:
        usage_summary += f" Base tier still covers {daily_runs_text}."

    usage_detail = (
        f"This week used {_format_budget_amount(weekly_used_usd)} / {_format_budget_amount(weekly_limit_usd)}, "
        f"with {_format_budget_amount(weekly_remaining_usd)} left."
    )
    if weekly_runs_text:
        usage_detail += f" Base tier still covers {weekly_runs_text}."

    reset_windows: list[str] = []
    if reset_day_text:
        reset_windows.append(f"daily window {reset_day_text}")
    if reset_week_text:
        reset_windows.append(f"weekly window {reset_week_text}")
    reset_windows_text = "; ".join(reset_windows)

    if blocked:
        usage_hint = (
            f"Resets at {reset_windows_text}."
            if reset_windows
            else "Access returns automatically after the matching budget window resets."
        )
    elif not remaining_allows_full_base_run and remaining_shortfall_usd > 1e-6:
        usage_hint = (
            f"The remaining budget is short by {_format_budget_amount(remaining_shortfall_usd)} for one full base-tier run."
        )
        if reset_windows:
            usage_hint += f" Resets at {reset_windows_text}."
    elif usage_tone != "ok":
        usage_hint = (
            f"The hard gate is getting close. Resets at {reset_windows_text}."
            if reset_windows
            else "The hard gate is getting close; the daily and weekly windows reset automatically."
        )
    else:
        usage_hint = (
            f"Resets at {reset_windows_text}."
            if reset_windows
            else "Daily and weekly windows reset automatically, and the bubble also shows a small receipt when they do."
        )

    idle_detail_lines = [
        f"Raw idle: {_format_budget_duration(raw_idle_seconds)}",
        f"Suspended fold-in: {_format_budget_duration(suspended_idle_seconds)}",
        f"Folded idle used for policy: {_format_budget_duration(folded_idle_seconds)}",
    ]
    if idle_throttle_reason:
        idle_detail_lines.insert(0, f"Current reason: {idle_throttle_reason}")

    tool_risk_summary_parts: list[str] = []
    tool_risk_detail_lines: list[str] = []
    for quota in tool_risk_quotas:
        level = str(quota.get("level") or "").strip().lower()
        label = _localized_tool_risk_label(level, ui_language="en-US")
        limit = max(0, int(_float_or_none(quota.get("limit")) or 0))
        description = _localized_tool_risk_description(level, ui_language="en-US")
        examples = str(quota.get("examples") or "").strip()
        if label and limit > 0:
            tool_risk_summary_parts.append(f"{label} {limit}")
        line_parts = []
        if label and limit > 0:
            line_parts.append(f"{label}: {limit}")
        if description:
            line_parts.append(description)
        if examples:
            line_parts.append(f"Examples: {examples}")
        if line_parts:
            tool_risk_detail_lines.append("; ".join(line_parts))

    memory_budget_label = _localized_memory_tier_label(
        memory_budget_tier,
        ui_language="en-US",
    )
    memory_factor_percent = int(round(memory_budget_factor * 100))
    memory_budget_summary = (
        f"When long-term memory is used, this tier brings up to {memory_budget_max_items} facts and keeps a {memory_factor_percent}% memory-budget factor."
        if memory_budget_max_items > 0
        else "When long-term memory is used, only the most relevant facts are sent."
    )
    memory_budget_detail = (
        f"Each fact is clipped to about {memory_budget_clip_chars} characters before going to the model."
        if memory_budget_clip_chars > 0
        else "This layer only changes how much memory context is sent upstream; it does not change the local memory file itself."
    )

    cards = [
        {
            "tone": "ok",
            "title": "Current Tier",
            "badge": mode_label,
            "summary": (
                f"Base per-run cap {_format_budget_amount(per_run_limit_usd)}; "
                f"daily / weekly hard gates {_format_budget_amount(daily_limit_usd)} / "
                f"{_format_budget_amount(weekly_limit_usd)}."
            ),
            "detail": mode_description or "This tier sets the base per-run cap plus daily and weekly hard gates.",
            "hint": "This is only the starting point; idle throttling and low headroom can still push it down.",
        },
        {
            "tone": run_tone,
            "title": "Where This Run Lands",
            "badge": run_badge,
            "summary": run_summary,
            "detail": run_detail,
            "hint": run_hint,
        },
        {
            "tone": usage_tone,
            "title": "Budget Windows",
            "badge": usage_badge,
            "summary": usage_summary,
            "detail": usage_detail,
            "hint": usage_hint,
        },
        {
            "tone": idle_tone,
            "title": "Idle Throttling",
            "badge": stage_label,
            "summary": (
                f"This idle stage applies a {factor_percent}% per-run budget."
                if idle_throttle_stage != "active"
                else "There was recent activity, so no extra idle tightening is active right now."
            ),
            "detail": "\n".join(idle_detail_lines),
            "hint": f"{stage_hint} Sleep / lock-screen time only counts at 20%.",
        },
        {
            "tone": (
                "warning"
                if blocked or not remaining_allows_full_base_run or idle_tone != "ok"
                else "ok"
            ),
            "title": "Recovery Points",
            "badge": "Watch",
            "summary": (
                f"Resets at {reset_windows_text}."
                if reset_windows
                else "Daily and weekly windows reset automatically in local time."
            ),
            "detail": (
                "Idle tightening does not need a reset. One click or one new message brings the per-run cap back to the active tier first."
                if idle_throttle_stage != "active"
                else "The app is already in the active tier. If it sits for a long time again, it moves through idle / away / parked stages."
            ),
            "hint": (
                "If a daily or weekly hard gate is hit, one click only clears idle tightening. It does not bypass the budget window."
                if blocked or not remaining_allows_full_base_run
                else "This card separates what can recover immediately from what must wait for the budget window."
            ),
        },
        {
            "tone": "ok",
            "title": "Tool Risk Quotas",
            "badge": "Per Run",
            "summary": (
                "; ".join(tool_risk_summary_parts)
                if tool_risk_summary_parts
                else "No tool-risk quota summary is available yet."
            ),
            "detail": (
                "\n".join(tool_risk_detail_lines)
                if tool_risk_detail_lines
                else "Tools are grouped by risk; higher-risk tools get fewer attempts in a single run."
            ),
            "hint": "This is a per-run tool guardrail, not a daily USD budget.",
        },
        {
            "tone": "warning" if memory_budget_factor < 1.0 else "ok",
            "title": "Memory Saver Tier",
            "badge": memory_budget_label,
            "summary": memory_budget_summary,
            "detail": memory_budget_detail,
            "hint": "A single short fact usually does not tighten budget further; it becomes more visible with many memories, cautious mode, or low headroom.",
        },
    ]

    return {
        "status_text": status_text,
        "meta_text": meta_text,
        "cards": cards,
    }


def _runtime_path_from_env(env_var: str, default_path: Path) -> Path:
    override = str(os.environ.get(env_var) or "").strip()
    if override:
        return Path(override).expanduser()
    return default_path


def _format_runtime_path(path: Path) -> str:
    try:
        normalized = path.expanduser().resolve()
    except OSError:
        normalized = path.expanduser()

    home = str(Path.home())
    text = str(normalized)
    if home and text.startswith(home):
        return "~" + text[len(home) :]
    return text


def _compact_detail_text(text: str, limit: int = 160) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _memory_key_source_from_path(path: Path) -> str:
    override = str(os.environ.get(MEMORY_KEY_ENV_VAR) or "").strip()
    if override:
        return "环境变量"

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raw = ""

    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            if str(payload.get("format") or "").strip() != "fernet":
                return "旧格式"
            key_source = str(payload.get("key_source") or "").strip().lower()
            if key_source == "keychain":
                return "系统钥匙串"
            if key_source == "sidecar":
                return "本地 .key 文件"
            if key_source == "env":
                return "环境变量"

    mode = str(os.environ.get(MEMORY_KEYCHAIN_MODE_ENV_VAR) or "").strip().lower()
    if sys.platform == "darwin":
        if mode in {"0", "false", "off", "no", "sidecar"}:
            return "本地 .key 文件"
        if mode in {"1", "true", "on", "yes", "keychain"}:
            return "系统钥匙串"
        try:
            if path.expanduser().resolve() == DEFAULT_MEMORY_STATE_PATH.resolve():
                return "系统钥匙串"
        except OSError:
            if path.expanduser() == DEFAULT_MEMORY_STATE_PATH:
                return "系统钥匙串"

    return "本地 .key 文件"


def _privacy_event_tone(event: ChatTraceEvent | None) -> str:
    if event is None:
        return "ok"
    title = str(event.title or "")
    detail = str(event.detail or "")
    if "留在本机" in title or "留在本机" in detail or "拦下" in detail:
        return "warning"
    return "ok"


def _recent_privacy_event_lines(events: list[ChatTraceEvent]) -> list[str]:
    lines: list[str] = []
    for event in reversed(events[-3:]):
        stamp = time.strftime("%H:%M:%S", time.localtime(event.created_at))
        block_lines = [f"{stamp} {event.title}"]
        for detail_line in str(event.detail or "").splitlines()[:4]:
            cleaned = detail_line.strip()
            if not cleaned:
                continue
            block_lines.append(f"  {cleaned}")
        lines.append("\n".join(block_lines))
    return lines


def _build_privacy_boundary_view(
    *,
    app_snapshot: AppStateSnapshot,
    api_status: ApiKeyStatus,
    api_key_path: Path,
    app_state_path: Path,
    memory_state_path: Path,
    memory_item_count: int,
    recent_events: list[ChatTraceEvent],
    language: str = "zh-CN",
) -> dict[str, object]:
    if _ui_uses_english(language):
        return _build_privacy_boundary_view_en(
            app_snapshot=app_snapshot,
            api_status=api_status,
            api_key_path=api_key_path,
            app_state_path=app_state_path,
            memory_state_path=memory_state_path,
            memory_item_count=memory_item_count,
            recent_events=recent_events,
        )
    memory_path_text = _format_runtime_path(memory_state_path)
    app_state_path_text = _format_runtime_path(app_state_path)
    api_key_path_text = _format_runtime_path(api_key_path)
    memory_key_source = _memory_key_source_from_path(memory_state_path)

    if api_status.source == "keychain":
        api_storage_summary = "Claude API key 当前保存在系统钥匙串。"
    elif api_status.source == "file":
        api_storage_summary = "Claude API key 当前保存在本机私有文件。"
    elif api_status.source == "env":
        api_storage_summary = "Claude API key 当前直接从环境变量读取。"
    else:
        api_storage_summary = "Claude API key 还没有配置。"

    recent_privacy_events = [
        event for event in recent_events if str(getattr(event, "kind", "")).strip() == "privacy"
    ]
    last_event = recent_privacy_events[-1] if recent_privacy_events else None
    last_event_tone = _privacy_event_tone(last_event)

    if last_event is None:
        status_text = "这里会说明什么内容可能离机，什么默认留在本机。"
        meta_text = (
            "一旦命中隐私边界，思考流里会留下“隐私”事件；这里也会记最近几次原因和下一步建议。"
        )
    else:
        status_text = f"最近一次隐私动作: {last_event.title}。"
        meta_text = (
            str(last_event.detail or "").strip()
            if str(last_event.detail or "").strip()
            else "这次没有附带更细的说明。"
        )

    local_detail_lines = [
        f"长期记忆: {memory_item_count} 条；本地路径 {memory_path_text}；加密密钥来源 {memory_key_source}。",
        f"本机偏好: {app_state_path_text}（称呼 / 预算档位 / 自动隐藏）。",
    ]
    if api_status.source == "file":
        local_detail_lines.insert(1, f"API key 文件: {api_key_path_text}。")

    recent_detail_lines = _recent_privacy_event_lines(recent_privacy_events)
    if not recent_detail_lines:
        recent_detail = "还没有命中过隐私边界。等下一次触发脱敏或阻断时，这里会留下解释。"
    else:
        recent_detail = "\n\n".join(recent_detail_lines)

    cards = [
        {
            "tone": "ok",
            "title": "可能会离机",
            "badge": "云端处理",
            "summary": "普通对话、工具摘要、命中的非高敏长期记忆，可能发给云端 Claude。",
            "detail": "这样她才能结合上下文继续聊天、调工具、把结果组织成回复。",
            "hint": "低风险内容也不是原样直出；像家目录路径这类信息会先做归一或脱敏。",
        },
        {
            "tone": "warning",
            "title": "默认留在本机",
            "badge": "默认阻断",
            "summary": "密码、密钥、Token、证件号、银行卡/账户号等高敏内容默认不上云。",
            "detail": "输入、工具结果、命中的长期记忆都会先过这一层；命中后要么脱敏，要么整段留在本机。",
            "hint": "读邮件和工具返回值也走同一条边界，不是只对聊天输入生效。",
        },
        {
            "tone": "ok",
            "title": "工具执行前",
            "badge": "先确认",
            "summary": "发邮件、粘贴、按键、创建或删除日历/提醒等写操作，会先在本机弹确认。",
            "detail": "你可以临时允许，也可以记住到本次会话；右键菜单还能随时清掉已记住授权。",
            "hint": "这道确认发生在工具真正执行前，不是执行完了才补解释。",
        },
        {
            "tone": "ok" if app_snapshot.data_boundary_acknowledged else "warning",
            "title": "本地保存",
            "badge": "已确认" if app_snapshot.data_boundary_acknowledged else "待确认",
            "summary": api_storage_summary,
            "detail": "\n".join(local_detail_lines),
            "hint": (
                f"长期记忆只能逐条编辑或删除；自动隐藏当前为 {'开' if app_snapshot.auto_hide_on_sensitive_scene else '关'}。"
            ),
        },
        {
            "tone": last_event_tone,
            "title": "最近一次边界动作",
            "badge": (
                time.strftime("%H:%M:%S", time.localtime(last_event.created_at))
                if last_event is not None
                else "暂无"
            ),
            "summary": (
                str(last_event.title or "").strip()
                if last_event is not None
                else "还没有命中过隐私边界。"
            ),
            "detail": recent_detail,
            "hint": "想看更细的过程，打开 thought trace；里面会用“隐私”标签逐条记。",
        },
    ]

    return {
        "status_text": status_text,
        "meta_text": meta_text,
        "cards": cards,
    }


def _build_privacy_boundary_view_en(
    *,
    app_snapshot: AppStateSnapshot,
    api_status: ApiKeyStatus,
    api_key_path: Path,
    app_state_path: Path,
    memory_state_path: Path,
    memory_item_count: int,
    recent_events: list[ChatTraceEvent],
) -> dict[str, object]:
    memory_path_text = _format_runtime_path(memory_state_path)
    app_state_path_text = _format_runtime_path(app_state_path)
    api_key_path_text = _format_runtime_path(api_key_path)
    memory_key_source = _memory_key_source_from_path(memory_state_path)

    if api_status.source == "keychain":
        api_storage_summary = "The Claude API key is currently stored in Keychain."
    elif api_status.source == "file":
        api_storage_summary = "The Claude API key is currently stored in a local private file."
    elif api_status.source == "env":
        api_storage_summary = "The Claude API key is currently read directly from the environment."
    else:
        api_storage_summary = "The Claude API key is not configured yet."

    recent_privacy_events = [
        event for event in recent_events if str(getattr(event, "kind", "")).strip() == "privacy"
    ]
    last_event = recent_privacy_events[-1] if recent_privacy_events else None
    last_event_tone = _privacy_event_tone(last_event)

    if last_event is None:
        status_text = "This panel explains what may leave the device and what stays local by default."
        meta_text = (
            "When the privacy boundary masks or blocks something, thought trace keeps a privacy event and this panel also stores the latest reason plus the next suggested step."
        )
    else:
        status_text = f"Latest privacy action: {last_event.title}."
        meta_text = (
            str(last_event.detail or "").strip()
            if str(last_event.detail or "").strip()
            else "No extra detail was attached to that event."
        )

    local_detail_lines = [
        f"Long-term memory: {memory_item_count} items; local path {memory_path_text}; encryption key source {memory_key_source}.",
        f"Local preferences: {app_state_path_text} (addressing name / reply language / interface language / budget / auto-hide).",
    ]
    if api_status.source == "file":
        local_detail_lines.insert(1, f"API key file: {api_key_path_text}.")

    recent_detail_lines = _recent_privacy_event_lines(recent_privacy_events)
    if not recent_detail_lines:
        recent_detail = "The privacy boundary has not fired yet. When masking or blocking happens, the explanation will be recorded here."
    else:
        recent_detail = "\n\n".join(recent_detail_lines)

    cards = [
        {
            "tone": "ok",
            "title": "May Leave the Device",
            "badge": "Cloud",
            "summary": "Regular chat, tool summaries, and matched non-sensitive long-term memory can be sent to Claude in the cloud.",
            "detail": "That is how the assistant keeps context, calls tools, and shapes the final reply.",
            "hint": "Even lower-risk content is not sent raw every time; local paths and similar details are normalized or masked first.",
        },
        {
            "tone": "warning",
            "title": "Stays Local by Default",
            "badge": "Blocked",
            "summary": "Passwords, keys, tokens, IDs, bank-card or account numbers, and similar sensitive values stay off-cloud by default.",
            "detail": "Inputs, tool outputs, and matched long-term memory all pass through this layer first. A hit is either masked or kept fully local.",
            "hint": "Mail reads and tool outputs pass through the same boundary; it is not only for chat input.",
        },
        {
            "tone": "ok",
            "title": "Before Tools Run",
            "badge": "Confirm",
            "summary": "Writes such as sending mail, pasting, key presses, or creating / deleting calendar and reminder items ask for confirmation locally first.",
            "detail": "You can allow one time, or remember it for the current session; the context menu can clear remembered approvals later.",
            "hint": "The confirmation happens before the tool actually runs, not afterward.",
        },
        {
            "tone": "ok" if app_snapshot.data_boundary_acknowledged else "warning",
            "title": "Local Storage",
            "badge": "Confirmed" if app_snapshot.data_boundary_acknowledged else "Pending",
            "summary": api_storage_summary,
            "detail": "\n".join(local_detail_lines),
            "hint": (
                f"Long-term memory can only be edited or deleted item by item; auto-hide is currently {'on' if app_snapshot.auto_hide_on_sensitive_scene else 'off'}."
            ),
        },
        {
            "tone": last_event_tone,
            "title": "Latest Boundary Event",
            "badge": (
                time.strftime("%H:%M:%S", time.localtime(last_event.created_at))
                if last_event is not None
                else "None"
            ),
            "summary": (
                str(last_event.title or "").strip()
                if last_event is not None
                else "The privacy boundary has not been triggered yet."
            ),
            "detail": recent_detail,
            "hint": 'For a more detailed trail, open thought trace; privacy events are tagged there one by one.',
        },
    ]

    return {
        "status_text": status_text,
        "meta_text": meta_text,
        "cards": cards,
    }


_AUTO_DND_REASON_LABELS_ZH = {
    "system_focus": "系统专注模式",
    "screen_share": "共享/演示场景",
    "camera_active": "摄像头使用中",
    "presentation_focus": "演示/录屏场景",
    "meeting_focus": "会议/通话场景",
    "frontmost_fullscreen": "前台全屏场景",
}

_AUTO_DND_REASON_LABELS_EN = {
    "system_focus": "System Focus",
    "screen_share": "Sharing / Presenting",
    "camera_active": "Camera In Use",
    "presentation_focus": "Presentation / Recording",
    "meeting_focus": "Meeting / Call",
    "frontmost_fullscreen": "Frontmost Fullscreen",
}


def _localized_auto_dnd_reason_label(
    reason_key: str,
    fallback: str,
    *,
    ui_language: str,
) -> str:
    normalized = str(reason_key or "").strip()
    fallback_text = str(fallback or "").strip()
    if _ui_uses_english(ui_language):
        return _AUTO_DND_REASON_LABELS_EN.get(normalized, fallback_text or "Background Detection")
    return _AUTO_DND_REASON_LABELS_ZH.get(normalized, fallback_text or "后台场景检测")


def _localized_auto_dnd_toggle_receipt(
    enabled: bool,
    *,
    ui_language: str,
) -> str:
    if _ui_uses_english(ui_language):
        if enabled:
            return "\n".join(
                [
                    "Receipt · Auto DND Detection",
                    "Status: Enabled",
                    "Effect: Fullscreen, meeting, sharing, recording, camera, and Focus scenes will keep being watched in the background.",
                    "Note: Manual Do Not Disturb still works as a separate switch.",
                ]
            )
        return "\n".join(
            [
                "Receipt · Auto DND Detection",
                "Status: Disabled",
                "Effect: Fullscreen, meeting, sharing, recording, camera, and Focus scenes will stop muting reminders automatically.",
                "Note: Manual Do Not Disturb still works as a separate switch.",
            ]
        )
    if enabled:
        return "\n".join(
            [
                "状态回执 · 自动免打扰检测",
                "状态: 已开启",
                "影响: 全屏、会议、共享、录屏、摄像头和系统 Focus 会继续在后台监测。",
                "附记: 手动免打扰仍然可以单独开关。",
            ]
        )
    return "\n".join(
        [
            "状态回执 · 自动免打扰检测",
            "状态: 已关闭",
            "影响: 全屏、会议、共享、录屏、摄像头和系统 Focus 不会再自动静音提醒。",
            "附记: 手动免打扰仍然可以单独开关。",
        ]
    )


def _build_sprite_pack_info_view(
    sprite_pack: SpritePackBundle,
    *,
    language: str = "zh-CN",
) -> dict[str, object]:
    english = _ui_uses_english(language)
    metadata = sprite_pack.metadata
    state_names = sorted(sprite_pack.states.keys())
    fallback_lines = [
        (
            f"{state_key} <- {fallback_source}"
            if english
            else f"{state_key} <- {fallback_source}"
        )
        for state_key, fallback_source in sorted(sprite_pack.fallback_states.items())
    ]
    source_text = (
        "Legacy built-in mapping"
        if sprite_pack.source == "legacy"
        else _format_runtime_path(Path(sprite_pack.source))
    )
    tag_text = ", ".join(metadata.tags) if metadata.tags else ("none" if english else "无")
    author_text = metadata.author or ("unknown" if english else "未标注")
    description_text = metadata.description or (
        "No extra description for this pack."
        if english
        else "这个立绘包还没有额外说明。"
    )
    diagnostic = diagnose_sprite_pack(sprite_pack)
    diagnostic_tone = (
        "error"
        if diagnostic.errors
        else "warning" if diagnostic.warnings else "ok"
    )
    frame_counts_text = ", ".join(
        f"{state}:{count}" for state, count in sorted(diagnostic.frame_counts.items())
    )
    missing_text = ", ".join(diagnostic.missing_states)
    warning_text = "\n".join(diagnostic.warnings[:6])
    error_text = "\n".join(diagnostic.errors[:6])
    issue_text = "\n".join(line for line in (error_text, warning_text) if line)
    if len(diagnostic.errors) > 6 or len(diagnostic.warnings) > 6:
        issue_text += "\n..."
    if not issue_text:
        issue_text = (
            "No blank frames, missing semantic states, or suspicious mappings were found."
            if english
            else "没有发现空白帧、语义状态缺失或明显可疑映射。"
        )

    if english:
        status_text = f"Current sprite pack: {sprite_pack.name}."
        meta_text = (
            "This panel shows metadata, state coverage, fallback poses, and pack-health diagnostics."
        )
        source_badge = "Legacy" if sprite_pack.source == "legacy" else "Manifest"
        state_badge = f"{len(state_names)} poses"
        fallback_badge = (
            f"{len(fallback_lines)} fallback"
            if fallback_lines
            else "complete"
        )
        fallback_summary = (
            "Some poses are still borrowed from the default pack."
            if fallback_lines
            else "This pack provides its own visible poses without borrowing from the default pack."
        )
        fallback_detail = (
            "\n".join(fallback_lines)
            if fallback_lines
            else "No fallback poses are in use right now."
        )
        cards = [
            {
                "tone": "ok",
                "title": "Current Pack",
                "badge": sprite_pack.pack_id,
                "summary": sprite_pack.name,
                "detail": description_text,
                "hint": (
                    f"Author: {author_text}. Tags: {tag_text}."
                ),
            },
            {
                "tone": "ok",
                "title": "Source & Metadata",
                "badge": source_badge,
                "summary": (
                    f"Preview pose: {metadata.preview_pose}. Default pose: {metadata.default_pose}."
                ),
                "detail": (
                    f"Source: {source_text}\n"
                    f"Canvas: {sprite_pack.canvas_width} x {sprite_pack.canvas_height}\n"
                    f"License: {metadata.license_name or 'unspecified'}\n"
                    f"Website: {metadata.website or 'n/a'}"
                ),
                "hint": "The preview pose is only metadata right now; the maid still uses runtime state switching.",
            },
            {
                "tone": diagnostic_tone,
                "title": "Pack Health",
                "badge": "OK" if diagnostic_tone == "ok" else "Check",
                "summary": (
                    "All standard DeskMaid states are available."
                    if not diagnostic.missing_states
                    else f"Missing: {missing_text}"
                ),
                "detail": (
                    f"Expected: {', '.join(diagnostic.expected_states)}\n"
                    f"Frames: {frame_counts_text or 'none'}\n"
                    f"{issue_text}"
                ),
                "hint": "Shared mappings are allowed, but separate art makes expressions clearer.",
            },
            {
                "tone": "warning" if fallback_lines else "ok",
                "title": "State Coverage",
                "badge": state_badge,
                "summary": ", ".join(state_names) if state_names else "No visible states",
                "detail": (
                    f"{fallback_summary}\n{fallback_detail}"
                ),
                "hint": f"Fallback status: {fallback_badge}.",
            },
        ]
    else:
        status_text = f"当前立绘包: {sprite_pack.name}。"
        meta_text = "这里会说明当前立绘包的元数据、状态覆盖、fallback 和健康诊断。"
        source_badge = "legacy" if sprite_pack.source == "legacy" else "manifest"
        state_badge = f"{len(state_names)} 个状态"
        fallback_badge = (
            f"{len(fallback_lines)} 个 fallback"
            if fallback_lines
            else "覆盖完整"
        )
        fallback_summary = (
            "有些姿态还在借默认包的图。"
            if fallback_lines
            else "这个立绘包当前显示到的姿态都由自己提供，没有借默认包。"
        )
        fallback_detail = (
            "\n".join(fallback_lines)
            if fallback_lines
            else "当前没有启用 fallback 姿态。"
        )
        cards = [
            {
                "tone": "ok",
                "title": "当前立绘包",
                "badge": sprite_pack.pack_id,
                "summary": sprite_pack.name,
                "detail": description_text,
                "hint": f"作者: {author_text}。标签: {tag_text}。",
            },
            {
                "tone": "ok",
                "title": "来源与元数据",
                "badge": source_badge,
                "summary": f"预览姿态: {metadata.preview_pose}。默认姿态: {metadata.default_pose}。",
                "detail": (
                    f"来源: {source_text}\n"
                    f"画布: {sprite_pack.canvas_width} x {sprite_pack.canvas_height}\n"
                    f"许可证: {metadata.license_name or '未标注'}\n"
                    f"主页: {metadata.website or '无'}"
                ),
                "hint": "preview pose 现在还是元数据说明；真正显示哪张图仍然由运行时状态机决定。",
            },
            {
                "tone": diagnostic_tone,
                "title": "立绘包健康",
                "badge": "正常" if diagnostic_tone == "ok" else "检查",
                "summary": (
                    "DeskMaid 标准状态都可用。"
                    if not diagnostic.missing_states
                    else f"缺少: {missing_text}"
                ),
                "detail": (
                    f"期望状态: {'、'.join(diagnostic.expected_states)}\n"
                    f"帧数: {frame_counts_text or '无'}\n"
                    f"{issue_text}"
                ),
                "hint": "状态复用同一批图是允许的，但独立表情会更清楚。",
            },
            {
                "tone": "warning" if fallback_lines else "ok",
                "title": "状态覆盖",
                "badge": state_badge,
                "summary": "、".join(state_names) if state_names else "没有可见状态",
                "detail": f"{fallback_summary}\n{fallback_detail}",
                "hint": f"fallback 情况: {fallback_badge}。",
            },
        ]

    return {
        "status_text": status_text,
        "meta_text": meta_text,
        "cards": cards,
    }


def _build_outing_collection_view(
    snapshot: OutingSnapshot,
    catalog: OutingCatalog,
    *,
    language: str = "zh-CN",
) -> dict[str, object]:
    english = _ui_uses_english(language)
    collectables_by_key = {item.key: item for item in catalog.collectables}
    total_kinds_available = len(collectables_by_key)
    collected_counts = {
        str(key): max(0, int(value or 0))
        for key, value in dict(snapshot.collectable_counts).items()
        if str(key).strip() and int(value or 0) > 0
    }
    collected_known = sum(
        1 for key, count in collected_counts.items()
        if count > 0 and key in collectables_by_key
    )
    collected_items = sum(collected_counts.values())
    total_duration = _format_elapsed_duration(
        snapshot.total_outing_seconds,
        english=english,
    )
    last_kind = str(snapshot.last_result_kind or "").strip().lower()
    last_key = str(snapshot.last_result_key or "").strip()
    last_kind_label = (
        "Collectable" if last_kind == "collectable" else "Event"
    ) if english else (
        "收藏品" if last_kind == "collectable" else "见闻"
    )
    last_text = (
        f"{last_kind_label}: {last_key}" if last_key else (
            "No return record yet." if english else "还没有回程记录。"
        )
    )

    progress_badge = (
        f"{collected_known}/{total_kinds_available}"
        if total_kinds_available
        else "0/0"
    )
    if english:
        status_text = (
            f"Outing collection: {collected_known} of {total_kinds_available} known items."
        )
        meta_text = (
            "This panel shows local outing history and the collectables the maid has brought back."
        )
        cards = [
            {
                "tone": "ok",
                "title": "Outing Log",
                "badge": f"{snapshot.outings_completed}/{snapshot.outings_started}",
                "summary": (
                    f"Completed {snapshot.outings_completed} of "
                    f"{snapshot.outings_started} outings."
                ),
                "detail": (
                    f"Total time out: {total_duration}\n"
                    f"Last return: {last_text}"
                ),
                "hint": "Manual and auto-DND outings both count here once they return.",
            },
            {
                "tone": "ok" if collected_known else "warning",
                "title": "Collection Progress",
                "badge": progress_badge,
                "summary": (
                    f"{collected_items} total collectable drops across "
                    f"{collected_known} known kinds."
                ),
                "detail": (
                    "Known catalog size: "
                    f"{total_kinds_available}. Unknown legacy items are still listed below."
                ),
                "hint": "Rarer items are intentionally stingy. Annoying, but thematically correct.",
            },
        ]
    else:
        status_text = f"出门收藏: 已收集 {collected_known} / {total_kinds_available} 类。"
        meta_text = "这里会显示本机出门记录，以及她到底从外面带回了什么破烂宝贝。"
        cards = [
            {
                "tone": "ok",
                "title": "出门记录",
                "badge": f"{snapshot.outings_completed}/{snapshot.outings_started}",
                "summary": (
                    f"已完成 {snapshot.outings_completed} 次；"
                    f"累计出门 {total_duration}。"
                ),
                "detail": f"最近回程: {last_text}",
                "hint": "手动出门和自动免打扰出门，回来以后都会记在这里。",
            },
            {
                "tone": "ok" if collected_known else "warning",
                "title": "收藏进度",
                "badge": progress_badge,
                "summary": f"共拿回 {collected_items} 件，覆盖 {collected_known} 类收藏品。",
                "detail": (
                    f"当前图鉴共有 {total_kinds_available} 类。旧版本未知物品也会列在下面。"
                ),
                "hint": "稀有物品掉率故意没那么友善。不然你又要三分钟毕业。",
            },
        ]

    rarity_rank = {"epic": 0, "rare": 1, "uncommon": 2, "common": 3}
    sorted_keys = sorted(
        collected_counts,
        key=lambda key: (
            rarity_rank.get(getattr(collectables_by_key.get(key), "rarity", "common"), 9),
            -collected_counts.get(key, 0),
            getattr(collectables_by_key.get(key), "name", key),
        ),
    )
    if not sorted_keys:
        cards.append(
            {
                "tone": "warning",
                "title": "Collection Shelf" if english else "收藏架",
                "badge": "Empty" if english else "空",
                "summary": (
                    "No collectables yet."
                    if english
                    else "还没有收藏品。她不是没努力，可能只是空手回来比较符合现实。"
                ),
                "detail": (
                    "Start an outing from the context menu and wait for her to return."
                    if english
                    else "从右键菜单启动一次出门态，等她回来就有机会掉东西。"
                ),
                "hint": (
                    "Events can still happen even when no item drops."
                    if english
                    else "就算没掉物品，也可能带回一条见闻。"
                ),
            }
        )
    for key in sorted_keys:
        count = collected_counts[key]
        item = collectables_by_key.get(key)
        rarity = str(getattr(item, "rarity", "common") or "common").strip().lower()
        rarity_label = RARITY_LABELS.get(rarity, "普通")
        tone = "warning" if rarity in {"rare", "epic"} else "ok"
        if english:
            rarity_text = {
                "common": "Common",
                "uncommon": "Uncommon",
                "rare": "Rare",
                "epic": "Keepsake",
            }.get(rarity, "Common")
            title = item.name if item is not None else key
            detail = item.description if item is not None else "This item is no longer in the current catalog."
            cards.append(
                {
                    "tone": tone,
                    "title": title,
                    "badge": f"x{count}",
                    "summary": f"Rarity: {rarity_text}.",
                    "detail": detail,
                    "hint": f"Catalog key: {key}.",
                }
            )
        else:
            title = item.name if item is not None else key
            detail = item.description if item is not None else "这个东西已经不在当前图鉴里了，但记录还在。"
            cards.append(
                {
                    "tone": tone,
                    "title": title,
                    "badge": f"x{count}",
                    "summary": f"稀有度: {rarity_label}。",
                    "detail": detail,
                    "hint": f"图鉴 key: {key}。",
                }
            )

    return {
        "status_text": status_text,
        "meta_text": meta_text,
        "cards": cards,
    }


def _build_auto_dnd_status_view(
    *,
    state: AutoDoNotDisturbState,
    auto_dnd_enabled: bool,
    manual_dnd_enabled: bool,
    auto_hide_enabled: bool,
    outing_active: bool,
    language: str = "zh-CN",
) -> dict[str, object]:
    english = _ui_uses_english(language)
    detection_enabled = bool(auto_dnd_enabled)
    active = bool(detection_enabled and state.active)
    effective_dnd = bool(manual_dnd_enabled or active)
    reason_label = _localized_auto_dnd_reason_label(
        state.reason_key,
        state.reason_text,
        ui_language=language,
    )
    checked_at = _format_health_checked_at(state.updated_at)
    frontmost_name = str(state.frontmost_app_name or "").strip()
    frontmost_bundle_id = str(state.frontmost_bundle_id or "").strip()
    detail_text = str(state.detail or "").strip()
    reason_key = str(state.reason_key or "").strip() if active else ""
    auto_hidden_now = bool(
        detection_enabled
        and auto_hide_enabled
        and reason_key in AUTO_HIDE_REASON_KEYS
    )

    if english:
        if detection_enabled:
            status_text = (
                f"Auto DND is active: {reason_label}."
                if active
                else "Auto DND detection is running, but no scene is active right now."
            )
            meta_text = (
                f"Last checked: {checked_at}."
                if checked_at
                else "Auto DND has not been checked yet."
            )
            if detail_text:
                meta_text += f" {detail_text}"
        else:
            status_text = "Auto DND detection is turned off."
            meta_text = (
                "Background scene probes are paused until you enable the master switch again."
            )
        cards = [
            {
                "tone": "ok" if detection_enabled else "warning",
                "title": "Detection Switch",
                "badge": "On" if detection_enabled else "Off",
                "summary": (
                    "Background scene detection is running."
                    if detection_enabled
                    else "Background scene detection is paused."
                ),
                "detail": (
                    "Fullscreen, meeting / call, share / recording, camera, and System Focus scenes can automatically mute reminders."
                    if detection_enabled
                    else "Fullscreen, meeting / call, share / recording, camera, and System Focus scenes are not being monitored right now."
                ),
                "hint": (
                    "This is separate from Manual DND. Manual DND still works even when detection is off."
                ),
            },
            {
                "tone": "warning" if active else "ok",
                "title": "Current Status",
                "badge": (
                    "On"
                    if active
                    else ("Idle" if detection_enabled else "Disabled")
                ),
                "summary": (
                    f"Current reason: {reason_label}."
                    if active
                    else (
                        "No fullscreen / meeting / share / camera / Focus scene is currently blocking normal reminders."
                        if detection_enabled
                        else "No automatic scene will mute reminders while detection is off."
                    )
                ),
                "detail": (
                    detail_text
                    or (
                        "Auto DND checks frontmost fullscreen windows, meeting / call windows, sharing / recording signals, camera usage, and System Focus."
                        if detection_enabled
                        else "Turn detection back on from the context menu or Setup to resume background checks."
                    )
                ),
                "hint": (
                    "When active, reminders are suppressed and some scenes can also auto-hide the sprite."
                    if detection_enabled
                    else "Manual DND still works normally; only the automatic scene watcher is paused."
                ),
            },
            {
                "tone": "ok",
                "title": "Detected Frontmost App",
                "badge": "Signal",
                "summary": (
                    frontmost_name
                    or (
                        "No frontmost app captured in the latest probe."
                        if detection_enabled
                        else "Detection is off, so no fresh probe is running."
                    )
                ),
                "detail": (
                    f"Bundle ID: {frontmost_bundle_id or 'n/a'}\n"
                    f"Reason key: {reason_key or 'none'}\n"
                    f"Last checked: {checked_at or 'n/a'}"
                ),
                "hint": (
                    "If this looks wrong, hit Refresh to probe the current window scene again."
                    if detection_enabled
                    else "Turn detection back on to resume live probing."
                ),
            },
            {
                "tone": "warning" if effective_dnd else "ok",
                "title": "What This Means Right Now",
                "badge": "Effective DND" if effective_dnd else "Normal",
                "summary": (
                    f"Manual DND: {'on' if manual_dnd_enabled else 'off'}; "
                    f"Auto DND Detection: {'on' if detection_enabled else 'off'}; "
                    f"Auto DND Scene: {'on' if active else 'off'}; "
                    f"Effective DND: {'on' if effective_dnd else 'off'}."
                ),
                "detail": (
                    f"Auto-hide on sensitive scenes: {'on' if auto_hide_enabled else 'off'}.\n"
                    f"Sprite hidden by auto DND right now: {'yes' if auto_hidden_now else 'no'}.\n"
                    f"Outing state active: {'yes' if outing_active else 'no'}."
                ),
                "hint": (
                    "Share / presentation scenes can auto-hide the sprite; meeting and fullscreen scenes usually only mute reminders."
                ),
            },
        ]
    else:
        if detection_enabled:
            status_text = (
                f"当前自动免打扰已开启: {reason_label}。"
                if active
                else "自动免打扰检测正在运行，但当前没有命中场景。"
            )
            meta_text = (
                f"上次检查: {checked_at}。"
                if checked_at
                else "自动免打扰还没有跑过检查。"
            )
            if detail_text:
                meta_text += f" {detail_text}"
        else:
            status_text = "自动免打扰检测已关闭。"
            meta_text = "后台场景探测已经暂停；重新打开总开关前，她不会再自动根据场景静音。"
        cards = [
            {
                "tone": "ok" if detection_enabled else "warning",
                "title": "检测总开关",
                "badge": "开启" if detection_enabled else "关闭",
                "summary": (
                    "后台场景检测正在运行。"
                    if detection_enabled
                    else "后台场景检测已经暂停。"
                ),
                "detail": (
                    "全屏、会议/通话、共享/录屏、摄像头和系统 Focus 场景都可以自动触发静音提醒。"
                    if detection_enabled
                    else "全屏、会议/通话、共享/录屏、摄像头和系统 Focus 场景当前都不会被后台监测。"
                ),
                "hint": "这和手动免打扰是两回事；检测关了之后，手动免打扰依然能单独使用。",
            },
            {
                "tone": "warning" if active else "ok",
                "title": "当前状态",
                "badge": (
                    "开启"
                    if active
                    else ("待机" if detection_enabled else "已停用")
                ),
                "summary": (
                    f"当前命中原因: {reason_label}。"
                    if active
                    else (
                        "现在没有全屏、会议、共享、录屏、摄像头或系统 Focus 场景在拦正常提醒。"
                        if detection_enabled
                        else "检测关闭后，不会再有任何自动场景替你拦提醒。"
                    )
                ),
                "detail": (
                    detail_text
                    or (
                        "自动免打扰会检查前台全屏、会议/通话窗口、共享/录屏信号、摄像头占用，以及系统 Focus。"
                        if detection_enabled
                        else "想恢复这条链路，只要从右键菜单或设置里把自动免打扰检测重新打开。"
                    )
                ),
                "hint": (
                    "命中后会静默提醒；部分场景还会顺手自动隐藏立绘。"
                    if detection_enabled
                    else "手动免打扰照常有效；停掉的只是自动场景判断。"
                ),
            },
            {
                "tone": "ok",
                "title": "检测到的前台线索",
                "badge": "信号",
                "summary": (
                    frontmost_name
                    or (
                        "最近一次探测里没有拿到前台 app。"
                        if detection_enabled
                        else "检测关着时，这里不会持续刷新新的前台线索。"
                    )
                ),
                "detail": (
                    f"Bundle ID: {frontmost_bundle_id or '无'}\n"
                    f"原因 key: {reason_key or '无'}\n"
                    f"上次检查: {checked_at or '无'}"
                ),
                "hint": (
                    "如果这里看起来不对，点刷新就会按当前窗口场景再探一次。"
                    if detection_enabled
                    else "重新打开检测后，这里才会继续实时刷新。"
                ),
            },
            {
                "tone": "warning" if effective_dnd else "ok",
                "title": "当前会怎么影响她",
                "badge": "实际免打扰" if effective_dnd else "正常",
                "summary": (
                    f"手动免打扰: {'开' if manual_dnd_enabled else '关'}；"
                    f"自动免打扰检测: {'开' if detection_enabled else '关'}；"
                    f"自动免打扰场景: {'开' if active else '关'}；"
                    f"实际免打扰: {'开' if effective_dnd else '关'}。"
                ),
                "detail": (
                    f"敏感场景自动隐藏: {'开' if auto_hide_enabled else '关'}。\n"
                    f"此刻是否会因自动免打扰隐藏立绘: {'会' if auto_hidden_now else '不会'}。\n"
                    f"当前是否在出门态: {'是' if outing_active else '否'}。"
                ),
                "hint": "共享/演示场景会顺手隐藏立绘；会议或全屏更多只是让提醒静音。",
            },
        ]

    return {
        "status_text": status_text,
        "meta_text": meta_text,
        "cards": cards,
        "refresh_enabled": detection_enabled,
    }


class PermissionHealthCardWidget(QFrame):
    action_requested = Signal(object)

    def __init__(self, check: dict[str, object]):
        super().__init__(None)
        self.setObjectName("permissionHealthCard")
        self.setFrameShape(QFrame.StyledPanel)

        self._title = QLabel(self)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._badge = QLabel(self)
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setMinimumWidth(72)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(self._title, 1)
        title_row.addWidget(self._badge, 0, Qt.AlignTop)

        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._detail = QLabel(self)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #444;")

        self._tools = QLabel(self)
        self._tools.setWordWrap(True)
        self._tools.setStyleSheet("color: #666;")

        self._hint = QLabel(self)
        self._hint.setWordWrap(True)

        self._actions_host = QWidget(self)
        self._actions_layout = QHBoxLayout(self._actions_host)
        self._actions_layout.setContentsMargins(0, 4, 0, 0)
        self._actions_layout.setSpacing(6)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.addLayout(title_row)
        layout.addWidget(self._summary)
        layout.addWidget(self._detail)
        layout.addWidget(self._tools)
        layout.addWidget(self._hint)
        layout.addWidget(self._actions_host)

        self.set_check(check)

    def set_check(self, check: dict[str, object]):
        status = str(check.get("status") or "warning").strip() or "warning"
        style = _HEALTH_STATUS_STYLE.get(status, _HEALTH_STATUS_STYLE["warning"])
        self.setStyleSheet(
            """
            QFrame#permissionHealthCard {
                background: %s;
                border: 1px solid %s;
                border-radius: 8px;
            }
            """
            % (style["card_bg"], style["card_border"])
        )
        self._title.setText(str(check.get("title") or "检查项"))
        self._badge.setText(str(check.get("status_label") or status))
        self._badge.setStyleSheet(
            """
            QLabel {
                background: %s;
                color: %s;
                border: 1px solid %s;
                border-radius: 6px;
                padding: 3px 8px;
                font-weight: 600;
            }
            """
            % (style["badge_bg"], style["badge_fg"], style["badge_border"])
        )

        self._summary.setText(str(check.get("summary") or ""))

        detail = str(check.get("detail") or "").strip()
        self._detail.setVisible(bool(detail))
        self._detail.setText(detail)

        tools = [str(tool).strip() for tool in (check.get("tools") or []) if str(tool).strip()]
        tools_text = f"影响工具: {', '.join(tools)}" if tools else ""
        self._tools.setVisible(bool(tools_text))
        self._tools.setText(tools_text)

        hint = str(check.get("hint") or "").strip()
        self._hint.setVisible(bool(hint))
        if hint:
            hint_color = style["badge_fg"] if status != "ok" else "#365e40"
            self._hint.setStyleSheet(f"color: {hint_color};")
            self._hint.setText(f"处理建议: {hint}")
        else:
            self._hint.setText("")

        self._render_actions(check.get("actions") or [])

    def _render_actions(self, actions):
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        rows = [dict(item) for item in actions if isinstance(item, dict)]
        self._actions_host.setVisible(bool(rows))
        if not rows:
            return

        for action in rows:
            label = str(action.get("label") or "").strip()
            if not label:
                continue
            button = QPushButton(label, self._actions_host)
            if str(action.get("kind") or "").strip() == "refresh":
                button.setObjectName("primaryButton")
            detail = str(action.get("detail") or "").strip()
            if detail:
                button.setToolTip(detail)
            button.clicked.connect(
                lambda _checked=False, payload=dict(action): self.action_requested.emit(payload)
            )
            self._actions_layout.addWidget(button)
        self._actions_layout.addStretch(1)


class PermissionHealthDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("权限自检")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(560, 540)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton:disabled {
                background: #f4f4f4;
                color: #9b9b9b;
                border: 1px solid #dddddd;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )

        self._snapshot = None
        self._empty_text = "还没检查。"

        self._status = QLabel("点一下刷新就会检查当前权限和运行环境。", self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-weight: 600;")

        self._meta = QLabel("第一次检查时，系统可能会顺手弹出授权提示。", self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color: #666;")

        self._cards_host = QWidget(self)
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)

        self._cards_scroll = QScrollArea(self)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setWidget(self._cards_host)

        self._refresh = QPushButton("刷新", self)
        self._refresh.setObjectName("primaryButton")
        self._refresh.clicked.connect(
            lambda _checked=False: self.refresh_requested.emit()
        )
        self._close = QPushButton("关闭", self)
        self._close.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addWidget(self._refresh)
        row.addStretch(1)
        row.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._meta)
        layout.addWidget(self._cards_scroll, 1)
        layout.addLayout(row)

        self._render_cards([])

    def has_snapshot(self) -> bool:
        return self._snapshot is not None

    def show_for(self, target: QWidget):
        self.reposition(target)
        self.show()
        self.raise_()
        self.activateWindow()

    def set_loading(self, text: str = "正在检查权限和运行环境..."):
        self._status.setText(text)
        self._meta.setText("有几项会轻触系统服务；如果系统弹出授权提示，按它的引导点就行。")
        self._refresh.setEnabled(False)
        self._empty_text = "检查中..."
        self._render_cards([])

    def set_error(self, message: str):
        self._refresh.setEnabled(True)
        self._status.setText("这次权限自检没跑完。")
        self._meta.setText("先看下面的报错，再点一次刷新。")
        self._empty_text = message.strip() or "未知错误"
        self._render_cards([])

    def refresh(self, snapshot: dict[str, object]):
        self._snapshot = dict(snapshot)
        self._refresh.setEnabled(True)
        self._status.setText(str(snapshot.get("summary_text") or ""))
        checked_at = _format_health_checked_at(snapshot.get("checked_at"))
        guide = build_permission_recovery_guide(snapshot.get("checks") or [])
        if guide is not None:
            if checked_at:
                self._meta.setText(
                    f"上次检查: {checked_at}。上面那张“恢复向导”卡会把该开的设置页直接打开。"
                )
            else:
                self._meta.setText("刚刚检查过。上面那张“恢复向导”卡可以直接带你去对应设置页。")
        elif checked_at:
            self._meta.setText(f"上次检查: {checked_at}")
        else:
            self._meta.setText("刚刚检查过。")
        self._empty_text = "这轮没有拿到检查项。"
        rows = [dict(item) for item in (snapshot.get("checks") or []) if isinstance(item, dict)]
        if guide is not None:
            rows = [guide, *rows]
        self._render_cards(rows)

    def _render_cards(self, checks):
        self._clear_cards()
        rows = [dict(item) for item in checks if isinstance(item, dict)]
        if not rows:
            empty = QLabel(self._empty_text, self._cards_host)
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #666; padding: 12px 6px;")
            self._cards_layout.addWidget(empty)
            self._cards_layout.addStretch(1)
            return

        for check in rows:
            card = PermissionHealthCardWidget(check)
            card.action_requested.connect(self._handle_action_requested)
            self._cards_layout.addWidget(card)
        self._cards_layout.addStretch(1)

    def _clear_cards(self):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)

        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)

    def _handle_action_requested(self, action: dict[str, object]):
        ok, message = perform_permission_recovery_action(action)
        clean_message = str(message or "").strip()
        if str(action.get("kind") or "").strip() == "refresh" and ok:
            self.set_loading(clean_message or "正在检查权限和运行环境...")
            self.refresh_requested.emit()
            return
        if clean_message:
            self._meta.setText(clean_message)


class BudgetStatusCardWidget(QFrame):
    def __init__(self, card: dict[str, object]):
        super().__init__(None)
        self.setObjectName("budgetStatusCard")
        self.setFrameShape(QFrame.StyledPanel)

        self._title = QLabel(self)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._badge = QLabel(self)
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setMinimumWidth(72)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(self._title, 1)
        title_row.addWidget(self._badge, 0, Qt.AlignTop)

        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._detail = QLabel(self)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #444;")

        self._hint = QLabel(self)
        self._hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        layout.addLayout(title_row)
        layout.addWidget(self._summary)
        layout.addWidget(self._detail)
        layout.addWidget(self._hint)

        self.set_card(card)

    def set_card(self, card: dict[str, object]):
        tone = str(card.get("tone") or "ok").strip() or "ok"
        style = _HEALTH_STATUS_STYLE.get(tone, _HEALTH_STATUS_STYLE["ok"])
        self.setStyleSheet(
            """
            QFrame#budgetStatusCard {
                background: %s;
                border: 1px solid %s;
                border-radius: 8px;
            }
            """
            % (style["card_bg"], style["card_border"])
        )

        self._title.setText(str(card.get("title") or ""))

        badge = str(card.get("badge") or "").strip()
        self._badge.setVisible(bool(badge))
        self._badge.setText(badge)
        self._badge.setStyleSheet(
            """
            QLabel {
                background: %s;
                color: %s;
                border: 1px solid %s;
                border-radius: 6px;
                padding: 3px 8px;
                font-weight: 600;
            }
            """
            % (style["badge_bg"], style["badge_fg"], style["badge_border"])
        )

        summary = str(card.get("summary") or "").strip()
        self._summary.setVisible(bool(summary))
        self._summary.setText(summary)

        detail = str(card.get("detail") or "").strip()
        self._detail.setVisible(bool(detail))
        self._detail.setText(detail)

        hint = str(card.get("hint") or "").strip()
        self._hint.setVisible(bool(hint))
        self._hint.setStyleSheet(
            f"color: {style['badge_fg'] if tone != 'ok' else '#365e40'};"
        )
        self._hint.setText(hint)


class BudgetStatusDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(560, 500)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )

        self._language_pref = DEFAULT_UI_LANGUAGE
        self._snapshot: dict[str, object] = {}
        self._empty_text = ""

        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-weight: 600;")

        self._meta = QLabel(self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color: #666;")

        self._cards_host = QWidget(self)
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)

        self._cards_scroll = QScrollArea(self)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setWidget(self._cards_host)

        self._refresh = QPushButton(self)
        self._refresh.setObjectName("primaryButton")
        self._refresh.clicked.connect(
            lambda _checked=False: self.refresh_requested.emit()
        )
        self._close = QPushButton(self)
        self._close.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addWidget(self._refresh)
        row.addStretch(1)
        row.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._meta)
        layout.addWidget(self._cards_scroll, 1)
        layout.addLayout(row)

        self.set_language(self._language_pref)
        self._render_cards([])

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Budget Status" if english else "预算状态")
        self._empty_text = (
            "No budget snapshot yet."
            if english
            else "还没拿到预算快照。"
        )
        self._refresh.setText("Refresh" if english else "刷新")
        self._close.setText("Close" if english else "关闭")
        if self._snapshot:
            self.refresh(self._snapshot)
        else:
            self._status.setText(
                "This panel explains the current budget tier, hard gates, and idle throttling."
                if english
                else "这里会解释当前预算档位、硬闸和闲时折算。"
            )
            self._meta.setText(
                "The two lines in the context menu are only a summary; this panel explains why it tightened and when it resets."
                if english
                else "右键菜单里的两行数字只是摘要；这里会把为什么收紧、什么时候恢复说清楚。"
            )

    def show_for(self, target: QWidget, snapshot: dict[str, object] | None = None):
        if snapshot is not None:
            self.refresh(snapshot)
        self.reposition(target)
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self, snapshot: dict[str, object]):
        self._snapshot = dict(snapshot or {})
        view = _build_budget_status_view(self._snapshot, language=self._language_pref)
        self._status.setText(str(view.get("status_text") or self._empty_text))
        self._meta.setText(str(view.get("meta_text") or ""))
        self._render_cards(view.get("cards") or [])

    def _render_cards(self, cards):
        self._clear_cards()
        rows = [dict(item) for item in cards if isinstance(item, dict)]
        if not rows:
            empty = QLabel(self._empty_text, self._cards_host)
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #666; padding: 12px 6px;")
            self._cards_layout.addWidget(empty)
            self._cards_layout.addStretch(1)
            return

        for card in rows:
            self._cards_layout.addWidget(BudgetStatusCardWidget(card))
        self._cards_layout.addStretch(1)

    def _clear_cards(self):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)

        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)


class PrivacyBoundaryDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(560, 500)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )

        self._language_pref = DEFAULT_UI_LANGUAGE
        self._view: dict[str, object] = {}
        self._empty_text = ""

        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-weight: 600;")

        self._meta = QLabel(self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color: #666;")

        self._cards_host = QWidget(self)
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)

        self._cards_scroll = QScrollArea(self)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setWidget(self._cards_host)

        self._refresh = QPushButton(self)
        self._refresh.setObjectName("primaryButton")
        self._refresh.clicked.connect(
            lambda _checked=False: self.refresh_requested.emit()
        )
        self._close = QPushButton(self)
        self._close.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addWidget(self._refresh)
        row.addStretch(1)
        row.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._meta)
        layout.addWidget(self._cards_scroll, 1)
        layout.addLayout(row)

        self.set_language(self._language_pref)
        self._render_cards([])

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Privacy Boundary" if english else "隐私边界")
        self._empty_text = (
            "No privacy-boundary summary yet."
            if english
            else "还没拿到隐私边界说明。"
        )
        self._refresh.setText("Refresh" if english else "刷新")
        self._close.setText("Close" if english else "关闭")
        if not self._view:
            self._status.setText(
                "This panel explains what may leave the device and what stays local by default."
                if english
                else "这里会说明什么可能离机、什么默认留在本机。"
            )
            self._meta.setText(
                "When masking or blocking happens, this panel also explains the latest reason and the next suggested step."
                if english
                else "命中脱敏或阻断后，这里会补一条最近一次为什么被拦、下一步怎么做的解释。"
            )

    def show_for(self, target: QWidget, view: dict[str, object] | None = None):
        if view is not None:
            self.refresh(view)
        self.reposition(target)
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self, view: dict[str, object]):
        self._view = dict(view or {})
        self._status.setText(str(self._view.get("status_text") or self._empty_text))
        self._meta.setText(str(self._view.get("meta_text") or ""))
        self._render_cards(self._view.get("cards") or [])

    def _render_cards(self, cards):
        self._clear_cards()
        rows = [dict(item) for item in cards if isinstance(item, dict)]
        if not rows:
            empty = QLabel(self._empty_text, self._cards_host)
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #666; padding: 12px 6px;")
            self._cards_layout.addWidget(empty)
            self._cards_layout.addStretch(1)
            return

        for card in rows:
            self._cards_layout.addWidget(BudgetStatusCardWidget(card))
        self._cards_layout.addStretch(1)

    def _clear_cards(self):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)

        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)


class SpritePackPickerDialog(QDialog):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(True)
        self.resize(520, 320)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
                background: transparent;
            }
            QComboBox {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d7e2;
                border-radius: 6px;
                padding: 6px 8px;
                min-height: 18px;
            }
            QComboBox:focus {
                border: 1px solid #76a8ef;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 6px 14px;
                min-width: 88px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )

        self._language_pref = DEFAULT_UI_LANGUAGE
        self._summaries: list[SpritePackSummary] = []
        self._current_pack_id = ""
        self._selected_pack_id: str | None = None

        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-weight: 600;")

        self._meta = QLabel(self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color: #666;")

        self._picker_label = QLabel(self)
        self._picker_label.setStyleSheet("font-weight: 600;")

        self._picker = QComboBox(self)
        self._picker.setMinimumHeight(34)
        self._picker.currentIndexChanged.connect(self._refresh_selection_copy)

        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("font-weight: 600;")

        self._detail = QLabel(self)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #444;")

        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #666;")

        self._close = QPushButton(self)
        self._close.clicked.connect(self.reject)
        self._apply = QPushButton(self)
        self._apply.setObjectName("primaryButton")
        self._apply.clicked.connect(self._accept_selection)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self._close)
        button_row.addWidget(self._apply)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._meta)
        layout.addWidget(self._picker_label)
        layout.addWidget(self._picker)
        layout.addWidget(self._summary)
        layout.addWidget(self._detail)
        layout.addWidget(self._hint)
        layout.addStretch(1)
        layout.addLayout(button_row)

        self.set_language(self._language_pref)

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        self._apply_localized_copy()

    def ask_for(
        self,
        target: QWidget,
        *,
        current_pack_id: str,
        summaries: list[SpritePackSummary],
    ) -> str | None:
        self._current_pack_id = str(current_pack_id or "").strip()
        self._selected_pack_id = None
        self._summaries = list(summaries)
        self._picker.blockSignals(True)
        self._picker.clear()
        for summary in self._summaries:
            self._picker.addItem(f"{summary.name} ({summary.pack_id})", summary.pack_id)
        self._picker.blockSignals(False)
        if self._summaries:
            index = self._picker.findData(self._current_pack_id)
            if index < 0:
                index = 0
            self._picker.setCurrentIndex(index)
        self._apply_localized_copy()
        self.reposition(target)
        self.raise_()
        self.activateWindow()
        if self.exec() == QDialog.Accepted:
            return self._selected_pack_id
        return None

    def _selected_summary(self) -> SpritePackSummary | None:
        current_pack_id = str(self._picker.currentData() or "").strip()
        for summary in self._summaries:
            if summary.pack_id == current_pack_id:
                return summary
        return None

    def _apply_localized_copy(self):
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Choose Sprite Pack" if english else "选择立绘包")
        self._picker_label.setText("Available Packs" if english else "可用立绘包")
        self._close.setText("Close" if english else "关闭")
        self._apply.setText("Apply" if english else "切换")
        self._refresh_selection_copy()

    def _refresh_selection_copy(self):
        summary = self._selected_summary()
        english = _ui_uses_english(self._language_pref)
        if summary is None:
            self._status.setText("No sprite pack available." if english else "现在没有可用立绘包。")
            self._meta.setText(
                "Drop a manifest pack into assets/packs and reopen this panel."
                if english
                else "把 manifest 立绘包放进 assets/packs 之后，再打开这里就会看到。"
            )
            self._summary.setText("")
            self._detail.setText("")
            self._hint.setText("")
            self._apply.setEnabled(False)
            return

        self._apply.setEnabled(True)
        source_text = (
            "legacy"
            if summary.source == "legacy"
            else _format_runtime_path(Path(summary.source))
        )
        state_text = ", ".join(summary.available_states) if summary.available_states else ("none" if english else "无")
        tag_text = ", ".join(summary.metadata.tags) if summary.metadata.tags else ("none" if english else "无")
        description = summary.metadata.description or (
            "No extra description for this pack."
            if english
            else "这个立绘包还没有额外说明。"
        )
        if english:
            self._status.setText(f"Current pack: {self._current_pack_id or summary.pack_id}.")
            self._meta.setText("Switching takes effect immediately and is remembered on this Mac.")
            self._summary.setText(f"{summary.name} ({summary.pack_id})")
            self._detail.setText(
                f"{description}\n"
                f"Author: {summary.metadata.author or 'unknown'}\n"
                f"States: {state_text}\n"
                f"Source: {source_text}"
            )
            self._hint.setText(
                f"Tags: {tag_text}. Preview pose: {summary.metadata.preview_pose}."
            )
        else:
            self._status.setText(f"当前立绘包: {self._current_pack_id or summary.pack_id}。")
            self._meta.setText("切换后会立刻生效，并记住到这台 Mac 的本机偏好里。")
            self._summary.setText(f"{summary.name} ({summary.pack_id})")
            self._detail.setText(
                f"{description}\n"
                f"作者: {summary.metadata.author or '未标注'}\n"
                f"状态: {state_text}\n"
                f"来源: {source_text}"
            )
            self._hint.setText(
                f"标签: {tag_text}。预览姿态: {summary.metadata.preview_pose}。"
            )

    def _accept_selection(self):
        summary = self._selected_summary()
        if summary is None:
            return
        self._selected_pack_id = summary.pack_id
        self.accept()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)

        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)


class SpritePackInfoDialog(QDialog):
    choose_requested = Signal()
    open_folder_requested = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(560, 500)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )

        self._language_pref = DEFAULT_UI_LANGUAGE
        self._view: dict[str, object] = {}
        self._empty_text = ""

        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-weight: 600;")

        self._meta = QLabel(self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color: #666;")

        self._cards_host = QWidget(self)
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)

        self._cards_scroll = QScrollArea(self)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setWidget(self._cards_host)

        self._choose = QPushButton(self)
        self._choose.setObjectName("primaryButton")
        self._choose.clicked.connect(
            lambda _checked=False: self.choose_requested.emit()
        )
        self._open_folder = QPushButton(self)
        self._open_folder.clicked.connect(
            lambda _checked=False: self.open_folder_requested.emit()
        )
        self._close = QPushButton(self)
        self._close.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addWidget(self._choose)
        row.addWidget(self._open_folder)
        row.addStretch(1)
        row.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._meta)
        layout.addWidget(self._cards_scroll, 1)
        layout.addLayout(row)

        self.set_language(self._language_pref)
        self._render_cards([])

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Sprite Pack Info" if english else "立绘包信息")
        self._empty_text = (
            "No sprite-pack summary yet."
            if english
            else "还没有立绘包说明。"
        )
        self._choose.setText("Choose Pack" if english else "切换立绘包")
        self._open_folder.setText("Open User Folder" if english else "打开用户立绘包目录")
        self._close.setText("Close" if english else "关闭")
        if self._view:
            self.refresh(self._view)
        else:
            self._status.setText(
                "This panel shows the current sprite-pack metadata and state coverage."
                if english
                else "这里会说明当前立绘包的元数据和状态覆盖。"
            )
            self._meta.setText(
                "Open the picker to switch packs without restarting the app."
                if english
                else "不用重启应用，也能从这里切换立绘包。"
            )

    def show_for(self, target: QWidget, view: dict[str, object] | None = None):
        if view is not None:
            self.refresh(view)
        self.reposition(target)
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self, view: dict[str, object]):
        self._view = dict(view or {})
        self._status.setText(str(self._view.get("status_text") or self._empty_text))
        self._meta.setText(str(self._view.get("meta_text") or ""))
        self._render_cards(self._view.get("cards") or [])

    def _render_cards(self, cards):
        self._clear_cards()
        rows = [dict(item) for item in cards if isinstance(item, dict)]
        if not rows:
            empty = QLabel(self._empty_text, self._cards_host)
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #666; padding: 12px 6px;")
            self._cards_layout.addWidget(empty)
            self._cards_layout.addStretch(1)
            return

        for card in rows:
            self._cards_layout.addWidget(BudgetStatusCardWidget(card))
        self._cards_layout.addStretch(1)

    def _clear_cards(self):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)

        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)


class OutingCollectionDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(560, 500)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )

        self._language_pref = DEFAULT_UI_LANGUAGE
        self._view: dict[str, object] = {}
        self._empty_text = ""

        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-weight: 600;")

        self._meta = QLabel(self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color: #666;")

        self._cards_host = QWidget(self)
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)

        self._cards_scroll = QScrollArea(self)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setWidget(self._cards_host)

        self._refresh = QPushButton(self)
        self._refresh.setObjectName("primaryButton")
        self._refresh.clicked.connect(
            lambda _checked=False: self.refresh_requested.emit()
        )
        self._close = QPushButton(self)
        self._close.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addWidget(self._refresh)
        row.addStretch(1)
        row.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._meta)
        layout.addWidget(self._cards_scroll, 1)
        layout.addLayout(row)

        self.set_language(self._language_pref)
        self._render_cards([])

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Outing Collection" if english else "出门收藏")
        self._empty_text = (
            "No outing collection summary yet."
            if english
            else "还没有出门收藏说明。"
        )
        self._refresh.setText("Refresh" if english else "刷新")
        self._close.setText("Close" if english else "关闭")
        if self._view:
            self.refresh(self._view)
        else:
            self._status.setText(
                "This panel shows outing history and collectables."
                if english
                else "这里会显示出门记录和收藏品。"
            )
            self._meta.setText(
                "Start an outing from the context menu; when she returns, this shelf updates."
                if english
                else "从右键菜单让她出门；回来以后，这个收藏架会刷新。"
            )

    def show_for(self, target: QWidget, view: dict[str, object] | None = None):
        if view is not None:
            self.refresh(view)
        self.reposition(target)
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self, view: dict[str, object]):
        self._view = dict(view or {})
        self._status.setText(str(self._view.get("status_text") or self._empty_text))
        self._meta.setText(str(self._view.get("meta_text") or ""))
        self._render_cards(self._view.get("cards") or [])

    def _render_cards(self, cards):
        self._clear_cards()
        rows = [dict(item) for item in cards if isinstance(item, dict)]
        if not rows:
            empty = QLabel(self._empty_text, self._cards_host)
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #666; padding: 12px 6px;")
            self._cards_layout.addWidget(empty)
            self._cards_layout.addStretch(1)
            return

        for card in rows:
            self._cards_layout.addWidget(BudgetStatusCardWidget(card))
        self._cards_layout.addStretch(1)

    def _clear_cards(self):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)

        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)


class AutoDoNotDisturbDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(560, 500)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )

        self._language_pref = DEFAULT_UI_LANGUAGE
        self._view: dict[str, object] = {}
        self._empty_text = ""

        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-weight: 600;")

        self._meta = QLabel(self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color: #666;")

        self._cards_host = QWidget(self)
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)

        self._cards_scroll = QScrollArea(self)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setWidget(self._cards_host)

        self._refresh = QPushButton(self)
        self._refresh.setObjectName("primaryButton")
        self._refresh.clicked.connect(
            lambda _checked=False: self.refresh_requested.emit()
        )
        self._close = QPushButton(self)
        self._close.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addWidget(self._refresh)
        row.addStretch(1)
        row.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._meta)
        layout.addWidget(self._cards_scroll, 1)
        layout.addLayout(row)

        self.set_language(self._language_pref)
        self._render_cards([])

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Auto DND" if english else "自动免打扰")
        self._empty_text = (
            "No auto-DND summary yet."
            if english
            else "还没有自动免打扰说明。"
        )
        self._refresh.setText("Refresh" if english else "刷新")
        self._close.setText("Close" if english else "关闭")
        if self._view:
            self.refresh(self._view)
        else:
            self._status.setText(
                "This panel explains why auto DND is on or off right now, or whether detection itself is paused."
                if english
                else "这里会说明自动免打扰现在为什么开着、为什么没开，或者检测本身是不是被暂停了。"
            )
            self._meta.setText(
                "It watches fullscreen windows, meeting / share signals, recording cues, camera usage, and System Focus."
                if english
                else "它会看全屏窗口、会议/共享信号、录屏线索、摄像头占用，以及系统 Focus。"
            )

    def show_for(self, target: QWidget, view: dict[str, object] | None = None):
        if view is not None:
            self.refresh(view)
        self.reposition(target)
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self, view: dict[str, object]):
        self._view = dict(view or {})
        self._status.setText(str(self._view.get("status_text") or self._empty_text))
        self._meta.setText(str(self._view.get("meta_text") or ""))
        self._refresh.setEnabled(bool(self._view.get("refresh_enabled", True)))
        self._render_cards(self._view.get("cards") or [])

    def _render_cards(self, cards):
        self._clear_cards()
        rows = [dict(item) for item in cards if isinstance(item, dict)]
        if not rows:
            empty = QLabel(self._empty_text, self._cards_host)
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #666; padding: 12px 6px;")
            self._cards_layout.addWidget(empty)
            self._cards_layout.addStretch(1)
            return

        for card in rows:
            self._cards_layout.addWidget(BudgetStatusCardWidget(card))
        self._cards_layout.addStretch(1)

    def _clear_cards(self):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)

        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)


class ReminderSettingsDialog(QDialog):
    saved = Signal(object)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(520, 360)
        self.setMinimumWidth(480)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QFrame#settingsPanel {
                background: #ffffff;
                border: 1px solid #d8dde6;
                border-radius: 8px;
            }
            QLineEdit,
            QSpinBox {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d7e2;
                border-radius: 6px;
                padding: 5px 8px;
                min-height: 20px;
            }
            QLineEdit:focus,
            QSpinBox:focus {
                border: 1px solid #76a8ef;
            }
            QCheckBox {
                color: #1f1f1f;
                spacing: 6px;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 6px 14px;
                min-width: 76px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )

        self._language_pref = DEFAULT_UI_LANGUAGE
        self._title = QLabel(self)
        self._title.setStyleSheet("font-weight: 700; font-size: 15px;")
        self._enabled = QCheckBox(self)
        self._enabled.toggled.connect(self._sync_enabled_controls)

        panel = QFrame(self)
        panel.setObjectName("settingsPanel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self._water_enabled = QCheckBox(self)
        self._water_enabled.toggled.connect(self._sync_enabled_controls)
        self._water_minutes = self._minutes_spinbox()
        self._activity_enabled = QCheckBox(self)
        self._activity_enabled.toggled.connect(self._sync_enabled_controls)
        self._activity_minutes = self._minutes_spinbox()
        self._custom_enabled = QCheckBox(self)
        self._custom_enabled.toggled.connect(self._sync_enabled_controls)
        self._custom_minutes = self._minutes_spinbox()
        self._custom_text = QLineEdit(self)

        self._custom_interval_label = QLabel(self)
        self._custom_text_label = QLabel(self)

        grid.addWidget(self._water_enabled, 0, 0)
        grid.addWidget(self._water_minutes, 0, 1)
        grid.addWidget(self._activity_enabled, 1, 0)
        grid.addWidget(self._activity_minutes, 1, 1)
        grid.addWidget(self._custom_enabled, 2, 0, 1, 2)
        grid.addWidget(self._custom_interval_label, 3, 0)
        grid.addWidget(self._custom_minutes, 3, 1)
        grid.addWidget(self._custom_text_label, 4, 0)
        grid.addWidget(self._custom_text, 4, 1)

        self._save = QPushButton(self)
        self._save.setObjectName("primaryButton")
        self._save.clicked.connect(self._save_clicked)
        self._close = QPushButton(self)
        self._close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._close)
        row.addWidget(self._save)

        header = QHBoxLayout()
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._enabled)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(panel)
        layout.addLayout(row)
        self.set_language(self._language_pref)

    def _minutes_spinbox(self) -> QSpinBox:
        spinbox = QSpinBox(self)
        spinbox.setRange(MIN_REMINDER_MINUTES, MAX_REMINDER_MINUTES)
        spinbox.setSingleStep(5)
        spinbox.setAlignment(Qt.AlignRight)
        return spinbox

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Reminder Settings" if english else "提醒设置")
        self._title.setText("Reminder Settings" if english else "提醒设置")
        self._enabled.setText("Enable reminders" if english else "开启提醒模式")
        self._water_enabled.setText("Water reminder" if english else "喝水提醒")
        self._activity_enabled.setText("Activity reminder" if english else "起身活动")
        self._custom_enabled.setText("Custom reminder" if english else "自定义提醒")
        self._custom_interval_label.setText("Interval" if english else "提醒间隔")
        self._custom_text_label.setText("Reminder text" if english else "提醒文案")
        suffix = " min" if english else " 分钟"
        for spinbox in (self._water_minutes, self._activity_minutes, self._custom_minutes):
            spinbox.setSuffix(suffix)
        self._save.setText("Save" if english else "保存")
        self._close.setText("Close" if english else "关闭")

    def show_for(self, target: QWidget, snapshot: AppStateSnapshot):
        self._load_snapshot(snapshot)
        self.reposition(target)
        self.show()
        self.raise_()
        self.activateWindow()

    def _load_snapshot(self, snapshot: AppStateSnapshot):
        self._enabled.setChecked(bool(getattr(snapshot, "reminders_enabled", DEFAULT_REMINDERS_ENABLED)))
        self._water_enabled.setChecked(
            bool(getattr(snapshot, "water_reminder_enabled", DEFAULT_WATER_REMINDER_ENABLED))
        )
        self._water_minutes.setValue(
            int(getattr(snapshot, "water_reminder_minutes", DEFAULT_WATER_REMINDER_MINUTES) or DEFAULT_WATER_REMINDER_MINUTES)
        )
        self._activity_enabled.setChecked(
            bool(getattr(snapshot, "activity_reminder_enabled", DEFAULT_ACTIVITY_REMINDER_ENABLED))
        )
        self._activity_minutes.setValue(
            int(getattr(snapshot, "activity_reminder_minutes", DEFAULT_ACTIVITY_REMINDER_MINUTES) or DEFAULT_ACTIVITY_REMINDER_MINUTES)
        )
        self._custom_enabled.setChecked(
            bool(getattr(snapshot, "custom_reminder_enabled", DEFAULT_CUSTOM_REMINDER_ENABLED))
        )
        self._custom_minutes.setValue(
            int(getattr(snapshot, "custom_reminder_minutes", DEFAULT_CUSTOM_REMINDER_MINUTES) or DEFAULT_CUSTOM_REMINDER_MINUTES)
        )
        self._custom_text.setText(
            str(getattr(snapshot, "custom_reminder_text", DEFAULT_CUSTOM_REMINDER_TEXT) or DEFAULT_CUSTOM_REMINDER_TEXT)
        )
        self._sync_enabled_controls()

    def _sync_enabled_controls(self):
        enabled = self._enabled.isChecked()
        water_enabled = enabled and self._water_enabled.isChecked()
        activity_enabled = enabled and self._activity_enabled.isChecked()
        custom_enabled = enabled and self._custom_enabled.isChecked()
        for widget in (
            self._water_enabled,
            self._activity_enabled,
            self._custom_enabled,
        ):
            widget.setEnabled(enabled)
        self._water_minutes.setEnabled(water_enabled)
        self._activity_minutes.setEnabled(activity_enabled)
        self._custom_interval_label.setEnabled(custom_enabled)
        self._custom_minutes.setEnabled(custom_enabled)
        self._custom_text_label.setEnabled(custom_enabled)
        self._custom_text.setEnabled(custom_enabled)

    def _preferences(self) -> dict[str, object]:
        return {
            "reminders_enabled": self._enabled.isChecked(),
            "water_reminder_enabled": self._water_enabled.isChecked(),
            "water_reminder_minutes": self._water_minutes.value(),
            "activity_reminder_enabled": self._activity_enabled.isChecked(),
            "activity_reminder_minutes": self._activity_minutes.value(),
            "custom_reminder_enabled": self._custom_enabled.isChecked(),
            "custom_reminder_minutes": self._custom_minutes.value(),
            "custom_reminder_text": self._custom_text.text().strip(),
        }

    def _save_clicked(self):
        self.saved.emit(self._preferences())
        self.close()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)
        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))
        self.move(x, y)


class SpriteDisplaySettingsDialog(QDialog):
    saved = Signal(object)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(520, 300)
        self.setMinimumWidth(480)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QFrame#settingsPanel {
                background: #ffffff;
                border: 1px solid #d8dde6;
                border-radius: 8px;
            }
            QComboBox,
            QSpinBox {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d7e2;
                border-radius: 6px;
                padding: 5px 8px;
                min-height: 20px;
            }
            QComboBox:focus,
            QSpinBox:focus {
                border: 1px solid #76a8ef;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 6px 14px;
                min-width: 76px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )

        self._language_pref = DEFAULT_UI_LANGUAGE
        self._screen_modes = (
            SPRITE_SCREEN_MODE_PRIMARY,
            SPRITE_SCREEN_MODE_CURSOR,
        )

        self._title = QLabel(self)
        self._title.setStyleSheet("font-weight: 700; font-size: 15px;")
        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #666;")

        panel = QFrame(self)
        panel.setObjectName("settingsPanel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self._size_label = QLabel(self)
        self._size = QSpinBox(self)
        self._size.setRange(MIN_SPRITE_SIZE_PERCENT, MAX_SPRITE_SIZE_PERCENT)
        self._size.setSingleStep(5)
        self._size.setAlignment(Qt.AlignRight)
        self._x_label = QLabel(self)
        self._x = QSpinBox(self)
        self._x.setRange(0, 100)
        self._x.setSingleStep(5)
        self._x.setAlignment(Qt.AlignRight)
        self._y_label = QLabel(self)
        self._y = QSpinBox(self)
        self._y.setRange(0, 100)
        self._y.setSingleStep(5)
        self._y.setAlignment(Qt.AlignRight)
        self._screen_label = QLabel(self)
        self._screen = QComboBox(self)
        for mode in self._screen_modes:
            self._screen.addItem("", mode)

        grid.addWidget(self._size_label, 0, 0)
        grid.addWidget(self._size, 0, 1)
        grid.addWidget(self._x_label, 1, 0)
        grid.addWidget(self._x, 1, 1)
        grid.addWidget(self._y_label, 2, 0)
        grid.addWidget(self._y, 2, 1)
        grid.addWidget(self._screen_label, 3, 0)
        grid.addWidget(self._screen, 3, 1)

        self._save = QPushButton(self)
        self._save.setObjectName("primaryButton")
        self._save.clicked.connect(self._save_clicked)
        self._close = QPushButton(self)
        self._close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._close)
        row.addWidget(self._save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._hint)
        layout.addWidget(panel)
        layout.addLayout(row)
        self.set_language(self._language_pref)

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Desktop Display" if english else "桌面显示设置")
        self._title.setText("Desktop Display" if english else "桌面显示设置")
        self._hint.setText(
            "Size applies immediately. The position is used now and on next launch."
            if english
            else "大小会立即生效；出现位置会现在应用，并在下次启动继续使用。"
        )
        self._size_label.setText("Size" if english else "缩放")
        self._x_label.setText("Horizontal position" if english else "水平出现位置")
        self._y_label.setText("Vertical position" if english else "垂直出现位置")
        self._screen_label.setText("Show on" if english else "出现在")
        suffix = " %"
        for spinbox in (self._size, self._x, self._y):
            spinbox.setSuffix(suffix)

        labels = {
            SPRITE_SCREEN_MODE_PRIMARY: "Primary display" if english else "主显示器",
            SPRITE_SCREEN_MODE_CURSOR: "Display under cursor" if english else "鼠标所在显示器",
        }
        current_mode = self._screen.currentData()
        self._screen.blockSignals(True)
        self._screen.clear()
        for mode in self._screen_modes:
            self._screen.addItem(labels.get(mode, mode), mode)
        index = self._screen.findData(current_mode or DEFAULT_SPRITE_SCREEN_MODE)
        self._screen.setCurrentIndex(max(0, index))
        self._screen.blockSignals(False)
        self._save.setText("Save" if english else "保存")
        self._close.setText("Close" if english else "关闭")

    def show_for(self, target: QWidget, snapshot: AppStateSnapshot):
        self._load_snapshot(snapshot)
        self.reposition(target)
        self.show()
        self.raise_()
        self.activateWindow()

    def _load_snapshot(self, snapshot: AppStateSnapshot):
        self._size.setValue(
            int(getattr(snapshot, "sprite_size_percent", DEFAULT_SPRITE_SIZE_PERCENT))
        )
        self._x.setValue(
            int(getattr(snapshot, "sprite_position_x_percent", DEFAULT_SPRITE_POSITION_X_PERCENT))
        )
        self._y.setValue(
            int(getattr(snapshot, "sprite_position_y_percent", DEFAULT_SPRITE_POSITION_Y_PERCENT))
        )
        mode = str(getattr(snapshot, "sprite_screen_mode", DEFAULT_SPRITE_SCREEN_MODE)
                   or DEFAULT_SPRITE_SCREEN_MODE)
        index = self._screen.findData(mode)
        self._screen.setCurrentIndex(index if index >= 0 else 0)

    def _preferences(self) -> dict[str, object]:
        return {
            "sprite_size_percent": self._size.value(),
            "sprite_position_x_percent": self._x.value(),
            "sprite_position_y_percent": self._y.value(),
            "sprite_screen_mode": str(self._screen.currentData() or DEFAULT_SPRITE_SCREEN_MODE),
        }

    def _save_clicked(self):
        self.saved.emit(self._preferences())
        self.close()

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)
        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))
        self.move(x, y)


def _derive_owner_name_from_memory_items(items: list[dict[str, object]]) -> str:
    for key in ("preferred_name", "name"):
        for item in items:
            if str(item.get("key") or "").strip() != key:
                continue
            text = str(item.get("text") or "").strip()
            if key == "preferred_name" and text.startswith("主人希望被叫作"):
                value = text.removeprefix("主人希望被叫作").strip("。！？!? ")
                if value:
                    return value
            if key == "name" and text.startswith("主人的名字是"):
                value = text.removeprefix("主人的名字是").strip("。！？!? ")
                if value:
                    return value
    return ""


def _derive_language_from_memory_items(items: list[dict[str, object]]) -> str:
    for item in items:
        if str(item.get("key") or "").strip() != "reply_language":
            continue
        text = str(item.get("text") or "").strip()
        if "英文" in text or "English" in text:
            return "en-US"
        if "中文" in text or "Chinese" in text:
            return "zh-CN"
    return DEFAULT_LANGUAGE


@dataclass(frozen=True)
class OnboardingDecision:
    remember: bool
    submitted: bool = False
    open_health: bool = False
    api_key_configured: bool = False
    owner_name: str = ""
    budget_mode: str = "normal"
    reply_language: str = DEFAULT_LANGUAGE
    ui_language: str = DEFAULT_UI_LANGUAGE
    data_boundary_acknowledged: bool = False
    auto_do_not_disturb_enabled: bool = True
    auto_hide_on_sensitive_scene: bool = True


class OnboardingDialog(QDialog):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(True)
        self.resize(620, 560)
        self.setMinimumWidth(620)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
                background: transparent;
            }
            QLineEdit,
            QComboBox {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d7e2;
                border-radius: 6px;
                padding: 6px 8px;
                min-height: 18px;
            }
            QLineEdit:focus,
            QComboBox:focus {
                border: 1px solid #76a8ef;
            }
            QComboBox {
                padding-right: 22px;
            }
            QCheckBox,
            QRadioButton {
                color: #1f1f1f;
                spacing: 6px;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 6px 14px;
                min-width: 88px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            """
        )
        self._decision = OnboardingDecision(remember=True)
        self._reply_language_codes = [code for code, _label, _description in LANGUAGE_OPTIONS]
        self._ui_language_codes = [code for code, _label, _description in UI_LANGUAGE_OPTIONS]

        self._title = QLabel(self)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._body = QLabel(self)
        self._body.setWordWrap(True)
        self._body.setStyleSheet("color: #333;")

        self._api_key_status = QLabel(self)
        self._api_key_status.setWordWrap(True)
        self._api_key_status.setStyleSheet("color: #666;")

        self._api_key_label = QLabel(self)
        self._api_key_label.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._api_key = QLineEdit(self)
        self._api_key.setEchoMode(QLineEdit.Password)
        self._api_key.setPlaceholderText("sk-ant-api03-...")
        self._api_key.setMinimumHeight(34)
        self._api_key.returnPressed.connect(self._accept_with_save)

        self._show_api_key = QCheckBox(self)
        self._show_api_key.toggled.connect(self._toggle_api_key_visibility)

        self._api_key_hint = QLabel(self)
        self._api_key_hint.setWordWrap(True)
        self._api_key_hint.setStyleSheet("color: #666;")

        self._owner_name_label = QLabel(self)
        self._owner_name_label.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._owner_name = QLineEdit(self)
        self._owner_name.setMinimumWidth(220)
        self._owner_name.setMinimumHeight(34)

        self._reply_language_label = QLabel(self)
        self._reply_language_label.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._reply_language = QComboBox(self)
        self._reply_language.setMinimumWidth(170)
        self._reply_language.setMinimumHeight(34)
        self._reply_language.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        for code in self._reply_language_codes:
            self._reply_language.addItem("", code)

        self._ui_language_label = QLabel(self)
        self._ui_language_label.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._ui_language = QComboBox(self)
        self._ui_language.setMinimumWidth(190)
        self._ui_language.setMinimumHeight(34)
        self._ui_language.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)
        for code in self._ui_language_codes:
            self._ui_language.addItem("", code)
        self._ui_language.currentIndexChanged.connect(self._on_ui_language_changed)

        self._identity_hint = QLabel(self)
        self._identity_hint.setWordWrap(True)
        self._identity_hint.setStyleSheet("color: #666;")

        self._budget_label = QLabel(self)
        self._budget_label.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._budget_modes: dict[str, QRadioButton] = {}
        self._budget_mode_codes: list[str] = []
        budget_row = QHBoxLayout()
        budget_row.setContentsMargins(0, 0, 0, 0)
        budget_row.setSpacing(12)
        for mode, _label, _description, _max_budget_usd in BUDGET_MODE_OPTIONS:
            radio = QRadioButton(self)
            radio.toggled.connect(self._refresh_budget_hint)
            self._budget_modes[mode] = radio
            self._budget_mode_codes.append(mode)
            budget_row.addWidget(radio)

        self._budget_hint = QLabel(self)
        self._budget_hint.setWordWrap(True)
        self._budget_hint.setStyleSheet("color: #666;")

        self._boundary_label = QLabel(self)
        self._boundary_label.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._boundary_body = QLabel(self)
        self._boundary_body.setWordWrap(True)
        self._boundary_body.setStyleSheet("color: #333;")

        self._data_boundary_ack = QCheckBox(self)

        self._auto_dnd_enabled = QCheckBox(self)
        self._auto_hide = QCheckBox(self)

        self._setup_hint = QLabel(self)
        self._setup_hint.setWordWrap(True)
        self._setup_hint.setStyleSheet("color: #666;")

        self._remember = QCheckBox(self)
        self._remember.setChecked(True)

        self._later = QPushButton(self)
        self._later.setMinimumHeight(34)
        self._later.clicked.connect(self.reject)
        self._save = QPushButton(self)
        self._save.setMinimumHeight(34)
        self._save.setObjectName("primaryButton")
        self._save.clicked.connect(self._accept_with_save)
        self._health = QPushButton(self)
        self._health.setMinimumHeight(34)
        self._health.clicked.connect(self._accept_with_health)

        identity_grid = QGridLayout()
        identity_grid.setContentsMargins(0, 0, 0, 0)
        identity_grid.setHorizontalSpacing(10)
        identity_grid.setVerticalSpacing(6)
        identity_grid.setColumnStretch(0, 1)
        identity_grid.setColumnStretch(1, 1)
        identity_grid.addWidget(self._owner_name_label, 0, 0, 1, 2)
        identity_grid.addWidget(self._owner_name, 1, 0, 1, 2)
        identity_grid.addWidget(self._reply_language_label, 2, 0)
        identity_grid.addWidget(self._ui_language_label, 2, 1)
        identity_grid.addWidget(self._reply_language, 3, 0)
        identity_grid.addWidget(self._ui_language, 3, 1)

        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(8)
        key_row.addWidget(self._api_key, 1)
        key_row.addWidget(self._show_api_key)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._later)
        row.addWidget(self._save)
        row.addWidget(self._health)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)
        layout.addWidget(self._title)
        layout.addWidget(self._body)
        layout.addWidget(self._api_key_status)
        layout.addWidget(self._api_key_label)
        layout.addLayout(key_row)
        layout.addWidget(self._api_key_hint)
        layout.addSpacing(2)
        layout.addLayout(identity_grid)
        layout.addWidget(self._identity_hint)
        layout.addSpacing(2)
        layout.addWidget(self._budget_label)
        layout.addLayout(budget_row)
        layout.addWidget(self._budget_hint)
        layout.addSpacing(2)
        layout.addWidget(self._boundary_label)
        layout.addWidget(self._boundary_body)
        layout.addWidget(self._data_boundary_ack)
        layout.addWidget(self._auto_dnd_enabled)
        layout.addWidget(self._auto_hide)
        layout.addSpacing(2)
        layout.addWidget(self._setup_hint)
        layout.addWidget(self._remember)
        layout.addLayout(row)
        self._apply_localized_copy()

    def ask_for(self, target: QWidget, snapshot, memory_items: list[dict[str, object]]) -> OnboardingDecision:
        self._decision = self._build_decision()
        self._api_key.clear()
        self._show_api_key.setChecked(False)
        self._remember.setChecked(True)
        owner_name = str(getattr(snapshot, "owner_name", "") or "").strip()
        if not owner_name:
            owner_name = _derive_owner_name_from_memory_items(memory_items)
        self._owner_name.setText(owner_name)
        self._set_ui_language_preference(
            str(getattr(snapshot, "ui_language", "") or DEFAULT_UI_LANGUAGE)
        )
        self._apply_localized_copy()
        stored_reply_language = str(getattr(snapshot, "language", "") or "").strip()
        reply_language = normalize_language(
            stored_reply_language or _derive_language_from_memory_items(memory_items)
        )
        self._set_reply_language(reply_language)
        self._set_budget_mode(str(getattr(snapshot, "budget_mode", "normal") or "normal"))
        self._data_boundary_ack.setChecked(
            bool(getattr(snapshot, "data_boundary_acknowledged", False))
        )
        self._auto_dnd_enabled.setChecked(
            bool(getattr(snapshot, "auto_do_not_disturb_enabled", True))
        )
        self._auto_hide.setChecked(
            bool(getattr(snapshot, "auto_hide_on_sensitive_scene", True))
        )
        self._refresh_identity_hint()
        self._refresh_api_key_status()
        self._refresh_budget_hint()
        self._refresh_setup_hint()
        self._sync_dialog_size()
        self.reposition(target)
        self.raise_()
        self.activateWindow()
        if self.exec() == QDialog.Accepted:
            return self._decision
        return self._build_decision(open_health=False)

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)

        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)

    def _toggle_api_key_visibility(self, checked: bool):
        self._api_key.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def _current_budget_mode(self) -> str:
        for mode, radio in self._budget_modes.items():
            if radio.isChecked():
                return mode
        return "normal"

    def _set_budget_mode(self, mode: str):
        normalized = normalize_budget_mode(mode)
        radio = self._budget_modes.get(normalized)
        if radio is not None:
            radio.setChecked(True)

    def _current_reply_language(self) -> str:
        return normalize_language(str(self._reply_language.currentData() or DEFAULT_LANGUAGE))

    def _set_reply_language(self, value: str):
        normalized = normalize_language(value)
        index = self._reply_language.findData(normalized)
        if index >= 0:
            self._reply_language.setCurrentIndex(index)

    def _current_ui_language_preference(self) -> str:
        return normalize_ui_language(
            str(self._ui_language.currentData() or DEFAULT_UI_LANGUAGE)
        )

    def _resolved_ui_language(self) -> str:
        return _resolved_ui_language(self._current_ui_language_preference())

    def _set_ui_language_preference(self, value: str):
        normalized = normalize_ui_language(value)
        index = self._ui_language.findData(normalized)
        if index >= 0:
            self._ui_language.setCurrentIndex(index)

    def _refresh_language_options(self):
        ui_language = self._resolved_ui_language()
        for index, code in enumerate(self._reply_language_codes):
            self._reply_language.setItemText(
                index,
                _localized_reply_language_label(code, ui_language=ui_language),
            )
        for index, code in enumerate(self._ui_language_codes):
            self._ui_language.setItemText(
                index,
                _localized_ui_language_label(code, ui_language=ui_language),
            )

    def _apply_localized_copy(self):
        ui_language = self._resolved_ui_language()
        english = _ui_uses_english(ui_language)
        self.setWindowTitle("First Run" if english else "第一次见面")
        self._title.setText(
            "Let's settle the API key, boundaries, and permissions first."
            if english
            else "先把 API key、边界和权限说清楚。"
        )
        self._body.setText(
            "Set the key, how I should address you, reply language, interface language, "
            "budget, and the data boundary first.\nYou can reopen setup, permission health, "
            "budget, and privacy later from the context menu."
            if english
            else "先把 key、称呼、回复语言、界面语言、预算和数据边界定好。\n"
            "权限、自检和隐私边界之后都能在右键菜单里再改。"
        )
        self._api_key_label.setText("Claude API key")
        self._show_api_key.setText("Show" if english else "显示")
        self._owner_name_label.setText("How to Address You" if english else "怎么称呼主人")
        self._owner_name.setPlaceholderText(
            "Leave blank to keep the default title."
            if english
            else "留空就继续叫“主人”"
        )
        self._reply_language_label.setText("Reply Language" if english else "回复语言")
        self._ui_language_label.setText("Interface Language" if english else "界面语言")
        self._budget_label.setText("Budget Mode" if english else "预算档位")
        self._boundary_label.setText("Data Boundary" if english else "数据边界")
        self._boundary_body.setText(
            "Regular chat and tool summaries may leave the device; sensitive content stays local by default.\n"
            "Your name, reply language, interface language, budget, and auto-hide stay local; "
            "long-term memory can be edited or deleted item by item."
            if english
            else "普通对话和工具摘要可能离机；高敏内容默认留在本机。\n"
            "称呼、回复语言、界面语言、预算和自动隐藏只记本机；长期记忆可逐条改删。"
        )
        self._data_boundary_ack.setText(
            "I understand and accept this data boundary"
            if english
            else "我知道并接受这条数据边界"
        )
        self._auto_dnd_enabled.setText(
            "Enable automatic do-not-disturb detection"
            if english
            else "开启自动免打扰检测"
        )
        self._auto_hide.setText(
            "Auto-hide the sprite during sharing / recording / presenting"
            if english
            else "共享 / 录屏 / 演示时自动隐藏立绘"
        )
        self._remember.setText(
            "Don't auto-open this setup again"
            if english
            else "以后不再自动弹出这份引导"
        )
        self._later.setText("Later" if english else "稍后")
        self._save.setText("Save Setup" if english else "保存设置")
        self._health.setText("Permission Health" if english else "权限自检")
        self._refresh_language_options()
        for mode in self._budget_mode_codes:
            radio = self._budget_modes.get(mode)
            if radio is not None:
                radio.setText(_localized_budget_mode_label(mode, ui_language=ui_language))

    def _refresh_identity_hint(self):
        ui_language = self._resolved_ui_language()
        reply_label = _localized_reply_language_label(
            self._current_reply_language(),
            ui_language=ui_language,
        )
        interface_label = _localized_ui_language_label(
            self._current_ui_language_preference(),
            ui_language=ui_language,
        )
        reply_description = _localized_reply_language_description(
            self._current_reply_language(),
            ui_language=ui_language,
        )
        ui_description = _localized_ui_language_description(
            self._current_ui_language_preference(),
            ui_language=ui_language,
        )
        if _ui_uses_english(ui_language):
            self._identity_hint.setText(
                "Your preferred name is saved into long-term memory.\n"
                f"Replies: {reply_label}. {reply_description}\n"
                f"Interface: {interface_label}. {ui_description}"
            )
        else:
            self._identity_hint.setText(
                "称呼会记进长期记忆；回复语言会默认沿用，界面语言只影响本机 UI。\n"
                f"回复: {reply_label}。{reply_description}\n"
                f"界面: {interface_label}。{ui_description}"
            )

    def _refresh_budget_hint(self):
        ui_language = self._resolved_ui_language()
        mode = self._current_budget_mode()
        label = _localized_budget_mode_label(mode, ui_language=ui_language)
        description = _localized_budget_mode_description(mode, ui_language=ui_language)
        max_budget_usd = float(BUDGET_MODE_MAX_BUDGET_USD.get(mode, 0.0) or 0.0)
        daily_limit_usd = float(BUDGET_MODE_DAILY_LIMIT_USD.get(mode, 0.0) or 0.0)
        weekly_limit_usd = float(BUDGET_MODE_WEEKLY_LIMIT_USD.get(mode, 0.0) or 0.0)
        if _ui_uses_english(ui_language):
            self._budget_hint.setText(
                f"Current mode: {label}. {description} "
                f"This sets the Agent SDK per-run cap to about ${max_budget_usd:.2f}, "
                f"with daily / weekly hard caps around ${daily_limit_usd:.2f} / ${weekly_limit_usd:.2f}."
            )
        else:
            self._budget_hint.setText(
                f"当前档位: {label}。{description} "
                f"这会把 Agent SDK 的单轮预算上限设为约 ${max_budget_usd:.2f}；"
                f"同时日 / 周硬闸约为 ${daily_limit_usd:.2f} / ${weekly_limit_usd:.2f}。"
            )

    def _refresh_setup_hint(self, message: str = "", error: bool = False):
        ui_language = self._resolved_ui_language()
        if error:
            self._setup_hint.setStyleSheet("color: #a33030;")
            self._setup_hint.setText(message)
            return
        self._setup_hint.setStyleSheet("color: #666;")
        if message:
            self._setup_hint.setText(message)
            return
        self._setup_hint.setText(
            "You can reopen Setup from the context menu, and also check Privacy Boundary, "
            "Budget Status, Long-term Memory, resumed sessions, and remembered approvals there."
            if _ui_uses_english(ui_language)
            else "右键菜单里还能重新打开设置，也能看隐私边界、预算、长期记忆，顺手清续接会话和工具授权。"
        )

    def _refresh_api_key_status(self, message: str = "", error: bool = False):
        ui_language = self._resolved_ui_language()
        status = api_key_status()
        if _ui_uses_english(ui_language):
            if status.source == "env":
                summary = "Claude API key is currently loaded from the environment."
            elif status.source == "keychain":
                summary = "Claude API key is currently saved in Keychain."
            elif status.source == "file":
                summary = "Claude API key is currently saved in a local private file."
            else:
                summary = "Claude API key is not configured yet."
        else:
            if status.source == "env":
                summary = "当前已从环境变量拿到 Claude API key。"
            elif status.source == "keychain":
                summary = "当前已在系统钥匙串里保存 Claude API key。"
            elif status.source == "file":
                summary = "当前已在本机私有文件里保存 Claude API key。"
            else:
                summary = "还没有配置 Claude API key。现在只能开壳，聊不了天。"
        if status.masked_value:
            summary += (
                f"\nCurrent token: {status.masked_value}"
                if _ui_uses_english(ui_language)
                else f"\n当前标识: {status.masked_value}"
            )
        self._api_key_status.setText(summary)
        if error:
            self._api_key_hint.setStyleSheet("color: #a33030;")
            self._api_key_hint.setText(message)
            return
        self._api_key_hint.setStyleSheet("color: #666;")
        if message:
            self._api_key_hint.setText(message)
            return
        if _ui_uses_english(ui_language):
            if status.source == "keychain":
                self._api_key_hint.setText(
                    "The packaged app reads from Keychain first. Paste a new key here to replace it."
                )
            elif status.configured:
                self._api_key_hint.setText(
                    "The current process already has a working API key. Leave this blank to keep using it."
                )
            else:
                self._api_key_hint.setText(
                    "The key is stored only on this Mac. The packaged app prefers Keychain by default."
                )
        else:
            if status.source == "keychain":
                self._api_key_hint.setText("现在会优先从系统钥匙串读取。要换 key，直接在这里贴新的就行。")
            elif status.configured:
                self._api_key_hint.setText("当前进程已经能拿到 API key。这里留空就表示继续沿用。")
            else:
                self._api_key_hint.setText("贴进去后会只保存在本机。打包版默认优先写进系统钥匙串。")

    def _build_decision(self, *, open_health: bool = False) -> OnboardingDecision:
        return OnboardingDecision(
            submitted=False,
            remember=self._remember.isChecked(),
            open_health=open_health,
            api_key_configured=api_key_status().configured,
            owner_name=self._owner_name.text().strip(),
            budget_mode=self._current_budget_mode(),
            reply_language=self._current_reply_language(),
            ui_language=self._current_ui_language_preference(),
            data_boundary_acknowledged=self._data_boundary_ack.isChecked(),
            auto_do_not_disturb_enabled=self._auto_dnd_enabled.isChecked(),
            auto_hide_on_sensitive_scene=self._auto_hide.isChecked(),
        )

    def _save_api_key_if_needed(self, *, required: bool) -> bool | None:
        value = self._api_key.text().strip()
        status = api_key_status()
        english = _ui_uses_english(self._resolved_ui_language())
        if not value:
            if status.configured:
                self._refresh_api_key_status(
                    "Keeping the currently configured API key."
                    if english
                    else "继续沿用当前已经配置好的 API key。"
                )
                return False
            if not required:
                self._refresh_api_key_status(
                    "You can run permission health first and fill the API key later."
                    if english
                    else "你可以先做权限自检，API key 稍后再补。"
                )
                return False
            self._refresh_api_key_status(
                "Enter a Claude API key first, otherwise she is still just a shell."
                if english
                else "先填一个 Claude API key，不然她还是空壳。",
                error=True,
            )
            return None

        try:
            saved_status = save_api_key(value)
        except Exception as exc:
            self._refresh_api_key_status(
                f"Failed to save the API key: {exc}"
                if english
                else f"API key 没存进去: {exc}",
                error=True,
            )
            return None

        self._api_key.clear()
        self._refresh_api_key_status(
            "Claude API key is now saved locally. She can actually speak now."
            if english
            else "已经把 Claude API key 存进本机。接下来她可以真开口了。"
        )
        return saved_status.configured

    def _validate_setup(self, *, require_boundary_ack: bool) -> bool:
        english = _ui_uses_english(self._resolved_ui_language())
        if require_boundary_ack and not self._data_boundary_ack.isChecked():
            self._refresh_setup_hint(
                "Confirm the data boundary first before hiding this setup."
                if english
                else "想让这份引导先收起来，至少先确认一下数据边界。",
                error=True,
            )
            return False
        self._refresh_setup_hint()
        return True

    def _accept_with_save(self):
        saved = self._save_api_key_if_needed(required=True)
        if saved is None:
            return
        if not self._validate_setup(require_boundary_ack=True):
            return
        base = self._build_decision(open_health=False)
        self._decision = OnboardingDecision(**{**base.__dict__, "submitted": True})
        self.accept()

    def _accept_with_health(self):
        saved = self._save_api_key_if_needed(required=False)
        if saved is None:
            return
        english = _ui_uses_english(self._resolved_ui_language())
        self._refresh_setup_hint(
            (
                "You can run permission health first. If the data boundary is still unchecked, "
                "this setup will remind you again later."
                if english
                else "权限自检可以先跑；没确认数据边界的话，这份引导之后还会再提醒你一次。"
            )
            if not self._data_boundary_ack.isChecked() else ""
        )
        base = self._build_decision(open_health=True)
        self._decision = OnboardingDecision(**{**base.__dict__, "submitted": True})
        self.accept()

    def _on_ui_language_changed(self):
        self._apply_localized_copy()
        self._refresh_identity_hint()
        self._refresh_budget_hint()
        self._refresh_api_key_status()
        self._refresh_setup_hint()
        self._sync_dialog_size()

    def _sync_dialog_size(self):
        layout = self.layout()
        if layout is None:
            return
        layout.activate()
        hint = layout.sizeHint()
        width = max(620, int(hint.width()) + 28)
        height = max(560, int(hint.height()) + 28)
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            width = min(width, max(560, geo.width() - 60))
            height = min(height, max(440, geo.height() - 60))
        self.resize(width, height)


class MemoryDeleteConfirmDialog(QDialog):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(True)
        self.resize(380, 220)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QPlainTextEdit {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton#dangerButton {
                background: #fff1f1;
                color: #9f1d1d;
                border: 1px solid #efc0c0;
            }
            QPushButton#dangerButton:hover {
                background: #ffe4e4;
            }
            """
        )
        self._language_pref = DEFAULT_UI_LANGUAGE

        self._title = QLabel(self)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-weight: 600; color: #1f1f1f;")

        self._detail = QLabel(self)
        self._detail.setStyleSheet("color: #666;")

        self._preview = QPlainTextEdit(self)
        self._preview.setReadOnly(True)

        self._cancel = QPushButton(self)
        self._cancel.clicked.connect(self.reject)
        self._delete = QPushButton(self)
        self._delete.setObjectName("dangerButton")
        self._delete.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._cancel)
        row.addWidget(self._delete)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._title)
        layout.addWidget(self._detail)
        layout.addWidget(self._preview, 1)
        layout.addLayout(row)

        self.set_language(self._language_pref)

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Delete Memory" if english else "确认删除")
        self._title.setText(
            "Once this long-term memory is deleted, it is gone."
            if english
            else "这条长期记忆删掉就没了。"
        )
        self._detail.setText("You are deleting:" if english else "要删的是这条：")
        self._cancel.setText("Cancel" if english else "取消")
        self._delete.setText("Delete" if english else "删除")

    def ask_for(self, target: QWidget, text: str) -> bool:
        preview = text.strip() or (
            "(Empty)" if _ui_uses_english(self._language_pref) else "（空白内容）"
        )
        self._preview.setPlainText(preview)
        self.reposition(target)
        self.raise_()
        self.activateWindow()
        return self.exec() == QDialog.Accepted

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() + max(0, (tg.width() - self.width()) // 2)
        y = tg.top() + max(0, (tg.height() - self.height()) // 2)

        if screen is not None:
            geo = screen.availableGeometry()
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)


def _clip_memory_preview(text: str, limit: int = 32) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _format_memory_timestamp(value) -> str:
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))


def _memory_source_excerpt(memory_item: dict[str, object], limit: int = 26) -> str:
    source = str(memory_item.get("source") or "").strip()
    if not source or source in {"manual", "legacy"}:
        return ""
    return _clip_memory_preview(source, limit=limit)


def _localized_memory_reason_text(
    memory_item: dict[str, object],
    *,
    ui_language: str,
) -> str:
    reason_key = str(memory_item.get("reason_key") or "").strip()
    source_excerpt = _memory_source_excerpt(memory_item)
    english = _ui_uses_english(ui_language)

    if english:
        base = {
            "manual": "Added or edited manually in the memory panel.",
            "legacy_import": "Migrated from an older local memory file.",
            "explicit_instruction": "You explicitly asked me to remember it.",
            "address_preference": "This is your addressing preference.",
            "identity_statement": "This is identity information you stated directly.",
            "reply_language_preference": "This is your preferred reply language.",
            "stated_preference": "This is a stable preference you stated directly.",
            "stated_fact": "This is a fact you gave directly.",
            "conversation_note": "This is a long-term note you left on purpose.",
            "conversation_memory": "This was retained from the conversation context.",
        }.get(reason_key, "This was retained from the conversation context.")
        if source_excerpt:
            return f"{base} Source: \"{source_excerpt}\""
        return base

    base = {
        "manual": "你在记忆面板里手动新增或改写了这条。",
        "legacy_import": "这条是从旧版本地记忆文件迁进来的。",
        "explicit_instruction": "你明确要求我记住这件事。",
        "address_preference": "这是你的称呼偏好。",
        "identity_statement": "这是你直接告诉我的身份信息。",
        "reply_language_preference": "这是你的回复语言偏好。",
        "stated_preference": "这是你直接说出的稳定偏好。",
        "stated_fact": "这是你明确给出的事实。",
        "conversation_note": "这是你留给我的长期便签。",
        "conversation_memory": "这是我从当前对话里收下的长期记忆。",
    }.get(reason_key, "这是我从当前对话里收下的长期记忆。")
    if source_excerpt:
        return f"{base} 原话: “{source_excerpt}”"
    return base


def _localized_memory_expiry_text(
    memory_item: dict[str, object],
    *,
    ui_language: str,
) -> str:
    english = _ui_uses_english(ui_language)
    policy_key = str(memory_item.get("expiry_policy_key") or "").strip()
    expires_label = _format_memory_timestamp(memory_item.get("expires_at"))
    days = memory_item.get("expiry_days")
    try:
        day_count = int(days)
    except (TypeError, ValueError):
        day_count = 0

    if policy_key == "forever":
        return (
            "Does not expire automatically; it only changes when you edit or delete it."
            if english
            else "不会自动过期，只会在你手动修改或删除时变化。"
        )

    if english:
        if day_count > 0 and expires_label:
            return (
                f"Default retention is {day_count} days; expected cleanup after {expires_label}. "
                "Expired entries are pruned on read or write."
            )
        if day_count > 0:
            return (
                f"Default retention is {day_count} days. "
                "Expired entries are pruned on read or write."
            )
        if expires_label:
            return (
                f"Expected cleanup after {expires_label}. "
                "Expired entries are pruned on read or write."
            )
        return "Expired entries are pruned on read or write."

    if day_count > 0 and expires_label:
        return f"默认保留 {day_count} 天；预计在 {expires_label} 后清理，读写时会顺手清过期项。"
    if day_count > 0:
        return f"默认保留 {day_count} 天；读写时会顺手清掉已过期的旧内容。"
    if expires_label:
        return f"预计在 {expires_label} 后清理；读写时会顺手清过期项。"
    return "读写时会顺手清掉已过期的旧内容。"


def _localized_memory_conflict_text(
    memory_item: dict[str, object],
    *,
    ui_language: str,
) -> str:
    english = _ui_uses_english(ui_language)
    policy_key = str(memory_item.get("conflict_policy_key") or "").strip()
    if english:
        return {
            "opposite_preference": "Like and dislike for the same thing replace each other; the newest one wins.",
            "same_topic": "Newer values on the same topic overwrite older ones.",
            "parallel_note": "Different notes can coexist; identical text just refreshes the timestamp.",
        }.get(policy_key, "Conflicts prefer the newest confirmed version.")
    return {
        "opposite_preference": "同一对象的喜欢 / 不喜欢会互相替换，以最近一次为准。",
        "same_topic": "同一主题后写覆盖前写，以最新说法为准。",
        "parallel_note": "不同便签会并存；完全相同的内容只会刷新时间。",
    }.get(policy_key, "冲突时会优先保留最近一次确认的版本。")


def _localized_memory_policy_summary(*, ui_language: str) -> str:
    if _ui_uses_english(ui_language):
        return (
            "Policy: notes 30d, facts 90d, like/dislike 180d, and naming / reply defaults / favorite-common stay until you edit or delete them. "
            "Expired entries are cleaned opportunistically on read or write."
        )
    return (
        "策略: 便签 30 天、事实 90 天、喜欢/不喜欢 180 天；称呼、名字、回复语言，以及 favorite/common 这类默认项不会自动过期。"
        "过期内容会在读取或写入时顺手清理。"
    )


def _localized_memory_write_action_label(action: str, *, ui_language: str) -> str:
    normalized = str(action or "").strip()
    if _ui_uses_english(ui_language):
        if normalized == "updated":
            return "Updated"
        if normalized == "replaced":
            return "Replaced"
        return "Created"
    if normalized == "updated":
        return "已更新"
    if normalized == "replaced":
        return "已替换写入"
    return "已新增"


def _memory_replaced_preview(memory_item: dict[str, object], limit: int = 2) -> str:
    replaced_items = [
        dict(item)
        for item in (memory_item.get("replaced_items") or [])
        if isinstance(item, dict)
    ]
    snippets = [
        _clip_memory_preview(str(item.get("text") or ""), limit=24)
        for item in replaced_items[:limit]
        if str(item.get("text") or "").strip()
    ]
    if len(replaced_items) > limit:
        snippets.append(f"... {len(replaced_items)}")
    return " | ".join(snippets)


def _localized_memory_write_receipt(
    memory_item: dict[str, object],
    *,
    ui_language: str,
) -> str:
    english = _ui_uses_english(ui_language)
    replaced_preview = _memory_replaced_preview(memory_item)
    pruned_expired_count = int(memory_item.get("pruned_expired_count") or 0)
    title = "Receipt · Long-term Memory" if english else "状态回执 · 长期记忆"
    lines = [
        f"{'Action' if english else '动作'}: {_localized_memory_write_action_label(memory_item.get('write_action'), ui_language=ui_language)}",
        f"{'Content' if english else '内容'}: {_clip_memory_preview(str(memory_item.get('text') or ''), limit=38)}",
        f"{'Why' if english else '原因'}: {_localized_memory_reason_text(memory_item, ui_language=ui_language)}",
        f"{'Expiry' if english else '过期'}: {_localized_memory_expiry_text(memory_item, ui_language=ui_language)}",
    ]
    if replaced_preview:
        lines.append(
            f"{'Replaced' if english else '覆盖'}: {replaced_preview}"
        )
    else:
        lines.append(
            f"{'Conflict' if english else '冲突'}: {_localized_memory_conflict_text(memory_item, ui_language=ui_language)}"
        )
    if pruned_expired_count > 0:
        lines.append(
            (
                f"Cleanup: pruned {pruned_expired_count} expired memories."
                if english
                else f"清理: 顺手清掉 {pruned_expired_count} 条已过期记忆。"
            )
        )
    return "\n".join([title, *lines])


def _localized_memory_delete_receipt(
    memory_item: dict[str, object],
    *,
    ui_language: str,
) -> str:
    english = _ui_uses_english(ui_language)
    title = "Receipt · Long-term Memory" if english else "状态回执 · 长期记忆"
    lines = [
        f"{'Action' if english else '动作'}: {'Deleted' if english else '已删除'}",
        f"{'Content' if english else '内容'}: {_clip_memory_preview(str(memory_item.get('text') or ''), limit=40)}",
        f"{'Removed From' if english else '来源'}: {'Local long-term memory only' if english else '仅从本机长期记忆里移除'}",
    ]
    return "\n".join([title, *lines])


class MemoryCardWidget(QFrame):
    save_requested = Signal(str, str)
    delete_requested = Signal(str)
    discard_requested = Signal()

    def __init__(
        self,
        memory_item: dict[str, object],
        draft: bool = False,
        *,
        language: str = DEFAULT_UI_LANGUAGE,
    ):
        super().__init__(None)
        self.setObjectName("memoryCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            """
            QFrame#memoryCard {
                background: rgba(255, 255, 255, 245);
                border: 1px solid #d6d6d6;
                border-radius: 8px;
            }
            QLabel {
                color: #1f1f1f;
            }
            QLabel#memoryMeta {
                color: #666;
            }
            QPlainTextEdit {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 6px;
                selection-background-color: #cfe4ff;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton:disabled {
                background: #f4f4f4;
                color: #9b9b9b;
                border: 1px solid #dddddd;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            QPushButton#dangerButton {
                background: #fff1f1;
                color: #9f1d1d;
                border: 1px solid #efc0c0;
            }
            QPushButton#dangerButton:hover {
                background: #ffe4e4;
            }
            """
        )

        self._draft = draft
        self._language_pref = normalize_ui_language(language)
        self._key = ""
        self._text = ""
        self._memory_item: dict[str, object] = {}

        self._meta = QLabel(self)
        self._meta.setObjectName("memoryMeta")
        self._meta.setWordWrap(True)

        self._governance = QLabel(self)
        self._governance.setObjectName("memoryMeta")
        self._governance.setWordWrap(True)

        self._text_label = QLabel(self)
        self._text_label.setWordWrap(True)
        self._text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._editor = QPlainTextEdit(self)
        self._editor.setFixedHeight(92)
        self._editor.textChanged.connect(self._sync_save_enabled)
        self._editor.hide()

        self._edit = QPushButton(self)
        self._edit.clicked.connect(self._begin_edit)
        self._save = QPushButton(self)
        self._save.setObjectName("primaryButton")
        self._save.clicked.connect(self._save_changes)
        self._save.hide()
        self._cancel = QPushButton(self)
        self._cancel.clicked.connect(self._cancel_edit)
        self._cancel.hide()
        self._delete = QPushButton(self)
        self._delete.setObjectName("dangerButton")
        self._delete.clicked.connect(self._delete_card)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(self._edit)
        buttons.addWidget(self._save)
        buttons.addWidget(self._cancel)
        buttons.addStretch(1)
        buttons.addWidget(self._delete)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self._meta)
        layout.addWidget(self._governance)
        layout.addWidget(self._text_label)
        layout.addWidget(self._editor)
        layout.addLayout(buttons)

        self._apply_language()
        self.set_memory(memory_item)
        self._set_editing(self._draft)

    def set_memory(self, memory_item: dict[str, object]):
        self._memory_item = dict(memory_item or {})
        self._key = str(memory_item.get("key") or "")
        self._text = str(memory_item.get("text") or "")
        english = _ui_uses_english(self._language_pref)

        if self._draft:
            self._meta.setText("New long-term memory" if english else "新增一条长期记忆")
            self._governance.setText(
                "This stays local and can be edited or deleted later."
                if english
                else "这条只留在本机，后面也能继续改或删。"
            )
            self._text_label.setText("")
            self._editor.setPlainText(self._text)
            self._sync_save_enabled()
            return

        updated = _format_memory_timestamp(memory_item.get("updated_at"))
        created = _format_memory_timestamp(memory_item.get("created_at"))
        meta_parts = []
        if updated:
            meta_parts.append(f"Updated {updated}" if english else f"更新于 {updated}")
        elif created:
            meta_parts.append(f"Created {created}" if english else f"创建于 {created}")

        last_used = _format_memory_timestamp(memory_item.get("last_used_at"))
        if last_used:
            meta_parts.append(
                f"Used {last_used}" if english else f"最近用到 {last_used}"
            )

        self._meta.setText(
            "  |  ".join(meta_parts) if meta_parts else ("Long-term Memory" if english else "长期记忆")
        )
        governance_lines = [
            f"{'Why' if english else '原因'}: {_localized_memory_reason_text(memory_item, ui_language=self._language_pref)}",
            f"{'Expiry' if english else '过期'}: {_localized_memory_expiry_text(memory_item, ui_language=self._language_pref)}",
            f"{'Conflict' if english else '冲突'}: {_localized_memory_conflict_text(memory_item, ui_language=self._language_pref)}",
        ]
        self._governance.setText("\n".join(governance_lines))
        self._text_label.setText(self._text)
        self._editor.setPlainText(self._text)
        self._sync_save_enabled()

    def _apply_language(self):
        english = _ui_uses_english(self._language_pref)
        self._editor.setPlaceholderText(
            "Write the version you really want me to keep long-term."
            if english
            else "改成你真正想让我长期记住的话。"
        )
        self._edit.setText("Edit" if english else "编辑")
        self._delete.setText("Delete" if english else "删除")

    def _set_editing(self, editing: bool):
        english = _ui_uses_english(self._language_pref)
        if self._draft:
            self._text_label.hide()
            self._editor.show()
            self._edit.hide()
            self._save.show()
            self._save.setText("Create" if english else "新增")
            self._cancel.show()
            self._cancel.setText("Cancel" if english else "取消")
            self._delete.hide()
            self._editor.setFocus(Qt.OtherFocusReason)
            self._sync_save_enabled()
            return

        self._text_label.setVisible(not editing)
        self._editor.setVisible(editing)
        self._edit.setVisible(not editing)
        self._save.setVisible(editing)
        self._save.setText("Save" if english else "保存")
        self._cancel.setVisible(editing)
        self._cancel.setText("Cancel" if english else "取消")
        self._delete.setVisible(not editing)
        if editing:
            self._editor.setFocus(Qt.OtherFocusReason)
            self._editor.selectAll()
        self._sync_save_enabled()

    def _begin_edit(self):
        self._editor.setPlainText(self._text)
        self._set_editing(True)

    def _cancel_edit(self):
        if self._draft:
            self.discard_requested.emit()
            return
        self._editor.setPlainText(self._text)
        self._set_editing(False)

    def _save_changes(self):
        text = self._editor.toPlainText().strip()
        if not text:
            return
        self.save_requested.emit(self._key, text)

    def _delete_card(self):
        if self._draft:
            self.discard_requested.emit()
            return
        self.delete_requested.emit(self._key)

    def _sync_save_enabled(self):
        text = self._editor.toPlainText().strip()
        if self._draft:
            self._save.setEnabled(bool(text))
            return
        self._save.setEnabled(bool(text) and text != self._text)


class LongTermMemoryDialog(QDialog):
    refresh_requested = Signal()
    save_requested = Signal(str, str)
    delete_requested = Signal(str)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(480, 400)
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f7f7;
                color: #1f1f1f;
            }
            QLabel {
                color: #1f1f1f;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QPushButton {
                background: #ffffff;
                color: #1f1f1f;
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background: #f0f0f0;
            }
            QPushButton:disabled {
                background: #f4f4f4;
                color: #9b9b9b;
                border: 1px solid #dddddd;
            }
            QPushButton#primaryButton {
                background: #eaf3ff;
                color: #1d4f91;
                border: 1px solid #bdd6fb;
            }
            QPushButton#primaryButton:hover {
                background: #dcecff;
            }
            QPushButton#dangerButton {
                background: #fff1f1;
                color: #9f1d1d;
                border: 1px solid #efc0c0;
            }
            QPushButton#dangerButton:hover {
                background: #ffe4e4;
            }
            """
        )
        self._language_pref = DEFAULT_UI_LANGUAGE
        self._memories: list[dict[str, object]] = []
        self._draft_visible = False

        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-weight: 600;")

        self._meta = QLabel(self)
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet("color: #666;")

        self._cards_host = QWidget(self)
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)

        self._cards_scroll = QScrollArea(self)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setWidget(self._cards_host)

        self._add = QPushButton(self)
        self._add.setObjectName("primaryButton")
        self._add.clicked.connect(
            lambda _checked=False: self._start_create()
        )
        self._refresh = QPushButton(self)
        self._refresh.clicked.connect(
            lambda _checked=False: self.refresh_requested.emit()
        )
        self._close = QPushButton(self)
        self._close.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addWidget(self._add)
        row.addWidget(self._refresh)
        row.addStretch(1)
        row.addWidget(self._close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._meta)
        layout.addWidget(self._cards_scroll, 1)
        layout.addLayout(row)

        self.set_language(self._language_pref)

    def set_language(self, language: str):
        self._language_pref = normalize_ui_language(language)
        english = _ui_uses_english(self._language_pref)
        self.setWindowTitle("Long-term Memory" if english else "长期记忆")
        self._add.setText("Add" if english else "新增")
        self._refresh.setText("Refresh" if english else "刷新")
        self._close.setText("Close" if english else "关闭")
        self._meta.setText(_localized_memory_policy_summary(ui_language=self._language_pref))
        self._render_cards()

    def show_for(self, target: QWidget, memories: list[dict[str, object]]):
        self.refresh(memories)
        self.reposition(target)
        self.show()
        self.raise_()

    def refresh(self, memories: list[dict[str, object]] | None = None):
        if memories is None:
            return
        self._memories = list(memories)
        self._render_cards()

    def _render_cards(self):
        english = _ui_uses_english(self._language_pref)
        self._clear_cards()
        self._add.setEnabled(not self._draft_visible)
        self._meta.setText(_localized_memory_policy_summary(ui_language=self._language_pref))
        if self._draft_visible:
            draft_card = MemoryCardWidget(
                {
                    "key": "",
                    "text": "",
                },
                draft=True,
                language=self._language_pref,
            )
            draft_card.save_requested.connect(
                lambda key, text, dialog=self: dialog.save_requested.emit(key, text)
            )
            draft_card.discard_requested.connect(self._discard_draft)
            self._cards_layout.addWidget(draft_card)

        if not self._memories:
            if self._draft_visible:
                self._status.setText(
                    "Finish the new memory and it will stay here."
                    if english
                    else "把这条新记忆写好就行。"
                )
            else:
                self._status.setText(
                    "There is no long-term memory yet."
                    if english
                    else "现在还没有长期记忆。"
                )
                empty = QLabel(
                    "This list is currently empty."
                    if english
                    else "这里现在还是空的。",
                    self._cards_host,
                )
                empty.setWordWrap(True)
                empty.setStyleSheet("color: #666; padding: 12px 6px;")
                self._cards_layout.addWidget(empty)
            self._cards_layout.addStretch(1)
            return

        if self._draft_visible:
            self._status.setText(
                f"Draft a new memory. Current total: {len(self._memories)}."
                if english
                else f"先补一条新记忆。现在已有 {len(self._memories)} 条。"
            )
        else:
            self._status.setText(
                f"Currently remembering {len(self._memories)} item(s)."
                if english
                else f"现在记着 {len(self._memories)} 条。"
            )
        for memory_item in self._memories:
            card = MemoryCardWidget(memory_item, language=self._language_pref)
            card.save_requested.connect(
                lambda key, text, dialog=self: dialog.save_requested.emit(key, text)
            )
            card.delete_requested.connect(
                lambda key, dialog=self: dialog.delete_requested.emit(key)
            )
            self._cards_layout.addWidget(card)
        self._cards_layout.addStretch(1)

    def _clear_cards(self):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _start_create(self):
        if self._draft_visible:
            return
        self._draft_visible = True
        self._render_cards()

    def _discard_draft(self):
        if not self._draft_visible:
            return
        self._draft_visible = False
        self._render_cards()

    def finish_create(self):
        if not self._draft_visible:
            return
        self._draft_visible = False

    def reposition(self, target: QWidget):
        tg = target.frameGeometry()
        screen = QApplication.screenAt(tg.center()) or QApplication.primaryScreen()
        x = tg.left() - self.width() - 12
        y = tg.top()

        if screen is not None:
            geo = screen.availableGeometry()
            if x < geo.left():
                x = tg.right() + 12
            max_x = geo.right() - self.width()
            max_y = geo.bottom() - self.height()
            x = min(max(geo.left(), x), max(geo.left(), max_x))
            y = min(max(geo.top(), y), max(geo.top(), max_y))

        self.move(x, y)

class _AutoDndNativeObserver:
    def __init__(self, callback, *, sleep_callback=None, wake_callback=None):
        self._callback = callback
        self._sleep_callback = sleep_callback
        self._wake_callback = wake_callback
        self._registrations: list[tuple[object, object]] = []

    def _notify(self, _note=None):
        callback = self._callback
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            print(f"[dnd:auto] native notification callback failed: {exc}")

    def _notify_sleep(self, _note=None):
        callback = self._sleep_callback
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            print(f"[budget] native sleep callback failed: {exc}")

    def _notify_wake(self, _note=None):
        callback = self._wake_callback
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            print(f"[budget] native wake callback failed: {exc}")

    def start(self):
        if self._registrations or not HAVE_AUTO_DND_NATIVE_NOTIFICATIONS:
            return

        try:
            workspace = NSWorkspace.sharedWorkspace()
            workspace_center = workspace.notificationCenter() if workspace is not None else None
        except Exception:
            workspace_center = None

        try:
            default_center = NSNotificationCenter.defaultCenter()
        except Exception:
            default_center = None

        if workspace_center is None or default_center is None:
            return

        def register(center, name, handler):
            if center is None or not name or handler is None:
                return
            token = center.addObserverForName_object_queue_usingBlock_(
                name,
                None,
                None,
                handler,
            )
            self._registrations.append((center, token))

        register(
            workspace_center,
            NSWorkspaceDidActivateApplicationNotification,
            self._notify,
        )
        register(
            workspace_center,
            NSWorkspaceDidLaunchApplicationNotification,
            self._notify,
        )
        register(
            workspace_center,
            NSWorkspaceDidTerminateApplicationNotification,
            self._notify,
        )
        register(
            workspace_center,
            NSWorkspaceActiveSpaceDidChangeNotification,
            self._notify,
        )
        register(
            default_center,
            NSApplicationDidChangeScreenParametersNotification,
            self._notify,
        )
        if self._sleep_callback is not None:
            register(
                workspace_center,
                NSWorkspaceWillSleepNotification,
                self._notify_sleep,
            )
            register(
                workspace_center,
                NSWorkspaceScreensDidSleepNotification,
                self._notify_sleep,
            )
        if self._wake_callback is not None:
            register(
                workspace_center,
                NSWorkspaceDidWakeNotification,
                self._notify_wake,
            )
            register(
                workspace_center,
                NSWorkspaceScreensDidWakeNotification,
                self._notify_wake,
            )

    def stop(self):
        while self._registrations:
            center, token = self._registrations.pop()
            try:
                center.removeObserver_(token)
            except Exception:
                continue


class MaidWidget(QWidget):
    chat_done = Signal(bool)
    permission_requested = Signal(object)
    question_requested = Signal(object)

    def __init__(self, sprite_pack: SpritePackBundle, bubble: SpeechBubble,
                 asset_dpr: float = DEFAULT_ASSET_DPR,
                 demo_short: bool = False):
        """`sprite_pack` contains aligned QImages grouped by state key."""
        super().__init__(None)
        assert "idle" in sprite_pack.states, "sprite pack must contain an 'idle' entry"

        self._app_state = AppStateStore()
        app_state = self._app_state.snapshot()
        self._asset_dpr = asset_dpr
        self._demo_short = bool(demo_short)
        self._sprite_pack = sprite_pack
        self._sprite_display_scale = _sprite_display_scale_for(sprite_pack, app_state)
        self._effective_asset_dpr = asset_dpr / self._sprite_display_scale
        self._sprites: dict[str, list[dict[str, object]]] = {}
        for key, images in sprite_pack.states.items():
            payloads: list[dict[str, object]] = []
            for img in images:
                pm = QPixmap.fromImage(img)
                pm.setDevicePixelRatio(self._effective_asset_dpr)
                payloads.append({"image": img, "pixmap": pm})
            if payloads:
                self._sprites[key] = payloads
        self._active_sprite_state_key = "idle"
        self._active_sprite_variant_index = 0

        idle_img = sprite_pack.states["idle"][0]
        self._asset_w = round(idle_img.width() / self._effective_asset_dpr)
        self._asset_h = round(idle_img.height() / self._effective_asset_dpr)
        win_w = self._asset_w
        win_h = self._asset_h + PAD_TOP + PAD_BOTTOM

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.resize(win_w, win_h)
        self._bubble = bubble

        # interaction
        self._click_through = None
        self._dragging = False
        self._drag_offset = QPoint()
        self._debug_border = False
        self._last_hit_asset = None
        self._nswindow = None
        self._trigger_now_cb = None
        self._reminder_scheduler: ReminderScheduler | None = None
        self._reminder_first_delay_s: float | None = None
        self._reminder_interval_override_s: float | None = None
        self._do_not_disturb = bool(app_state.do_not_disturb)
        self._auto_do_not_disturb_enabled = bool(
            getattr(app_state, "auto_do_not_disturb_enabled", True)
        )
        self._auto_hide_on_sensitive_scene = bool(app_state.auto_hide_on_sensitive_scene)
        self._auto_do_not_disturb = False
        self._auto_do_not_disturb_reason_key = ""
        self._auto_do_not_disturb_reason = ""
        self._auto_do_not_disturb_detail = ""
        self._auto_do_not_disturb_frontmost_app_name = ""
        self._auto_do_not_disturb_frontmost_bundle_id = ""
        self._auto_do_not_disturb_updated_at = 0.0
        self._auto_hidden = False
        self._auto_dnd_refresh_queued = False
        self._deferred_alert_line: str | None = None
        self._deferred_alert_style = "plain"
        self._next_deferred_flush_at = 0.0
        self._outing_store = OutingStateStore()
        self._outing_catalog = load_outing_catalog(ASSETS)
        self._chat_dialog = ChatInputDialog()
        self._chat_dialog.submitted.connect(self.submit_prompt)
        self._permission_dialog = PermissionDialog()
        self._question_dialog = AskUserQuestionDialog()
        self._trace_dialog = ThoughtTraceDialog()
        self._permission_health_dialog = PermissionHealthDialog()
        self._budget_status_dialog = BudgetStatusDialog()
        self._privacy_boundary_dialog = PrivacyBoundaryDialog()
        self._sprite_pack_picker_dialog = SpritePackPickerDialog()
        self._sprite_pack_info_dialog = SpritePackInfoDialog()
        self._outing_collection_dialog = OutingCollectionDialog()
        self._auto_dnd_status_dialog = AutoDoNotDisturbDialog()
        self._reminder_settings_dialog = ReminderSettingsDialog()
        self._sprite_display_settings_dialog = SpriteDisplaySettingsDialog()
        self._memory_dialog = LongTermMemoryDialog()
        self._memory_delete_dialog = MemoryDeleteConfirmDialog()
        self._onboarding_dialog = OnboardingDialog()
        self._recent_privacy_events: list[ChatTraceEvent] = []
        self._trace_enabled = True
        self._pending_permission_future = None
        self._pending_question_future = None
        self._permission_health_thread = None
        self._permission_health_worker = None
        self.permission_requested.connect(self._show_permission_request)
        self.question_requested.connect(self._show_question_request)
        self._trace_dialog.close_requested.connect(self._disable_trace_dialog)
        self._permission_health_dialog.refresh_requested.connect(
            self._refresh_permission_health_dialog
        )
        self._budget_status_dialog.refresh_requested.connect(
            self._refresh_budget_status_dialog
        )
        self._privacy_boundary_dialog.refresh_requested.connect(
            self._refresh_privacy_boundary_dialog
        )
        self._sprite_pack_info_dialog.choose_requested.connect(self._show_sprite_pack_picker)
        self._sprite_pack_info_dialog.open_folder_requested.connect(
            self._open_user_sprite_pack_folder
        )
        self._outing_collection_dialog.refresh_requested.connect(
            self._refresh_outing_collection_dialog
        )
        self._auto_dnd_status_dialog.refresh_requested.connect(
            self._refresh_auto_dnd_status_dialog
        )
        self._reminder_settings_dialog.saved.connect(self._save_reminder_preferences)
        self._sprite_display_settings_dialog.saved.connect(
            self._save_sprite_display_preferences
        )
        self._memory_dialog.refresh_requested.connect(self._refresh_memory_dialog)
        self._memory_dialog.save_requested.connect(self._save_long_term_memory_item)
        self._memory_dialog.delete_requested.connect(self._delete_long_term_memory_item)
        self._apply_ui_language_to_dialogs()
        set_permission_handler(self._request_permission)
        set_ask_user_question_handler(self._request_question)
        self._chat_thread = None
        self._chat_worker = None

        # animation
        self._t0 = time.monotonic()
        self._y_offset = 0
        self._eye_closed = False
        self._blink_end_at = None
        self._blink_next_at = self._t0 + random.uniform(*BLINK_INTERVAL)
        self._blink_paused = False

        # state machine
        self._state = MaidState.IDLE
        self._state_entered_at = self._t0
        # emote: independent of main state, time-bound flash
        self._emote_until = None
        self._emote_key = "excited"
        # transitional overlays (time-bound, fire-and-forget)
        self._enter_until = (self._t0 + ENTER_DURATION_S) if "enter" in self._sprites else None
        self._exiting = False
        # IDLE mood substate: "default" / "sleepy" / "peckish"
        self._mood = "default"
        self._mood_until = 0.0
        self._last_activity_at = self._t0
        self._outing_active = False
        self._outing_origin = ""
        self._outing_reason = ""
        self._outing_started_at = 0.0
        self._outing_return_at = 0.0
        self._outing_auto_return = False
        self._sleepy_after_s  = DEMO_SLEEPY_AFTER_S  if demo_short else SLEEPY_AFTER_S
        self._peckish_after_s = DEMO_PECKISH_AFTER_S if demo_short else PECKISH_AFTER_S
        self._sleepy_repeat_s = DEMO_SLEEPY_REPEAT_S if demo_short else SLEEPY_REPEAT_S
        self._peckish_repeat_s = DEMO_PECKISH_REPEAT_S if demo_short else PECKISH_REPEAT_S
        self._next_sleepy_at = self._t0 + self._sleepy_after_s
        self._next_peckish_at = self._t0 + self._peckish_after_s
        # idle quips + lifecycle lines (脚本台词 §三 / §四): scripted, no API spend.
        self._idle_quip_after_s  = DEMO_IDLE_QUIP_AFTER_S  if demo_short else IDLE_QUIP_AFTER_S
        self._idle_quip_repeat_s = DEMO_IDLE_QUIP_REPEAT_S if demo_short else IDLE_QUIP_REPEAT_S
        self._next_idle_quip_at = self._t0 + self._idle_quip_after_s
        self._last_idle_quip_line = ""
        self._last_lifecycle_line = ""
        # hunger (budget-driven): initial stage comes from the current snapshot,
        # so a restart never re-announces an old threshold crossing.
        try:
            self._hunger_state = evaluate_hunger(get_budget_guard_snapshot())
        except Exception as exc:
            print(f"[hunger] initial snapshot failed: {exc}")
            self._hunger_state = HungerState()
        self._hunger_announcer = HungerAnnouncer(
            {
                HUNGER_STAGE_PECKISH: HUNGER_PECKISH_LINES,
                HUNGER_STAGE_HUNGRY: HUNGER_HUNGRY_LINES,
                HUNGER_STAGE_STARVING: HUNGER_STARVING_LINES,
            },
            HUNGER_FULL_LINES,
            initial_stage=self._hunger_state.stage,
        )
        if self._hunger_state.stage != HUNGER_STAGE_NORMAL:
            print(
                f"[hunger] startup stage={self._hunger_state.stage} "
                f"ratio={self._hunger_state.ratio} scope={self._hunger_state.scope or 'n/a'}"
            )
        self._last_state_key = self._current_state_key()
        self._select_sprite_variant(self._last_state_key)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(TICK_MS)
        self._auto_dnd_timer = QTimer(self)
        self._auto_dnd_timer.timeout.connect(self._schedule_auto_do_not_disturb_refresh)
        if self._auto_do_not_disturb_enabled:
            self._auto_dnd_timer.start(AUTO_DND_POLL_MS)
        self._budget_notice_timer = QTimer(self)
        self._budget_notice_timer.timeout.connect(self._poll_budget_reset_notice)
        self._budget_notice_timer.start(BUDGET_NOTICE_POLL_MS)
        self._auto_dnd_native_observer = _AutoDndNativeObserver(
            self._schedule_auto_do_not_disturb_refresh,
            sleep_callback=self._on_system_will_sleep,
            wake_callback=self._on_system_did_wake,
        )
        if self._auto_do_not_disturb_enabled:
            self._auto_dnd_native_observer.start()
            QTimer.singleShot(1200, self._schedule_auto_do_not_disturb_refresh)
        QTimer.singleShot(1800, self._poll_budget_reset_notice)
        record_budget_activity()

        screen = QApplication.primaryScreen()
        screen_dpr = screen.devicePixelRatio() if screen is not None else 1.0
        states = ",".join(self._sprites.keys())
        print(f"[diag] sprite-pack={self._sprite_pack.pack_id} source={self._sprite_pack.source}")
        if (
            self._sprite_pack.metadata.author
            or self._sprite_pack.metadata.tags
            or self._sprite_pack.metadata.description
        ):
            print(
                f"[diag] sprite-pack-meta name={self._sprite_pack.name!r} "
                f"author={self._sprite_pack.metadata.author or 'n/a'!r} "
                f"preview={self._sprite_pack.metadata.preview_pose!r} "
                f"tags={list(self._sprite_pack.metadata.tags)!r}"
            )
        print(f"[diag] screen dpr={screen_dpr}  canvas={idle_img.width()}x{idle_img.height()}px "
              f"@{self._effective_asset_dpr:.3g}x effective "
              f"(base={asset_dpr:g}x scale={self._sprite_display_scale:g})  "
              f"asset_logical={self._asset_w}x{self._asset_h}  "
              f"window={win_w}x{win_h}  sample_factor={idle_img.width()/self._asset_w:.3f}  "
              f"states=[{states}]")

    # ---------- state -> sprite resolution ----------
    # Priority: EXIT > ENTER > ALERT > HELD > emote > outing > starving > hungry
    # > peckish > sleepy > blink > idle.
    # EXIT and ENTER are transitional overlays; ALERT is the main "talking"
    # state; HELD is direct pointer drag feedback; emote (excited/full) is a
    # brief reaction; outing is a local autonomous state; starving/hungry are
    # budget-driven persistent idle replacements; peckish/sleepy are short
    # ambient inserts; blink interrupts only the default idle.
    def _current_state_key(self) -> str:
        if self._exiting and "exit" in self._sprites:
            return "exit"
        now = time.monotonic()
        if (self._enter_until is not None and now < self._enter_until
                and "enter" in self._sprites):
            return "enter"
        if self._state == MaidState.ALERT and "alert" in self._sprites:
            return "alert"
        if self._dragging and "held" in self._sprites:
            return "held"
        if (self._emote_until is not None and now < self._emote_until
                and self._emote_key in self._sprites):
            return self._emote_key
        if self._outing_active and "outing" in self._sprites:
            return "outing"
        # hunger stages (budget-driven) replace idle while they hold;
        # packs without the dedicated forms degrade to peckish.
        if self._hunger_state.stage == HUNGER_STAGE_STARVING:
            if "starving" in self._sprites:
                return "starving"
            if "peckish" in self._sprites:
                return "peckish"
        if self._hunger_state.stage == HUNGER_STAGE_HUNGRY:
            if "hungry" in self._sprites:
                return "hungry"
            if "peckish" in self._sprites:
                return "peckish"
        # IDLE mood substates
        if self._mood == "peckish" and "peckish" in self._sprites:
            return "peckish"
        if self._mood == "sleepy" and "sleepy" in self._sprites:
            return "sleepy"
        if self._eye_closed and "blink" in self._sprites:
            return "blink"
        return "idle"

    def play_emote(self, key: str = "excited", duration_s: float = EMOTE_DURATION_S):
        """Show an emote sprite briefly. No-op if the sprite isn't in the set."""
        if key not in self._sprites:
            return
        if self._state == MaidState.ALERT or self._exiting:
            return  # those states win anyway; emote would be invisible
        self._emote_key = key
        self._emote_until = time.monotonic() + duration_s
        print(f"[emote] {key} for {duration_s}s")

    def _select_sprite_variant(self, state_key: str):
        variants = list(self._sprites.get(state_key) or [])
        if not variants:
            self._active_sprite_state_key = "idle"
            self._active_sprite_variant_index = 0
            return
        self._active_sprite_state_key = state_key
        if len(variants) <= 1:
            self._active_sprite_variant_index = 0
            return
        self._active_sprite_variant_index = random.randrange(len(variants))

    def _active_sprite_payload(self) -> dict[str, object]:
        variants = list(self._sprites.get(self._active_sprite_state_key) or [])
        if not variants:
            variants = list(self._sprites.get("idle") or [])
            self._active_sprite_state_key = "idle"
            self._active_sprite_variant_index = 0
        if not variants:
            raise RuntimeError("no idle sprite payload available")
        index = min(max(0, int(self._active_sprite_variant_index)), len(variants) - 1)
        return variants[index]

    def _set_deferred_alert(self, line: str, *, style: str = "plain"):
        self._deferred_alert_line = str(line or "")
        self._deferred_alert_style = (
            "receipt" if str(style or "").strip().lower() == "receipt" else "plain"
        )

    def _clear_deferred_alert(self):
        self._deferred_alert_line = None
        self._deferred_alert_style = "plain"

    def _begin_outing(
        self,
        origin: str,
        reason: str = "",
        *,
        auto_return: bool = True,
        duration_s: float | None = None,
        announce: bool = False,
    ) -> bool:
        if self._outing_active:
            return False

        now = time.monotonic()
        self._outing_active = True
        self._outing_origin = str(origin or "").strip() or "default"
        self._outing_reason = str(reason or "").strip()
        self._outing_started_at = now
        resolved_duration_s = float(duration_s) if duration_s is not None else float(
            outing_duration_seconds(demo_short=self._demo_short)
        )
        self._outing_auto_return = bool(auto_return)
        self._outing_return_at = (
            now + max(0.0, resolved_duration_s)
            if self._outing_auto_return
            else 0.0
        )
        self._outing_store.record_departure()
        if self._outing_collection_dialog.isVisible():
            self._refresh_outing_collection_dialog()
        if self._state == MaidState.ALERT:
            self.end_alert()
        if self._active_sprite_state_key != "outing":
            self._select_sprite_variant("outing")
        self.update()
        print(
            f"[outing] depart origin={self._outing_origin!r} "
            f"reason={self._outing_reason!r} auto_return={self._outing_auto_return} "
            f"return_in={resolved_duration_s if self._outing_auto_return else 'manual'}"
        )
        if announce:
            self.show_alert(outing_departure_line(self._outing_origin), force=False)
        return True

    def _fallback_outing_result(self) -> OutingResult:
        return OutingResult(
            kind="event",
            key="fallback",
            title="见闻",
            summary="外面还行，我替你看过了。",
            detail="这次没捎回收藏品，先把出门态跑通了。",
        )

    def _finish_outing(
        self,
        *,
        result: OutingResult | None = None,
        extra_note: str = "",
    ) -> bool:
        if not self._outing_active:
            return False

        now = time.monotonic()
        origin = self._outing_origin
        duration_s = max(0.0, now - float(self._outing_started_at or now))
        try:
            resolved_result = result or pick_outing_result(self._outing_catalog)
        except Exception as exc:
            print(f"[outing] result pick failed: {exc}")
            resolved_result = self._fallback_outing_result()

        snapshot, collectable_count = self._outing_store.record_return(
            resolved_result,
            duration_s=duration_s,
        )

        self._outing_active = False
        self._outing_origin = ""
        self._outing_reason = ""
        self._outing_started_at = 0.0
        self._outing_return_at = 0.0
        self._outing_auto_return = False
        self._record_activity()
        self.update()

        note = str(extra_note or "").strip()
        line = format_outing_return_message(
            resolved_result,
            collectable_count=collectable_count,
            extra_note=note,
        )
        print(
            f"[outing] return kind={resolved_result.kind!r} key={resolved_result.key!r} "
            f"origin={origin!r} duration={duration_s:.1f}s "
            f"collectables={snapshot.total_collectable_items}"
        )
        if self._outing_collection_dialog.isVisible():
            self._refresh_outing_collection_dialog()
        if self._state == MaidState.ALERT:
            self._set_deferred_alert(line, style="receipt")
        else:
            self.show_alert(line, force=False, style="receipt")
        return True

    def _record_activity(self):
        """User interacted — reset the 'no recent activity' timer (clears
        SLEEPY mood next tick)."""
        now = time.monotonic()
        self._last_activity_at = now
        self._next_sleepy_at = now + self._sleepy_after_s
        # an idle quip only fires after a fresh stretch of inactivity.
        self._next_idle_quip_at = now + self._idle_quip_after_s
        if self._mood in {"sleepy", "peckish"}:
            print(f"[mood] {self._mood} -> default  (activity)")
            self._mood = "default"
            self._mood_until = 0.0
        record_budget_activity()

    def _poll_budget_reset_notice(self):
        if self._budget_status_dialog.isVisible():
            self._refresh_budget_status_dialog()

        previous_stage = self._hunger_state.stage
        try:
            self._hunger_state = evaluate_hunger(get_budget_guard_snapshot())
        except Exception as exc:
            print(f"[hunger] snapshot failed: {exc}")
        if self._hunger_state.stage != previous_stage:
            print(
                f"[hunger] stage {previous_stage} -> {self._hunger_state.stage} "
                f"ratio={self._hunger_state.ratio} scope={self._hunger_state.scope or 'n/a'}"
            )
        announcement = self._hunger_announcer.observe(self._hunger_state)

        message = consume_budget_reset_notice().strip()
        if message:
            print(f"[budget] reset notice: {message!r}")
            if announcement is not None and announcement.kind == "full":
                # 回血报喜和正式回执合并成一条气泡，免得两条提醒抢同一个嘴。
                self._play_hunger_full_emote()
                self.show_alert(f"{announcement.line}\n\n{message}", force=False)
            else:
                self.show_alert(message, force=False)
            return

        if announcement is None:
            return
        print(f"[hunger] announce {announcement.kind}/{announcement.stage}: {announcement.line!r}")
        if announcement.kind == "full":
            self._play_hunger_full_emote()
        self.show_alert(announcement.line, force=False)

    def _play_hunger_full_emote(self):
        if "full" in self._sprites:
            self.play_emote("full", duration_s=EMOTE_DURATION_S * 2)
        else:
            self.play_emote("excited")

    def _on_system_will_sleep(self):
        note_budget_suspend()
        print("[budget] system sleep noted")

    def _on_system_did_wake(self):
        note_budget_resume()
        print("[budget] system wake noted")
        self._schedule_auto_do_not_disturb_refresh()
        self._poll_budget_reset_notice()

    def _update_mood(self, now: float):
        """Recompute mood from uptime + recent-activity timers. No-op while
        a transitional overlay (enter/exit) is in flight."""
        if self._exiting:
            return
        if self._enter_until is not None and now < self._enter_until:
            return
        uptime = now - self._t0
        quiet_for = now - self._last_activity_at

        if self._mood != "default":
            if now < self._mood_until:
                return
            old_mood = self._mood
            self._mood = "default"
            self._mood_until = 0.0
            print(f"[mood] {old_mood} -> default  "
                  f"(uptime={uptime:.1f}s, quiet_for={quiet_for:.1f}s)")
            return

        if now >= self._next_peckish_at and "peckish" in self._sprites:
            self._mood = "peckish"
            self._mood_until = now + PECKISH_DURATION_S
            self._next_peckish_at = now + self._peckish_repeat_s
        elif (
            quiet_for > self._sleepy_after_s
            and now >= self._next_sleepy_at
            and "sleepy" in self._sprites
        ):
            self._mood = "sleepy"
            self._mood_until = now + SLEEPY_DURATION_S
            self._next_sleepy_at = now + self._sleepy_repeat_s

        if self._mood != "default":
            print(f"[mood] default -> {self._mood}  "
                  f"(uptime={uptime:.1f}s, quiet_for={quiet_for:.1f}s)")

    def _idle_quip_allowed(self, now: float) -> bool:
        """Idle quips are pure flavor — only emit them when the maid is plainly
        idle and free to speak. If blocked we just skip (drop, never queue), so a
        stale quip can't pop up later at a bad moment."""
        if not IDLE_QUIP_LINES:
            return False
        if self._exiting or self._outing_active:
            return False
        if self._state != MaidState.IDLE:
            return False
        if self._enter_until is not None and now < self._enter_until:
            return False
        if (now - self._last_activity_at) < self._idle_quip_after_s:
            return False
        if self._effective_do_not_disturb() or self._is_busy_for_deferred_alerts():
            return False
        return True

    def _maybe_idle_quip(self, now: float):
        """Low-frequency standby aside (脚本台词 §三). Scripted, no API spend."""
        if now < self._next_idle_quip_at:
            return
        if not self._idle_quip_allowed(now):
            # conditions not met yet — retry on a later tick without resetting the
            # long repeat gap, so the next eligible moment still fires promptly.
            return
        line = pick_hunger_line(IDLE_QUIP_LINES, last_line=self._last_idle_quip_line)
        if not line:
            return
        self._last_idle_quip_line = line
        self._next_idle_quip_at = now + self._idle_quip_repeat_s
        print(f"[idle-quip] {line!r}")
        self.show_alert(line)

    def speak_launch_line(self):
        """Greeting on startup (脚本台词 §四). Optional flavor: skip silently if
        onboarding is up, the maid is busy/quitting, or do-not-disturb is on."""
        if not LIFECYCLE_LAUNCH_LINES or self._exiting:
            return
        if self._onboarding_dialog.isVisible():
            return
        if self._effective_do_not_disturb() or self._is_busy_for_deferred_alerts():
            return
        if self._state != MaidState.IDLE:
            return
        line = pick_hunger_line(LIFECYCLE_LAUNCH_LINES, last_line=self._last_lifecycle_line)
        if not line:
            return
        self._last_lifecycle_line = line
        print(f"[lifecycle] launch {line!r}")
        self.show_alert(line)

    def _blink_allowed(self, now: float) -> bool:
        """Blink is only allowed while the visual state is the plain idle pose."""
        if "blink" not in self._sprites:
            return False
        if self._exiting or self._state != MaidState.IDLE:
            return False
        if self._dragging:
            return False
        if self._outing_active:
            return False
        if self._mood != "default":
            return False
        if self._enter_until is not None and now < self._enter_until:
            return False
        if (
            self._emote_until is not None
            and now < self._emote_until
            and "excited" in self._sprites
        ):
            return False
        return True

    def begin_exit(self):
        """Start the EXIT transition. Schedules QApplication.quit after the
        exit sprite has had a moment to show. No-op on repeated calls."""
        if self._exiting:
            return
        self._exiting = True
        if self._reminder_scheduler is not None:
            self._reminder_scheduler.stop()
        self._auto_dnd_timer.stop()
        self._budget_notice_timer.stop()
        self._auto_dnd_native_observer.stop()
        # farewell line (脚本台词 §四): linger it in the bubble through the exit
        # animation. Skip during do-not-disturb / sensitive scenes, or when there's
        # no exit sprite to dwell on (we'd quit before it could be read).
        farewell = ""
        if (
            LIFECYCLE_QUIT_LINES
            and "exit" in self._sprites
            and not self._effective_do_not_disturb()
        ):
            farewell = pick_hunger_line(
                LIFECYCLE_QUIT_LINES, last_line=self._last_lifecycle_line
            )
        if farewell:
            self._last_lifecycle_line = farewell
            print(f"[lifecycle] quit {farewell!r}")
            self._bubble.show_at(farewell, self, style="plain")
        else:
            self._bubble.hide()
        self._chat_dialog.hide()
        self._permission_dialog.hide()
        self._question_dialog.hide()
        self._trace_dialog.hide()
        self._permission_health_dialog.hide()
        self._privacy_boundary_dialog.hide()
        self._sprite_pack_picker_dialog.reject()
        self._sprite_pack_info_dialog.hide()
        self._outing_collection_dialog.hide()
        self._auto_dnd_status_dialog.hide()
        self._reminder_settings_dialog.hide()
        self._sprite_display_settings_dialog.hide()
        self._memory_dialog.hide()
        self._memory_delete_dialog.reject()
        self._onboarding_dialog.reject()
        if self._pending_permission_future is not None and not self._pending_permission_future.done():
            self._pending_permission_future.set_result(PermissionDecision(allow=False))
        if self._pending_question_future is not None and not self._pending_question_future.done():
            self._pending_question_future.set_result(
                AskUserQuestionDecision(
                    cancelled=True,
                    message="主人结束了这次澄清。",
                )
            )
        if "exit" in self._sprites:
            print(f"[exit] transition for {EXIT_DURATION_S}s, then quit")
            QTimer.singleShot(int(EXIT_DURATION_S * 1000), self._quit_when_idle)
        else:
            print("[exit] no exit sprite; quitting immediately")
            self._quit_when_idle()
        self.update()

    def _quit_when_idle(self):
        if self._chat_thread is not None and self._chat_thread.isRunning():
            QTimer.singleShot(100, self._quit_when_idle)
            return
        QApplication.instance().quit()

    def _current_pixmap(self) -> QPixmap:
        current_state_key = self._current_state_key()
        if current_state_key != self._active_sprite_state_key:
            self._select_sprite_variant(current_state_key)
        return self._active_sprite_payload()["pixmap"]

    def _current_alpha_image(self) -> QImage:
        current_state_key = self._current_state_key()
        if current_state_key != self._active_sprite_state_key:
            self._select_sprite_variant(current_state_key)
        return self._active_sprite_payload()["image"]

    # ---------- chat ----------
    def open_input(self, initial_text: str = "", auto_submit: bool = False):
        if isinstance(initial_text, bool):
            initial_text = ""
        self._record_activity()
        self._chat_dialog.show_for(self, text=initial_text, auto_submit=auto_submit)

    def _request_permission(self, request: PermissionRequest) -> PermissionDecision:
        future = Future()
        self.permission_requested.emit((request, future))
        return future.result()

    def _request_question(self, request: AskUserQuestionRequest) -> AskUserQuestionDecision:
        future = Future()
        self.question_requested.emit((request, future))
        return future.result()

    def _sprite_pack_preference(self) -> str:
        return str(self._app_state.snapshot().sprite_pack_id or "").strip()

    def _persist_sprite_pack_preference(self, pack_id: str):
        self._app_state.set_sprite_pack_id(pack_id)

    def _available_sprite_pack_summaries(self) -> list[SpritePackSummary]:
        return describe_available_sprite_packs(ASSETS)

    def _current_auto_do_not_disturb_state(self) -> AutoDoNotDisturbState:
        return AutoDoNotDisturbState(
            active=self._auto_do_not_disturb,
            reason_key=self._auto_do_not_disturb_reason_key,
            reason_text=self._auto_do_not_disturb_reason,
            detail=self._auto_do_not_disturb_detail,
            frontmost_app_name=self._auto_do_not_disturb_frontmost_app_name,
            frontmost_bundle_id=self._auto_do_not_disturb_frontmost_bundle_id,
            updated_at=self._auto_do_not_disturb_updated_at or time.time(),
        )

    def _ui_language_preference(self) -> str:
        return normalize_ui_language(self._app_state.snapshot().ui_language)

    def _current_reminder_rules(self) -> list[ReminderRule]:
        return _reminder_rules_from_snapshot(
            self._app_state.snapshot(),
            first_delay_s=self._reminder_first_delay_s,
            interval_override_s=self._reminder_interval_override_s,
        )

    def _configure_reminder_scheduler(
        self,
        scheduler: ReminderScheduler | None = None,
        *,
        first_delay_s: float | None = None,
        interval_override_s: float | None = None,
    ):
        if scheduler is not None:
            self._reminder_scheduler = scheduler
            self._reminder_first_delay_s = first_delay_s
            self._reminder_interval_override_s = interval_override_s
        else:
            if first_delay_s is not None:
                self._reminder_first_delay_s = first_delay_s
            if interval_override_s is not None:
                self._reminder_interval_override_s = interval_override_s
        if self._reminder_scheduler is None:
            return
        self._reminder_scheduler.configure(self._current_reminder_rules())
        self._trigger_now_cb = self._reminder_scheduler.trigger_now

    def _show_reminder_settings_dialog(self):
        self._reminder_settings_dialog.set_language(self._ui_language_preference())
        self._reminder_settings_dialog.show_for(self, self._app_state.snapshot())

    def _show_sprite_display_settings_dialog(self):
        self._sprite_display_settings_dialog.set_language(self._ui_language_preference())
        self._sprite_display_settings_dialog.show_for(self, self._app_state.snapshot())

    def _target_screen_for_sprite_display(self, snapshot: AppStateSnapshot | None = None):
        snapshot = snapshot or self._app_state.snapshot()
        mode = str(getattr(snapshot, "sprite_screen_mode", DEFAULT_SPRITE_SCREEN_MODE)
                   or DEFAULT_SPRITE_SCREEN_MODE)
        if mode == SPRITE_SCREEN_MODE_CURSOR:
            screen = QApplication.screenAt(QCursor.pos())
            if screen is not None:
                return screen
        return QApplication.primaryScreen() or QApplication.screenAt(self.frameGeometry().center())

    def move_to_saved_start_position(self, snapshot: AppStateSnapshot | None = None):
        snapshot = snapshot or self._app_state.snapshot()
        screen = self._target_screen_for_sprite_display(snapshot)
        if screen is None:
            self.move(100, 100)
            return

        geo = screen.availableGeometry()
        x_percent = _bounded_percent(
            getattr(snapshot, "sprite_position_x_percent", DEFAULT_SPRITE_POSITION_X_PERCENT),
            fallback=DEFAULT_SPRITE_POSITION_X_PERCENT,
        )
        y_percent = _bounded_percent(
            getattr(snapshot, "sprite_position_y_percent", DEFAULT_SPRITE_POSITION_Y_PERCENT),
            fallback=DEFAULT_SPRITE_POSITION_Y_PERCENT,
        )
        x_span = max(0, geo.width() - self.width())
        y_span = max(0, geo.height() - self.height())
        x = geo.left() + round(x_span * x_percent / 100.0)
        y = geo.top() + round(y_span * y_percent / 100.0)
        self.move(x, y)

    def _reposition_attached_windows(self):
        if self._bubble.isVisible():
            self._bubble.reposition(self)
        if self._trace_dialog.isVisible():
            self._trace_dialog.reposition(self)
        if self._permission_health_dialog.isVisible():
            self._permission_health_dialog.reposition(self)
        if self._budget_status_dialog.isVisible():
            self._budget_status_dialog.reposition(self)
        if self._privacy_boundary_dialog.isVisible():
            self._privacy_boundary_dialog.reposition(self)
        if self._sprite_pack_info_dialog.isVisible():
            self._sprite_pack_info_dialog.reposition(self)
        if self._outing_collection_dialog.isVisible():
            self._outing_collection_dialog.reposition(self)
        if self._auto_dnd_status_dialog.isVisible():
            self._auto_dnd_status_dialog.reposition(self)
        if self._reminder_settings_dialog.isVisible():
            self._reminder_settings_dialog.reposition(self)
        if self._sprite_display_settings_dialog.isVisible():
            self._sprite_display_settings_dialog.reposition(self)
        if self._memory_dialog.isVisible():
            self._memory_dialog.reposition(self)

    def _apply_sprite_size_from_preferences(self):
        center = self.frameGeometry().center()
        sprite_pack = self._sprite_pack
        sprites: dict[str, list[dict[str, object]]] = {}
        display_scale = _sprite_display_scale_for(sprite_pack, self._app_state.snapshot())
        effective_dpr = self._asset_dpr / display_scale
        for key, images in sprite_pack.states.items():
            payloads: list[dict[str, object]] = []
            for img in images:
                pm = QPixmap.fromImage(img)
                pm.setDevicePixelRatio(effective_dpr)
                payloads.append({"image": img, "pixmap": pm})
            if payloads:
                sprites[key] = payloads

        idle_img = sprite_pack.states["idle"][0]
        self._sprite_display_scale = display_scale
        self._effective_asset_dpr = effective_dpr
        self._sprites = sprites
        self._asset_w = round(idle_img.width() / self._effective_asset_dpr)
        self._asset_h = round(idle_img.height() / self._effective_asset_dpr)
        self.resize(self._asset_w, self._asset_h + PAD_TOP + PAD_BOTTOM)
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        if self._active_sprite_state_key not in self._sprites:
            self._active_sprite_state_key = "idle"
            self._active_sprite_variant_index = 0
        self.update()
        self._reposition_attached_windows()

    def _save_sprite_display_preferences(self, preferences):
        if not isinstance(preferences, dict):
            preferences = {}
        snapshot = self._app_state.set_sprite_display_preferences(
            sprite_size_percent=preferences.get(
                "sprite_size_percent",
                DEFAULT_SPRITE_SIZE_PERCENT,
            ),
            sprite_position_x_percent=preferences.get(
                "sprite_position_x_percent",
                DEFAULT_SPRITE_POSITION_X_PERCENT,
            ),
            sprite_position_y_percent=preferences.get(
                "sprite_position_y_percent",
                DEFAULT_SPRITE_POSITION_Y_PERCENT,
            ),
            sprite_screen_mode=str(
                preferences.get("sprite_screen_mode", DEFAULT_SPRITE_SCREEN_MODE)
                or DEFAULT_SPRITE_SCREEN_MODE
            ),
        )
        self._apply_sprite_size_from_preferences()
        self.move_to_saved_start_position(snapshot)
        self._reposition_attached_windows()
        print(
            f"[display] saved size={snapshot.sprite_size_percent}% "
            f"x={snapshot.sprite_position_x_percent}% y={snapshot.sprite_position_y_percent}% "
            f"screen={snapshot.sprite_screen_mode}"
        )
        self.show_alert("桌面显示设置已保存。", force=True, style="receipt")

    def _save_reminder_preferences(self, preferences):
        if not isinstance(preferences, dict):
            preferences = {}
        snapshot = self._app_state.set_reminder_preferences(
            reminders_enabled=bool(
                preferences.get("reminders_enabled", DEFAULT_REMINDERS_ENABLED)
            ),
            water_reminder_enabled=bool(
                preferences.get("water_reminder_enabled", DEFAULT_WATER_REMINDER_ENABLED)
            ),
            water_reminder_minutes=int(
                preferences.get("water_reminder_minutes", DEFAULT_WATER_REMINDER_MINUTES)
                or DEFAULT_WATER_REMINDER_MINUTES
            ),
            activity_reminder_enabled=bool(
                preferences.get("activity_reminder_enabled", DEFAULT_ACTIVITY_REMINDER_ENABLED)
            ),
            activity_reminder_minutes=int(
                preferences.get(
                    "activity_reminder_minutes",
                    DEFAULT_ACTIVITY_REMINDER_MINUTES,
                )
                or DEFAULT_ACTIVITY_REMINDER_MINUTES
            ),
            custom_reminder_enabled=bool(
                preferences.get("custom_reminder_enabled", DEFAULT_CUSTOM_REMINDER_ENABLED)
            ),
            custom_reminder_minutes=int(
                preferences.get("custom_reminder_minutes", DEFAULT_CUSTOM_REMINDER_MINUTES)
                or DEFAULT_CUSTOM_REMINDER_MINUTES
            ),
            custom_reminder_text=str(
                preferences.get("custom_reminder_text", DEFAULT_CUSTOM_REMINDER_TEXT)
                or DEFAULT_CUSTOM_REMINDER_TEXT
            ),
        )
        self._configure_reminder_scheduler()
        active_count = sum(1 for rule in self._current_reminder_rules() if rule.enabled)
        print(f"[sched] reminder preferences saved active={active_count}")
        self._reminder_settings_dialog._load_snapshot(snapshot)
        self.show_alert("提醒设置已保存。", force=True, style="receipt")

    def _apply_ui_language_to_dialogs(self):
        language = self._ui_language_preference()
        self._budget_status_dialog.set_language(language)
        self._privacy_boundary_dialog.set_language(language)
        self._sprite_pack_picker_dialog.set_language(language)
        self._sprite_pack_info_dialog.set_language(language)
        self._outing_collection_dialog.set_language(language)
        self._auto_dnd_status_dialog.set_language(language)
        self._reminder_settings_dialog.set_language(language)
        self._sprite_display_settings_dialog.set_language(language)
        self._memory_dialog.set_language(language)
        self._memory_delete_dialog.set_language(language)

    def maybe_show_onboarding(self):
        snapshot = self._app_state.snapshot()
        if (
            snapshot.onboarding_seen
            and snapshot.setup_version_seen >= CURRENT_SETUP_VERSION
            and snapshot.data_boundary_acknowledged
            and api_key_status().configured
        ):
            return
        self._apply_onboarding_decision(
            self._onboarding_dialog.ask_for(self, snapshot, get_long_term_memory_items())
        )

    def _apply_onboarding_decision(self, decision: OnboardingDecision):
        if not decision.submitted:
            return
        previous = self._app_state.snapshot()
        owner_name = decision.owner_name.strip()
        reply_language = normalize_language(decision.reply_language)
        ui_language = normalize_ui_language(decision.ui_language)
        memory_language_label = "英文" if reply_language == "en-US" else "中文"
        onboarding_seen = bool(
            decision.remember
            and decision.api_key_configured
            and decision.data_boundary_acknowledged
        )
        self._app_state.apply_setup(
            onboarding_seen=onboarding_seen,
            setup_version_seen=(
                CURRENT_SETUP_VERSION
                if decision.api_key_configured and decision.data_boundary_acknowledged
                else previous.setup_version_seen
            ),
            owner_name=owner_name,
            budget_mode=decision.budget_mode,
            language=reply_language,
            ui_language=ui_language,
            data_boundary_acknowledged=decision.data_boundary_acknowledged,
            auto_do_not_disturb_enabled=decision.auto_do_not_disturb_enabled,
            auto_hide_on_sensitive_scene=decision.auto_hide_on_sensitive_scene,
        )
        self._auto_hide_on_sensitive_scene = decision.auto_hide_on_sensitive_scene
        self._set_auto_do_not_disturb_enabled(
            decision.auto_do_not_disturb_enabled,
            announce=False,
            persist=False,
        )
        self._apply_ui_language_to_dialogs()
        if self._budget_status_dialog.isVisible():
            self._refresh_budget_status_dialog()
        if self._privacy_boundary_dialog.isVisible():
            self._refresh_privacy_boundary_dialog()
        if owner_name:
            create_long_term_memory_item(f"主人希望被叫作{owner_name}。")
        else:
            delete_long_term_memory_item("preferred_name")
        create_long_term_memory_item(f"主人偏好我用{memory_language_label}回复。")
        if decision.open_health:
            self._show_permission_health_dialog()

    def _show_onboarding_dialog(self):
        self._apply_onboarding_decision(
            self._onboarding_dialog.ask_for(
                self,
                self._app_state.snapshot(),
                get_long_term_memory_items(),
            )
        )

    def _replace_sprite_pack(
        self,
        sprite_pack: SpritePackBundle,
        *,
        persist: bool = True,
        announce: bool = True,
    ):
        center = self.frameGeometry().center()
        sprites: dict[str, list[dict[str, object]]] = {}
        display_scale = _sprite_display_scale_for(sprite_pack, self._app_state.snapshot())
        effective_dpr = self._asset_dpr / display_scale
        for key, images in sprite_pack.states.items():
            payloads: list[dict[str, object]] = []
            for img in images:
                pm = QPixmap.fromImage(img)
                pm.setDevicePixelRatio(effective_dpr)
                payloads.append({"image": img, "pixmap": pm})
            if payloads:
                sprites[key] = payloads

        idle_img = sprite_pack.states["idle"][0]
        self._sprite_pack = sprite_pack
        self._sprite_display_scale = display_scale
        self._effective_asset_dpr = effective_dpr
        self._sprites = sprites
        self._asset_w = round(idle_img.width() / self._effective_asset_dpr)
        self._asset_h = round(idle_img.height() / self._effective_asset_dpr)
        self.resize(self._asset_w, self._asset_h + PAD_TOP + PAD_BOTTOM)
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        self._last_hit_asset = None
        self._active_sprite_state_key = "idle"
        self._active_sprite_variant_index = 0
        now = time.monotonic()
        self._enter_until = (now + ENTER_DURATION_S) if "enter" in self._sprites else None
        self._mood = "default"
        self._mood_until = 0.0
        self._last_activity_at = now
        self._next_sleepy_at = now + self._sleepy_after_s
        self._next_peckish_at = now + self._peckish_after_s
        self._eye_closed = False
        self._blink_end_at = None
        self._blink_next_at = now + random.uniform(*BLINK_INTERVAL)
        self._last_state_key = self._current_state_key()
        self._select_sprite_variant(self._last_state_key)
        self.update()
        self._reposition_attached_windows()

        screen = QApplication.primaryScreen()
        screen_dpr = screen.devicePixelRatio() if screen is not None else 1.0
        print(f"[sprite-pack] switched to {self._sprite_pack.pack_id} source={self._sprite_pack.source}")
        print(
            f"[diag] screen dpr={screen_dpr}  canvas={idle_img.width()}x{idle_img.height()}px "
            f"@{self._effective_asset_dpr:.3g}x effective "
            f"(base={self._asset_dpr:g}x scale={self._sprite_display_scale:g})  "
            f"asset_logical={self._asset_w}x{self._asset_h}  "
            f"window={self.width()}x{self.height()}  states=[{','.join(self._sprites.keys())}]"
        )

        if persist:
            self._persist_sprite_pack_preference(self._sprite_pack.pack_id)
        if self._sprite_pack_info_dialog.isVisible():
            self._refresh_sprite_pack_info_dialog()
        if announce:
            english = _ui_uses_english(self._ui_language_preference())
            self.show_alert(
                (
                    f"Switched to sprite pack: {self._sprite_pack.name}."
                    if english
                    else f"已经切到立绘包: {self._sprite_pack.name}。"
                ),
                force=True,
            )

    def _show_sprite_pack_picker(self):
        summaries = self._available_sprite_pack_summaries()
        selected_pack_id = self._sprite_pack_picker_dialog.ask_for(
            self,
            current_pack_id=self._sprite_pack.pack_id,
            summaries=summaries,
        )
        if not selected_pack_id or selected_pack_id == self._sprite_pack.pack_id:
            return

        try:
            sprite_pack = resolve_sprite_pack(
                assets_dir=ASSETS,
                sprite_set=selected_pack_id,
                sprite=None,
            )
        except SpritePackError as exc:
            print(f"[sprite-pack] switch failed: {exc}")
            english = _ui_uses_english(self._ui_language_preference())
            self.show_alert(
                f"Failed to switch sprite pack: {exc}"
                if english
                else f"切换立绘包失败: {exc}",
                force=True,
            )
            return

        self._replace_sprite_pack(sprite_pack, persist=True, announce=True)

    def _refresh_sprite_pack_info_dialog(self):
        self._sprite_pack_info_dialog.refresh(
            _build_sprite_pack_info_view(
                self._sprite_pack,
                language=self._ui_language_preference(),
            )
        )
        if self._sprite_pack_info_dialog.isVisible():
            self._sprite_pack_info_dialog.reposition(self)

    def _show_sprite_pack_info_dialog(self):
        self._sprite_pack_info_dialog.set_language(self._ui_language_preference())
        self._sprite_pack_info_dialog.show_for(
            self,
            _build_sprite_pack_info_view(
                self._sprite_pack,
                language=self._ui_language_preference(),
            ),
        )

    def _open_user_sprite_pack_folder(self):
        language = self._ui_language_preference()
        english = _ui_uses_english(language)
        target_root = user_sprite_packs_dir()
        try:
            root = ensure_user_sprite_pack_template(ASSETS)
        except Exception as exc:
            print(f"[sprite-pack] failed to prepare user sprite-pack folder {target_root}: {exc}")
            self.show_alert(
                (
                    f"Failed to prepare the user sprite-pack folder: {exc}"
                    if english
                    else f"准备用户立绘包目录失败: {exc}"
                ),
                force=True,
            )
            return

        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))
        self._refresh_sprite_pack_info_dialog()
        if opened:
            self.show_alert(
                (
                    f"Opened user sprite-pack folder: {root}"
                    if english
                    else f"已打开用户立绘包目录: {root}"
                ),
                force=True,
                style="receipt",
            )
        else:
            self.show_alert(
                (
                    f"User sprite-pack template is ready here: {root}"
                    if english
                    else f"用户立绘包模板已准备好: {root}"
                ),
                force=True,
                style="receipt",
            )

    def _current_outing_collection_view(self) -> dict[str, object]:
        return _build_outing_collection_view(
            self._outing_store.snapshot(),
            self._outing_catalog,
            language=self._ui_language_preference(),
        )

    def _refresh_outing_collection_dialog(self):
        self._outing_collection_dialog.set_language(self._ui_language_preference())
        self._outing_collection_dialog.refresh(self._current_outing_collection_view())
        if self._outing_collection_dialog.isVisible():
            self._outing_collection_dialog.reposition(self)

    def _show_outing_collection_dialog(self):
        self._outing_collection_dialog.set_language(self._ui_language_preference())
        self._outing_collection_dialog.show_for(
            self,
            self._current_outing_collection_view(),
        )

    def _hide_outing_collection_dialog(self):
        self._outing_collection_dialog.hide()

    def _toggle_outing_collection_dialog(self):
        if self._outing_collection_dialog.isVisible():
            self._hide_outing_collection_dialog()
            return
        self._show_outing_collection_dialog()

    def _current_auto_dnd_status_view(self) -> dict[str, object]:
        return _build_auto_dnd_status_view(
            state=self._current_auto_do_not_disturb_state(),
            auto_dnd_enabled=self._auto_do_not_disturb_enabled,
            manual_dnd_enabled=self._do_not_disturb,
            auto_hide_enabled=self._auto_hide_on_sensitive_scene,
            outing_active=self._outing_active,
            language=self._ui_language_preference(),
        )

    def _refresh_auto_dnd_status_dialog(self):
        self._refresh_auto_do_not_disturb()
        self._auto_dnd_status_dialog.refresh(self._current_auto_dnd_status_view())
        if self._auto_dnd_status_dialog.isVisible():
            self._auto_dnd_status_dialog.reposition(self)

    def _show_auto_dnd_status_dialog(self):
        self._auto_dnd_status_dialog.set_language(self._ui_language_preference())
        self._auto_dnd_status_dialog.show_for(
            self,
            self._current_auto_dnd_status_view(),
        )

    def _is_busy_for_deferred_alerts(self) -> bool:
        return bool(
            self._chat_dialog.isVisible()
            or (self._chat_thread is not None and self._chat_thread.isRunning())
            or self._pending_permission_future is not None
            or self._pending_question_future is not None
        )

    def _effective_do_not_disturb(self) -> bool:
        return bool(self._do_not_disturb or self._auto_do_not_disturb)

    def _should_auto_hide_for_reason(self, reason_key: str) -> bool:
        return bool(
            self._auto_hide_on_sensitive_scene
            and reason_key in AUTO_HIDE_REASON_KEYS
        )

    def _set_auto_hidden(self, hidden: bool):
        hidden = bool(hidden)
        if hidden == self._auto_hidden:
            return
        self._auto_hidden = hidden
        if hidden:
            if self._bubble.isVisible():
                self._bubble.hide()
            self.hide()
            self._set_click_through(False)
            print("[dnd:auto-hide] on")
            return

        self.show()
        self.update()
        print("[dnd:auto-hide] off")

    def _set_auto_hide_on_sensitive_scene(self, enabled: bool, *, announce: bool = True):
        enabled = bool(enabled)
        if enabled == self._auto_hide_on_sensitive_scene:
            return
        self._auto_hide_on_sensitive_scene = enabled
        self._app_state.set_auto_hide_on_sensitive_scene(enabled)
        if not enabled:
            self._set_auto_hidden(False)
        elif self._should_auto_hide_for_reason(self._auto_do_not_disturb_reason_key):
            self._set_auto_hidden(True)
        if self._privacy_boundary_dialog.isVisible():
            self._refresh_privacy_boundary_dialog()
        if self._auto_dnd_status_dialog.isVisible():
            self._auto_dnd_status_dialog.refresh(self._current_auto_dnd_status_view())
        if announce:
            self.show_alert(
                AUTO_HIDE_ENABLED_LINE if enabled else AUTO_HIDE_DISABLED_LINE,
                force=True,
            )

    def _toggle_auto_hide_on_sensitive_scene(self):
        self._set_auto_hide_on_sensitive_scene(not self._auto_hide_on_sensitive_scene)

    def _clear_auto_do_not_disturb_state(
        self,
        *,
        finish_outing_note: str = "",
        updated_at: float | None = None,
    ):
        old_active = self._auto_do_not_disturb
        self._auto_do_not_disturb_updated_at = float(updated_at or time.time())
        self._auto_do_not_disturb = False
        self._auto_do_not_disturb_reason_key = ""
        self._auto_do_not_disturb_reason = ""
        self._auto_do_not_disturb_detail = ""
        self._auto_do_not_disturb_frontmost_app_name = ""
        self._auto_do_not_disturb_frontmost_bundle_id = ""
        self._set_auto_hidden(False)
        if old_active:
            print("[dnd:auto] off")
        if self._outing_active and self._outing_origin == "auto_dnd":
            note = finish_outing_note or "刚才那阵不适合露面，我先避开了。现在场景过去了。"
            self._finish_outing(extra_note=note)
        elif old_active:
            self._flush_deferred_alert()
        if self._auto_dnd_status_dialog.isVisible():
            self._auto_dnd_status_dialog.refresh(self._current_auto_dnd_status_view())

    def _set_auto_do_not_disturb_enabled(
        self,
        enabled: bool,
        *,
        announce: bool = True,
        persist: bool = True,
    ):
        enabled = bool(enabled)
        if enabled == self._auto_do_not_disturb_enabled:
            return
        self._auto_do_not_disturb_enabled = enabled
        if persist:
            self._app_state.set_auto_do_not_disturb_enabled(enabled)
        self._auto_dnd_refresh_queued = False
        if enabled:
            if not self._auto_dnd_timer.isActive():
                self._auto_dnd_timer.start(AUTO_DND_POLL_MS)
            self._auto_dnd_native_observer.start()
            self._schedule_auto_do_not_disturb_refresh()
        else:
            self._auto_dnd_timer.stop()
            self._auto_dnd_native_observer.stop()
            self._clear_auto_do_not_disturb_state(
                finish_outing_note="自动免打扰检测刚被关掉了。我就不继续按场景躲着了。",
            )
        if self._auto_dnd_status_dialog.isVisible():
            self._auto_dnd_status_dialog.refresh(self._current_auto_dnd_status_view())
        if announce:
            self.show_alert(
                _localized_auto_dnd_toggle_receipt(
                    enabled,
                    ui_language=self._ui_language_preference(),
                ),
                force=True,
                style="receipt",
            )

    def _toggle_auto_do_not_disturb_enabled(self):
        self._set_auto_do_not_disturb_enabled(not self._auto_do_not_disturb_enabled)

    def _schedule_auto_do_not_disturb_refresh(self):
        if not self._auto_do_not_disturb_enabled:
            return
        if self._auto_dnd_refresh_queued:
            return
        self._auto_dnd_refresh_queued = True
        QTimer.singleShot(AUTO_DND_EVENT_DEBOUNCE_MS, self._run_scheduled_auto_dnd_refresh)

    def _run_scheduled_auto_dnd_refresh(self):
        self._auto_dnd_refresh_queued = False
        if not self._auto_do_not_disturb_enabled:
            return
        self._refresh_auto_do_not_disturb()

    def _refresh_auto_do_not_disturb(self):
        if not self._auto_do_not_disturb_enabled:
            self._clear_auto_do_not_disturb_state()
            return
        try:
            state = probe_auto_do_not_disturb()
        except Exception as exc:
            print(f"[dnd:auto] probe failed: {exc}")
            return

        active = bool(state.active)
        reason_key = str(state.reason_key or "").strip() if active else ""
        reason = str(state.reason_text or "").strip()
        detail = str(state.detail or "").strip()
        frontmost_app_name = str(state.frontmost_app_name or "").strip()
        frontmost_bundle_id = str(state.frontmost_bundle_id or "").strip()
        updated_at = float(state.updated_at or time.time())
        if (
            active == self._auto_do_not_disturb
            and reason_key == self._auto_do_not_disturb_reason_key
            and reason == self._auto_do_not_disturb_reason
            and detail == self._auto_do_not_disturb_detail
            and frontmost_app_name == self._auto_do_not_disturb_frontmost_app_name
            and frontmost_bundle_id == self._auto_do_not_disturb_frontmost_bundle_id
        ):
            self._auto_do_not_disturb_updated_at = updated_at
            if self._auto_dnd_status_dialog.isVisible():
                self._auto_dnd_status_dialog.refresh(self._current_auto_dnd_status_view())
            return

        old_active = self._auto_do_not_disturb
        self._auto_do_not_disturb_updated_at = updated_at
        self._auto_do_not_disturb_frontmost_app_name = frontmost_app_name
        self._auto_do_not_disturb_frontmost_bundle_id = frontmost_bundle_id
        self._auto_do_not_disturb = active
        self._auto_do_not_disturb_reason_key = reason_key
        self._auto_do_not_disturb_reason = reason if active else ""
        self._auto_do_not_disturb_detail = detail if active else ""
        self._set_auto_hidden(self._should_auto_hide_for_reason(str(state.reason_key or "")))
        if active:
            print(
                f"[dnd:auto] on reason={self._auto_do_not_disturb_reason!r} "
                f"detail={self._auto_do_not_disturb_detail!r}"
            )
            self._clear_deferred_alert()
            if self._state == MaidState.ALERT:
                self.end_alert()
            if not old_active and not self._outing_active:
                self._begin_outing(
                    "auto_dnd",
                    reason=self._auto_do_not_disturb_reason or self._auto_do_not_disturb_detail,
                    auto_return=False,
                    announce=False,
                )
            if self._auto_dnd_status_dialog.isVisible():
                self._auto_dnd_status_dialog.refresh(self._current_auto_dnd_status_view())
            return

        self._clear_auto_do_not_disturb_state(
            finish_outing_note="刚才那阵不适合露面，我先避开了。现在场景过去了。",
            updated_at=updated_at,
        )

    def _set_do_not_disturb(self, enabled: bool, *, announce: bool = True):
        enabled = bool(enabled)
        if enabled == self._do_not_disturb:
            return
        self._do_not_disturb = enabled
        self._app_state.set_do_not_disturb(enabled)
        if enabled:
            self._clear_deferred_alert()
            if self._state == MaidState.ALERT:
                self.end_alert()
        if announce:
            line = DND_ENABLED_LINE
            if not enabled:
                line = (
                    DND_DISABLED_AUTO_LINE
                    if self._auto_do_not_disturb
                    else DND_DISABLED_LINE
                )
            self.show_alert(
                line,
                force=True,
            )
        if self._auto_dnd_status_dialog.isVisible():
            self._auto_dnd_status_dialog.refresh(self._current_auto_dnd_status_view())

    def _toggle_do_not_disturb(self):
        self._set_do_not_disturb(not self._do_not_disturb)

    def _flush_deferred_alert(self):
        if self._effective_do_not_disturb() or self._is_busy_for_deferred_alerts():
            return
        if self._state == MaidState.ALERT:
            return
        line = (self._deferred_alert_line or "").strip()
        if not line:
            return
        style = self._deferred_alert_style
        self._clear_deferred_alert()
        self.show_alert(line, force=False, style=style)

    def _maybe_flush_deferred_alert(self, now: float):
        # 兜底补发：忙碌/免打扰解除后即使再没有别的气泡，排队的提醒也能在
        # 几秒内自己浮出来，而不是永远卡在队列里。
        if self._exiting:
            return
        if self._deferred_alert_line is None:
            return
        if now < self._next_deferred_flush_at:
            return
        self._next_deferred_flush_at = now + 2.0
        self._flush_deferred_alert()

    def _show_permission_request(self, payload):
        request, future = payload
        self._pending_permission_future = future
        self._record_activity()
        print(f"[perm] >>> {request.tool_name} {request.input_data!r}")
        try:
            decision = self._permission_dialog.ask_for(self, request)
        except Exception as exc:
            if not future.done():
                future.set_result(
                    PermissionDecision(
                        allow=False,
                        message=f"权限弹窗失败: {exc}",
                    )
                )
        else:
            self._record_activity()
            if not future.done():
                future.set_result(decision)
            print(
                f"[perm] <<< {request.tool_name} allow={decision.allow} "
                f"remember={decision.remember_tool}"
            )
        finally:
            self._pending_permission_future = None
            self._flush_deferred_alert()

    def _show_question_request(self, payload):
        request, future = payload
        self._pending_question_future = future
        self._record_activity()
        print(f"[ask] >>> {request.input_data!r}")
        try:
            decision = self._question_dialog.ask_for(self, request)
        except Exception as exc:
            if not future.done():
                future.set_result(
                    AskUserQuestionDecision(
                        cancelled=True,
                        message=f"澄清问题弹窗失败: {exc}",
                    )
                )
        else:
            self._record_activity()
            if not future.done():
                future.set_result(decision)
            print(
                f"[ask] <<< cancelled={decision.cancelled} "
                f"answers={decision.answers!r}"
            )
        finally:
            self._pending_question_future = None
            self._flush_deferred_alert()

    def _clear_remembered_permissions(self):
        names = get_remembered_tool_permissions()
        cleared = clear_remembered_tool_permissions()
        if cleared <= 0:
            line = "这次会话里还没有记住的工具授权。"
        elif cleared == 1:
            line = f"已经清掉本次会话里记住的工具授权: {names[0]}。"
        else:
            line = f"已经清掉本次会话里记住的 {cleared} 项工具授权。"
        print(f"[perm] cleared remembered approvals: {names}")
        self.show_alert(line, force=True)

    def _clear_resumable_session(self):
        if self._chat_thread is not None and self._chat_thread.isRunning():
            self.show_alert("我还在想上一句。等我回完再清续接会话。", force=True)
            return

        session_id = get_resumable_session_id()
        cleared_session_id = clear_resumable_session()
        cleared = cleared_session_id or session_id
        if cleared:
            line = "已经清掉续接会话。下次会从新会话开始。"
        else:
            line = "现在没有可清掉的续接会话。"
        print(f"[session] cleared resumable session: {cleared}")
        self.show_alert(line, force=True)

    def _show_permission_health_dialog(self):
        self._permission_health_dialog.show_for(self)
        self._refresh_permission_health_dialog()

    def _hide_permission_health_dialog(self):
        self._permission_health_dialog.hide()

    def _toggle_permission_health_dialog(self):
        if self._permission_health_dialog.isVisible():
            self._hide_permission_health_dialog()
            return
        self._show_permission_health_dialog()

    def _refresh_budget_status_dialog(self):
        self._budget_status_dialog.set_language(self._ui_language_preference())
        self._budget_status_dialog.refresh(get_budget_guard_snapshot())
        if self._budget_status_dialog.isVisible():
            self._budget_status_dialog.reposition(self)

    def _show_budget_status_dialog(self):
        self._budget_status_dialog.set_language(self._ui_language_preference())
        self._budget_status_dialog.show_for(self, get_budget_guard_snapshot())

    def _hide_budget_status_dialog(self):
        self._budget_status_dialog.hide()

    def _toggle_budget_status_dialog(self):
        if self._budget_status_dialog.isVisible():
            self._hide_budget_status_dialog()
            return
        self._show_budget_status_dialog()

    def _current_privacy_boundary_view(self) -> dict[str, object]:
        return _build_privacy_boundary_view(
            app_snapshot=self._app_state.snapshot(),
            api_status=api_key_status(),
            api_key_path=_runtime_path_from_env(
                API_KEY_PATH_ENV_VAR,
                DEFAULT_API_KEY_PATH,
            ),
            app_state_path=_runtime_path_from_env(
                APP_STATE_ENV_VAR,
                DEFAULT_APP_STATE_PATH,
            ),
            memory_state_path=_runtime_path_from_env(
                MEMORY_STATE_ENV_VAR,
                DEFAULT_MEMORY_STATE_PATH,
            ),
            memory_item_count=len(get_long_term_memory_items()),
            recent_events=list(self._recent_privacy_events),
            language=self._ui_language_preference(),
        )

    def _refresh_privacy_boundary_dialog(self):
        self._privacy_boundary_dialog.refresh(self._current_privacy_boundary_view())
        if self._privacy_boundary_dialog.isVisible():
            self._privacy_boundary_dialog.reposition(self)

    def _show_privacy_boundary_dialog(self):
        self._privacy_boundary_dialog.set_language(self._ui_language_preference())
        self._privacy_boundary_dialog.show_for(
            self,
            self._current_privacy_boundary_view(),
        )

    def _hide_privacy_boundary_dialog(self):
        self._privacy_boundary_dialog.hide()

    def _toggle_privacy_boundary_dialog(self):
        if self._privacy_boundary_dialog.isVisible():
            self._hide_privacy_boundary_dialog()
            return
        self._show_privacy_boundary_dialog()

    def _refresh_permission_health_dialog(self):
        if (
            self._permission_health_thread is not None
            and self._permission_health_thread.isRunning()
        ):
            self._permission_health_dialog.set_loading("还在检查，稍等一下。")
            return

        self._permission_health_dialog.show_for(self)
        self._permission_health_dialog.set_loading()
        thread = QThread(self)
        worker = PermissionHealthWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_permission_health_success)
        worker.failed.connect(self._on_permission_health_error)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_permission_health_worker)
        self._permission_health_thread = thread
        self._permission_health_worker = worker
        thread.start()

    def _on_permission_health_success(self, snapshot):
        errors = int(snapshot.get("error_count", 0) or 0)
        warnings = int(snapshot.get("warning_count", 0) or 0)
        print(
            f"[health] checked permissions: ok={snapshot.get('ok_count', 0)} "
            f"warning={warnings} error={errors}"
        )
        self._permission_health_dialog.refresh(snapshot)
        if self._permission_health_dialog.isVisible():
            self._permission_health_dialog.reposition(self)

    def _on_permission_health_error(self, message: str):
        print(f"[health] check failed: {message}")
        self._permission_health_dialog.set_error(message)

    def _clear_permission_health_worker(self):
        self._permission_health_thread = None
        self._permission_health_worker = None

    def _refresh_memory_dialog(self):
        self._memory_dialog.refresh(get_long_term_memory_items())

    def _show_memory_dialog(self):
        self._memory_dialog.set_language(self._ui_language_preference())
        self._memory_dialog.show_for(self, get_long_term_memory_items())

    def _hide_memory_dialog(self):
        self._memory_dialog.hide()

    def _toggle_memory_dialog(self):
        if self._memory_dialog.isVisible():
            self._hide_memory_dialog()
            return
        self._show_memory_dialog()

    def _save_long_term_memory_item(self, key: str, text: str):
        ui_language = self._ui_language_preference()
        english = _ui_uses_english(ui_language)
        key = key.strip()
        if not key:
            created = create_long_term_memory_item(text)
            if created is None:
                self.show_alert(
                    "The new memory was not saved."
                    if english
                    else "这条新记忆没记进去。",
                    force=True,
                )
                return
            print(f"[memory] created item: {created.get('key')}")
            self._memory_dialog.finish_create()
            self._refresh_memory_dialog()
            if self._privacy_boundary_dialog.isVisible():
                self._refresh_privacy_boundary_dialog()
            self.show_alert(
                _localized_memory_write_receipt(created, ui_language=ui_language),
                force=True,
                style="receipt",
            )
            return

        updated = update_long_term_memory_item(key, text)
        if updated is None:
            self.show_alert(
                "The memory was not updated."
                if english
                else "这条长期记忆没改成。",
                force=True,
            )
            return
        print(f"[memory] updated item: {key}")
        self._refresh_memory_dialog()
        if self._privacy_boundary_dialog.isVisible():
            self._refresh_privacy_boundary_dialog()
        self.show_alert(
            _localized_memory_write_receipt(updated, ui_language=ui_language),
            force=True,
            style="receipt",
        )

    def _delete_long_term_memory_item(self, key: str):
        items = get_long_term_memory_items()
        existing = next(
            (item for item in items if str(item.get("key") or "") == key),
            None,
        )
        ui_language = self._ui_language_preference()
        english = _ui_uses_english(ui_language)
        anchor = self._memory_dialog if self._memory_dialog.isVisible() else self
        self._memory_delete_dialog.set_language(ui_language)
        preview_text = str(existing.get("text") or "") if existing else ""
        if not self._memory_delete_dialog.ask_for(anchor, preview_text):
            print(f"[memory] delete cancelled: {key}")
            return

        removed = delete_long_term_memory_item(key)
        if removed is None:
            self.show_alert(
                "That memory is already gone."
                if english
                else "这条长期记忆已经不在了。",
                force=True,
            )
            return
        print(f"[memory] deleted item: {key}")
        self._refresh_memory_dialog()
        if self._privacy_boundary_dialog.isVisible():
            self._refresh_privacy_boundary_dialog()
        self.show_alert(
            _localized_memory_delete_receipt(removed, ui_language=ui_language),
            force=True,
            style="receipt",
        )

    def submit_prompt(self, prompt: str, attachments: list[str] | None = None):
        prompt = prompt.strip()
        if not prompt:
            return
        attachment_paths = _normalize_attachment_paths(attachments or [])
        if self._chat_thread is not None and self._chat_thread.isRunning():
            self._chat_dialog.set_busy(True, "我还在想上一句。")
            return

        self._record_activity()
        self._chat_dialog.set_busy(True, "思考中...")
        self._trace_dialog.clear()
        if self._trace_enabled:
            self._trace_dialog.begin_run(self)
        print(f"[chat] >>> {prompt!r} attachments={len(attachment_paths)}")

        thread = QThread(self)
        worker = ChatWorker(_build_prompt_with_attachments(prompt, attachment_paths))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.trace.connect(self._on_chat_trace)
        worker.finished.connect(self._on_chat_success)
        worker.failed.connect(self._on_chat_error)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_chat_worker)

        self._chat_thread = thread
        self._chat_worker = worker
        thread.start()

    def _on_chat_success(self, result):
        self._chat_dialog.set_busy(False)
        rewrite_actions = tuple(
            str(action or "").strip().lower()
            for action in getattr(result, "privacy_rewrite_actions", ())
            if str(action or "").strip()
        )
        if rewrite_actions:
            self._chat_dialog.show_privacy_rewrite_actions(result.text, rewrite_actions)
            self._chat_dialog.reposition(self)
            self.show_alert("这句被隐私边界拦下了。输入框里给你放了快捷改写按钮。", force=True)
        else:
            self._chat_dialog.clear_draft()
            self._chat_dialog.hide()
        self._refresh_memory_dialog()
        if self._budget_status_dialog.isVisible():
            self._refresh_budget_status_dialog()
        cost = (
            f"{result.total_cost_usd:.6f}"
            if result.total_cost_usd is not None
            else "n/a"
        )
        print(
            f"[chat] <<< {result.text!r} "
            f"(session={result.session_id} in={result.input_tokens} "
            f"out={result.output_tokens} stop={result.stop_reason} "
            f"dur={result.duration_ms}ms cost={cost})"
        )
        if not rewrite_actions:
            self.show_alert(result.display_text or result.text, force=True)
        self.chat_done.emit(True)
        self._flush_deferred_alert()

    def _on_chat_error(self, message: str):
        self._chat_dialog.set_busy(False, "没连上。")
        print(f"[chat] !!! {message}")
        if not api_key_status().configured:
            self.show_alert("先把 Claude API key 填上。不然她只有壳，没有脑子。", force=True)
            QTimer.singleShot(0, self._show_onboarding_dialog)
        else:
            self.show_alert(CHAT_ERROR_LINE, force=True)
        self.chat_done.emit(False)
        self._flush_deferred_alert()

    def _on_chat_trace(self, event: ChatTraceEvent):
        self._trace_dialog.append_event(event)
        if event.kind == "privacy":
            self._recent_privacy_events.append(event)
            if len(self._recent_privacy_events) > RECENT_PRIVACY_EVENTS_LIMIT:
                self._recent_privacy_events = self._recent_privacy_events[-RECENT_PRIVACY_EVENTS_LIMIT:]
            if self._privacy_boundary_dialog.isVisible():
                self._refresh_privacy_boundary_dialog()

    def _clear_chat_worker(self):
        self._chat_thread = None
        self._chat_worker = None

    def _disable_trace_dialog(self):
        self._trace_enabled = False
        self._trace_dialog.hide()

    def _enable_trace_dialog(self):
        self._trace_enabled = True
        self._trace_dialog.show_for(self)

    # ---------- macOS native setup ----------
    def configure_native(self):
        if not HAVE_OBJC:
            print("[warn] PyObjC unavailable; skipping native tweaks:", _OBJC_ERR)
            return
        win = self._ns_window()
        if win is None:
            print("[warn] could not get NSWindow")
            return
        win.setLevel_(NSStatusWindowLevel)
        win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        win.setHidesOnDeactivate_(False)
        try:
            win.setStyleMask_(win.styleMask() | NSWindowStyleMaskNonactivatingPanel)
            print("[diag] applied NSWindowStyleMaskNonactivatingPanel")
        except Exception as e:
            print("[diag] nonactivating mask not applied:", e)
        cls = win.className() if hasattr(win, "className") else "?"
        print(f"[diag] NSWindow class={cls} level={win.level()} styleMask={win.styleMask()}")

    def _ns_window(self):
        if self._nswindow is not None:
            return self._nswindow
        try:
            view = objc.objc_object(c_void_p=int(self.winId()))
            self._nswindow = view.window()
        except Exception as e:
            print("[warn] _ns_window failed:", e)
            self._nswindow = None
        return self._nswindow

    def _set_click_through(self, on: bool):
        if on == self._click_through:
            return
        self._click_through = on
        win = self._ns_window()
        if win is not None:
            win.setIgnoresMouseEvents_(bool(on))

    # ---------- state machine ----------
    def show_alert(self, line: str, force: bool = False, *, style: str = "plain"):
        # 非强制提醒被免打扰/忙碌/撞车拦下时一律进延后队列（§16「静默或排队」），
        # 等空闲由 _maybe_flush_deferred_alert 补发；队列只留最后一条。
        if not force and self._effective_do_not_disturb():
            if self._do_not_disturb:
                reason = "manual"
            else:
                reason = self._auto_do_not_disturb_reason or "auto"
            self._set_deferred_alert(line, style=style)
            print(f"[alert] deferred (do not disturb={reason}): {line!r}")
            return
        if not force and self._is_busy_for_deferred_alerts():
            self._set_deferred_alert(line, style=style)
            print(f"[alert] deferred (busy, style={style}): {line!r}")
            return
        if self._state == MaidState.ALERT and not force:
            self._set_deferred_alert(line, style=style)
            print(f"[alert] deferred (already alerting): {line!r}")
            return
        self._enter_until = None
        self._state = MaidState.ALERT
        self._state_entered_at = time.monotonic()
        self._bubble.show_at(line, self, style=style)
        self.update()
        print(f"[alert] >>> style={style} {line!r}")

    def end_alert(self):
        self._state = MaidState.IDLE
        self._bubble.hide()
        self.update()
        print("[alert] <<<")
        self._flush_deferred_alert()

    # ---------- alpha sampling (compensated for paint offset) ----------
    def _alpha_at_local(self, local: QPoint) -> int:
        ax = local.x()
        ay = local.y() - (PAD_TOP + self._y_offset)
        if not (0 <= ax < self._asset_w and 0 <= ay < self._asset_h):
            return 0
        img = self._current_alpha_image()
        factor = img.width() / self._asset_w
        px = int(ax * factor)
        py = int(ay * factor)
        if 0 <= px < img.width() and 0 <= py < img.height():
            return img.pixelColor(px, py).alpha()
        return 0

    # ---------- 60Hz tick ----------
    def _tick(self):
        now = time.monotonic()
        dt = now - self._t0

        self._update_mood(now)
        self._maybe_flush_deferred_alert(now)
        self._maybe_idle_quip(now)

        if (
            self._outing_active
            and self._outing_auto_return
            and self._outing_return_at > 0.0
            and now >= self._outing_return_at
        ):
            self._finish_outing()

        new_y = round(math.sin(2 * math.pi * dt / BREATH_PERIOD_S) * BREATH_AMP_LOGICAL)

        new_closed = self._eye_closed
        if not self._blink_allowed(now):
            self._blink_paused = True
            self._blink_end_at = None
            self._blink_next_at = None
            new_closed = False
        else:
            if self._blink_paused:
                self._blink_paused = False
                self._blink_next_at = now + random.uniform(*BLINK_INTERVAL)
            if self._eye_closed:
                if self._blink_end_at is not None and now >= self._blink_end_at:
                    new_closed = False
                    self._blink_end_at = None
                    if random.random() < DOUBLE_BLINK_CHANCE:
                        self._blink_next_at = now + random.uniform(*DOUBLE_BLINK_GAP)
                    else:
                        self._blink_next_at = now + random.uniform(*BLINK_INTERVAL)
            else:
                if self._blink_next_at is not None and now >= self._blink_next_at:
                    new_closed = True
                    self._blink_end_at = now + random.uniform(*BLINK_DURATION)
                    self._blink_next_at = None
                    print(f"[blink] t={dt:.1f}s")

        # If the set has no blink sprite, eye_closed swap is invisible — still
        # tracked for state but doesn't drive a repaint.
        eye_visual_changes = (new_closed != self._eye_closed) and ("blink" in self._sprites)
        visuals_changed = (new_y != self._y_offset) or eye_visual_changes
        self._y_offset = new_y
        self._eye_closed = new_closed

        if self._state == MaidState.ALERT and not self._exiting:
            if now - self._state_entered_at >= ALERT_DURATION_S:
                self.end_alert()
                visuals_changed = True

        # detect state-key change (idle <-> alert <-> blink) and force repaint
        new_key = self._current_state_key()
        if new_key != self._last_state_key:
            print(f"[state] sprite {self._last_state_key} -> {new_key}")
            self._last_state_key = new_key
            if self._active_sprite_state_key != new_key:
                self._select_sprite_variant(new_key)
            visuals_changed = True

        if self._dragging:
            self._set_click_through(False)
        else:
            local = self.mapFromGlobal(QCursor.pos())
            self._set_click_through(self._alpha_at_local(local) <= ALPHA_THRESHOLD)

        if visuals_changed:
            self.update()

    # ---------- painting ----------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        pixmap = self._current_pixmap()
        paint_y = PAD_TOP + self._y_offset
        p.drawPixmap(0, paint_y, self._asset_w, self._asset_h, pixmap)

        if self._debug_border:
            pen = QPen(QColor(255, 0, 0, 120))
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if self._debug_border and self._last_hit_asset is not None:
            mx = self._last_hit_asset.x()
            my = self._last_hit_asset.y() + paint_y
            pen = QPen(QColor(0, 120, 255, 220))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPoint(mx, my), 10, 10)
        p.end()

    # ---------- mouse ----------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            lp = ev.position().toPoint()
            hit_asset = QPoint(lp.x(), lp.y() - (PAD_TOP + self._y_offset))
            if self._debug_border:
                self._last_hit_asset = hit_asset
            else:
                self._last_hit_asset = None
            a = self._alpha_at_local(lp)
            print(f"[hit] BODY press window=({lp.x()},{lp.y()}) "
                  f"asset=({hit_asset.x()},{hit_asset.y()}) alpha={a}")
            # body-tap counts as activity (clears SLEEPY mood) + plays emote
            self._record_activity()
            self.play_emote("excited")
            if "held" in self._sprites:
                self._select_sprite_variant("held")
            self.update()
            ev.accept()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.open_input()
            ev.accept()

    def mouseMoveEvent(self, ev):
        if self._dragging and (ev.buttons() & Qt.LeftButton):
            self.move(ev.globalPosition().toPoint() - self._drag_offset)
            self._reposition_attached_windows()
            ev.accept()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = False
            self.update()
            ev.accept()

    def contextMenuEvent(self, ev):
        self._record_activity()
        m = QMenu(self)
        english = _ui_uses_english(self._ui_language_preference())
        on_label = "On" if english else "开"
        off_label = "Off" if english else "关"

        act_talk = QAction("Talk..." if english else "对话...", self)
        act_talk.triggered.connect(lambda _checked=False: self.open_input())
        m.addAction(act_talk)
        pack_label = (
            f"Sprite Pack: {self._sprite_pack.name}"
            if english
            else f"立绘包: {self._sprite_pack.name}"
        )
        act_pack = QAction(pack_label, self)
        act_pack.triggered.connect(self._show_sprite_pack_picker)
        m.addAction(act_pack)
        pack_meta_bits: list[str] = []
        if self._sprite_pack.metadata.author:
            pack_meta_bits.append(self._sprite_pack.metadata.author)
        if self._sprite_pack.metadata.tags:
            pack_meta_bits.append(", ".join(self._sprite_pack.metadata.tags[:4]))
        pack_meta_label = "Pack Info" if english else "包信息"
        if pack_meta_bits:
            pack_meta_label += ": " + " · ".join(pack_meta_bits)
        act_pack_meta = QAction(pack_meta_label, self)
        act_pack_meta.triggered.connect(self._show_sprite_pack_info_dialog)
        m.addAction(act_pack_meta)
        if not self._auto_do_not_disturb_enabled:
            auto_dnd_label = (
                "Auto DND: Detection Off"
                if english
                else "自动免打扰: 检测已关"
            )
        else:
            auto_dnd_status = on_label if self._auto_do_not_disturb else off_label
            auto_dnd_label = (
                f"Auto DND: {auto_dnd_status}"
                if english
                else f"自动免打扰: {auto_dnd_status}"
            )
        if self._auto_do_not_disturb_enabled and self._auto_do_not_disturb_reason:
            auto_dnd_label += " (" + _localized_auto_dnd_reason_label(
                self._auto_do_not_disturb_reason_key,
                self._auto_do_not_disturb_reason,
                ui_language=self._ui_language_preference(),
            ) + ")"
        act_auto_dnd = QAction(auto_dnd_label, self)
        act_auto_dnd.triggered.connect(self._show_auto_dnd_status_dialog)
        m.addAction(act_auto_dnd)
        auto_dnd_toggle_label = (
            ("Disable Auto DND Detection" if english else "关闭自动免打扰检测")
            if self._auto_do_not_disturb_enabled
            else ("Enable Auto DND Detection" if english else "打开自动免打扰检测")
        )
        act_auto_dnd_toggle = QAction(auto_dnd_toggle_label, self)
        act_auto_dnd_toggle.triggered.connect(self._toggle_auto_do_not_disturb_enabled)
        m.addAction(act_auto_dnd_toggle)
        dnd_label = (
            ("Disable Manual DND" if english else "关闭手动免打扰")
            if self._do_not_disturb
            else ("Enable Manual DND" if english else "打开手动免打扰")
        )
        act_dnd = QAction(dnd_label, self)
        act_dnd.triggered.connect(self._toggle_do_not_disturb)
        m.addAction(act_dnd)
        auto_hide_status = on_label if self._auto_hide_on_sensitive_scene else off_label
        act_auto_hide_status = QAction(
            (
                f"Auto-hide on Share/Record: {auto_hide_status}"
                if english
                else f"共享/录屏自动隐藏: {auto_hide_status}"
            ),
            self,
        )
        act_auto_hide_status.setEnabled(False)
        m.addAction(act_auto_hide_status)
        auto_hide_toggle_label = (
            ("Disable Auto-hide" if english else "关闭自动隐藏")
            if self._auto_hide_on_sensitive_scene
            else ("Enable Auto-hide" if english else "打开自动隐藏")
        )
        act_auto_hide = QAction(auto_hide_toggle_label, self)
        act_auto_hide.triggered.connect(self._toggle_auto_hide_on_sensitive_scene)
        m.addAction(act_auto_hide)
        budget_snapshot = get_budget_guard_snapshot()
        daily_used_usd = _format_budget_amount(budget_snapshot.get("daily_used_usd"))
        daily_limit_usd = _format_budget_amount(budget_snapshot.get("daily_limit_usd"))
        weekly_used_usd = _format_budget_amount(budget_snapshot.get("weekly_used_usd"))
        weekly_limit_usd = _format_budget_amount(budget_snapshot.get("weekly_limit_usd"))
        blocked_scope = str(budget_snapshot.get("blocked_scope") or "").strip()
        budget_day_label = (
            f"Today's Budget: {daily_used_usd} / {daily_limit_usd}"
            if english
            else f"今日预算: {daily_used_usd} / {daily_limit_usd}"
        )
        if blocked_scope == "day":
            budget_day_label += " (Blocked)" if english else " (已触顶)"
        act_budget_day = QAction(budget_day_label, self)
        act_budget_day.setEnabled(False)
        m.addAction(act_budget_day)
        budget_week_label = (
            f"This Week's Budget: {weekly_used_usd} / {weekly_limit_usd}"
            if english
            else f"本周预算: {weekly_used_usd} / {weekly_limit_usd}"
        )
        if blocked_scope == "week":
            budget_week_label += " (Blocked)" if english else " (已触顶)"
        act_budget_week = QAction(budget_week_label, self)
        act_budget_week.setEnabled(False)
        m.addAction(act_budget_week)
        if self._budget_status_dialog.isVisible():
            budget_toggle_label = "Hide Budget Status" if english else "收起预算状态"
        else:
            budget_toggle_label = "Show Budget Status" if english else "显示预算状态"
        act_show_budget = QAction(budget_toggle_label, self)
        act_show_budget.triggered.connect(self._toggle_budget_status_dialog)
        m.addAction(act_show_budget)
        if self._privacy_boundary_dialog.isVisible():
            privacy_toggle_label = "Hide Privacy Boundary" if english else "收起隐私边界"
        else:
            privacy_toggle_label = "Show Privacy Boundary" if english else "显示隐私边界"
        act_show_privacy = QAction(privacy_toggle_label, self)
        act_show_privacy.triggered.connect(self._toggle_privacy_boundary_dialog)
        m.addAction(act_show_privacy)
        if self._trace_enabled:
            trace_label = "Hide Thought Trace" if english else "收起思考流"
        else:
            trace_label = "Show Thought Trace" if english else "显示思考流"
        act_trace = QAction(trace_label, self)
        act_trace.triggered.connect(self._toggle_trace_dialog)
        m.addAction(act_trace)
        if self._memory_dialog.isVisible():
            memory_toggle_label = "Hide Long-term Memory" if english else "收起长期记忆"
        else:
            memory_toggle_label = "Show Long-term Memory" if english else "显示长期记忆"
        act_show_memory = QAction(memory_toggle_label, self)
        act_show_memory.triggered.connect(self._toggle_memory_dialog)
        m.addAction(act_show_memory)
        if self._permission_health_dialog.isVisible():
            health_toggle_label = "Hide Permission Health" if english else "收起权限自检"
        else:
            health_toggle_label = "Show Permission Health" if english else "显示权限自检"
        act_show_health = QAction(health_toggle_label, self)
        act_show_health.triggered.connect(self._toggle_permission_health_dialog)
        m.addAction(act_show_health)
        resumable_session_id = get_resumable_session_id()
        act_clear_session = QAction(
            "Clear Resumable Session" if english else "清空续接会话",
            self,
        )
        act_clear_session.setEnabled(bool(resumable_session_id))
        act_clear_session.triggered.connect(self._clear_resumable_session)
        m.addAction(act_clear_session)
        remembered_tools = get_remembered_tool_permissions()
        if remembered_tools:
            clear_label = (
                f"Clear Remembered Approvals ({len(remembered_tools)})"
                if english
                else f"清空已记住授权 ({len(remembered_tools)})"
            )
        else:
            clear_label = "Clear Remembered Approvals" if english else "清空已记住授权"
        act_clear_perms = QAction(clear_label, self)
        act_clear_perms.setEnabled(bool(remembered_tools))
        act_clear_perms.triggered.connect(self._clear_remembered_permissions)
        m.addAction(act_clear_perms)
        act_onboarding = QAction("Set up" if english else "设置", self)
        act_onboarding.triggered.connect(self._show_onboarding_dialog)
        m.addAction(act_onboarding)
        act_reminder_settings = QAction(
            "Reminder Settings..." if english else "提醒设置...",
            self,
        )
        act_reminder_settings.triggered.connect(self._show_reminder_settings_dialog)
        m.addAction(act_reminder_settings)
        act_display_settings = QAction(
            "Desktop Display..." if english else "桌面显示设置...",
            self,
        )
        act_display_settings.triggered.connect(self._show_sprite_display_settings_dialog)
        m.addAction(act_display_settings)
        m.addSeparator()
        if self._trigger_now_cb is not None:
            act_trigger = QAction("Trigger Reminder Now" if english else "立即触发提醒", self)
            act_trigger.triggered.connect(self._trigger_now_cb)
            m.addAction(act_trigger)
        if self._outing_active:
            if self._outing_origin == "auto_dnd" and self._auto_do_not_disturb:
                act_outing = QAction(
                    "Outing Locked by Auto DND" if english else "出门态已被自动免打扰锁定",
                    self,
                )
                act_outing.setEnabled(False)
            else:
                act_outing = QAction("End Outing Now" if english else "立刻结束出门态", self)
                act_outing.triggered.connect(lambda _checked=False: self._finish_outing())
        else:
            act_outing = QAction("Start Outing Now" if english else "立即进入出门态", self)
            act_outing.triggered.connect(
                lambda _checked=False: self._begin_outing("manual", announce=False)
            )
        m.addAction(act_outing)
        if self._outing_collection_dialog.isVisible():
            outing_collection_label = (
                "Hide Outing Collection"
                if english
                else "收起出门收藏"
            )
        else:
            outing_collection_label = (
                "Show Outing Collection"
                if english
                else "显示出门收藏"
            )
        act_outing_collection = QAction(outing_collection_label, self)
        act_outing_collection.triggered.connect(self._toggle_outing_collection_dialog)
        m.addAction(act_outing_collection)
        act_dbg = QAction("Toggle Debug Border" if english else "调试边框", self)
        act_dbg.triggered.connect(self._toggle_debug)
        m.addAction(act_dbg)
        m.addSeparator()
        act_quit = QAction("Quit" if english else "退出", self)
        act_quit.triggered.connect(self.begin_exit)
        m.addAction(act_quit)
        m.exec(ev.globalPos())

    def _toggle_debug(self):
        self._debug_border = not self._debug_border
        if not self._debug_border:
            self._last_hit_asset = None
        self.update()

    def _toggle_trace_dialog(self):
        if self._trace_enabled:
            self._disable_trace_dialog()
            return
        self._enable_trace_dialog()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_T, Qt.Key_Return, Qt.Key_Enter):
            self.open_input()
            return
        if ev.key() in (Qt.Key_Q, Qt.Key_Escape):
            self.begin_exit()

def _parse_cli(argv):
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--permission-health-json",
        action="store_true",
        help="print the permission health snapshot as JSON and exit",
    )
    p.add_argument("--demo", action="store_true")
    p.add_argument("--reminder-first", type=float, default=None)
    p.add_argument("--reminder-every", type=float, default=None)
    p.add_argument(
        "--sprite-set",
        type=str,
        default=None,
        choices=available_sprite_pack_ids(ASSETS),
        help=f"sprite pack id (default: {DEFAULT_SPRITE_SET})",
    )
    p.add_argument("--sprite", type=str, default=None,
                   help="legacy: <NAME>.png (+ optional <NAME>_blink.png)")
    p.add_argument("--sprite-dpr", type=float, default=DEFAULT_ASSET_DPR)
    p.add_argument("--demo-emote", action="store_true",
                   help="trigger an excited emote ~1s after launch (verification)")
    p.add_argument("--demo-blink", action="store_true",
                   help="force a blink at t≈1s after launch (verification)")
    p.add_argument("--demo-quit-at", type=float, default=None,
                   help="trigger begin_exit at t=N (verification)")
    p.add_argument("--demo-input", type=str, default=None,
                   help="open the input popup and auto-submit this text")
    p.add_argument("--demo-input-delay", type=float, default=DEFAULT_DEMO_INPUT_DELAY_S,
                   help="seconds to wait before auto-opening --demo-input")
    p.add_argument("--demo-quit-on-chat", action="store_true",
                   help="quit after the --demo-input request finishes")
    args, _ = p.parse_known_args(argv)
    first = args.reminder_first
    every = args.reminder_every
    if args.demo:
        first = DEMO_REMINDER_FIRST_S if first is None else first
        every = DEMO_REMINDER_INTERVAL_S if every is None else every
    return (args.permission_health_json, first, every, args.sprite_set, args.sprite, args.sprite_dpr,
            args.demo_emote, args.demo_blink, args.demo, args.demo_quit_at,
            args.demo_input, args.demo_input_delay, args.demo_quit_on_chat)


def main():
    (permission_health_json, first_s, every_s, sprite_set, sprite, sprite_dpr,
     demo_emote, demo_blink, demo_short, demo_quit_at,
     demo_input, demo_input_delay, demo_quit_on_chat) = _parse_cli(sys.argv[1:])

    if permission_health_json:
        snapshot = collect_permission_health()
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
        return

    app = QApplication(sys.argv)
    app.aboutToQuit.connect(shutdown_maid_session)
    app.aboutToQuit.connect(lambda: set_permission_handler(None))
    app.aboutToQuit.connect(lambda: set_ask_user_question_handler(None))
    if HAVE_OBJC:
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyRegular
        )

    app_state_snapshot = load_app_state_snapshot()
    resolved_sprite_set = sprite_set
    persisted_sprite_pack_id = ""
    if not sprite and not resolved_sprite_set:
        persisted_sprite_pack_id = str(app_state_snapshot.sprite_pack_id or "").strip()
        if persisted_sprite_pack_id:
            resolved_sprite_set = persisted_sprite_pack_id

    try:
        sprite_pack = resolve_sprite_pack(
            assets_dir=ASSETS,
            sprite_set=resolved_sprite_set,
            sprite=sprite,
        )
    except SpritePackError as exc:
        if persisted_sprite_pack_id and resolved_sprite_set == persisted_sprite_pack_id:
            print(
                f"[warn] persisted sprite pack {persisted_sprite_pack_id!r} failed to load: {exc}. "
                f"Falling back to {DEFAULT_SPRITE_PACK_ID!r}."
            )
            try:
                sprite_pack = resolve_sprite_pack(
                    assets_dir=ASSETS,
                    sprite_set=DEFAULT_SPRITE_PACK_ID,
                    sprite=None,
                )
            except SpritePackError as fallback_exc:
                print(f"[error] {fallback_exc}", file=sys.stderr)
                sys.exit(2)
        else:
            print(f"[error] {exc}", file=sys.stderr)
            sys.exit(2)
    meta_suffix: list[str] = []
    if sprite_pack.metadata.author:
        meta_suffix.append(f"author={sprite_pack.metadata.author}")
    if sprite_pack.metadata.tags:
        meta_suffix.append(f"tags={','.join(sprite_pack.metadata.tags)}")
    meta_suffix.append(f"preview={sprite_pack.metadata.preview_pose}")
    meta_text = (" " + " ".join(meta_suffix)) if meta_suffix else ""
    print(
        f"[sprite-pack] {sprite_pack.pack_id} "
        f"canvas={sprite_pack.canvas_width}x{sprite_pack.canvas_height}px "
        f"dpr={sprite_dpr} states={','.join(sorted(sprite_pack.states))}{meta_text}"
    )

    bubble = SpeechBubble()
    w = MaidWidget(sprite_pack, bubble, asset_dpr=sprite_dpr, demo_short=demo_short)
    w.move_to_saved_start_position()
    w.show()
    w.configure_native()
    QTimer.singleShot(0, w.maybe_show_onboarding)
    # greet once the opening animation has settled (脚本台词 §四).
    QTimer.singleShot(int(ENTER_DURATION_S * 1000) + 250, w.speak_launch_line)

    scheduler = ReminderScheduler()
    scheduler.fired.connect(w.show_alert)
    scheduler.manual_fired.connect(lambda line: w.show_alert(line, force=True))
    w._configure_reminder_scheduler(
        scheduler,
        first_delay_s=first_s,
        interval_override_s=every_s,
    )

    if demo_emote:
        # auto-trigger an emote 1s after launch (for verification screenshots)
        QTimer.singleShot(1000, lambda: w.play_emote("excited"))
        print("[diag] demo-emote scheduled at t=1s")
    if demo_blink:
        # force the next blink to land at t≈1s so a screenshot can catch it
        w._blink_next_at = w._t0 + 1.0
        print("[diag] demo-blink: next blink forced to t=1s")
    if demo_quit_at is not None:
        QTimer.singleShot(int(demo_quit_at * 1000), w.begin_exit)
        print(f"[diag] demo-quit-at scheduled at t={demo_quit_at}s")
    if demo_input:
        QTimer.singleShot(
            int(max(0, demo_input_delay) * 1000),
            lambda: w.open_input(initial_text=demo_input, auto_submit=True),
        )
        print(
            f"[diag] demo-input scheduled at t={demo_input_delay}s: "
            f"{demo_input!r}"
        )
    if demo_quit_on_chat:
        w.chat_done.connect(lambda _ok: w.begin_exit())
        print("[diag] demo-quit-on-chat enabled")

    print("[ready] maid is floating. Right-click body -> Quit. (q/esc also quit)")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
