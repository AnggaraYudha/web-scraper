# Progress

## CompletedSlices
- **Slice 1 (DevOps Skeleton)**:
  - Locked runtime (`pydantic>=2.10`, `trafilatura`, `htmldate`, `curl_cffi`) and dev (`pytest`, `pytest-asyncio`, `ruff`) deps; scaffolded `src/web_scraper/`, Ruff config, smoke test, `.dockerignore`, multi-stage non-root `Dockerfile`.
- **Slice 2 (Stealth Layer & Sannysoft Lab)**:
  - Set `asyncio_default_fixture_loop_scope = "function"` in `[tool.pytest.ini_options]`.
  - Locked `playwright>=1.65.2` and `playwright-stealth>=2.0` via `uv add`.
  - Implemented `FetchResult`, `HttpFetcher` (Chrome TLS, UA rotation, jitter delay, 429/5xx exponential backoff), and `BrowserFetcher` (`Stealth().use_async(async_playwright())` v2) in `src/web_scraper/stealth.py`.
  - Created `scripts/audit_sannysoft.py` (row parser, `data/sannysoft.png`, compact JSON summary).
  - Added offline unit tests in `tests/test_stealth.py`; verified `pytest` (15 passed), `ruff check`, `ruff format --check`.

## NextSlice
- **Slice 3 (Data Contracts & Extraction Pipeline)**:
  - Implement strict Pydantic v2 models (`models.py`) and `trafilatura` + `htmldate` extraction/fallback cascade (`extractor.py`).

## KnownIssues
- Live Sannysoft audit requires Chromium binary (`uv run playwright install chromium`) + network run of `scripts/audit_sannysoft.py`.
- `uv`/`rtk` binaries live outside sandbox `PATH`; sandboxed checks run via `.venv/bin/{pytest,ruff}`.
