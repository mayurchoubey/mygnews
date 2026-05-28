from __future__ import annotations

import hashlib
import json
import threading
from datetime import date
from typing import Any, Optional

from cachetools import TTLCache

from .config import get_settings


class _CreditCeilingExceeded(RuntimeError):
    pass


CreditCeilingExceeded = _CreditCeilingExceeded


class CreditMeter:
    """Naive daily credit counter with a date-based reset.

    Single-process only. Protects the Firecrawl budget from a runaway loop.
    """

    def __init__(self, ceiling: int) -> None:
        self._ceiling = ceiling
        self._day = date.today()
        self._used = 0
        self._lock = threading.Lock()

    def _maybe_reset(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self._used = 0

    def charge(self, units: int) -> None:
        with self._lock:
            self._maybe_reset()
            if self._used + units > self._ceiling:
                raise CreditCeilingExceeded(
                    f"daily Firecrawl credit ceiling reached "
                    f"({self._used}/{self._ceiling})"
                )
            self._used += units

    @property
    def used(self) -> int:
        with self._lock:
            self._maybe_reset()
            return self._used


_settings = get_settings()
_cache: TTLCache = TTLCache(
    maxsize=_settings.cache_max_entries, ttl=_settings.cache_ttl_seconds
)
_cache_lock = threading.Lock()
credit_meter = CreditMeter(_settings.firecrawl_daily_credit_ceiling)


def cache_key(params: dict[str, Any]) -> str:
    blob = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def cache_get(key: str) -> Optional[Any]:
    with _cache_lock:
        return _cache.get(key)


def cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = value


def feed_key(q: str, gl: Optional[str], hl: Optional[str]) -> str:
    # keyed on the query only (not start/num) so every page of a query
    # reuses a single Firecrawl scrape.
    return cache_key({"q": q, "gl": gl, "hl": hl})
