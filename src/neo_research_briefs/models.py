"""Domain models for research briefs.

These types are deliberately source-agnostic: a brief that originates in
Notion and a brief that originates in an Obsidian vault become the same
:class:`ResearchBrief`, which is what the watcher and adapters actually
operate on.

The models are pure dataclasses with no I/O. They know how to validate
themselves and how to round-trip to and from plain dictionaries, which
keeps tests simple and keeps adapters honest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class BriefStatus(str, Enum):
    """Workflow state of a research brief.

    The only truly load-bearing value is :attr:`WANT` - that is the
    signal the watcher responds to. The rest exist so that the state
    machine is legible when staring at a database view.
    """

    BACKLOG = "backlog"
    WANT = "want"
    IMPLEMENTING = "implementing"
    REVIEW = "review"
    DONE = "done"
    DROPPED = "dropped"

    @classmethod
    def parse(cls, raw: str | None) -> BriefStatus:
        """Parse a status string loosely.

        Accepts any casing and trims whitespace. Unknown values raise
        ``ValueError`` rather than silently mapping to ``BACKLOG``; the
        watcher needs to refuse to claim briefs it cannot classify.
        """
        if raw is None:
            raise ValueError("status is required")
        normalized = raw.strip().lower()
        if not normalized:
            raise ValueError("status is empty")
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"unknown status: {raw!r}")


class BriefSource(str, Enum):
    """Where the brief was authored."""

    NOTION = "notion"
    OBSIDIAN = "obsidian"


@dataclass(slots=True)
class ResearchBrief:
    """Normalized research brief.

    ``id`` is the canonical identifier used for idempotency. For Notion
    briefs it is the page ID; for Obsidian briefs it is the vault-relative
    path. The watcher never mints its own IDs.
    """

    id: str
    title: str
    status: BriefStatus
    source: BriefSource
    summary: str = ""
    why_it_matters: str = ""
    source_url: str | None = None
    target_repo: str | None = None
    discord_thread_url: str | None = None
    github_issue_url: str | None = None
    github_pr_url: str | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    last_sync_at: datetime | None = None
    error: str | None = None
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Validation

    def validate(self) -> None:
        """Raise ``ValueError`` if the brief is not fit to process.

        Called before the watcher attempts any external writes. Keeping
        validation here (instead of at each adapter boundary) means bad
        data fails fast and in one place.
        """
        if not self.id or not self.id.strip():
            raise ValueError("brief id is required")
        if not self.title or not self.title.strip():
            raise ValueError("brief title is required")
        if self.source_url is not None and not _looks_like_url(self.source_url):
            raise ValueError(f"source_url is not a URL: {self.source_url!r}")
        if self.target_repo is not None and "/" not in self.target_repo:
            raise ValueError(
                f"target_repo must be in owner/name form, got {self.target_repo!r}"
            )

    # ------------------------------------------------------------------
    # Idempotency helpers

    def is_claimable(self) -> bool:
        """True when the watcher should treat this brief as new work.

        A brief is claimable when it is in ``WANT`` and nothing has
        already produced a downstream artifact for it.
        """
        if self.status is not BriefStatus.WANT:
            return False
        if self.discord_thread_url:
            return False
        if self.claimed_by:
            # Another run already stamped it; let that run's state settle.
            return False
        return True

    # ------------------------------------------------------------------
    # Serialization

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict (enums and datetimes become strings)."""
        data = asdict(self)
        data["status"] = self.status.value
        data["source"] = self.source.value
        for key in ("claimed_at", "last_sync_at"):
            value = data.get(key)
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchBrief:
        """Inverse of :meth:`to_dict`. Tolerant of missing optional keys."""
        payload = dict(data)
        payload["status"] = BriefStatus.parse(payload.get("status"))
        payload["source"] = BriefSource(payload.get("source", BriefSource.NOTION.value))
        for key in ("claimed_at", "last_sync_at"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                payload[key] = _parse_iso(value)
            elif value in ("", None):
                payload[key] = None
        payload.setdefault("tags", [])
        payload.setdefault("raw", {})
        return cls(**payload)


# ---------------------------------------------------------------------------
# helpers


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _parse_iso(value: str) -> datetime:
    # ``fromisoformat`` on 3.11+ accepts a trailing ``Z``; normalize for 3.10.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
