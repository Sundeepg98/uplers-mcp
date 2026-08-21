"""auth.py - the sign-in handshake, and the bug it exists in order not to repeat.

One property here is worth more than all the others: **a token is never
evidence**. The sibling Instahyre server shipped a login tool that returned
success the moment a session cookie appeared, and Django issues those to
anonymous visitors - so the condition was true before the operator typed
anything, the window shut after one poll, and the tool claimed a session while
every real call 401'd. Uplers wears the same trap differently: its SPA falls
back to an anonymous ``guest_token``, so localStorage can hold a token that
authenticates nothing.

So the first test in this file is the regression test for that bug, written
the long way round on purpose: a token present from the very first look, an API
that rejects it, and assertions that the loop kept the window open and let the
API cast the deciding vote. The rest pin the other half of the contract - that
an attempt which proves nothing leaves no trace, and that nothing on the way
out carries the token itself.

No test here opens a browser or touches the network. Playwright is replaced at
``auth._playwright_factory``, the browser objects are the fakes below, and
every HTTP response comes from ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from uplers_server import auth, endpoints
from uplers_server.session import SessionStore

from conftest import make_transport

LIVE = "42|live-bearer-token-that-must-never-be-printed"
STALE = "41|stale-bearer-token-that-uplers-rejects"
PRIOR = "40|the-token-that-was-already-working"
GUEST = "9|anonymous-guest-token"

PROFILE = {
    "talent_details": {"full_name": "Sundeep G", "email": "someone@example.com"},
    "profile_completion_percentage": 82,
}

#: Long enough for many polls, short enough that a timing-out test costs 0.2s.
#: The autouse `no_sleep` fixture makes the poll interval free, but the deadline
#: is still measured against the wall clock.
SHORT_WAIT = 0.2

#: Generous, because every test using it returns the moment the API says yes.
LONG_WAIT = 5.0


# --- the fake browser -----------------------------------------------------


def storage(token=None, guest=None):
    """What the page script returns: both localStorage keys, read together."""
    return {"token": token, "guest_token": guest}


class FakePage:
    """A page whose localStorage answers are scripted, one entry per read.

    The last entry repeats forever, so a test states what it wants to happen
    without having to know how many times the loop will look. An entry that is
    an exception is raised instead of returned, which is what a real page does
    while it is mid-navigation.
    """

    def __init__(self, reads, *, url=auth.LOGIN_URL, closed=False, closes_after=None):
        self._reads = list(reads)
        self._closes_after = closes_after
        self.url = url
        self._closed = closed
        self.evaluations = 0
        self.goto_urls = []

    def is_closed(self):
        return self._closed

    def close(self):
        self._closed = True

    async def goto(self, url, **kwargs):
        self.goto_urls.append(url)

    async def evaluate(self, script):
        assert "localStorage" in script
        self.evaluations += 1
        value = self._reads[min(self.evaluations - 1, len(self._reads) - 1)]
        if self._closes_after is not None and self.evaluations >= self._closes_after:
            self._closed = True
        if isinstance(value, Exception):
            raise value
        return value


class FakeContext:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.closed = False

    async def new_page(self):
        page = FakePage([storage()])
        self.pages.append(page)
        return page

    async def close(self):
        self.closed = True
        for page in self.pages:
            page.close()


class _FakeChromium:
    def __init__(self, context, launches):
        self._context = context
        self.launches = launches

    async def launch_persistent_context(self, profile_dir, **kwargs):
        self.launches.append((profile_dir, kwargs))
        return self._context


class _FakePlaywright:
    def __init__(self, context, launches):
        self.chromium = _FakeChromium(context, launches)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def install_browser(monkeypatch, context):
    """Point auth at a fake driver and report every launch it performs."""
    launches = []
    monkeypatch.setattr(
        auth,
        "_playwright_factory",
        lambda: (lambda: _FakePlaywright(context, launches)),
    )
    return launches


# --- fixtures and handlers ------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_browser_profile(monkeypatch, tmp_path):
    """No test may create or read the real data/browser_profile directory."""
    path = tmp_path / "browser_profile"
    path.mkdir()
    (path / "Default").mkdir()  # non-empty: a profile that has been used
    monkeypatch.setattr(auth, "browser_profile_path", lambda: path)
    return path


@pytest.fixture
def session_store(tmp_path):
    return SessionStore(tmp_path / "session.json")


def always(status, payload):
    def handler(request):
        return httpx.Response(status, json=payload)

    return handler


#: Uplers' measured logged-out answer for talent/* with Accept: application/json.
REJECT = always(401, {"message": "Unauthenticated."})
ACCEPT = always(200, PROFILE)


async def run_login(monkeypatch, session_store, pages, handler, **kwargs):
    """Drive the whole handshake over fakes. Returns (result, calls, context, launches)."""
    context = FakeContext(*pages)
    transport, calls = make_transport(handler)
    launches = install_browser(monkeypatch, context)
    kwargs.setdefault("wait_seconds", SHORT_WAIT)
    result = await auth.login_via_browser(session_store, transport=transport, **kwargs)
    return (result, calls, context, launches)


# --- THE REGRESSION -------------------------------------------------------


async def test_a_token_present_from_the_first_poll_is_never_taken_as_proof(
    monkeypatch, session_store
):
    """The Instahyre bug, in Uplers clothes. This is the most important test here.

    localStorage holds a token on the very first look and on every look after
    it - exactly the shape that closed the sibling server's window instantly.
    The window must stay open, the API must be asked, and the API's `no` must
    be the verdict.
    """
    page = FakePage([storage(token=STALE)])
    result, calls, context, _ = await run_login(monkeypatch, session_store, [page], REJECT)

    assert result["authenticated"] is False

    # It did not return on first sight of the token: the browser was looked at
    # over and over, and only the deadline ended the wait.
    assert page.evaluations > 1
    assert result["window_closed"] is False
    assert result["elapsed_seconds"] >= 0.1

    # The token was a reason to ASK. One request, carrying that exact token.
    assert result["checks_run"] == 1
    assert len(calls) == 1
    assert calls[0].url.path.endswith(endpoints.EP_AUTH_PROBE)
    assert calls[0].headers["authorization"] == "Bearer " + STALE
    assert result["checked_against"] == endpoints.AUTH_PROBE_NOTE

    # And the answer decided it. A rejected probe leaves nothing behind.
    assert session_store.token() is None
    assert "rejected it" in result["reason"]
    assert context.closed is True


# --- the guest token ------------------------------------------------------


async def test_a_guest_token_alone_is_never_offered_as_a_credential(
    monkeypatch, session_store
):
    """guest_token is present before anybody signs in. It buys zero requests."""
    page = FakePage([storage(guest=GUEST)])
    result, calls, _, _ = await run_login(monkeypatch, session_store, [page], ACCEPT)

    assert result["authenticated"] is False
    assert result["guest_token_present"] is True
    assert result["token_present"] is False

    # Note the handler above would have said yes to anything. Nothing asked it:
    # not one request was made, so the guest token cannot have been sent.
    assert calls == []
    assert result["checks_run"] == 0

    assert "guest_token" in result["reason"]
    assert GUEST not in json.dumps(result)
    assert session_store.token() is None


async def test_a_token_key_seeded_with_the_guest_value_is_still_a_guest_token(
    monkeypatch, session_store
):
    """The SPA's own expression is `token ?? guest_token`.

    A build that eagerly copies the guest value into `token` would otherwise be
    probed forever against a credential that cannot authenticate.
    """
    page = FakePage([storage(token=GUEST, guest=GUEST)])
    result, calls, _, _ = await run_login(monkeypatch, session_store, [page], ACCEPT)

    assert result["authenticated"] is False
    assert calls == []
    assert result["guest_token_present"] is True
    assert result["token_present"] is False


# --- the happy path -------------------------------------------------------


async def test_a_token_appearing_later_is_confirmed_against_the_api_and_saved(
    monkeypatch, session_store, isolated_browser_profile
):
    page = FakePage([storage(), storage(guest=GUEST), storage(token=LIVE, guest=GUEST)])
    result, calls, context, launches = await run_login(
        monkeypatch, session_store, [page], ACCEPT, wait_seconds=LONG_WAIT
    )

    assert result["authenticated"] is True
    assert page.evaluations == 3           # it returned on the tick it saw the token
    assert result["checks_run"] == 1
    assert calls[0].headers["authorization"] == "Bearer " + LIVE

    assert session_store.token() == LIVE
    assert session_store.describe()["method"] == "browser"
    assert result["signed_in_as"] == "Sundeep G"
    assert result["profile_completion_percentage"] == 82
    assert result["verified_by"] == endpoints.AUTH_PROBE_NOTE

    # A persistent profile, so the next run confirms in about a second.
    assert launches[0][0] == str(isolated_browser_profile)
    assert launches[0][1]["headless"] is False
    assert page.goto_urls == [auth.LOGIN_URL]
    assert context.closed is True


async def test_a_navigation_that_breaks_one_read_does_not_abort_the_wait(
    monkeypatch, session_store
):
    """evaluate() throwing is what a sign-in looks like, not a broken browser."""
    page = FakePage(
        [RuntimeError("Execution context was destroyed"), storage(token=LIVE)]
    )
    result, _, _, _ = await run_login(
        monkeypatch, session_store, [page], ACCEPT, wait_seconds=LONG_WAIT
    )

    assert result["authenticated"] is True
    assert page.evaluations == 2


async def test_a_sign_in_that_lands_in_another_tab_is_followed_not_mourned(
    monkeypatch, session_store
):
    opener = FakePage([storage()], closes_after=1)
    landing = FakePage([storage(token=LIVE)])
    result, _, _, _ = await run_login(
        monkeypatch, session_store, [opener, landing], ACCEPT, wait_seconds=LONG_WAIT
    )

    # The tab it opened died, which on its own reads like "the operator gave
    # up"; the living sibling is what makes that reading wrong.
    assert opener.is_closed() is True
    assert landing.evaluations >= 1
    assert result["authenticated"] is True
    assert session_store.token() == LIVE


async def test_localStorage_is_only_read_on_the_uplers_origin(monkeypatch, session_store):
    """localStorage is per-origin, so a read taken elsewhere is not Uplers' storage."""
    page = FakePage([storage(token=LIVE)], url="https://accounts.google.com/signin")
    result, calls, _, _ = await run_login(monkeypatch, session_store, [page], ACCEPT)

    assert result["authenticated"] is False
    assert page.evaluations == 0
    assert calls == []
    assert auth.PLATFORM_ORIGIN in result["reason"]


