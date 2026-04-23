"""Obsidian adapter.

Unlike the other adapters in v1, this one is real: Obsidian vaults are
just folders of Markdown files, so there is no network dependency to
stub. The adapter can:

- walk a vault's briefs folder,
- parse a file's YAML-ish frontmatter block,
- convert a ``.md`` file into a :class:`ResearchBrief`,
- update a file's frontmatter atomically,
- enumerate which files are ready to claim.

The frontmatter parser handles only the subset of YAML that research
briefs actually use (scalars, booleans, nulls, inline and block lists).
That is by design; pulling in PyYAML for this would be overkill and
would couple the watcher to a third-party dependency that operators
have to install.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, Iterator

from ..models import BriefSource, BriefStatus, ResearchBrief

if TYPE_CHECKING:
    from ..config import ObsidianConfig


FRONTMATTER_DELIM = "---"


class ObsidianError(ValueError):
    """Raised when a brief file cannot be parsed or written safely."""


# ---------------------------------------------------------------------------
# File-level representation


@dataclass(slots=True)
class ObsidianBriefFile:
    """Parsed contents of a single brief ``.md`` file."""

    path: Path
    frontmatter: dict[str, Any]
    body: str
    # Original text, cached so :meth:`write_frontmatter` can preserve it verbatim.
    _raw: str = field(default="", repr=False)

    def get_str(self, key: str, default: str = "") -> str:
        """Look up a frontmatter string, defaulting to ``default``.

        Handy for optional fields (summary, why-it-matters) where an
        absent key should be equivalent to the empty string.
        """
        value = self.frontmatter.get(key, default)
        if value is None:
            return default
        return str(value)

    def get_list(self, key: str) -> list[str]:
        value = self.frontmatter.get(key)
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]


# ---------------------------------------------------------------------------
# Parsing


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown document into (frontmatter, body).

    Files without a frontmatter block return ``({}, text)``. Files whose
    frontmatter is empty (``---\\n---``) return ``({}, rest)``. Anything
    that looks like a frontmatter delimiter but is malformed raises
    :class:`ObsidianError`, so callers do not silently treat body text
    as configuration.
    """
    if not text.startswith(FRONTMATTER_DELIM):
        return {}, text

    # Accept CRLF and LF line endings; normalize to LF for scanning.
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")

    if lines[0].strip() != FRONTMATTER_DELIM:
        return {}, text

    closing_index: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == FRONTMATTER_DELIM:
            closing_index = i
            break

    if closing_index is None:
        raise ObsidianError("frontmatter opened with '---' but has no closing '---'")

    fm_lines = lines[1:closing_index]
    body_lines = lines[closing_index + 1 :]
    # Strip at most one leading blank line between the closer and the body.
    if body_lines and body_lines[0] == "":
        body_lines = body_lines[1:]

    frontmatter = _parse_yaml_subset(fm_lines)
    return frontmatter, "\n".join(body_lines)


def _parse_yaml_subset(lines: list[str]) -> dict[str, Any]:
    """Parse the narrow YAML subset research briefs use.

    Supports:
      - ``key: value`` scalars,
      - ``key: [a, b]`` inline lists,
      - ``key:`` followed by ``  - item`` block lists,
      - booleans (``true``/``false``), ``null`` / empty, integers,
        quoted strings.

    Does not support nested maps or multiline scalars. Raises
    :class:`ObsidianError` on clearly broken input.
    """
    result: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if ":" not in stripped:
            raise ObsidianError(f"frontmatter line is not key: value: {raw!r}")
        if raw.startswith((" ", "\t")):
            raise ObsidianError(f"unexpected indented frontmatter line: {raw!r}")

        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            raise ObsidianError(f"frontmatter line has empty key: {raw!r}")

        if value == "":
            # Could be a block list that follows, or simply an empty value.
            block_items, consumed = _collect_block_list(lines, i + 1)
            if block_items is not None:
                result[key] = block_items
                i += 1 + consumed
                continue
            result[key] = None
            i += 1
            continue

        result[key] = _parse_scalar_or_list(value)
        i += 1

    return result


def _collect_block_list(lines: list[str], start: int) -> tuple[list[str] | None, int]:
    """If ``lines[start:]`` begins with ``- item`` entries, return them."""
    items: list[str] = []
    j = start
    while j < len(lines):
        raw = lines[j]
        stripped = raw.strip()
        if not stripped:
            break
        if not stripped.startswith("- "):
            break
        items.append(_parse_scalar(stripped[2:].strip()))
        j += 1
    if not items:
        return None, 0
    return items, j - start


def _parse_scalar_or_list(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in _split_inline_list(inner)]
    return _parse_scalar(value)


def _split_inline_list(inner: str) -> list[str]:
    """Split ``a, b, "c, d", e`` respecting simple quotes."""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in inner:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            parts.append("".join(buf).strip())
            buf.clear()
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_scalar(value: str) -> Any:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    low = value.lower()
    if low in ("null", "~", ""):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


# ---------------------------------------------------------------------------
# Serialization


def dump_frontmatter(data: dict[str, Any]) -> str:
    """Render a minimal frontmatter block.

    Round-trip fidelity with arbitrary YAML is not a goal; readability
    for the files we emit is. Lists become block lists so merges diff
    cleanly line by line.
    """
    lines: list[str] = [FRONTMATTER_DELIM]
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {_emit_scalar(item)}")
        else:
            lines.append(f"{key}: {_emit_scalar(value)}")
    lines.append(FRONTMATTER_DELIM)
    return "\n".join(lines) + "\n"


