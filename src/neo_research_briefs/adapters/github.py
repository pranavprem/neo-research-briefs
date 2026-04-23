"""GitHub adapter.

The watcher only ever creates **issues** during intake. PRs are created
by the worker session once actual code is pushed. Keeping the watcher
off the PR surface makes the blast radius of a misconfigured cron much
smaller: a rogue watcher can at worst spam issues on one repo.

The adapter prefers the ``gh`` CLI when available because that reuses
host auth and enterprise routing. If the operator disables CLI usage or
``gh`` is unavailable, it falls back to the GitHub REST API when a token
is configured.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from ..config import GitHubConfig
    from ..models import ResearchBrief


JsonRequest = Callable[[str, str, Mapping[str, str], Any | None], Any]
CommandRunner = Callable[[list[str], str], subprocess.CompletedProcess[str]]


class GitHubError(RuntimeError):
    """Raised when GitHub issue creation fails."""


@dataclass(slots=True, frozen=True)
class IssueRef:
    """Identity of a created GitHub issue."""

    repo: str
    number: int
    url: str


class GitHubAdapter:
    """Thin seam over ``gh`` or the GitHub REST API."""

    def __init__(
        self,
        config: GitHubConfig,
        *,
        request_json: JsonRequest | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.config = config
        self._request_json = request_json or _default_request_json
        self._command_runner = command_runner or _default_command_runner

    def resolve_repo(self, brief: ResearchBrief) -> str | None:
        if brief.target_repo:
            return brief.target_repo
        return self.config.default_repo

    def create_issue(self, brief: ResearchBrief, *, repo: str) -> IssueRef:
        body = self.build_issue_body(brief)

        if self.config.prefer_gh_cli and shutil.which("gh"):
            try:
                return self._create_issue_with_gh(brief.title, body=body, repo=repo)
            except GitHubError:
                if not self.config.token:
                    raise

        if self.config.token:
            return self._create_issue_with_rest(brief.title, body=body, repo=repo)

        raise GitHubError(
            "GitHub issue creation requires either gh auth on the host or GITHUB_TOKEN"
        )

    def build_issue_body(self, brief: ResearchBrief) -> str:
        lines = [f"## {brief.title}"]
        if brief.summary:
            lines += ["", "### Summary", brief.summary]
        if brief.why_it_matters:
            lines += ["", "### Why this matters", brief.why_it_matters]
        if brief.source_url:
            lines += ["", f"- Source URL: {brief.source_url}"]
        brief_link = self._brief_link(brief)
        if brief_link:
            lines += [f"- Brief link: {brief_link}"]
        if brief.tags:
            lines += ["", "### Tags", ", ".join(brief.tags)]
        lines += ["", "### Next steps", "- Confirm scope", "- Implement", "- Review and test"]
        return "\n".join(lines).strip() + "\n"

    def _create_issue_with_gh(self, title: str, *, body: str, repo: str) -> IssueRef:
        result = self._command_runner(
            ["gh", "issue", "create", "--repo", repo, "--title", title, "--body-file", "-"],
            body,
        )
        if result.returncode != 0:
            raise GitHubError(result.stderr.strip() or "gh issue create failed")

        url = _extract_first_url(result.stdout)
        if url is None:
            raise GitHubError("gh issue create did not return an issue URL")
        number = _issue_number_from_url(url)
        return IssueRef(repo=repo, number=number, url=url)

    def _create_issue_with_rest(self, title: str, *, body: str, repo: str) -> IssueRef:
        response = self._request(
            "POST",
            f"/repos/{repo}/issues",
            payload={"title": title, "body": body},
        )
        url = response.get("html_url")
        number = response.get("number")
        if not isinstance(url, str) or not isinstance(number, int):
            raise GitHubError("GitHub issue response missing html_url or number")
        return IssueRef(repo=repo, number=number, url=url)

    def _brief_link(self, brief: ResearchBrief) -> str | None:
        raw = brief.raw
        for key in ("url", "path"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _request(self, method: str, path: str, *, payload: Any | None = None) -> Any:
        url = _join_url(self.config.api_base, path)
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        return self._request_json(method, url, headers, payload)


# ---------------------------------------------------------------------------
# Transport


def _default_command_runner(command: list[str], body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=body, text=True, capture_output=True, check=False)


def _default_request_json(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Any | None,
) -> Any:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = Request(url, method=method, headers=dict(headers), data=data)
    try:
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:  # pragma: no cover - network dependent.
        body = exc.read().decode("utf-8", errors="replace")
        raise GitHubError(f"HTTP {exc.code} from GitHub: {body}") from exc
    except URLError as exc:  # pragma: no cover - network dependent.
        raise GitHubError(f"failed to reach GitHub: {exc.reason}") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"GitHub returned invalid JSON from {url!r}") from exc


# ---------------------------------------------------------------------------
# Helpers


_URL_RE = re.compile(r"https?://\S+")


def _extract_first_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    if match is None:
        return None
    return match.group(0).rstrip(")].,;\n")


def _issue_number_from_url(url: str) -> int:
    tail = url.rstrip("/").split("/")[-1]
    try:
        return int(tail)
    except ValueError as exc:
        raise GitHubError(f"could not parse issue number from {url!r}") from exc


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"
