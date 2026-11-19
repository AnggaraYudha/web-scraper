# Progress

## CompletedSlices
- **Slice 1 (DevOps Skeleton)**:
  - Locked runtime (`pydantic>=2.10`, `trafilatura`, `htmldate`, `curl_cffi`) and dev (`pytest`, `pytest-asyncio`, `ruff`) deps; scaffolded `src/web_scraper/`, Ruff config, smoke test, `.dockerignore`, multi-stage non-root `Dockerfile`.
- **Slice 2 (Stealth Layer & Sannysoft Lab)**:
  - Set `asyncio_default_fixture_loop_scope = "function"`; locked `playwright` & `playwright-stealth>=2.0`.
  - Implemented `FetchResult`, `HttpFetcher`, `BrowserFetcher` (`Stealth().use_async(async_playwright())` v2) in `src/web_scraper/stealth.py`, `scripts/audit_sannysoft.py`, and offline tests in `tests/test_stealth.py`.
- **Slice 3 (Data Contracts & Extraction Pipeline)**:
  - Implemented strict Pydantic v2 models (`ExtractionStatus`, `ScrapeConfig`, `DiscoveryCandidate`, `ArticleRecord`) and `JsonlWriter` in `src/web_scraper/models.py`.
  - Implemented URL/domain/title/hash helpers and `extract_article` (`trafilatura.bare_extraction` + `htmldate.find_date` + date/status fallback cascade) in `src/web_scraper/extractor.py`.
  - Added offline tests in `tests/test_models.py` and `tests/test_extractor.py`; verified `pytest` (45 passed), `ruff check`, `ruff format --check`.

## NextSlice
- **Slice 4 (Discovery Engine & CLI Orchestration)**:
  - Implement search/RSS discovery, `site:` dorking, date-range query params, pagination early-stop (`early_stop_threshold` + `known_urls`), and CLI entrypoint (`discovery.py`, `cli.py`).

## KnownIssues
- Live Sannysoft audit requires `uv run playwright install chromium` + network run of `scripts/audit_sannysoft.py`.
- `urllib3` emits `DependencyWarning` for optional `PySocks` when `trafilatura` is imported.
- `uv`/`rtk` binaries live outside sandbox `PATH`; sandboxed checks run via `.venv/bin/{pytest,ruff}`.
