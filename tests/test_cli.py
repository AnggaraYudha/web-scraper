from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from web_scraper import cli
from web_scraper.models import ArticleRecord, ExtractionStatus, JsonlWriter, ScrapeConfig
from web_scraper.stealth import FetchResult

LONG_PROSE = (
    "Global semiconductor manufacturers expanded wafer capacity across multiple regions "
    "following sustained demand for data center accelerators and edge inference chips. "
    "Industry analysts noted that capital expenditure budgets rose significantly while "
    "supply chain bottlenecks continued to ease across packaging and testing facilities. "
) * 6

GOOGLE_RSS_REDIRECT = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Chip Capacity Expands - Reuters</title>
      <link>https://news.google.com/rss/articles/CBMiRedirect1</link>
      <pubDate>Thu, 20 Mar 2025 10:15:00 GMT</pubDate>
      <description>Chipmakers expand production.</description>
    </item>
    <item>
      <title>Blocked Story</title>
      <link>https://www.reuters.com/world/blocked-story</link>
      <pubDate>Fri, 21 Mar 2025 08:00:00 GMT</pubDate>
      <description>Blocked snippet.</description>
    </item>
  </channel>
</rss>
"""

GOOGLE_RSS_FALLBACK = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Blocked By 403</title>
      <link>https://www.reuters.com/tech/protected</link>
      <pubDate>Thu, 20 Mar 2025 10:15:00 GMT</pubDate>
      <description>Protected story.</description>
    </item>
    <item>
      <title>Paywall Stub</title>
      <link>https://www.reuters.com/tech/short-stub</link>
      <pubDate>Fri, 21 Mar 2025 08:00:00 GMT</pubDate>
      <description>Short stub story.</description>
    </item>
  </channel>
</rss>
"""

VALID_ARTICLE_HTML = f"""
<html>
  <head>
    <title>Chipmakers Expand Global Capacity | Reuters</title>
    <meta name="description" content="Wafer output climbs." />
    <meta property="article:published_time" content="2025-03-20T10:15:00Z" />
  </head>
  <body><article><p>{LONG_PROSE}</p></article></body>
</html>
"""

SHORT_PAYWALL_HTML = """
<html>
  <head>
    <title>Subscriber Only | Reuters</title>
    <meta property="article:published_time" content="2025-03-21T08:00:00Z" />
  </head>
  <body><article><p>Please subscribe to read the rest of this story.</p></article></body>
</html>
"""


def _make_fake_fetcher_cls(responses: dict[str, FetchResult]) -> tuple[MagicMock, MagicMock]:
    instance = MagicMock()

    async def _fetch(url: str, **_kwargs: Any) -> FetchResult:
        for key, value in responses.items():
            if url.startswith(key):
                return value
        return FetchResult(url=url, status_code=404, html="", final_url=url, error="HTTP 404")

    instance.fetch = AsyncMock(side_effect=_fetch)
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)

    cls = MagicMock(return_value=instance)
    return cls, instance


@pytest.mark.asyncio
async def test_run_scrape_e2e_redirect_final_url_and_failed_record_emitted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    http_cls, _ = _make_fake_fetcher_cls(
        {
            "https://news.google.com/rss/search": FetchResult(
                url="https://news.google.com/rss/search",
                status_code=200,
                html=GOOGLE_RSS_REDIRECT,
                final_url="https://news.google.com/rss/search",
                error=None,
            ),
            "https://news.google.com/rss/articles/CBMiRedirect1": FetchResult(
                url="https://news.google.com/rss/articles/CBMiRedirect1",
                status_code=200,
                html=VALID_ARTICLE_HTML,
                final_url="https://www.reuters.com/tech/chips-capacity/?utm_source=gnews#top",
                error=None,
            ),
            "https://www.reuters.com/world/blocked-story": FetchResult(
                url="https://www.reuters.com/world/blocked-story",
                status_code=403,
                html="<html>Blocked</html>",
                final_url="https://www.reuters.com/world/blocked-story",
                error="HTTP 403",
            ),
        }
    )
    browser_cls, _ = _make_fake_fetcher_cls({})
    monkeypatch.setattr(cli, "HttpFetcher", http_cls)
    monkeypatch.setattr(cli, "BrowserFetcher", browser_cls)

    out_path = tmp_path / "out.jsonl"
    config = ScrapeConfig(seed_keyword="chips", search_engines=["google"], max_results=10)

    with JsonlWriter(out_path, append=False) as writer:
        records = await cli.run_scrape(config, output_writer=writer, concurrency=2)

    assert len(records) == 2
    assert browser_cls.call_count == 0

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [ArticleRecord.model_validate_json(line) for line in lines]

    assert parsed[0].extraction_status == ExtractionStatus.SUCCESS
    assert parsed[0].canonical_url == "https://www.reuters.com/tech/chips-capacity"
    assert parsed[0].source_domain == "reuters.com"
    assert parsed[0].title == "Chipmakers Expand Global Capacity"

    assert parsed[1].extraction_status == ExtractionStatus.FAILED
    assert parsed[1].canonical_url == "https://www.reuters.com/world/blocked-story"

    captured = capsys.readouterr()
    assert captured.out == ""
    log_events = [json.loads(line) for line in captured.err.splitlines() if line.strip()]
    summary = next(ev for ev in log_events if ev["event"] == "scrape_complete")
    assert summary["total_discovered"] == 2
    assert summary["status_counts"]["SUCCESS"] == 1
    assert summary["status_counts"]["FAILED"] == 1
    assert isinstance(summary["elapsed_sec"], float)