# --- the ways it ends without a session -----------------------------------


async def test_a_window_the_operator_closed_is_reported_as_closed(monkeypatch, session_store):
    page = FakePage([storage()], closes_after=1)
    result, calls, context, _ = await run_login(monkeypatch, session_store, [page], ACCEPT)

    assert result["authenticated"] is False
    assert result["window_closed"] is True
    assert result["checks_run"] == 0
    assert calls == []
    assert "closed before a signed-in session" in result["reason"]
    assert "uplers_auth_status()" in result["reason"]
    assert context.closed is True


async def test_a_timeout_with_no_token_says_what_to_do_next(monkeypatch, session_store):
    page = FakePage([storage()])
    result, calls, _, _ = await run_login(monkeypatch, session_store, [page], ACCEPT)

    assert result["authenticated"] is False
    assert result["window_closed"] is False
    assert result["checks_run"] == 0
    assert calls == []

    reason = result["reason"]
    assert "%ss" % SHORT_WAIT in reason          # how long it actually waited
    assert auth.LOGIN_URL in reason              # where to sign in
    assert "wait_seconds" in reason              # how to get more time
    assert result["elapsed_seconds"] >= 0.1


async def test_a_200_without_talent_details_is_unknown_and_not_a_session(
    monkeypatch, session_store
):
    """An anonymous token can also get a 200 here, so a 200 alone proves nothing.

    Unknown must not collapse in either direction: claiming True would ship the
    Instahyre bug again, and claiming False would send the operator back through
    a browser round trip for a session that may be perfectly fine.
    """
    page = FakePage([storage(token=LIVE)])
    result, calls, _, _ = await run_login(
        monkeypatch, session_store, [page], always(200, {"ok": True})
    )

    assert result["authenticated"] is None
    assert result["authenticated"] is not False
    assert result["authenticated"] is not True
    assert result["error"] == "unexpected_shape"
    assert result["checks_run"] == 1
    assert len(calls) == 1
    assert session_store.token() is None


