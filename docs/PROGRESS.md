# Progress

## CompletedSlices
- **Slice 1 (DevOps Skeleton)**:
  - Locked core/dev deps via `uv`, scaffolded `src/web_scraper/`, Ruff config, smoke test, `.dockerignore`, multi-stage non-root `Dockerfile`.
- **Slice 2 (Stealth Layer & Sannysoft Lab)**:
  - Locked `playwright` & `playwright-stealth>=2.0`; implemented `FetchResult`, `HttpFetcher`, `BrowserFetcher` (`Stealth().use_async`), `scripts/audit_sannysoft.py`, and `tests/test_stealth.py`.
- **Slice 3 (Data Contracts & Extraction Pipeline)**:
  - Implemented strict Pydantic v2 models + `JsonlWriter` (`models.py`), `trafilatura` + `htmldate` extraction & date/status fallback cascade (`extractor.py`), and `tests/test_{models,extractor}.py`.
- **Slice 4 (Discovery Engine & Early-Stop Pagination)**:
  - Silenced `urllib3.exceptions.DependencyWarning` in `pyproject.toml`.
  - Implemented `build_search_query`, `unwrap_redirect_url`, `SearchAdapter`, 4 adapters (`GoogleNewsRssAdapter`, `BingNewsRssAdapter`, `DuckDuckGoAdapter`, `DirectRssAdapter`), and `DiscoveryEngine` with deduplication, `known_urls` (set/callback), `early_stop_threshold`, and `max_results` in `src/web_scraper/discovery.py`.
  - Added offline tests in `tests/test_discovery.py`; verified `pytest` (56 passed, 0 warnings), `ruff check`, `ruff format --check`.

## NextSlice
- **Slice 5 (CLI & End-to-End Orchestration)**:
  - Wire discovery -> fetch (HTTP with browser fallback) -> extraction -> JSONL/adapter output in `src/web_scraper/cli.py` and public package exports (`__init__.py`).

## KnownIssues
- Live Sannysoft audit requires `uv run playwright install chromium` + network run of `scripts/audit_sannysoft.py`.
- `uv`/`rtk` binaries live outside sandbox `PATH`; sandboxed checks run via `.venv/bin/{pytest,ruff}`.
