from __future__ import annotations

from datetime import UTC, datetime

import pytest

from web_scraper.extractor import (
    clean_title,
    compute_content_hash,
    extract_article,
    extract_source_domain,
    normalize_url,
)
from web_scraper.models import DiscoveryCandidate, ExtractionStatus
from web_scraper.stealth import FetchResult

LONG_PROSE = (
    "Central banks across major economies signaled a cautious stance on monetary policy "
    "as headline inflation moderated while core services costs remained sticky. "
    "Bond yields edged lower following the announcement and equity benchmarks climbed "
    "across technology, industrial, and healthcare sectors in afternoon trading. "
) * 6  # ~220 words

FIXED_SCRAPED_AT = datetime(2025, 4, 1, 12, 0, tzinfo=UTC)


def _candidate(
    url: str = "https://www.reuters.com/world/markets/?utm_source=x&fbclid=abc#section",
    *,
    serp_published_at: datetime | None = None,
) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        url=url,
        search_engine="google",
        serp_rank=2,
        serp_snippet="Central banks signaled caution...",
        serp_published_at=serp_published_at,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "HTTPS://WWW.Reuters.COM/world/story/?utm_source=twitter&utm_medium=social&id=42&fbclid=1&gclid=2&ref=home#top",
            "https://www.reuters.com/world/story?id=42",
        ),
        (
            "https://Example.COM:443/",
            "https://example.com/",
        ),
        (
            "http://Example.COM:80/news/item///",
            "http://example.com/news/item",
        ),
        (
            "https://example.com:8443/article/?page=2&UTM_CAMPAIGN=spring",
            "https://example.com:8443/article?page=2",
        ),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.reuters.com/world/story", "reuters.com"),
        ("https://news.bbc.co.uk/article", "bbc.co.uk"),
        ("https://money.kompas.co.id/read/123", "kompas.co.id"),
        ("http://localhost:8080/test", "localhost"),
    ],
)
def test_extract_source_domain(url: str, expected: str) -> None:
    assert extract_source_domain(url) == expected


@pytest.mark.parametrize(
    ("raw_title", "domain", "expected"),
    [
        (
            "Markets Rally After Rate Pause | Reuters",
            "reuters.com",
            "Markets Rally After Rate Pause",
        ),
        (
            "Markets Rally After Rate Pause - Reuters",
            "reuters.com",
            "Markets Rally After Rate Pause",
        ),
        (
            "Markets Rally After Rate Pause — The New York Times",
            "nytimes.com",
            "Markets Rally After Rate Pause",
        ),
        (
            "Markets Rally After Rate Pause - Markets | Reuters",
            "reuters.com",
            "Markets Rally After Rate Pause",
        ),
        (
            "AI-powered chips surge in 2025",
            "techcrunch.com",
            "AI-powered chips surge in 2025",
        ),
        (
            "Economy grows 5% - analysts expect inflation to cool further before year end",
            "reuters.com",
            "Economy grows 5% - analysts expect inflation to cool further before year end",
        ),
    ],
)
def test_clean_title(raw_title: str, domain: str, expected: str) -> None:
    assert clean_title(raw_title, domain) == expected


def test_compute_content_hash_syndication_dedup() -> None:
    body_a = "  " + ("Alpha beta gamma delta epsilon. " * 25) + "Tail A only."
    body_b = ("alpha   beta\ngamma delta epsilon. " * 25) + "Completely different tail B."

    hash_a = compute_content_hash("Global Markets Rally", body_a)
    hash_b = compute_content_hash("  global   markets rally ", body_b)
    hash_other = compute_content_hash("Different Headline", body_a)

    assert len(hash_a) == 64
    assert hash_a == hash_b
    assert hash_a != hash_other


