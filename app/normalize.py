from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode, urlparse

from .models import (
    NewsResponse,
    NewsResult,
    Pagination,
    ParsedItem,
    SearchMetadata,
    SearchParameters,
    Source,
)


def _favicon(link: str) -> Optional[str]:
    domain = urlparse(link).netloc
    if not domain:
        return None
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


def to_news_results(items: list[ParsedItem], start: int) -> list[NewsResult]:
    results: list[NewsResult] = []
    for i, it in enumerate(items):
        results.append(
            NewsResult(
                position=start + i + 1,
                title=it.title,
                link=it.link,
                source=Source(
                    name=it.source_name,
                    icon=it.source_icon or _favicon(it.link),
                ),
                date=it.date,
                snippet=it.snippet,
                thumbnail=it.thumbnail,
            )
        )
    return results


def _pagination(params: SearchParameters, result_count: int) -> Optional[Pagination]:
    start = params.start or 0
    num = params.num or 10
    if result_count < num:
        return Pagination(current=(start // num) + 1)
    next_start = start + num
    next_params = {"q": params.q, "tbm": "nws", "start": next_start, "num": num}
    if params.gl:
        next_params["gl"] = params.gl
    if params.hl:
        next_params["hl"] = params.hl
    return Pagination(
        current=(start // num) + 1,
        next=str(next_start),
        next_link=f"/search?{urlencode(next_params)}",
    )


def build_response(
    *,
    items: list[ParsedItem],
    params: SearchParameters,
    metadata: SearchMetadata,
) -> NewsResponse:
    results = to_news_results(items, params.start or 0)
    return NewsResponse(
        search_metadata=metadata,
        search_parameters=params,
        news_results=results,
        serpapi_pagination=_pagination(params, len(results)),
    )
