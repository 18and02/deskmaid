"""Smoke test for the privacy-boundary explainability view."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_api_key import ApiKeyStatus
from maid_app_state import AppStateSnapshot
from maid_chat import ChatTraceEvent
import main as maid_main


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _find_card(cards: list[dict[str, object]], title: str) -> dict[str, object]:
    for card in cards:
        if str(card.get("title") or "") == title:
            return card
    raise AssertionError(f"missing card {title!r}")


def main():
    with tempfile.TemporaryDirectory(prefix="deskmaid-privacy-view-") as tmp_dir:
        root = Path(tmp_dir)
        memory_path = root / "memory.json"
        memory_path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "format": "fernet",
                    "key_source": "keychain",
                    "ciphertext": "demo",
                },
                ensure_ascii=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        recent_events = [
            ChatTraceEvent(
                kind="privacy",
                title="离机前做了脱敏",
                detail=(
                    "这句输入里命中了 API 密钥。\n"
                    "命中数量: 2 处。\n"
                    "处理动作: 脱敏后继续发送给远端模型。\n"
                    "下一步建议: 把真实值换成 [已隐藏]、代号或末四位；改完后可以直接重发这句。"
                ),
                created_at=1_716_919_200.0,
            ),
            ChatTraceEvent(
                kind="privacy",
                title="高敏输入留在本机",
                detail=(
                    "这句输入里命中了密码字段。\n"
                    "命中数量: 1 处。\n"
                    "处理动作: 整段留在本机，不发送给远端模型。\n"
                    "下一步建议: 把真实值换成 [已隐藏]、代号或末四位；如果必须保留原文，请改走本机处理。"
                ),
                created_at=1_716_919_260.0,
            ),
        ]
        view = maid_main._build_privacy_boundary_view(
            app_snapshot=AppStateSnapshot(
                onboarding_seen=True,
                setup_version_seen=4,
                owner_name="主人",
                budget_mode="normal",
                data_boundary_acknowledged=True,
                auto_hide_on_sensitive_scene=False,
            ),
            api_status=ApiKeyStatus(
                configured=True,
                source="file",
                summary="当前已在本机私有文件里保存 Claude API key。",
            ),
            api_key_path=root / "anthropic_api_key",
            app_state_path=root / "app_state.json",
            memory_state_path=memory_path,
            memory_item_count=3,
            recent_events=recent_events,
        )
        view_en = maid_main._build_privacy_boundary_view(
            app_snapshot=AppStateSnapshot(
                onboarding_seen=True,
                setup_version_seen=4,
                owner_name="主人",
                budget_mode="normal",
                data_boundary_acknowledged=True,
                auto_hide_on_sensitive_scene=False,
            ),
            api_status=ApiKeyStatus(
                configured=True,
                source="file",
                summary="当前已在本机私有文件里保存 Claude API key。",
            ),
            api_key_path=root / "anthropic_api_key",
            app_state_path=root / "app_state.json",
            memory_state_path=memory_path,
            memory_item_count=3,
            recent_events=recent_events,
            language="en-US",
        )

        cards = [dict(item) for item in (view.get("cards") or []) if isinstance(item, dict)]
        cards_en = [
            dict(item)
            for item in (view_en.get("cards") or [])
            if isinstance(item, dict)
        ]
        _assert(len(cards) == 5, f"expected 5 privacy cards, got {len(cards)}")
        _assert(
            "高敏输入留在本机" in str(view.get("status_text") or ""),
            f"unexpected status text: {view.get('status_text')!r}",
        )
        _assert(
            "Latest privacy action:" in str(view_en.get("status_text") or ""),
            f"unexpected english privacy status: {view_en.get('status_text')!r}",
        )
        _assert(
            _find_card(cards_en, "Local Storage"),
            "expected english privacy card title",
        )

        local_card = _find_card(cards, "本地保存")
        local_detail = str(local_card.get("detail") or "")
        _assert(
            "系统钥匙串" in local_detail,
            f"expected keychain wording in local card: {local_detail!r}",
        )
        _assert(
            "memory.json" in local_detail and "app_state.json" in local_detail,
            f"expected local paths in local card: {local_detail!r}",
        )

        recent_card = _find_card(cards, "最近一次边界动作")
        _assert(
            "高敏输入留在本机" in str(recent_card.get("summary") or ""),
            f"unexpected recent summary: {recent_card!r}",
        )
        recent_detail = str(recent_card.get("detail") or "")
        _assert(
            "离机前做了脱敏" in recent_detail,
            f"expected older privacy trace in detail: {recent_detail!r}",
        )
        _assert(
            "下一步建议" in recent_detail,
            f"expected next-step advice in recent detail: {recent_detail!r}",
        )
        _assert(
            "下一步建议" in str(view.get("meta_text") or ""),
            f"expected next-step advice in meta text: {view.get('meta_text')!r}",
        )

        pending_view = maid_main._build_privacy_boundary_view(
            app_snapshot=AppStateSnapshot(
                data_boundary_acknowledged=False,
                auto_hide_on_sensitive_scene=True,
            ),
            api_status=ApiKeyStatus(configured=False, source="", summary="还没有配置 Claude API key。现在只能开壳，聊不了天。"),
            api_key_path=root / "anthropic_api_key",
            app_state_path=root / "app_state.json",
            memory_state_path=root / "memory-empty.json",
            memory_item_count=0,
            recent_events=[],
        )
        pending_cards = [
            dict(item)
            for item in (pending_view.get("cards") or [])
            if isinstance(item, dict)
        ]
        pending_local_card = _find_card(pending_cards, "本地保存")
        _assert(
            str(pending_local_card.get("badge") or "") == "待确认",
            f"expected pending boundary badge, got {pending_local_card!r}",
        )
        pending_recent_card = _find_card(pending_cards, "最近一次边界动作")
        _assert(
            "还没有命中过隐私边界" in str(pending_recent_card.get("summary") or ""),
            f"unexpected pending recent card: {pending_recent_card!r}",
        )

    print("ok")


if __name__ == "__main__":
    main()
