"""Local tests for the maid long-term memory store.

Usage:
    python3 Maid/test_long_term_memory_store.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_memory import (
    LongTermMemoryStore,
    MemoryItem,
    extract_memory_candidates,
    memory_item_metadata,
)


def _texts(store: LongTermMemoryStore) -> list[str]:
    return [item.text for item in store.entries()]


def main():
    candidates = extract_memory_candidates(
        "请记住这件事：我最喜欢的水果是梨。只回复记住了。"
    )
    if not any("主人最喜欢的水果是梨" in candidate.text for candidate in candidates):
        print(f"[error] failed to extract favorite fruit memory: {candidates!r}", file=sys.stderr)
        sys.exit(1)
    question_candidates = extract_memory_candidates("我最喜欢的水果是什么？")
    if question_candidates:
        print(
            f"[error] question prompt should not create memory candidates: {question_candidates!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="deskmaid-memory-") as tmp_dir:
        path = Path(tmp_dir) / "memory.json"
        store = LongTermMemoryStore(path)

        saved_outcomes = store.remember_from_turn_outcomes(
            "请记住这件事：我最喜欢的水果是梨。只回复记住了。"
        )
        saved = [outcome.item for outcome in saved_outcomes]
        if len(saved_outcomes) != 1:
            print(f"[error] expected 1 saved outcome, got {saved_outcomes!r}", file=sys.stderr)
            sys.exit(1)
        if saved_outcomes[0].action != "created":
            print(f"[error] first memory should be created: {saved_outcomes!r}", file=sys.stderr)
            sys.exit(1)
        first_meta = memory_item_metadata(saved_outcomes[0].item)
        if first_meta.get("reason_key") != "explicit_instruction":
            print(f"[error] unexpected remember reason metadata: {first_meta!r}", file=sys.stderr)
            sys.exit(1)

        recalled = store.recall("我最喜欢的水果是什么？")
        if not any("水果是梨" in item.text for item in recalled):
            print(f"[error] failed to recall fruit memory: {recalled!r}", file=sys.stderr)
            sys.exit(1)

        replace_outcomes = store.remember_from_turn_outcomes("请记住这件事：我最喜欢的水果是苹果。")
        texts = _texts(store)
        if any("水果是梨" in text for text in texts):
            print(f"[error] old fruit memory was not replaced: {texts!r}", file=sys.stderr)
            sys.exit(1)
        if not any("水果是苹果" in text for text in texts):
            print(f"[error] updated fruit memory missing: {texts!r}", file=sys.stderr)
            sys.exit(1)
        if not replace_outcomes or replace_outcomes[0].action != "updated":
            print(f"[error] expected updated outcome for fruit replacement: {replace_outcomes!r}", file=sys.stderr)
            sys.exit(1)
        if not any("水果是梨" in item.text for item in replace_outcomes[0].replaced):
            print(f"[error] fruit replacement should mention old value: {replace_outcomes!r}", file=sys.stderr)
            sys.exit(1)

        store.remember_from_turn("请记住这句原样内容：长期记忆口令是 deskmaid-memory-token-4729。")
        store.remember_from_turn("以后叫我主人。")
        store.remember_from_turn("我喜欢咖啡。")
        store.remember_from_turn("我不喜欢咖啡。")
        conflict_texts = _texts(store)
        if any(text == "主人喜欢咖啡。" for text in conflict_texts):
            print(f"[error] like/dislike conflict was not resolved: {conflict_texts!r}", file=sys.stderr)
            sys.exit(1)
        if not any(text == "主人不喜欢咖啡。" for text in conflict_texts):
            print(f"[error] dislike memory missing after conflict update: {conflict_texts!r}", file=sys.stderr)
            sys.exit(1)

        reloaded = LongTermMemoryStore(path)
        reloaded_texts = _texts(reloaded)
        if not any("deskmaid-memory-token-4729" in text for text in reloaded_texts):
            print(f"[error] token memory did not persist: {reloaded_texts!r}", file=sys.stderr)
            sys.exit(1)
        if not any("叫作主人" in text for text in reloaded_texts):
            print(f"[error] preferred-name memory missing: {reloaded_texts!r}", file=sys.stderr)
            sys.exit(1)
        raw_storage = path.read_text(encoding="utf-8")
        if "deskmaid-memory-token-4729" in raw_storage or "水果是苹果" in raw_storage:
            print(
                f"[error] plaintext memory leaked into encrypted storage: {raw_storage!r}",
                file=sys.stderr,
            )
            sys.exit(1)
        if '"format": "fernet"' not in raw_storage or "ciphertext" not in raw_storage:
            print(f"[error] encrypted storage envelope missing: {raw_storage!r}", file=sys.stderr)
            sys.exit(1)
        key_path = path.with_name(f"{path.name}.key")
        if not key_path.exists():
            print(f"[error] expected sidecar key file to exist: {key_path}", file=sys.stderr)
            sys.exit(1)

        token_recall = reloaded.recall("你长期记住的口令是什么？")
        if not any("deskmaid-memory-token-4729" in item.text for item in token_recall):
            print(f"[error] failed to recall token memory: {token_recall!r}", file=sys.stderr)
            sys.exit(1)

        created = reloaded.create_with_outcome("主人偏好我用中文回复。")
        if created is None or "中文" not in created.item.text:
            print(f"[error] failed to create manual memory item: {created!r}", file=sys.stderr)
            sys.exit(1)
        created_meta = memory_item_metadata(created.item)
        if created_meta.get("reason_key") != "manual":
            print(f"[error] manual create should carry manual reason: {created_meta!r}", file=sys.stderr)
            sys.exit(1)

        fruit_item = next((item for item in reloaded.entries() if "水果" in item.text), None)
        if fruit_item is None:
            print("[error] fruit memory entry missing before update", file=sys.stderr)
            sys.exit(1)
        updated = reloaded.update_text_with_outcome(fruit_item.key, "主人最喜欢的水果是葡萄。")
        if updated is None or "葡萄" not in updated.item.text:
            print(f"[error] failed to update memory item: {updated!r}", file=sys.stderr)
            sys.exit(1)
        if updated.action != "updated" or not any("水果是苹果" in item.text for item in updated.replaced):
            print(f"[error] updated fruit memory should expose replaced value: {updated!r}", file=sys.stderr)
            sys.exit(1)
        updated_recall = reloaded.recall("我最喜欢的水果是什么？")
        if not any("葡萄" in item.text for item in updated_recall):
            print(f"[error] updated memory did not recall correctly: {updated_recall!r}", file=sys.stderr)
            sys.exit(1)

        forget_recent = reloaded.forget_from_prompt("忘掉刚才那件事。")
        if not forget_recent.handled or not forget_recent.removed:
            print(f"[error] failed to forget recent memory: {forget_recent!r}", file=sys.stderr)
            sys.exit(1)
        if forget_recent.mode != "recent" or forget_recent.target != "刚才那条":
            print(f"[error] recent forget should record mode/target: {forget_recent!r}", file=sys.stderr)
            sys.exit(1)

        fruit_restore = reloaded.create("主人最喜欢的水果是葡萄。")
        if fruit_restore is None:
            print("[error] failed to restore fruit memory for forget test", file=sys.stderr)
            sys.exit(1)
        forget_fruit = reloaded.forget_from_prompt("把我最喜欢的水果忘掉。")
        if not forget_fruit.handled or not forget_fruit.removed:
            print(f"[error] failed to forget favorite memory: {forget_fruit!r}", file=sys.stderr)
            sys.exit(1)
        if forget_fruit.mode != "key" or forget_fruit.target != "水果":
            print(f"[error] favorite forget should record key target: {forget_fruit!r}", file=sys.stderr)
            sys.exit(1)
        if any("最喜欢的水果" in item.text for item in reloaded.entries()):
            print("[error] favorite memory still present after forget", file=sys.stderr)
            sys.exit(1)

        reloaded.create("测试项目是 Deskmaid。")
        reloaded.create("测试模式是 轻量。")
        forget_ambiguous = reloaded.forget_from_prompt("忘掉关于测试。")
        if (
            not forget_ambiguous.handled
            or forget_ambiguous.removed
            or len(forget_ambiguous.ambiguous_matches) < 2
            or forget_ambiguous.mode != "search"
        ):
            print(f"[error] ambiguous forget should stay traceable: {forget_ambiguous!r}", file=sys.stderr)
            sys.exit(1)
        phase_prompt = reloaded.forget_from_prompt("这是一次 Calendar 写入链路集成测试（删除阶段）。")
        if phase_prompt.handled:
            print(
                f"[error] delete-phase prompt should not trigger local forget flow: {phase_prompt!r}",
                file=sys.stderr,
            )
            sys.exit(1)

        preferred_name_item = next((item for item in reloaded.entries() if "叫作主人" in item.text), None)
        if preferred_name_item is None:
            print("[error] preferred-name memory entry missing before delete", file=sys.stderr)
            sys.exit(1)
        removed = reloaded.delete(preferred_name_item.key)
        if removed is None or "叫作主人" not in removed.text:
            print(f"[error] failed to delete memory item: {removed!r}", file=sys.stderr)
            sys.exit(1)
        if any(item.key == preferred_name_item.key for item in reloaded.entries()):
            print("[error] deleted memory item still present", file=sys.stderr)
            sys.exit(1)

        expiry_store = LongTermMemoryStore(path)
        old_note = MemoryItem(
            key="note:stale",
            text="旧便签会过期。",
            keywords=["旧便签"],
            created_at=time.time() - 3600,
            updated_at=time.time() - 3600,
            expires_at=time.time() - 1,
            last_used_at=None,
            source="manual",
        )
        expiry_store._items.append(old_note)
        if any(item.key == old_note.key for item in expiry_store.entries()):
            print("[error] expired note was not pruned on read", file=sys.stderr)
            sys.exit(1)

        expiry_store._items.append(old_note)
        cleanup_outcome = expiry_store.create_with_outcome("测试环境是本机。")
        if cleanup_outcome is None or cleanup_outcome.pruned_expired_count < 1:
            print(f"[error] create_with_outcome should report expired cleanup: {cleanup_outcome!r}", file=sys.stderr)
            sys.exit(1)

        cleared = reloaded.clear()
        if cleared < 2:
            print(f"[error] expected to clear at least 2 memories, got {cleared}", file=sys.stderr)
            sys.exit(1)
        if reloaded.entries():
            print(f"[error] memory store not empty after clear: {reloaded.entries()!r}", file=sys.stderr)
            sys.exit(1)
        if path.exists():
            print(f"[error] memory file still exists after clear: {path}", file=sys.stderr)
            sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="deskmaid-memory-legacy-") as tmp_dir:
        legacy_path = Path(tmp_dir) / "legacy.json"
        legacy_payload = {
            "version": 1,
            "memories": [
                {
                    "key": "legacy-note",
                    "text": "长期记忆口令是 legacy-secret-991。",
                    "keywords": ["长期记忆", "口令"],
                    "created_at": time.time(),
                    "updated_at": time.time(),
                    "last_used_at": None,
                    "source": "legacy",
                }
            ],
        }
        legacy_path.write_text(
            json.dumps(legacy_payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        migrated = LongTermMemoryStore(legacy_path)
        migrated_texts = _texts(migrated)
        if not any("legacy-secret-991" in text for text in migrated_texts):
            print(f"[error] failed to load legacy plaintext store: {migrated_texts!r}", file=sys.stderr)
            sys.exit(1)
        migrated_raw = legacy_path.read_text(encoding="utf-8")
        if "legacy-secret-991" in migrated_raw:
            print(f"[error] legacy plaintext store was not migrated: {migrated_raw!r}", file=sys.stderr)
            sys.exit(1)
        if '"format": "fernet"' not in migrated_raw:
            print(f"[error] migrated legacy store missing encrypted envelope: {migrated_raw!r}", file=sys.stderr)
            sys.exit(1)

    print("ok")


if __name__ == "__main__":
    main()
