from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

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


def _path_token(href: str, segment: str) -> Optional[str]:
    parts = [p for p in urlparse(href).path.split("/") if p]
    if len(parts) >= 2 and parts[0] == segment:
        return parts[1]
    return None


def _story_token(card: Tag) -> Optional[str]:
    """Best-effort: a /stories/ link inside the tight card = its cluster token."""
    for a in card.find_all("a", href=True):
        tok = _path_token(str(a.get("href", "")), "stories")
        if tok:
            return tok
    return None


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
                story_token=_story_token(card),
            )
        )
    return items


def parse_menu(html: str) -> list[tuple[str, str]]:
    """Extract the topic navigation as (title, topic_token) pairs.

    Best-effort: only nav entries that render with text are captured (the
    icon-only / deferred entries are skipped).
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        token = _path_token(str(a.get("href", "")), "topics")
        if not token or token in seen:
            continue
        title = a.get_text(" ", strip=True) or a.get("aria-label")
        if not title:
            continue
        seen.add(token)
        out.append((str(title), token))
    return out
