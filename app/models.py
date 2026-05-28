from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---- internal representation produced by parsers --------------------------

class ParsedItem(BaseModel):
    """Provider-agnostic news item emitted by the parsers, pre-normalization."""
    title: str
    link: str
    source: Optional[str] = None
    favicon: Optional[str] = None
    date: Optional[str] = None          # human-readable, e.g. "17 hours ago"
    iso_date: Optional[str] = None      # ISO 8601, used for sort/time filters
    snippet: Optional[str] = None
    thumbnail: Optional[str] = None


# ---- SearchApi-shaped response (google_news engine) -----------------------

class SearchMetadata(BaseModel):
    id: str
    status: Literal["Success", "Error", "Processing"]
    created_at: str
    request_time_taken: Optional[float] = None
    parsing_time_taken: Optional[float] = None
    total_time_taken: Optional[float] = None
    request_url: Optional[str] = None
    html_url: Optional[str] = None
    json_url: Optional[str] = None
    # non-breaking extensions
    provider: str = "firecrawl"
    parse_mode: Optional[Literal["selectors", "llm"]] = None
    cached: bool = False
    error: Optional[str] = None


class SearchParameters(BaseModel):
    engine: str = "google_news"
    q: Optional[str] = None
    location: Optional[str] = None
    location_used: Optional[str] = None
    uule: Optional[str] = None
    gl: Optional[str] = None
    hl: Optional[str] = None
    lr: Optional[str] = None
    cr: Optional[str] = None
    device: Optional[str] = None
    time_period: Optional[str] = None
    time_period_min: Optional[str] = None
    time_period_max: Optional[str] = None
    sort_by: Optional[str] = None
    nfpr: Optional[int] = None
    filter: Optional[int] = None
    page: Optional[int] = None


class SearchInformation(BaseModel):
    query_displayed: Optional[str] = None
    total_results: Optional[int] = None
    time_taken_displayed: Optional[float] = None
    detected_location: Optional[str] = None


class OrganicResult(BaseModel):
    position: int
    title: str
    link: str
    source: Optional[str] = None
    date: Optional[str] = None
    iso_date: Optional[str] = None
    snippet: Optional[str] = None
    favicon: Optional[str] = None
    thumbnail: Optional[str] = None


class TopStory(BaseModel):
    position: int
    title: str
    link: str
    source: Optional[str] = None
    date: Optional[str] = None
    iso_date: Optional[str] = None
    thumbnail: Optional[str] = None


class Pagination(BaseModel):
    current: int = 1
    next: Optional[str] = None
    other_pages: Optional[dict[str, str]] = None


class NewsResponse(BaseModel):
    search_metadata: SearchMetadata
    search_parameters: SearchParameters
    search_information: Optional[SearchInformation] = None
    organic_results: list[OrganicResult] = Field(default_factory=list)
    top_stories: list[TopStory] = Field(default_factory=list)
    pagination: Optional[Pagination] = None
