from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol, runtime_checkable
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from lxml import html as lxml_html

from web_scraper.extractor import normalize_url
from web_scraper.models import DiscoveryCandidate, ScrapeConfig, coerce_utc_datetime
from web_scraper.stealth import HttpFetcher

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
BING_NEWS_RSS_URL = "https://www.bing.com/news/search"
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _clean_domain_token(raw: str) -> str:
    cleaned = raw.strip().lower()
    if cleaned.startswith(("http://", "https://")):
        cleaned = (urlsplit(cleaned).hostname or "").lower()
    return cleaned.removeprefix("www.").strip("/")


def build_search_query(
    seed_keyword: str,
    target_domains: Sequence[str] | None = None,
    date_range: tuple[datetime | str, datetime | str] | None = None,
) -> str:
    """Build a search query with optional site: dorking and after:/before: date filters."""
    parts: list[str] = [seed_keyword.strip()]

    if target_domains:
        domains = [_clean_domain_token(d) for d in target_domains if _clean_domain_token(d)]
        if len(domains) == 1:
            parts.append(f"site:{domains[0]}")
        elif len(domains) > 1:
            joined = " OR ".join(f"site:{d}" for d in domains)
            parts.append(f"({joined})")

    if date_range is not None:
        start_dt = coerce_utc_datetime(date_range[0])
        end_dt = coerce_utc_datetime(date_range[1])
        parts.append(f"after:{start_dt.strftime('%Y-%m-%d')}")
        parts.append(f"before:{end_dt.strftime('%Y-%m-%d')}")

    return " ".join(part for part in parts if part)


def unwrap_redirect_url(url: str) -> str:
    """Unwrap DuckDuckGo (uddg=) and Bing (url=) redirect URLs and normalize the target."""
    candidate = url.strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"

    parsed = urlsplit(candidate)
    host = (parsed.hostname or "").lower()
    params = parse_qs(parsed.query)

    if "uddg" in params and params["uddg"]:
        target = params["uddg"][0]
        if target.startswith(("http://", "https://")):
            return normalize_url(target)

    if (host == "bing.com" or host.endswith(".bing.com")) and "url" in params and params["url"]:
        target = params["url"][0]
        if target.startswith(("http://", "https://")):
            return normalize_url(target)

    return normalize_url(candidate)


def _parse_pub_date(raw: str | None) -> datetime | None:
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except TypeError, ValueError:
        pass
    try:
        return coerce_utc_datetime(text)
    except ValueError:
        return None


