# Standalone Web Scraper Specification

## 1. Objective
Build a modular web discovery and article extraction engine. It accepts search parameters, queries search engines or targeted news portals, extracts clean article text and metadata, and outputs structured records for a downstream NLP pipeline.

## 2. Input Parameters (Control Interface)
The scraper must accept the following runtime configuration:
- `seed_keyword` (string): Target search phrase.
- `search_engines` (list[string]): Engines to query (e.g., Google, Bing, DuckDuckGo, or RSS).
- `target_domains` (list[string], optional): Whitelisted domains. If provided, restrict search via `site:domain.com` dorking or direct feed parsing.
- `date_range` (tuple[ISO-8601, ISO-8601], optional): Start and end dates for historical backfill via search query parameters.
- `max_results` (int): Hard cap on total articles to scrape per job.
- `early_stop_threshold` (float, `0.0`–`1.0`): Stop paginating a search engine if the ratio of already-known URLs on a results page meets or exceeds this value.
- `known_urls` (set[string] or callback): Existing URLs from downstream storage used to evaluate `early_stop_threshold` and skip redundant page fetches.

## 3. Output Data Contract

### Primary Fields (Required)
- `canonical_url` (string): Normalized URL stripped of tracking parameters (`utm_*`, `fbclid`).
- `seed_keyword` (string): The input `seed_keyword` that surfaced this record.
- `title` (string): Clean headline without site-name suffixes.
- `clean_body` (string): Main article prose stripped of HTML, navbars, ads, and boilerplate.
- `published_at` (ISO-8601 UTC): Publication timestamp. *Fallback cascade: JSON-LD/meta tag $\rightarrow$ DOM `<time>` or URL date regex $\rightarrow$ SERP snippet timestamp $\rightarrow$ `scraped_at`.*
- `scraped_at` (ISO-8601 UTC): Execution timestamp.
- `extraction_status` (enum): `SUCCESS`, `PARTIAL_NO_DATE`, `TOO_SHORT_OR_PAYWALL` (<100 words), or `FAILED`. Failed URLs must still be returned so downstream storage can blacklist them from future runs.

### Secondary Fields (Enrichment & Deduplication)
- `source_domain` (string): Base domain (e.g., `reuters.com`).
- `is_date_estimated` (bool): `true` if `published_at` fell back to SERP snippet or `scraped_at`.
- `content_hash` (string): SHA-256 hash of normalized `title` + first 500 chars of `clean_body` (detects syndicated wire duplicates across different URLs).
- `description` (string, nullable): Meta description or lead paragraph.
- `serp_snippet` (string, nullable): Raw text snippet captured from the search results page before visiting the URL.
- `serp_rank` (int): 1-based position on the search engine results page.
- `search_engine` (string): Specific engine that discovered the URL.
- `language` (string, nullable): ISO-639-1 code (`en`, `id`, etc.).
- `word_count` (int): Token/word count of `clean_body`.

## 4. Operational Boundaries
- **Polite Crawling:** Implement rate limiting, randomized delays, user-agent rotation, and exponential backoff on HTTP 429/5xx.
- **No Hard Circumvention:** Do not build CAPTCHA solvers, login flows, or heavy anti-bot bypasses (Cloudflare Turnstile/DataDome). Log blocked URLs as `FAILED` and move on.
- **Decoupled Storage:** Output records via a clean interface (JSONL, in-memory objects, or adapter pattern) without hardcoding downstream database schemas.