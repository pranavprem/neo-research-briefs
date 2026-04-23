"""Watcher: the idempotent intake loop.

The watcher is intentionally boring. Each run:

1. picks a source of briefs (Notion and/or Obsidian),
2. asks that source for briefs marked ``Want``,
3. claims a bounded batch,
4. creates downstream artifacts (Discord thread, optional GitHub issue),
5. writes those artifacts back to the brief,
6. records errors on the brief and moves on.

Idempotency is enforced by refusing to claim briefs that already carry
downstream links. The watcher never retries automatically; a follow-up
run does.

Dry-run mode is load-bearing: it is how operators (and tests) verify
that the watcher picks up what they expect without touching Notion or
Discord.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from ..adapters.discord import DiscordAdapter
from ..adapters.github import GitHubAdapter
from ..adapters.notion import NotionAdapter
from ..adapters.obsidian import ObsidianAdapter, now_utc
from ..models import BriefSource, BriefStatus, ResearchBrief

if TYPE_CHECKING:
    from ..config import Config


@dataclass(slots=True)
class WatcherAction:
    """A single decision the watcher made about a single brief.

    Holding decisions as data (rather than emitting log lines directly)
    lets the CLI render them consistently and lets tests assert on them.
    """

    brief_id: str
    title: str
    source: BriefSource
    action: str  # "claimed" | "skipped" | "error" | "dry-run"
    detail: str = ""
    discord_thread_url: str | None = None
    github_issue_url: str | None = None
    occurred_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class WatcherReport:
    """Summary of one watcher run."""

    started_at: datetime = field(default_factory=now_utc)
    dry_run: bool = False
    actions: list[WatcherAction] = field(default_factory=list)

    @property
    def claimed(self) -> list[WatcherAction]:
        return [a for a in self.actions if a.action == "claimed"]

    @property
    def errors(self) -> list[WatcherAction]:
        return [a for a in self.actions if a.action == "error"]

    def summary_line(self) -> str:
        total = len(self.actions)
        dry_run_actions = sum(1 for a in self.actions if a.action == "dry-run")
        if self.dry_run:
            return (
                f"watcher (dry-run) processed {total} brief(s): "
                f"{dry_run_actions} planned, {len(self.errors)} error(s)"
            )
        return (
            f"watcher processed {total} brief(s): "
            f"{len(self.claimed)} claimed, {len(self.errors)} error(s)"
        )


class Watcher:
    """Coordinates adapters through one intake cycle."""

    def __init__(
        self,
        config: Config,
        *,
        notion: NotionAdapter | None = None,
        discord: DiscordAdapter | None = None,
        github: GitHubAdapter | None = None,
        obsidian: ObsidianAdapter | None = None,
    ) -> None:
        self.config = config
        self.notion = notion or (
            NotionAdapter(config.notion)
            if "notion" in config.enabled_adapters and config.notion.is_configured()
            else None
        )
        self.discord = discord or (
            DiscordAdapter(config.discord)
            if "discord" in config.enabled_adapters and config.discord.is_configured()
            else None
        )
        self.github = github or (
            GitHubAdapter(config.github)
            if "github" in config.enabled_adapters and config.github.is_configured()
            else None
        )
        self.obsidian = obsidian or (
            ObsidianAdapter(config.obsidian)
            if "obsidian" in config.enabled_adapters and config.obsidian.is_configured()
            else None
        )

    # ------------------------------------------------------------------
    # Public API

    def run_once(self) -> WatcherReport:
        """Execute one full intake cycle and return a report."""
        report = WatcherReport(dry_run=self.config.dry_run)
        briefs = self._collect_briefs()

        for brief in briefs[: self.config.max_per_run]:
            try:
                brief.validate()
            except ValueError as exc:
                report.actions.append(
                    WatcherAction(
                        brief_id=brief.id,
                        title=brief.title or "(untitled)",
                        source=brief.source,
                        action="error",
                        detail=f"invalid brief: {exc}",
                    )
                )
                continue

            if not brief.is_claimable():
                report.actions.append(
                    WatcherAction(
                        brief_id=brief.id,
                        title=brief.title,
                        source=brief.source,
                        action="skipped",
                        detail="already claimed or downstream artifacts present",
                    )
                )
                continue

            report.actions.append(self._process_brief(brief))

        return report

    # ------------------------------------------------------------------
    # Collection

    def _collect_briefs(self) -> list[ResearchBrief]:
        briefs: list[ResearchBrief] = []
        if self.obsidian is not None and "obsidian" in self.config.enabled_adapters:
            briefs.extend(self.obsidian.list_want_briefs())
        if self.notion is not None and "notion" in self.config.enabled_adapters:
            briefs.extend(self.notion.list_want_briefs())
        return briefs

    # ------------------------------------------------------------------
    # Per-brief processing

    def _process_brief(self, brief: ResearchBrief) -> WatcherAction:
        if self.config.dry_run:
            return WatcherAction(
                brief_id=brief.id,
                title=brief.title,
                source=brief.source,
                action="dry-run",
                detail=(
                    f"would claim as {self.config.claimer!r}, "
                    f"open Discord thread, "
                    f"{'create GitHub issue, ' if self._would_use_github(brief) else ''}"
                    "write back to source"
                ),
            )

        # Real execution path.
        thread_url: str | None = None
        issue_url: str | None = None
        try:
            if self.discord is not None and "discord" in self.config.enabled_adapters:
                thread = self.discord.create_intake_thread(brief)
                thread_url = thread.url
                body = self.discord.build_starter_message(
                    brief,
                    brief_link=self._brief_link(brief),
                )
                self.discord.post_starter_message(thread, body)

            if self._would_use_github(brief) and self.github is not None:
                repo = self.github.resolve_repo(brief)
                if repo:
                    issue = self.github.create_issue(brief, repo=repo)
                    issue_url = issue.url

            self._write_back(brief, thread_url=thread_url, issue_url=issue_url)

            return WatcherAction(
                brief_id=brief.id,
                title=brief.title,
                source=brief.source,
                action="claimed",
                discord_thread_url=thread_url,
                github_issue_url=issue_url,
            )
        except NotImplementedError as exc:
            return WatcherAction(
                brief_id=brief.id,
                title=brief.title,
                source=brief.source,
                action="error",
                detail=f"adapter not implemented: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - watcher never crashes on one bad brief.
            return WatcherAction(
                brief_id=brief.id,
                title=brief.title,
                source=brief.source,
                action="error",
                detail=f"{type(exc).__name__}: {exc}",
            )

    def _would_use_github(self, brief: ResearchBrief) -> bool:
        if "github" not in self.config.enabled_adapters:
            return False
        if self.github is None:
            return False
        return self.github.resolve_repo(brief) is not None

    def _brief_link(self, brief: ResearchBrief) -> str | None:
        if brief.source is BriefSource.OBSIDIAN:
            return brief.raw.get("path")
        return brief.raw.get("url")

    # ------------------------------------------------------------------
    # Write-back

    def _write_back(
        self, brief: ResearchBrief, *, thread_url: str | None, issue_url: str | None
    ) -> None:
        now = now_utc()
        if brief.source is BriefSource.OBSIDIAN and self.obsidian is not None:
            brief_file = next(
                (f for f in self.obsidian.iter_brief_files() if str(f.path) == brief.raw.get("path")),
                None,
            )
            if brief_file is None:
                raise FileNotFoundError(f"brief file disappeared: {brief.raw.get('path')}")
            updates: dict[str, object] = {
                self.config.obsidian.status_field: BriefStatus.IMPLEMENTING.value,
                "claimed_by": self.config.claimer,
                "claimed_at": now.isoformat(),
                "last_sync_at": now.isoformat(),
                "error": None,
            }
            if thread_url:
                updates["discord_thread_url"] = thread_url
            if issue_url:
                updates["github_issue_url"] = issue_url
            self.obsidian.update_frontmatter(brief_file, updates)
            return

        if brief.source is BriefSource.NOTION and self.notion is not None:
            self.notion.claim(brief, claimer=self.config.claimer)
            self.notion.write_back(
                brief,
                discord_thread_url=thread_url,
                github_issue_url=issue_url,
            )
            return

        raise RuntimeError(f"no write-back path for brief source {brief.source}")
