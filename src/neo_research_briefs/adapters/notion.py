"""Notion adapter (stub).

Real implementation will call the Notion REST API (``api.notion.com``)
using the integration token from :class:`NotionConfig`. For v1 this
module documents the contract the watcher expects so that wiring in an
HTTP client later is a narrow change.

API notes for the future implementer
------------------------------------

- Query ``POST /v1/databases/{database_id}/query`` with a filter
  ``{"property": cfg.status_property, "select": {"equals": cfg.want_value}}``.
- Each returned page's ``id`` is the canonical brief identifier.
- Updating fields is ``PATCH /v1/pages/{page_id}`` with a ``properties``
  payload. Do not touch properties the watcher does not own.
- Respect the ``Notion-Version`` header; pin it explicitly instead of
  relying on the default.
- Paginate using ``next_cursor``; never assume a single page of results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from ..models import ResearchBrief

if TYPE_CHECKING:
    from ..config import NotionConfig


class NotionAdapter:
    """Thin seam over the Notion integration.

    The watcher uses this class rather than an ``httpx`` client directly
    so that tests and dry runs can substitute a fake implementation.
    """

    def __init__(self, config: NotionConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Reads

    def list_want_briefs(self) -> Iterable[ResearchBrief]:
        """Return briefs whose status equals the configured Want value.

        TODO: implement against the Notion REST API. Return an iterable
        so future code can stream paginated results without buffering.
        """
        raise NotImplementedError(
            "Notion adapter is a v1 stub. Configure NEO_BRIEFS_ENABLED_ADAPTERS "
            "without 'notion', or contribute the implementation."
        )

    # ------------------------------------------------------------------
    # Writes

    def claim(self, brief: ResearchBrief, *, claimer: str) -> None:
        """Mark the brief as ``Implementing`` and stamp ``Claimed By``/``Claimed At``.

        Must be a single PATCH so the claim is atomic from Notion's
        perspective.
        """
        raise NotImplementedError

    def write_back(
        self,
        brief: ResearchBrief,
        *,
        discord_thread_url: str | None = None,
        github_issue_url: str | None = None,
        github_pr_url: str | None = None,
        error: str | None = None,
    ) -> None:
        """Persist adapter outputs back onto the Notion page.

        Only provided fields should be written; ``None`` means "leave
        alone". Always refresh ``Last Sync At``.
        """
        raise NotImplementedError

    def set_status(self, brief: ResearchBrief, status: str) -> None:
        """Move the brief to a new workflow status.

        Kept separate from :meth:`write_back` so that status transitions
        stay explicit in the call site.
        """
        raise NotImplementedError
