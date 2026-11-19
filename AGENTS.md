# Commands (Always use quiet flags or `rtk` prefix)
- Test: `.venv/bin/pytest -q --tb=short --no-header`
- Lint: `.venv/bin/ruff check --quiet`
- Format: `.venv/bin/ruff format --check --quiet`

# Read-Deny Boundaries (NEVER read or cat these paths)
- `uv.lock`, `.venv/`, `.git/`, `__pycache__/`, `.pytest_cache/`
- `tests/fixtures/*.html`, `data/`, `*.jsonl` (inspect schemas or first 5 lines via `head -n 5` only)

# State & Artifact Protocol
- Spec lives in `docs/SPEC.md`. Read only the sections needed for the active slice.
- Use native `implementation_plan.md` and `task.md` for in-session planning.
- At the end of every slice, update `docs/PROGRESS.md` (max 25 lines: CompletedSlices, NextSlice, KnownIssues) so fresh chat threads resume with zero context loss.

# Architecture Constraints
- Python 3.14 (`src/web_scraper/` layout). Use `uv add` for dependencies; never edit `pyproject.toml` dependencies manually unless configuring tool sections.
- Do NOT write custom DOM/date extractors: wrap `trafilatura` and `htmldate`.
- HTTP/Browser: use `curl_cffi` (TLS impersonation) and `playwright` (headless stealth).
- Data contracts: strict `pydantic` v2 models. Output via clean adapter/JSONL interface.

# Output Style (Caveman Mode)
- Answer first. Drop all pleasantries, preambles, and closing recaps.
- Sentence fragments OK. Every technical fact, negation, path, command, and error string must stay exact.
- In chat, show only changed lines + 2 lines context (`git diff` style), never full files.