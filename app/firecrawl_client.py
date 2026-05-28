from __future__ import annotations

import time
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


GOOGLE_NEWS_HOST = "https://news.google.com"


def build_news_url(
    q: Optional[str] = None,
    gl: Optional[str] = None,
    hl: Optional[str] = None,
    topic_token: Optional[str] = None,
    publication_token: Optional[str] = None,
    story_token: Optional[str] = None,
    section_token: Optional[str] = None,
) -> tuple[str, str]:
    """Return (url, engine) for the requested news.google.com surface.

    Precedence mirrors SerpApi: story > publication > topic(+section) > query >
    headlines. news.google.com loads the full feed in one page; pagination is
    applied locally.
    """
    country = (gl or "US").upper()
    lang = hl or "en"
    locale = {"hl": lang, "gl": country, "ceid": f"{country}:{lang}"}

    if story_token:
        path, engine = f"/stories/{story_token}", "story"
    elif publication_token:
        path, engine = f"/publications/{publication_token}", "publication"
    elif topic_token:
        engine = "topic"
        path = f"/topics/{topic_token}"
        if section_token:
            path += f"/sections/{section_token}"
    elif q:
        return f"{GOOGLE_NEWS_BASE}?{urlencode({'q': q, **locale})}", "search"
    else:
        path, engine = "/home", "headlines"

    return f"{GOOGLE_NEWS_HOST}{path}?{urlencode(locale)}", engine


def _credit_cost(fmt: str) -> int:
    proxy = get_settings().firecrawl_proxy
    return _CREDIT_COST.get((fmt, proxy), 5)


# Transient Firecrawl statuses worth retrying (timeouts, rate limits, 5xx).
_RETRYABLE = {408, 429, 500, 502, 503, 504}


def _post_scrape(body: dict[str, Any], attempts: int = 3) -> dict[str, Any]:
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.firecrawl_api_key}",
        "Content-Type": "application/json",
    }
    last_err = "unknown error"
    for attempt in range(attempts):
        try:
            resp = httpx.post(
                f"{FIRECRAWL_BASE}/scrape",
                headers=headers,
                json=body,
                timeout=settings.request_timeout_seconds + 15,
            )
        except httpx.HTTPError as exc:
            last_err = f"request to Firecrawl failed: {exc}"
        else:
            if resp.status_code == 200:
                payload = resp.json()
                if payload.get("success"):
                    return payload.get("data", {})
                last_err = f"Firecrawl error: {payload}"
            else:
                last_err = f"Firecrawl returned {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in _RETRYABLE:
                    break
        if attempt + 1 < attempts:
            time.sleep(1.5 * (attempt + 1))
    raise FirecrawlError(last_err)


def scrape_html(
    url: str,
    country: str = "US",
    languages: Optional[list[str]] = None,
    mobile: bool = False,
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
        "mobile": mobile,
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
