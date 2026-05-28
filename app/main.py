from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from . import normalize, resolve
from .cache import CreditCeilingExceeded, cache_get, cache_set, credit_meter, feed_key
from .firecrawl_client import FirecrawlError, build_news_url, scrape_html
from .models import NewsResponse, ParsedItem, SearchMetadata, SearchParameters
from .parser import parse

app = FastAPI(title="OT News API", version="0.1.0")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "credits_used_today": credit_meter.used}


@app.get("/search", response_model=NewsResponse, response_model_exclude_none=True)
def search(
    q: str = Query(..., description="search query"),
    gl: Optional[str] = Query(None, description="country code, e.g. us"),
    hl: Optional[str] = Query(None, description="UI language, e.g. en"),
    start: int = Query(0, ge=0, description="result offset for pagination"),
    num: int = Query(10, ge=1, le=100, description="results per page"),
    engine: str = Query("google"),
    tbm: str = Query("nws"),
    no_cache: bool = Query(False, description="bypass the TTL cache"),
):
    started = time.perf_counter()
    created_at = _now()
    search_id = uuid.uuid4().hex

    params = SearchParameters(
        engine=engine, q=q, tbm=tbm, gl=gl, hl=hl, start=start, num=num
    )

    def _error(message: str, status_code: int = 502) -> JSONResponse:
        meta = SearchMetadata(
            id=search_id,
            status="Error",
            created_at=created_at,
            processed_at=_now(),
            total_time_taken=round(time.perf_counter() - started, 3),
            error=message,
        )
        body = NewsResponse(search_metadata=meta, search_parameters=params)
        return JSONResponse(
            body.model_dump(exclude_none=True), status_code=status_code
        )

    # The full result feed is cached per query (q/gl/hl); every page slices
    # from it, so paginating a query never re-scrapes Firecrawl.
    fkey = feed_key(q, gl, hl)
    cached_feed = None if no_cache else cache_get(fkey)

    if cached_feed is not None:
        feed = [ParsedItem(**d) for d in cached_feed["items"]]
        mode = cached_feed["mode"]
        from_cache = True
    else:
        url = build_news_url(q=q, gl=gl, hl=hl)
        country = (gl or "US").upper()
        try:
            html = scrape_html(
                url, country=country, languages=[f"{hl or 'en'}-{country}"]
            )
            feed, mode = parse(html, url)
        except CreditCeilingExceeded as exc:
            return _error(str(exc), status_code=429)
        except FirecrawlError as exc:
            return _error(str(exc), status_code=502)
        cache_set(
            fkey,
            {"mode": mode, "items": [it.model_dump() for it in feed]},
        )
        from_cache = False

    # Slice the requested page and resolve only its links to publisher URLs
    # (copy so the cached feed keeps original google redirect links).
    page = [it.model_copy() for it in feed[start : start + num]]
    mapping = resolve.resolve_many([it.link for it in page])
    for it in page:
        it.link = mapping.get(it.link, it.link)

    meta = SearchMetadata(
        id=search_id,
        status="Success",
        created_at=created_at,
        processed_at=_now(),
        total_time_taken=round(time.perf_counter() - started, 3),
        parse_mode=mode,
        cached=from_cache,
    )
    response = normalize.build_response(items=page, params=params, metadata=meta)
    return JSONResponse(response.model_dump(exclude_none=True))
