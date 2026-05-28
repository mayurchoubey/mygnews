from __future__ import annotations

from typing import Optional

from bs4 import BeautifulSoup, Tag

from ..models import ParsedItem

# news.google.com renders each article around a headline anchor (a.JtKRv).
# Class names are obfuscated and rotate, so they are hints; the card boundary
# is found structurally (nearest ancestor holding both a <time> and a favicon).
_HEADLINE_SELECTOR = "a.JtKRv"
_SOURCE_SELECTOR = "div.vr1PYe"
_MAX_CLIMB = 12


def _has_favicon(node: Tag) -> bool:
    return any(
        "faviconV2" in (img.get("src") or "")
        for img in node.find_all("img")
        if isinstance(img, Tag)
    )


def _card_for(anchor: Tag) -> Tag:
    """Climb to the smallest ancestor that bounds a single article."""
    card = anchor
    climbs = 0
    while (
        card.parent is not None
        and climbs < _MAX_CLIMB
        and not (card.find("time") and _has_favicon(card))
    ):
        card = card.parent
        climbs += 1
    return card


def _dates(card: Tag) -> tuple[Optional[str], Optional[str]]:
    """Return (human_readable, iso) from the card's <time> element."""
    t = card.find("time")
    if not isinstance(t, Tag):
        return None, None
    human = t.get_text(strip=True) or None
    iso = t.get("datetime") or None
    return human, (str(iso) if iso else None)


def _source_name(card: Tag) -> Optional[str]:
    el = card.select_one(_SOURCE_SELECTOR)
    return el.get_text(strip=True) if isinstance(el, Tag) else None


def _icons(card: Tag) -> tuple[Optional[str], Optional[str]]:
    source_icon: Optional[str] = None
    thumbnail: Optional[str] = None
    for img in card.find_all("img"):
        if not isinstance(img, Tag):
            continue
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        if "faviconV2" in src:
            source_icon = source_icon or src
        else:
            thumbnail = thumbnail or src
    return source_icon, thumbnail


def parse(html: str) -> list[ParsedItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ParsedItem] = []
    seen: set[str] = set()

    for anchor in soup.select(_HEADLINE_SELECTOR):
        if not isinstance(anchor, Tag):
            continue
        link = str(anchor.get("href", "")).strip()
        title = anchor.get_text(" ", strip=True)
        if not title or not link.startswith("http") or link in seen:
            continue
        seen.add(link)

        card = _card_for(anchor)
        favicon, thumbnail = _icons(card)
        human_date, iso_date = _dates(card)
        items.append(
            ParsedItem(
                title=title,
                link=link,
                source=_source_name(card),
                favicon=favicon,
                date=human_date,
                iso_date=iso_date,
                thumbnail=thumbnail,
            )
        )
    return items
