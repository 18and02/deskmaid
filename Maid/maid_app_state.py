"""Small persisted UI state for the desktop maid."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import threading
import time

from maid_paths import default_state_path
from maid_preferences import (
    DEFAULT_LANGUAGE,
    DEFAULT_UI_LANGUAGE,
    normalize_budget_mode,
    normalize_language,
    normalize_ui_language,
)

APP_STATE_ENV_VAR = "MAID_APP_STATE_PATH"
DEFAULT_APP_STATE_PATH = default_state_path(".maid_app_state.json")
DEFAULT_REMINDERS_ENABLED = True
DEFAULT_WATER_REMINDER_ENABLED = True
DEFAULT_WATER_REMINDER_MINUTES = 30
DEFAULT_WATER_REMINDER_TEXT = "水喝够了吗？血液太黏稠程序会跑得慢哦。"
DEFAULT_ACTIVITY_REMINDER_ENABLED = True
DEFAULT_ACTIVITY_REMINDER_MINUTES = 60
DEFAULT_ACTIVITY_REMINDER_TEXT = "已经坐了好一会了——再不站起来，你的关节会比我老得快。"
DEFAULT_CUSTOM_REMINDER_ENABLED = False
DEFAULT_CUSTOM_REMINDER_MINUTES = 30
DEFAULT_CUSTOM_REMINDER_TEXT = "休息一下吧"
MIN_REMINDER_MINUTES = 1
MAX_REMINDER_MINUTES = 720
DEFAULT_SPRITE_SIZE_PERCENT = 100
MIN_SPRITE_SIZE_PERCENT = 20
MAX_SPRITE_SIZE_PERCENT = 300
DEFAULT_SPRITE_POSITION_X_PERCENT = 50
DEFAULT_SPRITE_POSITION_Y_PERCENT = 50
SPRITE_SCREEN_MODE_PRIMARY = "primary"
SPRITE_SCREEN_MODE_CURSOR = "cursor"
DEFAULT_SPRITE_SCREEN_MODE = SPRITE_SCREEN_MODE_PRIMARY
SPRITE_SCREEN_MODES = {
    SPRITE_SCREEN_MODE_PRIMARY,
    SPRITE_SCREEN_MODE_CURSOR,
}


def _normalize_reminder_minutes(value: object, fallback: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = int(fallback)
    return max(MIN_REMINDER_MINUTES, min(MAX_REMINDER_MINUTES, normalized))


def _normalize_reminder_text(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    return text[:120]


def _normalize_int_range(value: object, fallback: int, low: int, high: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = int(fallback)
    return max(low, min(high, normalized))


def _normalize_sprite_screen_mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SPRITE_SCREEN_MODES:
        return normalized
    return DEFAULT_SPRITE_SCREEN_MODE


@dataclass(frozen=True)
class AppStateSnapshot:
    onboarding_seen: bool = False
    setup_version_seen: int = 0
    do_not_disturb: bool = False
    auto_do_not_disturb_enabled: bool = True
    owner_name: str = ""
    budget_mode: str = "normal"
    language: str = DEFAULT_LANGUAGE
    ui_language: str = DEFAULT_UI_LANGUAGE
    sprite_pack_id: str = ""
    sprite_size_percent: int = DEFAULT_SPRITE_SIZE_PERCENT
    sprite_position_x_percent: int = DEFAULT_SPRITE_POSITION_X_PERCENT
    sprite_position_y_percent: int = DEFAULT_SPRITE_POSITION_Y_PERCENT
    sprite_screen_mode: str = DEFAULT_SPRITE_SCREEN_MODE
    data_boundary_acknowledged: bool = False
    auto_hide_on_sensitive_scene: bool = True
    reminders_enabled: bool = DEFAULT_REMINDERS_ENABLED
    water_reminder_enabled: bool = DEFAULT_WATER_REMINDER_ENABLED
    water_reminder_minutes: int = DEFAULT_WATER_REMINDER_MINUTES
    water_reminder_text: str = DEFAULT_WATER_REMINDER_TEXT
    activity_reminder_enabled: bool = DEFAULT_ACTIVITY_REMINDER_ENABLED
    activity_reminder_minutes: int = DEFAULT_ACTIVITY_REMINDER_MINUTES
    activity_reminder_text: str = DEFAULT_ACTIVITY_REMINDER_TEXT
    custom_reminder_enabled: bool = DEFAULT_CUSTOM_REMINDER_ENABLED
    custom_reminder_minutes: int = DEFAULT_CUSTOM_REMINDER_MINUTES
    custom_reminder_text: str = DEFAULT_CUSTOM_REMINDER_TEXT
    updated_at: float = 0.0


def _app_state_path() -> Path:
    override = str(os.environ.get(APP_STATE_ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_APP_STATE_PATH


def _serialize(snapshot: AppStateSnapshot) -> str:
    payload = {
        "version": 1,
        **asdict(snapshot),
    }
    return json.dumps(payload, ensure_ascii=True, indent=2) + "\n"


def _load_snapshot(path: Path) -> AppStateSnapshot:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AppStateSnapshot()
    except OSError as exc:
        print(f"[app-state] failed to read {path}: {exc}")
        return AppStateSnapshot()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[app-state] failed to parse {path}: {exc}")
        return AppStateSnapshot()

    budget_mode = normalize_budget_mode(str(payload.get("budget_mode") or "normal"))
    language = normalize_language(str(payload.get("language") or DEFAULT_LANGUAGE))
    ui_language = normalize_ui_language(
        str(payload.get("ui_language") or DEFAULT_UI_LANGUAGE)
    )
    sprite_pack_id = str(payload.get("sprite_pack_id") or "").strip()
    onboarding_seen = bool(payload.get("onboarding_seen", False))
    setup_version_seen = int(payload.get("setup_version_seen") or 0)
    if setup_version_seen <= 0 and onboarding_seen:
        setup_version_seen = 1

    return AppStateSnapshot(
        onboarding_seen=onboarding_seen,
        setup_version_seen=max(0, setup_version_seen),
        do_not_disturb=bool(payload.get("do_not_disturb", False)),
        auto_do_not_disturb_enabled=bool(
            payload.get("auto_do_not_disturb_enabled", True)
        ),
        owner_name=str(payload.get("owner_name") or "").strip(),
        budget_mode=budget_mode,
        language=language,
        ui_language=ui_language,
        sprite_pack_id=sprite_pack_id,
        sprite_size_percent=_normalize_int_range(
            payload.get("sprite_size_percent"),
            DEFAULT_SPRITE_SIZE_PERCENT,
            MIN_SPRITE_SIZE_PERCENT,
            MAX_SPRITE_SIZE_PERCENT,
        ),
        sprite_position_x_percent=_normalize_int_range(
            payload.get("sprite_position_x_percent"),
            DEFAULT_SPRITE_POSITION_X_PERCENT,
            0,
            100,
        ),
        sprite_position_y_percent=_normalize_int_range(
            payload.get("sprite_position_y_percent"),
            DEFAULT_SPRITE_POSITION_Y_PERCENT,
            0,
            100,
        ),
        sprite_screen_mode=_normalize_sprite_screen_mode(
            payload.get("sprite_screen_mode")
        ),
        data_boundary_acknowledged=bool(payload.get("data_boundary_acknowledged", False)),
        auto_hide_on_sensitive_scene=bool(payload.get("auto_hide_on_sensitive_scene", True)),
        reminders_enabled=bool(payload.get("reminders_enabled", DEFAULT_REMINDERS_ENABLED)),
        water_reminder_enabled=bool(
            payload.get("water_reminder_enabled", DEFAULT_WATER_REMINDER_ENABLED)
        ),
        water_reminder_minutes=_normalize_reminder_minutes(
            payload.get("water_reminder_minutes"),
            DEFAULT_WATER_REMINDER_MINUTES,
        ),
        water_reminder_text=_normalize_reminder_text(
            payload.get("water_reminder_text"),
            DEFAULT_WATER_REMINDER_TEXT,
        ),
        activity_reminder_enabled=bool(
            payload.get("activity_reminder_enabled", DEFAULT_ACTIVITY_REMINDER_ENABLED)
        ),
        activity_reminder_minutes=_normalize_reminder_minutes(
            payload.get("activity_reminder_minutes"),
            DEFAULT_ACTIVITY_REMINDER_MINUTES,
        ),
        activity_reminder_text=_normalize_reminder_text(
            payload.get("activity_reminder_text"),
            DEFAULT_ACTIVITY_REMINDER_TEXT,
        ),
        custom_reminder_enabled=bool(
            payload.get("custom_reminder_enabled", DEFAULT_CUSTOM_REMINDER_ENABLED)
        ),
        custom_reminder_minutes=_normalize_reminder_minutes(
            payload.get("custom_reminder_minutes"),
            DEFAULT_CUSTOM_REMINDER_MINUTES,
        ),
        custom_reminder_text=_normalize_reminder_text(
            payload.get("custom_reminder_text"),
            DEFAULT_CUSTOM_REMINDER_TEXT,
        ),
        updated_at=float(payload.get("updated_at") or 0.0),
    )


def load_app_state_snapshot(path: Path | None = None) -> AppStateSnapshot:
    return _load_snapshot(path or _app_state_path())


class AppStateStore:
    def __init__(self, path: Path | None = None):
        self._path = path or _app_state_path()
        self._lock = threading.Lock()
        self._snapshot = _load_snapshot(self._path)

    def snapshot(self) -> AppStateSnapshot:
        with self._lock:
            return self._snapshot

    def set_onboarding_seen(self, seen: bool = True) -> AppStateSnapshot:
        with self._lock:
            self._snapshot = AppStateSnapshot(
                onboarding_seen=bool(seen),
                setup_version_seen=self._snapshot.setup_version_seen,
                do_not_disturb=self._snapshot.do_not_disturb,
                auto_do_not_disturb_enabled=self._snapshot.auto_do_not_disturb_enabled,
                owner_name=self._snapshot.owner_name,
                budget_mode=self._snapshot.budget_mode,
                language=self._snapshot.language,
                ui_language=self._snapshot.ui_language,
                sprite_pack_id=self._snapshot.sprite_pack_id,
                sprite_size_percent=self._snapshot.sprite_size_percent,
                sprite_position_x_percent=self._snapshot.sprite_position_x_percent,
                sprite_position_y_percent=self._snapshot.sprite_position_y_percent,
                sprite_screen_mode=self._snapshot.sprite_screen_mode,
                data_boundary_acknowledged=self._snapshot.data_boundary_acknowledged,
                auto_hide_on_sensitive_scene=self._snapshot.auto_hide_on_sensitive_scene,
                reminders_enabled=self._snapshot.reminders_enabled,
                water_reminder_enabled=self._snapshot.water_reminder_enabled,
                water_reminder_minutes=self._snapshot.water_reminder_minutes,
                water_reminder_text=self._snapshot.water_reminder_text,
                activity_reminder_enabled=self._snapshot.activity_reminder_enabled,
                activity_reminder_minutes=self._snapshot.activity_reminder_minutes,
                activity_reminder_text=self._snapshot.activity_reminder_text,
                custom_reminder_enabled=self._snapshot.custom_reminder_enabled,
                custom_reminder_minutes=self._snapshot.custom_reminder_minutes,
                custom_reminder_text=self._snapshot.custom_reminder_text,
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot

    def apply_setup(
        self,
        *,
        onboarding_seen: bool,
        setup_version_seen: int,
        owner_name: str,
        budget_mode: str,
        language: str,
        ui_language: str,
        data_boundary_acknowledged: bool,
        auto_do_not_disturb_enabled: bool,
        auto_hide_on_sensitive_scene: bool,
    ) -> AppStateSnapshot:
        normalized_budget_mode = normalize_budget_mode(budget_mode)
        normalized_language = normalize_language(language)
        normalized_ui_language = normalize_ui_language(ui_language)
        with self._lock:
            self._snapshot = AppStateSnapshot(
                onboarding_seen=bool(onboarding_seen),
                setup_version_seen=max(0, int(setup_version_seen or 0)),
                do_not_disturb=self._snapshot.do_not_disturb,
                auto_do_not_disturb_enabled=bool(auto_do_not_disturb_enabled),
                owner_name=str(owner_name or "").strip(),
                budget_mode=normalized_budget_mode,
                language=normalized_language,
                ui_language=normalized_ui_language,
                sprite_pack_id=self._snapshot.sprite_pack_id,
                sprite_size_percent=self._snapshot.sprite_size_percent,
                sprite_position_x_percent=self._snapshot.sprite_position_x_percent,
                sprite_position_y_percent=self._snapshot.sprite_position_y_percent,
                sprite_screen_mode=self._snapshot.sprite_screen_mode,
                data_boundary_acknowledged=bool(data_boundary_acknowledged),
                auto_hide_on_sensitive_scene=bool(auto_hide_on_sensitive_scene),
                reminders_enabled=self._snapshot.reminders_enabled,
                water_reminder_enabled=self._snapshot.water_reminder_enabled,
                water_reminder_minutes=self._snapshot.water_reminder_minutes,
                water_reminder_text=self._snapshot.water_reminder_text,
                activity_reminder_enabled=self._snapshot.activity_reminder_enabled,
                activity_reminder_minutes=self._snapshot.activity_reminder_minutes,
                activity_reminder_text=self._snapshot.activity_reminder_text,
                custom_reminder_enabled=self._snapshot.custom_reminder_enabled,
                custom_reminder_minutes=self._snapshot.custom_reminder_minutes,
                custom_reminder_text=self._snapshot.custom_reminder_text,
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot

    def set_do_not_disturb(self, enabled: bool) -> AppStateSnapshot:
        with self._lock:
            self._snapshot = AppStateSnapshot(
                onboarding_seen=self._snapshot.onboarding_seen,
                setup_version_seen=self._snapshot.setup_version_seen,
                do_not_disturb=bool(enabled),
                auto_do_not_disturb_enabled=self._snapshot.auto_do_not_disturb_enabled,
                owner_name=self._snapshot.owner_name,
                budget_mode=self._snapshot.budget_mode,
                language=self._snapshot.language,
                ui_language=self._snapshot.ui_language,
                sprite_pack_id=self._snapshot.sprite_pack_id,
                sprite_size_percent=self._snapshot.sprite_size_percent,
                sprite_position_x_percent=self._snapshot.sprite_position_x_percent,
                sprite_position_y_percent=self._snapshot.sprite_position_y_percent,
                sprite_screen_mode=self._snapshot.sprite_screen_mode,
                data_boundary_acknowledged=self._snapshot.data_boundary_acknowledged,
                auto_hide_on_sensitive_scene=self._snapshot.auto_hide_on_sensitive_scene,
                reminders_enabled=self._snapshot.reminders_enabled,
                water_reminder_enabled=self._snapshot.water_reminder_enabled,
                water_reminder_minutes=self._snapshot.water_reminder_minutes,
                water_reminder_text=self._snapshot.water_reminder_text,
                activity_reminder_enabled=self._snapshot.activity_reminder_enabled,
                activity_reminder_minutes=self._snapshot.activity_reminder_minutes,
                activity_reminder_text=self._snapshot.activity_reminder_text,
                custom_reminder_enabled=self._snapshot.custom_reminder_enabled,
                custom_reminder_minutes=self._snapshot.custom_reminder_minutes,
                custom_reminder_text=self._snapshot.custom_reminder_text,
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot

    def set_sprite_pack_id(self, pack_id: str) -> AppStateSnapshot:
        normalized_pack_id = str(pack_id or "").strip()
        with self._lock:
            self._snapshot = AppStateSnapshot(
                onboarding_seen=self._snapshot.onboarding_seen,
                setup_version_seen=self._snapshot.setup_version_seen,
                do_not_disturb=self._snapshot.do_not_disturb,
                auto_do_not_disturb_enabled=self._snapshot.auto_do_not_disturb_enabled,
                owner_name=self._snapshot.owner_name,
                budget_mode=self._snapshot.budget_mode,
                language=self._snapshot.language,
                ui_language=self._snapshot.ui_language,
                sprite_pack_id=normalized_pack_id,
                sprite_size_percent=self._snapshot.sprite_size_percent,
                sprite_position_x_percent=self._snapshot.sprite_position_x_percent,
                sprite_position_y_percent=self._snapshot.sprite_position_y_percent,
                sprite_screen_mode=self._snapshot.sprite_screen_mode,
                data_boundary_acknowledged=self._snapshot.data_boundary_acknowledged,
                auto_hide_on_sensitive_scene=self._snapshot.auto_hide_on_sensitive_scene,
                reminders_enabled=self._snapshot.reminders_enabled,
                water_reminder_enabled=self._snapshot.water_reminder_enabled,
                water_reminder_minutes=self._snapshot.water_reminder_minutes,
                water_reminder_text=self._snapshot.water_reminder_text,
                activity_reminder_enabled=self._snapshot.activity_reminder_enabled,
                activity_reminder_minutes=self._snapshot.activity_reminder_minutes,
                activity_reminder_text=self._snapshot.activity_reminder_text,
                custom_reminder_enabled=self._snapshot.custom_reminder_enabled,
                custom_reminder_minutes=self._snapshot.custom_reminder_minutes,
                custom_reminder_text=self._snapshot.custom_reminder_text,
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot

    def set_sprite_display_preferences(
        self,
        *,
        sprite_size_percent: int,
        sprite_position_x_percent: int,
        sprite_position_y_percent: int,
        sprite_screen_mode: str,
    ) -> AppStateSnapshot:
        with self._lock:
            self._snapshot = AppStateSnapshot(
                onboarding_seen=self._snapshot.onboarding_seen,
                setup_version_seen=self._snapshot.setup_version_seen,
                do_not_disturb=self._snapshot.do_not_disturb,
                auto_do_not_disturb_enabled=self._snapshot.auto_do_not_disturb_enabled,
                owner_name=self._snapshot.owner_name,
                budget_mode=self._snapshot.budget_mode,
                language=self._snapshot.language,
                ui_language=self._snapshot.ui_language,
                sprite_pack_id=self._snapshot.sprite_pack_id,
                sprite_size_percent=_normalize_int_range(
                    sprite_size_percent,
                    DEFAULT_SPRITE_SIZE_PERCENT,
                    MIN_SPRITE_SIZE_PERCENT,
                    MAX_SPRITE_SIZE_PERCENT,
                ),
                sprite_position_x_percent=_normalize_int_range(
                    sprite_position_x_percent,
                    DEFAULT_SPRITE_POSITION_X_PERCENT,
                    0,
                    100,
                ),
                sprite_position_y_percent=_normalize_int_range(
                    sprite_position_y_percent,
                    DEFAULT_SPRITE_POSITION_Y_PERCENT,
                    0,
                    100,
                ),
                sprite_screen_mode=_normalize_sprite_screen_mode(sprite_screen_mode),
                data_boundary_acknowledged=self._snapshot.data_boundary_acknowledged,
                auto_hide_on_sensitive_scene=self._snapshot.auto_hide_on_sensitive_scene,
                reminders_enabled=self._snapshot.reminders_enabled,
                water_reminder_enabled=self._snapshot.water_reminder_enabled,
                water_reminder_minutes=self._snapshot.water_reminder_minutes,
                water_reminder_text=self._snapshot.water_reminder_text,
                activity_reminder_enabled=self._snapshot.activity_reminder_enabled,
                activity_reminder_minutes=self._snapshot.activity_reminder_minutes,
                activity_reminder_text=self._snapshot.activity_reminder_text,
                custom_reminder_enabled=self._snapshot.custom_reminder_enabled,
                custom_reminder_minutes=self._snapshot.custom_reminder_minutes,
                custom_reminder_text=self._snapshot.custom_reminder_text,
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot

    def set_auto_do_not_disturb_enabled(self, enabled: bool) -> AppStateSnapshot:
        with self._lock:
            self._snapshot = AppStateSnapshot(
                onboarding_seen=self._snapshot.onboarding_seen,
                setup_version_seen=self._snapshot.setup_version_seen,
                do_not_disturb=self._snapshot.do_not_disturb,
                auto_do_not_disturb_enabled=bool(enabled),
                owner_name=self._snapshot.owner_name,
                budget_mode=self._snapshot.budget_mode,
                language=self._snapshot.language,
                ui_language=self._snapshot.ui_language,
                sprite_pack_id=self._snapshot.sprite_pack_id,
                sprite_size_percent=self._snapshot.sprite_size_percent,
                sprite_position_x_percent=self._snapshot.sprite_position_x_percent,
                sprite_position_y_percent=self._snapshot.sprite_position_y_percent,
                sprite_screen_mode=self._snapshot.sprite_screen_mode,
                data_boundary_acknowledged=self._snapshot.data_boundary_acknowledged,
                auto_hide_on_sensitive_scene=self._snapshot.auto_hide_on_sensitive_scene,
                reminders_enabled=self._snapshot.reminders_enabled,
                water_reminder_enabled=self._snapshot.water_reminder_enabled,
                water_reminder_minutes=self._snapshot.water_reminder_minutes,
                water_reminder_text=self._snapshot.water_reminder_text,
                activity_reminder_enabled=self._snapshot.activity_reminder_enabled,
                activity_reminder_minutes=self._snapshot.activity_reminder_minutes,
                activity_reminder_text=self._snapshot.activity_reminder_text,
                custom_reminder_enabled=self._snapshot.custom_reminder_enabled,
                custom_reminder_minutes=self._snapshot.custom_reminder_minutes,
                custom_reminder_text=self._snapshot.custom_reminder_text,
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot

    def set_auto_hide_on_sensitive_scene(self, enabled: bool) -> AppStateSnapshot:
        with self._lock:
            self._snapshot = AppStateSnapshot(
                onboarding_seen=self._snapshot.onboarding_seen,
                setup_version_seen=self._snapshot.setup_version_seen,
                do_not_disturb=self._snapshot.do_not_disturb,
                auto_do_not_disturb_enabled=self._snapshot.auto_do_not_disturb_enabled,
                owner_name=self._snapshot.owner_name,
                budget_mode=self._snapshot.budget_mode,
                language=self._snapshot.language,
                ui_language=self._snapshot.ui_language,
                sprite_pack_id=self._snapshot.sprite_pack_id,
                sprite_size_percent=self._snapshot.sprite_size_percent,
                sprite_position_x_percent=self._snapshot.sprite_position_x_percent,
                sprite_position_y_percent=self._snapshot.sprite_position_y_percent,
                sprite_screen_mode=self._snapshot.sprite_screen_mode,
                data_boundary_acknowledged=self._snapshot.data_boundary_acknowledged,
                auto_hide_on_sensitive_scene=bool(enabled),
                reminders_enabled=self._snapshot.reminders_enabled,
                water_reminder_enabled=self._snapshot.water_reminder_enabled,
                water_reminder_minutes=self._snapshot.water_reminder_minutes,
                water_reminder_text=self._snapshot.water_reminder_text,
                activity_reminder_enabled=self._snapshot.activity_reminder_enabled,
                activity_reminder_minutes=self._snapshot.activity_reminder_minutes,
                activity_reminder_text=self._snapshot.activity_reminder_text,
                custom_reminder_enabled=self._snapshot.custom_reminder_enabled,
                custom_reminder_minutes=self._snapshot.custom_reminder_minutes,
                custom_reminder_text=self._snapshot.custom_reminder_text,
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot

    def set_reminder_preferences(
        self,
        *,
        reminders_enabled: bool,
        water_reminder_enabled: bool,
        water_reminder_minutes: int,
        activity_reminder_enabled: bool,
        activity_reminder_minutes: int,
        custom_reminder_enabled: bool,
        custom_reminder_minutes: int,
        custom_reminder_text: str,
    ) -> AppStateSnapshot:
        with self._lock:
            self._snapshot = AppStateSnapshot(
                onboarding_seen=self._snapshot.onboarding_seen,
                setup_version_seen=self._snapshot.setup_version_seen,
                do_not_disturb=self._snapshot.do_not_disturb,
                auto_do_not_disturb_enabled=self._snapshot.auto_do_not_disturb_enabled,
                owner_name=self._snapshot.owner_name,
                budget_mode=self._snapshot.budget_mode,
                language=self._snapshot.language,
                ui_language=self._snapshot.ui_language,
                sprite_pack_id=self._snapshot.sprite_pack_id,
                sprite_size_percent=self._snapshot.sprite_size_percent,
                sprite_position_x_percent=self._snapshot.sprite_position_x_percent,
                sprite_position_y_percent=self._snapshot.sprite_position_y_percent,
                sprite_screen_mode=self._snapshot.sprite_screen_mode,
                data_boundary_acknowledged=self._snapshot.data_boundary_acknowledged,
                auto_hide_on_sensitive_scene=self._snapshot.auto_hide_on_sensitive_scene,
                reminders_enabled=bool(reminders_enabled),
                water_reminder_enabled=bool(water_reminder_enabled),
                water_reminder_minutes=_normalize_reminder_minutes(
                    water_reminder_minutes,
                    DEFAULT_WATER_REMINDER_MINUTES,
                ),
                water_reminder_text=self._snapshot.water_reminder_text,
                activity_reminder_enabled=bool(activity_reminder_enabled),
                activity_reminder_minutes=_normalize_reminder_minutes(
                    activity_reminder_minutes,
                    DEFAULT_ACTIVITY_REMINDER_MINUTES,
                ),
                activity_reminder_text=self._snapshot.activity_reminder_text,
                custom_reminder_enabled=bool(custom_reminder_enabled),
                custom_reminder_minutes=_normalize_reminder_minutes(
                    custom_reminder_minutes,
                    DEFAULT_CUSTOM_REMINDER_MINUTES,
                ),
                custom_reminder_text=_normalize_reminder_text(
                    custom_reminder_text,
                    DEFAULT_CUSTOM_REMINDER_TEXT,
                ),
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot

    def _save_locked(self):
        tmp_path = self._path.with_name(f"{self._path.name}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(_serialize(self._snapshot), encoding="utf-8")
            tmp_path.replace(self._path)
        except OSError as exc:
            print(f"[app-state] failed to write {self._path}: {exc}")
            try:
                tmp_path.unlink()
            except OSError:
                pass
