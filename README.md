# mygnews — a SearchApi-compatible Google News API

A small, self-hosted news search API whose request parameters and JSON response
mirror [SearchApi.io](https://www.searchapi.io/google-news)'s `google_news`
engine, so existing SearchApi clients can point at it with minimal changes.

It scrapes `news.google.com` through [Firecrawl](https://firecrawl.dev)
(JS rendering + stealth proxy), parses the result feed, resolves each article
to its **real publisher URL**, and serves a SearchApi-shaped response.

## Why Firecrawl + news.google.com

- A direct request to Google returns `403`/CAPTCHA without proxy and anti-bot
  handling. Firecrawl renders JS and rotates proxies to get clean HTML.
- SearchApi's `google_news` engine is built on the classic web SERP
  (`google.com/search?tbm=nws`), which is **hard-blocked** even through a
  stealth proxy (it consistently returns Google's "unusual traffic" CAPTCHA).
  So mygnews matches the SearchApi **API surface** while sourcing data from
  `news.google.com`, which renders reliably.

## Features

- **SearchApi-shaped response** — `search_metadata`, `search_parameters`,
  `search_information`, `organic_results`, `top_stories`, `pagination`.
- **Publisher URLs** — Google's signed redirect links are decoded to the
  source URL via Google's `batchexecute` RPC (plain HTTP, no Firecrawl credits),
  resolved in parallel and cached, with graceful fallback to the Google link.
- **Time filtering** — `time_period` (last_hour…last_year) and
  `time_period_min`/`max` (`MM/DD/YYYY`), applied via Google date operators and
  guaranteed client-side against each result's `iso_date`.
- **Sorting** — `sort_by=most_recent` reorders by `iso_date`.
- **Hybrid parser** — fast deterministic CSS selectors, with a Firecrawl
  LLM-extract fallback only when selectors miss (DOM-churn resilience).
- **Cost controls** — the parsed feed is cached per query, so sort/page/filter
  variations never re-scrape; a daily Firecrawl credit ceiling guards the budget.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then put your Firecrawl key in FIRECRAWL_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

## Example

```bash
curl "http://localhost:8000/search?q=tesla&gl=us&hl=en&num=5&sort_by=most_recent"
```

```jsonc
{
  "search_metadata": {
    "id": "…", "status": "Success",
    "request_time_taken": 7.18, "parsing_time_taken": 0.06,
    "total_time_taken": 8.4, "request_url": "https://news.google.com/search?…",
    "provider": "firecrawl", "parse_mode": "selectors", "cached": false
  },
  "search_parameters": { "engine": "google_news", "q": "tesla",
                         "gl": "us", "hl": "en", "device": "desktop",
                         "sort_by": "most_recent", "page": 1 },
  "search_information": { "query_displayed": "tesla", "total_results": 105,
                          "detected_location": "US" },
  "organic_results": [
    {
      "position": 1,
      "title": "Tesla autopilot sinks in pond …",
      "link": "https://www.fox13news.com/news/tesla-autopilot-…",
      "source": "FOX 13 Tampa Bay",
      "date": "2 hours ago",
      "iso_date": "2026-05-28T08:39:02Z",
      "favicon": "https://…/faviconV2?url=…",
      "thumbnail": "https://news.google.com/api/attachments/…"
    }
  ],
  "top_stories": [ { "position": 1, "title": "…", "link": "…", "source": "…" } ],
  "pagination": { "current": 1, "next": "/search?…&page=2",
                  "other_pages": { "2": "/search?…&page=2", "3": "…" } }
}
```

## Request parameters (SearchApi `google_news` compatible)

| Param             | Default   | Description                                            |
|-------------------|-----------|--------------------------------------------------------|
| `q`               | —         | Query (required); supports `site:`, `when:`, `after:`, `before:` |
| `gl`              | `us`      | Country code                                           |
| `hl`              | `en`      | Interface language                                     |
| `location`        | —         | Canonical location (echoed as `location_used`)         |
| `uule`            | —         | Google-encoded location                                |
| `lr`              | —         | Document language, e.g. `lang_en`                      |
| `cr`              | —         | Country restriction, e.g. `countryUS`                  |
| `device`          | `desktop` | `desktop` \| `mobile` \| `tablet`                      |
| `time_period`     | —         | `last_hour` \| `last_day` \| `last_week` \| `last_month` \| `last_year` |
| `time_period_min` | —         | Start date `MM/DD/YYYY`                                |
| `time_period_max` | —         | End date `MM/DD/YYYY`                                   |
| `sort_by`         | relevance | `most_recent`                                          |
| `nfpr`            | —         | `1` to exclude auto-corrected results                  |
| `filter`          | —         | `0` to disable dedup / host-crowding                   |
| `page`            | `1`       | 1-based page number                                    |
| `num`             | `10`      | Results per page (extension; 1–100)                    |
| `no_cache`        | `false`   | Bypass the feed cache and force a fresh scrape         |

`GET /health` reports liveness and `credits_used_today`.

## Configuration (`.env`)

| Key                              | Default   | Description                          |
|----------------------------------|-----------|--------------------------------------|
| `FIRECRAWL_API_KEY`              | —         | Firecrawl API key (required)         |
| `FIRECRAWL_PROXY`                | `stealth` | Firecrawl proxy mode                 |
| `CACHE_TTL_SECONDS`              | `600`     | Feed cache TTL                       |
| `FIRECRAWL_DAILY_CREDIT_CEILING` | `400`     | Hard daily cap on Firecrawl credits  |

## Parity notes & caveats

- **Data source differs.** mygnews matches SearchApi's `google_news` parameters
  and response schema, but data comes from `news.google.com` (the `tbm=nws`
  SERP is unscrapeable). Result sets and ordering will not be byte-identical.
- **`snippet` is usually absent.** news.google.com search cards carry no
  description text, so `organic_results[].snippet` is typically omitted. The
  field is supported when the LLM-extract fallback recovers it.
- **`html_url`/`json_url`** are not provided — raw artifacts aren't persisted.
- **Token-based modes** (`topic_token`, `publication_token`, `story_token`,
  `section_token`) belong to SearchApi's separate `google_news_portal` engine,
  not `google_news`, so they are out of scope here.
- Scraping Google is against its Terms of Service; use accordingly. Selector
  classes change over time (the LLM fallback covers churn at extra credit cost),
  and publisher-URL resolution makes a couple of cached requests per article.
