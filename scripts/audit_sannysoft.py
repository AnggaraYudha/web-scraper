from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from lxml import html as lxml_html

from web_scraper.stealth import BrowserFetcher

SANNYSOFT_URL = "https://bot.sannysoft.com/"
SCREENSHOT_PATH = Path("data/sannysoft.png")


def parse_sannysoft_results(raw_html: str) -> dict[str, Any]:
    """Parse Sannysoft bot test rows into a compact summary."""
    doc = lxml_html.fromstring(raw_html)
    passed_count = 0
    failed_tests: list[dict[str, str]] = []

    for row in doc.xpath("//tr"):
        cells = row.xpath("./td")
        if len(cells) < 2:
            continue
        name = " ".join(cells[0].text_content().split())
        status_cell = next(
            (
                cell
                for cell in cells[1:]
                if {"passed", "failed"} & set(cell.get("class", "").split())
            ),
            cells[1],
        )
        classes = set(status_cell.get("class", "").split())
        result_text = " ".join(status_cell.text_content().split())

        if "failed" in classes:
            failed_tests.append(
                {
                    "name": name,
                    "result": result_text,
                    "class": "failed",
                }
            )
        elif "passed" in classes:
            passed_count += 1

    return {
        "passed_count": passed_count,
        "failed_count": len(failed_tests),
        "failed_tests": failed_tests,
    }


async def run_audit(screenshot_path: Path = SCREENSHOT_PATH) -> dict[str, Any]:
    async with BrowserFetcher(headless=True) as fetcher:
        result = await fetcher.fetch(
            SANNYSOFT_URL,
            wait_until="networkidle",
            settle_ms=1500,
            screenshot_path=screenshot_path,
        )

    if result.html is None:
        return {
            "passed_count": 0,
            "failed_count": 0,
            "failed_tests": [],
            "error": result.error or "Empty HTML response",
        }

    return parse_sannysoft_results(result.html)


def main() -> int:
    summary = asyncio.run(run_audit())
    print(json.dumps(summary, separators=(",", ":")))
    return 1 if "error" in summary else 0


if __name__ == "__main__":
    sys.exit(main())
