"""GitHub adapter (stub).

The watcher only ever creates **issues** during intake. PRs are created
by the worker session once actual code is pushed. Keeping the watcher
off the PR surface makes the blast radius of a misconfigured cron much
smaller: a rogue watcher can at worst spam issues on one repo.

Implementation options
----------------------

- Shell out to ``gh issue create`` if the host already has ``gh
  auth login`` set up. This is the path the README recommends.
- Use the REST API (``POST /repos/{owner}/{name}/issues``) with a
  personal access token from :class:`GitHubConfig.token`.

Prefer the ``gh`` CLI unless a deployment explicitly lacks it: it
handles auth refresh and enterprise hosts for free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import GitHubConfig
    from ..models import ResearchBrief


@dataclass(slots=True, frozen=True)
class IssueRef:
    """Identity of a created GitHub issue."""

    repo: str  # owner/name
    number: int
    url: str


class GitHubAdapter:
    """Thin seam over ``gh`` / the GitHub REST API."""

    def __init__(self, config: GitHubConfig) -> None:
        self.config = config

    def resolve_repo(self, brief: ResearchBrief) -> str | None:
        """Pick the repo a brief should land in.

        Uses the brief's explicit ``target_repo`` when set, otherwise
        falls back to :attr:`GitHubConfig.default_repo`. Returning
        ``None`` means the brief is discussion-only and GitHub should
        be skipped.
        """
        if brief.target_repo:
            return brief.target_repo
        return self.config.default_repo

    def create_issue(self, brief: ResearchBrief, *, repo: str) -> IssueRef:
        """Create a tracking issue for the brief on ``repo``.

        TODO: ``gh issue create --repo {repo} --title ... --body ...``
        and parse the returned URL. The issue body should include a
        back-link to the original brief so a stranger landing on the
        issue can find the source of truth.
        """
        raise NotImplementedError(
            "GitHub adapter is a v1 stub. Disable the 'github' adapter or "
            "contribute the implementation."
        )