# --- what a failed attempt costs ------------------------------------------


async def test_a_failed_attempt_does_not_clobber_a_working_token(monkeypatch, session_store):
    """A sign-in that proves nothing must not cost a session that was working."""
    session_store.save(PRIOR, method="browser")

    page = FakePage([storage(token=STALE)])
    result, calls, _, _ = await run_login(monkeypatch, session_store, [page], REJECT)

    assert result["authenticated"] is False
    # The candidate really was put through the credential slot - this is a
    # restore, not a no-op: the request carried STALE, not PRIOR.
    assert calls[0].headers["authorization"] == "Bearer " + STALE
    # And the slot holds exactly what it held before, method included.
    assert session_store.token() == PRIOR
    assert session_store.describe()["method"] == "browser"
    assert PRIOR not in json.dumps(result)


async def test_the_result_never_carries_the_token_value(monkeypatch, session_store):
    good = FakePage([storage(token=LIVE)])
    confirmed, _, _, _ = await run_login(
        monkeypatch, session_store, [good], ACCEPT, wait_seconds=LONG_WAIT
    )
    assert confirmed["authenticated"] is True
    assert LIVE not in json.dumps(confirmed)
    # The shape is reported instead of the value.
    assert confirmed["session"]["token_present"] is True

    bad = FakePage([storage(token=STALE)])
    rejected, _, _, _ = await run_login(monkeypatch, session_store, [bad], REJECT)
    assert rejected["authenticated"] is False
    assert STALE not in json.dumps(rejected)


