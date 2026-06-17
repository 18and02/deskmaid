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

# Third-party LLM provider keys share one keychain service, scoped by account=id.
ANTHROPIC_PROVIDER_ID = "anthropic"
LLM_KEY_KEYCHAIN_SERVICE = "com.regulus.deskmaid.llm_provider_key"


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


def _load_named_keychain(service: str, account: str) -> str | None:
    try:
        value = _run_security_command(
            ["find-generic-password", "-w", "-s", service, "-a", account]
        )
    except Exception:
        return None
    value = value.strip()
    return value or None


def _store_named_keychain(service: str, account: str, value: str):
    _run_security_command(
        ["add-generic-password", "-U", "-s", service, "-a", account, "-w", value]
    )


def _load_key_from_keychain() -> str | None:
    return _load_named_keychain(API_KEY_KEYCHAIN_SERVICE, API_KEY_KEYCHAIN_ACCOUNT)


def _store_key_in_keychain(value: str):
    _store_named_keychain(API_KEY_KEYCHAIN_SERVICE, API_KEY_KEYCHAIN_ACCOUNT, value)


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


# --- per-provider keys (DeepSeek / Kimi / custom) -------------------------------
#
# The Anthropic key keeps its dedicated env var, keychain service, and file path
# for backward compatibility. Third-party providers share one keychain service
# scoped by account=provider_id, with a per-provider sidecar file fallback.


def _safe_provider_id(provider_id: str) -> str:
    pid = str(provider_id or "").strip().lower()
    return pid or ANTHROPIC_PROVIDER_ID


LLM_KEY_DIR_ENV_VAR = "MAID_LLM_KEY_DIR"


def _provider_key_path(provider_id: str) -> Path:
    pid = _safe_provider_id(provider_id)
    if pid == ANTHROPIC_PROVIDER_ID:
        return _api_key_path()
    safe = "".join(c for c in pid if c.isalnum() or c in "-_") or "provider"
    override_dir = str(os.environ.get(LLM_KEY_DIR_ENV_VAR) or "").strip()
    if override_dir:
        return Path(override_dir).expanduser() / f".llm_key_{safe}"
    return default_state_path(f".llm_key_{safe}")


def _provider_keychain_coords(provider_id: str) -> tuple[str, str]:
    pid = _safe_provider_id(provider_id)
    if pid == ANTHROPIC_PROVIDER_ID:
        return API_KEY_KEYCHAIN_SERVICE, API_KEY_KEYCHAIN_ACCOUNT
    return LLM_KEY_KEYCHAIN_SERVICE, pid


def _provider_uses_keychain(provider_id: str) -> bool:
    pid = _safe_provider_id(provider_id)
    if pid == ANTHROPIC_PROVIDER_ID:
        return _should_use_keychain(_api_key_path())
    if sys.platform != "darwin":
        return False
    mode = _keychain_mode()
    if mode in {"0", "false", "off", "no", "sidecar", "file"}:
        return False
    return True  # default to keychain on macOS for provider keys too


def load_provider_key(provider_id: str, *, env_var: str = "") -> str | None:
    """Resolve a provider's key: explicit env var → keychain → sidecar file."""
    pid = _safe_provider_id(provider_id)
    ev = str(env_var or "").strip() or (
        API_KEY_ENV_VAR if pid == ANTHROPIC_PROVIDER_ID else ""
    )
    if ev:
        value = str(os.environ.get(ev) or "").strip()
        if value:
            return value
    if _provider_uses_keychain(pid):
        service, account = _provider_keychain_coords(pid)
        value = _load_named_keychain(service, account)
        if value:
            return value
    return _load_key_from_file(_provider_key_path(pid))


def provider_key_status(provider_id: str, *, env_var: str = "") -> ApiKeyStatus:
    pid = _safe_provider_id(provider_id)
    ev = str(env_var or "").strip() or (
        API_KEY_ENV_VAR if pid == ANTHROPIC_PROVIDER_ID else ""
    )
    if ev:
        value = str(os.environ.get(ev) or "").strip()
        if value:
            return ApiKeyStatus(
                configured=True,
                source="env",
                summary=f"当前已从环境变量 {ev} 拿到该服务商的 key。",
                masked_value=_mask_api_key(value),
            )
    if _provider_uses_keychain(pid):
        service, account = _provider_keychain_coords(pid)
        value = _load_named_keychain(service, account)
        if value:
            return ApiKeyStatus(
                configured=True,
                source="keychain",
                summary="当前已在系统钥匙串里保存该服务商的 key。",
                masked_value=_mask_api_key(value),
            )
    value = _load_key_from_file(_provider_key_path(pid))
    if value:
        return ApiKeyStatus(
            configured=True,
            source="file",
            summary="当前已在本机私有文件里保存该服务商的 key。",
            masked_value=_mask_api_key(value),
        )
    return ApiKeyStatus(configured=False, summary="还没有配置该服务商的 key。")


def save_provider_key(provider_id: str, value: str, *, env_var: str = "") -> ApiKeyStatus:
    pid = _safe_provider_id(provider_id)
    if pid == ANTHROPIC_PROVIDER_ID:
        return save_api_key(value)

    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("API key 不能为空。")

    if _provider_uses_keychain(pid):
        service, account = _provider_keychain_coords(pid)
        try:
            _store_named_keychain(service, account, normalized)
        except Exception as exc:
            raise RuntimeError(f"写入系统钥匙串失败: {exc}") from exc
    else:
        _store_key_in_file(_provider_key_path(pid), normalized)

    ev = str(env_var or "").strip()
    if ev:
        os.environ[ev] = normalized
    return provider_key_status(pid, env_var=ev)
