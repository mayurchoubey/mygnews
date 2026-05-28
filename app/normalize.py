from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode, urlparse

from .models import (
    NewsResponse,
    OrganicResult,
    Pagination,
    ParsedItem,
    SearchInformation,
    SearchMetadata,
    SearchParameters,
    TopStory,
)


def _favicon(item: ParsedItem) -> Optional[str]:
    if item.favicon:
        return item.favicon
    domain = urlparse(item.link).netloc
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64" if domain else None


def to_organic_results(items: list[ParsedItem], start: int) -> list[OrganicResult]:
    out: list[OrganicResult] = []
    for i, it in enumerate(items):
        out.append(
            OrganicResult(
                position=start + i + 1,
                title=it.title,
                link=it.link,
                source=it.source,
                date=it.date,
                iso_date=it.iso_date,
                snippet=it.snippet,
                favicon=_favicon(it),
                thumbnail=it.thumbnail,
            )
        )
    return out


def to_top_stories(items: list[ParsedItem]) -> list[TopStory]:
    out: list[TopStory] = []
    for i, it in enumerate(items):
        out.append(
            TopStory(
                position=i + 1,
                title=it.title,
                link=it.link,
                source=it.source,
                date=it.date,
                iso_date=it.iso_date,
                thumbnail=it.thumbnail,
            )
        )
    return out


def _page_link(params: SearchParameters, page: int) -> str:
    q: dict[str, object] = {"engine": "google_news", "q": params.q, "page": page}
    for k in ("gl", "hl", "location", "device", "time_period", "sort_by"):
        v = getattr(params, k)
        if v:
            q[k] = v
    return f"/search?{urlencode({k: v for k, v in q.items() if v is not None})}"


# Google's footer shows a bounded window of pages, not the full range.
_PAGE_WINDOW = 10


def build_pagination(
    params: SearchParameters, page: int, total: int, page_size: int
) -> Pagination:
    last_page = max(1, (total + page_size - 1) // page_size)
    nxt = _page_link(params, page + 1) if page < last_page else None
    lo = max(1, page - _PAGE_WINDOW // 2)
    hi = min(last_page, lo + _PAGE_WINDOW - 1)
    others = {str(p): _page_link(params, p) for p in range(lo, hi + 1) if p != page}
    return Pagination(
        current=page,
        next=nxt,
        other_pages=others or None,
    )


def build_response(
    *,
    page_items: list[ParsedItem],
    top_stories: list[ParsedItem],
    params: SearchParameters,
    metadata: SearchMetadata,
    info: SearchInformation,
    page: int,
    page_size: int,
    total: int,
) -> NewsResponse:
    start = (page - 1) * page_size
    return NewsResponse(
        search_metadata=metadata,
        search_parameters=params,
        search_information=info,
        organic_results=to_organic_results(page_items, start),
        top_stories=to_top_stories(top_stories),
        pagination=build_pagination(params, page, total, page_size),
    )
