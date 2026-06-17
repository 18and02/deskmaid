"""Tests for multi-provider LLM support (presets, env resolution, per-provider keys).

DeskMaid routes third-party providers (DeepSeek / Kimi / custom) through their
Anthropic-compatible endpoints on the same Claude Agent SDK. This covers the
pure resolution logic, the subprocess-env override, per-provider key storage,
and app-state persistence.

Usage:
    .venv/bin/python -u Maid/test_llm_providers.py
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_providers import (
    AUTH_ENV_API_KEY,
    AUTH_ENV_AUTH_TOKEN,
    BASE_URL_ENV,
    build_subprocess_env,
    get_provider,
    resolve_active_provider,
)


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


class _FakeSnapshot:
    def __init__(self, **kw):
        self.llm_provider_id = kw.get("llm_provider_id", "anthropic")
        self.llm_model = kw.get("llm_model", "")
        self.llm_custom_base_url = kw.get("llm_custom_base_url", "")
        self.llm_custom_model = kw.get("llm_custom_model", "")


def test_resolve_provider():
    anth = resolve_active_provider(_FakeSnapshot())
    _assert(anth.is_anthropic, f"default should be anthropic: {anth!r}")
    _assert(anth.model == "claude-haiku-4-5", f"default model should be haiku: {anth!r}")

    # per-provider model override wins
    over = resolve_active_provider(_FakeSnapshot(llm_provider_id="anthropic", llm_model="claude-opus-4-8"))
    _assert(over.model == "claude-opus-4-8", f"override should win: {over!r}")

    ds = resolve_active_provider(_FakeSnapshot(llm_provider_id="deepseek"))
    _assert(not ds.is_anthropic, "deepseek is third-party")
    _assert(ds.base_url == "https://api.deepseek.com/anthropic", f"unexpected base_url: {ds!r}")
    _assert(ds.model == "deepseek-chat", f"deepseek default model: {ds!r}")
    _assert(ds.auth_env == AUTH_ENV_AUTH_TOKEN, f"deepseek auth env: {ds!r}")

    kimi = resolve_active_provider(_FakeSnapshot(llm_provider_id="kimi", llm_model="kimi-custom"))
    _assert(kimi.base_url.endswith("/anthropic"), f"kimi base_url: {kimi!r}")
    _assert(kimi.model == "kimi-custom", f"kimi model override: {kimi!r}")

    custom = resolve_active_provider(
        _FakeSnapshot(
            llm_provider_id="custom",
            llm_custom_base_url="https://relay.example.com/anthropic",
            llm_custom_model="my-model",
        )
    )
    _assert(custom.id == "custom", f"custom id: {custom!r}")
    _assert(custom.base_url == "https://relay.example.com/anthropic", f"custom base_url: {custom!r}")
    _assert(custom.model == "my-model", f"custom model: {custom!r}")

    # unknown / blank provider id falls back to anthropic
    junk = resolve_active_provider(_FakeSnapshot(llm_provider_id="nope"))
    _assert(junk.is_anthropic, f"unknown provider should fall back: {junk!r}")


def test_build_env():
    anth = resolve_active_provider(_FakeSnapshot())
    _assert(build_subprocess_env(anth, "sk-ant-xxx") == {}, "anthropic env must stay empty")

    ds = resolve_active_provider(_FakeSnapshot(llm_provider_id="deepseek"))
    env = build_subprocess_env(ds, "ds-key-123")
    _assert(env.get(BASE_URL_ENV) == "https://api.deepseek.com/anthropic", f"base_url env: {env!r}")
    _assert(env.get(AUTH_ENV_AUTH_TOKEN) == "ds-key-123", f"auth token env: {env!r}")
    _assert(env.get(AUTH_ENV_API_KEY) == "", "inherited ANTHROPIC_API_KEY must be neutralized to empty")

    # custom with no base_url is still treated as third-party only if base_url set;
    # a blank custom base_url collapses to "anthropic-like" empty env.
    blank_custom = resolve_active_provider(_FakeSnapshot(llm_provider_id="custom"))
    _assert(build_subprocess_env(blank_custom, "k") == {}, "blank custom base_url → empty env")


def test_provider_presets():
    _assert(get_provider("deepseek").key_env_var == "DEEPSEEK_API_KEY", "deepseek env hint")
    _assert(get_provider("kimi").key_env_var == "MOONSHOT_API_KEY", "kimi env hint")
    _assert(get_provider("custom") is None, "custom has no static preset")


def test_provider_key_store():
    import maid_api_key as keystore

    with tempfile.TemporaryDirectory(prefix="deskmaid-keys-") as tmp:
        os.environ["MAID_API_KEYCHAIN_MODE"] = "file"  # no real keychain in tests
        os.environ["MAID_LLM_KEY_DIR"] = tmp
        os.environ["MAID_API_KEY_PATH"] = str(Path(tmp) / ".anthropic_api_key")
        os.environ.pop("DEEPSEEK_API_KEY", None)

        st = keystore.provider_key_status("deepseek", env_var="DEEPSEEK_API_KEY")
        _assert(not st.configured, "deepseek key should start unconfigured")
        _assert(keystore.load_provider_key("deepseek", env_var="DEEPSEEK_API_KEY") is None, "no key yet")

        keystore.save_provider_key("deepseek", "ds-secret-789", env_var="DEEPSEEK_API_KEY")
        # clear the env the save set, to prove it persisted to the sidecar file
        os.environ.pop("DEEPSEEK_API_KEY", None)
        loaded = keystore.load_provider_key("deepseek", env_var="DEEPSEEK_API_KEY")
        _assert(loaded == "ds-secret-789", f"deepseek key should persist to file: {loaded!r}")

        st2 = keystore.provider_key_status("deepseek", env_var="DEEPSEEK_API_KEY")
        _assert(st2.configured and st2.source == "file", f"status should report file: {st2!r}")

        # env var takes precedence over stored file
        os.environ["DEEPSEEK_API_KEY"] = "ds-from-env"
        _assert(
            keystore.load_provider_key("deepseek", env_var="DEEPSEEK_API_KEY") == "ds-from-env",
            "env var should win over stored key",
        )
        os.environ.pop("DEEPSEEK_API_KEY", None)

        # provider keys are isolated from each other
        _assert(
            keystore.load_provider_key("kimi", env_var="MOONSHOT_API_KEY") is None,
            "kimi key must be independent of deepseek",
        )


def test_app_state_persistence():
    import maid_app_state as st

    with tempfile.TemporaryDirectory(prefix="deskmaid-appstate-") as tmp:
        os.environ["MAID_APP_STATE_PATH"] = str(Path(tmp) / "app_state.json")
        store = st.AppStateStore()

        snap = store.set_llm_preferences(provider_id="deepseek", model="deepseek-reasoner")
        _assert(snap.llm_provider_id == "deepseek", f"provider persisted: {snap!r}")
        _assert(snap.llm_model == "deepseek-reasoner", f"model persisted: {snap!r}")

        # an UNRELATED setter must not reset the llm fields (the replace_all hazard)
        snap2 = store.set_do_not_disturb(True)
        _assert(snap2.llm_provider_id == "deepseek", "do-not-disturb wiped provider!")
        _assert(snap2.llm_model == "deepseek-reasoner", "do-not-disturb wiped model!")

        # the reminder setter (the one replace_all skipped) must preserve llm too
        snap3 = store.set_reminder_preferences(
            reminders_enabled=True,
            water_reminder_enabled=True,
            water_reminder_minutes=30,
            activity_reminder_enabled=True,
            activity_reminder_minutes=60,
            custom_reminder_enabled=False,
            custom_reminder_minutes=30,
            custom_reminder_text="x",
        )
        _assert(snap3.llm_provider_id == "deepseek", "reminder setter wiped provider!")
        _assert(snap3.llm_model == "deepseek-reasoner", "reminder setter wiped model!")

        # reload from disk round-trips
        reloaded = st.load_app_state_snapshot(Path(os.environ["MAID_APP_STATE_PATH"]))
        _assert(reloaded.llm_provider_id == "deepseek", f"reload provider: {reloaded!r}")
        _assert(reloaded.llm_model == "deepseek-reasoner", f"reload model: {reloaded!r}")


def main():
    test_resolve_provider()
    test_build_env()
    test_provider_presets()
    test_provider_key_store()
    test_app_state_persistence()
    print("ok")


if __name__ == "__main__":
    main()
