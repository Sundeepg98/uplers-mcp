"""talent.py - the authenticated HTTP client and its error taxonomy.

Two properties of this client are load-bearing and neither is obvious from
reading a call site, so both are pinned here.

The first is that the token is *pulled* per request rather than captured at
construction. A Uplers session is short-lived; a re-login has to be picked up
by a client that is already open, or every long-running tool would have to be
rebuilt around a new token mid-flight.

The second is that nothing decays into a soft failure. Every non-200 becomes a
named exception, an unreadable body raises rather than returning None, and a
302 is a signal rather than something to chase. The taxonomy exists so a caller
can tell "sign in again" apart from "that requisition is gone" apart from
"Uplers is broken right now" - a distinction that vanishes the moment one of
these paths returns an empty result instead.

Every request below is served by httpx.MockTransport; nothing here touches the
network.
"""

from __future__ import annotations

import json

import httpx
import pytest

from uplers_server import config, endpoints
from uplers_server.client import UplersError
from uplers_server.talent import (
    AuthRequired,
    NotFound,
    RateLimited,
    TalentClient,
    TalentError,
    ValidationFailed,
)

from conftest import make_transport

TOKEN = "live-bearer-token-value"

PROBE = endpoints.EP_AUTH_PROBE


def make_client(handler, supplier=None, **kwargs):
    """A TalentClient wired to a MockTransport, with politeness delays off."""
    transport, calls = make_transport(handler)
    kwargs.setdefault("delay", 0)
    client = TalentClient(supplier or (lambda: TOKEN), transport=transport, **kwargs)
    return (client, calls)


def serve(payload=None, **kwargs):
    """Answer every request with the same 200 JSON body."""
    body = {"ok": True} if payload is None else payload
    return lambda request: httpx.Response(200, json=body, **kwargs)


# --- the token is pulled, never remembered --------------------------------


async def test_the_bearer_header_carries_the_value_the_supplier_returned():
    client, calls = make_client(serve())
    async with client:
        await client.get_json(PROBE)

    assert calls[0].headers["authorization"] == "Bearer " + TOKEN


async def test_the_supplier_is_consulted_on_every_request_not_cached_at_build():
    """A re-login mid-session must reach the wire without a new client.

    This is the entire reason the constructor takes a callable instead of a
    string. If the token were read once at __init__, the second request below
    would still carry the stale value and every tool holding an open client
    would keep 401ing after a successful uplers_login().
    """
    current = ["first-token"]
    client, calls = make_client(serve(), supplier=lambda: current[0])
    async with client:
        await client.get_json(PROBE)
        current[0] = "second-token-after-relogin"
        await client.get_json(PROBE)

    assert calls[0].headers["authorization"] == "Bearer first-token"
    assert calls[1].headers["authorization"] == "Bearer second-token-after-relogin"


async def test_no_token_refuses_BEFORE_spending_a_request():
    """First run is a different answer, and it is reached without a round trip.

    THIS TEST USED TO ASSERT THE OPPOSITE and the reversal is the point. It
    read: sending nothing gets the same clean 401 as an expired token, so
    "never logged in" and "token went stale" report identically instead of
    forking the caller.

    Reporting them identically is the defect. This repository is public, so the
    reader is not necessarily its owner. Somebody who had just cloned it and
    never signed in was told "Uplers sessions are short-lived, so this is
    usually an expired token" - false about their situation, silent about the
    step they needed, and paid for with a pointless round trip to Uplers to
    learn something already on disk.

    So: no token means no request at all, and the message names the next step.
    """
    client, calls = make_client(serve(), supplier=lambda: None)
    async with client:
        assert client.has_token() is False
        with pytest.raises(AuthRequired) as caught:
            await client.get_json(PROBE)

    assert calls == [], "a first run must not cost a request to diagnose"
    message = str(caught.value)
    assert "FIRST RUN" in message
    assert "uplers_login()" in message
    # THE SENTENCE, not the word. A first draft of this asserted that
    # "expired" was absent entirely, and that is too blunt: the message says
    # "a FIRST RUN rather than an expired session", which DISTINGUISHES the two
    # and is exactly what a confused reader needs. What must never reach them is
    # the diagnosis written for the operator - that their problem is probably a
    # stale token. Pin that sentence.
    assert "usually an expired token" not in message.lower(), (
        "the operator's expired-session diagnosis reached a reader who has "
        "never signed in - that is the sentence this test exists to keep away"
    )


async def test_a_token_that_exists_still_reaches_the_wire_unchanged():
    """The reversal must not have broken the ordinary path.

    A control for the test above: with a token present, the request goes out
    exactly as before and carries the bearer header. Without this, deleting the
    whole request path would satisfy the no-token assertion.
    """
    client, calls = make_client(serve(), supplier=lambda: "a-token")
    async with client:
        await client.get_json(PROBE)

    assert len(calls) == 1
    assert calls[0].headers["authorization"] == "Bearer a-token"


