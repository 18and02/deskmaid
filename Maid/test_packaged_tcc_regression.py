"""Packaged .app TCC regression entry for Deskmaid.

Usage:
    .venv/bin/python -u Maid/test_packaged_tcc_regression.py
    .venv/bin/python -u Maid/test_packaged_tcc_regression.py --skip-build
    .venv/bin/python -u Maid/test_packaged_tcc_regression.py --skip-launch
    .venv/bin/python -u Maid/test_packaged_tcc_regression.py --json

This runner goes one step beyond the bundle-only health check:
- optionally rebuilds Deskmaid.app and reruns bundled health
- verifies the packaged executable path exists
- optionally launches the built app via Launch Services
- prints a fixed real-machine TCC checklist for the remaining manual passes
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent.parent
REPO_VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(REPO_VENV_PYTHON) if REPO_VENV_PYTHON.is_file() else sys.executable
BUILD_SCRIPT = ROOT / "build_macos_app.py"
APP_PATH = ROOT / "dist" / "Deskmaid.app"
APP_EXECUTABLE = APP_PATH / "Contents" / "MacOS" / "Deskmaid"

MANUAL_CHECKLIST: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "首启引导",
        (
            "从 .app 正常启动后，确认会出现首启引导，且能填写 API key、主人称呼、预算档位、数据边界确认。",
            "把称呼清空并保存一次，确认会恢复成默认“主人”，不会残留旧自定义称呼。",
            "切换预算档位后重开引导，确认档位会被记住。",
        ),
    ),
    (
        "权限正向链路",
        (
            "在应用里打开 Permission health，确认 bundle runtime / TCC metadata / Accessibility / Calendar / Reminders / Mail 都能得到明确状态。",
            "分别走一次 Calendar / Reminders / Mail 主链路，确认系统授权框、权限弹窗、成功回执三者都正常出现。",
        ),
    ),
    (
        "权限负向链路",
        (
            "关闭或重置某项 Automation / Accessibility 授权后，再触发对应工具，确认失败提示会明确指出系统设置路径，并提示回到 Permission health 刷新一次，不会卡死。",
            "在 Permission health 里确认最上面会出现“恢复向导”卡，且能直接点开辅助功能 / 自动化设置页，再回来刷新。",
            "确认高风险写操作仍保留人工确认，而不是因为打包后变成静默执行。",
        ),
    ),
    (
        "场景感知",
        (
            "在共享屏幕、浏览器分享标签页、QuickTime/录屏工具活跃时，确认自动免打扰会生效；若打开了自动隐藏，立绘也会自动消失并在结束后恢复。",
        ),
    ),
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run packaged Deskmaid.app TCC regression checks.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="reuse the existing dist/Deskmaid.app instead of rebuilding it first",
    )
    parser.add_argument(
        "--skip-launch",
        action="store_true",
        help="skip Launch Services open() verification and only print the checklist",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the final report as JSON",
    )
    return parser


def _run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _deskmaid_processes() -> list[dict[str, object]]:
    proc = _run_command(["ps", "-axo", "pid=,command="])
    rows: list[dict[str, object]] = []
    if proc.returncode != 0:
        return rows

    target = str(APP_EXECUTABLE)
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid_text, command = line.split(None, 1)
        except ValueError:
            continue
        if target not in command:
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        rows.append({"pid": pid, "command": command})
    return rows


def _check_bundle_paths() -> dict[str, object]:
    ok = APP_PATH.is_dir() and APP_EXECUTABLE.is_file()
    summary = "打包后的 .app 与主可执行文件都在" if ok else "打包产物不完整"
    detail = (
        f"app={APP_PATH}\nexecutable={APP_EXECUTABLE}"
    )
    return {
        "key": "bundle_paths",
        "status": "ok" if ok else "error",
        "summary": summary,
        "detail": detail,
    }


def _run_packaged_health(skip_build: bool) -> dict[str, object]:
    cmd = [PYTHON, "-u", str(BUILD_SCRIPT)]
    if skip_build:
        cmd.append("--skip-build")
    cmd.append("--verify-health")
    proc = _run_command(cmd)
    ok = proc.returncode == 0
    summary = "build_macos_app.py --verify-health 通过" if ok else "packaged health 失败"
    detail_parts = [f"cmd={' '.join(cmd)}"]
    if proc.stdout.strip():
        detail_parts.append(proc.stdout.strip())
    if proc.stderr.strip():
        detail_parts.append(proc.stderr.strip())
    return {
        "key": "packaged_health",
        "status": "ok" if ok else "error",
        "summary": summary,
        "detail": "\n\n".join(detail_parts),
    }


def _launch_packaged_app() -> dict[str, object]:
    before = {int(row["pid"]) for row in _deskmaid_processes()}
    proc = _run_command(["open", str(APP_PATH)])
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "open returned a non-zero exit code"
        return {
            "key": "launch_services_open",
            "status": "error",
            "summary": "open Deskmaid.app 失败",
            "detail": detail,
        }

    deadline = time.time() + 8.0
    observed: list[dict[str, object]] = []
    while time.time() < deadline:
        observed = _deskmaid_processes()
        if observed:
            break
        time.sleep(0.4)

    if not observed:
        return {
            "key": "launch_services_open",
            "status": "error",
            "summary": "Launch Services 没把 Deskmaid 拉起来",
            "detail": f"open {APP_PATH} returned 0, but no packaged process appeared within 8s.",
        }

    after = {int(row["pid"]) for row in observed}
    new_pids = sorted(after - before)
    if new_pids:
        summary = f"Deskmaid.app 已启动（新进程: {', '.join(str(pid) for pid in new_pids)}）"
    else:
        summary = "Deskmaid.app 已经在运行，Launch Services 复用了现有实例"
    return {
        "key": "launch_services_open",
        "status": "ok",
        "summary": summary,
        "detail": "\n".join(str(row["command"]) for row in observed[:3]),
    }


def _render_text_report(report: dict[str, object]):
    checks = list(report.get("checks") or [])
    print(
        f"[summary] ok={report.get('ok_count', 0)} "
        f"error={report.get('error_count', 0)}"
    )
    for check in checks:
        print(
            f"- {check['key']}: {check['status']} :: {check['summary']}"
        )
    print("\n[manual] 真实 TCC 回归清单")
    for title, steps in MANUAL_CHECKLIST:
        print(f"* {title}")
        for index, step in enumerate(steps, start=1):
            print(f"  {index}. {step}")


def main():
    args = _build_parser().parse_args()

    checks = [_run_packaged_health(skip_build=args.skip_build), _check_bundle_paths()]
    if not args.skip_launch and all(check["status"] == "ok" for check in checks):
        checks.append(_launch_packaged_app())

    ok_count = sum(1 for check in checks if check["status"] == "ok")
    error_count = sum(1 for check in checks if check["status"] == "error")
    report = {
        "checks": checks,
        "ok_count": ok_count,
        "error_count": error_count,
        "manual_checklist": [
            {
                "title": title,
                "steps": list(steps),
            }
            for title, steps in MANUAL_CHECKLIST
        ],
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _render_text_report(report)

    if error_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
