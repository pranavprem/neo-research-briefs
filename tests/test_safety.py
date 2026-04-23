"""Tests for :mod:`neo_research_briefs.safety`."""

from __future__ import annotations

from pathlib import Path

from neo_research_briefs.safety import scan_repo_for_bespoke_info


def test_scan_repo_for_bespoke_info_flags_private_details(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    private_ip = "10." "0.0.116"
    home_path = "/Users/" "alice/projects"
    snowflake = "123456789" "012345678"
    custom_domain = "vault." "example." "internal"
    (root / "README.md").write_text(
        f"Visit http://{private_ip}/service and {home_path}.\n"
        f"discord channel {snowflake}\n"
        f"custom url https://{custom_domain}/login\n",
        encoding="utf-8",
    )

    findings = scan_repo_for_bespoke_info(root)
    kinds = {finding.kind for finding in findings}

    assert "private_ip" in kinds
    assert "home_path" in kinds
    assert "discord_snowflake_context" in kinds
    assert "custom_domain" in kinds


def test_scan_repo_for_bespoke_info_allows_public_docs_domains(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text(
        "https://github.com/example/repo\n"
        "https://api.notion.com/v1/pages\n"
        "https://discord.com/api/v10/channels\n"
        "https://docs.openclaw.ai\n",
        encoding="utf-8",
    )

    findings = scan_repo_for_bespoke_info(root)

    assert findings == []
