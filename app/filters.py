from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import ParsedItem

# Maps SearchApi time_period values to (google query operator, lookback delta).
_PERIODS: dict[str, tuple[str, timedelta]] = {
    "last_hour": ("when:1h", timedelta(hours=1)),
    "last_day": ("when:1d", timedelta(days=1)),
    "last_week": ("when:7d", timedelta(days=7)),
    "last_month": ("when:30d", timedelta(days=30)),
    "last_year": ("when:1y", timedelta(days=365)),
}


def _to_iso_day(mmddyyyy: str) -> Optional[str]:
    try:
        return datetime.strptime(mmddyyyy, "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def build_query(
    q: str,
    time_period: Optional[str],
    time_period_min: Optional[str],
    time_period_max: Optional[str],
) -> str:
    """Append Google News date operators so the scrape pre-filters by date."""
    parts = [q]
    if time_period and time_period in _PERIODS:
        parts.append(_PERIODS[time_period][0])
    if time_period_min and (d := _to_iso_day(time_period_min)):
        parts.append(f"after:{d}")
    if time_period_max and (d := _to_iso_day(time_period_max)):
        parts.append(f"before:{d}")
    return " ".join(parts)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def filter_by_time(
    items: list[ParsedItem],
    time_period: Optional[str],
    time_period_min: Optional[str],
    time_period_max: Optional[str],
) -> list[ParsedItem]:
    """Client-side guarantee on top of the query operators, using iso_date."""
    if not (time_period or time_period_min or time_period_max):
        return items

    now = datetime.now(timezone.utc)
    lo: Optional[datetime] = None
    hi: Optional[datetime] = None
    if time_period and time_period in _PERIODS:
        lo = now - _PERIODS[time_period][1]
    if time_period_min and (d := _to_iso_day(time_period_min)):
        lo = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
    if time_period_max and (d := _to_iso_day(time_period_max)):
        hi = datetime.fromisoformat(d).replace(tzinfo=timezone.utc) + timedelta(days=1)

    kept: list[ParsedItem] = []
    for it in items:
        dt = _parse_iso(it.iso_date)
        if dt is None:
            continue  # can't verify the date under an active filter
        if lo and dt < lo:
            continue
        if hi and dt > hi:
            continue
        kept.append(it)
    return kept


def sort_items(items: list[ParsedItem], sort_by: Optional[str]) -> list[ParsedItem]:
    if sort_by != "most_recent":
        return items
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return sorted(
        items,
        key=lambda it: _parse_iso(it.iso_date) or epoch,
        reverse=True,
    )
