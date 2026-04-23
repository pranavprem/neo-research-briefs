"""Configuration loading and validation.

Configuration lives in environment variables so that the same process can
run locally, under cron, inside an OpenClaw session, or in a container
without code changes. A ``.env`` file next to the working directory is
read if present, but real environment variables always win so that
operators can override one value without editing the file.

There is no third-party YAML or TOML parsing here on purpose: the
``.env`` format is narrow enough that a ~30 line parser is safer than
an optional dependency that might not be installed on the watcher host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# Adapters the user can toggle. Keep the set closed so that typos in
# ``NEO_BRIEFS_ENABLED_ADAPTERS`` surface as config errors, not as a
# silent "that adapter is simply off".
KNOWN_ADAPTERS: frozenset[str] = frozenset({"notion", "discord", "github", "obsidian"})


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass(slots=True)
class NotionConfig:
    token: str | None = None
    database_id: str | None = None
    status_property: str = "Status"
    want_value: str = "Want"

    def is_configured(self) -> bool:
        return bool(self.token and self.database_id)


@dataclass(slots=True)
class DiscordConfig:
    bot_token: str | None = None
    intake_channel_id: str | None = None

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.intake_channel_id)


@dataclass(slots=True)
class GitHubConfig:
    token: str | None = None
    default_repo: str | None = None

    def is_configured(self) -> bool:
        # ``gh auth login`` can provide credentials without a token env var,
        # so we only require a default repo to consider GitHub wired.
        return bool(self.default_repo)


@dataclass(slots=True)
class ObsidianConfig:
    vault_path: Path | None = None
    briefs_folder: str = "Research Briefs"
    status_field: str = "status"
    want_value: str = "want"

    def is_configured(self) -> bool:
        return self.vault_path is not None

    def briefs_dir(self) -> Path:
        """Absolute path to the folder that holds research briefs.

        Raises :class:`ConfigError` if the vault is not configured, so
        callers never have to handle an optional path themselves.
        """
        if self.vault_path is None:
            raise ConfigError("Obsidian vault is not configured")
        return self.vault_path / self.briefs_folder


@dataclass(slots=True)
class Config:
    claimer: str = "openclaw:research-briefs"
    dry_run: bool = True
    enabled_adapters: frozenset[str] = field(default_factory=lambda: frozenset({"obsidian"}))
    max_per_run: int = 3
    notion: NotionConfig = field(default_factory=NotionConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    obsidian: ObsidianConfig = field(default_factory=ObsidianConfig)

    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Return a list of human-readable problems; empty means OK.

        We return errors rather than raising so that the ``validate``
        CLI command can print all problems at once.
        """
        problems: list[str] = []

        unknown = self.enabled_adapters - KNOWN_ADAPTERS
        if unknown:
            problems.append(
                f"unknown adapters enabled: {sorted(unknown)} "
                f"(known: {sorted(KNOWN_ADAPTERS)})"
            )

        if self.max_per_run < 1:
            problems.append(f"NEO_BRIEFS_MAX_PER_RUN must be >= 1, got {self.max_per_run}")

        if not self.claimer.strip():
            problems.append("NEO_BRIEFS_CLAIMER must not be empty")

        if "notion" in self.enabled_adapters and not self.notion.is_configured():
            problems.append("notion adapter enabled but NOTION_TOKEN / NOTION_DATABASE_ID missing")
        if "discord" in self.enabled_adapters and not self.discord.is_configured():
            problems.append(
                "discord adapter enabled but DISCORD_BOT_TOKEN / "
                "DISCORD_INTAKE_CHANNEL_ID missing"
            )
        if "github" in self.enabled_adapters and not self.github.is_configured():
            problems.append("github adapter enabled but GITHUB_DEFAULT_REPO missing")
        if "obsidian" in self.enabled_adapters:
            if self.obsidian.vault_path is None:
                problems.append("obsidian adapter enabled but OBSIDIAN_VAULT_PATH missing")
            elif not self.obsidian.vault_path.exists():
                problems.append(
                    f"OBSIDIAN_VAULT_PATH does not exist: {self.obsidian.vault_path}"
                )

        return problems


# ---------------------------------------------------------------------------
# Loading


def load_config(
    environ: dict[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
) -> Config:
    """Build a :class:`Config` from environment variables.

    ``environ`` defaults to ``os.environ``. Overriding it is the main
    hook tests use to avoid polluting the real environment. If
    ``dotenv_path`` is given and the file exists, its entries populate
    any keys that are not already set in ``environ``.
    """
    env: dict[str, str] = dict(os.environ if environ is None else environ)

    if dotenv_path is not None and dotenv_path.exists():
        for key, value in _read_dotenv(dotenv_path).items():
            env.setdefault(key, value)

    vault_raw = env.get("OBSIDIAN_VAULT_PATH", "").strip()
    vault_path = Path(vault_raw).expanduser() if vault_raw else None

    return Config(
        claimer=env.get("NEO_BRIEFS_CLAIMER", "openclaw:research-briefs").strip()
        or "openclaw:research-briefs",
        dry_run=_parse_bool(env.get("NEO_BRIEFS_DRY_RUN"), default=True),
        enabled_adapters=_parse_adapter_set(env.get("NEO_BRIEFS_ENABLED_ADAPTERS")),
        max_per_run=_parse_int(env.get("NEO_BRIEFS_MAX_PER_RUN"), default=3),
        notion=NotionConfig(
            token=_clean(env.get("NOTION_TOKEN")),
            database_id=_clean(env.get("NOTION_DATABASE_ID")),
            status_property=env.get("NOTION_STATUS_PROPERTY", "Status").strip() or "Status",
            want_value=env.get("NOTION_WANT_VALUE", "Want").strip() or "Want",
        ),
        discord=DiscordConfig(
            bot_token=_clean(env.get("DISCORD_BOT_TOKEN")),
            intake_channel_id=_clean(env.get("DISCORD_INTAKE_CHANNEL_ID")),
        ),
        github=GitHubConfig(
            token=_clean(env.get("GITHUB_TOKEN")),
            default_repo=_clean(env.get("GITHUB_DEFAULT_REPO")),
        ),
        obsidian=ObsidianConfig(
            vault_path=vault_path,
            briefs_folder=env.get("OBSIDIAN_BRIEFS_FOLDER", "Research Briefs").strip()
            or "Research Briefs",
            status_field=env.get("OBSIDIAN_STATUS_FIELD", "status").strip() or "status",
            want_value=env.get("OBSIDIAN_WANT_VALUE", "want").strip() or "want",
        ),
    )


# ---------------------------------------------------------------------------
# parsers


_TRUE = frozenset({"1", "true", "yes", "y", "on"})
_FALSE = frozenset({"0", "false", "no", "n", "off"})


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ConfigError(f"cannot parse boolean from {value!r}")


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ConfigError(f"cannot parse integer from {value!r}") from exc


def _parse_adapter_set(value: str | None) -> frozenset[str]:
    if value is None:
        return frozenset({"obsidian"})
    parts = [p.strip().lower() for p in value.split(",")]
    return frozenset(p for p in parts if p)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


# ---------------------------------------------------------------------------
# minimal .env parser


def _read_dotenv(path: Path) -> dict[str, str]:
    """Parse a ``.env`` file.

    Supports ``KEY=value`` lines with optional surrounding single or
    double quotes, ``#`` comments, and blank lines. Anything more exotic
    (exports, variable expansion, multi-line values) is intentionally
    unsupported - operators who need that should use a real shell or a
    real loader.
    """
    result: dict[str, str] = {}
    for raw_line in _iter_lines(path):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def _iter_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8") as handle:
        yield from handle
