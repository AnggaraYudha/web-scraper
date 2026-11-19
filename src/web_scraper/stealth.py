from __future__ import annotations

import asyncio
import random
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self

from curl_cffi.requests import AsyncSession
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from playwright_stealth import Stealth

DEFAULT_USER_AGENTS: tuple[str, ...] = (
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
)

DEFAULT_VIEWPORT: dict[str, int] = {"width": 1366, "height": 768}


@dataclass(slots=True)
class FetchResult:
    url: str
    status_code: int | None
    html: str | None
    final_url: str | None
    error: str | None = None


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


class HttpFetcher:
    """Async HTTP fetcher backed by curl_cffi with Chrome TLS impersonation."""

    def __init__(
        self,
        *,
        impersonate: str = "chrome",
        min_delay: float = 0.5,
        max_delay: float = 1.5,
        max_retries: int = 3,
        base_backoff: float = 1.0,
        max_backoff_jitter: float = 0.5,
        timeout: float = 30.0,
        user_agents: Sequence[str] = DEFAULT_USER_AGENTS,
    ) -> None:
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError("min_delay must be >= 0 and max_delay >= min_delay")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if base_backoff < 0 or max_backoff_jitter < 0:
            raise ValueError("base_backoff and max_backoff_jitter must be >= 0")
        if not user_agents:
            raise ValueError("user_agents must not be empty")

        self.impersonate = impersonate
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff_jitter = max_backoff_jitter
        self.timeout = timeout
        self._user_agents = tuple(user_agents)
        self._ua_index = 0
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        if self._session is None:
            self._session = AsyncSession(impersonate=self.impersonate)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _next_user_agent(self) -> str:
        ua = self._user_agents[self._ua_index % len(self._user_agents)]
        self._ua_index += 1
        return ua

    def _compute_backoff(self, attempt: int) -> float:
        return self.base_backoff * (2**attempt) + random.uniform(0.0, self.max_backoff_jitter)

    async def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        if self._session is not None:
            return await self._fetch_with_session(self._session, url, headers=headers)
        async with AsyncSession(impersonate=self.impersonate) as session:
            return await self._fetch_with_session(session, url, headers=headers)

    async def _fetch_with_session(
        self,
        session: AsyncSession,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        if self.max_delay > 0:
            await asyncio.sleep(random.uniform(self.min_delay, self.max_delay))

        for attempt in range(self.max_retries + 1):
            req_headers = {"User-Agent": self._next_user_agent()}
            if headers:
                req_headers.update(headers)

            try:
                response = await session.get(url, headers=req_headers, timeout=self.timeout)
            except Exception as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(self._compute_backoff(attempt))
                    continue
                return FetchResult(
                    url=url,
                    status_code=None,
                    html=None,
                    final_url=None,
                    error=f"{type(exc).__name__}: {exc}",
                )

            status_code = int(response.status_code)
            html = response.text
            final_url = str(response.url)

            if _is_retryable_status(status_code):
                if attempt < self.max_retries:
                    await asyncio.sleep(self._compute_backoff(attempt))
                    continue
                return FetchResult(
                    url=url,
                    status_code=status_code,
                    html=html,
                    final_url=final_url,
                    error=f"HTTP {status_code} after {self.max_retries} retries",
                )

            if 200 <= status_code < 300:
                return FetchResult(
                    url=url,
                    status_code=status_code,
                    html=html,
                    final_url=final_url,
                    error=None,
                )

            return FetchResult(
                url=url,
                status_code=status_code,
                html=html,
                final_url=final_url,
                error=f"HTTP {status_code}",
            )

        return FetchResult(
            url=url,
            status_code=None,
            html=None,
            final_url=None,
            error="Exhausted retries",
        )


class BrowserFetcher:
    """Async headless Chromium fetcher with playwright-stealth v2 patches."""

    def __init__(
        self,
        *,
        headless: bool = True,
        viewport: dict[str, int] | None = None,
        locale: str = "en-US",
        timezone_id: str = "America/New_York",
        user_agent: str | None = None,
        timeout_ms: int = 30_000,
        stealth_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.headless = headless
        self.viewport = dict(viewport) if viewport is not None else dict(DEFAULT_VIEWPORT)
        self.locale = locale
        self.timezone_id = timezone_id
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self._stealth_kwargs = dict(stealth_kwargs) if stealth_kwargs else {}

        self._pw_cm: AbstractAsyncContextManager[Playwright] | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> Self:
        stealth = Stealth(**self._stealth_kwargs)
        pw_cm = stealth.use_async(async_playwright())
        self._pw_cm = pw_cm
        try:
            playwright = await pw_cm.__aenter__()
            self._playwright = playwright
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._browser = browser
            context_kwargs: dict[str, Any] = {
                "viewport": self.viewport,
                "locale": self.locale,
                "timezone_id": self.timezone_id,
            }
            if self.user_agent is not None:
                context_kwargs["user_agent"] = self.user_agent
            self._context = await browser.new_context(**context_kwargs)
        except Exception:
            await self.close()
            raise
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        errors: list[Exception] = []
        if self._context is not None:
            try:
                await self._context.close()
            except Exception as exc:
                errors.append(exc)
            finally:
                self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                errors.append(exc)
            finally:
                self._browser = None
        if self._pw_cm is not None:
            try:
                await self._pw_cm.__aexit__(None, None, None)
            except Exception as exc:
                errors.append(exc)
            finally:
                self._pw_cm = None
                self._playwright = None
        if errors:
            raise errors[0]

    async def fetch(
        self,
        url: str,
        *,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "networkidle",
        timeout_ms: int | None = None,
        settle_ms: int = 0,
        screenshot_path: str | Path | None = None,
    ) -> FetchResult:
        if self._context is None:
            raise RuntimeError("BrowserFetcher must be entered as an async context manager")

        page = await self._context.new_page()
        try:
            response = await page.goto(
                url,
                wait_until=wait_until,
                timeout=timeout_ms if timeout_ms is not None else self.timeout_ms,
            )
            if settle_ms > 0:
                await page.wait_for_timeout(settle_ms)
            if screenshot_path is not None:
                out_path = Path(screenshot_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(out_path), full_page=True)
            html = await page.content()
            final_url = page.url
            status_code = response.status if response is not None else None
            if status_code is not None and 200 <= status_code < 300:
                error = None
            elif status_code is not None:
                error = f"HTTP {status_code}"
            else:
                error = "No HTTP response received"
            return FetchResult(
                url=url,
                status_code=status_code,
                html=html,
                final_url=final_url,
                error=error,
            )
        except Exception as exc:
            return FetchResult(
                url=url,
                status_code=None,
                html=None,
                final_url=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            await page.close()
