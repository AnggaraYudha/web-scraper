from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Self, TextIO

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)


def coerce_utc_datetime(value: Any) -> datetime:
    """Parse an ISO-8601 string or datetime and normalize to timezone-aware UTC."""
    if isinstance(value, str):
        dt = datetime.fromisoformat(value)
    elif isinstance(value, datetime):
        dt = value
    else:
        raise ValueError("Expected a datetime or ISO-8601 string")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def serialize_utc_datetime(value: datetime) -> str:
    """Serialize a datetime as ISO-8601 UTC with Z suffix."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[
    datetime,
    BeforeValidator(coerce_utc_datetime),
    PlainSerializer(serialize_utc_datetime, return_type=str, when_used="json"),
]


class ExtractionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_NO_DATE = "PARTIAL_NO_DATE"
    TOO_SHORT_OR_PAYWALL = "TOO_SHORT_OR_PAYWALL"
    FAILED = "FAILED"


class ScrapeConfig(BaseModel):
    """Runtime control parameters for a scrape job (SPEC Section 2)."""

    model_config = ConfigDict(strict=True, extra="forbid", arbitrary_types_allowed=True)

    seed_keyword: str = Field(min_length=1)
    search_engines: list[str] = Field(min_length=1)
    target_domains: list[str] | None = None
    date_range: tuple[UtcDatetime, UtcDatetime] | None = None
    max_results: int = Field(default=50, ge=1)
    early_stop_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    known_urls: set[str] | Callable[[str], bool] = Field(default_factory=set, exclude=True)

    @field_validator("seed_keyword")
    @classmethod
    def _validate_seed_keyword(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("seed_keyword must not be blank")
        return cleaned

    @field_validator("search_engines")
    @classmethod
    def _validate_search_engines(cls, value: list[str]) -> list[str]:
        cleaned = [engine.strip().lower() for engine in value if engine.strip()]
        if len(cleaned) != len(value):
            raise ValueError("search_engines entries must not be blank")
        return cleaned

    @field_validator("target_domains")
    @classmethod
    def _validate_target_domains(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [domain.strip().lower().removeprefix("www.") for domain in value]
        if any(not domain for domain in cleaned):
            raise ValueError("target_domains entries must not be blank")
        return cleaned

    @model_validator(mode="after")
    def _validate_date_range_order(self) -> Self:
        if self.date_range is not None:
            start, end = self.date_range
            if start > end:
                raise ValueError("date_range start must be <= end")
        return self

    def is_url_known(self, url: str) -> bool:
        """Check whether a normalized URL already exists in known_urls."""
        if callable(self.known_urls):
            return bool(self.known_urls(url))
        return url in self.known_urls


class DiscoveryCandidate(BaseModel):
    """Intermediate URL candidate emitted by a discovery engine."""

    model_config = ConfigDict(strict=True, extra="forbid")

    url: str = Field(min_length=1)
    search_engine: str = Field(min_length=1)
    serp_rank: int = Field(ge=1)
    serp_snippet: str | None = None
    serp_published_at: UtcDatetime | None = None


class ArticleRecord(BaseModel):
    """Structured output contract for downstream NLP pipelines (SPEC Section 3)."""

    model_config = ConfigDict(strict=True, extra="forbid")

    # Primary fields
    canonical_url: str = Field(min_length=1)
    seed_keyword: str = Field(min_length=1)
    title: str
    clean_body: str
    published_at: UtcDatetime
    scraped_at: UtcDatetime
    extraction_status: ExtractionStatus

    # Secondary fields
    source_domain: str
    is_date_estimated: bool
    content_hash: str
    description: str | None = None
    serp_snippet: str | None = None
    serp_rank: int = Field(ge=1)
    search_engine: str = Field(min_length=1)
    language: str | None = None
    word_count: int = Field(ge=0)

    def to_jsonl(self) -> str:
        """Serialize this record as a single compact JSONL line (without trailing newline)."""
        return self.model_dump_json()


class JsonlWriter:
    """Decoupled JSONL output adapter for writing ArticleRecord instances."""

    def __init__(self, path: str | Path, *, append: bool = True) -> None:
        self.path = Path(path)
        self.append = append
        self._handle: TextIO | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self.append else "w"
        self._handle = self.path.open(mode, encoding="utf-8")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def write(self, record: ArticleRecord) -> None:
        line = f"{record.to_jsonl()}\n"
        if self._handle is not None:
            self._handle.write(line)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self.append else "w"
        with self.path.open(mode, encoding="utf-8") as handle:
            handle.write(line)

    def write_many(self, records: Iterable[ArticleRecord]) -> int:
        count = 0
        if self._handle is not None:
            for record in records:
                self._handle.write(f"{record.to_jsonl()}\n")
                count += 1
            return count
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self.append else "w"
        with self.path.open(mode, encoding="utf-8") as handle:
            for record in records:
                handle.write(f"{record.to_jsonl()}\n")
                count += 1
        return count
