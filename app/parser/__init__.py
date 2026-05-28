from __future__ import annotations

from typing import Literal

from ..config import get_settings
from ..models import ParsedItem
from . import llm_extract, selectors

ParseMode = Literal["selectors", "llm"]


def parse(html: str, url: str) -> tuple[list[ParsedItem], ParseMode]:
    """Hybrid parse: deterministic selectors first, LLM extract on miss.

    A "miss" is too few items (DOM churn / selector rot) or a hard parse error.
    The LLM path costs extra credits, so it stays the exception, not the rule.
    """
    threshold = get_settings().min_results_threshold

    try:
        items = selectors.parse(html)
    except Exception:
        items = []

    if len(items) >= threshold:
        return items, "selectors"

    # selector miss -> pay for the resilient path
    llm_items = llm_extract.parse(url)
    if len(llm_items) >= len(items):
        return llm_items, "llm"
    return items, "selectors"
