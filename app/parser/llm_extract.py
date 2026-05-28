from __future__ import annotations

from typing import Any

from .. import firecrawl_client
from ..models import ParsedItem

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "news_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "link": {"type": "string"},
                    "source": {"type": "string"},
                    "date": {"type": "string"},
                    "snippet": {"type": "string"},
                    "thumbnail": {"type": "string"},
                },
                "required": ["title", "link"],
            },
        }
    },
    "required": ["news_results"],
}

_PROMPT = (
    "This is a Google News search results page. Extract every news article "
    "card in the order shown. For each: the headline (title), the destination "
    "URL (link), the publishing source name (source), the published date or "
    "relative time string (date), the summary text (snippet), and the "
    "thumbnail image URL (thumbnail) if present."
)


def parse(url: str) -> list[ParsedItem]:
    extracted = firecrawl_client.extract_json(url, _SCHEMA, _PROMPT)
    rows = extracted.get("news_results") or []
    items: list[ParsedItem] = []
    seen: set[str] = set()
    for row in rows:
        link = (row.get("link") or "").strip()
        title = (row.get("title") or "").strip()
        if not link.startswith("http") or not title or link in seen:
            continue
        seen.add(link)
        items.append(
            ParsedItem(
                title=title,
                link=link,
                source=row.get("source") or None,
                date=row.get("date") or None,
                snippet=row.get("snippet") or None,
                thumbnail=row.get("thumbnail") or None,
            )
        )
    return items
