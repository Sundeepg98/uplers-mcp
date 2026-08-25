"""The authenticated HTTP client. One bearer token, one error taxonomy.

Deliberately not a browser. Playwright appears in exactly one module of this
package - :mod:`uplers_server.auth`, for the sign-in handshake - and never for
fetching data, exactly as the public tier keeps the browser out of the data
path. Once the token is harvested this is plain httpx.

**Why `follow_redirects=False`.** Laravel answers an unauthenticated
browser-shaped request with `302 -> /console/login` and an HTML body. Following
that redirect turns a crisp "you are logged out" into a 200 carrying a login
page, which every JSON parser downstream would then report as a shape change.
Not following it keeps the failure legible.

**Why every non-success raises.** A failed fetch that returns `[]` is
indistinguishable from a successful fetch that matched nothing, and this
codebase has been bitten by that class of bug before. So there is exactly one
request path, it either returns parsed JSON or raises something from the
taxonomy below, and nothing in between.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Mapping

import httpx

from . import config, endpoints
from .client import UplersError

log = logging.getLogger("uplers.talent")

#: Sent so Laravel's Authenticate middleware answers 401-JSON rather than
#: redirecting to an HTML login page. This single header is the difference
#: between a legible failure and an illegible one.
JSON_HEADERS = {"Accept": "application/json"}


class TalentError(UplersError):
    """Any failure talking to the authenticated API. Always surfaced."""

    kind = "talent_error"


class AuthRequired(TalentError):
    """No live session: a 401, or a redirect to the login page.

    The message is written for a model to act on, because that is who reads it:
    it names the tool to call next.
    """

    kind = "auth_required"


class NotFound(TalentError):
    kind = "not_found"


class ValidationFailed(TalentError):
    """HTTP 422. Laravel puts the detail at `errors: {field: [message]}`."""

    kind = "validation_failed"

    def __init__(self, message: str, errors: dict | None = None) -> None:
        super().__init__(message)
        self.errors = errors or {}


class RateLimited(TalentError):
    kind = "rate_limited"


TokenSupplier = Callable[[], "str | None"]


class TalentClient:
    """Authenticated async JSON client. Use as an async context manager.

    The token is supplied by a callable rather than passed in, so a re-login
    mid-session is picked up without rebuilding the client, and so tests can
    hand over a fake without touching disk.
    """

    def __init__(
        self,
        token_supplier: TokenSupplier,
        *,
        delay: float = config.REQUEST_DELAY_SECONDS,
        timeout: float = config.REQUEST_TIMEOUT_SECONDS,
        max_retries: int = config.MAX_RETRIES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token_supplier = token_supplier
        self._delay = delay
        self._max_retries = max_retries
        self.requests_made = 0
        self._client = httpx.AsyncClient(
            base_url=endpoints.API_BASE,
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
            headers=dict(JSON_HEADERS),
        )

    async def __aenter__(self) -> "TalentClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- token -------------------------------------------------------------

    def has_token(self) -> bool:
        return bool(self._token_supplier())

    def _auth_header(self) -> dict[str, str]:
        """Bearer header, or nothing.

        Sending no Authorization header when there is no token still produces a
        clean 401 rather than a malformed-credential error, and that half of
        the original reasoning holds.

        THE OTHER HALF WAS REVERSED ON 2026-08-25. It used to say the point was
        that "never logged in" and "token went stale" report the same way. They
        must NOT: `_request` now refuses before spending a request when there is
        no token, because a first-run reader told "this is usually an expired
        token" is being told something false about their own situation. This
        header path is therefore only reached with a token that Uplers itself
        rejected - which is what makes the 401 message's "expired" wording true
        wherever it can now appear.
        """
        token = self._token_supplier()
        return {"Authorization": "Bearer %s" % token} if token else {}

    # -- the one request path ----------------------------------------------

    def _classify(self, response: httpx.Response, path: str) -> None:
        """Turn a non-success into the right exception. Returns only on success.

        **Any 2xx is a success, not just 200.** Reading this as `== 200` was a
        real bug: a write that answered `201 Created` or `204 No Content` would
        have raised *after the write had already landed*, and the caller's
        natural response to a failure is to retry. On `talent/hr/intrested` -
        which cannot be undone - that turns one apply into two.
        """
        status = response.status_code
        if 200 <= status < 300:
            return

        if status in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if "login" in location:
                raise AuthRequired(
                    "Uplers redirected %s to the login page, which means this session "
                    "is not signed in. Run uplers_login() to sign in again." % path
                )
            raise TalentError("GET %s unexpectedly redirected to %r" % (path, location))

        if status in (401, 403):
            raise AuthRequired(
                "Uplers answered %d Unauthenticated for %s. Uplers sessions are "
                "short-lived, so this is usually an expired token rather than a "
                "problem with your account. Run uplers_login() to sign in again."
                % (status, path)
            )

        if status == 404:
            raise NotFound("Uplers has no %s (HTTP 404)." % path)

        if status == 422:
            errors = {}
            try:
                body = response.json()
                if isinstance(body, dict):
                    errors = body.get("errors") or {}
            except ValueError:
                pass
            raise ValidationFailed(
                "Uplers rejected the request to %s as invalid (HTTP 422). "
                "Fields: %s" % (path, sorted(errors) or "not reported"),
                errors=errors,
            )

        if status == 429:
            raise RateLimited(
                "Uplers rate-limited this client (HTTP 429) on %s. Wait a minute "
                "before retrying; this server paces itself but the account is "
                "shared with your own browser sessions." % path
            )

        raise TalentError("Uplers answered HTTP %d for %s." % (status, path))

    @staticmethod
    def _parse(response: httpx.Response, path: str) -> Any:
        # A 204, or any 2xx with a genuinely empty body, means "it worked and
        # there is nothing to say". That is a legitimate write response, so it
        # becomes {} rather than a parse failure. It is NOT a licence for a read
        # to return nothing quietly: every read path validates its own envelope
        # and raises when the expected key is missing.
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "?")
            raise TalentError(
                "Uplers returned non-JSON for %s (content-type %r, %d bytes). The "
                "authenticated API may have changed shape, or this response is an "
                "HTML error page." % (path, content_type, len(response.content))
            ) from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
    ) -> Any:
        """Perform one call. Returns parsed JSON or raises. Never returns None."""
        if not self.has_token():
            # FIRST RUN, and it is a DIFFERENT ANSWER from an expired session.
            # Added 2026-08-25 under the four-server auth contract, and it
            # deliberately REVERSES the reasoning that used to sit on
            # `_auth_header`: that sending no header produced a clean 401 so
            # "never logged in" and "token went stale" reported the same way.
            #
            # Reporting them the same way is exactly the defect. These repos
            # are public now, so the reader is not necessarily the operator.
            # Somebody who has just cloned this and never signed in was being
            # told "Uplers sessions are short-lived, so this is usually an
            # expired token" - which is not true of them, does not name the
            # step they need, and costs a pointless round trip to Uplers to
            # discover something knowable from disk.
            raise AuthRequired(
                "Not signed in: no Uplers token is stored, so %s was not sent. "
                "This is a FIRST RUN rather than an expired session - nothing "
                "has gone wrong. Run uplers_login() and complete the Google "
                "sign-in in the browser window it opens; this server never "
                "handles a password. The public tier needs none of this: "
                "uplers_sync_index() then uplers_daily_brief() work with no "
                "account at all." % path
            )
        last_error = ""
        attempt = 0
        for attempt in range(1, self._max_retries + 1):
            if self._delay:
                await asyncio.sleep(self._delay)
            try:
                self.requests_made += 1
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    data=data,
                    files=files,
                    headers=self._auth_header(),
                )
            except httpx.HTTPError as exc:
                last_error = "%s: %s" % (type(exc).__name__, exc)
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2.0 ** attempt, 8.0))
                continue

            # A 5xx may fix itself; everything else is classified now, because
            # retrying a 401 or a 422 just spends the operator's rate budget.
            if response.status_code >= 500 and attempt < self._max_retries:
                last_error = "HTTP %d" % response.status_code
                await asyncio.sleep(min(2.0 ** attempt, 8.0))
                continue

            self._classify(response, path)
            return self._parse(response, path)

        raise TalentError(
            "%s %s failed after %d attempt(s): %s" % (method, path, attempt, last_error)
        )

    # -- verbs -------------------------------------------------------------

    async def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post_json(self, path: str, body: Mapping[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json_body=dict(body or {}))

    async def post_form(self, path: str, fields: Mapping[str, Any]) -> Any:
        """POST as multipart/form-data.

        Exactly one route needs this: ``talent/hr/intrested``, whose call sites
        build a `FormData` rather than a JSON body. httpx switches to multipart
        when `files=` is present, so the fields are passed that way with no
        filename - which is what a browser sends for `FormData.append(k, v)`.
        """
        parts = {key: (None, str(value)) for key, value in fields.items()}
        return await self._request("POST", path, files=parts)
