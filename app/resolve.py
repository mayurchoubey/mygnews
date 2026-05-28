from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from cachetools import TTLCache

# news.google.com article links (.../read/CBMi... or .../articles/CBMi...) are
# signed redirect blobs. The publisher URL is recovered by reading each
# article page's signature/timestamp and asking Google's batchexecute RPC to
# decode it. Plain HTTP works here (no Firecrawl credits); a consent cookie
# avoids the EU interstitial.

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_COOKIES = {"CONSENT": "YES+cb", "SOCS": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg"}
_BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"

# Publisher URLs are stable; cache them for a day to avoid re-resolving.
_cache: TTLCache = TTLCache(maxsize=8192, ttl=86400)
_lock = threading.Lock()


def _is_gnews_link(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host.endswith("news.google.com")


def _article_id(url: str) -> str:
    return urlparse(url).path.split("/")[-1]


def _decode_one(client: httpx.Client, google_url: str) -> str:
    art_id = _article_id(google_url)

    page = client.get(f"https://news.google.com/rss/articles/{art_id}")
    page.raise_for_status()
    div = BeautifulSoup(page.text, "lxml").select_one("c-wiz > div")
    if div is None:
        raise ValueError("signature block not found")
    sig = div.get("data-n-a-sg")
    ts = div.get("data-n-a-ts")
    gid = div.get("data-n-a-id")
    if not (sig and ts and gid):
        raise ValueError("missing decode params")

    inner = json.dumps(
        [
            "garturlreq",
            [
                ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                 None, None, None, None, None, 0, 1],
                "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0,
            ],
            gid, ts, sig,
        ]
    )
    freq = json.dumps([[["Fbv4je", inner, None, "generic"]]])
    resp = client.post(
        _BATCH_URL,
        data={"f.req": freq},
        headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"},
    )
    resp.raise_for_status()
    parsed = json.loads(resp.text.split("\n\n")[1])
    return json.loads(parsed[0][2])[1]


def _resolve(client: httpx.Client, google_url: str) -> str:
    if not _is_gnews_link(google_url):
        return google_url
    with _lock:
        cached = _cache.get(google_url)
    if cached:
        return cached
    try:
        publisher = _decode_one(client, google_url)
    except Exception:
        return google_url  # graceful fallback: keep the Google link
    with _lock:
        _cache[google_url] = publisher
    return publisher


def resolve_many(urls: list[str], max_workers: int = 8) -> dict[str, str]:
    """Map each google news link to its publisher URL (or itself on failure)."""
    if not urls:
        return {}
    out: dict[str, str] = {}
    with httpx.Client(
        headers={"User-Agent": _UA},
        cookies=_COOKIES,
        follow_redirects=True,
        timeout=10,
    ) as client:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_resolve, client, u): u for u in urls}
            for fut, src in futures.items():
                try:
                    out[src] = fut.result()
                except Exception:
                    out[src] = src
    return out
