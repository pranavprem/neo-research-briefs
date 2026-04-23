"""Tests for :mod:`neo_research_briefs.adapters.notion`."""

from __future__ import annotations

from typing import Any, Mapping

from neo_research_briefs.adapters.notion import NotionAdapter
from neo_research_briefs.config import NotionConfig
from neo_research_briefs.models import BriefStatus


def _page(*, page_id: str, title: str, status: str) -> dict[str, Any]:
    return {
        "id": page_id,
        "url": f"https://notion.so/{page_id.replace('-', '')}",
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": title}],
            },
            "Status": {
                "type": "select",
                "select": {"name": status},
            },
            "Summary": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "one-line summary"}],
            },
            "Why it matters": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "because it helps"}],
            },
            "Source URL": {
                "type": "url",
                "url": "https://example.com/source",
            },
            "Target Repo": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "octo/cat"}],
            },
            "Claimed By": {
                "type": "rich_text",
                "rich_text": [],
            },
            "Claimed At": {
                "type": "date",
                "date": None,
            },
            "Last Sync At": {
                "type": "date",
                "date": None,
            },
            "Error": {
                "type": "rich_text",
                "rich_text": [],
            },
        },
    }


def test_list_want_briefs_paginates_and_parses() -> None:
    calls: list[tuple[str, str, Mapping[str, str], Any | None]] = []
    responses = [
        {
            "results": [_page(page_id="page-1", title="Brief one", status="Want")],
            "has_more": True,
            "next_cursor": "cursor-2",
        },
        {
            "results": [_page(page_id="page-2", title="Brief two", status="Want")],
            "has_more": False,
            "next_cursor": None,
        },
    ]

    def fake_request(method: str, url: str, headers: Mapping[str, str], payload: Any | None) -> Any:
        calls.append((method, url, headers, payload))
        return responses[len(calls) - 1]

    adapter = NotionAdapter(
        NotionConfig(token="secret", database_id="db-123"),
        request_json=fake_request,
    )

    briefs = list(adapter.list_want_briefs())

    assert [brief.id for brief in briefs] == ["page-1", "page-2"]
    assert briefs[0].status is BriefStatus.WANT
    assert briefs[0].target_repo == "octo/cat"
    assert briefs[0].raw["url"] == "https://notion.so/page1"
    assert calls[0][0] == "POST"
    assert calls[0][3]["filter"]["select"]["equals"] == "Want"
    assert calls[1][3]["start_cursor"] == "cursor-2"


def test_claim_and_write_back_patch_expected_properties() -> None:
    calls: list[tuple[str, str, Mapping[str, str], Any | None]] = []

    def fake_request(method: str, url: str, headers: Mapping[str, str], payload: Any | None) -> Any:
        calls.append((method, url, headers, payload))
        return {"id": "page-1"}

    adapter = NotionAdapter(
        NotionConfig(token="secret", database_id="db-123"),
        request_json=fake_request,
    )
    parsed = adapter._page_to_brief(_page(page_id="page-1", title="Brief one", status="Want"))

    adapter.claim(parsed, claimer="openclaw:research-briefs")
    adapter.write_back(
        parsed,
        discord_thread_url="https://discord.com/channels/1/2",
        github_issue_url="https://github.com/octo/cat/issues/1",
    )

    assert len(calls) == 2
    claim_payload = calls[0][3]
    write_payload = calls[1][3]
    assert claim_payload["properties"]["Status"]["select"]["name"] == "Implementing"
    assert claim_payload["properties"]["Claimed By"]["rich_text"][0]["text"]["content"] == (
        "openclaw:research-briefs"
    )
    assert write_payload["properties"]["Discord Thread URL"]["url"] == (
        "https://discord.com/channels/1/2"
    )
    assert write_payload["properties"]["GitHub Issue URL"]["url"] == (
        "https://github.com/octo/cat/issues/1"
    )
    assert "Last Sync At" in write_payload["properties"]
