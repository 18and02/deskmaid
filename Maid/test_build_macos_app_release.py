"""Smoke test for Deskmaid macOS build/sign/notarize helpers."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(ROOT))

import build_macos_app as build_release


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def _restore_env(old_values: dict[str, str | None]):
    for key, value in old_values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _codesign_args(**overrides):
    base = {
        "sign": True,
        "notarize": False,
        "codesign_identity": None,
        "codesign_entitlements": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _notary_args(**overrides):
    base = {
        "notarize": True,
        "notary_keychain_profile": None,
        "notary_keychain": None,
        "notary_apple_id": None,
        "notary_password": None,
        "notary_team_id": None,
        "notary_api_key": None,
        "notary_key_id": None,
        "notary_issuer": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def main():
    tracked_env = {
        build_release.CODESIGN_IDENTITY_ENV_VAR: os.environ.get(
            build_release.CODESIGN_IDENTITY_ENV_VAR
        ),
        build_release.CODESIGN_ENTITLEMENTS_ENV_VAR: os.environ.get(
            build_release.CODESIGN_ENTITLEMENTS_ENV_VAR
        ),
        build_release.NOTARY_KEYCHAIN_PROFILE_ENV_VAR: os.environ.get(
            build_release.NOTARY_KEYCHAIN_PROFILE_ENV_VAR
        ),
        build_release.NOTARY_KEYCHAIN_PATH_ENV_VAR: os.environ.get(
            build_release.NOTARY_KEYCHAIN_PATH_ENV_VAR
        ),
        build_release.NOTARY_APPLE_ID_ENV_VAR: os.environ.get(
            build_release.NOTARY_APPLE_ID_ENV_VAR
        ),
        build_release.NOTARY_PASSWORD_ENV_VAR: os.environ.get(
            build_release.NOTARY_PASSWORD_ENV_VAR
        ),
        build_release.NOTARY_TEAM_ID_ENV_VAR: os.environ.get(
            build_release.NOTARY_TEAM_ID_ENV_VAR
        ),
        build_release.NOTARY_API_KEY_ENV_VAR: os.environ.get(
            build_release.NOTARY_API_KEY_ENV_VAR
        ),
        build_release.NOTARY_KEY_ID_ENV_VAR: os.environ.get(
            build_release.NOTARY_KEY_ID_ENV_VAR
        ),
        build_release.NOTARY_ISSUER_ENV_VAR: os.environ.get(
            build_release.NOTARY_ISSUER_ENV_VAR
        ),
    }

    try:
        for key in tracked_env:
            os.environ.pop(key, None)

        identity = "Developer ID Application: Deskmaid Example (TEAMID1234)"
        os.environ[build_release.CODESIGN_IDENTITY_ENV_VAR] = identity
        codesign_settings = build_release._resolve_codesign_settings(_codesign_args())
        _assert(codesign_settings is not None, "expected codesign settings")
        _assert(
            codesign_settings.identity == identity,
            f"unexpected codesign identity: {codesign_settings.identity!r}",
        )
        _assert(
            codesign_settings.entitlements_path
            == build_release.DEFAULT_CODESIGN_ENTITLEMENTS_PATH.resolve(),
            f"expected default entitlements path, got: {codesign_settings.entitlements_path!r}",
        )

        with tempfile.TemporaryDirectory(prefix="deskmaid-entitlements-") as tmp_dir:
            entitlements_path = Path(tmp_dir) / "custom.entitlements"
            entitlements_path.write_text("<plist></plist>\n", encoding="utf-8")
            os.environ[build_release.CODESIGN_ENTITLEMENTS_ENV_VAR] = str(entitlements_path)
            explicit_codesign_settings = build_release._resolve_codesign_settings(
                _codesign_args()
            )
            _assert(
                explicit_codesign_settings is not None,
                "expected explicit codesign settings",
            )
            _assert(
                explicit_codesign_settings.entitlements_path == entitlements_path.resolve(),
                "expected env override entitlements path",
            )
            os.environ.pop(build_release.CODESIGN_ENTITLEMENTS_ENV_VAR, None)

        os.environ.pop(build_release.CODESIGN_IDENTITY_ENV_VAR, None)
        try:
            build_release._resolve_codesign_settings(_codesign_args())
        except RuntimeError as exc:
            _assert(
                build_release.CODESIGN_IDENTITY_ENV_VAR in str(exc),
                f"missing env hint in codesign error: {exc}",
            )
        else:
            _assert(False, "expected missing codesign identity to fail")

        try:
            build_release._resolve_notary_auth(_notary_args())
        except RuntimeError as exc:
            _assert(
                build_release.NOTARY_KEYCHAIN_PROFILE_ENV_VAR in str(exc),
                f"missing env hint in notary error: {exc}",
            )
        else:
            _assert(False, "expected missing notary auth to fail")

        os.environ[build_release.NOTARY_KEYCHAIN_PROFILE_ENV_VAR] = "deskmaid-notary"
        notary_auth = build_release._resolve_notary_auth(_notary_args())
        _assert(notary_auth is not None, "expected keychain-profile auth")
        _assert(
            notary_auth.mode == "keychain-profile",
            f"unexpected notary mode: {notary_auth.mode!r}",
        )
        _assert(
            "--keychain-profile" in notary_auth.args,
            f"missing keychain-profile args: {notary_auth.args!r}",
        )

        os.environ[build_release.NOTARY_APPLE_ID_ENV_VAR] = "maid@example.com"
        os.environ[build_release.NOTARY_PASSWORD_ENV_VAR] = "app-specific-password"
        os.environ[build_release.NOTARY_TEAM_ID_ENV_VAR] = "TEAMID1234"
        try:
            build_release._resolve_notary_auth(_notary_args())
        except RuntimeError as exc:
            _assert(
                "ambiguous" in str(exc).lower(),
                f"expected ambiguous auth error, got: {exc}",
            )
        else:
            _assert(False, "expected ambiguous notary auth to fail")

        os.environ.pop(build_release.NOTARY_KEYCHAIN_PROFILE_ENV_VAR, None)
        with tempfile.TemporaryDirectory(prefix="deskmaid-notary-key-") as tmp_dir:
            api_key_path = Path(tmp_dir) / "AuthKey_TEST123456.p8"
            api_key_path.write_text("test", encoding="utf-8")
            os.environ.pop(build_release.NOTARY_APPLE_ID_ENV_VAR, None)
            os.environ.pop(build_release.NOTARY_PASSWORD_ENV_VAR, None)
            os.environ.pop(build_release.NOTARY_TEAM_ID_ENV_VAR, None)
            os.environ[build_release.NOTARY_API_KEY_ENV_VAR] = str(api_key_path)
            os.environ[build_release.NOTARY_KEY_ID_ENV_VAR] = "TEST123456"
            os.environ[build_release.NOTARY_ISSUER_ENV_VAR] = "11111111-2222-3333-4444-555555555555"
            api_auth = build_release._resolve_notary_auth(_notary_args())
            _assert(api_auth is not None, "expected api-key auth")
            _assert(api_auth.mode == "api-key", f"unexpected api auth mode: {api_auth.mode!r}")
            _assert(
                str(api_key_path.resolve()) in api_auth.args,
                "expected api key path in auth args",
            )

        masked = build_release._format_command(
            ["xcrun", "notarytool", "submit", "--password", "super-secret"],
            secret_values=("super-secret",),
        )
        _assert("super-secret" not in masked, f"secret leaked in command: {masked}")
        _assert("******" in masked, f"expected masked marker in command: {masked}")

        archive_path = build_release._resolve_archive_path(None)
        _assert(
            archive_path == build_release.DEFAULT_NOTARY_ARCHIVE_PATH,
            f"unexpected default archive path: {archive_path}",
        )

        dmg_path = build_release._resolve_dmg_path(None)
        _assert(
            dmg_path == build_release.DEFAULT_DMG_PATH,
            f"unexpected default dmg path: {dmg_path}",
        )

        with tempfile.TemporaryDirectory(prefix="deskmaid-dmg-path-") as tmp_dir:
            custom_dmg = Path(tmp_dir) / "DeskMaid-custom.dmg"
            resolved_dmg = build_release._resolve_dmg_path(str(custom_dmg))
            _assert(
                resolved_dmg == custom_dmg.resolve(),
                f"unexpected custom dmg path: {resolved_dmg}",
            )
    finally:
        _restore_env(tracked_env)

    print("ok")


if __name__ == "__main__":
    main()