async def test_a_progress_hook_that_raises_cannot_take_the_login_down(
    monkeypatch, session_store
):
    seen = []

    def hostile(elapsed, total, message):
        seen.append((elapsed, total, message))
        raise RuntimeError("the progress client went away")

    page = FakePage([storage(), storage(token=LIVE)])
    result, _, _, _ = await run_login(
        monkeypatch,
        session_store,
        [page],
        ACCEPT,
        wait_seconds=LONG_WAIT,
        on_progress=hostile,
    )

    assert result["authenticated"] is True
    assert len(seen) >= 2                 # called once per poll, every time
    assert seen[0][1] == LONG_WAIT
    assert auth.LOGIN_URL in seen[0][2]


# --- the silent path ------------------------------------------------------


async def test_refresh_returns_none_when_the_profile_holds_no_live_session(
    monkeypatch, session_store
):
    """The rule that governs the interactive path governs this one too.

    A dead profile still holds a token; only the API can say whether it works,
    and a `no` here must be silent rather than fatal - the server calls this on
    the way up.
    """
    page = FakePage([storage(token=STALE)])
    context = FakeContext(page)
    transport, calls = make_transport(REJECT)
    launches = install_browser(monkeypatch, context)

    assert await auth.refresh_from_profile(session_store, transport=transport) is None

    assert launches and launches[0][1]["headless"] is True
    assert calls[0].headers["authorization"] == "Bearer " + STALE
    assert session_store.token() is None
    assert context.closed is True


async def test_refresh_leaves_a_working_token_alone_when_the_profile_is_stale(
    monkeypatch, session_store
):
    session_store.save(PRIOR, method="browser")
    page = FakePage([storage(token=STALE)])
    transport, _ = make_transport(REJECT)
    install_browser(monkeypatch, FakeContext(page))

    assert await auth.refresh_from_profile(session_store, transport=transport) is None
    assert session_store.token() == PRIOR


async def test_refresh_ignores_a_profile_that_only_has_a_guest_token(
    monkeypatch, session_store
):
    page = FakePage([storage(guest=GUEST)])
    transport, calls = make_transport(ACCEPT)
    install_browser(monkeypatch, FakeContext(page))

    assert await auth.refresh_from_profile(session_store, transport=transport) is None
    assert calls == []
    assert session_store.token() is None


async def test_refresh_never_launches_for_a_profile_that_was_never_used(
    monkeypatch, session_store, tmp_path
):
    empty = tmp_path / "never_used"
    empty.mkdir()
    monkeypatch.setattr(auth, "browser_profile_path", lambda: empty)
    launches = install_browser(monkeypatch, FakeContext(FakePage([storage(token=LIVE)])))

    assert await auth.refresh_from_profile(session_store) is None
    assert launches == []


async def test_refresh_saves_a_token_the_api_confirms(monkeypatch, session_store):
    page = FakePage([storage(token=LIVE, guest=GUEST)])
    transport, calls = make_transport(ACCEPT)
    install_browser(monkeypatch, FakeContext(page))

    result = await auth.refresh_from_profile(session_store, transport=transport)

    assert result is not None
    assert result["authenticated"] is True
    assert result["method"] == "browser-refresh"
    assert calls[0].headers["authorization"] == "Bearer " + LIVE
    assert session_store.token() == LIVE
    assert session_store.describe()["method"] == "browser-refresh"
    assert LIVE not in json.dumps(result)


# --- no browser at all ----------------------------------------------------


async def test_a_missing_playwright_is_actionable_for_login_and_silent_for_refresh(
    monkeypatch, session_store
):
    # None in sys.modules makes the import fail whether or not the package is
    # installed, so this test means the same thing on every box.
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)

    with pytest.raises(auth.BrowserUnavailable) as excinfo:
        await auth.login_via_browser(session_store)

    message = str(excinfo.value)
    assert "pip install playwright && playwright install chromium" in message
    assert auth.BrowserUnavailable.kind == "browser_unavailable"

    # The background path swallows the very same failure.
    assert await auth.refresh_from_profile(session_store) is None
