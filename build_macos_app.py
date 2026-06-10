#!/usr/bin/env python3
"""Build, sign, and optionally notarize Deskmaid.app.

Usage:
    .venv/bin/python -u build_macos_app.py
    .venv/bin/python -u build_macos_app.py --verify-health
    .venv/bin/python -u build_macos_app.py --skip-build --verify-health
    .venv/bin/python -u build_macos_app.py --skip-build --dmg
    .venv/bin/python -u build_macos_app.py --list-signing-identities
    DESKMAID_CODESIGN_IDENTITY="Developer ID Application: Example (TEAMID)" \
        .venv/bin/python -u build_macos_app.py --sign --verify-health --verify-signature
    DESKMAID_CODESIGN_IDENTITY="Developer ID Application: Example (TEAMID)" \
    DESKMAID_NOTARY_KEYCHAIN_PROFILE="deskmaid-notary" \
        .venv/bin/python -u build_macos_app.py --notarize --verify-health --verify-gatekeeper
    DESKMAID_CODESIGN_IDENTITY="Developer ID Application: Example (TEAMID)" \
    DESKMAID_NOTARY_KEYCHAIN_PROFILE="deskmaid-notary" \
        .venv/bin/python -u build_macos_app.py --notarize --verify-health --verify-gatekeeper --dmg
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys

import claude_agent_sdk
from PIL import Image
from PIL import ImageOps


ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable
APP_NAME = "Deskmaid"
BUNDLE_ID = "com.regulus.deskmaid"
APP_PATH = ROOT / "dist" / f"{APP_NAME}.app"
APP_EXECUTABLE = APP_PATH / "Contents" / "MacOS" / APP_NAME
BUILD_DIR = ROOT / "build" / "pyinstaller"
DIST_DIR = ROOT / "dist"
ICON_BUILD_DIR = ROOT / "build" / "icons"
DMG_BUILD_DIR = ROOT / "build" / "dmg"
APP_ICON_SOURCE = ROOT / "Maid.png"
APP_ICONSET_PATH = ICON_BUILD_DIR / f"{APP_NAME}.iconset"
APP_ICON_PATH = ICON_BUILD_DIR / f"{APP_NAME}.icns"
DEFAULT_CODESIGN_ENTITLEMENTS_PATH = ROOT / "Deskmaid.entitlements"
DEFAULT_NOTARY_ARCHIVE_PATH = DIST_DIR / f"{APP_NAME}-notarize.zip"
DEFAULT_DMG_PATH = DIST_DIR / "DeskMaid.dmg"
DMG_VOLUME_NAME = "DeskMaid"
USER_GUIDE_SOURCE = ROOT / "DeskMaid-使用手册.md"
USER_GUIDE_RELEASE_NAME = "DeskMaid-README.md"
APPLE_EVENTS_USAGE = (
    "Deskmaid 需要在你确认后控制 Calendar、Reminders、Mail 和 System Events "
    "来完成桌面任务。"
)

CODESIGN_IDENTITY_ENV_VAR = "DESKMAID_CODESIGN_IDENTITY"
CODESIGN_ENTITLEMENTS_ENV_VAR = "DESKMAID_CODESIGN_ENTITLEMENTS"
NOTARY_KEYCHAIN_PROFILE_ENV_VAR = "DESKMAID_NOTARY_KEYCHAIN_PROFILE"
NOTARY_KEYCHAIN_PATH_ENV_VAR = "DESKMAID_NOTARY_KEYCHAIN"
NOTARY_APPLE_ID_ENV_VAR = "DESKMAID_NOTARY_APPLE_ID"
NOTARY_PASSWORD_ENV_VAR = "DESKMAID_NOTARY_PASSWORD"
NOTARY_TEAM_ID_ENV_VAR = "DESKMAID_NOTARY_TEAM_ID"
NOTARY_API_KEY_ENV_VAR = "DESKMAID_NOTARY_API_KEY"
NOTARY_KEY_ID_ENV_VAR = "DESKMAID_NOTARY_KEY_ID"
NOTARY_ISSUER_ENV_VAR = "DESKMAID_NOTARY_ISSUER"


@dataclass(frozen=True)
class CodesignSettings:
    identity: str
    entitlements_path: Path | None = None


@dataclass(frozen=True)
class NotaryAuth:
    mode: str
    args: tuple[str, ...]
    summary: str
    secret_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class NotarySubmissionResult:
    artifact_path: Path
    submission_id: str = ""
    status: str = ""


def _bundled_claude_cli_path() -> Path | None:
    cli_name = "claude.exe" if sys.platform == "win32" else "claude"
    package_root = Path(inspect.getfile(claude_agent_sdk)).resolve().parent
    candidate = package_root / "_bundled" / cli_name
    if candidate.is_file():
        return candidate
    return None


def _first_nonempty(*values: str | None) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _format_command(
    cmd: list[str],
    *,
    secret_values: tuple[str, ...] = (),
) -> str:
    hidden = {str(value) for value in secret_values if str(value)}
    rendered: list[str] = []
    for part in cmd:
        text = str(part)
        if text in hidden:
            rendered.append("******")
        else:
            rendered.append(shlex.quote(text))
    return " ".join(rendered)


def _run_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    capture_output: bool = False,
    secret_values: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    print(f"[cmd] {_format_command(cmd, secret_values=secret_values)}")
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        capture_output=capture_output,
        text=True,
        check=False,
    )


def _raise_command_error(context: str, proc: subprocess.CompletedProcess[str]):
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    raise RuntimeError(f"{context} failed with exit code {proc.returncode}")


def _require_command_available(executable: str, *, hint: str = ""):
    if shutil.which(executable):
        return
    suffix = f" {hint.strip()}" if hint.strip() else ""
    raise FileNotFoundError(f"required command not found: {executable}.{suffix}")


def _prepare_app_icon() -> Path | None:
    if not APP_ICON_SOURCE.is_file():
        print(f"[icon] source image not found, skipping custom app icon: {APP_ICON_SOURCE}")
        return None

    _require_command_available(
        "iconutil",
        hint="This is required on macOS to build a .icns app icon.",
    )

    icon_specs = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]

    ICON_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if APP_ICONSET_PATH.exists():
        shutil.rmtree(APP_ICONSET_PATH)
    APP_ICONSET_PATH.mkdir(parents=True, exist_ok=True)

    with Image.open(APP_ICON_SOURCE) as opened:
        source = opened.convert("RGBA")
        source.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (1024, 1024), (255, 255, 255, 255))
        offset = (
            (canvas.width - source.width) // 2,
            (canvas.height - source.height) // 2,
        )
        canvas.paste(source, offset, source)

        for filename, size in icon_specs:
            resized = ImageOps.contain(canvas, (size, size), Image.Resampling.LANCZOS)
            target = APP_ICONSET_PATH / filename
            resized.save(target, format="PNG")

    if APP_ICON_PATH.exists():
        APP_ICON_PATH.unlink()

    proc = _run_command(
        [
            "iconutil",
            "-c",
            "icns",
            str(APP_ICONSET_PATH),
            "-o",
            str(APP_ICON_PATH),
        ]
    )
    if proc.returncode != 0:
        _raise_command_error("iconutil", proc)

    print(f"[icon] prepared {APP_ICON_PATH} from {APP_ICON_SOURCE.name}")
    return APP_ICON_PATH


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build Deskmaid.app with optional signing/notarization steps.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="skip the PyInstaller build and operate on the existing dist/Deskmaid.app",
    )
    parser.add_argument(
        "--verify-health",
        action="store_true",
        help="run --permission-health-json from the packaged app after the build/sign step",
    )
    parser.add_argument(
        "--list-signing-identities",
        action="store_true",
        help="print locally available code signing identities and exit",
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help=(
            "codesign Deskmaid.app with a Developer ID identity from "
            f"--codesign-identity or {CODESIGN_IDENTITY_ENV_VAR}"
        ),
    )
    parser.add_argument(
        "--codesign-identity",
        help="Developer ID Application identity to use for codesign",
    )
    parser.add_argument(
        "--codesign-entitlements",
        help=(
            "optional entitlements plist for codesign; defaults to "
            f"{DEFAULT_CODESIGN_ENTITLEMENTS_PATH} when present"
        ),
    )
    parser.add_argument(
        "--verify-signature",
        action="store_true",
        help="run codesign verification on the built app",
    )
    parser.add_argument(
        "--notarize",
        action="store_true",
        help=(
            "submit the signed app to notarytool, wait for completion, staple it, "
            "and also notarize the final DMG when --dmg is set"
        ),
    )
    parser.add_argument(
        "--archive-path",
        help=(
            "archive path for app-bundle notary submission; defaults to "
            f"{DEFAULT_NOTARY_ARCHIVE_PATH}"
        ),
    )
    parser.add_argument(
        "--staple",
        action="store_true",
        help=(
            "run stapler against the built app; when --notarize --dmg is used, "
            "the final DMG is also stapled after DMG notarization"
        ),
    )
    parser.add_argument(
        "--dmg",
        action="store_true",
        help=(
            "build a distributable DMG containing Deskmaid.app, an Applications "
            "shortcut, and the DeskMaid README"
        ),
    )
    parser.add_argument(
        "--dmg-path",
        help=f"output path for the DMG; defaults to {DEFAULT_DMG_PATH}",
    )
    parser.add_argument(
        "--verify-gatekeeper",
        action="store_true",
        help=(
            "run spctl assessment on the final app bundle; when --notarize --dmg "
            "is used, the final DMG is also assessed"
        ),
    )
    parser.add_argument(
        "--notary-keychain-profile",
        help=(
            "preferred notarytool auth method: profile created via "
            "`xcrun notarytool store-credentials`"
        ),
    )
    parser.add_argument(
        "--notary-keychain",
        help="optional custom keychain path for --notary-keychain-profile",
    )
    parser.add_argument(
        "--notary-apple-id",
        help="Apple ID for notarytool authentication",
    )
    parser.add_argument(
        "--notary-password",
        help="app-specific password for --notary-apple-id (env var is safer than shell history)",
    )
    parser.add_argument(
        "--notary-team-id",
        help="Developer Team ID for --notary-apple-id",
    )
    parser.add_argument(
        "--notary-api-key",
        help="path to the App Store Connect API key (.p8) for notarytool",
    )
    parser.add_argument(
        "--notary-key-id",
        help="App Store Connect API key ID for --notary-api-key",
    )
    parser.add_argument(
        "--notary-issuer",
        help="App Store Connect issuer ID; optional for individual API keys",
    )
    parser.add_argument(
        "--notary-timeout",
        default="15m",
        help="how long notarytool should wait before timing out (default: 15m)",
    )
    return parser


def _pyinstaller_command() -> list[str]:
    asset_dir = ROOT / "Maid" / "assets"
    icon_path = _prepare_app_icon()
    cmd = [
        PYTHON,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(ROOT),
        "--paths",
        str(ROOT / "Maid"),
        "--osx-bundle-identifier",
        BUNDLE_ID,
        "--hidden-import",
        "objc",
        "--hidden-import",
        "AppKit",
        "--hidden-import",
        "Foundation",
        "--hidden-import",
        "Intents",
        "--hidden-import",
        "AVFoundation",
        "--hidden-import",
        "Quartz",
        "--hidden-import",
        "qasync",
        "--collect-submodules",
        "claude_agent_sdk",
        "--collect-submodules",
        "anthropic",
        "--collect-data",
        "PySide6",
        "--add-data",
        f"{asset_dir}:Maid/assets",
        str(ROOT / "Maid" / "main.py"),
    ]
    if icon_path is not None:
        cmd.extend(
            [
                "--icon",
                str(icon_path),
            ]
        )
    bundled_cli = _bundled_claude_cli_path()
    if bundled_cli is not None:
        cmd.extend(
            [
                "--add-binary",
                f"{bundled_cli}:claude_agent_sdk/_bundled",
            ]
        )
    return cmd


def _patch_info_plist(app_path: Path):
    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.is_file():
        raise FileNotFoundError(f"missing Info.plist: {plist_path}")

    with plist_path.open("rb") as fh:
        info = plistlib.load(fh)

    info["CFBundleDisplayName"] = APP_NAME
    info["CFBundleName"] = APP_NAME
    info["CFBundleIdentifier"] = BUNDLE_ID
    info.pop("LSUIElement", None)
    info["NSAppleEventsUsageDescription"] = APPLE_EVENTS_USAGE
    # 自动免打扰只读摄像头占用状态、不采集画面；声明该键以便枚举 Continuity Camera 设备。
    info["NSCameraUseContinuityCameraDeviceType"] = True

    with plist_path.open("wb") as fh:
        plistlib.dump(info, fh, sort_keys=True)


def _build_app() -> Path:
    if APP_PATH.exists():
        shutil.rmtree(APP_PATH)

    cmd = _pyinstaller_command()
    print(f"[build] {_format_command(cmd)}")
    proc = _run_command(cmd)
    if proc.returncode != 0:
        _raise_command_error("PyInstaller build", proc)

    _patch_info_plist(APP_PATH)
    if not APP_EXECUTABLE.is_file():
        raise FileNotFoundError(f"missing app executable: {APP_EXECUTABLE}")
    print(f"[build] built {APP_PATH}")
    return APP_PATH


def _list_signing_identities() -> int:
    _require_command_available(
        "security",
        hint="This is part of macOS command-line tools.",
    )
    proc = _run_command(["security", "find-identity", "-v", "-p", "codesigning"])
    if proc.returncode != 0:
        _raise_command_error("security find-identity", proc)
    return 0


def _resolve_codesign_settings(args) -> CodesignSettings | None:
    if not (bool(args.sign) or bool(args.notarize)):
        return None

    identity = _first_nonempty(
        args.codesign_identity,
        os.environ.get(CODESIGN_IDENTITY_ENV_VAR),
    )
    if not identity:
        raise RuntimeError(
            "Signing was requested, but no codesign identity was provided. "
            f"Pass --codesign-identity or set {CODESIGN_IDENTITY_ENV_VAR}. "
            "Use --list-signing-identities to inspect the local keychain."
        )

    entitlements_raw = _first_nonempty(
        args.codesign_entitlements,
        os.environ.get(CODESIGN_ENTITLEMENTS_ENV_VAR),
    )
    entitlements_path: Path | None = None
    if entitlements_raw:
        entitlements_path = Path(entitlements_raw).expanduser().resolve()
        if not entitlements_path.is_file():
            raise FileNotFoundError(
                f"codesign entitlements file not found: {entitlements_path}"
            )
    elif DEFAULT_CODESIGN_ENTITLEMENTS_PATH.is_file():
        entitlements_path = DEFAULT_CODESIGN_ENTITLEMENTS_PATH.resolve()

    return CodesignSettings(
        identity=identity,
        entitlements_path=entitlements_path,
    )


def _resolve_notary_auth(args) -> NotaryAuth | None:
    if not bool(args.notarize):
        return None

    keychain_profile = _first_nonempty(
        args.notary_keychain_profile,
        os.environ.get(NOTARY_KEYCHAIN_PROFILE_ENV_VAR),
    )
    keychain_path = _first_nonempty(
        args.notary_keychain,
        os.environ.get(NOTARY_KEYCHAIN_PATH_ENV_VAR),
    )
    apple_id = _first_nonempty(
        args.notary_apple_id,
        os.environ.get(NOTARY_APPLE_ID_ENV_VAR),
    )
    password = _first_nonempty(
        args.notary_password,
        os.environ.get(NOTARY_PASSWORD_ENV_VAR),
    )
    team_id = _first_nonempty(
        args.notary_team_id,
        os.environ.get(NOTARY_TEAM_ID_ENV_VAR),
    )
    api_key = _first_nonempty(
        args.notary_api_key,
        os.environ.get(NOTARY_API_KEY_ENV_VAR),
    )
    key_id = _first_nonempty(
        args.notary_key_id,
        os.environ.get(NOTARY_KEY_ID_ENV_VAR),
    )
    issuer = _first_nonempty(
        args.notary_issuer,
        os.environ.get(NOTARY_ISSUER_ENV_VAR),
    )

    methods: list[NotaryAuth] = []

    if keychain_profile:
        profile_args = ["--keychain-profile", keychain_profile]
        summary = f"keychain profile `{keychain_profile}`"
        if keychain_path:
            profile_args.extend(["--keychain", keychain_path])
            summary += f" @ {keychain_path}"
        methods.append(
            NotaryAuth(
                mode="keychain-profile",
                args=tuple(profile_args),
                summary=summary,
            )
        )

    if api_key or key_id or issuer:
        if not api_key or not key_id:
            raise RuntimeError(
                "Notary API-key auth is incomplete. Provide both "
                f"--notary-api-key/ {NOTARY_API_KEY_ENV_VAR} and "
                f"--notary-key-id/ {NOTARY_KEY_ID_ENV_VAR}."
            )
        api_key_path = Path(api_key).expanduser().resolve()
        if not api_key_path.is_file():
            raise FileNotFoundError(f"notary API key file not found: {api_key_path}")
        api_args = [
            "--key",
            str(api_key_path),
            "--key-id",
            key_id,
        ]
        if issuer:
            api_args.extend(["--issuer", issuer])
        methods.append(
            NotaryAuth(
                mode="api-key",
                args=tuple(api_args),
                summary=f"App Store Connect API key `{api_key_path.name}`",
            )
        )

    if apple_id or password or team_id:
        if not apple_id or not password or not team_id:
            raise RuntimeError(
                "Apple ID notarization auth is incomplete. Provide "
                "--notary-apple-id, --notary-password, and --notary-team-id "
                f"(or {NOTARY_APPLE_ID_ENV_VAR}, {NOTARY_PASSWORD_ENV_VAR}, {NOTARY_TEAM_ID_ENV_VAR})."
            )
        methods.append(
            NotaryAuth(
                mode="apple-id",
                args=(
                    "--apple-id",
                    apple_id,
                    "--password",
                    password,
                    "--team-id",
                    team_id,
                ),
                summary=f"Apple ID `{apple_id}` / team `{team_id}`",
                secret_values=(password,),
            )
        )

    if not methods:
        raise RuntimeError(
            "Notarization was requested, but no notary credentials were configured. "
            "Preferred: set "
            f"{NOTARY_KEYCHAIN_PROFILE_ENV_VAR} after running "
            "`xcrun notarytool store-credentials`. "
            "Alternatively provide App Store Connect API-key credentials or Apple ID credentials."
        )

    if len(methods) > 1:
        joined = ", ".join(method.summary for method in methods)
        raise RuntimeError(
            "Notarization credentials are ambiguous. Pick exactly one auth method. "
            f"Currently detected: {joined}"
        )

    return methods[0]


def _resolve_archive_path(raw_value: str | None) -> Path:
    if not str(raw_value or "").strip():
        return DEFAULT_NOTARY_ARCHIVE_PATH
    return Path(str(raw_value)).expanduser().resolve()


def _resolve_dmg_path(raw_value: str | None) -> Path:
    if not str(raw_value or "").strip():
        return DEFAULT_DMG_PATH
    return Path(str(raw_value)).expanduser().resolve()


def _codesign_app(app_path: Path, settings: CodesignSettings):
    _require_command_available("codesign")
    cmd = [
        "codesign",
        "--force",
        "--deep",
        "--sign",
        settings.identity,
        "--timestamp",
        "--options",
        "runtime",
    ]
    if settings.entitlements_path is not None:
        cmd.extend(["--entitlements", str(settings.entitlements_path)])
    cmd.append(str(app_path))
    proc = _run_command(cmd)
    if proc.returncode != 0:
        _raise_command_error("codesign", proc)
    print(f"[sign] signed {app_path} with {settings.identity}")
    if settings.entitlements_path is not None:
        print(f"[sign] entitlements: {settings.entitlements_path}")


def _verify_signature(app_path: Path):
    _require_command_available("codesign")
    proc = _run_command(
        [
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            "--verbose=2",
            str(app_path),
        ]
    )
    if proc.returncode != 0:
        _raise_command_error("codesign verification", proc)
    print(f"[sign] verification passed for {app_path}")


def _archive_for_notary(app_path: Path, archive_path: Path) -> Path:
    _require_command_available("ditto")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()
    cmd = [
        "ditto",
        "-c",
        "-k",
        "--sequesterRsrc",
        "--keepParent",
        str(app_path),
        str(archive_path),
    ]
    proc = _run_command(cmd)
    if proc.returncode != 0:
        _raise_command_error("ditto archive", proc)
    print(f"[notary] archive ready: {archive_path}")
    return archive_path


def _fetch_notary_log(
    submission_id: str,
    auth: NotaryAuth,
) -> str:
    if not submission_id:
        return ""
    cmd = [
        "xcrun",
        "notarytool",
        "log",
        submission_id,
        *auth.args,
        "--output-format",
        "json",
    ]
    proc = _run_command(
        cmd,
        capture_output=True,
        secret_values=auth.secret_values,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or proc.stderr or "").strip()


def _submit_for_notarization(
    artifact_path: Path,
    auth: NotaryAuth,
    *,
    timeout: str,
) -> NotarySubmissionResult:
    _require_command_available("xcrun")
    cmd = [
        "xcrun",
        "notarytool",
        "submit",
        str(artifact_path),
        *auth.args,
        "--wait",
        "--timeout",
        timeout,
        "--output-format",
        "json",
        "--no-progress",
    ]
    proc = _run_command(
        cmd,
        capture_output=True,
        secret_values=auth.secret_values,
    )
    if proc.returncode != 0:
        _raise_command_error("notarytool submit", proc)

    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("notarytool submit returned no stdout")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"notarytool submit returned invalid JSON: {raw!r}"
        ) from exc

    submission_id = str(payload.get("id") or "").strip()
    status = str(payload.get("status") or "").strip()
    message = _first_nonempty(
        str(payload.get("message") or ""),
        str(payload.get("statusSummary") or ""),
    )

    if submission_id:
        print(f"[notary] submission id: {submission_id}")
    if status:
        print(f"[notary] status: {status}")
    if message:
        print(f"[notary] message: {message}")

    normalized_status = status.lower()
    if normalized_status and normalized_status != "accepted":
        log_text = _fetch_notary_log(submission_id, auth)
        if log_text:
            print("[notary] log:")
            print(log_text)
        raise RuntimeError(
            f"notarytool finished with non-accepted status: {status or 'unknown'}"
        )

    return NotarySubmissionResult(
        artifact_path=artifact_path,
        submission_id=submission_id,
        status=status,
    )


def _staple_target(target_path: Path):
    _require_command_available("xcrun")
    proc = _run_command(["xcrun", "stapler", "staple", "-v", str(target_path)])
    if proc.returncode != 0:
        _raise_command_error("stapler staple", proc)
    validate = _run_command(["xcrun", "stapler", "validate", "-v", str(target_path)])
    if validate.returncode != 0:
        _raise_command_error("stapler validate", validate)
    print(f"[staple] stapled ticket onto {target_path}")


def _verify_gatekeeper(app_path: Path):
    _require_command_available("spctl")
    proc = _run_command(
        ["spctl", "--assess", "--type", "execute", "-vv", str(app_path)]
    )
    if proc.returncode != 0:
        _raise_command_error("spctl assess", proc)
    print(f"[gatekeeper] assessment passed for {app_path}")


def _verify_gatekeeper_disk_image(dmg_path: Path):
    _require_command_available("spctl")
    proc = _run_command(
        ["spctl", "--assess", "--type", "open", "-vv", str(dmg_path)]
    )
    if proc.returncode != 0:
        _raise_command_error("spctl assess disk image", proc)
    print(f"[gatekeeper] disk image assessment passed for {dmg_path}")


def _run_packaged_health(app_path: Path) -> dict[str, object]:
    executable = app_path / "Contents" / "MacOS" / APP_NAME
    if not executable.is_file():
        raise FileNotFoundError(f"missing app executable: {executable}")

    cmd = [str(executable), "--permission-health-json"]
    print(f"[health] {_format_command(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"packaged health check failed with exit code {proc.returncode}")

    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError("packaged health check produced no stdout")
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"packaged health check returned invalid JSON: {raw!r}") from exc

    print(snapshot.get("summary_text") or "[health] no summary")
    for check in snapshot.get("checks") or []:
        if not isinstance(check, dict):
            continue
        print(
            f"- {check.get('title')}: {check.get('status_label')} :: "
            f"{check.get('summary')}"
        )
    error_count = int(snapshot.get("error_count") or 0)
    if error_count > 0:
        raise RuntimeError(
            f"packaged health reported {error_count} error(s); fix them before shipping"
        )
    return snapshot


def _stage_dmg_contents(app_path: Path) -> Path:
    _require_command_available(
        "ditto",
        hint="This is required on macOS to stage release bundles into a DMG.",
    )
    stage_dir = DMG_BUILD_DIR / DMG_VOLUME_NAME
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    staged_app_path = stage_dir / app_path.name
    proc = _run_command(["ditto", str(app_path), str(staged_app_path)])
    if proc.returncode != 0:
        _raise_command_error("ditto stage app", proc)

    applications_link = stage_dir / "Applications"
    if applications_link.exists() or applications_link.is_symlink():
        if applications_link.is_symlink() or applications_link.is_file():
            applications_link.unlink()
        else:
            shutil.rmtree(applications_link)
    applications_link.symlink_to("/Applications", target_is_directory=True)

    if USER_GUIDE_SOURCE.is_file():
        shutil.copy2(USER_GUIDE_SOURCE, stage_dir / USER_GUIDE_RELEASE_NAME)
    else:
        print(f"[dmg] README source not found, skipping: {USER_GUIDE_SOURCE}")

    print(f"[dmg] staged contents at {stage_dir}")
    return stage_dir


def _build_dmg(app_path: Path, dmg_path: Path) -> Path:
    _require_command_available(
        "hdiutil",
        hint="This is required on macOS to build a DMG installer.",
    )
    staged_dir = _stage_dmg_contents(app_path)
    dmg_path.parent.mkdir(parents=True, exist_ok=True)
    if dmg_path.exists():
        dmg_path.unlink()

    proc = _run_command(
        [
            "hdiutil",
            "create",
            "-volname",
            DMG_VOLUME_NAME,
            "-srcfolder",
            str(staged_dir),
            "-ov",
            "-format",
            "UDZO",
            str(dmg_path),
        ]
    )
    if proc.returncode != 0:
        _raise_command_error("hdiutil create", proc)
    print(f"[dmg] built {dmg_path}")
    return dmg_path


def main() -> int:
    args = _build_parser().parse_args()

    if bool(args.list_signing_identities):
        return _list_signing_identities()

    sign_requested = bool(args.sign or args.notarize)
    verify_signature_requested = bool(args.verify_signature or sign_requested)
    staple_requested = bool(args.staple or args.notarize)
    dmg_requested = bool(args.dmg)

    app_path = APP_PATH
    if args.skip_build and not app_path.exists():
        print(
            f"[error] --skip-build was set, but no existing app was found at {app_path}",
            file=sys.stderr,
        )
        return 1

    codesign_settings = _resolve_codesign_settings(args)
    notary_auth = _resolve_notary_auth(args)
    archive_path = _resolve_archive_path(args.archive_path) if args.notarize else None
    dmg_path = _resolve_dmg_path(args.dmg_path) if dmg_requested else None

    if not args.skip_build:
        app_path = _build_app()

    if sign_requested:
        assert codesign_settings is not None
        _codesign_app(app_path, codesign_settings)

    if verify_signature_requested:
        _verify_signature(app_path)

    if args.verify_health:
        _run_packaged_health(app_path)

    if args.notarize:
        assert notary_auth is not None
        assert archive_path is not None
        _submit_for_notarization(
            _archive_for_notary(app_path, archive_path),
            notary_auth,
            timeout=str(args.notary_timeout or "15m"),
        )

    if staple_requested:
        _staple_target(app_path)

    if bool(args.verify_gatekeeper):
        _verify_gatekeeper(app_path)

    if dmg_requested:
        assert dmg_path is not None
        _build_dmg(app_path, dmg_path)
        if args.notarize:
            assert notary_auth is not None
            _submit_for_notarization(
                dmg_path,
                notary_auth,
                timeout=str(args.notary_timeout or "15m"),
            )
            _staple_target(dmg_path)
            if bool(args.verify_gatekeeper):
                _verify_gatekeeper_disk_image(dmg_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
