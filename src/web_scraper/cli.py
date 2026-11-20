from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from web_scraper.discovery import DiscoveryEngine
from web_scraper.extractor import extract_article
from web_scraper.models import (
    ArticleRecord,
    DiscoveryCandidate,
    ExtractionStatus,
    JsonlWriter,
    ScrapeConfig,
    serialize_utc_datetime,
)
from web_scraper.stealth import BrowserFetcher, FetchResult, HttpFetcher


class _DynamicStderrHandler(logging.Handler):
    """Logging handler that always writes to the current sys.stderr."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stderr.write(f"{msg}\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


class JsonLogFormatter(logging.Formatter):
    """Formats log records as single-line UTC JSON telemetry objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": serialize_utc_datetime(datetime.now(UTC)),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, separators=(",", ":"), default=str)


def get_logger(name: str = "web_scraper") -> logging.Logger:
    """Return a structured JSON logger configured to write only to stderr."""
    logger = logging.getLogger(name)
    if not any(isinstance(h, _DynamicStderrHandler) for h in logger.handlers):
        handler = _DynamicStderrHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    logger.log(level, event, extra={"event": event, "fields": fields})


def _emit_record(output_writer: Any, record: ArticleRecord) -> None:
    if output_writer is None:
        return
    if isinstance(output_writer, JsonlWriter):
        output_writer.write(record)
        return
    if isinstance(output_writer, io.IOBase) or hasattr(output_writer, "isatty"):
        output_writer.write(f"{record.to_jsonl()}\n")
        if hasattr(output_writer, "flush"):
            output_writer.flush()
        return
    if callable(output_writer):
        output_writer(record)
        return
    if hasattr(output_writer, "write"):
        output_writer.write(record)
        return
    raise TypeError(f"Unsupported output_writer type: {type(output_writer).__name__}")


def _needs_browser_fallback(fetch_result: FetchResult, record: ArticleRecord) -> bool:
    if record.extraction_status in (
        ExtractionStatus.FAILED,
        ExtractionStatus.TOO_SHORT_OR_PAYWALL,
    ):
        return True
    return fetch_result.error is not None or fetch_result.status_code in (403, 429)


