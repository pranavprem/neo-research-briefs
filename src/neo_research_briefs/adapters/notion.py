"""Notion adapter.

This adapter talks directly to the Notion REST API using the integration
secret from :class:`neo_research_briefs.config.NotionConfig`.

The surface area stays intentionally small:

- list briefs whose status is the configured Want value,
- claim a brief,
- write back artifact URLs and error state,
- move a brief to a new status.

A future implementation can always swap out the transport layer, but the
watcher's contract should not need to change.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import BriefSource, BriefStatus, ResearchBrief

if TYPE_CHECKING:
    from ..config import NotionConfig


JsonRequest = Callable[[str, str, Mapping[str, str], Any | None], Any]


class NotionError(RuntimeError):
    """Raised when the Notion API returns an error or invalid payload."""


class NotionAdapter:
    """Thin seam over the Notion integration."""

    def __init__(self, config: NotionConfig, *, request_json: JsonRequest | None = None) -> None:
        self.config = config
        self._request_json = request_json or _default_request_json

    # ------------------------------------------------------------------
    # Reads

    def list_want_briefs(self) -> Iterable[ResearchBrief]:
        """Return briefs whose status equals the configured Want value."""
        payload: dict[str, Any] = {
            "filter": {
                "property": self.config.status_property,
                "select": {"equals": self.config.want_value},
            },
            "page_size": 100,
        }
        cursor: str | None = None
        briefs: list[ResearchBrief] = []

        while True:
            request_payload = dict(payload)
            if cursor:
                request_payload["start_cursor"] = cursor
            response = self._request(
                "POST",
                f"/databases/{self.config.database_id}/query",
                payload=request_payload,
            )
            results = response.get("results", [])
            if not isinstance(results, list):
                raise NotionError("Notion query response missing results list")
            briefs.extend(self._page_to_brief(page) for page in results)
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
            if not isinstance(cursor, str) or not cursor:
                break

        return briefs

    # ------------------------------------------------------------------
    # Writes

    def claim(self, brief: ResearchBrief, *, claimer: str) -> None:
        """Mark the brief as implementing and stamp claim metadata."""
        now = _iso_now()
        properties: dict[str, Any] = {
            self.config.status_property: _select(self.config.implementing_value),
            self.config.claimed_by_property: _rich_text(claimer),
            self.config.claimed_at_property: _date(now),
            self.config.last_sync_at_property: _date(now),
            self.config.error_property: _rich_text(""),
        }
        self._patch_page(brief.id, properties)

    def write_back(
        self,
        brief: ResearchBrief,
        *,
        discord_thread_url: str | None = None,
        github_issue_url: str | None = None,
        github_pr_url: str | None = None,
        error: str | None = None,
    ) -> None:
        """Persist adapter outputs back onto the Notion page."""
        properties: dict[str, Any] = {
            self.config.last_sync_at_property: _date(_iso_now()),
        }
        if discord_thread_url is not None:
            properties[self.config.discord_thread_url_property] = _url(discord_thread_url)
        if github_issue_url is not None:
            properties[self.config.github_issue_url_property] = _url(github_issue_url)
        if github_pr_url is not None:
            properties[self.config.github_pr_url_property] = _url(github_pr_url)
        if error is not None:
            properties[self.config.error_property] = _rich_text(error)
        self._patch_page(brief.id, properties)

    def set_status(self, brief: ResearchBrief, status: str) -> None:
        """Move the brief to a new workflow status."""
        self._patch_page(brief.id, {self.config.status_property: _select(status)})

    # ------------------------------------------------------------------
    # Parsing

    def _page_to_brief(self, page: Mapping[str, Any]) -> ResearchBrief:
        page_id = _require_str(page.get("id"), field="id")
        properties = _require_mapping(page.get("properties"), field="properties")

        title = _property_plain_text(properties.get(self.config.title_property))
        if not title:
            title = _first_title(properties) or page_id

        brief = ResearchBrief(
            id=page_id,
            title=title,
            status=BriefStatus.parse(_property_select_name(properties.get(self.config.status_property))),
            source=BriefSource.NOTION,
            summary=_property_plain_text(properties.get(self.config.summary_property)),
            why_it_matters=_property_plain_text(
                properties.get(self.config.why_it_matters_property)
            ),
            source_url=_blank_to_none(_property_url(properties.get(self.config.source_url_property))),
            target_repo=_blank_to_none(
                _property_plain_text(properties.get(self.config.target_repo_property))
            ),
            discord_thread_url=_blank_to_none(
                _property_url(properties.get(self.config.discord_thread_url_property))
            ),
            github_issue_url=_blank_to_none(
                _property_url(properties.get(self.config.github_issue_url_property))
            ),
            github_pr_url=_blank_to_none(
                _property_url(properties.get(self.config.github_pr_url_property))
            ),
            claimed_by=_blank_to_none(
                _property_plain_text(properties.get(self.config.claimed_by_property))
            ),
            claimed_at=_property_date(properties.get(self.config.claimed_at_property)),
            last_sync_at=_property_date(properties.get(self.config.last_sync_at_property)),
            error=_blank_to_none(_property_plain_text(properties.get(self.config.error_property))),
            raw={
                "page": dict(page),
                "url": page.get("url"),
            },
        )
        brief.validate()
        return brief

    # ------------------------------------------------------------------
    # HTTP

    def _patch_page(self, page_id: str, properties: Mapping[str, Any]) -> None:
        self._request("PATCH", f"/pages/{page_id}", payload={"properties": dict(properties)})

    def _request(self, method: str, path: str, *, payload: Any | None = None) -> Any:
        url = _join_url(self.config.api_base, path)
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "Notion-Version": self.config.notion_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return self._request_json(method, url, headers, payload)


# ---------------------------------------------------------------------------
# Transport


def _default_request_json(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Any | None,
) -> Any:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = Request(url, method=method, headers=dict(headers), data=data)
    try:
        with urlopen(request) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:  # pragma: no cover - exercised through adapter behavior tests.
        body = exc.read().decode("utf-8", errors="replace")
        raise NotionError(f"HTTP {exc.code} from Notion: {body}") from exc
    except URLError as exc:  # pragma: no cover - network dependent.
        raise NotionError(f"failed to reach Notion: {exc.reason}") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotionError(f"Notion returned invalid JSON from {url!r}") from exc


# ---------------------------------------------------------------------------
# Property helpers


def _property_plain_text(prop: Any) -> str:
    if not isinstance(prop, Mapping):
        return ""
    kind = prop.get("type")
    if kind == "title":
        return _join_rich_text(prop.get("title"))
    if kind == "rich_text":
        return _join_rich_text(prop.get("rich_text"))
    if kind == "url":
        value = prop.get("url")
        return value if isinstance(value, str) else ""
    if kind == "select":
        select = prop.get("select")
        if isinstance(select, Mapping):
            name = select.get("name")
            return name if isinstance(name, str) else ""
    if kind == "date":
        date = prop.get("date")
        if isinstance(date, Mapping):
            start = date.get("start")
            return start if isinstance(start, str) else ""
    return ""


def _property_select_name(prop: Any) -> str:
    if not isinstance(prop, Mapping):
        raise NotionError("status property missing or malformed")
    select = prop.get("select")
    if not isinstance(select, Mapping):
        raise NotionError("status property is not a select")
    name = select.get("name")
    if not isinstance(name, str) or not name.strip():
        raise NotionError("status select has no name")
    return name


def _property_url(prop: Any) -> str:
    if not isinstance(prop, Mapping):
        return ""
    value = prop.get("url")
    return value if isinstance(value, str) else ""


def _property_date(prop: Any) -> datetime | None:
    if not isinstance(prop, Mapping):
        return None
    date = prop.get("date")
    if not isinstance(date, Mapping):
        return None
    start = date.get("start")
    if not isinstance(start, str) or not start:
        return None
    if start.endswith("Z"):
        start = start[:-1] + "+00:00"
    parsed = datetime.fromisoformat(start)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _first_title(properties: Mapping[str, Any]) -> str:
    for prop in properties.values():
        if isinstance(prop, Mapping) and prop.get("type") == "title":
            title = _join_rich_text(prop.get("title"))
            if title:
                return title
    return ""


def _join_rich_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        plain = item.get("plain_text")
        if isinstance(plain, str):
            parts.append(plain)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Payload builders


def _select(value: str) -> dict[str, Any]:
    return {"select": {"name": value}}


def _url(value: str | None) -> dict[str, Any]:
    return {"url": value}


def _date(value: str) -> dict[str, Any]:
    return {"date": {"start": value}}


def _rich_text(value: str) -> dict[str, Any]:
    if not value:
        return {"rich_text": []}
    return {
        "rich_text": [
            {
                "type": "text",
                "text": {
                    "content": value,
                },
            }
        ]
    }


# ---------------------------------------------------------------------------
# Small helpers


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NotionError(f"page {field} missing or invalid")
    return value


def _require_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NotionError(f"page {field} missing or invalid")
    return value


def _blank_to_none(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None
