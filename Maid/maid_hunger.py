"""Budget-driven hunger system for the desktop maid (脚本台词 §二).

饿 = 预算快耗尽；断 = 连不上（降级台词另走 §15 容错链路），两套状态不混。
台词全部脚本化，不走 API——「为了宣布自己没饭吃反而又吃掉一口饭」是荒诞的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
import time

HUNGER_STAGE_NORMAL = "normal"
HUNGER_STAGE_PECKISH = "peckish"
HUNGER_STAGE_HUNGRY = "hungry"
HUNGER_STAGE_STARVING = "starving"

HUNGER_STAGE_ORDER = {
    HUNGER_STAGE_NORMAL: 0,
    HUNGER_STAGE_PECKISH: 1,
    HUNGER_STAGE_HUNGRY: 2,
    HUNGER_STAGE_STARVING: 3,
}

PECKISH_RATIO = 0.80
HUNGRY_RATIO = 0.95
STARVING_RATIO = 0.999

_SCOPE_FIELDS = (
    ("day", "daily_limit_usd", "daily_used_usd"),
    ("week", "weekly_limit_usd", "weekly_used_usd"),
)


@dataclass(frozen=True)
class HungerState:
    stage: str = HUNGER_STAGE_NORMAL
    ratio: float | None = None
    scope: str = ""
    blocked: bool = False
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class HungerAnnouncement:
    kind: str  # "stage" (越过阈值) / "full" (回血报喜)
    stage: str
    line: str


def _coerce_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_hunger(
    snapshot: dict[str, object],
    *,
    now: float | None = None,
) -> HungerState:
    """Map a budget guard snapshot to a hunger stage.

    没设任何预算上限时饥饿系统不参与（ratio=None, normal）；
    blocked 时无论比例多少都按断粮处理——她确实跑不动了。
    """
    updated_at = now or time.time()
    normalized = dict(snapshot or {})
    worst_ratio: float | None = None
    worst_scope = ""
    for scope, limit_key, used_key in _SCOPE_FIELDS:
        limit = _coerce_float(normalized.get(limit_key))
        if limit is None or limit <= 0:
            continue
        used = _coerce_float(normalized.get(used_key)) or 0.0
        ratio = max(0.0, used / limit)
        if worst_ratio is None or ratio > worst_ratio:
            worst_ratio = ratio
            worst_scope = scope

    blocked = bool(normalized.get("blocked"))
    if blocked:
        scope = str(normalized.get("blocked_scope") or "") or worst_scope
        return HungerState(
            stage=HUNGER_STAGE_STARVING,
            ratio=worst_ratio,
            scope=scope,
            blocked=True,
            updated_at=updated_at,
        )

    if worst_ratio is None:
        return HungerState(updated_at=updated_at)

    if worst_ratio >= STARVING_RATIO:
        stage = HUNGER_STAGE_STARVING
    elif worst_ratio >= HUNGRY_RATIO:
        stage = HUNGER_STAGE_HUNGRY
    elif worst_ratio >= PECKISH_RATIO:
        stage = HUNGER_STAGE_PECKISH
    else:
        stage = HUNGER_STAGE_NORMAL

    return HungerState(
        stage=stage,
        ratio=worst_ratio,
        scope=worst_scope,
        updated_at=updated_at,
    )


def pick_hunger_line(
    lines: list[str],
    *,
    last_line: str = "",
    rng: random.Random | None = None,
) -> str:
    """Pick a random line, avoiding an immediate repeat of the previous one."""
    pool = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
    if not pool:
        return ""
    candidates = [line for line in pool if line != last_line] or pool
    chooser = rng or random
    return chooser.choice(candidates)


class HungerAnnouncer:
    """Decide which scripted hunger line (if any) a stage change deserves.

    只在阈值「向上越过」时播报一次；回到 normal（额度回血）时报喜一次。
    初始档位从当前状态取，所以重启不会把旧档位再播一遍。
    """

    def __init__(
        self,
        stage_lines: dict[str, list[str]],
        full_lines: list[str],
        *,
        initial_stage: str = HUNGER_STAGE_NORMAL,
        rng: random.Random | None = None,
    ):
        self._stage_lines = {key: list(value or []) for key, value in (stage_lines or {}).items()}
        self._full_lines = list(full_lines or [])
        self._last_stage = (
            initial_stage if initial_stage in HUNGER_STAGE_ORDER else HUNGER_STAGE_NORMAL
        )
        self._last_lines: dict[str, str] = {}
        self._rng = rng

    @property
    def last_stage(self) -> str:
        return self._last_stage

    def observe(self, state: HungerState) -> HungerAnnouncement | None:
        stage = state.stage if state.stage in HUNGER_STAGE_ORDER else HUNGER_STAGE_NORMAL
        previous = self._last_stage
        self._last_stage = stage
        if stage == previous:
            return None

        if HUNGER_STAGE_ORDER[stage] > HUNGER_STAGE_ORDER[previous]:
            line = pick_hunger_line(
                self._stage_lines.get(stage) or [],
                last_line=self._last_lines.get(stage, ""),
                rng=self._rng,
            )
            if not line:
                return None
            self._last_lines[stage] = line
            return HungerAnnouncement(kind="stage", stage=stage, line=line)

        if stage == HUNGER_STAGE_NORMAL:
            line = pick_hunger_line(
                self._full_lines,
                last_line=self._last_lines.get("full", ""),
                rng=self._rng,
            )
            if not line:
                return None
            self._last_lines["full"] = line
            return HungerAnnouncement(kind="full", stage=stage, line=line)

        # 向下但还没回到 normal（比如周窗回血、日窗还紧）：不播报，立绘自己会变。
        return None
