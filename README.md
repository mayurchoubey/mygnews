# mygnews — a SerpApi-compatible Google News API

A self-hosted Google News API whose request parameters and JSON response mirror
[SerpApi](https://serpapi.com/google-news-api)'s `google_news` engine, so
existing SerpApi clients can point at it with minimal changes.

It scrapes `news.google.com` through [Firecrawl](https://firecrawl.dev)
(JS rendering + stealth proxy), parses the result feed, resolves each article
to its **real publisher URL**, and serves a SerpApi-shaped response.

A SearchApi.io-shaped response is also available via `?output=searchapi`.

## Why Firecrawl + news.google.com

- A direct request to Google returns `403`/CAPTCHA without proxy and anti-bot
  handling. Firecrawl renders JS and rotates proxies to get clean HTML.
- The classic web SERP (`google.com/search?tbm=nws`) is **hard-blocked** even
  through a stealth proxy (it returns Google's "unusual traffic" CAPTCHA), so
  data is sourced from `news.google.com`, which renders reliably.

## Engines

The engine is chosen by which parameter you pass (precedence top to bottom):

| Pass… | Engine | news.google.com surface |
|-------|--------|--------------------------|
| `story_token` | full-coverage story | `/stories/{token}` |
| `publication_token` | a publication's feed | `/publications/{token}` |
| `topic_token` (+ `section_token`) | a topic / subsection | `/topics/{token}[/sections/{s}]` |
| `q` | keyword search | `/search?q=…` |
| _(none)_ | top headlines | `/home` |

Tokens are discovered from `menu_links` (topic nav) and from `news_results[].story_token`
in any response — pass them back to drill in, just like SerpApi.

## Features

- **SerpApi-shaped response** — `search_metadata`, `search_parameters`,
  `news_results` (`source: {name, icon}`, `thumbnail`, `date`, `story_token`),
  `menu_links`, `serpapi_pagination`.
- **Publisher URLs** — Google's signed redirect links are decoded to the
  source URL via Google's `batchexecute` RPC (plain HTTP, no Firecrawl credits),
  resolved in parallel and cached, with graceful fallback to the Google link.
- **Time filtering** (`time_period`, `time_period_min`/`max`) and **sorting**
  (`sort_by=most_recent`), applied against each result's date.
- **Hybrid parser** — deterministic CSS selectors with a Firecrawl LLM-extract
  fallback when selectors miss; transient scrape failures are retried.
- **Cost controls** — per-query feed cache (sort/page/filter reuse one scrape)
  and a daily Firecrawl credit ceiling.

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

## Examples

```bash
curl "http://localhost:8000/search?q=openai&gl=us&hl=en"          # keyword search
curl "http://localhost:8000/search?gl=us&hl=en"                   # top headlines
curl "http://localhost:8000/search?topic_token=CAAq...&gl=us"     # browse a topic
curl "http://localhost:8000/search?story_token=CAAq...&gl=us"     # full coverage
curl "http://localhost:8000/search?q=openai&output=searchapi"     # SearchApi shape
```

```jsonc
{
  "search_metadata": {
    "id": "…", "status": "Success",
    "total_time_taken": 8.4,
    "google_news_url": "https://news.google.com/search?q=openai&…",
    "provider": "firecrawl", "parse_mode": "selectors", "cached": false
  },
  "search_parameters": { "engine": "google_news", "q": "openai", "gl": "us", "hl": "en" },
  "news_results": [
    {
      "position": 1,
      "title": "OpenAI Foundation commits $250 million …",
      "source": { "name": "Reuters", "icon": "https://…/faviconV2?url=…" },
      "link": "https://www.reuters.com/business/openai-foundation-commits-…",
      "thumbnail": "https://news.google.com/api/attachments/…",
      "date": "17 hours ago"
    }
  ],
  "menu_links": [
    { "title": "World", "topic_token": "CAAq…",
      "serpapi_link": "/search?engine=google_news&topic_token=CAAq…&gl=us&hl=en" }
  ],
  "serpapi_pagination": { "current": 1, "next": "/search?…&page=2",
                          "other_pages": { "2": "…", "3": "…" } }
}
```

## Request parameters

| Param               | Default   | Description                                       |
|---------------------|-----------|---------------------------------------------------|
| `q`                 | —         | Query (omit for headlines); supports `site:`, `when:`, `after:`, `before:` |
| `topic_token`       | —         | Browse a topic                                    |
| `publication_token` | —         | Browse a publication's feed                       |
| `story_token`       | —         | Full coverage of a story                          |
| `section_token`     | —         | A subsection of a topic                           |
| `gl`                | `us`      | Country code                                      |
| `hl`                | `en`      | Interface language                                |
| `location`, `uule`, `lr`, `cr` | — | Accepted and echoed (best-effort geo/lang)   |
| `device`            | `desktop` | `desktop` \| `mobile` \| `tablet`                 |
| `time_period`       | —         | `last_hour` … `last_year`                         |
| `time_period_min`/`max` | —     | `MM/DD/YYYY`                                       |
| `sort_by`           | relevance | `most_recent`                                     |
| `nfpr`, `filter`    | —         | Accepted and echoed                               |
| `page`              | `1`       | 1-based page number                               |
| `num`               | `10`      | Results per page (extension; 1–100)               |
| `output`            | `serpapi` | `serpapi` \| `searchapi`                          |
| `no_cache`          | `false`   | Bypass the feed cache                             |

`GET /health` reports liveness and `credits_used_today`.

## Configuration (`.env`)

| Key                              | Default   | Description                          |
|----------------------------------|-----------|--------------------------------------|
| `FIRECRAWL_API_KEY`              | —         | Firecrawl API key (required)         |
| `FIRECRAWL_PROXY`                | `stealth` | Firecrawl proxy mode                 |
| `CACHE_TTL_SECONDS`              | `600`     | Feed cache TTL                       |
| `FIRECRAWL_DAILY_CREDIT_CEILING` | `400`     | Hard daily cap on Firecrawl credits  |

## Parity notes & caveats

- **Data source differs.** Parameters and response schema match SerpApi's
  `google_news`, but data comes from `news.google.com` (the `tbm=nws` SERP is
  unscrapeable). Result sets and ordering won't be byte-identical.
- **`menu_links` and per-result `story_token` are best-effort** — the topic nav
  and cluster tokens render only on `/home` and topic pages (not keyword search),
  and only entries that render with text are captured.
- **No `snippet`** — news.google.com cards carry no description text (SerpApi's
  news engine usually omits it too).
- **Scale**: in-memory single-process cache; publisher-URL resolution makes a
  couple of cached requests per article and can rate-limit under heavy traffic.
- Scraping Google is against its Terms of Service; use accordingly.
