from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from web_scraper import stealth as stealth_mod
from web_scraper.stealth import BrowserFetcher, FetchResult, HttpFetcher


@dataclass
class FakeResponse:
    status_code: int
    text: str
    url: str


def _patch_async_session(
    monkeypatch: pytest.MonkeyPatch,
    side_effect: list[FakeResponse | Exception],
) -> tuple[MagicMock, AsyncMock]:
    session_instance = MagicMock()
    session_instance.get = AsyncMock(side_effect=side_effect)
    session_instance.close = AsyncMock()
    session_instance.__aenter__ = AsyncMock(return_value=session_instance)
    session_instance.__aexit__ = AsyncMock(return_value=None)

    session_cls = MagicMock(return_value=session_instance)
    monkeypatch.setattr(stealth_mod, "AsyncSession", session_cls)
    return session_cls, session_instance.get


@pytest.mark.asyncio
async def test_http_fetcher_success_and_ua_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(stealth_mod.asyncio, "sleep", fake_sleep)
    session_cls, mock_get = _patch_async_session(
        monkeypatch,
        [
            FakeResponse(200, "<html>one</html>", "https://example.com/1"),
            FakeResponse(200, "<html>two</html>", "https://example.com/2"),
        ],
    )

    uas = ("UA-Alpha", "UA-Beta")
    async with HttpFetcher(min_delay=0.2, max_delay=0.4, user_agents=uas) as fetcher:
        res1 = await fetcher.fetch("https://example.com/1")
        res2 = await fetcher.fetch("https://example.com/2")

    session_cls.assert_called_once_with(impersonate="chrome")
    assert res1 == FetchResult(
        url="https://example.com/1",
        status_code=200,
        html="<html>one</html>",
        final_url="https://example.com/1",
        error=None,
    )
    assert res2.status_code == 200
    assert res2.error is None

    sent_uas = [call.kwargs["headers"]["User-Agent"] for call in mock_get.call_args_list]
    assert sent_uas == ["UA-Alpha", "UA-Beta"]
    assert len(sleeps) == 2
    assert all(0.2 <= s <= 0.4 for s in sleeps)


@pytest.mark.asyncio
async def test_http_fetcher_429_exponential_backoff_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(stealth_mod.asyncio, "sleep", fake_sleep)
    _, mock_get = _patch_async_session(
        monkeypatch,
        [
            FakeResponse(429, "rate limited", "https://example.com/a"),
            FakeResponse(429, "still rate limited", "https://example.com/a"),
            FakeResponse(200, "<html>ok</html>", "https://example.com/a"),
        ],
    )

    async with HttpFetcher(
        min_delay=0.1,
        max_delay=0.2,
        max_retries=3,
        base_backoff=1.0,
        max_backoff_jitter=0.5,
    ) as fetcher:
        result = await fetcher.fetch("https://example.com/a")

    assert mock_get.await_count == 3
    assert result.status_code == 200
    assert result.html == "<html>ok</html>"
    assert result.error is None

    assert len(sleeps) == 3
    pre_delay, backoff_0, backoff_1 = sleeps
    assert 0.1 <= pre_delay <= 0.2
    assert 1.0 <= backoff_0 <= 1.5
    assert 2.0 <= backoff_1 <= 2.5


@pytest.mark.asyncio
async def test_http_fetcher_5xx_retry_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(stealth_mod.asyncio, "sleep", fake_sleep)
    _, mock_get = _patch_async_session(
        monkeypatch,
        [
            FakeResponse(500, "err0", "https://example.com/5xx"),
            FakeResponse(502, "err1", "https://example.com/5xx"),
            FakeResponse(503, "err2", "https://example.com/5xx"),
            FakeResponse(503, "err3", "https://example.com/5xx"),
        ],
    )

    async with HttpFetcher(
        min_delay=0.05,
        max_delay=0.1,
        max_retries=3,
        base_backoff=1.0,
        max_backoff_jitter=0.25,
    ) as fetcher:
        result = await fetcher.fetch("https://example.com/5xx")

    assert mock_get.await_count == 4
    assert result.status_code == 503
    assert result.html == "err3"
    assert result.error == "HTTP 503 after 3 retries"

    assert len(sleeps) == 4
    pre_delay, b0, b1, b2 = sleeps
    assert 0.05 <= pre_delay <= 0.1
    assert 1.0 <= b0 <= 1.25
    assert 2.0 <= b1 <= 2.25
    assert 4.0 <= b2 <= 4.25


