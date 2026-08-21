"""The one module in this package allowed to open a browser.

Uplers authenticates every call with ``Authorization: Bearer <token>``, where
the token is whatever the SPA left in ``localStorage["token"]``. That value is
minted inside a sign-in flow this client has no business reimplementing, so the
honest way to obtain one is to open the real login page, let the operator sign
in with their own hands, and read the result out of the browser. Nothing here
types a credential and nothing here fetches job data: once a token is harvested
every request goes through :class:`~uplers_server.talent.TalentClient`.

**The completion condition is an authenticated request, never a token.** This
is the entire reason the module has this shape. The sibling Instahyre server
shipped a login tool that finished the moment a ``sessionid`` cookie appeared;
Django hands those to anonymous visitors, so the condition was already true
while the login page was still painting. The window closed after one poll and
the tool reported ``authenticated: true`` while every real call 401'd.

Uplers carries the same trap in different clothes. Its bundle reads
``localStorage["token"] ?? localStorage["guest_token"]``, and ``guest_token``
holds an ANONYMOUS token that exists before anybody signs in. So a token here
is a reason to ASK the server, never an answer. The only thing that ends the
wait successfully is :func:`~uplers_server.session.check_auth` returning
``authenticated: True``, measured against a route whose logged-out behaviour
was recorded live. ``guest_token`` is read for exactly one purpose: so that a
failure can say "that was only a guest token" instead of "no token appeared".

**The store is the credential slot, not a cache.** The probe token is written
to the :class:`~uplers_server.session.SessionStore` before it is checked, so
the client sends it the same way every other request in this server sends a
token, and a live session ends up saved with no second write path. The cost is
that a probe touches state the operator already had, which is why the previous
record is snapshotted up front and put back on any outcome other than a proven
success. A failed sign-in must never cost a session that was already working.

**Async, not sync.** Every tool in this server is a coroutine and the HTTP
client is ``httpx.AsyncClient``, so this uses ``playwright.async_api``. The
sync API raises the moment it is touched inside a running asyncio loop, which
is precisely where this code lives.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from . import config, endpoints
from .session import (
    GUEST_TOKEN_KEY,
    TOKEN_KEY,
    SessionStore,
    browser_profile_path,
    check_auth,
)
from .talent import TalentClient, TalentError

log = logging.getLogger("uplers.auth")

#: The page a human signs in on. Single-sourced from endpoints.py so a route
#: change lands in one file.
LOGIN_URL = endpoints.LOGIN_URL

#: Origin that owns the localStorage we care about. localStorage is per-origin,
#: so a read taken anywhere else (an OAuth hop, a blank tab) is not a read of
#: Uplers' storage and must not be mistaken for one.
PLATFORM_ORIGIN = config.BASE_URL

#: How long a window stays open for a human by default. Five minutes is a
#: password, an OTP, and a moment of looking for the phone.
DEFAULT_WAIT_S = 300

#: How often the loop wakes and looks at the browser. Local and free.
POLL_INTERVAL_S = 2.5

#: How often the loop spends an API request while the token has NOT changed.
#: A changed token is re-checked on the same tick it is seen, so this only
#: bounds the odd case of a session going live without localStorage moving.
#: It also keeps a 300s wait to roughly 21 requests instead of 120.
RECHECK_INTERVAL_S = 15.0

#: Callback signature: ``(elapsed_seconds, total_seconds, message)``.
ProgressHook = Callable[[float, float, str], None]

#: One round trip reads both keys, so the pair can never be seen half-updated.
#: The try/catch is inside the page because some origins throw on any
#: localStorage access, and an exception crossing the bridge would be reported
#: as a broken browser rather than as "nothing to read here".
_READ_TOKENS_JS = (
    "() => { try { return {"
    " token: window.localStorage.getItem('" + TOKEN_KEY + "'),"
    " guest_token: window.localStorage.getItem('" + GUEST_TOKEN_KEY + "')"
    " }; } catch (error) { return null; } }"
)

_WAITING_MESSAGE = (
    "Waiting for you to sign in at " + LOGIN_URL + " - the window stays open "
    "until Uplers confirms a signed-in session."
)


class BrowserUnavailable(TalentError):
    """Playwright is not installed, so no window can be opened at all."""

    kind = "browser_unavailable"


def _playwright_factory():
    """Return ``playwright.async_api.async_playwright``, or explain its absence.

    Imported here rather than at module scope for two reasons: Playwright is an
    optional dependency that nothing else in this server needs, and routing
    both entry points through one function gives the failure exactly one
    wording - and gives a test one place to substitute a driver, which is what
    keeps this suite from ever launching a real browser.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise BrowserUnavailable(
            "Playwright is not installed, so Uplers' login page cannot be opened. "
            "Run `pip install playwright && playwright install chromium`, then call "
            "uplers_login() again. There is no password path here: Uplers mints the "
            "bearer token inside its own sign-in flow."
        ) from exc
    return async_playwright