def _strip_html(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    try:
        text = lxml_html.fromstring(raw).text_content()
    except Exception:
        text = raw
    cleaned = " ".join(text.split())
    return cleaned or None


def _parse_rss_or_atom(
    xml_text: str,
    *,
    search_engine: str,
    start_rank: int = 1,
) -> list[DiscoveryCandidate]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    candidates: list[DiscoveryCandidate] = []
    rank = start_rank

    items = root.findall(".//item")
    if items:
        for item in items:
            raw_link = (item.findtext("link") or "").strip()
            if not raw_link:
                continue
            description = _strip_html(item.findtext("description"))
            title = _strip_html(item.findtext("title"))
            snippet = description or title
            pub_date = _parse_pub_date(item.findtext("pubDate"))
            candidates.append(
                DiscoveryCandidate(
                    url=unwrap_redirect_url(raw_link),
                    search_engine=search_engine,
                    serp_rank=rank,
                    serp_snippet=snippet,
                    serp_published_at=pub_date,
                )
            )
            rank += 1
        return candidates

    entries = root.findall(f".//{ATOM_NS}entry") or root.findall(".//entry")
    for entry in entries:
        raw_link = _extract_atom_link(entry)
        if not raw_link:
            continue
        summary = _strip_html(
            entry.findtext(f"{ATOM_NS}summary")
            or entry.findtext("summary")
            or entry.findtext(f"{ATOM_NS}content")
            or entry.findtext("content")
            or entry.findtext(f"{ATOM_NS}title")
            or entry.findtext("title")
        )
        pub_date = _parse_pub_date(
            entry.findtext(f"{ATOM_NS}published")
            or entry.findtext("published")
            or entry.findtext(f"{ATOM_NS}updated")
            or entry.findtext("updated")
        )
        candidates.append(
            DiscoveryCandidate(
                url=unwrap_redirect_url(raw_link),
                search_engine=search_engine,
                serp_rank=rank,
                serp_snippet=summary,
                serp_published_at=pub_date,
            )
        )
        rank += 1

    return candidates


def _extract_atom_link(entry: ET.Element) -> str:
    links = entry.findall(f"{ATOM_NS}link") or entry.findall("link")
    fallback = ""
    for link in links:
        href = (link.attrib.get("href") or link.text or "").strip()
        if not href:
            continue
        rel = link.attrib.get("rel", "alternate")
        if rel == "alternate":
            return href
        if not fallback:
            fallback = href
    return fallback


@runtime_checkable
class SearchAdapter(Protocol):
    name: str

    def iter_pages(self, config: ScrapeConfig) -> AsyncIterator[list[DiscoveryCandidate]]: ...


class GoogleNewsRssAdapter:
    """Google News RSS search adapter."""

    name = "google"

    def __init__(
        self,
        fetcher: HttpFetcher,
        *,
        hl: str = "en-US",
        gl: str = "US",
        ceid: str = "US:en",
    ) -> None:
        self.fetcher = fetcher
        self.hl = hl
        self.gl = gl
        self.ceid = ceid

    async def iter_pages(self, config: ScrapeConfig) -> AsyncIterator[list[DiscoveryCandidate]]:
        query = build_search_query(config.seed_keyword, config.target_domains, config.date_range)
        params = urlencode({"q": query, "hl": self.hl, "gl": self.gl, "ceid": self.ceid})
        result = await self.fetcher.fetch(f"{GOOGLE_NEWS_RSS_URL}?{params}")
        if result.error is not None or not result.html:
            return
        candidates = _parse_rss_or_atom(result.html, search_engine=self.name)
        if candidates:
            yield candidates


class BingNewsRssAdapter:
    """Bing News RSS search adapter with redirect URL unwrapping."""

    name = "bing"

    def __init__(self, fetcher: HttpFetcher) -> None:
        self.fetcher = fetcher

    async def iter_pages(self, config: ScrapeConfig) -> AsyncIterator[list[DiscoveryCandidate]]:
        query = build_search_query(config.seed_keyword, config.target_domains, config.date_range)
        params = urlencode({"q": query, "format": "rss"})
        result = await self.fetcher.fetch(f"{BING_NEWS_RSS_URL}?{params}")
        if result.error is not None or not result.html:
            return
        candidates = _parse_rss_or_atom(result.html, search_engine=self.name)
        if candidates:
            yield candidates


class DuckDuckGoAdapter:
    """DuckDuckGo HTML SERP adapter with multi-page pagination."""

    name = "duckduckgo"

    def __init__(self, fetcher: HttpFetcher, *, max_pages: int = 5) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        self.fetcher = fetcher
        self.max_pages = max_pages

    async def iter_pages(self, config: ScrapeConfig) -> AsyncIterator[list[DiscoveryCandidate]]:
        query = build_search_query(config.seed_keyword, config.target_domains, config.date_range)
        next_url: str | None = f"{DUCKDUCKGO_HTML_URL}?{urlencode({'q': query})}"
        visited: set[str] = set()
        rank = 1

        for _ in range(self.max_pages):
            if not next_url or next_url in visited:
                break
            visited.add(next_url)

            result = await self.fetcher.fetch(next_url)
            if result.error is not None or not result.html:
                break

            page_candidates, next_url = _parse_ddg_page(
                result.html,
                current_url=result.final_url or next_url,
                search_engine=self.name,
                start_rank=rank,
            )
            if not page_candidates:
                break
            rank += len(page_candidates)
            yield page_candidates


def _parse_ddg_page(
    raw_html: str,
    *,
    current_url: str,
    search_engine: str,
    start_rank: int,
) -> tuple[list[DiscoveryCandidate], str | None]:
    try:
        doc = lxml_html.fromstring(raw_html)
    except Exception:
        return [], None

    candidates: list[DiscoveryCandidate] = []
    rank = start_rank

    result_nodes = doc.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' result ') "
        "and not(contains(concat(' ', normalize-space(@class), ' '), ' result--ad '))]"
    )
    for node in result_nodes:
        link_nodes = node.xpath(
            ".//a[contains(concat(' ', normalize-space(@class), ' '), ' result__a ')]"
        )
        if not link_nodes:
            continue
        href = (link_nodes[0].get("href") or "").strip()
        if not href:
            continue

        snippet_nodes = node.xpath(
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' result__snippet ')]"
        )
        raw_snippet = snippet_nodes[0].text_content() if snippet_nodes else ""
        snippet = " ".join(raw_snippet.split()) or None

        candidates.append(
            DiscoveryCandidate(
                url=unwrap_redirect_url(href),
                search_engine=search_engine,
                serp_rank=rank,
                serp_snippet=snippet,
                serp_published_at=None,
            )
        )
        rank += 1

    next_url = _extract_ddg_next_url(doc, current_url)
    return candidates, next_url


