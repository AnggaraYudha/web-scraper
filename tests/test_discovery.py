from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from web_scraper.discovery import (
    BingNewsRssAdapter,
    DirectRssAdapter,
    DiscoveryEngine,
    DuckDuckGoAdapter,
    GoogleNewsRssAdapter,
    build_search_query,
    unwrap_redirect_url,
)
from web_scraper.models import ScrapeConfig
from web_scraper.stealth import FetchResult

GOOGLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>Fed Holds Rates Steady - Reuters</title>
      <link>https://www.reuters.com/world/fed-rates/?utm_source=google#top</link>
      <pubDate>Thu, 20 Mar 2025 10:15:00 GMT</pubDate>
      <description>
        &lt;a href="https://reuters.com"&gt;Fed keeps benchmark unchanged&lt;/a&gt;
      </description>
    </item>
    <item>
      <title>Inflation Cools in March</title>
      <link>https://www.bbc.co.uk/news/inflation-march</link>
      <pubDate>Fri, 21 Mar 2025 08:00:00 GMT</pubDate>
      <description>Consumer prices rose less than expected.</description>
    </item>
  </channel>
</rss>
"""

BING_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Chipmakers Surge on AI Demand</title>
      <link>https://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fwww.reuters.com%2ftech%2fchips%2f%3futm_medium%3dbing</link>
      <pubDate>Sat, 22 Mar 2025 14:00:00 GMT</pubDate>
      <description>Semiconductor stocks gained strongly.</description>
    </item>
  </channel>
</rss>
"""

ATOM_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Tech Atom Feed</title>
  <entry>
    <title>Open Source AI Models Expand</title>
    <link rel="alternate" href="https://techcrunch.com/2025/03/23/open-ai/?fbclid=xyz" />
    <published>2025-03-23T09:30:00Z</published>
    <summary>New weights released under permissive terms.</summary>
  </entry>
</feed>
"""

DDG_PAGE_1_HTML = """
<html>
  <body>
    <div class="result result--ad">
      <a class="result__a" href="https://ads.example.com/promo">Sponsored</a>
      <a class="result__snippet">Buy now</a>
    </div>
    <div class="result results_links">
      <a
        class="result__a"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Freuters.com%2Farticle-1%2F%3Futm_source%3Dddg"
      >Article 1</a>
      <a class="result__snippet">First snippet text.</a>
    </div>
    <div class="result results_links">
      <a
        class="result__a"
        href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Freuters.com%2Farticle-2"
      >Article 2</a>
      <a class="result__snippet">Second snippet text.</a>
    </div>
    <div class="nav-link">
      <form action="/html/" method="post">
        <input type="hidden" name="q" value="ai policy" />
        <input type="hidden" name="s" value="2" />
        <input type="submit" value="Next" />
      </form>
    </div>
  </body>
</html>
"""

DDG_PAGE_2_HTML = """
<html>
  <body>
    <div class="result results_links">
      <a
        class="result__a"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Freuters.com%2Farticle-3"
      >Article 3</a>
      <a class="result__snippet">Third snippet text.</a>
    </div>
    <div class="result results_links">
      <a
        class="result__a"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Freuters.com%2Farticle-4"
      >Article 4</a>
      <a class="result__snippet">Fourth snippet text.</a>
    </div>
    <div class="nav-link">
      <form action="/html/" method="post">
        <input type="hidden" name="q" value="ai policy" />
        <input type="hidden" name="s" value="0" />
        <input type="submit" value="Previous" />
      </form>
      <form action="/html/" method="post">
        <input type="hidden" name="q" value="ai policy" />
        <input type="hidden" name="s" value="4" />
        <input type="submit" value="Next" />
      </form>
    </div>
  </body>
</html>
"""

DDG_PAGE_3_HTML = """
<html>
  <body>
    <div class="result results_links">
      <a
        class="result__a"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Freuters.com%2Farticle-5"
      >Article 5</a>
      <a class="result__snippet">Fifth snippet text.</a>
    </div>
  </body>
