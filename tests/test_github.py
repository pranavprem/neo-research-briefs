"""Tests for :mod:`neo_research_briefs.adapters.github`."""

from __future__ import annotations

import subprocess
from typing import Any, Mapping

from neo_research_briefs.adapters.github import GitHubAdapter
from neo_research_briefs.config import GitHubConfig
from neo_research_briefs.models import BriefSource, BriefStatus, ResearchBrief


def _brief() -> ResearchBrief:
    return ResearchBrief(
        id="brief-1",
        title="Wire the thing",
        status=BriefStatus.WANT,
        source=BriefSource.NOTION,
        summary="short summary",
        why_it_matters="because it helps",
        source_url="https://example.com/source",
        target_repo="octo/cat",
        tags=["ai", "ops"],
        raw={"url": "https://notion.so/brief-1"},
    )


def test_resolve_repo_prefers_brief_target_repo() -> None:
    adapter = GitHubAdapter(GitHubConfig(default_repo="fallback/repo"))
    assert adapter.resolve_repo(_brief()) == "octo/cat"


def test_create_issue_with_rest_uses_token_when_cli_disabled() -> None:
    calls: list[tuple[str, str, Mapping[str, str], Any | None]] = []

    def fake_request(method: str, url: str, headers: Mapping[str, str], payload: Any | None) -> Any:
        calls.append((method, url, headers, payload))
        return {"html_url": "https://github.com/octo/cat/issues/9", "number": 9}

    adapter = GitHubAdapter(
        GitHubConfig(token="token", default_repo="octo/cat", prefer_gh_cli=False),
        request_json=fake_request,
    )

    issue = adapter.create_issue(_brief(), repo="octo/cat")

    assert issue.number == 9
    assert issue.url.endswith("/issues/9")
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/repos/octo/cat/issues")
    assert calls[0][3]["title"] == "Wire the thing"
    assert "Brief link: https://notion.so/brief-1" in calls[0][3]["body"]


def test_create_issue_with_gh_parses_stdout_url(monkeypatch) -> None:
    def fake_runner(command: list[str], body: str) -> subprocess.CompletedProcess[str]:
        assert command[:4] == ["gh", "issue", "create", "--repo"]
        assert "### Summary" in body
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="https://github.com/octo/cat/issues/12\n",
            stderr="",
        )

    monkeypatch.setattr("neo_research_briefs.adapters.github.shutil.which", lambda _: "/usr/bin/gh")

    adapter = GitHubAdapter(
        GitHubConfig(default_repo="octo/cat", prefer_gh_cli=True),
        command_runner=fake_runner,
    )

    issue = adapter.create_issue(_brief(), repo="octo/cat")

    assert issue.number == 12
    assert issue.url == "https://github.com/octo/cat/issues/12"