async def test_every_request_asks_for_json():
    """The header that decides whether a failure is legible.

    With Accept: application/json Laravel's Authenticate middleware answers
    401 with a JSON body. Without it, the same logged-out state arrives as a
    302 to an HTML login page - a shape change that reads downstream as a
    broken API rather than an expired session.
    """
    # A token, because a tokenless client now refuses before the wire. This
    # test is about the Accept header, not about auth.
    client, calls = make_client(serve(), supplier=lambda: "a-token")
    async with client:
        await client.get_json(PROBE)
        await client.post_json(endpoints.EP_NOT_INTERESTED, {"hr_number": "HR1"})

    assert calls[0].headers["accept"] == "application/json"
    assert calls[1].headers["accept"] == "application/json"


# --- the taxonomy ---------------------------------------------------------


async def test_a_401_is_auth_required():
    client, _ = make_client(lambda request: httpx.Response(401, json={"message": "Unauthenticated."}))
    async with client:
        with pytest.raises(AuthRequired) as excinfo:
            await client.get_json(PROBE)

    assert "uplers_login()" in str(excinfo.value)


async def test_a_403_is_auth_required_too():
    """403 is folded in on purpose: for this API both mean "not you, not now",
    and splitting them would hand the caller a distinction it cannot act on."""
    client, _ = make_client(lambda request: httpx.Response(403, json={"message": "Forbidden."}))
    async with client:
        with pytest.raises(AuthRequired):
            await client.get_json(PROBE)


async def test_a_redirect_to_the_login_page_is_auth_required():
    """A middleware change must not read as "logged in".

    If Uplers ever stops honouring Accept: application/json, the logged-out
    signal reverts to a 302. That has to keep landing on AuthRequired rather
    than on a generic error, or the operator gets told the API broke.
    """
    def handler(request):
        return httpx.Response(302, headers={"location": endpoints.LOGIN_REDIRECT})

    client, _ = make_client(handler)
    async with client:
        with pytest.raises(AuthRequired) as excinfo:
            await client.get_json(PROBE)

    assert "login page" in str(excinfo.value)


async def test_a_redirect_somewhere_else_is_an_error_but_not_auth_required():
    """Only a login redirect means logged out. A redirect to a maintenance
    page is a shape change, and claiming it is an expired session would send
    the operator through a browser sign-in that fixes nothing."""
    def handler(request):
        return httpx.Response(302, headers={"location": "https://platform.uplers.com/maintenance"})

    client, _ = make_client(handler)
    async with client:
        with pytest.raises(TalentError) as excinfo:
            await client.get_json(PROBE)

    assert not isinstance(excinfo.value, AuthRequired)
    assert "maintenance" in str(excinfo.value)


async def test_a_302_is_not_followed():
    """follow_redirects=False, proven by counting.

    A followed redirect would turn a crisp "you are logged out" into a 200
    carrying a login page - and two requests instead of one is the only
    evidence that survives at this layer.
    """
    def handler(request):
        return httpx.Response(302, headers={"location": endpoints.LOGIN_REDIRECT})

    client, calls = make_client(handler)
    async with client:
        with pytest.raises(AuthRequired):
            await client.get_json(PROBE)

    assert len(calls) == 1
    assert client.requests_made == 1


async def test_a_404_is_not_found():
    client, calls = make_client(lambda request: httpx.Response(404, text="gone"))
    async with client:
        with pytest.raises(NotFound) as excinfo:
            await client.get_json(endpoints.EP_SINGLE_HR)

    assert len(calls) == 1  # a 4xx will not fix itself
    assert endpoints.EP_SINGLE_HR in str(excinfo.value)


async def test_a_422_carries_the_field_errors_laravel_reported():
    """The 422 body is the only place that says WHICH field was wrong, and
    this API's identifier spaces are easy to mix up (id vs enc_id vs
    HR_Number), so losing that detail costs a guessing round."""
    body = {"message": "The given data was invalid.", "errors": {"hr_id": ["The hr id field is required."]}}
    client, _ = make_client(lambda request: httpx.Response(422, json=body))
    async with client:
        with pytest.raises(ValidationFailed) as excinfo:
            await client.post_json(endpoints.EP_INTRESTED, {"note": "x"})

    assert excinfo.value.errors == {"hr_id": ["The hr id field is required."]}
    assert "hr_id" in str(excinfo.value)


async def test_a_429_is_rate_limited():
    client, calls = make_client(lambda request: httpx.Response(429, text="slow down"))
    async with client:
        with pytest.raises(RateLimited) as excinfo:
            await client.get_json(PROBE)

    assert len(calls) == 1
    assert "429" in str(excinfo.value)


