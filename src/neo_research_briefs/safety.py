"""Repository safety scanning.

This is not a secret scanner in the cryptographic sense. It is a small,
opinionated lint pass for things that often sneak into public repos by
accident:

- private RFC1918 IPs,
- workstation-specific absolute home paths,
- custom internal domains and hostnames,
- Discord-style snowflakes when they appear next to channel/guild/user labels.

The goal is to catch bespoke operator setup details before pushing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


EXCLUDED_DIRS = frozenset(
    {".git", "__pycache__", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)
DEFAULT_ALLOWED_DOMAINS = frozenset(
    {
        "api.github.com",
        "api.notion.com",
        "discord.com",
        "docs.openclaw.ai",
        "example.com",
        "github.com",
        "notion.so",
        "www.notion.so",
    }
)


@dataclass(slots=True, frozen=True)
class SafetyFinding:
    path: str
    line: int
    kind: str
    match: str
    snippet: str


PRIVATE_IPV4_RE = re.compile(
    r"\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b"
)
HOME_PATH_RE = re.compile(r"(?:/Users/[A-Za-z0-9._-]+(?:/|$)|/home/[A-Za-z0-9._-]+(?:/|$))")
LOCAL_HOST_RE = re.compile(r"\b[A-Za-z0-9._-]+\.(?:local|lan|home|internal)\b")
URL_HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
DISCORD_CONTEXT_RE = re.compile(
    r"(?i)\b(?:discord|channel|guild|thread|message|user)[^\n]{0,40}\b(\d{16,20})\b"
)


def scan_repo_for_bespoke_info(
    root: Path,
    *,
    allowed_domains: frozenset[str] = DEFAULT_ALLOWED_DOMAINS,
) -> list[SafetyFinding]:
    """Scan a repo tree for bespoke or potentially sensitive setup details."""
    findings: list[SafetyFinding] = []
    root = root.resolve()

    for path in root.rglob("*"):
        if path.is_dir() or any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        rel = path.relative_to(root).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            findings.extend(_scan_line(rel, lineno, line, allowed_domains))

    return findings


def _scan_line(
    path: str,
    lineno: int,
    line: str,
    allowed_domains: frozenset[str],
) -> list[SafetyFinding]:
    findings: list[SafetyFinding] = []

    findings.extend(_regex_findings(path, lineno, line, "private_ip", PRIVATE_IPV4_RE))
    findings.extend(_regex_findings(path, lineno, line, "home_path", HOME_PATH_RE))
    findings.extend(_regex_findings(path, lineno, line, "local_hostname", LOCAL_HOST_RE))

    for match in DISCORD_CONTEXT_RE.finditer(line):
        findings.append(
            SafetyFinding(
                path=path,
                line=lineno,
                kind="discord_snowflake_context",
                match=match.group(1),
                snippet=line.strip()[:240],
            )
        )

    for match in URL_HOST_RE.finditer(line):
        host = match.group(1).lower().rstrip(".")
        if host.startswith("<") or host.endswith(">"):
            continue
        if host in allowed_domains or host.endswith(".example.com"):
            continue
        if _looks_like_public_placeholder(host):
            continue
        findings.append(
            SafetyFinding(
                path=path,
                line=lineno,
                kind="custom_domain",
                match=host,
                snippet=line.strip()[:240],
            )
        )

    return findings


def _regex_findings(
    path: str,
    lineno: int,
    line: str,
    kind: str,
    pattern: re.Pattern[str],
) -> list[SafetyFinding]:
    findings: list[SafetyFinding] = []
    for match in pattern.finditer(line):
        raw = match.group(0)
        if kind == "home_path" and raw in {"/Users/you/", "/home/user/", "/path/to/your/home/"}:
            continue
        findings.append(
            SafetyFinding(
                path=path,
                line=lineno,
                kind=kind,
                match=raw,
                snippet=line.strip()[:240],
            )
        )
    return findings


def _looks_like_public_placeholder(host: str) -> bool:
    return host in {"localhost", "127.0.0.1"} or host.startswith("<")