# ---------------------------------------------------------------------------
# Small helpers, each doing one thing the loop should not have to spell out
# ---------------------------------------------------------------------------


def _report(hook: ProgressHook | None, elapsed: float, total: float, message: str) -> None:
    """Progress is cosmetic. It may never take a sign-in down with it."""
    if hook is None:
        return
    try:
        hook(round(elapsed, 1), float(total), message)
    except Exception as exc:  # a dead progress client is not a failed sign-in
        log.debug("progress hook raised, ignoring: %s: %s", type(exc).__name__, exc)


def _live_pages(context: Any, page: Any) -> list:
    """Every page still open, the one we started on first.

    A sign-in can close the page it began on, or land in a fresh tab. A closed
    page with living siblings therefore means "follow the sibling", not "the
    operator gave up". An empty list is the only thing that counts as the
    window being gone, and a question we cannot get an answer to counts as
    gone too, because the alternative is hanging on a dead browser.
    """
    pages: list = []
    try:
        if page is not None and not page.is_closed():
            pages.append(page)
    except Exception:
        page = None
    try:
        siblings = list(context.pages)
    except Exception:
        return pages
    for sibling in siblings:
        if sibling is page:
            continue
        try:
            if not sibling.is_closed():
                pages.append(sibling)
        except Exception:
            continue
    return pages


def _on_platform(page: Any) -> bool:
    try:
        return str(page.url).startswith(PLATFORM_ORIGIN)
    except Exception:
        return False