@pytest.mark.asyncio
async def test_run_scrape_browser_fallback_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_cls, _ = _make_fake_fetcher_cls(
        {
            "https://news.google.com/rss/search": FetchResult(
                url="https://news.google.com/rss/search",
                status_code=200,
                html=GOOGLE_RSS_FALLBACK,
                final_url="https://news.google.com/rss/search",
                error=None,
            ),
            "https://www.reuters.com/tech/protected": FetchResult(
                url="https://www.reuters.com/tech/protected",
                status_code=403,
                html="<html>Forbidden</html>",
                final_url="https://www.reuters.com/tech/protected",
                error="HTTP 403",
            ),
            "https://www.reuters.com/tech/short-stub": FetchResult(
                url="https://www.reuters.com/tech/short-stub",
                status_code=200,
                html=SHORT_PAYWALL_HTML,
                final_url="https://www.reuters.com/tech/short-stub",
                error=None,
            ),
        }
    )
    browser_cls, _ = _make_fake_fetcher_cls({})
    monkeypatch.setattr(cli, "HttpFetcher", http_cls)
    monkeypatch.setattr(cli, "BrowserFetcher", browser_cls)

    config = ScrapeConfig(seed_keyword="chips", search_engines=["google"])
    records = await cli.run_scrape(config, browser_fallback=False)

    assert browser_cls.call_count == 0
    assert [r.extraction_status for r in records] == [
        ExtractionStatus.FAILED,
        ExtractionStatus.TOO_SHORT_OR_PAYWALL,
    ]


@pytest.mark.asyncio
async def test_run_scrape_browser_fallback_retries_403_and_short_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_cls, _ = _make_fake_fetcher_cls(
        {
            "https://news.google.com/rss/search": FetchResult(
                url="https://news.google.com/rss/search",
                status_code=200,
                html=GOOGLE_RSS_FALLBACK,
                final_url="https://news.google.com/rss/search",
                error=None,
            ),
            "https://www.reuters.com/tech/protected": FetchResult(
                url="https://www.reuters.com/tech/protected",
                status_code=403,
                html="<html>Forbidden</html>",
                final_url="https://www.reuters.com/tech/protected",
                error="HTTP 403",
            ),
            "https://www.reuters.com/tech/short-stub": FetchResult(
                url="https://www.reuters.com/tech/short-stub",
                status_code=200,
                html=SHORT_PAYWALL_HTML,
                final_url="https://www.reuters.com/tech/short-stub",
                error=None,
            ),
        }
    )
    browser_cls, browser_inst = _make_fake_fetcher_cls(
        {
            "https://www.reuters.com/tech/protected": FetchResult(
                url="https://www.reuters.com/tech/protected",
                status_code=200,
                html=VALID_ARTICLE_HTML,
                final_url="https://www.reuters.com/tech/protected",
                error=None,
            ),
            "https://www.reuters.com/tech/short-stub": FetchResult(
                url="https://www.reuters.com/tech/short-stub",
                status_code=200,
                html=VALID_ARTICLE_HTML,
                final_url="https://www.reuters.com/tech/short-stub",
                error=None,
            ),
        }
    )
    monkeypatch.setattr(cli, "HttpFetcher", http_cls)
    monkeypatch.setattr(cli, "BrowserFetcher", browser_cls)

    config = ScrapeConfig(seed_keyword="chips", search_engines=["google"])
    records = await cli.run_scrape(config, browser_fallback=True, concurrency=2)

    assert browser_cls.call_count == 1
    assert browser_inst.fetch.await_count == 2
    browser_inst.__aexit__.assert_awaited_once()
    assert [r.extraction_status for r in records] == [
        ExtractionStatus.SUCCESS,
        ExtractionStatus.SUCCESS,
    ]


def test_cli_help_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "--keyword" in captured.out
    assert "--browser-fallback" in captured.out


def test_cli_stdout_is_pure_jsonl_and_logs_go_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    http_cls, _ = _make_fake_fetcher_cls(
        {
            "https://news.google.com/rss/search": FetchResult(
                url="https://news.google.com/rss/search",
                status_code=200,
                html=GOOGLE_RSS_REDIRECT,
                final_url="https://news.google.com/rss/search",
                error=None,
            ),
            "https://news.google.com/rss/articles/CBMiRedirect1": FetchResult(
                url="https://news.google.com/rss/articles/CBMiRedirect1",
                status_code=200,
                html=VALID_ARTICLE_HTML,
                final_url="https://www.reuters.com/tech/chips-capacity/?ref=news",
                error=None,
            ),
        }
    )
    monkeypatch.setattr(cli, "HttpFetcher", http_cls)

    known_file = tmp_path / "known.txt"
    known_file.write_text("https://www.reuters.com/world/blocked-story\n", encoding="utf-8")

    exit_code = cli.main(
        [
            "--keyword",
            "chips",
            "--engines",
            "google",
            "--domains",
            "reuters.com",
            "--date-from",
            "2025-03-01T00:00:00Z",
            "--date-to",
            "2025-03-31T23:59:59Z",
            "--max-results",
            "5",
            "--early-stop",
            "0.8",
            "--known-urls-file",
            str(known_file),
            "--output",
            "-",
            "--concurrency",
            "2",
        ]
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    stdout_lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(stdout_lines) == 1
    record = ArticleRecord.model_validate_json(stdout_lines[0])
    assert record.canonical_url == "https://www.reuters.com/tech/chips-capacity"
    assert record.extraction_status == ExtractionStatus.SUCCESS

    stderr_lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(stderr_lines) >= 2
    stderr_events = [json.loads(line) for line in stderr_lines]
    assert any(ev["event"] == "scrape_complete" for ev in stderr_events)


def test_cli_rejects_half_date_range() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--keyword", "chips", "--date-from", "2025-03-01T00:00:00Z"])
    assert exc_info.value.code == 2