async def test_a_persistent_500_is_retried_and_then_raises():
    client, calls = make_client(lambda request: httpx.Response(500, text="boom"))
    async with client:
        with pytest.raises(TalentError) as excinfo:
            await client.get_json(PROBE)

    assert len(calls) == config.MAX_RETRIES == 3
    assert "HTTP 500" in str(excinfo.value)


async def test_a_non_json_body_raises_rather_than_returning_nothing():
    """An HTML error page is a failure, not a payload.

    Returning None here, or the raw text, would push an HTML blob into a
    parser that expects a dict - and the traceback would then blame the
    parser rather than the response that caused it.
    """
    def handler(request):
        return httpx.Response(200, text="<html>maintenance</html>",
                              headers={"content-type": "text/html"})

    client, calls = make_client(handler)
    async with client:
        with pytest.raises(TalentError) as excinfo:
            await client.get_json(PROBE)

    assert len(calls) == 1
    assert "non-JSON" in str(excinfo.value)
    assert "text/html" in str(excinfo.value)


# --- retries are for 5xx and transport faults only ------------------------


async def test_a_500_that_clears_on_the_second_attempt_returns_the_data():
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"recovered": True})

    client, calls = make_client(handler)
    async with client:
        payload = await client.get_json(PROBE)

    assert payload == {"recovered": True}
    assert len(calls) == 2


async def test_a_401_is_never_retried():
    """Retrying an expired token cannot succeed, and every attempt spends the
    operator's rate budget on an account he also browses from Chrome."""
    client, calls = make_client(lambda request: httpx.Response(401, json={"message": "Unauthenticated."}))
    async with client:
        with pytest.raises(AuthRequired):
            await client.get_json(PROBE)

    assert len(calls) == 1


async def test_a_transport_level_error_is_retried_and_reported_by_name():
    """The underlying exception name has to survive into the message: a DNS
    failure, a refused connection and a timeout all need different responses
    from whoever reads the error."""
    def handler(request):
        raise httpx.ConnectError("no route to host", request=request)

    client, calls = make_client(handler)
    async with client:
        with pytest.raises(TalentError) as excinfo:
            await client.get_json(PROBE)

    assert len(calls) == config.MAX_RETRIES == 3
    assert "ConnectError" in str(excinfo.value)
    assert "3 attempt(s)" in str(excinfo.value)


# --- the verbs ------------------------------------------------------------


async def test_post_json_sends_a_json_body():
    client, calls = make_client(serve({"status": "success"}))
    async with client:
        await client.post_json(endpoints.EP_NOT_INTERESTED, {"hr_number": "HR100725001919"})

    assert calls[0].method == "POST"
    assert json.loads(calls[0].content) == {"hr_number": "HR100725001919"}


async def test_post_form_sends_multipart_with_the_field_names_and_values():
    """talent/hr/intrested is the one route built from a browser FormData.

    Sending it as JSON gets a 422, so the multipart shape - field names and
    values, no filenames - is part of the contract rather than a detail of
    how httpx happened to encode it.
    """
    client, calls = make_client(serve({"status": "success"}))
    async with client:
        await client.post_form(endpoints.EP_INTRESTED, {"hr_id": 4211, "note": "keen"})

    request = calls[0]
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content.decode("utf-8")
    assert 'name="hr_id"' in body
    assert "4211" in body
    assert 'name="note"' in body
    assert "keen" in body


async def test_requests_made_counts_every_attempt_including_the_failed_ones():
    """The counter is the only evidence of how much of somebody else's rate
    budget a tool call spent, so a retried failure has to be counted too."""
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(200, json={"ok": True})
        if state["n"] == 2:
            return httpx.Response(404, text="gone")
        return httpx.Response(500, text="boom")

    client, calls = make_client(handler)
    async with client:
        await client.get_json(PROBE)
        with pytest.raises(NotFound):
            await client.get_json(PROBE)
        with pytest.raises(TalentError):
            await client.get_json(PROBE)

    # 1 success + 1 un-retried 404 + 3 attempts at the 500.
    assert client.requests_made == 5
    assert len(calls) == 5


# --- the taxonomy stays catchable upstream --------------------------------


def test_every_talent_error_is_an_uplers_error():
    """Callers written against the public tier catch UplersError.

    The authenticated tier arrived later; if its exceptions had been rooted
    anywhere else, every existing `except UplersError` would have stopped
    covering them silently - the failure mode being a traceback out of a tool
    rather than the tool's own error message.
    """
    for error in (AuthRequired, NotFound, ValidationFailed, RateLimited):
        assert issubclass(error, TalentError)
    assert issubclass(TalentError, UplersError)
    assert issubclass(UplersError, RuntimeError)


async def test_a_raised_auth_required_is_caught_by_except_uplers_error():
    """The inheritance above, exercised rather than asserted."""
    client, _ = make_client(lambda request: httpx.Response(401, json={"message": "Unauthenticated."}))
    async with client:
        with pytest.raises(UplersError):
            await client.get_json(PROBE)
