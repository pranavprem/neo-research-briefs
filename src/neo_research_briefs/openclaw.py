"""OpenClaw-specific convenience helpers.

The watcher itself is OpenClaw-agnostic, but operators frequently want a
ready-to-paste cron job and a small wrapper command that another
OpenClaw can run without remembering Python module paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_runner_command(
    repo_dir: Path,
    *,
    env_file: Path | None = None,
    dry_run: bool | None = None,
    json_out: bool = True,
) -> str:
    """Return the command another OpenClaw should run inside ``repo_dir``."""
    parts = ["bash", "scripts/run_neo_briefs.sh"]
    if env_file is not None:
        parts.extend(["--env-file", _shell_quote(str(env_file))])
    if json_out:
        parts.append("--json")
    parts.append("run-once")
    if dry_run is True:
        parts.append("--dry-run")
    elif dry_run is False:
        parts.append("--no-dry-run")
    return " ".join(parts)


def build_cron_job(
    repo_dir: Path,
    *,
    env_file: Path | None = None,
    every_minutes: int = 5,
    session_target: str = "isolated",
    delivery_mode: str = "none",
    job_name: str = "research-brief-intake",
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """Build an OpenClaw cron job object for the watcher."""
    if every_minutes < 1:
        raise ValueError("every_minutes must be >= 1")

    repo_dir = repo_dir.expanduser().resolve()
    env_file = env_file.expanduser().resolve() if env_file is not None else None
    command = build_runner_command(repo_dir, env_file=env_file, dry_run=dry_run, json_out=True)
    shell_command = f"cd {_shell_quote(str(repo_dir))} && {command}"

    message = "\n".join(
        [
            "Use exec to run the watcher wrapper and return only the command's JSON output.",
            f"Repository: {repo_dir}",
            f"Command: {shell_command}",
            "If the command exits non-zero, return the JSON or stderr summary once and do not retry in a loop.",
        ]
    )

    return {
        "name": job_name,
        "schedule": {
            "kind": "every",
            "everyMs": every_minutes * 60 * 1000,
        },
        "sessionTarget": session_target,
        "payload": {
            "kind": "agentTurn",
            "message": message,
        },
        "delivery": {
            "mode": delivery_mode,
        },
    }


def _shell_quote(value: str) -> str:
    if value and all(ch.isalnum() or ch in "/._-:" for ch in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"
