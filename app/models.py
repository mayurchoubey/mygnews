from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---- internal representation produced by parsers --------------------------

class ParsedItem(BaseModel):
    """Provider-agnostic news item emitted by the parsers, pre-normalization."""
    title: str
    link: str
    source_name: Optional[str] = None
    source_icon: Optional[str] = None
    date: Optional[str] = None
    snippet: Optional[str] = None
    thumbnail: Optional[str] = None


# ---- SerpApi-shaped response ----------------------------------------------

class SearchMetadata(BaseModel):
    id: str
    status: Literal["Success", "Error", "Processing"]
    created_at: str
    processed_at: Optional[str] = None
    total_time_taken: Optional[float] = None
    # non-breaking extensions
    provider: str = "firecrawl"
    parse_mode: Optional[Literal["selectors", "llm"]] = None
    cached: bool = False
    error: Optional[str] = None


class SearchParameters(BaseModel):
    engine: str = "google"
    q: str
    tbm: str = "nws"
    gl: Optional[str] = None
    hl: Optional[str] = None
    start: Optional[int] = None
    num: Optional[int] = None


class Source(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None


class NewsResult(BaseModel):
    position: int
    title: str
    link: str
    source: Source = Field(default_factory=Source)
    date: Optional[str] = None
    snippet: Optional[str] = None
    thumbnail: Optional[str] = None


class Pagination(BaseModel):
    current: int = 1
    next: Optional[str] = None
    next_link: Optional[str] = None


class NewsResponse(BaseModel):
    search_metadata: SearchMetadata
    search_parameters: SearchParameters
    news_results: list[NewsResult] = Field(default_factory=list)
    serpapi_pagination: Optional[Pagination] = None
