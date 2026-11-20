# web-scraper

Modular Python 3.14 web discovery and article extraction engine built for downstream NLP pipelines. Discovers URLs across search/RSS sources with early-stop pagination, fetches pages politely using Chrome TLS impersonation (with optional headless stealth Chromium fallback), extracts clean prose and publication timestamps via `trafilatura` and `htmldate`, and emits strict Pydantic v2 `ArticleRecord` JSONL records to `stdout` or disk while logging structured UTC JSON telemetry to `stderr`.

```text
+-------------------+     +---------------------+     +-----------------------+     +-----------------------+
|     Discovery     | --> |    Stealth Fetch    | --> |      Extraction       | --> |         JSONL         |
| Google/Bing/DDG/  |     | curl_cffi (Chrome)  |     | trafilatura +         |     | ArticleRecord stdout/ |
| RSS + early-stop  |     | + opt-in Playwright |     | htmldate + dedup hash |     | file + stderr logs    |
+-------------------+     +---------------------+     +-----------------------+     +-----------------------+
```

## Architecture

| Module | Responsibility |
| --- | --- |
| `src/web_scraper/__init__.py` | Public API re-exports with PEP 562 lazy `run_scrape` loading to avoid `runpy` import warnings. |
| `src/web_scraper/models.py` | Strict Pydantic v2 data contracts (`ScrapeConfig`, `DiscoveryCandidate`, `ArticleRecord`, `ExtractionStatus`) and `JsonlWriter`. |
| `src/web_scraper/discovery.py` | Query builder (`site:` dorking, `after:`/`before:`), redirect unwrapper, 4 async adapters (`google`, `bing`, `duckduckgo`, `rss`), and `DiscoveryEngine` early-stop pagination. |
| `src/web_scraper/stealth.py` | `FetchResult`, `HttpFetcher` (`curl_cffi` Chrome TLS, UA rotation, jitter delay, 429/5xx exponential backoff), and `BrowserFetcher` (`playwright-stealth` v2 headless Chromium). |
| `src/web_scraper/extractor.py` | URL/domain/title normalization, SHA-256 syndication hash, and `extract_article` wrapping `trafilatura.bare_extraction` + `htmldate.find_date` with date/status fallback cascade. |
| `src/web_scraper/cli.py` | Async `run_scrape` orchestrator (semaphore concurrency, lazy browser fallback, stderr JSON telemetry) and `argparse` CLI entrypoint. |
| `src/web_scraper/py.typed` | PEP 561 marker advertising inline type annotations for downstream type checkers. |

## Quickstart

### Local (`uv`)

```bash
# Install locked dependencies
uv sync --locked

# Scrape to a JSONL file (telemetry logs go to stderr)
uv run python -m web_scraper.cli \
  --keyword "semiconductor supply chain" \
  --engines bing,google \
  --domains reuters.com,bbc.co.uk \
  --date-from 2025-01-01T00:00:00Z \
  --date-to 2025-12-31T23:59:59Z \
  --max-results 10 \
  --early-stop 0.8 \
  --concurrency 3 \
  --output data/sample.jsonl

# Stream pure JSONL to stdout with known-URL dedup and opt-in browser fallback
uv run playwright install chromium
uv run python -m web_scraper.cli \
  --keyword "semiconductor supply chain" \
  --engines duckduckgo,bing \
  --known-urls-file data/known_urls.txt \
  --browser-fallback \
  --output - > data/articles.jsonl
```

### Docker

Multi-stage `Dockerfile` (`ghcr.io/astral-sh/uv:python3.14-bookworm-slim` builder with `uv sync --frozen --no-dev --no-editable` into a non-root `python:3.14-slim-bookworm` runtime image):

```bash
# Build image
docker build -t web-scraper:dev .

# Verify CLI entrypoint
docker run --rm web-scraper:dev --help

# Run scrape (stdout = pure JSONL, stderr = JSON telemetry)
docker run --rm web-scraper:dev \
  --keyword "semiconductor supply chain" \
  --engines bing \
  --max-results 5 > data/docker_sample.jsonl
```

> Note: `--browser-fallback` is disabled by default and requires Chromium binaries installed via `playwright install chromium` (omitted from the slim runtime image to keep container size small).

### CLI Flags

| Flag | Default | Description |
| --- | --- | --- |
| `--keyword` | *(required)* | Target search phrase (`seed_keyword`). |
| `--engines` | `google,bing` | Comma-separated adapters: `google` (`google_news_rss`), `bing` (`bing_rss`), `duckduckgo` (`ddg`), `rss`. |
| `--domains` | `None` | Comma-separated whitelisted domains (dorked via `site:`) or direct RSS/Atom URLs for `rss`. |
| `--date-from`, `--date-to` | `None` | ISO-8601 backfill bounds (must be provided together). |
| `--max-results` | `10` | Hard cap on total candidates scraped per run. |
| `--early-stop` | `0.8` | Halt engine pagination when page `known_ratio >= threshold` (`0.0`–`1.0`). |
| `--known-urls-file` | `None` | Newline-delimited file of known URLs (`#` comments ignored). |
| `--output` | `-` | Output JSONL path, or `-` for `stdout`. |
| `--concurrency` | `3` | Maximum concurrent article fetches (`asyncio.Semaphore`). |
| `--browser-fallback` | `False` | Retry failed (403/429/error) or `<100`-word fetches once via lazy `BrowserFetcher`. |

## Testing & DevOps

```bash
# Offline unit test suite (62 tests, 0 network calls)
uv run pytest -q --tb=short --no-header

# Lint & format checks (Ruff py314, line-length 100, rules E/F/I/UP/B)
uv run ruff check --quiet
uv run ruff format --check --quiet

# Live stealth verification against bot.sannysoft.com (saves data/sannysoft.png + prints compact JSON)
uv run playwright install chromium
uv run python scripts/audit_sannysoft.py
```

### GitHub Actions CI (`.github/workflows/ci.yml`)

Runs automatically on `push` and `pull_request` (`ubuntu-latest`, `contents: read`):
- **`lint-and-test`**: SHA-pinned `actions/checkout` (v7.0.1) and `astral-sh/setup-uv` (v10.3.3, cache enabled), `uv sync --locked`, `ruff check`, `ruff format --check`, and `pytest`.
- **`docker-build`**: Builds the production `Dockerfile` (`docker build -t web-scraper:ci .`) and runs `docker run --rm web-scraper:ci --help`.
