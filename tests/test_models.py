"""Tests for :mod:`neo_research_briefs.models`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from neo_research_briefs.models import BriefSource, BriefStatus, ResearchBrief


class TestBriefStatus:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("want", BriefStatus.WANT),
            ("Want", BriefStatus.WANT),
            (" WANT ", BriefStatus.WANT),
            ("backlog", BriefStatus.BACKLOG),
            ("implementing", BriefStatus.IMPLEMENTING),
            ("done", BriefStatus.DONE),
        ],
    )
    def test_parse_accepts_casing_and_whitespace(self, raw: str, expected: BriefStatus) -> None:
        assert BriefStatus.parse(raw) is expected

    @pytest.mark.parametrize("raw", ["", "   ", "wanted", "in-progress", "DONE!"])
    def test_parse_rejects_invalid_values(self, raw: str) -> None:
        with pytest.raises(ValueError):
            BriefStatus.parse(raw)

    def test_parse_rejects_none(self) -> None:
        with pytest.raises(ValueError):
            BriefStatus.parse(None)


class TestResearchBriefValidation:
    def _make(self, **overrides: object) -> ResearchBrief:
        defaults: dict[str, object] = dict(
            id="brief-1",
            title="Explore pgvector",
            status=BriefStatus.WANT,
            source=BriefSource.OBSIDIAN,
        )
        defaults.update(overrides)
        return ResearchBrief(**defaults)  # type: ignore[arg-type]

    def test_valid_minimal_brief(self) -> None:
        self._make().validate()

    def test_blank_id_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="id is required"):
            self._make(id="   ").validate()

    def test_blank_title_is_invalid(self) -> None:
        with pytest.raises(ValueError, match="title is required"):
            self._make(title="").validate()

    def test_source_url_must_be_http(self) -> None:
        with pytest.raises(ValueError, match="not a URL"):
            self._make(source_url="example.com").validate()

    def test_source_url_accepts_https(self) -> None:
        self._make(source_url="https://example.com").validate()

    def test_target_repo_must_contain_slash(self) -> None:
        with pytest.raises(ValueError, match="owner/name"):
            self._make(target_repo="just-a-name").validate()


class TestResearchBriefIdempotency:
    def test_is_claimable_for_plain_want(self) -> None:
        brief = ResearchBrief(
            id="b", title="t", status=BriefStatus.WANT, source=BriefSource.OBSIDIAN
        )
        assert brief.is_claimable() is True

    def test_not_claimable_when_already_has_discord_thread(self) -> None:
        brief = ResearchBrief(
            id="b",
            title="t",
            status=BriefStatus.WANT,
            source=BriefSource.OBSIDIAN,
            discord_thread_url="https://discord.com/channels/1/2",
        )
        assert brief.is_claimable() is False

    def test_not_claimable_when_claimed_by_is_set(self) -> None:
        brief = ResearchBrief(
            id="b",
            title="t",
            status=BriefStatus.WANT,
            source=BriefSource.OBSIDIAN,
            claimed_by="openclaw:research-briefs",
        )
        assert brief.is_claimable() is False

    def test_not_claimable_when_status_is_not_want(self) -> None:
        brief = ResearchBrief(
            id="b",
            title="t",
            status=BriefStatus.IMPLEMENTING,
            source=BriefSource.OBSIDIAN,
        )
        assert brief.is_claimable() is False


class TestResearchBriefSerialization:
    def test_round_trip_through_dict(self) -> None:
        brief = ResearchBrief(
            id="b",
            title="t",
            status=BriefStatus.WANT,
            source=BriefSource.NOTION,
            source_url="https://example.com",
            target_repo="octo/cat",
            tags=["ai", "infra"],
            claimed_at=datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc),
        )
        restored = ResearchBrief.from_dict(brief.to_dict())
        assert restored == brief

    def test_from_dict_accepts_iso_z_suffix(self) -> None:
        payload = {
            "id": "b",
            "title": "t",
            "status": "want",
            "source": "obsidian",
            "claimed_at": "2026-04-22T12:00:00Z",
        }
        restored = ResearchBrief.from_dict(payload)
        assert restored.claimed_at == datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc)

    def test_from_dict_fills_optional_defaults(self) -> None:
        brief = ResearchBrief.from_dict(
            {"id": "b", "title": "t", "status": "backlog", "source": "obsidian"}
        )
        assert brief.tags == []
        assert brief.raw == {}
        assert brief.claimed_at is None
