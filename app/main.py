from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from . import normalize, resolve
from .cache import CreditCeilingExceeded, cache_get, cache_key, cache_set, credit_meter
from .firecrawl_client import FirecrawlError, build_news_url, scrape_html
from .models import NewsResponse, SearchMetadata, SearchParameters
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
    key = cache_key(params.model_dump())

    if not no_cache:
        hit = cache_get(key)
        if hit is not None:
            hit = dict(hit)
            meta = dict(hit["search_metadata"])
            meta["cached"] = True
            meta["id"] = search_id
            meta["processed_at"] = _now()
            hit["search_metadata"] = meta
            return JSONResponse(hit)

    url = build_news_url(q=q, gl=gl, hl=hl)

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

    try:
        html = scrape_html(url, country=(gl or "US").upper(), languages=[f"{hl or 'en'}-{(gl or 'US').upper()}"])
        items, mode = parse(html, url)
    except CreditCeilingExceeded as exc:
        return _error(str(exc), status_code=429)
    except FirecrawlError as exc:
        return _error(str(exc), status_code=502)

    # news.google.com returns the full feed in one page; paginate locally,
    # then resolve only this page's links to publisher URLs.
    page = items[start : start + num]
    mapping = resolve.resolve_many([it.link for it in page])
    for it in page:
        it.link = mapping.get(it.link, it.link)
    items = page

    meta = SearchMetadata(
        id=search_id,
        status="Success",
        created_at=created_at,
        processed_at=_now(),
        total_time_taken=round(time.perf_counter() - started, 3),
        parse_mode=mode,
        cached=False,
    )
    response = normalize.build_response(items=items, params=params, metadata=meta)
    payload = response.model_dump(exclude_none=True)
    cache_set(key, payload)
    return JSONResponse(payload)
