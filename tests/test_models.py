from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from web_scraper.models import (
    ArticleRecord,
    DiscoveryCandidate,
    ExtractionStatus,
    JsonlWriter,
    ScrapeConfig,
)


def _sample_article(**overrides: object) -> ArticleRecord:
    base: dict[str, object] = {
        "canonical_url": "https://reuters.com/world/markets-rally",
        "seed_keyword": "central bank rates",
        "title": "Markets rally after rate pause",
        "clean_body": "word " * 120,
        "published_at": datetime(2025, 3, 15, 14, 30, tzinfo=UTC),
        "scraped_at": datetime(2025, 3, 16, 8, 0, tzinfo=UTC),
        "extraction_status": ExtractionStatus.SUCCESS,
        "source_domain": "reuters.com",
        "is_date_estimated": False,
        "content_hash": "a" * 64,
        "description": "Stocks rose broadly.",
        "serp_snippet": "Global equities gained...",
        "serp_rank": 1,
        "search_engine": "google",
        "language": "en",
        "word_count": 120,
    }
    base.update(overrides)
    return ArticleRecord(**base)  # type: ignore[arg-type]


def test_extraction_status_values() -> None:
    assert [s.value for s in ExtractionStatus] == [
        "SUCCESS",
        "PARTIAL_NO_DATE",
        "TOO_SHORT_OR_PAYWALL",
        "FAILED",
    ]


def test_scrape_config_validates_bounds_and_normalizes() -> None:
    cfg = ScrapeConfig(
        seed_keyword="  AI regulation  ",
        search_engines=["Google", " Bing "],
        target_domains=["www.Reuters.com", "bbc.co.uk"],
        date_range=("2025-01-01T00:00:00Z", "2025-02-01T00:00:00+02:00"),  # type: ignore[arg-type]
        max_results=25,
        early_stop_threshold=0.75,
        known_urls={"https://reuters.com/old"},
    )

    assert cfg.seed_keyword == "AI regulation"
    assert cfg.search_engines == ["google", "bing"]
    assert cfg.target_domains == ["reuters.com", "bbc.co.uk"]
    assert cfg.date_range is not None
    assert cfg.date_range[0] == datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    assert cfg.date_range[1] == datetime(2025, 1, 31, 22, 0, tzinfo=UTC)
    assert cfg.is_url_known("https://reuters.com/old") is True
    assert cfg.is_url_known("https://reuters.com/new") is False


def test_scrape_config_known_urls_callback_and_json_exclusion() -> None:
    seen = {"https://example.com/a"}
    cfg = ScrapeConfig(
        seed_keyword="energy",
        search_engines=["rss"],
        known_urls=lambda u: u in seen,
    )
    assert cfg.is_url_known("https://example.com/a") is True
    assert cfg.is_url_known("https://example.com/b") is False

    dumped = json.loads(cfg.model_dump_json())
    assert "known_urls" not in dumped


@pytest.mark.parametrize("bad_threshold", [-0.01, 1.01, "0.5"])
def test_scrape_config_rejects_invalid_threshold(bad_threshold: object) -> None:
    with pytest.raises(ValidationError):
        ScrapeConfig(
            seed_keyword="ai",
            search_engines=["google"],
            early_stop_threshold=bad_threshold,  # type: ignore[arg-type]
        )


def test_scrape_config_rejects_invalid_date_range_and_strict_types() -> None:
    with pytest.raises(ValidationError):
        ScrapeConfig(
            seed_keyword="ai",
            search_engines=["google"],
            date_range=(
                datetime(2025, 3, 2, tzinfo=UTC),
                datetime(2025, 3, 1, tzinfo=UTC),
            ),
        )

    with pytest.raises(ValidationError):
        ScrapeConfig(
            seed_keyword="ai",
            search_engines=["google"],
            max_results="10",  # type: ignore[arg-type]
        )

    with pytest.raises(ValidationError):
        ScrapeConfig(
            seed_keyword="   ",
            search_engines=["google"],
        )


def test_discovery_candidate_coerces_utc_and_rejects_rank_zero() -> None:
    tz_plus_7 = timezone(timedelta(hours=7))
    cand = DiscoveryCandidate(
        url="https://reuters.com/a",
        search_engine="duckduckgo",
        serp_rank=1,
        serp_snippet="Snippet text",
        serp_published_at=datetime(2025, 5, 1, 12, 0, tzinfo=tz_plus_7),
    )
    assert cand.serp_published_at == datetime(2025, 5, 1, 5, 0, tzinfo=UTC)

    with pytest.raises(ValidationError):
        DiscoveryCandidate(url="https://reuters.com/a", search_engine="bing", serp_rank=0)


def test_article_record_utc_iso_serialization_and_roundtrip() -> None:
    tz_minus_5 = timezone(timedelta(hours=-5))
    record = _sample_article(
        published_at=datetime(2025, 3, 15, 9, 30, tzinfo=tz_minus_5),
        scraped_at=datetime(2025, 3, 16, 8, 0, tzinfo=UTC),
    )

    line = record.to_jsonl()
    payload = json.loads(line)
    assert payload["published_at"] == "2025-03-15T14:30:00Z"
    assert payload["scraped_at"] == "2025-03-16T08:00:00Z"
    assert payload["extraction_status"] == "SUCCESS"

    restored = ArticleRecord.model_validate_json(line)
    assert restored == record


def test_jsonl_writer_context_manager(tmp_path: Path) -> None:
    out_file = tmp_path / "nested" / "articles.jsonl"
    rec1 = _sample_article(canonical_url="https://reuters.com/1", serp_rank=1)
    rec2 = _sample_article(canonical_url="https://reuters.com/2", serp_rank=2)

    with JsonlWriter(out_file, append=False) as writer:
        writer.write(rec1)
        written = writer.write_many([rec2])

    assert written == 1
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert ArticleRecord.model_validate_json(lines[0]).canonical_url == "https://reuters.com/1"
    assert ArticleRecord.model_validate_json(lines[1]).canonical_url == "https://reuters.com/2"
