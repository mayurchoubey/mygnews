from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from . import filters, normalize, resolve, serpapi
from .cache import CreditCeilingExceeded, cache_get, cache_key, cache_set, credit_meter
from .firecrawl_client import FirecrawlError, build_news_url, scrape_html
from .models import (
    NewsResponse,
    ParsedItem,
    SearchInformation,
    SearchMetadata,
    SearchParameters,
)
from .parser import parse
from .parser.selectors import parse_menu

app = FastAPI(title="mygnews — Google News API (SerpApi-compatible)", version="0.3.0")

_TOP_STORIES_COUNT = 3


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "credits_used_today": credit_meter.used}


@app.get("/search")
def search(
    q: Optional[str] = Query(None, description="query (omit for headlines)"),
    gl: Optional[str] = Query(None, description="country code, e.g. us"),
    hl: Optional[str] = Query(None, description="UI language, e.g. en"),
    topic_token: Optional[str] = Query(None, description="browse a topic"),
    publication_token: Optional[str] = Query(None, description="browse a publication"),
    story_token: Optional[str] = Query(None, description="full coverage of a story"),
    section_token: Optional[str] = Query(None, description="a topic subsection"),
    location: Optional[str] = Query(None),
    uule: Optional[str] = Query(None),
    lr: Optional[str] = Query(None),
    cr: Optional[str] = Query(None),
    device: str = Query("desktop", description="desktop | mobile | tablet"),
    time_period: Optional[str] = Query(None, description="last_hour..last_year"),
    time_period_min: Optional[str] = Query(None, description="MM/DD/YYYY"),
    time_period_max: Optional[str] = Query(None, description="MM/DD/YYYY"),
    sort_by: Optional[str] = Query(None, description="most_recent"),
    nfpr: Optional[int] = Query(None),
    filter: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    num: int = Query(10, ge=1, le=100),
    output: str = Query("serpapi", description="serpapi | searchapi"),
    no_cache: bool = Query(False),
):
    started = time.perf_counter()
    created_at = _now()
    search_id = uuid.uuid4().hex
    is_searchapi = output == "searchapi"

    effective_q = (
        filters.build_query(q, time_period, time_period_min, time_period_max)
        if q
        else None
    )
    url, engine = build_news_url(
        q=effective_q,
        gl=gl,
        hl=hl,
        topic_token=topic_token,
        publication_token=publication_token,
        story_token=story_token,
        section_token=section_token,
    )

    def _error(message: str, status_code: int) -> JSONResponse:
        if is_searchapi:
            meta = SearchMetadata(
                id=search_id, status="Error", created_at=created_at,
                total_time_taken=round(time.perf_counter() - started, 3),
                error=message,
            )
            body = NewsResponse(
                search_metadata=meta, search_parameters=SearchParameters(q=q, gl=gl, hl=hl)
            )
        else:
            meta = serpapi.SerpMetadata(
                id=search_id, status="Error", created_at=created_at,
                total_time_taken=round(time.perf_counter() - started, 3),
                error=message,
            )
            body = serpapi.SerpResponse(
                search_metadata=meta, search_parameters=serpapi.SerpParameters(q=q, gl=gl, hl=hl)
            )
        return JSONResponse(body.model_dump(exclude_none=True), status_code=status_code)

    fkey = cache_key(
        {
            "q": effective_q, "gl": gl, "hl": hl, "engine": engine,
            "topic_token": topic_token, "publication_token": publication_token,
            "story_token": story_token, "section_token": section_token,
        }
    )
    cached_feed = None if no_cache else cache_get(fkey)

    request_time = parsing_time = None
    if cached_feed is not None:
        feed = [ParsedItem(**d) for d in cached_feed["items"]]
        mode = cached_feed["mode"]
        menu = cached_feed.get("menu", [])
        from_cache = True
    else:
        country = (gl or "US").upper()
        try:
            t0 = time.perf_counter()
            html = scrape_html(
                url, country=country, languages=[f"{hl or 'en'}-{country}"],
                mobile=(device == "mobile"),
            )
            request_time = round(time.perf_counter() - t0, 3)
            t1 = time.perf_counter()
            feed, mode = parse(html, url)
            menu = parse_menu(html)
            parsing_time = round(time.perf_counter() - t1, 3)
        except CreditCeilingExceeded as exc:
            return _error(str(exc), 429)
        except FirecrawlError as exc:
            return _error(str(exc), 502)
        cache_set(
            fkey,
            {"mode": mode, "menu": menu, "items": [it.model_dump() for it in feed]},
        )
        from_cache = False

    # SearchApi semantics: time filter, then top_stories (relevance), then sort.
    filtered = filters.filter_by_time(feed, time_period, time_period_min, time_period_max)
    top_stories = filtered[:_TOP_STORIES_COUNT]
    ordered = filters.sort_items(filtered, sort_by)
    total = len(ordered)

    start = (page - 1) * num
    page_items = [it.model_copy() for it in ordered[start : start + num]]

    targets = [it.link for it in page_items] + [it.link for it in top_stories]
    mapping = resolve.resolve_many(list(dict.fromkeys(targets)))
    for it in page_items:
        it.link = mapping.get(it.link, it.link)

    if is_searchapi:
        resolved_top = []
        for it in top_stories:
            cp = it.model_copy(); cp.link = mapping.get(it.link, it.link)
            resolved_top.append(cp)
        params = SearchParameters(
            engine="google_news", q=q, location=location, location_used=location,
            uule=uule, gl=gl, hl=hl, lr=lr, cr=cr, device=device,
            time_period=time_period, time_period_min=time_period_min,
            time_period_max=time_period_max, sort_by=sort_by, nfpr=nfpr,
            filter=filter, page=page,
        )
        info = SearchInformation(
            query_displayed=effective_q or q, total_results=total,
            time_taken_displayed=round(time.perf_counter() - started, 3),
            detected_location=location or (gl.upper() if gl else None),
        )
        meta = SearchMetadata(
            id=search_id, status="Success", created_at=created_at,
            request_time_taken=request_time, parsing_time_taken=parsing_time,
            total_time_taken=round(time.perf_counter() - started, 3),
            request_url=url, parse_mode=mode, cached=from_cache,
        )
        resp = normalize.build_response(
            page_items=page_items, top_stories=resolved_top, params=params,
            metadata=meta, info=info, page=page, page_size=num, total=total,
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    # default: SerpApi shape
    menu_links = [
        serpapi.MenuLink(
            title=title,
            topic_token=token,
            serpapi_link="/search?"
            + urlencode({"engine": "google_news", "topic_token": token,
                         **({"gl": gl} if gl else {}), **({"hl": hl} if hl else {})}),
        )
        for title, token in menu
    ]
    params = serpapi.SerpParameters(
        engine="google_news", q=q, gl=gl, hl=hl, topic_token=topic_token,
        publication_token=publication_token, story_token=story_token,
        section_token=section_token,
    )
    meta = serpapi.SerpMetadata(
        id=search_id, status="Success", created_at=created_at, processed_at=_now(),
        total_time_taken=round(time.perf_counter() - started, 3),
        google_news_url=url, parse_mode=mode, cached=from_cache,
    )
    resp = serpapi.build_response(
        page_items=page_items, menu_links=menu_links, params=params,
        metadata=meta, page=page, page_size=num, total=total,
    )
    return JSONResponse(resp.model_dump(exclude_none=True))