def test_extract_article_success_with_page_date() -> None:
    html = f"""
    <html>
      <head>
        <title>Central Banks Hold Rates Steady | Reuters</title>
        <meta name="description" content="Policymakers kept benchmark rates unchanged." />
        <meta property="article:published_time" content="2025-03-20T10:15:00Z" />
      </head>
      <body>
        <nav>Menu links to ignore</nav>
        <article>
          <h1>Central Banks Hold Rates Steady</h1>
          <p>{LONG_PROSE}</p>
        </article>
      </body>
    </html>
    """
    cand = _candidate()
    fetch = FetchResult(
        url=cand.url,
        status_code=200,
        html=html,
        final_url=cand.url,
        error=None,
    )

    record = extract_article(
        fetch,
        cand,
        seed_keyword="central bank rates",
        scraped_at=FIXED_SCRAPED_AT,
    )

    assert record.extraction_status == ExtractionStatus.SUCCESS
    assert record.canonical_url == "https://www.reuters.com/world/markets"
    assert record.source_domain == "reuters.com"
    assert record.title == "Central Banks Hold Rates Steady"
    assert record.description == "Policymakers kept benchmark rates unchanged."
    assert record.published_at == datetime(2025, 3, 20, 10, 15, tzinfo=UTC)
    assert record.scraped_at == FIXED_SCRAPED_AT
    assert record.is_date_estimated is False
    assert record.word_count >= 100
    assert record.serp_rank == 2
    assert record.search_engine == "google"
    assert len(record.content_hash) == 64


def test_extract_article_paywall_too_short() -> None:
    html = """
    <html>
      <head>
        <title>Exclusive Investigation - Financial Times</title>
        <meta property="article:published_time" content="2025-03-20T10:15:00Z" />
      </head>
      <body>
        <article>
          <p>Subscribe now to unlock full access to this investigative report.</p>
        </article>
      </body>
    </html>
    """
    cand = _candidate(url="https://www.ft.com/content/12345")
    fetch = FetchResult(
        url=cand.url,
        status_code=200,
        html=html,
        final_url=cand.url,
        error=None,
    )

    record = extract_article(
        fetch,
        cand,
        seed_keyword="exclusive",
        scraped_at=FIXED_SCRAPED_AT,
    )

    assert record.extraction_status == ExtractionStatus.TOO_SHORT_OR_PAYWALL
    assert record.word_count < 100
    assert record.is_date_estimated is False


def test_extract_article_serp_date_fallback() -> None:
    html = f"""
    <html>
      <head><title>Supply Chain Outlook — Bloomberg</title></head>
      <body><article><p>{LONG_PROSE}</p></article></body>
    </html>
    """
    serp_dt = datetime(2025, 3, 28, 9, 0, tzinfo=UTC)
    cand = _candidate(
        url="https://www.bloomberg.com/news/supply-chain-outlook",
        serp_published_at=serp_dt,
    )
    fetch = FetchResult(
        url=cand.url,
        status_code=200,
        html=html,
        final_url=cand.url,
        error=None,
    )

    record = extract_article(
        fetch,
        cand,
        seed_keyword="supply chain",
        scraped_at=FIXED_SCRAPED_AT,
    )

    assert record.extraction_status == ExtractionStatus.SUCCESS
    assert record.published_at == serp_dt
    assert record.is_date_estimated is True
    assert record.title == "Supply Chain Outlook"


def test_extract_article_missing_date_partial_no_date() -> None:
    html = f"""
    <html>
      <head><title>Undated Market Analysis - Reuters</title></head>
      <body><article><p>{LONG_PROSE}</p></article></body>
    </html>
    """
    cand = _candidate(url="https://www.reuters.com/markets/undated-analysis")
    fetch = FetchResult(
        url=cand.url,
        status_code=200,
        html=html,
        final_url=cand.url,
        error=None,
    )

    record = extract_article(
        fetch,
        cand,
        seed_keyword="market analysis",
        scraped_at=FIXED_SCRAPED_AT,
    )

    assert record.extraction_status == ExtractionStatus.PARTIAL_NO_DATE
    assert record.published_at == FIXED_SCRAPED_AT
    assert record.is_date_estimated is True
    assert record.word_count >= 100


def test_extract_article_failed_fetch_returns_blacklistable_record() -> None:
    cand = _candidate(url="https://www.reuters.com/blocked/?utm_source=g&ref=1")
    fetch = FetchResult(
        url=cand.url,
        status_code=403,
        html="<html><body>Access denied</body></html>",
        final_url=cand.url,
        error="HTTP 403",
    )

    record = extract_article(
        fetch,
        cand,
        seed_keyword="central bank rates",
        scraped_at=FIXED_SCRAPED_AT,
    )

    assert record.extraction_status == ExtractionStatus.FAILED
    assert record.canonical_url == "https://www.reuters.com/blocked"
    assert record.source_domain == "reuters.com"
    assert record.clean_body == ""
    assert record.word_count == 0
    assert record.published_at == FIXED_SCRAPED_AT
    assert record.is_date_estimated is True
