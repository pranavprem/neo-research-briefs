"""Tests for :mod:`neo_research_briefs.adapters.obsidian`.

Covers the frontmatter parser (the thing most likely to surprise
operators editing briefs by hand) and the vault-level adapter flow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from neo_research_briefs.adapters.obsidian import (
    ObsidianAdapter,
    ObsidianError,
    dump_frontmatter,
    parse_frontmatter,
)
from neo_research_briefs.config import ObsidianConfig
from neo_research_briefs.models import BriefSource, BriefStatus


# ---------------------------------------------------------------------------
# parse_frontmatter


class TestParseFrontmatter:
    def test_no_frontmatter_returns_empty_dict(self) -> None:
        fm, body = parse_frontmatter("# Just a heading\n\nSome prose.\n")
        assert fm == {}
        assert body == "# Just a heading\n\nSome prose.\n"

    def test_empty_frontmatter_is_empty_dict(self) -> None:
        fm, body = parse_frontmatter("---\n---\n# body\n")
        assert fm == {}
        assert body == "# body\n"

    def test_simple_scalars(self) -> None:
        text = "---\ntitle: Explore pgvector\nstatus: want\n---\nbody\n"
        fm, body = parse_frontmatter(text)
        assert fm == {"title": "Explore pgvector", "status": "want"}
        assert body == "body\n"

    def test_quoted_strings(self) -> None:
        text = "---\ntitle: \"Hello: world\"\nslug: 'my-slug'\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm == {"title": "Hello: world", "slug": "my-slug"}

    def test_booleans_null_and_integers(self) -> None:
        text = "---\nactive: true\narchived: False\nparent: null\nrank: 42\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm == {"active": True, "archived": False, "parent": None, "rank": 42}

    def test_inline_list(self) -> None:
        text = "---\ntags: [ai, infra, databases]\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm["tags"] == ["ai", "infra", "databases"]

    def test_inline_list_respects_quoted_commas(self) -> None:
        text = '---\ntags: ["ai, ml", infra]\n---\n'
        fm, _ = parse_frontmatter(text)
        assert fm["tags"] == ["ai, ml", "infra"]

    def test_inline_empty_list(self) -> None:
        fm, _ = parse_frontmatter("---\ntags: []\n---\n")
        assert fm["tags"] == []

    def test_block_list(self) -> None:
        text = "---\ntags:\n  - ai\n  - infra\n  - databases\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm["tags"] == ["ai", "infra", "databases"]

    def test_block_list_terminates_on_non_list_line(self) -> None:
        text = "---\ntags:\n  - ai\n  - infra\nstatus: want\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm == {"tags": ["ai", "infra"], "status": "want"}

    def test_missing_closer_raises(self) -> None:
        with pytest.raises(ObsidianError, match="no closing"):
            parse_frontmatter("---\ntitle: broken\nbody goes here\n")

    def test_line_without_colon_raises(self) -> None:
        with pytest.raises(ObsidianError, match="not key: value"):
            parse_frontmatter("---\ntitle\n---\n")

    def test_indented_line_raises(self) -> None:
        # Nested maps are unsupported on purpose.
        with pytest.raises(ObsidianError, match="indented"):
            parse_frontmatter("---\ntitle: X\n  nested: no\n---\n")

    def test_crlf_line_endings_are_handled(self) -> None:
        text = "---\r\ntitle: Windows Brief\r\nstatus: want\r\n---\r\nbody line\r\n"
        fm, body = parse_frontmatter(text)
        assert fm == {"title": "Windows Brief", "status": "want"}
        assert "body line" in body

    def test_strips_single_blank_line_between_closer_and_body(self) -> None:
        text = "---\nstatus: want\n---\n\n# Heading\n"
        _, body = parse_frontmatter(text)
        assert body == "# Heading\n"


# ---------------------------------------------------------------------------
# dump_frontmatter round trip


class TestDumpFrontmatter:
    def test_round_trip_preserves_values(self) -> None:
        original = {
            "title": "Evaluate pgvector",
            "status": "want",
            "active": True,
            "parent": None,
            "tags": ["ai", "infra"],
            "empty_list": [],
        }
        text = dump_frontmatter(original)
        reparsed, body = parse_frontmatter(text)
        assert body == ""
        assert reparsed == original

    def test_quotes_values_with_colons(self) -> None:
        text = dump_frontmatter({"title": "Hello: world"})
        assert 'title: "Hello: world"' in text
        reparsed, _ = parse_frontmatter(text)
        assert reparsed["title"] == "Hello: world"


# ---------------------------------------------------------------------------
# ObsidianAdapter end-to-end


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "Research Briefs").mkdir(parents=True)
    return vault


def _write_brief(vault: Path, name: str, content: str) -> Path:
    path = vault / "Research Briefs" / name
    path.write_text(content, encoding="utf-8")
    return path


class TestObsidianAdapter:
    def test_scan_returns_ok_and_problems_separately(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_brief(
            vault,
            "good.md",
            "---\ntitle: Good\nstatus: want\n---\nbody\n",
        )
        _write_brief(
            vault,
            "bad.md",
            "---\ntitle: Bad\n",  # missing closing delimiter
        )
        adapter = ObsidianAdapter(ObsidianConfig(vault_path=vault))

        ok, problems = adapter.scan()
        assert len(ok) == 1
        assert ok[0].get_str("title") == "Good"
        assert len(problems) == 1
        assert problems[0][0].name == "bad.md"
        assert "no closing" in problems[0][1]

    def test_list_want_briefs_filters_by_status(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_brief(vault, "a.md", "---\ntitle: A\nstatus: want\n---\n")
        _write_brief(vault, "b.md", "---\ntitle: B\nstatus: backlog\n---\n")
        _write_brief(vault, "c.md", "---\ntitle: C\nstatus: WANT\n---\n")

        adapter = ObsidianAdapter(ObsidianConfig(vault_path=vault))
        briefs = adapter.list_want_briefs()
        titles = sorted(b.title for b in briefs)
        assert titles == ["A", "C"]

    def test_file_to_brief_projects_fields(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_brief(
            vault,
            "pgvector.md",
            "\n".join(
                [
                    "---",
                    "title: pgvector eval",
                    "status: want",
                    "summary: short",
                    "why_it_matters: long-ish",
                    "source_url: https://example.com",
                    "target_repo: octo/cat",
                    "tags: [db, ai]",
                    "---",
                    "body",
                ]
            )
            + "\n",
        )
        adapter = ObsidianAdapter(ObsidianConfig(vault_path=vault))
        briefs = adapter.list_want_briefs()
        assert len(briefs) == 1
        brief = briefs[0]
        assert brief.source is BriefSource.OBSIDIAN
        assert brief.status is BriefStatus.WANT
        assert brief.title == "pgvector eval"
        assert brief.target_repo == "octo/cat"
        assert brief.source_url == "https://example.com"
        assert brief.tags == ["db", "ai"]
        assert brief.id.startswith("obsidian:")

    def test_file_to_brief_rejects_bad_target_repo(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_brief(
            vault,
            "bad.md",
            "---\ntitle: bad\nstatus: want\ntarget_repo: not-a-repo\n---\n",
        )
        adapter = ObsidianAdapter(ObsidianConfig(vault_path=vault))
        # list_want_briefs swallows validation errors; check directly.
        files = list(adapter.iter_brief_files())
        assert len(files) == 1
        with pytest.raises(ValueError, match="owner/name"):
            adapter.file_to_brief(files[0])

    def test_update_frontmatter_writes_atomically_and_preserves_body(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        original_body = "# Notes\n\nA line of prose.\nAnother line.\n"
        path = _write_brief(
            vault,
            "notes.md",
            "---\ntitle: original\nstatus: want\n---\n" + original_body,
        )
        adapter = ObsidianAdapter(ObsidianConfig(vault_path=vault))
        (brief_file,) = list(adapter.iter_brief_files())
        adapter.update_frontmatter(
            brief_file,
            {"status": "implementing", "claimed_by": "openclaw:research-briefs"},
        )
        text = path.read_text(encoding="utf-8")
        assert text.endswith(original_body)
        assert "status: implementing" in text
        # The colon in "openclaw:research-briefs" forces quoting on the way out.
        assert 'claimed_by: "openclaw:research-briefs"' in text

        # Round-trip parse to make sure the written file is still valid.
        reparsed, _ = parse_frontmatter(text)
        assert reparsed["claimed_by"] == "openclaw:research-briefs"

        # No leftover tempfiles in the directory.
        leftovers = [p.name for p in path.parent.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    def test_iter_brief_files_is_recursive(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        nested = vault / "Research Briefs" / "databases"
        nested.mkdir()
        (nested / "pgvector.md").write_text(
            "---\ntitle: nested\nstatus: want\n---\n", encoding="utf-8"
        )
        adapter = ObsidianAdapter(ObsidianConfig(vault_path=vault))
        files = list(adapter.iter_brief_files())
        assert len(files) == 1
        assert files[0].path.name == "pgvector.md"
