"""Persistent budget ledger and runtime-aware guardrails for Deskmaid."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
import time

from maid_paths import default_state_path
from maid_preferences import (
    BUDGET_MODE_DAILY_LIMIT_USD,
    BUDGET_MODE_WEEKLY_LIMIT_USD,
    normalize_budget_mode,
)


BUDGET_STATE_ENV_VAR = "MAID_BUDGET_STATE_PATH"
DEFAULT_BUDGET_STATE_PATH = default_state_path(".maid_budget.json")
_BUDGET_RETENTION_DAYS = 120
_EPSILON = 1e-6
_IDLE_THROTTLE_IDLE_AFTER_S = 10 * 60
_IDLE_THROTTLE_AWAY_AFTER_S = 45 * 60
_IDLE_THROTTLE_PARKED_AFTER_S = 6 * 60 * 60
_SUSPENDED_IDLE_DISCOUNT = 0.20
_PRESSURE_WARNING_RATIO = 0.25
_PRESSURE_CRITICAL_RATIO = 0.10
_PRESSURE_WARNING_BASE_RUNS = 1.5


@dataclass(frozen=True)
class BudgetUsageEntry:
    recorded_at: float
    cost_usd: float
    mode: str = "normal"
    session_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""


@dataclass(frozen=True)
class BudgetRuntimeState:
    last_activity_at: float = 0.0
    last_suspend_at: float = 0.0
    last_resume_at: float = 0.0
    suspended_since_activity_s: float = 0.0
    last_seen_day_key: str = ""
    last_seen_week_key: str = ""


@dataclass(frozen=True)
class BudgetGuardStatus:
    mode: str
    per_run_limit_usd: float | None
    effective_max_budget_usd: float | None
    daily_limit_usd: float | None
    daily_used_usd: float
    daily_remaining_usd: float | None
    weekly_limit_usd: float | None
    weekly_used_usd: float
    weekly_remaining_usd: float | None
    raw_idle_seconds: float = 0.0
    suspended_idle_seconds: float = 0.0
    folded_idle_seconds: float = 0.0
    idle_throttle_factor: float = 1.0
    idle_throttle_stage: str = "active"
    idle_throttle_reason: str = ""
    daily_pressure_level: str = "ok"
    weekly_pressure_level: str = "ok"
    daily_base_runs_left: float | None = None
    weekly_base_runs_left: float | None = None
    remaining_allows_full_base_run: bool = True
    remaining_shortfall_usd: float = 0.0
    next_daily_reset_at: float = 0.0
    next_weekly_reset_at: float = 0.0
    blocked: bool = False
    blocked_scope: str = ""
    updated_at: float = field(default_factory=time.time)


def _budget_state_path() -> Path:
    override = str(os.environ.get(BUDGET_STATE_ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_BUDGET_STATE_PATH


def _serialize(
    entries: list[BudgetUsageEntry],
    runtime: BudgetRuntimeState,
) -> str:
    payload = {
        "version": 2,
        "entries": [asdict(entry) for entry in entries],
        "runtime": asdict(runtime),
    }
    return json.dumps(payload, ensure_ascii=True, indent=2) + "\n"


def _load_state(path: Path) -> tuple[list[BudgetUsageEntry], BudgetRuntimeState]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], BudgetRuntimeState()
    except OSError as exc:
        print(f"[budget] failed to read {path}: {exc}")
        return [], BudgetRuntimeState()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[budget] failed to parse {path}: {exc}")
        return [], BudgetRuntimeState()

    if not isinstance(payload, dict):
        return [], BudgetRuntimeState()

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raw_entries = []

    entries: list[BudgetUsageEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        try:
            entry = BudgetUsageEntry(
                recorded_at=float(raw_entry.get("recorded_at") or 0.0),
                cost_usd=max(0.0, float(raw_entry.get("cost_usd") or 0.0)),
                mode=normalize_budget_mode(str(raw_entry.get("mode") or "normal")),
                session_id=str(raw_entry.get("session_id") or "").strip(),
                input_tokens=max(0, int(raw_entry.get("input_tokens") or 0)),
                output_tokens=max(0, int(raw_entry.get("output_tokens") or 0)),
                stop_reason=str(raw_entry.get("stop_reason") or "").strip(),
            )
        except Exception:
            continue
        if entry.recorded_at <= 0 or entry.cost_usd <= 0:
            continue
        entries.append(entry)

    entries.sort(key=lambda item: item.recorded_at)

    runtime = BudgetRuntimeState()
    raw_runtime = payload.get("runtime")
    if isinstance(raw_runtime, dict):
        try:
            runtime = BudgetRuntimeState(
                last_activity_at=max(0.0, float(raw_runtime.get("last_activity_at") or 0.0)),
                last_suspend_at=max(0.0, float(raw_runtime.get("last_suspend_at") or 0.0)),
                last_resume_at=max(0.0, float(raw_runtime.get("last_resume_at") or 0.0)),
                suspended_since_activity_s=max(
                    0.0,
                    float(raw_runtime.get("suspended_since_activity_s") or 0.0),
                ),
                last_seen_day_key=str(raw_runtime.get("last_seen_day_key") or "").strip(),
                last_seen_week_key=str(raw_runtime.get("last_seen_week_key") or "").strip(),
            )
        except Exception:
            runtime = BudgetRuntimeState()

    return entries, runtime


def _local_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).astimezone()


def _local_day_key(timestamp: float) -> str:
    return _local_datetime(timestamp).date().isoformat()


def _local_week_key(timestamp: float) -> str:
    iso = _local_datetime(timestamp).isocalendar()
    return f"{int(iso.year):04d}-W{int(iso.week):02d}"


def _same_local_day(timestamp: float, reference: datetime) -> bool:
    dt = _local_datetime(timestamp)
    return dt.date() == reference.date()


def _same_local_week(timestamp: float, reference: datetime) -> bool:
    dt = _local_datetime(timestamp)
    return dt.isocalendar()[:2] == reference.isocalendar()[:2]


def _remaining(limit_usd: float | None, used_usd: float) -> float | None:
    if limit_usd is None:
        return None
    return max(0.0, float(limit_usd) - max(0.0, float(used_usd)))


def _remaining_ratio(limit_usd: float | None, remaining_usd: float | None) -> float | None:
    if limit_usd is None or remaining_usd is None:
        return None
    limit = max(0.0, float(limit_usd))
    if limit <= _EPSILON:
        return None
    return max(0.0, min(1.0, float(remaining_usd) / limit))


def _remaining_base_runs(
    remaining_usd: float | None,
    per_run_limit_usd: float | None,
) -> float | None:
    if remaining_usd is None or per_run_limit_usd is None:
        return None
    per_run = max(0.0, float(per_run_limit_usd))
    if per_run <= _EPSILON:
        return None
    return max(0.0, float(remaining_usd) / per_run)


def _pressure_level(
    limit_usd: float | None,
    remaining_usd: float | None,
    *,
    per_run_limit_usd: float | None,
) -> str:
    if remaining_usd is None:
        return "ok"
    if remaining_usd <= _EPSILON:
        return "blocked"

    base_runs_left = _remaining_base_runs(remaining_usd, per_run_limit_usd)
    if base_runs_left is not None:
        if base_runs_left < 1.0 - _EPSILON:
            return "critical"
        if base_runs_left <= _PRESSURE_WARNING_BASE_RUNS + _EPSILON:
            return "warning"

    ratio = _remaining_ratio(limit_usd, remaining_usd)
    if ratio is None:
        return "ok"
    if ratio <= _PRESSURE_CRITICAL_RATIO + _EPSILON:
        return "critical"
    if ratio <= _PRESSURE_WARNING_RATIO + _EPSILON:
        return "warning"
    return "ok"


def _next_local_day_reset_at(timestamp: float) -> float:
    local_now = _local_datetime(timestamp)
    next_day = datetime.combine(
        local_now.date() + timedelta(days=1),
        datetime.min.time(),
        tzinfo=local_now.tzinfo,
    )
    return next_day.timestamp()


def _next_local_week_reset_at(timestamp: float) -> float:
    local_now = _local_datetime(timestamp)
    days_until_next_week = 8 - int(local_now.isoweekday())
    next_week = datetime.combine(
        local_now.date() + timedelta(days=days_until_next_week),
        datetime.min.time(),
        tzinfo=local_now.tzinfo,
    )
    return next_week.timestamp()


def _prune_entries(entries: list[BudgetUsageEntry], now: float) -> list[BudgetUsageEntry]:
    cutoff = _local_datetime(now) - timedelta(days=_BUDGET_RETENTION_DAYS)
    return [
        entry
        for entry in entries
        if _local_datetime(entry.recorded_at) >= cutoff
    ]


def _runtime_is_empty(runtime: BudgetRuntimeState) -> bool:
    return (
        runtime.last_activity_at <= _EPSILON
        and runtime.last_suspend_at <= _EPSILON
        and runtime.last_resume_at <= _EPSILON
        and runtime.suspended_since_activity_s <= _EPSILON
        and not runtime.last_seen_day_key
        and not runtime.last_seen_week_key
    )


def _idle_runtime(
    runtime: BudgetRuntimeState,
    *,
    now: float,
) -> tuple[float, float, float, str, float, str]:
    if runtime.last_activity_at <= _EPSILON:
        return 0.0, 0.0, 0.0, "active", 1.0, ""

    raw_idle_seconds = max(0.0, float(now) - runtime.last_activity_at)
    suspended_idle_seconds = max(0.0, runtime.suspended_since_activity_s)
    if runtime.last_suspend_at > _EPSILON and now > runtime.last_suspend_at:
        suspended_idle_seconds += now - runtime.last_suspend_at
    suspended_idle_seconds = min(suspended_idle_seconds, raw_idle_seconds)
    awake_idle_seconds = max(0.0, raw_idle_seconds - suspended_idle_seconds)
    folded_idle_seconds = (
        awake_idle_seconds + suspended_idle_seconds * _SUSPENDED_IDLE_DISCOUNT
    )

    if folded_idle_seconds >= _IDLE_THROTTLE_PARKED_AFTER_S:
        return (
            raw_idle_seconds,
            suspended_idle_seconds,
            folded_idle_seconds,
            "parked",
            0.35,
            "常驻待机档",
        )
    if folded_idle_seconds >= _IDLE_THROTTLE_AWAY_AFTER_S:
        return (
            raw_idle_seconds,
            suspended_idle_seconds,
            folded_idle_seconds,
            "away",
            0.60,
            "离开较久",
        )
    if folded_idle_seconds >= _IDLE_THROTTLE_IDLE_AFTER_S:
        return (
            raw_idle_seconds,
            suspended_idle_seconds,
            folded_idle_seconds,
            "idle",
            0.80,
            "闲时待机",
        )
    return raw_idle_seconds, suspended_idle_seconds, folded_idle_seconds, "active", 1.0, ""


def format_budget_usage_summary(status: BudgetGuardStatus) -> str:
    daily_limit = (
        f"${status.daily_limit_usd:.2f}" if status.daily_limit_usd is not None else "n/a"
    )
    weekly_limit = (
        f"${status.weekly_limit_usd:.2f}" if status.weekly_limit_usd is not None else "n/a"
    )
    return (
        f"今日 ${status.daily_used_usd:.2f} / {daily_limit}；"
        f"本周 ${status.weekly_used_usd:.2f} / {weekly_limit}"
    )


def _format_budget_reset_at(timestamp: float) -> str:
    if float(timestamp or 0.0) <= _EPSILON:
        return ""
    return _local_datetime(timestamp).strftime("%Y-%m-%d %H:%M")


def _format_base_runs_left(runs_left: float | None) -> str:
    if runs_left is None:
        return ""
    runs = max(0.0, float(runs_left))
    rounded = round(runs)
    if abs(runs - rounded) <= 0.05:
        return f"{int(rounded)}轮"
    return f"{runs:.1f}轮"


def format_budget_block_message(status: BudgetGuardStatus) -> str:
    if status.blocked_scope == "week":
        reset_at = _format_budget_reset_at(status.next_weekly_reset_at)
        tail = (
            f"要继续的话，等本周预算窗在 {reset_at} 重置，"
            "或在设置里把预算档位调高。"
            if reset_at
            else "要继续的话，等下周预算窗重置，或在设置里把预算档位调高。"
        )
        head = "这周的预算已经到上限了。"
    else:
        reset_at = _format_budget_reset_at(status.next_daily_reset_at)
        tail = (
            f"要继续的话，等今天预算窗在 {reset_at} 重置，"
            "或在设置里把预算档位调高。"
            if reset_at
            else "要继续的话，等今天预算窗重置，或在设置里把预算档位调高。"
        )
        head = "今天的预算已经到上限了。"
    return f"{head}\n\n{format_budget_usage_summary(status)}。\n{tail}"


def format_budget_reset_message(
    status: BudgetGuardStatus,
    *,
    scopes: list[str],
) -> str:
    normalized_scopes = [scope for scope in scopes if scope in {"day", "week"}]
    if "day" in normalized_scopes and "week" in normalized_scopes:
        head = "今天和本周的预算窗都已经重置了。"
    elif "week" in normalized_scopes:
        head = "本周的预算窗已经重置了。"
    else:
        head = "今天的预算窗已经重置了。"
    return f"{head}\n\n{format_budget_usage_summary(status)}。"


def format_budget_tightening_message(
    status: BudgetGuardStatus,
    *,
    base_per_run_limit_usd: float | None,
) -> str:
    if (
        base_per_run_limit_usd is None
        or status.effective_max_budget_usd is None
        or status.effective_max_budget_usd >= base_per_run_limit_usd - _EPSILON
    ):
        return ""

    reasons: list[str] = []
    if status.idle_throttle_factor < 1.0 - _EPSILON and status.idle_throttle_reason:
        reasons.append(
            f"{status.idle_throttle_reason} {int(round(status.idle_throttle_factor * 100))}%"
        )
    if (
        status.daily_remaining_usd is not None
        and status.daily_remaining_usd < base_per_run_limit_usd - _EPSILON
    ):
        runs_left = _format_base_runs_left(status.daily_base_runs_left)
        if runs_left:
            reasons.append(f"今日按基础档只够 {runs_left}")
        else:
            reasons.append(f"今日剩余 ${status.daily_remaining_usd:.2f}")
    if (
        status.weekly_remaining_usd is not None
        and status.weekly_remaining_usd < base_per_run_limit_usd - _EPSILON
    ):
        runs_left = _format_base_runs_left(status.weekly_base_runs_left)
        if runs_left:
            reasons.append(f"本周按基础档只够 {runs_left}")
        else:
            reasons.append(f"本周剩余 ${status.weekly_remaining_usd:.2f}")

    if (
        not status.remaining_allows_full_base_run
        and status.remaining_shortfall_usd > _EPSILON
    ):
        reasons.append(f"还差 ${status.remaining_shortfall_usd:.2f} 才够一整轮基础档")

    if not reasons:
        return ""

    return (
        f"单轮预算上限已从 ${base_per_run_limit_usd:.2f} "
        f"收紧到 ${status.effective_max_budget_usd:.2f}（{'，'.join(reasons)}）。"
    )


class BudgetUsageStore:
    def __init__(self, path: Path | None = None):
        self._path = path or _budget_state_path()
        self._lock = threading.Lock()
        self._entries, self._runtime = _load_state(self._path)
        with self._lock:
            pruned = _prune_entries(self._entries, time.time())
            if len(pruned) != len(self._entries):
                self._entries = pruned
                self._save_locked()

    def _save_locked(self):
        if not self._entries and _runtime_is_empty(self._runtime):
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f"[budget] failed to remove {self._path}: {exc}")
            return

        tmp_path = self._path.with_name(f"{self._path.name}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(
                _serialize(self._entries, self._runtime),
                encoding="utf-8",
            )
            tmp_path.replace(self._path)
        except OSError as exc:
            print(f"[budget] failed to write {self._path}: {exc}")
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def mark_activity(self, *, recorded_at: float | None = None) -> BudgetRuntimeState:
        current_time = float(recorded_at or time.time())
        with self._lock:
            self._entries = _prune_entries(self._entries, current_time)
            self._runtime = BudgetRuntimeState(
                last_activity_at=current_time,
                last_resume_at=max(self._runtime.last_resume_at, current_time),
                last_seen_day_key=self._runtime.last_seen_day_key,
                last_seen_week_key=self._runtime.last_seen_week_key,
            )
            self._save_locked()
            return self._runtime

    def note_suspend(self, *, recorded_at: float | None = None) -> BudgetRuntimeState:
        current_time = float(recorded_at or time.time())
        with self._lock:
            self._entries = _prune_entries(self._entries, current_time)
            if self._runtime.last_suspend_at > _EPSILON:
                return self._runtime
            self._runtime = BudgetRuntimeState(
                last_activity_at=self._runtime.last_activity_at,
                last_suspend_at=current_time,
                last_resume_at=self._runtime.last_resume_at,
                suspended_since_activity_s=self._runtime.suspended_since_activity_s,
                last_seen_day_key=self._runtime.last_seen_day_key,
                last_seen_week_key=self._runtime.last_seen_week_key,
            )
            self._save_locked()
            return self._runtime

    def note_resume(self, *, recorded_at: float | None = None) -> float:
        current_time = float(recorded_at or time.time())
        with self._lock:
            self._entries = _prune_entries(self._entries, current_time)
            suspended_for = 0.0
            if self._runtime.last_suspend_at > _EPSILON and current_time > self._runtime.last_suspend_at:
                suspended_for = current_time - self._runtime.last_suspend_at
            suspended_since_activity_s = self._runtime.suspended_since_activity_s
            if self._runtime.last_activity_at > _EPSILON:
                suspended_since_activity_s += suspended_for
            else:
                suspended_since_activity_s = 0.0
            self._runtime = BudgetRuntimeState(
                last_activity_at=self._runtime.last_activity_at,
                last_resume_at=current_time,
                suspended_since_activity_s=max(0.0, suspended_since_activity_s),
                last_seen_day_key=self._runtime.last_seen_day_key,
                last_seen_week_key=self._runtime.last_seen_week_key,
            )
            self._save_locked()
            return suspended_for

    def consume_reset_message(
        self,
        *,
        budget_mode: str,
        per_run_limit_usd: float | None,
        now: float | None = None,
    ) -> str:
        current_time = float(now or time.time())
        current_day_key = _local_day_key(current_time)
        current_week_key = _local_week_key(current_time)
        with self._lock:
            pruned = _prune_entries(self._entries, current_time)
            entries_pruned = len(pruned) != len(self._entries)
            if entries_pruned:
                self._entries = pruned
            entries = list(self._entries)
            runtime = self._runtime
            scopes: list[str] = []

            if runtime.last_seen_day_key and runtime.last_seen_day_key != current_day_key:
                previous_day_used = sum(
                    entry.cost_usd
                    for entry in entries
                    if _local_day_key(entry.recorded_at) == runtime.last_seen_day_key
                )
                if previous_day_used > _EPSILON:
                    scopes.append("day")

            if runtime.last_seen_week_key and runtime.last_seen_week_key != current_week_key:
                previous_week_used = sum(
                    entry.cost_usd
                    for entry in entries
                    if _local_week_key(entry.recorded_at) == runtime.last_seen_week_key
                )
                if previous_week_used > _EPSILON:
                    scopes.append("week")

            next_runtime = BudgetRuntimeState(
                last_activity_at=runtime.last_activity_at,
                last_suspend_at=runtime.last_suspend_at,
                last_resume_at=runtime.last_resume_at,
                suspended_since_activity_s=runtime.suspended_since_activity_s,
                last_seen_day_key=current_day_key,
                last_seen_week_key=current_week_key,
            )
            changed = next_runtime != self._runtime or entries_pruned
            self._entries = pruned
            self._runtime = next_runtime
            if changed:
                self._save_locked()

        if not scopes:
            return ""

        status = self.guard_status(
            budget_mode=budget_mode,
            per_run_limit_usd=per_run_limit_usd,
            now=current_time,
        )
        return format_budget_reset_message(status, scopes=scopes)

    def guard_status(
        self,
        *,
        budget_mode: str,
        per_run_limit_usd: float | None,
        now: float | None = None,
    ) -> BudgetGuardStatus:
        current_time = float(now or time.time())
        local_now = _local_datetime(current_time)
        normalized_mode = normalize_budget_mode(budget_mode)
        with self._lock:
            pruned = _prune_entries(self._entries, current_time)
            if len(pruned) != len(self._entries):
                self._entries = pruned
                self._save_locked()
            entries = list(self._entries)
            runtime = self._runtime

        daily_limit_usd = BUDGET_MODE_DAILY_LIMIT_USD.get(normalized_mode)
        weekly_limit_usd = BUDGET_MODE_WEEKLY_LIMIT_USD.get(normalized_mode)

        daily_used_usd = sum(
            entry.cost_usd
            for entry in entries
            if _same_local_day(entry.recorded_at, local_now)
        )
        weekly_used_usd = sum(
            entry.cost_usd
            for entry in entries
            if _same_local_week(entry.recorded_at, local_now)
        )

        daily_remaining_usd = _remaining(daily_limit_usd, daily_used_usd)
        weekly_remaining_usd = _remaining(weekly_limit_usd, weekly_used_usd)
        daily_pressure_level = _pressure_level(
            daily_limit_usd,
            daily_remaining_usd,
            per_run_limit_usd=per_run_limit_usd,
        )
        weekly_pressure_level = _pressure_level(
            weekly_limit_usd,
            weekly_remaining_usd,
            per_run_limit_usd=per_run_limit_usd,
        )
        daily_base_runs_left = _remaining_base_runs(
            daily_remaining_usd,
            per_run_limit_usd,
        )
        weekly_base_runs_left = _remaining_base_runs(
            weekly_remaining_usd,
            per_run_limit_usd,
        )
        remaining_candidates = [
            float(remaining)
            for remaining in (daily_remaining_usd, weekly_remaining_usd)
            if remaining is not None
        ]
        if per_run_limit_usd is None or not remaining_candidates:
            remaining_allows_full_base_run = True
            remaining_shortfall_usd = 0.0
        else:
            smallest_remaining = min(remaining_candidates)
            remaining_allows_full_base_run = (
                smallest_remaining >= float(per_run_limit_usd) - _EPSILON
            )
            remaining_shortfall_usd = max(
                0.0,
                float(per_run_limit_usd) - smallest_remaining,
            )
        (
            raw_idle_seconds,
            suspended_idle_seconds,
            folded_idle_seconds,
            idle_throttle_stage,
            idle_throttle_factor,
            idle_throttle_reason,
        ) = _idle_runtime(runtime, now=current_time)

        effective_max_budget_usd = per_run_limit_usd
        if effective_max_budget_usd is not None:
            effective_max_budget_usd *= idle_throttle_factor
            if daily_remaining_usd is not None:
                effective_max_budget_usd = min(effective_max_budget_usd, daily_remaining_usd)
            if weekly_remaining_usd is not None:
                effective_max_budget_usd = min(effective_max_budget_usd, weekly_remaining_usd)

        blocked_scope = ""
        blocked = False
        if daily_remaining_usd is not None and daily_remaining_usd <= _EPSILON:
            blocked = True
            blocked_scope = "day"
            effective_max_budget_usd = 0.0
        elif weekly_remaining_usd is not None and weekly_remaining_usd <= _EPSILON:
            blocked = True
            blocked_scope = "week"
            effective_max_budget_usd = 0.0

        return BudgetGuardStatus(
            mode=normalized_mode,
            per_run_limit_usd=per_run_limit_usd,
            effective_max_budget_usd=effective_max_budget_usd,
            daily_limit_usd=daily_limit_usd,
            daily_used_usd=daily_used_usd,
            daily_remaining_usd=daily_remaining_usd,
            weekly_limit_usd=weekly_limit_usd,
            weekly_used_usd=weekly_used_usd,
            weekly_remaining_usd=weekly_remaining_usd,
            raw_idle_seconds=raw_idle_seconds,
            suspended_idle_seconds=suspended_idle_seconds,
            folded_idle_seconds=folded_idle_seconds,
            idle_throttle_factor=idle_throttle_factor,
            idle_throttle_stage=idle_throttle_stage,
            idle_throttle_reason=idle_throttle_reason,
            daily_pressure_level=daily_pressure_level,
            weekly_pressure_level=weekly_pressure_level,
            daily_base_runs_left=daily_base_runs_left,
            weekly_base_runs_left=weekly_base_runs_left,
            remaining_allows_full_base_run=remaining_allows_full_base_run,
            remaining_shortfall_usd=remaining_shortfall_usd,
            next_daily_reset_at=_next_local_day_reset_at(current_time),
            next_weekly_reset_at=_next_local_week_reset_at(current_time),
            blocked=blocked,
            blocked_scope=blocked_scope,
            updated_at=current_time,
        )

    def record_usage(
        self,
        cost_usd: float | None,
        *,
        budget_mode: str,
        session_id: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        stop_reason: str = "",
        recorded_at: float | None = None,
    ) -> BudgetUsageEntry | None:
        amount = max(0.0, float(cost_usd or 0.0))
        if amount <= _EPSILON:
            return None

        entry = BudgetUsageEntry(
            recorded_at=float(recorded_at or time.time()),
            cost_usd=amount,
            mode=normalize_budget_mode(budget_mode),
            session_id=str(session_id or "").strip(),
            input_tokens=max(0, int(input_tokens or 0)),
            output_tokens=max(0, int(output_tokens or 0)),
            stop_reason=str(stop_reason or "").strip(),
        )
        with self._lock:
            self._entries.append(entry)
            self._entries.sort(key=lambda item: item.recorded_at)
            self._entries = _prune_entries(self._entries, entry.recorded_at)
            self._save_locked()
        return entry