@pytest.mark.asyncio
async def test_http_fetcher_403_blocked_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(stealth_mod.asyncio, "sleep", fake_sleep)
    _, mock_get = _patch_async_session(
        monkeypatch,
        [FakeResponse(403, "<html>captcha</html>", "https://example.com/blocked")],
    )

    async with HttpFetcher(min_delay=0.0, max_delay=0.0, max_retries=3) as fetcher:
        result = await fetcher.fetch("https://example.com/blocked")

    assert mock_get.await_count == 1
    assert sleeps == []
    assert result.status_code == 403
    assert result.html == "<html>captcha</html>"
    assert result.error == "HTTP 403"


@pytest.mark.asyncio
async def test_http_fetcher_network_exception_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(stealth_mod.asyncio, "sleep", fake_sleep)
    _, mock_get = _patch_async_session(
        monkeypatch,
        [ConnectionError("reset"), ConnectionError("reset"), ConnectionError("reset")],
    )

    async with HttpFetcher(
        min_delay=0.0,
        max_delay=0.0,
        max_retries=2,
        base_backoff=0.5,
        max_backoff_jitter=0.1,
    ) as fetcher:
        result = await fetcher.fetch("https://example.com/down")

    assert mock_get.await_count == 3
    assert len(sleeps) == 2
    assert 0.5 <= sleeps[0] <= 0.6
    assert 1.0 <= sleeps[1] <= 1.1
    assert result.status_code is None
    assert result.html is None
    assert result.final_url is None
    assert result.error == "ConnectionError: reset"


@pytest.mark.asyncio
async def test_http_fetcher_jitter_bounds_across_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(stealth_mod.asyncio, "sleep", fake_sleep)
    _patch_async_session(
        monkeypatch,
        [FakeResponse(200, "ok", "https://example.com") for _ in range(25)],
    )

    async with HttpFetcher(min_delay=0.3, max_delay=0.9) as fetcher:
        for _ in range(25):
            await fetcher.fetch("https://example.com")

    assert len(sleeps) == 25
    assert all(0.3 <= s <= 0.9 for s in sleeps)


def test_http_fetcher_validates_init_args() -> None:
    with pytest.raises(ValueError):
        HttpFetcher(min_delay=-0.1, max_delay=1.0)
    with pytest.raises(ValueError):
        HttpFetcher(min_delay=2.0, max_delay=1.0)
    with pytest.raises(ValueError):
        HttpFetcher(max_retries=-1)
    with pytest.raises(ValueError):
        HttpFetcher(user_agents=())


@pytest.mark.asyncio
async def test_browser_fetcher_uses_stealth_v2_and_tears_down(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mock_response = MagicMock()
    mock_response.status = 200

    mock_page = MagicMock()
    mock_page.url = "https://bot.sannysoft.com/"
    mock_page.goto = AsyncMock(return_value=mock_response)
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html><body>ok</body></html>")
    mock_page.close = AsyncMock()

    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock()

    mock_pw = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_wrapped_cm = MagicMock()
    mock_wrapped_cm.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_wrapped_cm.__aexit__ = AsyncMock(return_value=None)

    mock_stealth_instance = MagicMock()
    mock_stealth_instance.use_async = MagicMock(return_value=mock_wrapped_cm)
    mock_stealth_cls = MagicMock(return_value=mock_stealth_instance)

    raw_pw_cm: Any = object()
    monkeypatch.setattr(stealth_mod, "async_playwright", MagicMock(return_value=raw_pw_cm))
    monkeypatch.setattr(stealth_mod, "Stealth", mock_stealth_cls)

    shot = tmp_path / "nested" / "sannysoft.png"
    async with BrowserFetcher(headless=True, locale="en-US") as fetcher:
        result = await fetcher.fetch(
            "https://bot.sannysoft.com/",
            settle_ms=500,
            screenshot_path=shot,
        )

    mock_stealth_cls.assert_called_once_with()
    mock_stealth_instance.use_async.assert_called_once_with(raw_pw_cm)
    mock_pw.chromium.launch.assert_awaited_once_with(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    mock_page.wait_for_timeout.assert_awaited_once_with(500)
    mock_page.screenshot.assert_awaited_once_with(path=str(shot), full_page=True)
    mock_page.close.assert_awaited_once()
    mock_context.close.assert_awaited_once()
    mock_browser.close.assert_awaited_once()
    mock_wrapped_cm.__aexit__.assert_awaited_once_with(None, None, None)

    assert result == FetchResult(
        url="https://bot.sannysoft.com/",
        status_code=200,
        html="<html><body>ok</body></html>",
        final_url="https://bot.sannysoft.com/",
        error=None,
    )


@pytest.mark.asyncio
async def test_browser_fetcher_requires_context_manager() -> None:
    fetcher = BrowserFetcher()
    with pytest.raises(RuntimeError):
        await fetcher.fetch("https://example.com")
