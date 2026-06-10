"""Data-driven outing events and collectables for Deskmaid."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import random
import threading
import time

from maid_paths import default_state_path


OUTING_STATE_ENV_VAR = "MAID_OUTING_STATE_PATH"
DEFAULT_OUTING_STATE_PATH = default_state_path(".maid_outing.json")
DEFAULT_OUTING_DURATION_S = 4 * 60
DEMO_OUTING_DURATION_S = 18
COLLECTABLE_TRACK_CHANCE = 0.34

RARITY_LABELS = {
    "common": "普通",
    "uncommon": "少见",
    "rare": "稀有",
    "epic": "珍藏",
}
OUTING_KIND_LABELS = {
    "event": "见闻",
    "collectable": "收藏品",
}

_RARITY_WEIGHTS = {
    "common": 1.0,
    "uncommon": 0.65,
    "rare": 0.35,
    "epic": 0.16,
}

_DEPARTURE_LINES = {
    "manual": "我先出去转一圈。你趁我不在也别乱加需求。",
    "auto_dnd": "现在这场合不适合我晃来晃去。我先出去避一会儿。",
    "budget": "额度有点紧。我先出去晃一圈，省得把今天的预算啃穿。",
    "default": "我先出去转一圈，很快回来。",
}


@dataclass(frozen=True)
class OutingEvent:
    key: str
    text: str
    weight: float = 1.0


@dataclass(frozen=True)
class OutingCollectable:
    key: str
    name: str
    rarity: str = "common"
    description: str = ""
    weight: float = 1.0


@dataclass(frozen=True)
class OutingResult:
    kind: str
    key: str
    title: str
    summary: str
    detail: str = ""
    rarity: str = ""


@dataclass(frozen=True)
class OutingCatalog:
    events: tuple[OutingEvent, ...] = ()
    collectables: tuple[OutingCollectable, ...] = ()


@dataclass(frozen=True)
class OutingSnapshot:
    outings_started: int = 0
    outings_completed: int = 0
    total_outing_seconds: float = 0.0
    collectable_counts: dict[str, int] = field(default_factory=dict)
    last_result_kind: str = ""
    last_result_key: str = ""
    updated_at: float = 0.0

    @property
    def total_collectable_items(self) -> int:
        return sum(max(0, int(value or 0)) for value in self.collectable_counts.values())

    @property
    def total_collectable_kinds(self) -> int:
        return sum(1 for value in self.collectable_counts.values() if int(value or 0) > 0)


def departure_line(origin: str) -> str:
    normalized = str(origin or "").strip().lower()
    return _DEPARTURE_LINES.get(normalized, _DEPARTURE_LINES["default"])


def outing_duration_seconds(*, demo_short: bool = False) -> int:
    return DEMO_OUTING_DURATION_S if demo_short else DEFAULT_OUTING_DURATION_S


def format_outing_return_message(
    result: OutingResult,
    *,
    collectable_count: int = 0,
    extra_note: str = "",
) -> str:
    kind = str(result.kind or "").strip().lower()
    kind_label = OUTING_KIND_LABELS.get(kind, "见闻")
    lines = [f"出门回执 · {kind_label}"]
    title = str(result.title or "").strip()

    if kind == "collectable":
        if title:
            lines.append(f"收获: {title}")
        rarity_label = RARITY_LABELS.get(_normalize_rarity(result.rarity), "收藏")
        lines.append(f"稀有度: {rarity_label}")
        if collectable_count > 0:
            lines.append(f"累计: {collectable_count}")
        summary = str(result.summary or "").strip()
        if summary:
            lines.append(f"摘要: {summary}")
    else:
        if title and title != "见闻":
            lines.append(f"主题: {title}")
        summary = str(result.summary or "").strip()
        if summary:
            lines.append(f"见闻: {summary}")

    detail = str(result.detail or "").strip()
    if detail:
        lines.append(f"备注: {detail}")
    note = str(extra_note or "").strip()
    if note:
        lines.append(f"附记: {note}")
    return "\n".join(line for line in lines if line)


def load_outing_catalog(assets_dir: Path) -> OutingCatalog:
    root = Path(assets_dir) / "outing"
    return OutingCatalog(
        events=tuple(_load_events(root / "events.json")),
        collectables=tuple(_load_collectables(root / "collectables.json")),
    )


def pick_outing_result(
    catalog: OutingCatalog,
    *,
    rng: random.Random | None = None,
    preferred_kind: str | None = None,
) -> OutingResult:
    chooser = rng or random.Random()
    track = str(preferred_kind or "").strip().lower()
    if track not in {"event", "collectable"}:
        if catalog.collectables and chooser.random() < COLLECTABLE_TRACK_CHANCE:
            track = "collectable"
        else:
            track = "event"

    if track == "collectable" and catalog.collectables:
        item = _weighted_choice_collectable(catalog.collectables, chooser)
        rarity = _normalize_rarity(item.rarity)
        rarity_label = RARITY_LABELS.get(rarity, "收藏")
        summary = f"她顺手带回了个{rarity_label}收藏品。"
        detail = item.description or "看起来像是她路上顺手捡回来的。"
        return OutingResult(
            kind="collectable",
            key=item.key,
            title=item.name,
            summary=summary,
            detail=detail,
            rarity=rarity,
        )

    if catalog.events:
        item = _weighted_choice_event(catalog.events, chooser)
        return OutingResult(
            kind="event",
            key=item.key,
            title="见闻",
            summary=item.text,
            detail="这次没带东西，纯带回来一句嘴碎。",
        )

    raise RuntimeError("outing catalog is empty")


def _weighted_choice_event(
    items: tuple[OutingEvent, ...],
    rng: random.Random,
) -> OutingEvent:
    weights = [max(0.01, float(item.weight or 0.0)) for item in items]
    return rng.choices(list(items), weights=weights, k=1)[0]


def _weighted_choice_collectable(
    items: tuple[OutingCollectable, ...],
    rng: random.Random,
) -> OutingCollectable:
    weights: list[float] = []
    for item in items:
        rarity_weight = _RARITY_WEIGHTS.get(_normalize_rarity(item.rarity), 1.0)
        weights.append(max(0.01, float(item.weight or 0.0) * rarity_weight))
    return rng.choices(list(items), weights=weights, k=1)[0]


def _load_events(path: Path) -> list[OutingEvent]:
    payload = _load_json_list(path)
    rows: list[OutingEvent] = []
    for raw in payload:
        key = str(raw.get("id") or "").strip()
        text = str(raw.get("text") or "").strip()
        if not key or not text:
            continue
        try:
            weight = max(0.01, float(raw.get("weight") or 1.0))
        except Exception:
            weight = 1.0
        rows.append(OutingEvent(key=key, text=text, weight=weight))
    return rows


def _load_collectables(path: Path) -> list[OutingCollectable]:
    payload = _load_json_list(path)
    rows: list[OutingCollectable] = []
    for raw in payload:
        key = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not key or not name:
            continue
        try:
            weight = max(0.01, float(raw.get("weight") or 1.0))
        except Exception:
            weight = 1.0
        rows.append(
            OutingCollectable(
                key=key,
                name=name,
                rarity=_normalize_rarity(raw.get("rarity")),
                description=str(raw.get("description") or "").strip(),
                weight=weight,
            )
        )
    return rows


def _load_json_list(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as exc:
        print(f"[outing] failed to read {path}: {exc}")
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _normalize_rarity(value: object) -> str:
    rarity = str(value or "").strip().lower() or "common"
    if rarity not in RARITY_LABELS:
        return "common"
    return rarity


def _outing_state_path() -> Path:
    override = str(os.environ.get(OUTING_STATE_ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_OUTING_STATE_PATH


def load_outing_snapshot(path: Path | None = None) -> OutingSnapshot:
    return _load_snapshot(path or _outing_state_path())


def _load_snapshot(path: Path) -> OutingSnapshot:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return OutingSnapshot()
    except Exception as exc:
        print(f"[outing] failed to read {path}: {exc}")
        return OutingSnapshot()

    if not isinstance(payload, dict):
        return OutingSnapshot()
    raw_counts = payload.get("collectable_counts")
    counts: dict[str, int] = {}
    if isinstance(raw_counts, dict):
        for key, value in raw_counts.items():
            normalized_key = str(key or "").strip()
            if not normalized_key:
                continue
            try:
                count = max(0, int(value or 0))
            except Exception:
                count = 0
            if count > 0:
                counts[normalized_key] = count

    return OutingSnapshot(
        outings_started=max(0, int(payload.get("outings_started") or 0)),
        outings_completed=max(0, int(payload.get("outings_completed") or 0)),
        total_outing_seconds=max(0.0, float(payload.get("total_outing_seconds") or 0.0)),
        collectable_counts=counts,
        last_result_kind=str(payload.get("last_result_kind") or "").strip(),
        last_result_key=str(payload.get("last_result_key") or "").strip(),
        updated_at=max(0.0, float(payload.get("updated_at") or 0.0)),
    )


def _serialize(snapshot: OutingSnapshot) -> str:
    payload = {
        "version": 1,
        "outings_started": snapshot.outings_started,
        "outings_completed": snapshot.outings_completed,
        "total_outing_seconds": snapshot.total_outing_seconds,
        "collectable_counts": dict(snapshot.collectable_counts),
        "last_result_kind": snapshot.last_result_kind,
        "last_result_key": snapshot.last_result_key,
        "updated_at": snapshot.updated_at,
    }
    return json.dumps(payload, ensure_ascii=True, indent=2) + "\n"


class OutingStateStore:
    def __init__(self, path: Path | None = None):
        self._path = path or _outing_state_path()
        self._lock = threading.Lock()
        self._snapshot = _load_snapshot(self._path)

    def snapshot(self) -> OutingSnapshot:
        with self._lock:
            return self._snapshot

    def record_departure(self) -> OutingSnapshot:
        with self._lock:
            snapshot = self._snapshot
            self._snapshot = OutingSnapshot(
                outings_started=snapshot.outings_started + 1,
                outings_completed=snapshot.outings_completed,
                total_outing_seconds=snapshot.total_outing_seconds,
                collectable_counts=dict(snapshot.collectable_counts),
                last_result_kind=snapshot.last_result_kind,
                last_result_key=snapshot.last_result_key,
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot

    def record_return(
        self,
        result: OutingResult,
        *,
        duration_s: float = 0.0,
    ) -> tuple[OutingSnapshot, int]:
        with self._lock:
            snapshot = self._snapshot
            counts = dict(snapshot.collectable_counts)
            collectable_count = 0
            if result.kind == "collectable" and result.key:
                collectable_count = counts.get(result.key, 0) + 1
                counts[result.key] = collectable_count
            self._snapshot = OutingSnapshot(
                outings_started=snapshot.outings_started,
                outings_completed=snapshot.outings_completed + 1,
                total_outing_seconds=snapshot.total_outing_seconds + max(0.0, float(duration_s)),
                collectable_counts=counts,
                last_result_kind=result.kind,
                last_result_key=result.key,
                updated_at=time.time(),
            )
            self._save_locked()
            return self._snapshot, collectable_count

    def _save_locked(self):
        tmp_path = self._path.with_name(f"{self._path.name}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(_serialize(self._snapshot), encoding="utf-8")
            tmp_path.replace(self._path)
        except OSError as exc:
            print(f"[outing] failed to write {self._path}: {exc}")
            try:
                tmp_path.unlink()
            except OSError:
                pass
