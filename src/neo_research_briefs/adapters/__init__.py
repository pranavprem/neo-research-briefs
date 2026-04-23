"""External-system adapters.

Each adapter exposes a small, mockable surface so the watcher never
imports an HTTP client directly. All four adapters are usable in v1:

- Notion: REST API reads and write-back
- Discord: thread creation plus starter-message posting
- GitHub: issue creation via ``gh`` or REST
- Obsidian: markdown file discovery and frontmatter updates
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