async def run_scrape(
    config: ScrapeConfig,
    *,
    known_urls: set[str] | Callable[[str], bool] | None = None,
    output_writer: Any = None,
    concurrency: int = 3,
    browser_fallback: bool = False,
) -> list[ArticleRecord]:
    """Run end-to-end discovery, concurrent fetching, extraction, and telemetry."""
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")

    logger = get_logger()
    started = time.monotonic()
    _log_event(
        logger,
        logging.INFO,
        "scrape_started",
        seed_keyword=config.seed_keyword,
        search_engines=config.search_engines,
        max_results=config.max_results,
        concurrency=concurrency,
        browser_fallback=browser_fallback,
    )

    records: list[ArticleRecord] = []
    candidates: list[DiscoveryCandidate] = []

    async with AsyncExitStack() as stack:
        http_fetcher = await stack.enter_async_context(HttpFetcher())
        engine = DiscoveryEngine(http_fetcher)
        candidates = await engine.discover(config, known_urls=known_urls)
        _log_event(
            logger,
            logging.INFO,
            "discovery_complete",
            total_discovered=len(candidates),
        )

        browser_fetcher: BrowserFetcher | None = None
        browser_lock = asyncio.Lock()

        async def get_browser() -> BrowserFetcher:
            nonlocal browser_fetcher
            async with browser_lock:
                if browser_fetcher is None:
                    browser_fetcher = await stack.enter_async_context(BrowserFetcher())
                return browser_fetcher

        semaphore = asyncio.Semaphore(concurrency)

        async def process_candidate(candidate: DiscoveryCandidate) -> ArticleRecord:
            async with semaphore:
                fetch_result = await http_fetcher.fetch(candidate.url)
                resolved_url = fetch_result.final_url or candidate.url
                effective_candidate = (
                    candidate.model_copy(update={"url": resolved_url})
                    if resolved_url != candidate.url
                    else candidate
                )
                record = extract_article(
                    fetch_result,
                    effective_candidate,
                    seed_keyword=config.seed_keyword,
                )

                if browser_fallback and _needs_browser_fallback(fetch_result, record):
                    reason = fetch_result.error or record.extraction_status.value
                    _log_event(
                        logger,
                        logging.WARNING,
                        "browser_fallback_triggered",
                        url=resolved_url,
                        reason=reason,
                    )
                    browser = await get_browser()
                    browser_result = await browser.fetch(resolved_url)
                    browser_url = browser_result.final_url or resolved_url
                    browser_candidate = (
                        effective_candidate.model_copy(update={"url": browser_url})
                        if browser_url != effective_candidate.url
                        else effective_candidate
                    )
                    fallback_record = extract_article(
                        browser_result,
                        browser_candidate,
                        seed_keyword=config.seed_keyword,
                    )
                    if (
                        fallback_record.extraction_status != ExtractionStatus.FAILED
                        or record.extraction_status == ExtractionStatus.FAILED
                    ):
                        record = fallback_record

                return record

        if candidates:
            records = list(
                await asyncio.gather(*(process_candidate(candidate) for candidate in candidates))
            )

    for record in records:
        _emit_record(output_writer, record)

    counts = Counter(record.extraction_status for record in records)
    status_counts = {status.value: counts.get(status, 0) for status in ExtractionStatus}
    elapsed_sec = round(time.monotonic() - started, 3)

    _log_event(
        logger,
        logging.INFO,
        "scrape_complete",
        total_discovered=len(candidates),
        status_counts=status_counts,
        elapsed_sec=elapsed_sec,
    )
    return records


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _load_known_urls_file(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web-scraper",
        description="Modular web discovery and article extraction engine.",
    )
    parser.add_argument("--keyword", required=True, help="Target search phrase (seed_keyword).")
    parser.add_argument(
        "--engines",
        default="google,bing",
        help="Comma-separated search engines (default: google,bing).",
    )
    parser.add_argument(
        "--domains",
        default=None,
        help="Comma-separated whitelisted domains or RSS URLs (optional).",
    )
    parser.add_argument(
        "--date-from",
        default=None,
        help="Historical backfill start date in ISO-8601 format (optional).",
    )
    parser.add_argument(
        "--date-to",
        default=None,
        help="Historical backfill end date in ISO-8601 format (optional).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Hard cap on total articles to scrape per job (default: 10).",
    )
    parser.add_argument(
        "--early-stop",
        type=float,
        default=0.8,
        help="Early-stop known URL ratio threshold 0.0-1.0 (default: 0.8).",
    )
    parser.add_argument(
        "--known-urls-file",
        type=Path,
        default=None,
        help="Newline-delimited file of already-known URLs (optional).",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output JSONL file path or '-' for stdout (default: '-').",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Maximum concurrent article fetches (default: 3).",
    )
    parser.add_argument(
        "--browser-fallback",
        action="store_true",
        help="Retry failed or short/paywalled HTTP fetches via headless Chromium.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if bool(args.date_from) != bool(args.date_to):
        parser.error("--date-from and --date-to must be provided together")

    date_range: tuple[Any, Any] | None = (
        (args.date_from, args.date_to) if args.date_from and args.date_to else None
    )
    engines = _split_csv(args.engines)
    domains = _split_csv(args.domains) if args.domains else None
    known_urls = _load_known_urls_file(args.known_urls_file) if args.known_urls_file else set()

    config = ScrapeConfig(
        seed_keyword=args.keyword,
        search_engines=engines,
        target_domains=domains,
        date_range=date_range,
        max_results=args.max_results,
        early_stop_threshold=args.early_stop,
        known_urls=known_urls,
    )

    if args.output == "-":
        asyncio.run(
            run_scrape(
                config,
                known_urls=known_urls,
                output_writer=sys.stdout,
                concurrency=args.concurrency,
                browser_fallback=args.browser_fallback,
            )
        )
    else:
        with JsonlWriter(args.output, append=False) as writer:
            asyncio.run(
                run_scrape(
                    config,
                    known_urls=known_urls,
                    output_writer=writer,
                    concurrency=args.concurrency,
                    browser_fallback=args.browser_fallback,
                )
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
