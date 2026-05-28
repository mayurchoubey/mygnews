from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from . import filters, normalize, resolve
from .cache import CreditCeilingExceeded, cache_get, cache_set, credit_meter, feed_key
from .firecrawl_client import FirecrawlError, build_news_url, scrape_html
from .models import (
    NewsResponse,
    ParsedItem,
    SearchInformation,
    SearchMetadata,
    SearchParameters,
)
from .parser import parse

app = FastAPI(title="mygnews — SearchApi-compatible Google News API", version="0.2.0")

_TOP_STORIES_COUNT = 3


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "credits_used_today": credit_meter.used}


@app.get(
    "/search",
    response_model=NewsResponse,
    response_model_exclude_none=True,
)
def search(
    q: str = Query(..., description="search query (supports site:, when:, after:, before:)"),
    gl: Optional[str] = Query(None, description="country code, e.g. us"),
    hl: Optional[str] = Query(None, description="UI language, e.g. en"),
    location: Optional[str] = Query(None, description="canonical location string"),
    uule: Optional[str] = Query(None, description="google-encoded location"),
    lr: Optional[str] = Query(None, description="document language, e.g. lang_en"),
    cr: Optional[str] = Query(None, description="country restriction, e.g. countryUS"),
    device: str = Query("desktop", description="desktop | mobile | tablet"),
    time_period: Optional[str] = Query(
        None, description="last_hour | last_day | last_week | last_month | last_year"
    ),
    time_period_min: Optional[str] = Query(None, description="start date MM/DD/YYYY"),
    time_period_max: Optional[str] = Query(None, description="end date MM/DD/YYYY"),
    sort_by: Optional[str] = Query(None, description="most_recent (default: relevance)"),
    nfpr: Optional[int] = Query(None, description="1 to exclude auto-corrected results"),
    filter: Optional[int] = Query(None, description="0 to disable dedup/host-crowding"),
    page: int = Query(1, ge=1, description="1-based page number"),
    num: int = Query(10, ge=1, le=100, description="results per page (extension)"),
    no_cache: bool = Query(False, description="bypass the feed cache"),
):
    started = time.perf_counter()
    created_at = _now()
    search_id = uuid.uuid4().hex

    params = SearchParameters(
        engine="google_news",
        q=q,
        location=location,
        location_used=location,
        uule=uule,
        gl=gl,
        hl=hl,
        lr=lr,
        cr=cr,
        device=device,
        time_period=time_period,
        time_period_min=time_period_min,
        time_period_max=time_period_max,
        sort_by=sort_by,
        nfpr=nfpr,
        filter=filter,
        page=page,
    )

    def _error(message: str, status_code: int = 502) -> JSONResponse:
        meta = SearchMetadata(
            id=search_id,
            status="Error",
            created_at=created_at,
            total_time_taken=round(time.perf_counter() - started, 3),
            error=message,
        )
        body = NewsResponse(search_metadata=meta, search_parameters=params)
        return JSONResponse(body.model_dump(exclude_none=True), status_code=status_code)

    effective_q = filters.build_query(q, time_period, time_period_min, time_period_max)
    url = build_news_url(q=effective_q, gl=gl, hl=hl)

    # Feed cache is keyed on the (date-operator-augmented) query + locale, so
    # sort/page/filter variations reuse a single Firecrawl scrape.
    fkey = feed_key(effective_q, gl, hl)
    cached_feed = None if no_cache else cache_get(fkey)

    request_time = None
    parsing_time = None
    if cached_feed is not None:
        feed = [ParsedItem(**d) for d in cached_feed["items"]]
        mode = cached_feed["mode"]
        from_cache = True
    else:
        country = (gl or "US").upper()
        try:
            t0 = time.perf_counter()
            html = scrape_html(
                url,
                country=country,
                languages=[f"{hl or 'en'}-{country}"],
                mobile=(device == "mobile"),
            )
            request_time = round(time.perf_counter() - t0, 3)
            t1 = time.perf_counter()
            feed, mode = parse(html, url)
            parsing_time = round(time.perf_counter() - t1, 3)
        except CreditCeilingExceeded as exc:
            return _error(str(exc), status_code=429)
        except FirecrawlError as exc:
            return _error(str(exc), status_code=502)
        cache_set(fkey, {"mode": mode, "items": [it.model_dump() for it in feed]})
        from_cache = False

    # Apply the time filter first (relevance order preserved), then derive
    # top_stories from the relevance-top, then optionally re-sort the rest.
    filtered = filters.filter_by_time(
        feed, time_period, time_period_min, time_period_max
    )
    top_stories = filtered[:_TOP_STORIES_COUNT]
    ordered = filters.sort_items(filtered, sort_by)
    total = len(ordered)

    start = (page - 1) * num
    page_items = [it.model_copy() for it in ordered[start : start + num]]

    # Resolve only this page's links to publisher URLs.
    targets = [it.link for it in page_items] + [it.link for it in top_stories]
    mapping = resolve.resolve_many(list(dict.fromkeys(targets)))
    for it in page_items:
        it.link = mapping.get(it.link, it.link)
    resolved_top = []
    for it in top_stories:
        copy = it.model_copy()
        copy.link = mapping.get(it.link, it.link)
        resolved_top.append(copy)

    info = SearchInformation(
        query_displayed=effective_q,
        total_results=total,
        time_taken_displayed=round(time.perf_counter() - started, 3),
        detected_location=location or (gl.upper() if gl else None),
    )
    meta = SearchMetadata(
        id=search_id,
        status="Success",
        created_at=created_at,
        request_time_taken=request_time,
        parsing_time_taken=parsing_time,
        total_time_taken=round(time.perf_counter() - started, 3),
        request_url=url,
        parse_mode=mode,
        cached=from_cache,
    )
    response = normalize.build_response(
        page_items=page_items,
        top_stories=resolved_top,
        params=params,
        metadata=meta,
        info=info,
        page=page,
        page_size=num,
        total=total,
    )
    return JSONResponse(response.model_dump(exclude_none=True))
