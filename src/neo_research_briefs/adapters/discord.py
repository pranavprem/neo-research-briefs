"""Discord adapter (stub).

The watcher needs exactly two things from Discord:

1. create an implementation thread in the intake channel,
2. post a starter message to that thread.

Everything else (progress updates, human handoffs) happens inside the
worker session, not the watcher. Keeping this surface small means the
watcher never has to track a thread's conversational state.

REST endpoints the future implementer will want
-----------------------------------------------

- ``POST /channels/{channel_id}/threads`` with ``type=11`` (public
  thread) or ``type=12`` (private thread).
- ``POST /channels/{thread_id}/messages`` for the starter message.
- Authorization header: ``Bot {token}``.
- Respect ``X-RateLimit-*`` headers - 429s on thread creation usually
  indicate a misconfigured cron interval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import DiscordConfig
    from ..models import ResearchBrief


@dataclass(slots=True, frozen=True)
class DiscordThread:
    """Minimal info the watcher needs to write back to Notion."""

    id: str
    url: str


class DiscordAdapter:
    """Thin seam over the Discord bot API."""

    def __init__(self, config: DiscordConfig) -> None:
        self.config = config

    def create_intake_thread(self, brief: ResearchBrief) -> DiscordThread:
        """Create a public thread in the intake channel and return its identity.

        TODO: POST to ``/channels/{channel_id}/threads``; the thread
        name should be derived from :attr:`ResearchBrief.title` and
        truncated to Discord's 100-character limit.
        """
        raise NotImplementedError(
            "Discord adapter is a v1 stub. Disable the 'discord' adapter or "
            "contribute the implementation."
        )

    def post_starter_message(self, thread: DiscordThread, body: str) -> None:
        """Post the first message to a freshly created thread.

        Must be safe to retry: the watcher may re-invoke this after a
        Notion write-back failure. Recommended protection: check for an
        existing bot message before posting.
        """
        raise NotImplementedError

    def build_starter_message(self, brief: ResearchBrief, *, brief_link: str | None) -> str:
        """Render the starter message using the brief's fields.

        ``brief_link`` is a source-specific back-link when one exists,
        for example a Notion page URL or an Obsidian file path.

        Kept on the adapter (not the watcher) so that formatting can
        evolve without touching the control flow.
        """
        lines = [
            "Research brief claimed.",
            "",
            f"**{brief.title}**",
        ]
        if brief.summary:
            lines += ["", "Summary:", brief.summary]
        if brief.why_it_matters:
            lines += ["", "Why this matters:", brief.why_it_matters]
        if brief.source_url:
            lines += ["", f"Source: {brief.source_url}"]
        if brief_link:
            lines += ["", f"Brief link: {brief_link}"]
        lines += [
            "",
            "Planned next steps:",
            "- confirm target repo or destination",
            "- break work into implementation tasks",
            "- start execution",
        ]
        return "\n".join(lines)
