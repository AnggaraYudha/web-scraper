from __future__ import annotations

import hashlib
import re
import warnings
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import htmldate
from courlan import extract_domain
from urllib3.exceptions import DependencyWarning

from web_scraper.models import (
    ArticleRecord,
    DiscoveryCandidate,
    ExtractionStatus,
    coerce_utc_datetime,
)
from web_scraper.stealth import FetchResult

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DependencyWarning)
    import trafilatura

MIN_ARTICLE_WORDS = 100
CONTENT_HASH_BODY_CHARS = 500
TRACKING_EXACT_PARAMS: frozenset[str] = frozenset({"fbclid", "gclid", "ref"})
_TITLE_SPLIT_RE = re.compile(r"\s+(?P<sep>\||-|—|–)\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith("utm_") or lowered in TRACKING_EXACT_PARAMS


def normalize_url(url: str) -> str:
    """Normalize a URL by stripping tracking params, fragments, and trailing slashes."""
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()

    port = parsed.port
    is_default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    if port is not None and not is_default_port:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    path = parsed.path
    if path.startswith("/"):
        path = path.rstrip("/") or "/"
    elif path:
        path = path.rstrip("/")

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    query = urlencode(filtered_query, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def extract_source_domain(url: str) -> str:
    """Extract base registrable domain (falling back to host without www.)."""
    domain = extract_domain(url)
    if domain:
        return domain.lower().removeprefix("www.")
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    return host.removeprefix("www.")


def _domain_stem(source_domain: str) -> str:
    cleaned = source_domain.lower().removeprefix("www.").strip()
    return cleaned.split(".")[0] if cleaned else ""


def _looks_like_site_suffix(suffix: str, sep: str, source_domain: str, prefix: str) -> bool:
    if not prefix.strip():
        return False

    norm_suffix = _NON_ALNUM_RE.sub("", suffix.lower())
    norm_domain = _NON_ALNUM_RE.sub("", source_domain.lower())
    stem = _NON_ALNUM_RE.sub("", _domain_stem(source_domain))

    if stem and len(stem) >= 2 and (stem in norm_suffix or norm_suffix == norm_domain):
        return True

    if sep == "|":
        return True

    suffix_words = suffix.split()
    prefix_words = prefix.split()
    has_terminal_punct = suffix.endswith((".", "!", "?"))
    return len(suffix_words) <= 4 and not has_terminal_punct and len(prefix_words) >= 2


def clean_title(title: str, source_domain: str) -> str:
    """Strip trailing site-name suffixes (` | Site`, ` - Site`, ` — Site`, ` – Site`)."""
    cleaned = " ".join(title.split())
    if not cleaned:
        return ""

    for _ in range(2):
        matches = list(_TITLE_SPLIT_RE.finditer(cleaned))
        if not matches:
            break
        last = matches[-1]
        prefix = cleaned[: last.start()].strip()
        suffix = cleaned[last.end() :].strip()
        sep = last.group("sep")
        if _looks_like_site_suffix(suffix, sep, source_domain, prefix):
            cleaned = prefix
        else:
            break

    return cleaned


def compute_content_hash(title: str, clean_body: str) -> str:
    """Compute SHA-256 hex digest of normalized title + first 500 chars of clean_body."""
    norm_title = " ".join(title.lower().split())
    norm_body = " ".join(clean_body.lower().split())[:CONTENT_HASH_BODY_CHARS]
    payload = f"{norm_title}\n{norm_body}".encode()
    return hashlib.sha256(payload).hexdigest()


def _normalize_language(language: str | None) -> str | None:
    if not language:
        return None
    primary = re.split(r"[-_]", language.strip().lower())[0]
    return primary if len(primary) == 2 and primary.isalpha() else None


def _read_doc_field(doc: Any, name: str) -> str | None:
    if doc is None:
        return None
    value = doc.get(name) if isinstance(doc, dict) else getattr(doc, name, None)
    return value if isinstance(value, str) else None


def _extract_page_date(raw_html: str, canonical_url: str) -> datetime | None:
    found = htmldate.find_date(
        raw_html,
        url=canonical_url,
        original_date=True,
        extensive_search=True,
        outputformat="%Y-%m-%dT%H:%M:%S%z",
    )
    if not found:
        return None
    try:
        return coerce_utc_datetime(found)
    except ValueError:
        return None


def extract_article(
    fetch_result: FetchResult,
    candidate: DiscoveryCandidate,
    *,
    seed_keyword: str,
    scraped_at: datetime | None = None,
) -> ArticleRecord:
    """Extract clean article text and metadata into a validated ArticleRecord."""
    now_utc = coerce_utc_datetime(scraped_at) if scraped_at is not None else datetime.now(UTC)
    raw_url = fetch_result.final_url or fetch_result.url or candidate.url
    canonical_url = normalize_url(raw_url)
    source_domain = extract_source_domain(canonical_url)

    is_fetch_ok = (
        fetch_result.error is None
        and fetch_result.status_code is not None
        and 200 <= fetch_result.status_code < 300
        and bool(fetch_result.html and fetch_result.html.strip())
    )

    if not is_fetch_ok:
        fallback_date = candidate.serp_published_at or now_utc
        return ArticleRecord(
            canonical_url=canonical_url,
            seed_keyword=seed_keyword,
            title="",
            clean_body="",
            published_at=fallback_date,
            scraped_at=now_utc,
            extraction_status=ExtractionStatus.FAILED,
            source_domain=source_domain,
            is_date_estimated=True,
            content_hash=compute_content_hash("", ""),
            description=None,
            serp_snippet=candidate.serp_snippet,
            serp_rank=candidate.serp_rank,
            search_engine=candidate.search_engine,
            language=None,
            word_count=0,
        )

    assert fetch_result.html is not None
    raw_html = fetch_result.html

    doc = trafilatura.bare_extraction(
        raw_html,
        url=canonical_url,
        with_metadata=True,
        include_comments=False,
    )

    raw_title = (_read_doc_field(doc, "title") or "").strip()
    clean_body = (_read_doc_field(doc, "text") or "").strip()
    description = (_read_doc_field(doc, "description") or "").strip() or None
    language = _normalize_language(_read_doc_field(doc, "language"))

    title = clean_title(raw_title, source_domain)
    word_count = len(clean_body.split())

    page_date = _extract_page_date(raw_html, canonical_url)
    if page_date is not None:
        published_at = page_date
        is_date_estimated = False
        has_resolved_date = True
    elif candidate.serp_published_at is not None:
        published_at = candidate.serp_published_at
        is_date_estimated = True
        has_resolved_date = True
    else:
        published_at = now_utc
        is_date_estimated = True
        has_resolved_date = False

    if word_count < MIN_ARTICLE_WORDS:
        status = ExtractionStatus.TOO_SHORT_OR_PAYWALL
    elif has_resolved_date:
        status = ExtractionStatus.SUCCESS
    else:
        status = ExtractionStatus.PARTIAL_NO_DATE

    return ArticleRecord(
        canonical_url=canonical_url,
        seed_keyword=seed_keyword,
        title=title,
        clean_body=clean_body,
        published_at=published_at,
        scraped_at=now_utc,
        extraction_status=status,
        source_domain=source_domain,
        is_date_estimated=is_date_estimated,
        content_hash=compute_content_hash(title, clean_body),
        description=description,
        serp_snippet=candidate.serp_snippet,
        serp_rank=candidate.serp_rank,
        search_engine=candidate.search_engine,
        language=language,
        word_count=word_count,
    )