def _extract_ddg_next_url(doc: lxml_html.HtmlElement, current_url: str) -> str | None:
    forms = doc.xpath("//div[contains(@class, 'nav-link')]//form") or doc.xpath("//form")
    for form in forms:
        submit_values = [
            (el.get("value") or el.text_content() or "").strip().lower()
            for el in form.xpath(".//input[@type='submit'] | .//button")
        ]
        if not any("next" in val for val in submit_values):
            continue
        params: list[tuple[str, str]] = []
        for hidden in form.xpath(".//input[@type='hidden' and @name]"):
            name = hidden.get("name")
            if name:
                params.append((name, hidden.get("value") or ""))
        if params:
            action = form.get("action") or DUCKDUCKGO_HTML_URL
            base = urljoin(current_url, action)
            return f"{base}?{urlencode(params)}"

    next_links = doc.xpath(
        "//div[contains(@class, 'nav-link')]//a[@href] "
        "| //a[contains(translate(@class, 'NEXT', 'next'), 'next') and @href]"
    )
    for link in next_links:
        text = " ".join(link.text_content().split()).lower()
        href = (link.get("href") or "").strip()
        if href and ("next" in text or "next" in (link.get("class") or "").lower()):
            return urljoin(current_url, href)

    return None


class DirectRssAdapter:
    """Direct RSS 2.0 / Atom feed adapter."""

    name = "rss"

    def __init__(
        self,
        fetcher: HttpFetcher,
        *,
        feed_urls: Sequence[str] | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.feed_urls = tuple(feed_urls) if feed_urls else None

    def _resolve_feeds(self, config: ScrapeConfig) -> list[str]:
        if self.feed_urls:
            return list(self.feed_urls)
        if not config.target_domains:
            return []
        feeds: list[str] = []
        for entry in config.target_domains:
            if entry.startswith(("http://", "https://")):
                feeds.append(entry)
            else:
                feeds.append(f"https://{entry}/rss")
        return feeds

    async def iter_pages(self, config: ScrapeConfig) -> AsyncIterator[list[DiscoveryCandidate]]:
        rank = 1
        for feed_url in self._resolve_feeds(config):
            result = await self.fetcher.fetch(feed_url)
            if result.error is not None or not result.html:
                continue
            candidates = _parse_rss_or_atom(
                result.html,
                search_engine=self.name,
                start_rank=rank,
            )
            if candidates:
                rank += len(candidates)
                yield candidates


class DiscoveryEngine:
    """Orchestrates discovery adapters with deduplication and early-stop pagination."""

    def __init__(
        self,
        fetcher: HttpFetcher,
        *,
        adapters: Mapping[str, SearchAdapter] | None = None,
        rss_feed_urls: Sequence[str] | None = None,
    ) -> None:
        if adapters is not None:
            self._adapters: dict[str, SearchAdapter] = {k.lower(): v for k, v in adapters.items()}
        else:
            google = GoogleNewsRssAdapter(fetcher)
            bing = BingNewsRssAdapter(fetcher)
            ddg = DuckDuckGoAdapter(fetcher)
            rss = DirectRssAdapter(fetcher, feed_urls=rss_feed_urls)
            self._adapters = {
                "google": google,
                "google_news_rss": google,
                "bing": bing,
                "bing_rss": bing,
                "duckduckgo": ddg,
                "ddg": ddg,
                "rss": rss,
            }

    @staticmethod
    def _build_known_checker(
        known_urls: set[str] | Callable[[str], bool] | None,
        config: ScrapeConfig,
    ) -> Callable[[str], bool]:
        source = config.known_urls if known_urls is None else known_urls
        if callable(source):
            return source
        normalized_known = {normalize_url(u) for u in source}
        return lambda url: url in normalized_known

    async def discover(
        self,
        config: ScrapeConfig,
        *,
        known_urls: set[str] | Callable[[str], bool] | None = None,
    ) -> list[DiscoveryCandidate]:
        is_known = self._build_known_checker(known_urls, config)
        results: list[DiscoveryCandidate] = []
        seen_urls: set[str] = set()

        for engine_name in config.search_engines:
            if len(results) >= config.max_results:
                break

            adapter = self._adapters.get(engine_name.lower())
            if adapter is None:
                raise ValueError(f"Unsupported search engine: {engine_name}")

            async for page in adapter.iter_pages(config):
                if not page:
                    break

                known_on_page = 0
                for candidate in page:
                    canonical = unwrap_redirect_url(candidate.url)
                    if is_known(canonical):
                        known_on_page += 1
                        continue
                    if canonical in seen_urls:
                        continue
                    seen_urls.add(canonical)
                    results.append(candidate.model_copy(update={"url": canonical}))
                    if len(results) >= config.max_results:
                        return results

                known_ratio = known_on_page / len(page)
                if known_ratio >= config.early_stop_threshold:
                    break

        return results
