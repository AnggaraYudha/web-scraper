from __future__ import annotations

from typing import TYPE_CHECKING, Any

from web_scraper.discovery import (
    BingNewsRssAdapter,
    DirectRssAdapter,
    DiscoveryEngine,
    DuckDuckGoAdapter,
    GoogleNewsRssAdapter,
    SearchAdapter,
    build_search_query,
    unwrap_redirect_url,
)
from web_scraper.extractor import (
    clean_title,
    compute_content_hash,
    extract_article,
    extract_source_domain,
    normalize_url,
)
from web_scraper.models import (
    ArticleRecord,
    DiscoveryCandidate,
    ExtractionStatus,
    JsonlWriter,
    ScrapeConfig,
)
from web_scraper.stealth import BrowserFetcher, FetchResult, HttpFetcher

if TYPE_CHECKING:
    from web_scraper.cli import run_scrape

__all__ = [
    "ArticleRecord",
    "BingNewsRssAdapter",
    "BrowserFetcher",
    "DirectRssAdapter",
    "DiscoveryCandidate",
    "DiscoveryEngine",
    "DuckDuckGoAdapter",
    "ExtractionStatus",
    "FetchResult",
    "GoogleNewsRssAdapter",
    "HttpFetcher",
    "JsonlWriter",
    "ScrapeConfig",
    "SearchAdapter",
    "build_search_query",
    "clean_title",
    "compute_content_hash",
    "extract_article",
    "extract_source_domain",
    "normalize_url",
    "run_scrape",
    "unwrap_redirect_url",
]


def __getattr__(name: str) -> Any:
    if name == "run_scrape":
        from web_scraper.cli import run_scrape as _run_scrape

        return _run_scrape
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
