#!/usr/bin/env python3
"""Developer command entry for Deskmaid backend checks.

Usage:
    ./dev_checks.py
    ./dev_checks.py list
    ./dev_checks.py quick
    ./dev_checks.py daily
    ./dev_checks.py packaged
    ./dev_checks.py signed
    ./dev_checks.py notarize
    ./dev_checks.py tcc
    ./dev_checks.py full
    .venv/bin/python -u dev_checks.py list
    .venv/bin/python -u dev_checks.py quick
    .venv/bin/python -u dev_checks.py desktop
    .venv/bin/python -u dev_checks.py apple
    .venv/bin/python -u dev_checks.py packaged
    .venv/bin/python -u dev_checks.py signed
    .venv/bin/python -u dev_checks.py notarize
    .venv/bin/python -u dev_checks.py tcc
    .venv/bin/python -u dev_checks.py core
    .venv/bin/python -u dev_checks.py apple --send-mail-to someone@example.com
    .venv/bin/python -u dev_checks.py core --send-mail-to someone@example.com

Profiles:
    quick    Daily quick check: permission health + desktop regression
    desktop  Desktop input / bridge regression
    apple    Calendar / Reminders / Mail regression
    packaged Build Deskmaid.app and run packaged health verification
    signed   Build Deskmaid.app, codesign it, and verify the signature
    notarize Build Deskmaid.app, build DeskMaid.dmg, notarize release artifacts, staple them, and verify Gatekeeper
    tcc      Packaged .app TCC regression with launch + checklist
    core     Full core health/regression suite

Aliases:
    daily -> quick
    smoke -> quick
    apps  -> apple
    bundle -> packaged
    release-sign -> signed
    release -> notarize
    ship -> notarize
    realmachine -> tcc
    full  -> core
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO_VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(REPO_VENV_PYTHON) if REPO_VENV_PYTHON.is_file() else sys.executable
DEFAULT_PROFILE = "quick"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

PROFILE_CASES: dict[str, tuple[str, tuple[tuple[str, ...], ...]]] = {
    "quick": (
        "Daily quick check: permission health + desktop regression",
        (
            ("permission_health", "Maid/test_permission_health.py"),
            ("desktop_input_regression", "Maid/test_desktop_input_regression.py"),
        ),
    ),
    "desktop": (
        "Desktop input / bridge regression",
        (
            ("desktop_input_regression", "Maid/test_desktop_input_regression.py"),
        ),
    ),
    "apple": (
        "Calendar / Reminders / Mail regression",
        (
            ("apple_apps_regression", "Maid/test_apple_apps_regression.py"),
        ),
    ),
    "packaged": (
        "Build Deskmaid.app and run packaged health verification",
        (
            ("packaged_health", "build_macos_app.py", "--verify-health"),
        ),
    ),
    "signed": (
        "Build Deskmaid.app, codesign it, and verify the signature",
        (
            (
                "signed_bundle",
                "build_macos_app.py",
                "--verify-health",
                "--sign",
                "--verify-signature",
            ),
        ),
    ),
    "notarize": (
        "Build Deskmaid.app, build DeskMaid.dmg, notarize release artifacts, staple them, and verify Gatekeeper",
        (
            (
                "notarized_bundle",
                "build_macos_app.py",
                "--verify-health",
                "--notarize",
                "--verify-gatekeeper",
                "--dmg",
            ),
        ),
    ),
    "tcc": (
        "Packaged .app TCC regression with launch + checklist",
        (
            ("packaged_tcc_regression", "Maid/test_packaged_tcc_regression.py"),
        ),
    ),
    "core": (
        "Full core health/regression suite",
        (
            ("core_health_regression", "Maid/test_core_health_regression.py"),
        ),
    ),
}

PROFILE_ALIASES: dict[str, str] = {
    "daily": "quick",
    "smoke": "quick",
    "apps": "apple",
    "bundle": "packaged",
    "release-sign": "signed",
    "release": "notarize",
    "ship": "notarize",
    "realmachine": "tcc",
    "full": "core",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Deskmaid developer check profiles.",
    )
    parser.add_argument(
        "profile",
        nargs="?",
        default=DEFAULT_PROFILE,
        help=(
            "Which check profile to run. "
            f"Defaults to {DEFAULT_PROFILE}. Use 'list' to show profiles."
        ),
    )
    parser.add_argument(
        "--send-mail-to",
        dest="send_mail_to",
        help=(
            "Enable send_mail_draft coverage by forwarding this recipient as "
            "DESKMAID_SEND_MAIL_TEST_TO."
        ),
    )
    return parser


def _print_profiles():
    print(f"Default profile: {DEFAULT_PROFILE}")
    print("Available profiles:")
    for name, (description, cases) in PROFILE_CASES.items():
        labels = ", ".join(case[0] for case in cases)
        print(f"- {name}: {description}")
        print(f"  cases: {labels}")
    print("Aliases:")
    for alias, canonical in PROFILE_ALIASES.items():
        print(f"- {alias}: alias of {canonical}")
    print("- list: show this help summary")


def _resolve_profile(profile: str) -> tuple[str, str | None]:
    if profile == "list":
        return profile, None
    if profile in PROFILE_CASES:
        return profile, None
    if profile in PROFILE_ALIASES:
        return PROFILE_ALIASES[profile], profile
    valid_names = ["list", *PROFILE_CASES.keys(), *PROFILE_ALIASES.keys()]
    raise ValueError(f"unknown profile {profile!r}; expected one of: {', '.join(valid_names)}")


def _run_case(
    label: str,
    rel_path: str,
    *,
    extra_args: tuple[str, ...] = (),
    send_mail_to: str | None = None,
) -> tuple[int, float]:
    path = ROOT / rel_path
    if not path.is_file():
        print(f"[error] missing script for {label}: {path}", file=sys.stderr)
        return 1, 0.0

    cmd = [PYTHON, "-u", str(path), *extra_args]
    print(f"\n=== {label} :: start ===")
    print(f"[cmd] {' '.join(cmd)}")
    started = time.monotonic()

    env = dict(os.environ)
    if send_mail_to:
        env["DESKMAID_SEND_MAIL_TEST_TO"] = send_mail_to

    with tempfile.TemporaryDirectory(prefix=f"deskmaid-dev-{label}-") as tmp_dir:
        env["MAID_SESSION_STATE_PATH"] = str(Path(tmp_dir) / "session_state.json")
        env["MAID_APP_STATE_PATH"] = str(Path(tmp_dir) / "app_state.json")
        env["MAID_BUDGET_STATE_PATH"] = str(Path(tmp_dir) / "budget_state.json")
        completed = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            check=False,
        )

    duration_s = time.monotonic() - started
    print(
        f"=== {label} :: {'ok' if completed.returncode == 0 else 'failed'} "
        f"({duration_s:.2f}s) ==="
    )
    return completed.returncode, duration_s


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        profile, alias_used = _resolve_profile(args.profile)
    except ValueError as exc:
        parser.error(str(exc))

    if profile == "list":
        _print_profiles()
        return 0

    description, cases = PROFILE_CASES[profile]
    print(f"[profile] {profile}: {description}")
    if alias_used:
        print(f"[profile] alias {alias_used} -> {profile}")
    if args.send_mail_to:
        print(f"[profile] send_mail_draft enabled -> {args.send_mail_to}")
    else:
        print("[profile] send_mail_draft stays in opt-in mode")

    failures: list[str] = []
    started = time.monotonic()

    for case in cases:
        label, rel_path, *extra_args = case
        returncode, _ = _run_case(
            label,
            rel_path,
            extra_args=tuple(extra_args),
            send_mail_to=args.send_mail_to,
        )
        if returncode != 0:
            failures.append(label)

    total_duration_s = time.monotonic() - started
    if failures:
        print(
            f"\n[error] profile {profile} failed: {', '.join(failures)} "
            f"(total {total_duration_s:.2f}s)",
            file=sys.stderr,
        )
        return 1

    print(
        f"\n[ok] profile {profile} passed "
        f"(total {total_duration_s:.2f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
