# mygnews — a SerpApi-compatible Google News API

A small, self-hosted news search API that returns results in the same JSON
shape as [SerpApi](https://serpapi.com/)'s Google engine, so existing SerpApi
clients can point at it with minimal changes.

It scrapes `news.google.com` through [Firecrawl](https://firecrawl.dev)
(JS rendering + stealth proxy), parses the result feed, resolves each article
to its **real publisher URL**, and serves a SerpApi-shaped response.

## Why Firecrawl + news.google.com

- A direct request to Google returns `403`/CAPTCHA without proxy and anti-bot
  handling. Firecrawl renders JS and rotates proxies to get clean HTML.
- The classic web SERP (`google.com/search?tbm=nws`) is **hard-blocked** even
  through a stealth proxy — it consistently returns Google's "unusual traffic"
  CAPTCHA page. `news.google.com` renders reliably, so it is the source here.

## Features

- **SerpApi-shaped response** — `search_metadata`, `search_parameters`,
  `news_results`, `serpapi_pagination`.
- **Publisher URLs** — Google's signed redirect links are decoded to the
  source URL via Google's `batchexecute` RPC (plain HTTP, no Firecrawl credits),
  resolved in parallel and cached, with graceful fallback to the Google link.
- **Hybrid parser** — fast deterministic CSS selectors, with a Firecrawl
  LLM-extract fallback only when selectors miss (DOM churn resilience).
- **Cost controls** — the parsed feed is cached per query, so paginating a
  query never re-scrapes; a daily Firecrawl credit ceiling guards the budget.

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
curl "http://localhost:8000/search?q=openai&gl=us&hl=en&num=5"
```

```jsonc
{
  "search_metadata": {
    "id": "…", "status": "Success",
    "provider": "firecrawl", "parse_mode": "selectors", "cached": false,
    "total_time_taken": 9.6
  },
  "search_parameters": { "engine": "google", "q": "openai", "tbm": "nws",
                         "gl": "us", "hl": "en", "start": 0, "num": 5 },
  "news_results": [
    {
      "position": 1,
      "title": "OpenAI Foundation commits $250 million …",
      "link": "https://www.reuters.com/business/openai-foundation-commits-…",
      "source": { "name": "Reuters", "icon": "https://…/faviconV2?url=…" },
      "date": "17 hours ago",
      "thumbnail": "https://news.google.com/api/attachments/…"
    }
  ],
  "serpapi_pagination": { "current": 1, "next": "5", "next_link": "/search?q=openai&…&start=5&num=5" }
}
```

## Query parameters

| Param      | Default | Description                                  |
|------------|---------|----------------------------------------------|
| `q`        | —       | Search query (required)                      |
| `gl`       | `us`    | Country code                                 |
| `hl`       | `en`    | UI language                                  |
| `start`    | `0`     | Result offset (pagination)                   |
| `num`      | `10`    | Results per page (1–100)                      |
| `no_cache` | `false` | Bypass the feed cache and force a fresh scrape |

`GET /health` reports liveness and `credits_used_today`.

## Configuration (`.env`)

| Key                              | Default   | Description                          |
|----------------------------------|-----------|--------------------------------------|
| `FIRECRAWL_API_KEY`              | —         | Firecrawl API key (required)         |
| `FIRECRAWL_PROXY`                | `stealth` | Firecrawl proxy mode                 |
| `CACHE_TTL_SECONDS`              | `600`     | Feed cache TTL                       |
| `FIRECRAWL_DAILY_CREDIT_CEILING` | `400`     | Hard daily cap on Firecrawl credits  |

## Caveats

- Scraping Google is against its Terms of Service; use accordingly.
- Selector classes on `news.google.com` are obfuscated and change over time;
  the LLM-extract fallback covers churn but costs extra Firecrawl credits.
- Publisher-URL resolution makes a couple of requests to `news.google.com` per
  article (cached 24h); at high volume watch for rate-limiting — it degrades to
  the Google redirect link rather than failing.
