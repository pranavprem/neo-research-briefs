"""Tests for :mod:`neo_research_briefs.openclaw`."""

from __future__ import annotations

from pathlib import Path

from neo_research_briefs.openclaw import build_cron_job, build_runner_command


def test_build_runner_command_defaults_to_json_run_once() -> None:
    command = build_runner_command(Path("/srv/neo-research-briefs"))
    assert command == "bash scripts/run_neo_briefs.sh --json run-once"


def test_build_runner_command_quotes_env_path_with_spaces() -> None:
    command = build_runner_command(
        Path("/srv/neo-research-briefs"),
        env_file=Path("/secure path/neo briefs.env"),
        dry_run=False,
    )
    assert command == (
        "bash scripts/run_neo_briefs.sh --env-file '/secure path/neo briefs.env' --json run-once --no-dry-run"
    )


def test_build_cron_job_uses_minutes_and_repo_path() -> None:
    job = build_cron_job(
        Path("/srv/neo-research-briefs"),
        every_minutes=10,
        session_target="current",
        delivery_mode="announce",
    )
    assert job["schedule"]["everyMs"] == 600000
    assert job["sessionTarget"] == "current"
    assert job["delivery"]["mode"] == "announce"
    message = job["payload"]["message"]
    assert "Repository: /srv/neo-research-briefs" in message
    assert "bash scripts/run_neo_briefs.sh --json run-once" in message
