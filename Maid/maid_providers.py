"""Multi-provider LLM presets for DeskMaid.

DeskMaid drives Claude through the Claude Agent SDK (the bundled ``claude`` CLI).
Several providers — DeepSeek, Moonshot/Kimi — ship **Anthropic-compatible**
endpoints, so the *same* Agent SDK can talk to them by pointing
``ANTHROPIC_BASE_URL`` at their gateway and authenticating with their key. This
module defines those presets and resolves the effective base_url / model /
subprocess-env for the active provider.

Design notes:
- The **Anthropic** provider keeps today's behaviour exactly: no base_url, no
  env override, the key flows through ``ANTHROPIC_API_KEY`` as before.
- A **third-party** provider only ever changes the *endpoint + key + model*. All
  of DeskMaid's tool / MCP / budget / memory machinery rides on top unchanged.
- Third-party model IDs drift over time, so ``models`` is only a suggestion list;
  the effective model is always user-editable via app-state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid an import cycle at runtime
    from maid_app_state import AppStateSnapshot

ANTHROPIC_PROVIDER_ID = "anthropic"
CUSTOM_PROVIDER_ID = "custom"

# Which subprocess env var carries a provider's key into the claude CLI.
AUTH_ENV_API_KEY = "ANTHROPIC_API_KEY"
AUTH_ENV_AUTH_TOKEN = "ANTHROPIC_AUTH_TOKEN"
_AUTH_ENVS = (AUTH_ENV_API_KEY, AUTH_ENV_AUTH_TOKEN)
BASE_URL_ENV = "ANTHROPIC_BASE_URL"


@dataclass(frozen=True)
class Provider:
    """A selectable LLM backend reachable through the Claude Agent SDK."""

    id: str
    name: str
    base_url: str          # "" → official Anthropic (no endpoint override)
    default_model: str
    models: tuple[str, ...] = ()      # suggested models for the picker (editable)
    auth_env: str = AUTH_ENV_API_KEY  # which env var the provider authenticates with
    key_env_var: str = ""             # env var an already-exported key may live in
    key_hint: str = ""                # where the user gets a key
    editable_endpoint: bool = False   # True only for the user-defined custom slot

    @property
    def is_anthropic(self) -> bool:
        return not self.base_url.strip()


# Built-in presets. DeepSeek and Kimi both publish Anthropic-compatible gateways
# intended for Claude Code; the base URLs below are their documented defaults —
# the custom slot exists for anything else (self-hosted relay, other gateway).
BUILTIN_PROVIDERS: tuple[Provider, ...] = (
    Provider(
        id=ANTHROPIC_PROVIDER_ID,
        name="Anthropic 官方",
        base_url="",
        default_model="claude-haiku-4-5",
        models=("claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-8"),
        auth_env=AUTH_ENV_API_KEY,
        key_env_var="ANTHROPIC_API_KEY",
        key_hint="console.anthropic.com",
    ),
    Provider(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/anthropic",
        default_model="deepseek-chat",
        models=("deepseek-chat", "deepseek-reasoner"),
        auth_env=AUTH_ENV_AUTH_TOKEN,
        key_env_var="DEEPSEEK_API_KEY",
        key_hint="platform.deepseek.com",
    ),
    Provider(
        id="kimi",
        name="Kimi（Moonshot）",
        base_url="https://api.moonshot.cn/anthropic",
        default_model="kimi-k2-0905-preview",
        models=("kimi-k2-0905-preview", "kimi-k2-turbo-preview"),
        auth_env=AUTH_ENV_AUTH_TOKEN,
        key_env_var="MOONSHOT_API_KEY",
        key_hint="platform.moonshot.cn",
    ),
)

_BUILTIN_BY_ID = {p.id: p for p in BUILTIN_PROVIDERS}


@dataclass(frozen=True)
class ResolvedProvider:
    """The concrete endpoint + model the chat path should use right now."""

    id: str
    name: str
    base_url: str
    model: str
    auth_env: str

    @property
    def is_anthropic(self) -> bool:
        return not self.base_url.strip()


def normalize_provider_id(value: object) -> str:
    text = str(value or "").strip().lower()
    if text == CUSTOM_PROVIDER_ID or text in _BUILTIN_BY_ID:
        return text
    return ANTHROPIC_PROVIDER_ID


def get_provider(provider_id: str) -> Provider | None:
    """Return the static preset for a built-in provider id (None for custom)."""
    return _BUILTIN_BY_ID.get(normalize_provider_id(provider_id))


def custom_provider_from_state(snapshot: "AppStateSnapshot") -> Provider:
    """Build the user-defined custom provider from app-state."""
    base_url = str(getattr(snapshot, "llm_custom_base_url", "") or "").strip()
    model = str(getattr(snapshot, "llm_custom_model", "") or "").strip()
    return Provider(
        id=CUSTOM_PROVIDER_ID,
        name="自定义",
        base_url=base_url,
        default_model=model,
        models=(),
        auth_env=AUTH_ENV_AUTH_TOKEN,
        editable_endpoint=True,
    )


def resolve_active_provider(snapshot: "AppStateSnapshot") -> ResolvedProvider:
    """Resolve the active provider + effective model from app-state.

    The per-provider model override (``llm_model``) wins when set; otherwise the
    preset's default model is used.
    """
    provider_id = normalize_provider_id(getattr(snapshot, "llm_provider_id", ""))
    if provider_id == CUSTOM_PROVIDER_ID:
        provider = custom_provider_from_state(snapshot)
    else:
        provider = _BUILTIN_BY_ID[provider_id]

    model = str(getattr(snapshot, "llm_model", "") or "").strip() or provider.default_model
    return ResolvedProvider(
        id=provider.id,
        name=provider.name,
        base_url=provider.base_url.strip(),
        model=model,
        auth_env=provider.auth_env,
    )


def build_subprocess_env(resolved: ResolvedProvider, key: str) -> dict[str, str]:
    """Env overrides to hand ``ClaudeAgentOptions(env=...)`` for this provider.

    Anthropic returns ``{}`` — the key already flows through the inherited
    ``ANTHROPIC_API_KEY`` exactly as before, so the default path is untouched.

    A third-party provider sets the endpoint + its auth var, and **neutralizes**
    the other Anthropic auth var so an inherited key can't shadow the token (the
    SDK merges ``{**os.environ, **options.env}`` with options.env winning).
    """
    key = str(key or "").strip()
    if resolved.is_anthropic:
        return {}

    env: dict[str, str] = {BASE_URL_ENV: resolved.base_url, resolved.auth_env: key}
    for other in _AUTH_ENVS:
        if other != resolved.auth_env:
            env[other] = ""  # blank so the underlying client treats it as unset
    return env