def _clean(value: Any) -> str | None:
    """A token is a non-empty string or it is nothing."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lower() not in ("null", "undefined"):
            return stripped
    return None


async def _read_tokens(pages: list) -> tuple[str | None, str | None, bool]:
    """``(token, guest_token, read_ok)`` from the first page on the platform origin.

    ``read_ok`` is False when no page could be read at all - either none was on
    platform.uplers.com or ``evaluate`` threw. Evaluate throwing is ordinary:
    it happens whenever the page is mid-navigation, and a navigation is what a
    sign-in looks like. It must cost this tick, never the wait.
    """
    for page in pages:
        if not _on_platform(page):
            continue
        try:
            values = await page.evaluate(_READ_TOKENS_JS)
        except Exception as exc:
            log.debug("localStorage read failed this tick: %s: %s", type(exc).__name__, exc)
            continue
        if not isinstance(values, dict):
            # The page answered but storage was unreachable (see _READ_TOKENS_JS).
            return (None, None, True)
        return (_clean(values.get(TOKEN_KEY)), _clean(values.get(GUEST_TOKEN_KEY)), True)
    return (None, None, False)


async def _close_quietly(context: Any) -> None:
    try:
        await context.close()
    except Exception as exc:  # already gone is the normal case here
        log.debug("closing the browser context raised: %s: %s", type(exc).__name__, exc)


def _restore(store: SessionStore, snapshot: dict) -> None:
    """Put the session record back exactly as this attempt found it.

    Reinstates the token and the method that produced it; ``saved_at`` becomes
    now, which is the one field this cannot preserve without a raw-write API.
    An attempt that proved nothing must leave no trace beyond that.
    """
    token = snapshot.get("token")
    if isinstance(token, str) and token:
        store.save(token, method=snapshot.get("method") or "restored")
    else:
        store.clear()


# ---------------------------------------------------------------------------
# The wait
# ---------------------------------------------------------------------------


async def _wait_for_signed_in_session(
    context: Any,
    page: Any,
    client: TalentClient,
    store: SessionStore,
    *,
    started: float,
    wait_seconds: float,
    on_progress: ProgressHook | None,
) -> dict:
    """Poll until Uplers says we are signed in, the window dies, or time runs out.

    Takes the browser objects as parameters so the whole decision procedure can
    be driven by fakes; the caller owns launching and closing. Returns a record
    of what happened. It never claims a session it did not measure, and it
    never closes the wait early because a token showed up.
    """
    record: dict[str, Any] = {
        "status": None,
        "checks": 0,
        "window_closed": False,
        "token_seen": False,
        "guest_token_seen": False,
        "origin_reads": 0,
        "saved": False,
    }
    checked_token: str | None = None
    last_check_at = 0.0

    while True:
        elapsed = time.time() - started
        _report(on_progress, elapsed, wait_seconds, _WAITING_MESSAGE)

        pages = _live_pages(context, page)
        if not pages:
            record["window_closed"] = True
            break
        page = pages[0]

        token, guest, read_ok = await _read_tokens(pages)
        if read_ok:
            record["origin_reads"] += 1
        if guest:
            record["guest_token_seen"] = True
        if token and token == guest:
            # The SPA's own expression is `token ?? guest_token`, so a build
            # that seeds `token` with the guest value would otherwise be probed
            # forever against a credential that cannot authenticate.
            record["guest_token_seen"] = True
            token = None
        if token:
            record["token_seen"] = True

        now = time.time()
        # A token is only ever a reason to ASK. It is never an answer.
        worth_asking = token is not None and (
            checked_token is None
            or token != checked_token
            or (now - last_check_at) >= RECHECK_INTERVAL_S
        )
        if worth_asking:
            checked_token = token
            last_check_at = now
            record["checks"] += 1
            # The store is the credential slot the client reads from; this is
            # how the candidate token gets sent, and why the caller restores.
            store.save(token, method="browser")
            status = await check_auth(client)
            record["status"] = status
            if status.get("authenticated") is True:
                record["saved"] = True
                return record

        elapsed = time.time() - started
        if elapsed >= wait_seconds:
            break
        await asyncio.sleep(min(POLL_INTERVAL_S, max(wait_seconds - elapsed, 0.0)))

    # No final catch-up check on purpose: any token differing from the last one
    # checked already satisfies `worth_asking`, so a newly signed-in tab is put
    # to the API on the same tick it is harvested. There is no unchecked state
    # left to rescue, and a rescue that cannot fire is worse than none - it
    # reads like a safety net.
    return record


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def login_via_browser(
    store: SessionStore,
    *,
    wait_seconds: float = DEFAULT_WAIT_S,
    headless: bool = False,
    on_progress: ProgressHook | None = None,
    transport: Any | None = None,
) -> dict:
    """Open Uplers' login page and wait for the operator to actually sign in.

    Uses a **persistent** profile directory, so a later run usually finds the
    session already live and returns in about a second without asking for
    anything.

    Args:
        store: where a proven token is written. Also the slot the probe token
            passes through, which is why it is snapshotted and restored.
        wait_seconds: how long to leave the window open for a human.
        headless: only useful for re-checking an already-live profile. A
            headless window cannot complete an interactive sign-in.
        on_progress: optional ``(elapsed, total, message)`` hook, called once
            per poll. Exceptions from it are swallowed.
        transport: optional httpx transport for the verification client, so
            the whole handshake can be driven without a network.

    Returns:
        A dict whose ``authenticated`` is True only when Uplers said so, False
        on a timeout or a window the operator closed, and **None** when the
        state could not be determined - unknown does not collapse into false
        here any more than it does in ``check_auth``, because "you are logged
        out, sign in again" is a lie that costs a browser round trip. The dict
        never carries the token, a prefix of it, or its length.

    Raises:
        BrowserUnavailable: Playwright is not installed.
    """
    factory = _playwright_factory()
    profile_dir = browser_profile_path()
    started = time.time()
    before = store.read()

    async with factory() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(profile_dir),
            headless=headless,
            # The operator signs in with their own hands in this window; it
            # should look like the browser they would have opened themselves.
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
            log.info(
                "browser open at %s - waiting up to %ss for a confirmed sign-in",
                LOGIN_URL,
                wait_seconds,
            )
            async with TalentClient(store.token, transport=transport) as client:
                record = await _wait_for_signed_in_session(
                    context,
                    page,
                    client,
                    store,
                    started=started,
                    wait_seconds=wait_seconds,
                    on_progress=on_progress,
                )
        finally:
            await _close_quietly(context)

    status = record["status"] or {}
    common = {
        "method": "browser",
        "profile_dir": str(profile_dir),
        "elapsed_seconds": round(time.time() - started, 1),
        "checks_run": record["checks"],
        "checked_against": status.get("checked_against", endpoints.AUTH_PROBE_NOTE),
    }

    if status.get("authenticated") is True:
        log.info("signed-in session confirmed after %ss", common["elapsed_seconds"])
        confirmed = {
            "authenticated": True,
            "verified_by": status.get("checked_against"),
            "session": store.describe(),
            **common,
        }
        for key in ("signed_in_as", "profile_completion_percentage"):
            if status.get(key) is not None:
                confirmed[key] = status[key]
        return confirmed

    # Nothing below this line got a proven session. Put the record back and say
    # plainly what happened and what to do about it.
    _restore(store, before)

    if status.get("authenticated") is None and status:
        return {
            "authenticated": None,
            "reason": (
                "Could not determine whether the sign-in succeeded: %s"
                % status.get("reason", "the auth check returned no verdict")
            ),
            "error": status.get("error"),
            "window_closed": record["window_closed"],
            **common,
        }

    if record["window_closed"]:
        reason = (
            "The browser window was closed before a signed-in session could be "
            "confirmed. If you did finish signing in, the persistent profile kept "
            "it: call uplers_auth_status(), or run uplers_login() again and it will "
            "confirm in about a second. Otherwise leave the window open until this "
            "tool returns on its own."
        )
    else:
        reason = (
            "No signed-in session appeared within %ss. The window was open at %s - "
            "sign in there and call uplers_login() again, with a larger wait_seconds "
            "if you need more time." % (wait_seconds, LOGIN_URL)
        )
        if record["checks"]:
            reason += (
                " A token was present and was put to %s every time it changed, and "
                "Uplers rejected it, so this was not a session that merely needed "
                "more time." % endpoints.EP_AUTH_PROBE
            )
        elif record["guest_token_seen"]:
            reason += (
                " Only an anonymous %s was in localStorage. Uplers hands that to "
                "signed-out visitors and it never authenticates, so no request was "
                "spent on it." % GUEST_TOKEN_KEY
            )
        elif not record["origin_reads"]:
            reason += (
                " No tab was on %s while waiting, so there was no Uplers localStorage "
                "to read - finish the sign-in in the tab this tool opened rather than "
                "in another window." % PLATFORM_ORIGIN
            )

    return {
        "authenticated": False,
        "reason": reason,
        "window_closed": record["window_closed"],
        "token_present": record["token_seen"],
        "guest_token_present": record["guest_token_seen"],
        **common,
    }


async def refresh_from_profile(
    store: SessionStore,
    *,
    transport: Any | None = None,
) -> dict | None:
    """Silently re-harvest a token from the persistent profile, if one is live.

    The transparent-refresh path: no window is shown and every failure returns
    None rather than raising, because the caller always has the interactive
    path to fall back on and a background refresh must never take the server
    down. A missing Playwright is one of those failures, not an error.

    Same rule as the interactive path: a dead profile still holds a
    ``guest_token``, so whatever is harvested is verified against the API
    before it is allowed to stand, and the previous record is put back if it
    does not check out.
    """
    try:
        factory = _playwright_factory()
    except BrowserUnavailable:
        return None

    profile_dir = browser_profile_path()
    try:
        if not any(profile_dir.iterdir()):
            return None  # nothing has ever been signed in here
    except OSError:
        return None

    before = store.read()
    try:
        async with factory() as pw:
            context = await pw.chromium.launch_persistent_context(
                str(profile_dir), headless=True
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                # Any page on the origin will do; localStorage is per-origin,
                # and this is the one URL in endpoints.py verified to exist.
                await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)
                token, guest, _ = await _read_tokens(_live_pages(context, page))
            finally:
                await _close_quietly(context)
    except Exception as exc:  # a silent refresh must never take the server down
        log.info("silent session refresh could not read the profile: %s", exc)
        return None

    if token is None or token == guest:
        return None

    try:
        store.save(token, method="browser-refresh")
        async with TalentClient(store.token, transport=transport) as client:
            status = await check_auth(client)
    except Exception as exc:
        _restore(store, before)
        log.info("silent session refresh could not verify the profile token: %s", exc)
        return None

    if status.get("authenticated") is not True:
        _restore(store, before)
        log.info(
            "the browser profile holds no live session (%s)",
            status.get("reason") or status.get("error") or "the endpoint said no",
        )
        return None

    refreshed = {
        "authenticated": True,
        "method": "browser-refresh",
        "verified_by": status.get("checked_against"),
        "session": store.describe(),
    }
    if status.get("signed_in_as") is not None:
        refreshed["signed_in_as"] = status["signed_in_as"]
    return refreshed
