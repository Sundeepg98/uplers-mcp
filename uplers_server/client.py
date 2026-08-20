"""Async HTTP client for the two public Uplers endpoints.

Design rules, in priority order:

1. Be a good citizen. Bounded concurrency, a delay between requests, and an
   actual reaction to the server's own X-RateLimit-Remaining header.
2. Fail loudly. A failed fetch raises or is reported per-id. It is never
   swallowed into an empty result that reads like "no matches".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from . import config


class UplersError(RuntimeError):
    """Any failure talking to platform.uplers.com. Always surfaced to caller."""


class RateLimitExhausted(UplersError):
    """The server's advertised remaining budget fell below the abort floor."""


@dataclass
class FetchReport:
    """What a batch fetch actually managed. Both halves are always reported."""

    records: dict[str, dict] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    requests_made: int = 0
    ratelimit_remaining: int | None = None
    aborted_reason: str | None = None

    @property
    def ok(self) -> bool:
        return not self.failures and self.aborted_reason is None


class UplersClient:
    """Thin wrapper over httpx.AsyncClient. Use as an async context manager."""

    def __init__(
        self,
        *,
        concurrency: int = config.MAX_CONCURRENCY,
        delay: float = config.REQUEST_DELAY_SECONDS,
        timeout: float = config.REQUEST_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._delay = delay
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._client = httpx.AsyncClient(
            base_url=config.BASE_URL,
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "application/json"},
        )
        self.ratelimit_remaining: int | None = None
        self.requests_made = 0

    async def __aenter__(self) -> "UplersClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- rate-limit bookkeeping -------------------------------------------

    def _note_ratelimit(self, response: httpx.Response) -> None:
        raw = response.headers.get("X-RateLimit-Remaining")
        if raw is None:
            return
        try:
            self.ratelimit_remaining = int(raw)
        except ValueError:
            return
        if self.ratelimit_remaining < config.RATELIMIT_ABORT_BELOW:
            raise RateLimitExhausted(
                "Uplers reports only %d requests left in its rate-limit window "
                "(abort floor %d). Stopping so the account/IP is not throttled. "
                "Wait a minute and retry."
                % (self.ratelimit_remaining, config.RATELIMIT_ABORT_BELOW)
            )

    async def _throttle(self) -> None:
        if (
            self.ratelimit_remaining is not None
            and self.ratelimit_remaining < config.RATELIMIT_SLOW_BELOW
        ):
            await asyncio.sleep(config.RATELIMIT_SLOW_SLEEP_SECONDS)
        elif self._delay:
            await asyncio.sleep(self._delay)

    # -- single requests ---------------------------------------------------

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        """GET with bounded retries. Raises UplersError with a real reason."""
        last_error = ""
        for attempt in range(1, config.MAX_RETRIES + 1):
            async with self._semaphore:
                await self._throttle()
                try:
                    self.requests_made += 1
                    response = await self._client.get(url, params=params)
                except httpx.HTTPError as exc:
                    last_error = "%s: %s" % (type(exc).__name__, exc)
                    response = None
            if response is not None:
                self._note_ratelimit(response)
                if response.status_code == 200:
                    return response
                last_error = "HTTP %d" % response.status_code
                if response.status_code < 500 and response.status_code != 429:
                    break  # a 4xx will not fix itself
            if attempt < config.MAX_RETRIES:
                await asyncio.sleep(min(2.0 ** attempt, 8.0))
        raise UplersError("GET %s failed after %d attempt(s): %s" % (url, attempt, last_error))

    async def get_record(self, hr_number: str) -> dict:
        """Fetch one requisition. Raises UplersError on any failure."""
        response = await self._get(config.RECORD_PATH, {"hr_number": hr_number})
        try:
            payload = response.json()
        except ValueError as exc:
            raise UplersError(
                "Uplers returned non-JSON for %s (content-type %r). The public "
                "endpoint may have changed shape." % (hr_number, response.headers.get("content-type"))
            ) from exc
        if not isinstance(payload, dict) or "HR_Number" not in payload:
            raise UplersError(
                "Uplers returned an unexpected payload for %s: %s"
                % (hr_number, sorted(payload)[:8] if isinstance(payload, dict) else type(payload).__name__)
            )
        return payload

    async def get_sitemap(self) -> str:
        """Fetch sitemap.xml as text. Raises UplersError on any failure."""
        response = await self._get(config.SITEMAP_PATH)
        text = response.text
        if "<urlset" not in text:
            raise UplersError(
                "sitemap.xml did not look like a sitemap (%d bytes, starts %r)."
                % (len(text), text[:80])
            )
        return text

    # -- batch -------------------------------------------------------------

    async def get_records(self, hr_numbers: list[str]) -> FetchReport:
        """Fetch many requisitions concurrently, reporting successes AND failures.

        Never raises for a per-id failure; it records it. Only a rate-limit
        abort stops the batch early, and that is reported too.
        """
        report = FetchReport()
        stop = asyncio.Event()

        async def one(hr_number: str) -> None:
            if stop.is_set():
                return
            try:
                report.records[hr_number] = await self.get_record(hr_number)
            except RateLimitExhausted as exc:
                stop.set()
                report.aborted_reason = str(exc)
            except UplersError as exc:
                report.failures[hr_number] = str(exc)

        await asyncio.gather(*(one(h) for h in hr_numbers))
        report.requests_made = self.requests_made
        report.ratelimit_remaining = self.ratelimit_remaining
        return report
