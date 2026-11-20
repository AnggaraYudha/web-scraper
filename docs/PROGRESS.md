# Progress

## CompletedSlices
- **Slice 1 (DevOps Skeleton)**:
  - Core/dev deps locked via `uv`; `src/web_scraper/` scaffold, Ruff config, smoke test, `.dockerignore`, multi-stage non-root `Dockerfile`.
- **Slice 2 (Stealth Layer & Sannysoft Lab)**:
  - Locked `playwright` & `playwright-stealth>=2.0`; `FetchResult`, `HttpFetcher`, `BrowserFetcher` (`Stealth().use_async`), `scripts/audit_sannysoft.py`, `tests/test_stealth.py`.
- **Slice 3 (Data Contracts & Extraction Pipeline)**:
  - Strict Pydantic v2 models + `JsonlWriter` (`models.py`), `trafilatura` + `htmldate` extraction & fallback cascade (`extractor.py`), `tests/test_{models,extractor}.py`.
- **Slice 4 (Discovery Engine & Early-Stop Pagination)**:
  - `build_search_query`, `unwrap_redirect_url`, 4 adapters (`google`, `bing`, `duckduckgo`, `rss`), `DiscoveryEngine` with `known_urls`, `early_stop_threshold`, `max_results`, `tests/test_discovery.py`.
- **Slice 5 (End-to-End Pipeline, Telemetry & CI)**:
  - Implemented stderr JSON telemetry logger, `run_scrape` (concurrent semaphore fetching, `final_url` canonicalization, lazy opt-in `BrowserFetcher` fallback, `FAILED` emission), and `argparse` CLI `main` in `src/web_scraper/cli.py`.
  - Added public re-exports in `src/web_scraper/__init__.py` (PEP 562 lazy `run_scrape` to avoid `runpy` warning).
  - Added `.github/workflows/ci.yml` (`lint-and-test` + `docker-build`) and `tests/test_cli.py`; verified `pytest` (62 passed, 0 warnings), `ruff check`, `ruff format --check`.

## NextSlice
- **Live Verification & Hardening**:
  - Run live Chromium Sannysoft audit (`scripts/audit_sannysoft.py`), end-to-end live smoke scrape, and Docker build verification outside sandbox.

## KnownIssues
- Live Sannysoft audit and `--browser-fallback` require `uv run playwright install chromium`.
- `uv`/`rtk` binaries live outside sandbox `PATH`; sandboxed checks run via `.venv/bin/{pytest,ruff}`.
