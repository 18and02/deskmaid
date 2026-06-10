"""Regression coverage for outing catalog and state persistence."""

from __future__ import annotations

from pathlib import Path
import random
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_outing import (
    OutingStateStore,
    format_outing_return_message,
    load_outing_catalog,
    load_outing_snapshot,
    pick_outing_result,
)
from main import _build_outing_collection_view


ASSETS = Path(__file__).resolve().parent / "assets"


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    catalog = load_outing_catalog(ASSETS)
    _assert(catalog.events, "expected non-empty outing events catalog")
    _assert(catalog.collectables, "expected non-empty outing collectables catalog")
    _assert(len(catalog.events) >= 20, f"outing event catalog should be expanded: {len(catalog.events)}")
    _assert(
        len(catalog.collectables) >= 12,
        f"outing collectable catalog should be expanded: {len(catalog.collectables)}",
    )

    event_result = pick_outing_result(catalog, preferred_kind="event", rng=random.Random(3))
    _assert(event_result.kind == "event", f"expected event track, got {event_result!r}")

    collectable_result = pick_outing_result(
        catalog,
        preferred_kind="collectable",
        rng=random.Random(7),
    )
    _assert(
        collectable_result.kind == "collectable",
        f"expected collectable track, got {collectable_result!r}",
    )

    with tempfile.TemporaryDirectory(prefix="deskmaid-outing-flow-") as tmp_dir:
        state_path = Path(tmp_dir) / "outing_state.json"
        store = OutingStateStore(state_path)

        departed = store.record_departure()
        _assert(departed.outings_started == 1, f"unexpected departure snapshot: {departed!r}")

        returned, collectable_count = store.record_return(collectable_result, duration_s=12.5)
        _assert(returned.outings_completed == 1, f"unexpected return snapshot: {returned!r}")
        _assert(returned.total_outing_seconds >= 12.5, f"duration not recorded: {returned!r}")
        _assert(collectable_count == 1, f"collectable count should start at 1: {collectable_count}")

        persisted = load_outing_snapshot(state_path)
        _assert(persisted.outings_started == 1, f"persisted outings_started mismatch: {persisted!r}")
        _assert(
            persisted.collectable_counts.get(collectable_result.key) == 1,
            f"persisted collectable count mismatch: {persisted!r}",
        )
        view = _build_outing_collection_view(persisted, catalog, language="zh-CN")
        _assert("出门收藏" in str(view.get("status_text")), f"unexpected collection status: {view!r}")
        card_titles = [str(card.get("title") or "") for card in view.get("cards") or []]
        _assert("出门记录" in card_titles, f"collection view should include outing log card: {card_titles!r}")
        _assert("收藏进度" in card_titles, f"collection view should include progress card: {card_titles!r}")
        _assert(
            collectable_result.title in card_titles,
            f"collection view should include returned collectable: {card_titles!r}",
        )

    message = format_outing_return_message(
        collectable_result,
        collectable_count=collectable_count,
        extra_note="已经回来了。",
    )
    _assert(message.startswith("出门回执 · 收藏品"), f"message missing receipt header: {message!r}")
    _assert(f"收获: {collectable_result.title}" in message, f"message missing item title: {message!r}")
    _assert("累计: 1" in message, f"message missing count: {message!r}")
    _assert("附记: 已经回来了。" in message, f"message missing extra note: {message!r}")

    event_message = format_outing_return_message(event_result)
    _assert(event_message.startswith("出门回执 · 见闻"), f"event message missing header: {event_message!r}")
    _assert(f"见闻: {event_result.summary}" in event_message, f"event message missing summary: {event_message!r}")

    print("ok")


if __name__ == "__main__":
    main()
