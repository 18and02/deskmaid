"""Manifest-driven sprite-pack loading for Deskmaid."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import shutil

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from maid_paths import default_user_sprite_packs_dir


DEFAULT_SPRITE_PACK_ID = "gemini"
DEFAULT_ANCHOR_X = 0.5
DEFAULT_ANCHOR_Y = 0.92
_PACKS_DIR = "packs"
_IMAGE_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}
USER_SPRITE_PACKS_DIR_ENV_VAR = "MAID_SPRITE_PACKS_DIR"
USER_SPRITE_PACK_TEMPLATE_ID = "my-maid"
STANDARD_SPRITE_STATES = (
    "idle",
    "blink",
    "alert",
    "excited",
    "enter",
    "exit",
    "outing",
    "peckish",
    "sleepy",
    "held",
)

LEGACY_SPRITE_SETS: dict[str, dict[str, str | None]] = {
    "placeholder": {
        "idle": "placeholder.png",
        "blink": "placeholder_blink.png",
        "alert": None,
    },
    "maid": {
        "idle": "maid.png",
        "blink": None,
        "alert": None,
    },
    "gemini": {
        "idle": "maid_idle.png",
        "blink": "maid_idle_blink.png",
        "alert": "maid_reply_sarcastic.png",
        "excited": "maid.png",
        "enter": "maid_enter.png",
        "exit": "maid_exit.png",
        "sleepy": "maid_yawn.png",
        "peckish": "maid_peckish.png",
        "outing": "maid_exit.png",
        "held": "maid.png",
    },
}


class SpritePackError(RuntimeError):
    """Raised when a sprite pack cannot be loaded."""


@dataclass(frozen=True)
class SpritePackMetadata:
    version: int = 1
    author: str = ""
    description: str = ""
    website: str = ""
    license_name: str = ""
    tags: tuple[str, ...] = ()
    default_pose: str = "idle"
    preview_pose: str = "idle"
    display_scale: float = 1.0


@dataclass(frozen=True)
class SpritePackBundle:
    pack_id: str
    name: str
    source: str
    canvas_width: int
    canvas_height: int
    states: dict[str, list[QImage]]
    state_sources: dict[str, list[str]] = field(default_factory=dict)
    fallback_states: dict[str, str] = field(default_factory=dict)
    animations: dict[str, dict[str, object]] = field(default_factory=dict)
    metadata: SpritePackMetadata = field(default_factory=SpritePackMetadata)


@dataclass(frozen=True)
class SpritePackSummary:
    pack_id: str
    name: str
    source: str
    available_states: tuple[str, ...] = ()
    metadata: SpritePackMetadata = field(default_factory=SpritePackMetadata)


@dataclass(frozen=True)
class SpritePackDiagnostic:
    pack_id: str
    ok: bool
    expected_states: tuple[str, ...]
    missing_states: tuple[str, ...]
    fallback_states: dict[str, str] = field(default_factory=dict)
    frame_counts: dict[str, int] = field(default_factory=dict)
    shared_source_states: dict[str, tuple[str, ...]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RawSpriteFrame:
    image: QImage
    source: str
    anchor_x: float
    anchor_y: float


@dataclass(frozen=True)
class _RawSpritePack:
    pack_id: str
    name: str
    source: str
    states: dict[str, list[_RawSpriteFrame]]
    animations: dict[str, dict[str, object]] = field(default_factory=dict)
    metadata: SpritePackMetadata = field(default_factory=SpritePackMetadata)
    canvas_width_hint: int | None = None
    canvas_height_hint: int | None = None


def user_sprite_packs_dir() -> Path:
    override = str(os.environ.get(USER_SPRITE_PACKS_DIR_ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    return default_user_sprite_packs_dir()


def sprite_pack_search_dirs(assets_dir: Path) -> tuple[Path, ...]:
    dirs: list[Path] = []
    for candidate in (Path(assets_dir) / _PACKS_DIR, user_sprite_packs_dir()):
        if candidate in dirs:
            continue
        dirs.append(candidate)
    return tuple(dirs)


def available_sprite_pack_ids(assets_dir: Path) -> list[str]:
    pack_ids = set(LEGACY_SPRITE_SETS.keys())
    for packs_dir in sprite_pack_search_dirs(assets_dir):
        if not packs_dir.is_dir():
            continue
        for manifest_path in sorted(packs_dir.glob("*/manifest.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pack_ids.add(manifest_path.parent.name)
                continue
            pack_id = str(payload.get("id") or "").strip() or manifest_path.parent.name
            pack_ids.add(pack_id)
    ordered = [DEFAULT_SPRITE_PACK_ID] if DEFAULT_SPRITE_PACK_ID in pack_ids else []
    ordered.extend(pack_id for pack_id in sorted(pack_ids) if pack_id not in ordered)
    return ordered


def describe_available_sprite_packs(assets_dir: Path) -> list[SpritePackSummary]:
    summaries: list[SpritePackSummary] = []
    for pack_id in available_sprite_pack_ids(assets_dir):
        try:
            summaries.append(describe_sprite_pack(assets_dir, pack_id))
        except SpritePackError:
            continue
    return summaries


def ensure_user_sprite_pack_template(assets_dir: Path) -> Path:
    """Create a small editable user-pack template and return the user pack root."""
    root = user_sprite_packs_dir()
    template = root / USER_SPRITE_PACK_TEMPLATE_ID
    for relative_dir in (
        "poses/idle",
        "poses/dialogue",
        "poses/held",
        "poses/transition",
        "poses/outing",
    ):
        (template / relative_dir).mkdir(parents=True, exist_ok=True)

    copies = {
        "poses/idle/idle.png": "maid_idle.png",
        "poses/idle/blink.png": "maid_idle_blink.png",
        "poses/dialogue/stand.png": "maid_reply_sarcastic.png",
        "poses/dialogue/excited.png": "maid.png",
        "poses/held/held.png": "maid.png",
        "poses/transition/enter.png": "maid_enter.png",
        "poses/transition/exit.png": "maid_exit.png",
        "poses/transition/sleepy.png": "maid_yawn.png",
        "poses/transition/peckish.png": "maid_peckish.png",
        "poses/outing/outing.png": "maid_exit.png",
    }
    for target_relative, source_relative in copies.items():
        target = template / target_relative
        source = Path(assets_dir) / source_relative
        if target.exists() or not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    manifest_path = template / "manifest.json"
    if not manifest_path.exists():
        manifest = {
            "id": USER_SPRITE_PACK_TEMPLATE_ID,
            "name": "My Maid",
            "version": 1,
            "author": "",
            "description": "Editable DeskMaid sprite-pack template.",
            "tags": ["template", "local"],
            "default_pose": "idle",
            "preview_pose": "alert",
            "canvas_width": 480,
            "canvas_height": 480,
            "default_anchor": {"x": DEFAULT_ANCHOR_X, "y": DEFAULT_ANCHOR_Y},
            "poses": {
                "idle": "poses/idle/idle.png",
                "blink": "poses/idle/blink.png",
                "alert": "poses/dialogue/stand.png",
                "excited": "poses/dialogue/excited.png",
                "enter": "poses/transition/enter.png",
                "exit": "poses/transition/exit.png",
                "sleepy": "poses/transition/sleepy.png",
                "peckish": "poses/transition/peckish.png",
                "outing": "poses/outing/outing.png",
                "held": "poses/held/held.png",
            },
            "animations": {
                "walk": {"fps": 4, "frames": []},
            },
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    readme_path = template / "README.txt"
    if not readme_path.exists():
        readme_path.write_text(
            "\n".join(
                [
                    "DeskMaid sprite-pack template",
                    "",
                    "Replace the PNG files under poses/ with transparent-background art.",
                    "Keep a stable canvas, consistent bottom anchor, and about 8% transparent padding.",
                    "After editing images, use DeskMaid's sprite-pack panel to reload or switch packs.",
                    "",
                    "Core states: " + ", ".join(STANDARD_SPRITE_STATES),
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return root


def resolve_sprite_pack(
    *,
    assets_dir: Path,
    sprite_set: str | None,
    sprite: str | None,
) -> SpritePackBundle:
    if sprite:
        return _build_single_sprite_pack(assets_dir, sprite)

    pack_id = str(sprite_set or DEFAULT_SPRITE_PACK_ID).strip() or DEFAULT_SPRITE_PACK_ID
    base_pack = _load_raw_pack_by_id(assets_dir, pack_id)
    fallback_states: dict[str, str] = {}

    if pack_id != DEFAULT_SPRITE_PACK_ID:
        try:
            default_pack = _load_raw_pack_by_id(assets_dir, DEFAULT_SPRITE_PACK_ID)
        except SpritePackError:
            default_pack = None
        if default_pack is not None:
            merged_states = dict(base_pack.states)
            for state_key, frames in default_pack.states.items():
                if merged_states.get(state_key):
                    continue
                merged_states[state_key] = frames
                fallback_states[state_key] = DEFAULT_SPRITE_PACK_ID
            merged_canvas_width_hint = int(base_pack.canvas_width_hint or 0) or None
            merged_canvas_height_hint = int(base_pack.canvas_height_hint or 0) or None
            if fallback_states:
                merged_canvas_width_hint = max(
                    int(base_pack.canvas_width_hint or 0),
                    int(default_pack.canvas_width_hint or 0),
                ) or None
                merged_canvas_height_hint = max(
                    int(base_pack.canvas_height_hint or 0),
                    int(default_pack.canvas_height_hint or 0),
                ) or None
            base_pack = _RawSpritePack(
                pack_id=base_pack.pack_id,
                name=base_pack.name,
                source=base_pack.source,
                states=merged_states,
                animations=dict(base_pack.animations),
                metadata=base_pack.metadata,
                canvas_width_hint=merged_canvas_width_hint,
                canvas_height_hint=merged_canvas_height_hint,
            )

    if "idle" not in base_pack.states:
        raise SpritePackError(f"sprite pack {pack_id!r} has no 'idle' pose")

    states, canvas_w, canvas_h, state_sources = _align_sprite_states(
        base_pack.states,
        min_canvas_width=base_pack.canvas_width_hint,
        min_canvas_height=base_pack.canvas_height_hint,
    )
    return SpritePackBundle(
        pack_id=base_pack.pack_id,
        name=base_pack.name,
        source=base_pack.source,
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        states=states,
        state_sources=state_sources,
        fallback_states=fallback_states,
        animations=dict(base_pack.animations),
        metadata=base_pack.metadata,
    )


def diagnose_sprite_pack(
    bundle: SpritePackBundle,
    *,
    expected_states: tuple[str, ...] = STANDARD_SPRITE_STATES,
) -> SpritePackDiagnostic:
    states = bundle.states
    expected = tuple(str(state or "").strip() for state in expected_states if str(state or "").strip())
    missing = tuple(state for state in expected if state not in states)
    frame_counts = {state: len(frames) for state, frames in sorted(states.items())}
    warnings: list[str] = []
    errors: list[str] = []

    if missing:
        warnings.append("missing semantic states: " + ", ".join(missing))
    if bundle.fallback_states:
        warnings.append(
            "fallback states: "
            + ", ".join(f"{state}->{source}" for state, source in sorted(bundle.fallback_states.items()))
        )

    source_to_states: dict[tuple[str, ...], list[str]] = {}
    for state, sources in sorted(bundle.state_sources.items()):
        key = tuple(str(source) for source in sources)
        if key:
            source_to_states.setdefault(key, []).append(state)
    shared_source_states = {
        " / ".join(sources): tuple(states_for_source)
        for sources, states_for_source in source_to_states.items()
        if len(states_for_source) > 1
    }
    if shared_source_states:
        warnings.append(
            "shared art mappings: "
            + "; ".join(
                f"{', '.join(states_for_source)}"
                for states_for_source in shared_source_states.values()
            )
        )

    for state, frames in sorted(states.items()):
        if not frames:
            errors.append(f"{state}: no frames")
            continue
        for index, image in enumerate(frames):
            if image.width() != bundle.canvas_width or image.height() != bundle.canvas_height:
                errors.append(
                    f"{state}[{index}]: canvas {image.width()}x{image.height()} "
                    f"does not match pack canvas {bundle.canvas_width}x{bundle.canvas_height}"
                )
            bounds = _visible_bounds(image)
            if bounds is None:
                errors.append(f"{state}[{index}]: fully transparent")
                continue
            left, top, right, bottom = bounds
            pad_x = min(left, max(0, image.width() - right - 1)) / max(1, image.width())
            pad_y = min(top, max(0, image.height() - bottom - 1)) / max(1, image.height())
            if min(pad_x, pad_y) < 0.02:
                warnings.append(
                    f"{state}[{index}]: visible art is very close to the canvas edge"
                )
                break

    return SpritePackDiagnostic(
        pack_id=bundle.pack_id,
        ok=not errors,
        expected_states=expected,
        missing_states=missing,
        fallback_states=dict(bundle.fallback_states),
        frame_counts=frame_counts,
        shared_source_states=shared_source_states,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def _build_single_sprite_pack(assets_dir: Path, sprite_name: str) -> SpritePackBundle:
    name = str(sprite_name or "").strip()
    if not name:
        raise SpritePackError("legacy sprite name is empty")
    idle_path = Path(assets_dir) / f"{name}.png"
    blink_path = Path(assets_dir) / f"{name}_blink.png"

    states: dict[str, list[_RawSpriteFrame]] = {
        "idle": [_raw_frame_from_path(idle_path, anchor_x=DEFAULT_ANCHOR_X, anchor_y=DEFAULT_ANCHOR_Y)],
    }
    if blink_path.is_file():
        states["blink"] = [
            _raw_frame_from_path(
                blink_path,
                anchor_x=DEFAULT_ANCHOR_X,
                anchor_y=DEFAULT_ANCHOR_Y,
            )
        ]
    aligned_states, canvas_w, canvas_h, state_sources = _align_sprite_states(states)
    return SpritePackBundle(
        pack_id=f"legacy:{name}",
        name=f"legacy:{name}",
        source="legacy",
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        states=aligned_states,
        state_sources=state_sources,
        fallback_states={},
        animations={},
        metadata=SpritePackMetadata(
            author="legacy",
            description="Legacy single-sprite import.",
            tags=("legacy", "single-sprite"),
            display_scale=1.0,
        ),
    )


def describe_sprite_pack(assets_dir: Path, pack_id: str) -> SpritePackSummary:
    normalized_pack_id = str(pack_id or "").strip()
    if not normalized_pack_id:
        raise SpritePackError("sprite pack id is empty")

    manifest_path = _manifest_path_for_pack_id(assets_dir, normalized_pack_id)
    if manifest_path is not None:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SpritePackError(f"failed to parse {manifest_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SpritePackError(f"manifest {manifest_path} must contain a JSON object")
        poses = payload.get("poses")
        if not isinstance(poses, dict):
            raise SpritePackError(f"manifest {manifest_path} is missing a 'poses' object")
        pack_name = str(payload.get("name") or "").strip() or normalized_pack_id
        available_states = tuple(
            sorted(
                str(state_key or "").strip()
                for state_key in poses.keys()
                if str(state_key or "").strip()
            )
        )
        return SpritePackSummary(
            pack_id=normalized_pack_id,
            name=pack_name,
            source=str(manifest_path),
            available_states=available_states,
            metadata=_parse_pack_metadata(payload),
        )

    mapping = LEGACY_SPRITE_SETS.get(normalized_pack_id)
    if mapping is None:
        raise SpritePackError(
            f"unknown sprite pack {normalized_pack_id!r}; "
            f"available: {', '.join(available_sprite_pack_ids(assets_dir))}"
        )
    available_states = tuple(
        sorted(state_key for state_key, filename in mapping.items() if filename)
    )
    return SpritePackSummary(
        pack_id=normalized_pack_id,
        name=normalized_pack_id,
        source="legacy",
        available_states=available_states,
        metadata=SpritePackMetadata(
            author="legacy",
            description="Legacy built-in sprite pack.",
            tags=("legacy", normalized_pack_id),
        ),
    )


def _load_raw_pack_by_id(assets_dir: Path, pack_id: str) -> _RawSpritePack:
    normalized_pack_id = str(pack_id or "").strip()
    if not normalized_pack_id:
        raise SpritePackError("sprite pack id is empty")

    manifest_path = _manifest_path_for_pack_id(assets_dir, normalized_pack_id)
    if manifest_path is not None:
        return _load_manifest_pack(manifest_path)

    mapping = LEGACY_SPRITE_SETS.get(normalized_pack_id)
    if mapping is None:
        raise SpritePackError(
            f"unknown sprite pack {normalized_pack_id!r}; "
            f"available: {', '.join(available_sprite_pack_ids(assets_dir))}"
        )
    states: dict[str, list[_RawSpriteFrame]] = {}
    for state_key, filename in mapping.items():
        if not filename:
            continue
        states[state_key] = [
            _raw_frame_from_path(
                Path(assets_dir) / filename,
                anchor_x=DEFAULT_ANCHOR_X,
                anchor_y=DEFAULT_ANCHOR_Y,
            )
        ]
    if "idle" not in states:
        raise SpritePackError(f"legacy sprite pack {normalized_pack_id!r} has no idle sprite")
    return _RawSpritePack(
        pack_id=normalized_pack_id,
        name=normalized_pack_id,
        source="legacy",
        states=states,
        animations={},
        metadata=SpritePackMetadata(
            author="legacy",
            description="Legacy built-in sprite pack.",
            tags=("legacy", normalized_pack_id),
        ),
    )


def _manifest_path_for_pack_id(assets_dir: Path, pack_id: str) -> Path | None:
    for packs_dir in sprite_pack_search_dirs(assets_dir):
        if not packs_dir.is_dir():
            continue
        for manifest_path in sorted(packs_dir.glob("*/manifest.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            manifest_pack_id = str(payload.get("id") or "").strip() or manifest_path.parent.name
            if manifest_pack_id == pack_id:
                return manifest_path
        direct_candidate = packs_dir / pack_id / "manifest.json"
        if direct_candidate.is_file():
            return direct_candidate
    return None


def _load_manifest_pack(manifest_path: Path) -> _RawSpritePack:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SpritePackError(f"failed to parse {manifest_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise SpritePackError(f"manifest {manifest_path} must contain a JSON object")

    pack_id = str(payload.get("id") or "").strip() or manifest_path.parent.name
    name = str(payload.get("name") or "").strip() or pack_id
    metadata = _parse_pack_metadata(payload)
    canvas_width_hint = _normalize_optional_positive_int(payload.get("canvas_width"))
    canvas_height_hint = _normalize_optional_positive_int(payload.get("canvas_height"))
    poses = payload.get("poses")
    if not isinstance(poses, dict):
        raise SpritePackError(f"manifest {manifest_path} is missing a 'poses' object")

    anchor_payload = payload.get("default_anchor")
    anchor_x, anchor_y = _normalize_anchor_pair(anchor_payload)
    states: dict[str, list[_RawSpriteFrame]] = {}
    pack_root = manifest_path.parent

    for state_key, pose_spec in poses.items():
        normalized_state = str(state_key or "").strip()
        if not normalized_state:
            continue
        try:
            frames = _load_pose_frames(
                pack_root=pack_root,
                pose_spec=pose_spec,
                default_anchor_x=anchor_x,
                default_anchor_y=anchor_y,
            )
        except SpritePackError as exc:
            if normalized_state == "idle":
                raise
            print(f"[sprite-pack] skipped {pack_id}.{normalized_state}: {exc}")
            frames = []
        if frames:
            states[normalized_state] = frames

    animations_payload = payload.get("animations")
    animations: dict[str, dict[str, object]] = {}
    if isinstance(animations_payload, dict):
        for name_key, value in animations_payload.items():
            normalized_key = str(name_key or "").strip()
            if normalized_key and isinstance(value, dict):
                animations[normalized_key] = dict(value)

    if "idle" not in states:
        raise SpritePackError(f"manifest pack {pack_id!r} has no idle pose")
    default_pose = metadata.default_pose if metadata.default_pose in states else "idle"
    preview_pose = metadata.preview_pose if metadata.preview_pose in states else default_pose
    metadata = SpritePackMetadata(
        version=metadata.version,
        author=metadata.author,
        description=metadata.description,
        website=metadata.website,
        license_name=metadata.license_name,
        tags=metadata.tags,
        default_pose=default_pose,
        preview_pose=preview_pose,
        display_scale=metadata.display_scale,
    )
    return _RawSpritePack(
        pack_id=pack_id,
        name=name,
        source=str(manifest_path),
        states=states,
        animations=animations,
        metadata=metadata,
        canvas_width_hint=canvas_width_hint,
        canvas_height_hint=canvas_height_hint,
    )


def _parse_pack_metadata(payload: dict[str, object]) -> SpritePackMetadata:
    version = _normalize_optional_positive_int(payload.get("version")) or 1
    author = str(payload.get("author") or "").strip()
    description = str(payload.get("description") or "").strip()
    website = str(payload.get("website") or payload.get("homepage") or "").strip()
    license_name = str(payload.get("license") or "").strip()
    default_pose = str(payload.get("default_pose") or "idle").strip() or "idle"
    preview_pose = str(payload.get("preview_pose") or default_pose).strip() or default_pose
    display_scale = _normalize_optional_positive_float(payload.get("display_scale")) or 1.0
    return SpritePackMetadata(
        version=version,
        author=author,
        description=description,
        website=website,
        license_name=license_name,
        tags=_normalize_tags(payload.get("tags")),
        default_pose=default_pose,
        preview_pose=preview_pose,
        display_scale=display_scale,
    )


def _normalize_tags(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = list(value)
    else:
        return ()

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = str(raw_item or "").strip()
        if not item:
            continue
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(item)
    return tuple(normalized)


def _normalize_optional_positive_int(value: object) -> int | None:
    try:
        normalized = int(value)
    except Exception:
        return None
    if normalized <= 0:
        return None
    return normalized


def _normalize_optional_positive_float(value: object) -> float | None:
    try:
        normalized = float(value)
    except Exception:
        return None
    if math.isnan(normalized) or math.isinf(normalized):
        return None
    if normalized <= 0:
        return None
    return max(0.25, min(8.0, normalized))


def _load_pose_frames(
    *,
    pack_root: Path,
    pose_spec: object,
    default_anchor_x: float,
    default_anchor_y: float,
) -> list[_RawSpriteFrame]:
    if pose_spec is None:
        return []

    anchor_x = default_anchor_x
    anchor_y = default_anchor_y
    path_specs: list[object] = []

    if isinstance(pose_spec, str):
        path_specs = [pose_spec]
    elif isinstance(pose_spec, list):
        path_specs = list(pose_spec)
    elif isinstance(pose_spec, dict):
        anchor_x, anchor_y = _normalize_anchor_pair(
            pose_spec.get("anchor"),
            fallback_x=default_anchor_x,
            fallback_y=default_anchor_y,
        )
        path_value = pose_spec.get("path")
        paths_value = pose_spec.get("paths")
        if isinstance(paths_value, list):
            path_specs = list(paths_value)
        elif path_value is not None:
            path_specs = [path_value]
    else:
        return []

    frames: list[_RawSpriteFrame] = []
    for path_spec in path_specs:
        frames.extend(
            _load_frames_from_path_spec(
                pack_root=pack_root,
                path_spec=path_spec,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
            )
        )
    return frames


def _load_frames_from_path_spec(
    *,
    pack_root: Path,
    path_spec: object,
    anchor_x: float,
    anchor_y: float,
) -> list[_RawSpriteFrame]:
    relative_path = str(path_spec or "").strip()
    if not relative_path:
        return []
    path = (pack_root / relative_path).resolve()
    if path.is_dir():
        frames: list[_RawSpriteFrame] = []
        for child in sorted(path.iterdir()):
            if not child.is_file():
                continue
            if child.suffix.lower() not in _IMAGE_EXTENSIONS:
                continue
            frame = _raw_frame_from_path(child, anchor_x=anchor_x, anchor_y=anchor_y)
            if _image_has_visible_pixels(frame.image):
                frames.append(frame)
        return frames
    frame = _raw_frame_from_path(path, anchor_x=anchor_x, anchor_y=anchor_y)
    return [frame] if _image_has_visible_pixels(frame.image) else []


def _raw_frame_from_path(path: Path, *, anchor_x: float, anchor_y: float) -> _RawSpriteFrame:
    image = _load_image(path)
    return _RawSpriteFrame(
        image=image,
        source=str(path),
        anchor_x=float(anchor_x),
        anchor_y=float(anchor_y),
    )


def _load_image(path: Path) -> QImage:
    if not path.is_file():
        raise SpritePackError(f"missing sprite asset {path}")
    image = QImage(str(path))
    if image.isNull():
        raise SpritePackError(f"failed to load sprite asset {path}")
    if image.format() != QImage.Format_ARGB32:
        image = image.convertToFormat(QImage.Format_ARGB32)
    return image


def _image_has_visible_pixels(image: QImage) -> bool:
    return _visible_bounds(image) is not None


def _visible_bounds(image: QImage) -> tuple[int, int, int, int] | None:
    left = image.width()
    top = image.height()
    right = -1
    bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() <= 0:
                continue
            left = min(left, x)
            top = min(top, y)
            right = max(right, x)
            bottom = max(bottom, y)
    if right < 0 or bottom < 0:
        return None
    return left, top, right, bottom


def _normalize_anchor_pair(
    payload: object,
    *,
    fallback_x: float = DEFAULT_ANCHOR_X,
    fallback_y: float = DEFAULT_ANCHOR_Y,
) -> tuple[float, float]:
    if isinstance(payload, dict):
        raw_x = payload.get("x", fallback_x)
        raw_y = payload.get("y", fallback_y)
    else:
        raw_x = fallback_x
        raw_y = fallback_y
    return (_clamp_anchor(raw_x, fallback_x), _clamp_anchor(raw_y, fallback_y))


def _clamp_anchor(value: object, fallback: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        return float(fallback)
    if math.isnan(numeric) or math.isinf(numeric):
        return float(fallback)
    return max(0.0, min(1.0, numeric))


def _align_sprite_states(
    raw_states: dict[str, list[_RawSpriteFrame]],
    *,
    min_canvas_width: int | None = None,
    min_canvas_height: int | None = None,
) -> tuple[dict[str, list[QImage]], int, int, dict[str, list[str]]]:
    nonempty_frames = [
        frame
        for frames in raw_states.values()
        for frame in frames
    ]
    if not nonempty_frames:
        raise SpritePackError("sprite pack has no usable frames")

    left_extent = 0.0
    right_extent = 0.0
    top_extent = 0.0
    bottom_extent = 0.0
    for frame in nonempty_frames:
        anchor_px = frame.image.width() * frame.anchor_x
        anchor_py = frame.image.height() * frame.anchor_y
        left_extent = max(left_extent, anchor_px)
        right_extent = max(right_extent, frame.image.width() - anchor_px)
        top_extent = max(top_extent, anchor_py)
        bottom_extent = max(bottom_extent, frame.image.height() - anchor_py)

    canvas_w = max(
        1,
        int(math.ceil(left_extent + right_extent)),
        int(min_canvas_width or 0),
    )
    canvas_h = max(
        1,
        int(math.ceil(top_extent + bottom_extent)),
        int(min_canvas_height or 0),
    )
    anchor_canvas_x = int(round(left_extent))
    anchor_canvas_y = int(round(top_extent))

    states: dict[str, list[QImage]] = {}
    state_sources: dict[str, list[str]] = {}
    for state_key, frames in raw_states.items():
        if not frames:
            continue
        aligned_frames: list[QImage] = []
        sources: list[str] = []
        for frame in frames:
            aligned_frames.append(
                _draw_frame_on_canvas(
                    frame.image,
                    canvas_w=canvas_w,
                    canvas_h=canvas_h,
                    anchor_canvas_x=anchor_canvas_x,
                    anchor_canvas_y=anchor_canvas_y,
                    anchor_x=frame.anchor_x,
                    anchor_y=frame.anchor_y,
                )
            )
            sources.append(frame.source)
        states[state_key] = aligned_frames
        state_sources[state_key] = sources

    return states, canvas_w, canvas_h, state_sources


def _draw_frame_on_canvas(
    image: QImage,
    *,
    canvas_w: int,
    canvas_h: int,
    anchor_canvas_x: int,
    anchor_canvas_y: int,
    anchor_x: float,
    anchor_y: float,
) -> QImage:
    frame_anchor_x = image.width() * float(anchor_x)
    frame_anchor_y = image.height() * float(anchor_y)
    draw_x = int(round(anchor_canvas_x - frame_anchor_x))
    draw_y = int(round(anchor_canvas_y - frame_anchor_y))

    if draw_x == 0 and draw_y == 0 and image.width() == canvas_w and image.height() == canvas_h:
        return image

    out = QImage(canvas_w, canvas_h, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.drawImage(draw_x, draw_y, image)
    painter.end()
    return out
