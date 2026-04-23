"""Discord adapter.

The watcher needs exactly two things from Discord:

1. create an implementation thread in the intake channel,
2. post a starter message to that thread.

Everything else (progress updates, human handoffs) happens inside the
worker session, not the watcher. Keeping this surface small means the
watcher never has to track a thread's conversational state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from ..config import DiscordConfig
    from ..models import ResearchBrief


JsonRequest = Callable[[str, str, Mapping[str, str], Any | None], Any]


class DiscordError(RuntimeError):
    """Raised when the Discord API returns an error or invalid payload."""


@dataclass(slots=True, frozen=True)
class DiscordThread:
    """Minimal info the watcher needs to write back to the brief source."""

    id: str
    url: str


class DiscordAdapter:
    """Thin seam over the Discord bot API."""

    def __init__(self, config: DiscordConfig, *, request_json: JsonRequest | None = None) -> None:
        self.config = config
        self._request_json = request_json or _default_request_json
        self._bot_user_id: str | None = None

    def create_intake_thread(self, brief: ResearchBrief) -> DiscordThread:
        """Create a public thread in the intake channel and return its identity."""
        payload = {
            "name": self._make_thread_name(brief),
            "auto_archive_duration": self.config.auto_archive_duration,
            "type": 11,
        }
        response = self._request(
            "POST",
            f"/channels/{self.config.intake_channel_id}/threads",
            payload=payload,
        )
        thread_id = _require_str(response.get("id"), field="id")
        guild_id = response.get("guild_id")
        guild_segment = guild_id if isinstance(guild_id, str) and guild_id else "@me"
        return DiscordThread(
            id=thread_id,
            url=f"https://discord.com/channels/{guild_segment}/{thread_id}",
        )

    def post_starter_message(self, thread: DiscordThread, body: str) -> None:
        """Post the first message to a freshly created thread.

        Safe retry behavior matters because a later write-back step can
        fail after the thread already exists. To avoid duplicate starter
        messages, the adapter checks the most recent bot-authored thread
        messages for an exact content match before posting.
        """
        bot_user_id = self._get_bot_user_id()
        recent = self._request(
            "GET",
            f"/channels/{thread.id}/messages?limit={self.config.starter_message_history_limit}",
        )
        if isinstance(recent, list):
            for message in recent:
                if not isinstance(message, Mapping):
                    continue
                author = message.get("author")
                if not isinstance(author, Mapping):
                    continue
                author_id = author.get("id")
                content = message.get("content")
                if author_id == bot_user_id and content == body:
                    return

        self._request(
            "POST",
            f"/channels/{thread.id}/messages",
            payload={
                "content": body,
                "allowed_mentions": {"parse": []},
            },
        )

    def build_starter_message(self, brief: ResearchBrief, *, brief_link: str | None) -> str:
        """Render the starter message using the brief's fields."""
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

    def _get_bot_user_id(self) -> str:
        if self._bot_user_id is None:
            response = self._request("GET", "/users/@me")
            self._bot_user_id = _require_str(response.get("id"), field="id")
        return self._bot_user_id

    def _make_thread_name(self, brief: ResearchBrief) -> str:
        clean_title = " ".join(brief.title.split()) or "Research brief"
        suffix = hashlib.sha1(brief.id.encode("utf-8")).hexdigest()[:6]
        prefix = "Research: "
        joiner = " · "
        max_len = 100
        budget = max_len - len(prefix) - len(joiner) - len(suffix)
        if len(clean_title) > budget:
            clean_title = clean_title[: max(1, budget - 1)].rstrip() + "…"
        return f"{prefix}{clean_title}{joiner}{suffix}"

    def _request(self, method: str, path: str, *, payload: Any | None = None) -> Any:
        url = _join_url(self.config.api_base, path)
        headers = {
            "Authorization": f"Bot {self.config.bot_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return self._request_json(method, url, headers, payload)


# ---------------------------------------------------------------------------
# Transport


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
        raise DiscordError(f"HTTP {exc.code} from Discord: {body}") from exc
    except URLError as exc:  # pragma: no cover - network dependent.
        raise DiscordError(f"failed to reach Discord: {exc.reason}") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DiscordError(f"Discord returned invalid JSON from {url!r}") from exc


# ---------------------------------------------------------------------------
# Helpers


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _require_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscordError(f"Discord response missing or invalid {field}")
    return value
