"""Local API key loading and storage helpers for Deskmaid."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

from maid_paths import default_state_path


API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
API_KEY_PATH_ENV_VAR = "MAID_API_KEY_PATH"
API_KEY_KEYCHAIN_MODE_ENV_VAR = "MAID_API_KEYCHAIN_MODE"
API_KEY_KEYCHAIN_SERVICE = "com.regulus.deskmaid.anthropic_api_key"
API_KEY_KEYCHAIN_ACCOUNT = "default"
DEFAULT_API_KEY_PATH = default_state_path(".anthropic_api_key")


@dataclass(frozen=True)
class ApiKeyStatus:
    configured: bool
    source: str = ""
    summary: str = ""
    masked_value: str = ""


def _api_key_path() -> Path:
    override = str(os.environ.get(API_KEY_PATH_ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_API_KEY_PATH


def _keychain_mode() -> str:
    return str(os.environ.get(API_KEY_KEYCHAIN_MODE_ENV_VAR) or "").strip().lower()


def _should_use_keychain(path: Path) -> bool:
    if sys.platform != "darwin":
        return False

    mode = _keychain_mode()
    if mode in {"0", "false", "off", "no", "sidecar", "file"}:
        return False
    if mode in {"1", "true", "on", "yes", "keychain"}:
        return True

    try:
        return path.expanduser().resolve() == DEFAULT_API_KEY_PATH.resolve()
    except OSError:
        return path.expanduser() == DEFAULT_API_KEY_PATH


def _write_private_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _run_security_command(args: list[str]) -> str:
    proc = subprocess.run(
        ["security", *args],
        capture_output=True,
        text=True,
        timeout=8.0,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(detail or f"security exited with code {proc.returncode}")
    return (proc.stdout or "").strip()


def _load_key_from_keychain() -> str | None:
    try:
        value = _run_security_command(
            [
                "find-generic-password",
                "-w",
                "-s",
                API_KEY_KEYCHAIN_SERVICE,
                "-a",
                API_KEY_KEYCHAIN_ACCOUNT,
            ]
        )
    except Exception:
        return None
    value = value.strip()
    return value or None


def _store_key_in_keychain(value: str):
    _run_security_command(
        [
            "add-generic-password",
            "-U",
            "-s",
            API_KEY_KEYCHAIN_SERVICE,
            "-a",
            API_KEY_KEYCHAIN_ACCOUNT,
            "-w",
            value,
        ]
    )


def _load_key_from_file(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeError(f"读取 API key 文件失败: {exc}") from exc
    return value or None


def _store_key_in_file(path: Path, value: str):
    try:
        _write_private_text(path, value + "\n")
    except OSError as exc:
        raise RuntimeError(f"写入 API key 文件失败: {exc}") from exc


def _mask_api_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


def _runtime_api_key() -> str | None:
    value = str(os.environ.get(API_KEY_ENV_VAR) or "").strip()
    return value or None


def _saved_api_key() -> tuple[str | None, str]:
    path = _api_key_path()
    if _should_use_keychain(path):
        value = _load_key_from_keychain()
        if value:
            return value, "keychain"
    value = _load_key_from_file(path)
    if value:
        return value, "file"
    return None, ""


def api_key_status() -> ApiKeyStatus:
    value = _runtime_api_key()
    if value:
        return ApiKeyStatus(
            configured=True,
            source="env",
            summary="当前已从环境变量拿到 Claude API key。",
            masked_value=_mask_api_key(value),
        )

    value, source = _saved_api_key()
    if value:
        if source == "keychain":
            summary = "当前已在系统钥匙串里保存 Claude API key。"
        else:
            summary = "当前已在本机私有文件里保存 Claude API key。"
        return ApiKeyStatus(
            configured=True,
            source=source,
            summary=summary,
            masked_value=_mask_api_key(value),
        )

    return ApiKeyStatus(
        configured=False,
        summary="还没有配置 Claude API key。现在只能开壳，聊不了天。",
    )


def ensure_runtime_api_key() -> str | None:
    value = _runtime_api_key()
    if value:
        return value

    value, _source = _saved_api_key()
    if value:
        os.environ[API_KEY_ENV_VAR] = value
        return value
    return None


def save_api_key(value: str) -> ApiKeyStatus:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("API key 不能为空。")

    path = _api_key_path()
    if _should_use_keychain(path):
        try:
            _store_key_in_keychain(normalized)
        except Exception as exc:
            raise RuntimeError(f"写入系统钥匙串失败: {exc}") from exc
    else:
        _store_key_in_file(path, normalized)

    os.environ[API_KEY_ENV_VAR] = normalized
    return api_key_status()
