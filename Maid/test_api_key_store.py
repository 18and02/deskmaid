"""Smoke test for Deskmaid API key storage helpers.

Usage:
    .venv/bin/python -u Maid/test_api_key_store.py
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maid_api_key import (
    API_KEY_ENV_VAR,
    API_KEY_KEYCHAIN_MODE_ENV_VAR,
    API_KEY_PATH_ENV_VAR,
    api_key_status,
    ensure_runtime_api_key,
    save_api_key,
)


TEST_KEY = "sk-ant-api03-test-1234567890"


def _assert(condition: bool, message: str):
    if not condition:
        print(f"[error] {message}", file=sys.stderr)
        sys.exit(1)


def main():
    old_values = {
        API_KEY_ENV_VAR: os.environ.get(API_KEY_ENV_VAR),
        API_KEY_KEYCHAIN_MODE_ENV_VAR: os.environ.get(API_KEY_KEYCHAIN_MODE_ENV_VAR),
        API_KEY_PATH_ENV_VAR: os.environ.get(API_KEY_PATH_ENV_VAR),
    }

    with tempfile.TemporaryDirectory(prefix="deskmaid-api-key-") as tmp_dir:
        path = Path(tmp_dir) / "anthropic_api_key.txt"
        try:
            os.environ.pop(API_KEY_ENV_VAR, None)
            os.environ[API_KEY_KEYCHAIN_MODE_ENV_VAR] = "sidecar"
            os.environ[API_KEY_PATH_ENV_VAR] = str(path)

            empty_status = api_key_status()
            _assert(not empty_status.configured, "expected empty API key state")

            saved_status = save_api_key(TEST_KEY)
            _assert(saved_status.configured, "expected saved API key to be configured")
            _assert(path.is_file(), "expected sidecar API key file to exist")
            _assert(path.read_text(encoding="utf-8").strip() == TEST_KEY, "expected saved key text")

            os.environ.pop(API_KEY_ENV_VAR, None)
            file_status = api_key_status()
            _assert(file_status.configured, "expected stored API key to be discoverable")
            _assert(file_status.source == "file", f"unexpected stored source: {file_status.source!r}")

            loaded = ensure_runtime_api_key()
            _assert(loaded == TEST_KEY, "expected ensure_runtime_api_key to load saved key")
            env_status = api_key_status()
            _assert(env_status.configured, "expected env-backed API key state after runtime load")
            _assert(env_status.source == "env", f"unexpected runtime source: {env_status.source!r}")
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    print("ok")


if __name__ == "__main__":
    main()