</html>
"""


def _mock_fetcher(responses: list[FetchResult]) -> Any:
    fetcher = MagicMock()
    fetcher.fetch = AsyncMock(side_effect=responses)
    return fetcher


def test_build_search_query_dorking_and_date_range() -> None:
    dr = (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 15, tzinfo=UTC))

    assert build_search_query("AI regulation") == "AI regulation"
    assert build_search_query("AI regulation", ["www.reuters.com"]) == (
        "AI regulation site:reuters.com"
    )
    assert build_search_query("AI regulation", ["reuters.com", "bbc.co.uk"], dr) == (
        "AI regulation (site:reuters.com OR site:bbc.co.uk) after:2025-01-01 before:2025-02-15"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.reuters.com%2Fworld%2Fa%2F%3Futm_source%3Dddg&rut=1",
            "https://www.reuters.com/world/a",
        ),
        (
            "https://www.bing.com/news/apiclick.aspx?ref=FexRss&url=https%3a%2f%2fbbc.co.uk%2fnews%2f1%3ffbclid%3d9",
            "https://bbc.co.uk/news/1",
        ),
        (
            "https://Example.COM/story/?gclid=abc#frag",
            "https://example.com/story",
        ),
    ],
)
def test_unwrap_redirect_url(raw: str, expected: str) -> None:
    assert unwrap_redirect_url(raw) == expected


@pytest.mark.asyncio
async def test_google_news_rss_adapter_parses_items() -> None:
    fetcher = _mock_fetcher(
        [FetchResult("https://news.google.com/rss/search", 200, GOOGLE_RSS_XML, None, None)]
    )
    adapter = GoogleNewsRssAdapter(fetcher)
    cfg = ScrapeConfig(
        seed_keyword="fed rates",
        search_engines=["google"],
        target_domains=["reuters.com", "bbc.co.uk"],
    )

    pages = [page async for page in adapter.iter_pages(cfg)]
    assert len(pages) == 1
    assert [c.url for c in pages[0]] == [
        "https://www.reuters.com/world/fed-rates",
        "https://www.bbc.co.uk/news/inflation-march",
    ]
    assert pages[0][0].serp_rank == 1
    assert pages[0][0].serp_snippet == "Fed keeps benchmark unchanged"
    assert pages[0][0].serp_published_at == datetime(2025, 3, 20, 10, 15, tzinfo=UTC)
    assert pages[0][1].serp_rank == 2

    called_url: str = fetcher.fetch.call_args.args[0]
    assert "news.google.com/rss/search" in called_url
    assert "site%3Areuters.com+OR+site%3Abbc.co.uk" in called_url


@pytest.mark.asyncio
async def test_bing_news_rss_adapter_unwraps_redirect() -> None:
    fetcher = _mock_fetcher(
        [FetchResult("https://www.bing.com/news/search", 200, BING_RSS_XML, None, None)]
    )
    adapter = BingNewsRssAdapter(fetcher)
    cfg = ScrapeConfig(seed_keyword="chips", search_engines=["bing"])

    pages = [page async for page in adapter.iter_pages(cfg)]
    assert len(pages) == 1
    assert len(pages[0]) == 1
    assert pages[0][0].url == "https://www.reuters.com/tech/chips"
    assert pages[0][0].search_engine == "bing"
    assert pages[0][0].serp_snippet == "Semiconductor stocks gained strongly."
    assert pages[0][0].serp_published_at == datetime(2025, 3, 22, 14, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_duckduckgo_adapter_multipage_html() -> None:
    fetcher = _mock_fetcher(
        [
            FetchResult(
                "https://html.duckduckgo.com/html/?q=ai+policy",
                200,
                DDG_PAGE_1_HTML,
                "https://html.duckduckgo.com/html/?q=ai+policy",
                None,
            ),
            FetchResult(
                "https://html.duckduckgo.com/html/?q=ai+policy&s=2",
                200,
                DDG_PAGE_2_HTML,
                "https://html.duckduckgo.com/html/?q=ai+policy&s=2",
                None,
            ),
            FetchResult(
                "https://html.duckduckgo.com/html/?q=ai+policy&s=4",
                200,
                DDG_PAGE_3_HTML,
                "https://html.duckduckgo.com/html/?q=ai+policy&s=4",
                None,
            ),
        ]
    )
    adapter = DuckDuckGoAdapter(fetcher, max_pages=5)
    cfg = ScrapeConfig(seed_keyword="ai policy", search_engines=["duckduckgo"])

    pages = [page async for page in adapter.iter_pages(cfg)]
    assert len(pages) == 3
    all_candidates = [c for page in pages for c in page]
    assert [c.url for c in all_candidates] == [
        "https://reuters.com/article-1",
        "https://reuters.com/article-2",
        "https://reuters.com/article-3",
        "https://reuters.com/article-4",
        "https://reuters.com/article-5",
    ]
    assert [c.serp_rank for c in all_candidates] == [1, 2, 3, 4, 5]
    assert all_candidates[0].serp_snippet == "First snippet text."


@pytest.mark.asyncio
async def test_direct_rss_adapter_supports_rss2_and_atom() -> None:
    fetcher = _mock_fetcher(
        [
            FetchResult("https://reuters.com/rss", 200, GOOGLE_RSS_XML, None, None),
            FetchResult("https://techcrunch.com/feed.atom", 200, ATOM_FEED_XML, None, None),
        ]
    )
    adapter = DirectRssAdapter(fetcher)
    cfg = ScrapeConfig(
        seed_keyword="tech",
        search_engines=["rss"],
        target_domains=["reuters.com", "https://techcrunch.com/feed.atom"],
    )

    pages = [page async for page in adapter.iter_pages(cfg)]
    assert len(pages) == 2
    assert pages[0][0].url == "https://www.reuters.com/world/fed-rates"
    assert pages[1][0].url == "https://techcrunch.com/2025/03/23/open-ai"
    assert pages[1][0].serp_rank == 3
    assert pages[1][0].serp_published_at == datetime(2025, 3, 23, 9, 30, tzinfo=UTC)
    assert pages[1][0].serp_snippet == "New weights released under permissive terms."


@pytest.mark.asyncio
async def test_discovery_engine_early_stop_halts_pagination_with_set() -> None:
    fetcher = _mock_fetcher(
        [
            FetchResult(
                "https://html.duckduckgo.com/html/?q=ai+policy",
                200,
                DDG_PAGE_1_HTML,
                "https://html.duckduckgo.com/html/?q=ai+policy",
                None,
            ),
            FetchResult(
                "https://html.duckduckgo.com/html/?q=ai+policy&s=2",
                200,
                DDG_PAGE_2_HTML,
                "https://html.duckduckgo.com/html/?q=ai+policy&s=2",
                None,
            ),
            FetchResult(
                "https://html.duckduckgo.com/html/?q=ai+policy&s=4",
                200,
                DDG_PAGE_3_HTML,
                "https://html.duckduckgo.com/html/?q=ai+policy&s=4",
                None,
            ),
        ]
    )
    engine = DiscoveryEngine(fetcher)
    cfg = ScrapeConfig(
        seed_keyword="ai policy",
        search_engines=["duckduckgo"],
        max_results=20,
        early_stop_threshold=0.5,
    )

    # Page 1: 0/2 known (0.0 < 0.5) -> continues to Page 2.
    # Page 2: 1/2 known (0.5 >= 0.5) -> halts before fetching Page 3!
    known = {"https://reuters.com/article-3/?utm_source=old"}
    results = await engine.discover(cfg, known_urls=known)

    assert fetcher.fetch.await_count == 2
    assert [c.url for c in results] == [
        "https://reuters.com/article-1",
        "https://reuters.com/article-2",
        "https://reuters.com/article-4",
    ]


@pytest.mark.asyncio
async def test_discovery_engine_callback_known_urls_and_dedup_across_engines() -> None:
    fetcher = _mock_fetcher(
        [
            FetchResult("https://news.google.com/rss/search", 200, GOOGLE_RSS_XML, None, None),
            FetchResult("https://www.bing.com/news/search", 200, BING_RSS_XML, None, None),
        ]
    )
    engine = DiscoveryEngine(fetcher)
    cfg = ScrapeConfig(
        seed_keyword="markets",
        search_engines=["google", "bing"],
        max_results=10,
        early_stop_threshold=1.0,
        known_urls=lambda url: url.endswith("inflation-march"),
    )

    results = await engine.discover(cfg)
    assert [c.url for c in results] == [
        "https://www.reuters.com/world/fed-rates",
        "https://www.reuters.com/tech/chips",
    ]


@pytest.mark.asyncio
async def test_discovery_engine_enforces_max_results_hard_cap() -> None:
    fetcher = _mock_fetcher(
        [
            FetchResult(
                "https://html.duckduckgo.com/html/?q=ai+policy",
                200,
                DDG_PAGE_1_HTML,
                "https://html.duckduckgo.com/html/?q=ai+policy",
                None,
            ),
            FetchResult(
                "https://html.duckduckgo.com/html/?q=ai+policy&s=2",
                200,
                DDG_PAGE_2_HTML,
                "https://html.duckduckgo.com/html/?q=ai+policy&s=2",
                None,
            ),
        ]
    )
    engine = DiscoveryEngine(fetcher)
    cfg = ScrapeConfig(
        seed_keyword="ai policy",
        search_engines=["duckduckgo"],
        max_results=3,
        early_stop_threshold=1.0,
    )

    results = await engine.discover(cfg)
    assert len(results) == 3
    assert [c.url for c in results] == [
        "https://reuters.com/article-1",
        "https://reuters.com/article-2",
        "https://reuters.com/article-3",
    ]
    assert fetcher.fetch.await_count == 2
