"""Tests for :mod:`neo_research_briefs.config`."""

from __future__ import annotations

from pathlib import Path

import pytest

from neo_research_briefs.config import (
    KNOWN_ADAPTERS,
    ConfigError,
    load_config,
)


def test_load_config_defaults_to_obsidian_only_dry_run() -> None:
    config = load_config(environ={})
    assert config.dry_run is True
    assert config.enabled_adapters == frozenset({"obsidian"})
    assert config.claimer == "openclaw:research-briefs"
    assert config.max_per_run == 3
    # None of the adapters are configured from an empty env.
    assert not config.notion.is_configured()
    assert not config.discord.is_configured()
    assert not config.github.is_configured()
    assert not config.obsidian.is_configured()


def test_load_config_parses_booleans_and_ints() -> None:
    config = load_config(
        environ={
            "NEO_BRIEFS_DRY_RUN": "false",
            "NEO_BRIEFS_MAX_PER_RUN": "7",
            "GITHUB_PREFER_GH_CLI": "false",
            "DISCORD_AUTO_ARCHIVE_DURATION": "4320",
        }
    )
    assert config.dry_run is False
    assert config.max_per_run == 7
    assert config.github.prefer_gh_cli is False
    assert config.discord.auto_archive_duration == 4320


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("FALSE", False),
        ("no", False),
        ("off", False),
    ],
)
def test_bool_parsing_is_liberal(value: str, expected: bool) -> None:
    assert load_config(environ={"NEO_BRIEFS_DRY_RUN": value}).dry_run is expected


def test_bool_parsing_rejects_junk() -> None:
    with pytest.raises(ConfigError):
        load_config(environ={"NEO_BRIEFS_DRY_RUN": "maybe"})


def test_int_parsing_rejects_junk() -> None:
    with pytest.raises(ConfigError):
        load_config(environ={"NEO_BRIEFS_MAX_PER_RUN": "three"})


def test_enabled_adapters_trimmed_and_lowercased() -> None:
    config = load_config(
        environ={"NEO_BRIEFS_ENABLED_ADAPTERS": " Notion , Obsidian ,  "}
    )
    assert config.enabled_adapters == frozenset({"notion", "obsidian"})


def test_validate_reports_unknown_adapters() -> None:
    config = load_config(environ={"NEO_BRIEFS_ENABLED_ADAPTERS": "obsidian,rss"})
    problems = config.validate()
    assert any("unknown adapters" in p for p in problems)


def test_validate_reports_missing_notion_credentials() -> None:
    config = load_config(environ={"NEO_BRIEFS_ENABLED_ADAPTERS": "notion"})
    problems = config.validate()
    assert any("notion" in p.lower() for p in problems)


def test_validate_reports_missing_github_token_when_cli_disabled() -> None:
    config = load_config(
        environ={
            "NEO_BRIEFS_ENABLED_ADAPTERS": "github",
            "GITHUB_DEFAULT_REPO": "octo/cat",
            "GITHUB_PREFER_GH_CLI": "false",
        }
    )
    problems = config.validate()
    assert any("GITHUB_DEFAULT_REPO / GITHUB_TOKEN" in p for p in problems)


def test_validate_reports_missing_obsidian_vault() -> None:
    config = load_config(environ={"NEO_BRIEFS_ENABLED_ADAPTERS": "obsidian"})
    problems = config.validate()
    assert any("OBSIDIAN_VAULT_PATH" in p for p in problems)


def test_validate_detects_nonexistent_vault_path(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    config = load_config(
        environ={
            "NEO_BRIEFS_ENABLED_ADAPTERS": "obsidian",
            "OBSIDIAN_VAULT_PATH": str(missing),
        }
    )
    problems = config.validate()
    assert any("does not exist" in p for p in problems)


def test_validate_accepts_a_healthy_obsidian_config(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "Research Briefs").mkdir(parents=True)
    config = load_config(
        environ={
            "NEO_BRIEFS_ENABLED_ADAPTERS": "obsidian",
            "OBSIDIAN_VAULT_PATH": str(vault),
        }
    )
    assert config.validate() == []


def test_validate_rejects_zero_max_per_run() -> None:
    config = load_config(environ={"NEO_BRIEFS_MAX_PER_RUN": "0"})
    problems = config.validate()
    assert any("max_per_run" in p.lower() or "MAX_PER_RUN" in p for p in problems)


def test_load_config_reads_dotenv_without_overriding_real_env(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "NEO_BRIEFS_CLAIMER=from-dotenv",
                'NOTION_TOKEN="quoted-secret"',
                "NEO_BRIEFS_MAX_PER_RUN=5",
                "export OBSIDIAN_BRIEFS_FOLDER='Briefs Archive'",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(
        environ={"NEO_BRIEFS_CLAIMER": "from-real-env"},
        dotenv_path=dotenv,
    )
    # real env wins
    assert config.claimer == "from-real-env"
    # dotenv fills gaps
    assert config.notion.token == "quoted-secret"
    assert config.max_per_run == 5
    assert config.obsidian.briefs_folder == "Briefs Archive"
    assert config.notion.implementing_value == "Implementing"


def test_known_adapters_is_closed_set() -> None:
    # Sanity check: if someone adds a new adapter, they must update this set.
    assert KNOWN_ADAPTERS == frozenset({"notion", "discord", "github", "obsidian"})
