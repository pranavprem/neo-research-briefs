"""Tests for :mod:`neo_research_briefs.adapters.discord`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

from neo_research_briefs.adapters.discord import DiscordAdapter
from neo_research_briefs.config import DiscordConfig
from neo_research_briefs.models import BriefSource, BriefStatus, ResearchBrief


def _brief(title: str = "A very useful research brief") -> ResearchBrief:
    return ResearchBrief(
        id="brief-123",
        title=title,
        status=BriefStatus.WANT,
        source=BriefSource.OBSIDIAN,
        summary="short summary",
        why_it_matters="because it matters",
        source_url="https://example.com",
        raw={"path": "/vault/Research Briefs/sample.md"},
    )


def test_create_intake_thread_posts_expected_payload() -> None:
    calls: list[tuple[str, str, Mapping[str, str], Any | None]] = []

    def fake_request(method: str, url: str, headers: Mapping[str, str], payload: Any | None) -> Any:
        calls.append((method, url, headers, payload))
        return {"id": "222", "guild_id": "111"}

    adapter = DiscordAdapter(
        DiscordConfig(bot_token="bot-token", intake_channel_id="999"),
        request_json=fake_request,
    )

    thread = adapter.create_intake_thread(_brief())

    assert thread.id == "222"
    assert thread.url == "https://discord.com/channels/111/222"
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/channels/999/threads")
    assert calls[0][3]["type"] == 11
    assert len(calls[0][3]["name"]) <= 100


def test_post_starter_message_skips_duplicate_bot_message() -> None:
    calls: list[tuple[str, str, Mapping[str, str], Any | None]] = []

    def fake_request(method: str, url: str, headers: Mapping[str, str], payload: Any | None) -> Any:
        calls.append((method, url, headers, payload))
        if url.endswith("/users/@me"):
            return {"id": "bot-1"}
        if "/messages?limit=" in url:
            return [{"author": {"id": "bot-1"}, "content": "hello"}]
        raise AssertionError(f"unexpected request: {method} {url}")

    adapter = DiscordAdapter(
        DiscordConfig(bot_token="bot-token", intake_channel_id="999"),
        request_json=fake_request,
    )

    adapter.post_starter_message(SimpleNamespace(id="222"), "hello")

    assert [call[1] for call in calls] == [
        "https://discord.com/api/v10/users/@me",
        "https://discord.com/api/v10/channels/222/messages?limit=10",
    ]


def test_build_starter_message_includes_brief_link() -> None:
    adapter = DiscordAdapter(DiscordConfig(bot_token="bot-token", intake_channel_id="999"))

    body = adapter.build_starter_message(_brief(), brief_link="/vault/sample.md")

    assert "Research brief claimed." in body
    assert "Brief link: /vault/sample.md" in body
    assert "Source: https://example.com" in body
