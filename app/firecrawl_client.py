from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from .cache import credit_meter
from .config import get_settings

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
GOOGLE_NEWS_BASE = "https://news.google.com/search"

# Rough credit estimates so the daily ceiling guard is meaningful.
# Stealth proxy is the expensive multiplier; json extract runs an LLM pass.
_CREDIT_COST = {
    ("html", "basic"): 1,
    ("html", "stealth"): 5,
    ("html", "auto"): 5,
    ("json", "basic"): 5,
    ("json", "stealth"): 9,
    ("json", "auto"): 9,
}


class FirecrawlError(RuntimeError):
    pass


def build_news_url(
    q: str,
    gl: Optional[str] = None,
    hl: Optional[str] = None,
) -> str:
    # news.google.com loads the full result feed in one page; pagination
    # (start/num) is applied locally rather than via URL params.
    country = (gl or "US").upper()
    lang = hl or "en"
    params: dict[str, Any] = {
        "q": q,
        "hl": lang,
        "gl": country,
        "ceid": f"{country}:{lang}",
    }
    return f"{GOOGLE_NEWS_BASE}?{urlencode(params)}"


def _credit_cost(fmt: str) -> int:
    proxy = get_settings().firecrawl_proxy
    return _CREDIT_COST.get((fmt, proxy), 5)


def _post_scrape(body: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.firecrawl_api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.post(
            f"{FIRECRAWL_BASE}/scrape",
            headers=headers,
            json=body,
            timeout=settings.request_timeout_seconds + 10,
        )
    except httpx.HTTPError as exc:
        raise FirecrawlError(f"request to Firecrawl failed: {exc}") from exc

    if resp.status_code != 200:
        raise FirecrawlError(
            f"Firecrawl returned {resp.status_code}: {resp.text[:300]}"
        )
    payload = resp.json()
    if not payload.get("success"):
        raise FirecrawlError(f"Firecrawl error: {payload}")
    return payload.get("data", {})


def scrape_html(
    url: str,
    country: str = "US",
    languages: Optional[list[str]] = None,
) -> str:
    """Render the page and return raw HTML.

    news.google.com is a JS/Angular app, so JS rendering (waitFor) and proxy
    geo-routing are required to get the hydrated result feed.
    """
    settings = get_settings()
    credit_meter.charge(_credit_cost("html"))
    body = {
        "url": url,
        "formats": ["html"],
        "proxy": settings.firecrawl_proxy,
        "timeout": settings.request_timeout_seconds * 1000,
        "onlyMainContent": False,
        "waitFor": 3000,
        "location": {
            "country": country,
            "languages": languages or ["en-US"],
        },
    }
    data = _post_scrape(body)
    html = data.get("html") or data.get("rawHtml")
    if not html:
        raise FirecrawlError("Firecrawl response contained no HTML")
    return html


def extract_json(url: str, schema: dict[str, Any], prompt: str) -> dict[str, Any]:
    """LLM-backed structured extraction, used only when selectors miss."""
    settings = get_settings()
    credit_meter.charge(_credit_cost("json"))
    body = {
        "url": url,
        "formats": ["json"],
        "proxy": settings.firecrawl_proxy,
        "timeout": settings.request_timeout_seconds * 1000,
        "waitFor": 3000,
        "location": {"country": "US", "languages": ["en-US"]},
        "jsonOptions": {"schema": schema, "prompt": prompt},
    }
    data = _post_scrape(body)
    extracted = data.get("json")
    if extracted is None:
        raise FirecrawlError("Firecrawl json extraction returned nothing")
    return extracted
