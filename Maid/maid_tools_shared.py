"""Shared helpers for maid tool domains."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import subprocess

from maid_permission_recovery import tool_permission_recovery_message
from maid_privacy import sanitize_tool_payload_for_remote


def _format_error(exc) -> str:
    if exc is None:
        return ""
    try:
        detail = exc.localizedDescription()
    except Exception:
        detail = None
    if detail:
        return str(detail)
    return str(exc)


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _parse_time_range_value(value: str, *, end_of_day: bool) -> datetime:
    raw = str(value).strip()
    if not raw:
        raise ValueError("time range value is empty")

    normalized = raw.replace("Z", "+00:00")
    has_time = ("T" in raw) or (" " in raw)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid datetime value: {value!r}") from exc

    if parsed.tzinfo is None:
        local_tz = _local_now().tzinfo
        if has_time:
            parsed = parsed.replace(tzinfo=local_tz)
        elif end_of_day:
            parsed = parsed.replace(
                hour=23,
                minute=59,
                second=59,
                microsecond=999999,
                tzinfo=local_tz,
            )
        else:
            parsed = parsed.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
                tzinfo=local_tz,
            )
    return parsed


def _normalize_calendar_names(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raise ValueError("value must be a string or a list of strings")

    names: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _normalize_attachment_paths(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raise ValueError("attachments must be a string or a list of strings")

    paths: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        raw_path = str(item or "").strip()
        if not raw_path:
            continue
        candidate = Path(raw_path).expanduser()
        if not candidate.exists():
            raise FileNotFoundError(f"attachment file not found: {candidate}")
        if not candidate.is_file():
            raise ValueError(f"attachment path is not a file: {candidate}")
        resolved = str(candidate.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        paths.append(resolved)
    return paths


def _attachment_metadata_from_paths(paths: list[str] | None) -> list[dict[str, object]]:
    metadata: list[dict[str, object]] = []
    for raw_path in paths or []:
        path = Path(str(raw_path))
        size_bytes: int | None = None
        try:
            size_bytes = int(path.stat().st_size)
        except OSError:
            size_bytes = None
        metadata.append(
            {
                "name": path.name,
                "path": str(path),
                "size_bytes": size_bytes,
            }
        )
    return metadata


def _run_jxa_json(
    script: str,
    payload: dict[str, object],
    timeout_s: float = 20.0,
) -> dict[str, object]:
    proc = subprocess.run(
        [
            "osascript",
            "-l",
            "JavaScript",
            "-e",
            script,
            "--",
            json.dumps(payload, ensure_ascii=False),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(detail or f"osascript exited with code {proc.returncode}")

    stdout = proc.stdout.strip()
    if not stdout:
        raise RuntimeError("osascript returned no output")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"osascript returned invalid JSON: {stdout!r}") from exc


def _run_applescript(
    script: str,
    args: list[str] | None = None,
    timeout_s: float = 20.0,
) -> str:
    proc = subprocess.run(
        [
            "osascript",
            "-e",
            script,
            "--",
            *(args or []),
        ],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(detail or f"osascript exited with code {proc.returncode}")
    return (proc.stdout or "").strip()


def _normalize_optional_text(value) -> str | None:
    if value is None:
        return None
    return str(value).strip()


def _normalize_required_text(value, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _tool_success_result(tool_name: str, payload: dict[str, object]) -> dict:
    sanitized = sanitize_tool_payload_for_remote(payload)
    safe_payload = sanitized.value
    if not isinstance(safe_payload, dict):
        safe_payload = {"value": safe_payload}
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(safe_payload, ensure_ascii=False, indent=2, sort_keys=True),
            }
        ]
    }


def _tool_error_result(tool_name: str, exc: Exception) -> dict:
    detail = _format_error(exc) or str(exc)
    remediation = tool_permission_recovery_message(tool_name, detail)
    if remediation:
        text = (
            f"{tool_name} failed: {remediation}\n\n"
            f"raw error: {detail}"
        )
    else:
        text = f"{tool_name} failed: {detail}"
    return {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
        "is_error": True,
    }
