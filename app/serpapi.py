"""SerpApi google_news-compatible response shape and builder."""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode, urlparse

from pydantic import BaseModel, Field

from .models import ParsedItem

_PAGE_WINDOW = 10


# ---- SerpApi-shaped models ------------------------------------------------

class SerpSource(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None


class SerpNewsResult(BaseModel):
    position: int
    title: str
    source: SerpSource = Field(default_factory=SerpSource)
    link: str
    thumbnail: Optional[str] = None
    date: Optional[str] = None
    story_token: Optional[str] = None


class MenuLink(BaseModel):
    title: str
    topic_token: str
    serpapi_link: str


class SerpPagination(BaseModel):
    current: int = 1
    next: Optional[str] = None
    next_link: Optional[str] = None
    other_pages: Optional[dict[str, str]] = None


class SerpMetadata(BaseModel):
    id: str
    status: str
    created_at: str
    processed_at: Optional[str] = None
    total_time_taken: Optional[float] = None
    google_news_url: Optional[str] = None
    json_endpoint: Optional[str] = None
    provider: str = "firecrawl"
    parse_mode: Optional[str] = None
    cached: bool = False
    error: Optional[str] = None


class SerpParameters(BaseModel):
    engine: str = "google_news"
    q: Optional[str] = None
    gl: Optional[str] = None
    hl: Optional[str] = None
    topic_token: Optional[str] = None
    publication_token: Optional[str] = None
    story_token: Optional[str] = None
    section_token: Optional[str] = None


class SerpResponse(BaseModel):
    search_metadata: SerpMetadata
    search_parameters: SerpParameters
    news_results: list[SerpNewsResult] = Field(default_factory=list)
    menu_links: list[MenuLink] = Field(default_factory=list)
    serpapi_pagination: Optional[SerpPagination] = None


# ---- builder --------------------------------------------------------------

def _favicon(item: ParsedItem) -> Optional[str]:
    if item.favicon:
        return item.favicon
    domain = urlparse(item.link).netloc
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64" if domain else None


def _page_link(params: SerpParameters, page: int) -> str:
    q: dict[str, object] = {"engine": "google_news", "page": page}
    for k in ("q", "gl", "hl", "topic_token", "publication_token",
              "story_token", "section_token"):
        v = getattr(params, k)
        if v:
            q[k] = v
    return f"/search?{urlencode(q)}"


def _pagination(params: SerpParameters, page: int, total: int, size: int) -> SerpPagination:
    last = max(1, (total + size - 1) // size)
    lo = max(1, page - _PAGE_WINDOW // 2)
    hi = min(last, lo + _PAGE_WINDOW - 1)
    others = {str(p): _page_link(params, p) for p in range(lo, hi + 1) if p != page}
    nxt = _page_link(params, page + 1) if page < last else None
    return SerpPagination(
        current=page, next=nxt, next_link=nxt, other_pages=others or None
    )


def build_response(
    *,
    page_items: list[ParsedItem],
    menu_links: list[MenuLink],
    params: SerpParameters,
    metadata: SerpMetadata,
    page: int,
    page_size: int,
    total: int,
) -> SerpResponse:
    start = (page - 1) * page_size
    results = [
        SerpNewsResult(
            position=start + i + 1,
            title=it.title,
            link=it.link,
            source=SerpSource(name=it.source, icon=_favicon(it)),
            thumbnail=it.thumbnail,
            date=it.date,
            story_token=it.story_token,
        )
        for i, it in enumerate(page_items)
    ]
    return SerpResponse(
        search_metadata=metadata,
        search_parameters=params,
        news_results=results,
        menu_links=menu_links,
        serpapi_pagination=_pagination(params, page, total, page_size),
    )
