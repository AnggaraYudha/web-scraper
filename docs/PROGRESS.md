# Progress

## CompletedSlices
- **Slice 1 (DevOps Skeleton)**:
  - Runtime deps (`pydantic>=2.10`, `trafilatura`, `htmldate`, `curl_cffi`) and dev deps (`pytest`, `pytest-asyncio`, `ruff`) locked via `uv`.
  - Scaffolded `src/web_scraper/` (`__init__.py`, `models.py`, `extractor.py`, `discovery.py`, `stealth.py`, `cli.py`).
  - Configured `[tool.ruff]` (`py314`, line-length 100, `E/F/I/UP/B`) in `pyproject.toml`.
  - Added `tests/test_smoke.py`; verified `pytest` (6 passed), `ruff check`, and `ruff format --check`.
  - Added `.dockerignore` and multi-stage non-root `Dockerfile` (`ghcr.io/astral-sh/uv:python3.14-bookworm-slim`, `uv sync --frozen --no-dev`).

## NextSlice
- **Slice 2 (Stealth Lab & Sannysoft Pen-Test)**:
  - Add `playwright`, build stealth HTTP/browser layer in `src/web_scraper/stealth.py`, and validate against Sannysoft bot detection.

## KnownIssues
- `pytest-asyncio` emits deprecation warning until `asyncio_default_fixture_loop_scope` is set.
- `uv`/`rtk` binaries live outside sandbox `PATH`; sandboxed checks run via `.venv/bin/{pytest,ruff}`.
