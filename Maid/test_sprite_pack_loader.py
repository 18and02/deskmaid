"""Smoke/regression coverage for manifest-driven sprite packs."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_sprite_packs import (
    DEFAULT_SPRITE_PACK_ID,
    USER_SPRITE_PACKS_DIR_ENV_VAR,
    USER_SPRITE_PACK_TEMPLATE_ID,
    available_sprite_pack_ids,
    describe_available_sprite_packs,
    diagnose_sprite_pack,
    ensure_user_sprite_pack_template,
    resolve_sprite_pack,
)


ASSETS = Path(__file__).resolve().parent / "assets"


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _assert_uniform_canvas(bundle):
    for state_key, frames in bundle.states.items():
        _assert(frames, f"{bundle.pack_id} state {state_key!r} has no frames")
        for index, image in enumerate(frames):
            _assert(
                image.width() == bundle.canvas_width,
                f"{bundle.pack_id} {state_key}[{index}] width mismatch: "
                f"{image.width()} != {bundle.canvas_width}",
            )
            _assert(
                image.height() == bundle.canvas_height,
                f"{bundle.pack_id} {state_key}[{index}] height mismatch: "
                f"{image.height()} != {bundle.canvas_height}",
            )


def _assert_visible_frames(bundle):
    for state_key, frames in bundle.states.items():
        for index, image in enumerate(frames):
            visible = False
            for y in range(image.height()):
                for x in range(image.width()):
                    if image.pixelColor(x, y).alpha() > 0:
                        visible = True
                        break
                if visible:
                    break
            _assert(visible, f"{bundle.pack_id} {state_key}[{index}] is fully transparent")


def main():
    pack_ids = available_sprite_pack_ids(ASSETS)
    for expected in ("gemini", "maid", "placeholder"):
        _assert(expected in pack_ids, f"missing sprite pack id {expected!r}: {pack_ids!r}")

    summaries = describe_available_sprite_packs(ASSETS)
    summary_by_id = {summary.pack_id: summary for summary in summaries}
    _assert("gemini" in summary_by_id, f"missing gemini summary: {summary_by_id!r}")
    _assert(
        summary_by_id["maid"].name == "Classic Maid",
        f"unexpected maid summary name: {summary_by_id['maid']!r}",
    )
    _assert(
        "idle" in summary_by_id["placeholder"].available_states,
        f"placeholder summary should expose idle pose: {summary_by_id['placeholder']!r}",
    )

    gemini_bundle = resolve_sprite_pack(assets_dir=ASSETS, sprite_set="gemini", sprite=None)
    expected_states = {
        "idle", "blink", "alert", "excited", "enter", "exit", "sleepy", "peckish", "outing", "held",
    }
    _assert(
        expected_states.issubset(set(gemini_bundle.states)),
        f"gemini bundle missing expected states: {sorted(expected_states - set(gemini_bundle.states))!r}",
    )
    _assert_uniform_canvas(gemini_bundle)
    _assert(gemini_bundle.metadata.author == "Deskmaid", f"unexpected author: {gemini_bundle.metadata!r}")
    _assert(
        gemini_bundle.metadata.preview_pose == "alert",
        f"unexpected preview pose: {gemini_bundle.metadata!r}",
    )
    _assert(
        "default" in gemini_bundle.metadata.tags,
        f"expected default tag in gemini metadata: {gemini_bundle.metadata!r}",
    )
    gemini_diag = diagnose_sprite_pack(gemini_bundle)
    _assert(not gemini_diag.errors, f"gemini diagnostic should have no errors: {gemini_diag.errors!r}")
    _assert("held" in gemini_diag.frame_counts, f"gemini diagnostic should include held: {gemini_diag!r}")

    maid_bundle = resolve_sprite_pack(assets_dir=ASSETS, sprite_set="maid", sprite=None)
    _assert(maid_bundle.pack_id == "maid", f"unexpected maid pack id: {maid_bundle.pack_id!r}")
    _assert(
        maid_bundle.fallback_states.get("blink") == DEFAULT_SPRITE_PACK_ID,
        f"maid pack should fall back blink from {DEFAULT_SPRITE_PACK_ID}: {maid_bundle.fallback_states!r}",
    )
    _assert(
        maid_bundle.fallback_states.get("outing") == DEFAULT_SPRITE_PACK_ID,
        f"maid pack should fall back outing from {DEFAULT_SPRITE_PACK_ID}: {maid_bundle.fallback_states!r}",
    )
    _assert(
        maid_bundle.fallback_states.get("held") == DEFAULT_SPRITE_PACK_ID,
        f"maid pack should fall back held from {DEFAULT_SPRITE_PACK_ID}: {maid_bundle.fallback_states!r}",
    )
    _assert_uniform_canvas(maid_bundle)
    _assert(
        maid_bundle.metadata.description,
        f"maid bundle should expose manifest description: {maid_bundle.metadata!r}",
    )

    placeholder_bundle = resolve_sprite_pack(assets_dir=ASSETS, sprite_set="placeholder", sprite=None)
    _assert(
        "blink" not in placeholder_bundle.fallback_states,
        f"placeholder blink should come from its own manifest: {placeholder_bundle.fallback_states!r}",
    )
    _assert(
        placeholder_bundle.fallback_states.get("alert") == DEFAULT_SPRITE_PACK_ID,
        f"placeholder alert should fall back from {DEFAULT_SPRITE_PACK_ID}",
    )
    _assert_uniform_canvas(placeholder_bundle)
    _assert(
        placeholder_bundle.metadata.preview_pose == "blink",
        f"placeholder preview pose should come from manifest: {placeholder_bundle.metadata!r}",
    )

    petdex_bundle = resolve_sprite_pack(
        assets_dir=ASSETS,
        sprite_set="petdex-maid-codex",
        sprite=None,
    )
    _assert(
        petdex_bundle.pack_id == "petdex-maid-codex",
        f"unexpected petdex pack id: {petdex_bundle.pack_id!r}",
    )
    _assert_uniform_canvas(petdex_bundle)
    _assert_visible_frames(petdex_bundle)
    _assert("held" in petdex_bundle.states, "petdex bundle should provide held pose")
    _assert_visible_frames(
        type("PetdexHeldOnly", (), {
            "pack_id": petdex_bundle.pack_id,
            "states": {"held": petdex_bundle.states["held"]},
        })()
    )
    petdex_diag = diagnose_sprite_pack(petdex_bundle)
    _assert(not petdex_diag.errors, f"petdex diagnostic should have no errors: {petdex_diag.errors!r}")
    _assert(
        len(petdex_bundle.states["excited"]) == 4,
        f"petdex excited should skip transparent generated frames: {len(petdex_bundle.states['excited'])}",
    )
    _assert(
        len(petdex_bundle.states["alert"]) == 6,
        f"petdex alert should use review expression frames: {len(petdex_bundle.states['alert'])}",
    )

    legacy_bundle = resolve_sprite_pack(assets_dir=ASSETS, sprite_set=None, sprite="placeholder")
    _assert(
        legacy_bundle.pack_id == "legacy:placeholder",
        f"unexpected legacy bundle id: {legacy_bundle.pack_id!r}",
    )
    _assert("idle" in legacy_bundle.states, "legacy bundle should provide idle")
    _assert_uniform_canvas(legacy_bundle)
    _assert(
        "legacy" in legacy_bundle.metadata.tags,
        f"legacy bundle should expose legacy tag: {legacy_bundle.metadata!r}",
    )

    previous_user_pack_dir = os.environ.get(USER_SPRITE_PACKS_DIR_ENV_VAR)
    with tempfile.TemporaryDirectory(prefix="deskmaid-user-packs-") as tmp_dir:
        os.environ[USER_SPRITE_PACKS_DIR_ENV_VAR] = tmp_dir
        root = ensure_user_sprite_pack_template(ASSETS)
        _assert(
            (root / USER_SPRITE_PACK_TEMPLATE_ID / "manifest.json").is_file(),
            f"user sprite-pack template manifest was not created under {root}",
        )
        _assert(
            USER_SPRITE_PACK_TEMPLATE_ID in available_sprite_pack_ids(ASSETS),
            "user sprite-pack template id should be discoverable",
        )
        user_bundle = resolve_sprite_pack(
            assets_dir=ASSETS,
            sprite_set=USER_SPRITE_PACK_TEMPLATE_ID,
            sprite=None,
        )
        _assert("held" in user_bundle.states, "user sprite-pack template should include held")
        user_diag = diagnose_sprite_pack(user_bundle)
        _assert(not user_diag.errors, f"user template diagnostic should have no errors: {user_diag.errors!r}")
    if previous_user_pack_dir is None:
        os.environ.pop(USER_SPRITE_PACKS_DIR_ENV_VAR, None)
    else:
        os.environ[USER_SPRITE_PACKS_DIR_ENV_VAR] = previous_user_pack_dir

    print("ok")


if __name__ == "__main__":
    main()
