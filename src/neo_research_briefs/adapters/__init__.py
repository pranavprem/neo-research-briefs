"""External-system adapters.

Each adapter exposes a small, mockable surface so the watcher never
imports an HTTP client directly. The Obsidian adapter is real in v1;
the others are documented stubs that raise :class:`NotImplementedError`
from methods that would otherwise touch the network.
"""

from .discord import DiscordAdapter
from .github import GitHubAdapter
from .notion import NotionAdapter
from .obsidian import ObsidianAdapter, ObsidianBriefFile, parse_frontmatter

__all__ = [
    "DiscordAdapter",
    "GitHubAdapter",
    "NotionAdapter",
    "ObsidianAdapter",
    "ObsidianBriefFile",
    "parse_frontmatter",
]