def _emit_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    # Quote if the scalar contains characters that would confuse the parser.
    if any(ch in text for ch in (":", "#", "[", "]", ",")) or text != text.strip():
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text


# ---------------------------------------------------------------------------
# Adapter


class ObsidianAdapter:
    """Reads and writes research briefs stored in an Obsidian vault."""

    def __init__(self, config: ObsidianConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Reads

    def iter_brief_files(self) -> Iterator[ObsidianBriefFile]:
        """Yield every ``.md`` file under the configured briefs folder.

        Files that cannot be parsed are skipped silently here; callers
        that want to surface them (for example the ``obsidian`` CLI
        subcommand) should call :meth:`scan` instead.
        """
        for path in self._iter_md_paths():
            try:
                yield self._read_file(path)
            except ObsidianError:
                continue

    def scan(self) -> tuple[list[ObsidianBriefFile], list[tuple[Path, str]]]:
        """Return ``(briefs, problems)``.

        ``problems`` is a list of ``(path, message)`` tuples for files
        that failed to parse. Kept separate from the happy-path list so
        the CLI can summarize each cleanly.
        """
        ok: list[ObsidianBriefFile] = []
        problems: list[tuple[Path, str]] = []
        for path in self._iter_md_paths():
            try:
                ok.append(self._read_file(path))
            except ObsidianError as exc:
                problems.append((path, str(exc)))
        return ok, problems

    def list_want_briefs(self) -> list[ResearchBrief]:
        """Return briefs whose frontmatter status equals the Want value."""
        briefs: list[ResearchBrief] = []
        for brief_file in self.iter_brief_files():
            raw_status = brief_file.get_str(self.config.status_field)
            if raw_status.strip().lower() != self.config.want_value.strip().lower():
                continue
            try:
                brief = self.file_to_brief(brief_file)
            except ValueError:
                continue
            briefs.append(brief)
        return briefs

    def file_to_brief(self, brief_file: ObsidianBriefFile) -> ResearchBrief:
        """Project a parsed file into the :class:`ResearchBrief` domain type."""
        fm = brief_file.frontmatter
        title = brief_file.get_str("title") or brief_file.path.stem
        raw_status = brief_file.get_str(self.config.status_field, "backlog")
        try:
            status = BriefStatus.parse(raw_status)
        except ValueError as exc:
            raise ValueError(f"{brief_file.path}: {exc}") from exc

        brief = ResearchBrief(
            id=self._stable_id(brief_file.path),
            title=title.strip(),
            status=status,
            source=BriefSource.OBSIDIAN,
            summary=brief_file.get_str("summary"),
            why_it_matters=brief_file.get_str("why_it_matters")
            or brief_file.get_str("why it matters"),
            source_url=_none_if_blank(brief_file.get_str("source_url")),
            target_repo=_none_if_blank(brief_file.get_str("target_repo")),
            discord_thread_url=_none_if_blank(brief_file.get_str("discord_thread_url")),
            github_issue_url=_none_if_blank(brief_file.get_str("github_issue_url")),
            github_pr_url=_none_if_blank(brief_file.get_str("github_pr_url")),
            claimed_by=_none_if_blank(brief_file.get_str("claimed_by")),
            tags=brief_file.get_list("tags"),
            raw={"path": str(brief_file.path), "frontmatter": dict(fm)},
        )
        brief.validate()
        return brief

    # ------------------------------------------------------------------
    # Writes

    def update_frontmatter(
        self, brief_file: ObsidianBriefFile, updates: dict[str, Any]
    ) -> ObsidianBriefFile:
        """Return a new file object with ``updates`` applied and the file rewritten.

        Writes are atomic (temp file + rename) so that a crash never
        leaves a half-written brief on disk.
        """
        merged = dict(brief_file.frontmatter)
        merged.update(updates)
        new_text = dump_frontmatter(merged) + brief_file.body
        _atomic_write(brief_file.path, new_text)
        brief_file.frontmatter = merged
        brief_file._raw = new_text
        return brief_file

    # ------------------------------------------------------------------
    # Internals

    def _iter_md_paths(self) -> Iterator[Path]:
        briefs_dir = self.config.briefs_dir()
        if not briefs_dir.exists():
            return
        for root, _dirs, files in os.walk(briefs_dir):
            for name in sorted(files):
                if name.endswith(".md"):
                    yield Path(root) / name

    def _read_file(self, path: Path) -> ObsidianBriefFile:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        return ObsidianBriefFile(path=path, frontmatter=frontmatter, body=body, _raw=text)

    def _stable_id(self, path: Path) -> str:
        """Derive a deterministic ID from the vault-relative path.

        Using a hash keeps the ID filesystem-safe even for vaults whose
        paths contain spaces or unicode, while still being stable across
        runs.
        """
        try:
            rel = path.relative_to(self.config.briefs_dir())
        except ValueError:
            rel = path
        digest = hashlib.sha1(str(rel).encode("utf-8")).hexdigest()[:16]
        return f"obsidian:{digest}"


# ---------------------------------------------------------------------------
# helpers


def _none_if_blank(value: str) -> str | None:
    return value.strip() or None if value is not None else None


def _atomic_write(path: Path, text: str) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, delete=False, prefix=path.name + ".", suffix=".tmp"
    ) as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def now_utc() -> datetime:
    """Clock helper kept here so tests can monkeypatch it in one place."""
    return datetime.now(timezone.utc)
