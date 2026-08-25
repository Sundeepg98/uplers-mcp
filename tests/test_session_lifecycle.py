"""uplers_session_info and uplers_logout - the honesty properties, not the shape.

These two tools exist to answer one question the operator actually has ("is my
Uplers session alive, and how long have I got?") and there are exactly two ways
to answer it dishonestly. Both have shipped in this family of servers before,
so both get a test here and both get a CONTROL that proves the test can go red.

**Presence read as a verdict.** The sibling Instahyre server shipped a login
that succeeded the moment a session cookie appeared - Django hands those to
anonymous visitors, so the condition was true before anybody typed. Uplers
carries the same trap in different clothes: the SPA falls back to
``localStorage["guest_token"]``, so a token can be present and anonymous. The
rule that follows is absolute: ``authenticated`` comes from
:func:`uplers_server.session.check_auth` and from nowhere else, and where that
returns None the tool reports null WITH A REASON. Never false, never true.
``scripts/presence_is_auth_control.py`` re-creates the bug by deriving the
verdict from ``client.has_token()``; the tests marked __PRESENCE below go red
under it, and the measured counts are in that file's docstring.

**A ceiling read as a runway.** The stored token is a JWT whose ``exp`` claim
sits roughly six months out. That number is TRUE and USELESS: Uplers revokes
server-side within about a day, which this server's own login docstring and MCP
instructions both say. A tool that printed "expires 2027-02-17" and stopped
would be accurate and would still cost the operator a working morning, which is
why ``expiry_is_authoritative`` is false here and why its prose is asserted
rather than merely its boolean. A ``false`` with an empty explanation is the
same defect wearing a flag.

The third property has no clever name: **the token is never returned**. Not the
value, not a prefix, not a length. Asserted by walking every string in every
payload these tools can produce, including the error paths.

Isolation, all autouse:
  * NO REAL SESSION FILE. ``server._session_store`` and ``session.session_path``
    both point at tmp_path. The real ``data/session.json`` holds a LIVE bearer
    token and ``uplers_logout`` deletes it; no test here may reach it.
  * NO NETWORK unless a test wires a MockTransport itself.
  * NO BROWSER, ever.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

import server
from uplers_server import auth as auth_mod
from uplers_server import endpoints
from uplers_server import session as session_mod
from uplers_server.session import SessionStore
from uplers_server.talent import TalentClient

from conftest import leaks_of, make_transport, secret_fragments
from credential_echo_control import TRANSFORMS, render

#: A Sanctum-shaped token: `<id>|<plaintext>`. No expiry is knowable from it.
SANCTUM = "42|bearer-token-that-must-never-be-printed"

#: A bare string that is neither a JWT nor Sanctum-shaped.
OPAQUE = "opaque-secret-that-must-never-be-printed"


def make_jwt(exp: float | None, tag: str = "shared") -> str:
    """A structurally real JWT. The signature is not checked by anything here.

    Built rather than captured because a captured one would be the operator's
    actual credential, and a fixture file is the wrong place for that.

    `tag` makes the SUBJECT and the SIGNATURE differ between tokens, which
    real JWTs do and this helper originally did not. That mattered: with a
    constant signature, two different credentials shared a fragment, and the
    detector below cannot tell "this string identifies one credential" from
    "this string is a property of the format" except by asking whether an
    unrelated credential of the same format also contains it.
    """

    def seg(payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    claims: dict = {"sub": "talent-%s-must-never-be-printed" % tag}
    if exp is not None:
        claims["exp"] = exp
    return "%s.%s.%s" % (
        seg({"alg": "HS256", "typ": "JWT"}),
        seg(claims),
        "signature-%s-must-never-be-printed" % tag,
    )


#: Six months out, which is the real token's shape and the whole reason
#: `expiry_is_authoritative` exists.
JWT_SIX_MONTHS = make_jwt(time.time() + 180 * 86400, "six")
JWT_PAST = make_jwt(time.time() - 3 * 86400, "past")
JWT_NO_EXP = make_jwt(None, "noexp")

#: Every secret string above, so the leak sweep has one list to walk.
SECRETS = (SANCTUM, OPAQUE, JWT_SIX_MONTHS, JWT_PAST, JWT_NO_EXP)

#: A JWT this suite never stores, used ONLY to subtract the parts of a JWT that
#: are true of every JWT. Without it the detector treats "eyJhbGciOiJI" - the
#: base64 of a standard HS256 header - as though it identified a credential.
FORMAT_DECOY = make_jwt(1, "decoy-never-stored-anywhere")

#: secret -> the fragments whose appearance in a payload discloses it. See the
#: long note in tests/conftest.py for why a substring hunt on the whole value
#: is not enough when the credential is a JWT.
FRAGMENTS = secret_fragments(SECRETS, format_decoys=(FORMAT_DECOY,))


# --- isolation ------------------------------------------------------------


@pytest.fixture(autouse=True)
def session_file(monkeypatch, tmp_path):
    """Both constructors point at tmp_path. Belt and braces, and both needed.

    ``server._session_store`` is what the tools call; ``session.session_path``
    is what a default-constructed SessionStore anywhere else would resolve to.
    """
    path = tmp_path / "session.json"
    monkeypatch.setattr(session_mod, "session_path", lambda: path)
    monkeypatch.setattr(server, "_session_store", lambda: SessionStore(path))
    return path


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("no test in this file may open a browser")

    monkeypatch.setattr(auth_mod, "login_via_browser", refuse)


class NoNetwork:
    """Stand-in for TalentClient: constructing one is a test failure.

    This is the instrument for the verify_live=False property. A tool that
    quietly spent a request would otherwise pass a shape assertion perfectly.
    """

    def __init__(self, *args, **kwargs):
        raise AssertionError("this call must not construct an HTTP client")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Default to no network. A test that wants one calls `wire` explicitly."""
    monkeypatch.setattr(server, "TalentClient", NoNetwork)
    monkeypatch.setattr(server, "UplersClient", NoNetwork)


def wire(monkeypatch, handler, token=SANCTUM):
    """Let the tool build a real TalentClient over a MockTransport."""
    transport, calls = make_transport(handler)
    monkeypatch.setattr(
        server,
        "TalentClient",
        lambda *a, **k: TalentClient(lambda: token, transport=transport, delay=0),
    )
    return calls


def probe_ok(request):
    """A 200 that carries his profile back - the only shape that means yes."""
    return httpx.Response(
        200,
        json={
            "talent_details": {"full_name": "Sundeep G"},
            "profile_completion_percentage": 88,
        },
    )


def probe_401(request):
    return httpx.Response(401, json={"message": "Unauthenticated."})


def probe_guest(request):
    """HTTP 200 with no talent_details - what an anonymous guest token gets.

    The single most important fixture in this file. This is the response that
    a presence-based build calls "authenticated" and that check_auth correctly
    calls unknown.
    """
    return httpx.Response(200, json={"status": 200, "data": {}})


def probe_500(request):
    return httpx.Response(500, text="upstream is having a day")


def strings(node, trail=""):
    """Every string in a payload, with the path that reached it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from strings(value, "%s.%s" % (trail, key))
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            yield from strings(item, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        yield (trail, node)


# --- the verdict is measured, never presence __PRESENCE -------------------


class TestTheVerdictComesFromTheProbe:
    """Every test here goes red under presence_is_auth_control.py."""

    async def test_a_guest_200_is_null_not_false_and_not_true(
            self, monkeypatch, session_file):
        """__PRESENCE. The token is PRESENT and the answer is still null.

        A 200 without `talent_details` is exactly what an anonymous guest
        token gets. Presence says yes; the probe says "I cannot tell"; the
        probe wins.
        """
        SessionStore(session_file).save(SANCTUM, method="test")
        wire(monkeypatch, probe_guest)

        result = await server.uplers_session_info()

        assert result["authenticated"] is None
        assert result["credential"]["present"] is True
        assert result["live_check"]["attempted"] is True
        assert result["live_check"]["completed"] is False
        assert result["live_check"]["why_not"]
        assert "guest token" in result["live_check"]["why_not"]
        assert "not because Uplers said no" in result["live_check"]["what_it_means"].replace("NOT", "not")

    async def test_a_transport_failure_is_null_with_the_reason_attached(
            self, monkeypatch, session_file):
        """__PRESENCE. Network down, token on disk. Still null."""
        SessionStore(session_file).save(SANCTUM, method="test")
        wire(monkeypatch, probe_500)

        result = await server.uplers_session_info()

        assert result["authenticated"] is None
        assert result["credential"]["present"] is True
        assert result["live_check"]["completed"] is False
        assert result["live_check"]["why_not"]

    async def test_a_401_with_a_token_present_is_a_real_false(
            self, monkeypatch, session_file):
        """__PRESENCE. Presence would say true; Uplers said no, so false."""
        SessionStore(session_file).save(SANCTUM, method="test")
        wire(monkeypatch, probe_401)

        result = await server.uplers_session_info()

        assert result["authenticated"] is False
        assert result["credential"]["present"] is True
        assert result["live_check"]["completed"] is True
        assert "why_not" not in result["live_check"]
        assert "REFUSED" in result["live_check"]["what_it_means"]

    async def test_a_real_yes_is_a_yes_and_says_where_it_came_from(
            self, monkeypatch, session_file):
        SessionStore(session_file).save(SANCTUM, method="test")
        wire(monkeypatch, probe_ok)

        result = await server.uplers_session_info()

        assert result["authenticated"] is True
        assert result["live_check"]["completed"] is True
        assert result["checked_against"] == endpoints.AUTH_PROBE_NOTE
        assert result["live_check"]["endpoint"] == endpoints.AUTH_PROBE_NOTE
        assert result["signed_in_as"] == "Sundeep G"

    async def test_no_token_and_a_401_is_false_not_null(
            self, monkeypatch, session_file):
        """The CONTROL for the tests above: this one must stay GREEN.

        With no token stored, a presence-based build and an honest one agree,
        so this case cannot distinguish them. It is here to prove the suite is
        not simply asserting "everything is null", which would pass under any
        build at all.
        """
        wire(monkeypatch, probe_401, token=None)

        result = await server.uplers_session_info()

        assert result["authenticated"] is False
        assert result["credential"]["present"] is False
        assert result["credential"]["format"] == "absent"


# --- verify_live=False costs nothing --------------------------------------


class TestTheOfflineModeIsFree:

    async def test_verify_live_false_constructs_no_client_at_all(
            self, session_file):
        """The autouse `offline` fixture makes any client construction raise.

        Asserting the shape of the offline result would pass even if the tool
        spent a request first, so the instrument is the constructor, not the
        payload.
        """
        SessionStore(session_file).save(SANCTUM, method="test")

        result = await server.uplers_session_info(verify_live=False)

        assert result["authenticated"] is None
        assert result["live_check"]["attempted"] is False
        assert result["live_check"]["completed"] is False
        assert "offline answer" in result["live_check"]["why_not"]

    async def test_the_offline_result_still_carries_every_store_fact(
            self, session_file):
        """Free does not mean empty. The credential block is the whole point."""
        SessionStore(session_file).save(JWT_SIX_MONTHS, method="test")

        result = await server.uplers_session_info(verify_live=False)

        credential = result["credential"]
        assert credential["present"] is True
        assert credential["format"] == "jwt"
        assert credential["expires_at"]
        assert credential["expires_in_days"] > 170
        assert result["durability"]["survives_machine_reboot"] is True
        assert result["renewal"]["silent_renew_available"] is False

    async def test_attempted_distinguishes_asked_not_to_from_could_not(
            self, session_file):
        """Two different facts, one null, and they do not share a field."""
        store = SessionStore(session_file)

        asked_not_to = await server.uplers_session_info(verify_live=False)
        could_not = session_mod.session_info_offline(
            store, why_no_live_check="the browser is dead", attempted=True
        )

        assert asked_not_to["live_check"]["attempted"] is False
        assert could_not["live_check"]["attempted"] is True
        assert asked_not_to["authenticated"] is could_not["authenticated"] is None


# --- the expiry is a ceiling, not a runway --------------------------------


class TestTheExpiryIsNeverAuthoritative:

    async def test_a_six_month_jwt_reports_the_date_and_refuses_to_endorse_it(
            self, session_file):
        """The named difference this platform demands, asserted in full.

        A `false` flag with no explanation beside it is the same defect
        wearing a flag, so the prose is asserted too: it must say the date is
        a ceiling, and it must say only the live check settles it.
        """
        SessionStore(session_file).save(JWT_SIX_MONTHS, method="test")

        credential = (await server.uplers_session_info(verify_live=False))["credential"]

        assert credential["expiry_is_authoritative"] is False
        assert credential["expired"] is False
        source = credential["expiry_source"]
        assert "CEILING" in source
        assert "SHORT-LIVED" in source
        assert "roughly daily" in source
        assert "live check settles" in source

    async def test_the_flag_is_false_on_every_token_shape_there_is(
            self, session_file):
        """No branch may quietly promote the claimed date to a promise."""
        store = SessionStore(session_file)

        seen = []
        for token in (JWT_SIX_MONTHS, JWT_PAST, JWT_NO_EXP, SANCTUM, OPAQUE):
            store.save(token, method="test")
            credential = session_mod.credential_report(store)
            seen.append(credential["format"])
            assert credential["expiry_is_authoritative"] is False, credential["format"]
            assert credential["expiry_source"], credential["format"]

        # The loop is only worth anything if it really walked four shapes.
        assert seen == ["jwt", "jwt", "jwt", "sanctum", "opaque"]

    async def test_a_past_exp_is_expired_true(self, session_file):
        """`expired` must still be capable of true, or null is not a finding."""
        SessionStore(session_file).save(JWT_PAST, method="test")

        credential = (await server.uplers_session_info(verify_live=False))["credential"]

        assert credential["expired"] is True
        assert credential["expires_in_days"] < 0

    async def test_the_date_is_the_contract_z_spelling(self, session_file):
        SessionStore(session_file).save(JWT_SIX_MONTHS, method="test")

        credential = (await server.uplers_session_info(verify_live=False))["credential"]

        assert credential["expires_at"].endswith("Z")
        assert "+00:00" not in credential["expires_at"]
        assert len(credential["expires_at"]) == len("2027-02-17T12:00:00Z")


class TestAnUnknowableExpiryIsNullAndNotFalse:

    @pytest.mark.parametrize("token,shape", [(SANCTUM, "sanctum"), (OPAQUE, "opaque")])
    async def test_an_opaque_token_has_expired_null(
            self, session_file, token, shape):
        """The distinction the whole contract turns on.

        `false` here would read as "not expired", which is a claim nothing on
        this machine can support: the expiry lives on Uplers' servers and is
        never sent to this client.
        """
        SessionStore(session_file).save(token, method="test")

        credential = (await server.uplers_session_info(verify_live=False))["credential"]

        assert credential["format"] == shape
        assert credential["expired"] is None
        assert credential["expires_at"] is None
        assert credential["expires_in_days"] is None
        assert shape in credential["expiry_source"]
        assert "null rather than false" in credential["expiry_source"]

    async def test_a_jwt_with_no_exp_claim_is_also_null(self, session_file):
        """The fourth case. A JWT is not a promise that an `exp` is in it."""
        SessionStore(session_file).save(JWT_NO_EXP, method="test")

        credential = session_mod.credential_report(SessionStore(session_file))

        assert credential["format"] == "jwt"
        assert credential["expired"] is None
        assert "no readable `exp` claim" in credential["expiry_source"]

    async def test_no_token_at_all_is_null_not_true(self, session_file):
        """Nothing expired. There is simply nothing."""
        credential = session_mod.credential_report(SessionStore(session_file))

        assert credential["present"] is False
        assert credential["format"] == "absent"
        assert credential["expired"] is None


# --- renewal is impossible here, and says why ------------------------------


class TestRenewalIsRuledOutWithEvidence:

    async def test_silent_renew_is_false_with_a_real_reason_behind_it(
            self, session_file):
        """A bare false invites somebody to ship the decoy reauth next quarter.

        The reason is asserted by its load-bearing clauses, not by length: the
        layers are backwards, the profile cookies are session-only, and the
        route sweep found nothing.
        """
        renewal = (await server.uplers_session_info(verify_live=False))["renewal"]

        assert renewal["silent_renew_available"] is False
        assert renewal["tool"] is None
        why = renewal["why"]
        assert len(why) > 200
        assert "BEARER TOKEN is the" in why
        assert "session-only" in why
        assert "214-route sweep" in why
        assert "uplers_login()" in why

    async def test_uses_browser_is_null_not_false_and_mechanism_says_by_hand(
            self, session_file):
        """`is None`, deliberately - a `False` passes a falsy check.

        That is not pedantry, it is the exact confusion the field exists to
        stop. The two servers that DO ship a reauth both drive a browser and
        neither said so, which let "silent renew" read as "free". Here there
        is no mechanism at all, so `false` would assert that a silent renew
        exists and merely happens not to use a browser - a claim about a thing
        that does not exist. Same three-valued discipline as `authenticated`.

        `assert not renewal["uses_browser"]` would pass on False, on 0 and on
        "", which is why the assertion below is identity against None and why
        the second half checks a False is not what arrived.
        """
        renewal = (await server.uplers_session_info(verify_live=False))["renewal"]

        assert renewal["uses_browser"] is None
        assert renewal["uses_browser"] is not False

        mechanism = renewal["mechanism"]
        assert mechanism
        # A straight answer, not a pointer at renewal.why - a caller reading
        # `mechanism` across four servers should not have to chase a
        # cross-reference on this one.
        assert "BY HAND" in mechanism
        assert "uplers_login()" in mechanism
        assert "never handles a password" in mechanism
        assert "null rather than false" in mechanism

    async def test_the_mechanism_is_the_same_on_the_live_path(
            self, monkeypatch, session_file):
        """Both paths build `renewal` from one function; this pins that."""
        SessionStore(session_file).save(JWT_SIX_MONTHS, method="test")
        wire(monkeypatch, probe_ok, token=JWT_SIX_MONTHS)

        live = await server.uplers_session_info()
        offline = await server.uplers_session_info(verify_live=False)

        assert live["renewal"]["uses_browser"] is None
        assert live["renewal"]["mechanism"] == offline["renewal"]["mechanism"]

    async def test_session_lapses_at_tracks_the_credential_exactly(
            self, session_file):
        """`session_lapses_at` answers a different question and here matches.

        The two are NOT the same field in general - on the sibling naukri
        server `nauk_at` measures half an hour out while the session behind it
        runs 188 days, so a client comparing `credential.expires_at` across
        four servers would read naukri as nearly dead. Here they coincide, and
        the equality is by CONSTRUCTION rather than by luck: `_renewal` is
        handed the already-built credential block, so a rounding tick cannot
        put a tenth of a day between two fields defined to be equal.
        """
        SessionStore(session_file).save(JWT_SIX_MONTHS, method="test")

        result = await server.uplers_session_info(verify_live=False)
        renewal, credential = result["renewal"], result["credential"]

        assert renewal["session_lapses_at"] == credential["expires_at"]
        assert renewal["session_lapses_in_days"] == credential["expires_in_days"]
        assert renewal["session_lapses_at"].endswith("Z")
        assert renewal["session_lapses_in_days"] > 170

    async def test_the_lapse_source_names_the_no_renewal_reason_and_the_ceiling(
            self, session_file):
        """Why they coincide is the whole content of the field.

        And the ceiling warning is repeated HERE rather than left to
        `expiry_is_authoritative`, because this is the field most likely to be
        read as a deadline - a caller who plans against it as a runway is
        wrong in the expensive direction.
        """
        SessionStore(session_file).save(JWT_SIX_MONTHS, method="test")

        source = (
            await server.uplers_session_info(verify_live=False)
        )["renewal"]["session_lapses_source"]

        assert "no silent renew" in source
        assert "cannot outlive the credential" in source
        assert "LATEST the session" in source
        assert "roughly daily" in source

    @pytest.mark.parametrize("token,fragment", [
        (None, "no token is stored"),
        (SANCTUM, "a sanctum token keeps its expiry on Uplers' servers"),
        (OPAQUE, "a opaque token keeps its expiry on Uplers' servers"),
        (JWT_NO_EXP, "carries no readable `exp` claim"),
    ])
    async def test_an_unknowable_lapse_is_null_and_never_zero(
            self, session_file, token, fragment):
        """Null, with the missing fact NAMED. A 0.0 here would read as "today".

        Same rule as `expired`: the absence of a date is reported as an
        absence, not filled in with the falsiest number to hand.
        """
        if token:
            SessionStore(session_file).save(token, method="test")

        renewal = (await server.uplers_session_info(verify_live=False))["renewal"]

        assert renewal["session_lapses_at"] is None
        assert renewal["session_lapses_in_days"] is None
        assert fragment in renewal["session_lapses_source"]
        assert "null rather than guessed" in renewal["session_lapses_source"]
        assert "no silent renew" in renewal["session_lapses_source"]

    async def test_the_lapse_keys_are_present_on_the_live_path_too(
            self, monkeypatch, session_file):
        """Both paths build `renewal` the same way; this pins that they do."""
        SessionStore(session_file).save(JWT_SIX_MONTHS, method="test")
        wire(monkeypatch, probe_ok, token=JWT_SIX_MONTHS)

        result = await server.uplers_session_info()

        assert result["authenticated"] is True
        assert set(result["renewal"]) == {
            "silent_renew_available", "uses_browser", "tool", "mechanism",
            "why", "session_lapses_at", "session_lapses_in_days",
            "session_lapses_source",
            # Added 2026-08-25. `tool` is null because there is no REAUTH, and
            # a null there left a machine reader with no next step - "there is
            # no silent renew" and "there is nothing you can do" are different
            # facts. Recovery is now a field, not only prose in `mechanism`,
            # because a client that renders fields shows one and not the other.
            "recover_with", "recovery_is_a_human_action",
        }
        assert result["renewal"]["session_lapses_at"] == result["credential"]["expires_at"]
        # Recovery names a REAL tool and is not the reauth slot wearing a
        # different name. Both halves matter: a caller must be able to act on
        # it, and must not be able to loop on it as though it were silent.
        assert result["renewal"]["tool"] is None
        assert result["renewal"]["recover_with"] == "uplers_login"
        assert hasattr(server, "uplers_login")
        assert result["renewal"]["recovery_is_a_human_action"] is True

    async def test_the_server_ships_no_reauth_tool(self):
        """The rule, enforced where it can actually be broken.

        Ruled 2026-08-23 with evidence: a reauth on this platform would be
        uplers_login wearing a different name. This is the tripwire for
        somebody adding one anyway.
        """
        names = {tool.name for tool in await server.mcp.list_tools()}

        assert "uplers_reauth" not in names
        assert not hasattr(server, "uplers_reauth")

    async def test_on_expiry_names_the_recovery_tool(self, session_file):
        result = await server.uplers_session_info(verify_live=False)

        assert "uplers_login()" in result["on_expiry"]
        assert "empty list" in result["on_expiry"]


# --- durability, and the path that must not publish the box ----------------


class TestDurability:

    async def test_the_store_outlives_the_process_and_says_why(
            self, session_file):
        durability = (await server.uplers_session_info(verify_live=False))["durability"]

        assert durability["survives_server_restart"] is True
        assert durability["survives_machine_reboot"] is True
        assert "FILE on disk" in durability["why"]
        assert "not state held in this process" in durability["why"]

    async def test_stored_in_is_relativised_and_is_still_an_answer(
            self, session_file, tmp_path):
        """Relativise, do not delete - the ruling in tests/test_path_hygiene.py.

        Two assertions, because either alone permits a wrong fix: the first
        says the layout is gone, the second says the field still names a file.
        """
        stored_in = (
            await server.uplers_session_info(verify_live=False)
        )["durability"]["stored_in"]

        assert str(tmp_path) not in stored_in
        assert "session.json" in stored_in

    async def test_supporting_is_empty_and_the_prose_says_so(self, session_file):
        """An empty list must be a measured absence, not a field nobody filled."""
        result = await server.uplers_session_info(verify_live=False)

        assert result["supporting"] == []
        assert "csrf" in result["credential_source"]
        assert "measured absence" in result["credential_source"]


# --- the credential value never leaves ------------------------------------


class TestTheTokenNeverAppearsAnywhere:

    async def test_no_payload_this_tool_can_produce_carries_the_token(
            self, monkeypatch, session_file):
        """One sweep over every string in every branch, including the errors.

        Not a prefix and not a length either: `describe()` deliberately reports
        neither, and a length is a small leak that buys nothing a boolean does
        not.
        """
        store = SessionStore(session_file)
        payloads = {}

        for token in (SANCTUM, OPAQUE, JWT_SIX_MONTHS, JWT_PAST, JWT_NO_EXP):
            store.save(token, method="test")
            payloads["offline:%s" % token[:0]] = await server.uplers_session_info(
                verify_live=False
            )
            for label, handler in (
                ("ok", probe_ok),
                ("401", probe_401),
                ("guest", probe_guest),
                ("500", probe_500),
            ):
                wire(monkeypatch, handler, token=token)
                payloads["%s:%s" % (label, len(payloads))] = (
                    await server.uplers_session_info()
                )

        store.save(SANCTUM, method="test")
        payloads["logout"] = await server.uplers_logout()

        leaks = [
            "%s %s disclosed %r via %r" % (name, trail, secret[:8] + "...", piece)
            for name, payload in payloads.items()
            for trail, secret, piece in leaks_of(payload, FRAGMENTS)
        ]
        assert leaks == [], leaks
        # And the sweep must have had something to sweep.
        assert len(payloads) >= 20

    def test_the_leak_sweep_can_actually_fail(self, session_file):
        """__CONTROL for the sweep above. An instrument never shown failing
        certifies nothing, and this file's whole claim rests on that one.

        This is the PLAINTEXT arm, and on its own it is the arm that lulled
        the sibling naukri server: a Sanctum token wears its secret half in
        the clear, so any detector at all catches it. The four controls after
        this one are the arms that plaintext proves nothing about.
        """
        planted = {"credential": {"expiry_source": "token was " + SANCTUM}}

        assert sorted({t for t, _, _ in leaks_of(planted, FRAGMENTS)}) == [
            "$.credential.expiry_source"
        ]

    def test_the_sweep_fires_on_a_whole_jwt(self, session_file):
        """__CONTROL. The credential this server really holds is a JWT, and
        the suite's own canaries are Sanctum-shaped. Without this, the JWT arm
        of every leak assertion in the file is certified by nothing."""
        planted = {"credential": {"raw": JWT_SIX_MONTHS}}

        assert sorted({t for t, _, _ in leaks_of(planted, FRAGMENTS)}) == [
            "$.credential.raw"
        ]

    def test_the_sweep_fires_on_one_base64url_segment(self, session_file):
        """__CONTROL, and the first of the two shapes MEASURED BLIND on
        2026-08-23 under the rule this replaced.

        A JWT's claims segment is not a superstring of the JWT, so
        `secret in text` cannot see it - yet that segment decodes to the whole
        identity half of the credential. A payload echoing only this would
        have passed every "the token never leaks" test in this repo.
        """
        claims_segment = JWT_SIX_MONTHS.split(".")[1]
        planted = {"credential": {"claims_b64": claims_segment}}

        assert sorted({t for t, _, _ in leaks_of(planted, FRAGMENTS)}) == [
            "$.credential.claims_b64"
        ]
        assert JWT_SIX_MONTHS not in claims_segment    # the old rule's blindness

    def test_the_sweep_fires_on_decoded_claims(self, session_file):
        """__CONTROL, and the second measured-blind shape. This one is not
        hypothetical: `session.token_expiry` ALREADY decodes that segment, so
        the decoded form is one careless `return` away in production code.

        The decoded claims share no substring with the encoded token, which is
        exactly the naukri failure transposed - there, a walker hunted a
        plaintext marker that never appears inside a base64url JWT.
        """
        payload = json.loads(
            base64.urlsafe_b64decode(JWT_SIX_MONTHS.split(".")[1] + "==")
        )
        planted = {"credential": {"claims": payload}}

        assert sorted({t for t, _, _ in leaks_of(planted, FRAGMENTS)}) == [
            "$.credential.claims.sub"
        ]
        assert payload["sub"] not in JWT_SIX_MONTHS    # no substring relation at all

    def test_the_sweep_does_not_fire_on_a_generic_jwt_header(self, session_file):
        """__CONTROL for the OTHER failure direction, which the replaced rule
        had: it hunted `secret[:12]`, and for a JWT that is "eyJhbGciOiJI" -
        the base64 of a standard HS256 header, MEASURED IDENTICAL across all
        three JWTs here. It matched a constant, not a credential: zero signal
        on the shape that matters, and a false report on prose describing one.

        A detector that fires on documentation gets disabled by whoever is
        next debugging at 2am, which is how the real one stops running.
        """
        prose = {"note": "Uplers tokens look like eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<claims>.<sig>"}

        assert leaks_of(prose, FRAGMENTS) == []
        assert JWT_SIX_MONTHS[:12] == JWT_PAST[:12] == "eyJhbGciOiJI"

    def test_the_format_decoy_removes_only_format_and_not_credential(self):
        """__CONTROL for the subtraction itself, which is the one step that
        could silently empty the detector.

        If `format_decoys` were ever handed a real credential - or if two
        credentials came to share their signature, as they did before
        `make_jwt` grew a per-token tag - the fragment set would shrink to
        nothing and every leak test in this file would pass vacuously.
        """
        # Asserted BEHAVIOURALLY rather than by inspecting the set, because
        # the set holds 12-character runs now and "is the whole value in it"
        # stopped being the right question the moment runs arrived. What has
        # to stay true is that hunting runs SUBSUMES hunting the whole value.
        for secret in SECRETS:
            assert leaks_of({"planted": secret}, FRAGMENTS), secret[:12]
            assert FRAGMENTS[secret], "empty fragment set = a vacuous pass"
            assert all(len(run) == 12 for run in FRAGMENTS[secret])

        jwt_runs = FRAGMENTS[JWT_SIX_MONTHS]

        def survives(text):
            """SOME window of `text` is still hunted."""
            return any(text[i:i + 12] in jwt_runs for i in range(len(text) - 11))

        # Asserted as "some window survives", never as "this exact window",
        # and the difference is a real finding rather than a convenience.
        # `claims_segment[:12]` is "eyJzdWIiOiJ0", which decodes to `{"sub":"t`
        # - shared with the decoy and correctly subtracted. A witness chosen
        # by position rather than by uniqueness tests the decoy, not the rule.
        assert survives(JWT_SIX_MONTHS.split(".")[1])           # claims kept
        assert "talent-six-m" in jwt_runs                       # decoded sub kept
        assert "signature-si" in jwt_runs

        # The shared header is gone RUN BY RUN, not merely as a whole string.
        header = JWT_SIX_MONTHS.split(".")[0]
        header_runs = {header[i:i + 12] for i in range(len(header) - 11)}
        assert header_runs & jwt_runs == set(), sorted(header_runs & jwt_runs)

        # The encoded spellings are hunted too - the leak path can encode even
        # when the credential does not. Their shared PREFIXES are subtracted
        # for the same reason the header is, so again: some window, not the
        # first one.
        raw = JWT_SIX_MONTHS.encode()
        assert survives(base64.b64encode(raw).decode())
        assert survives(base64.urlsafe_b64encode(raw).decode().rstrip("="))
        assert survives(raw.hex())

        # And the decoy really is a different credential, never a stored one.
        assert FORMAT_DECOY not in SECRETS

    async def test_no_token_reaches_a_log_line(
            self, monkeypatch, session_file, caplog):
        """The error paths log; the token must not ride along."""
        SessionStore(session_file).save(SANCTUM, method="test")
        wire(monkeypatch, probe_500)

        with caplog.at_level(0):
            await server.uplers_session_info()
            await server.uplers_logout()

        assert leaks_of({"log": caplog.text}, FRAGMENTS) == []


# --- logout ----------------------------------------------------------------


class TestLogout:

    async def test_it_clears_the_token_and_reports_the_contract_shape(
            self, session_file):
        store = SessionStore(session_file)
        store.save(SANCTUM, method="test")
        assert session_file.is_file()

        result = await server.uplers_logout()

        assert result["cleared"] is True
        assert result["authenticated"] is False
        assert not session_file.exists()
        assert store.token() is None
        assert set(result) == {
            "cleared", "scope", "authenticated", "reason",
            "what_is_lost", "recover_by",
        }

    async def test_the_false_is_justified_rather_than_asserted(
            self, session_file):
        """The one false in this server with no live check behind it.

        It is legitimate only because no request CAN be made without a
        credential, and the tool has to say that - otherwise it is
        indistinguishable from the presence-based false this contract bans.
        """
        SessionStore(session_file).save(SANCTUM, method="test")

        result = await server.uplers_logout()

        assert "no credential left to send" in result["reason"]
        assert "provable rather than measured" in result["reason"]

    async def test_scope_says_what_survived_it(self, session_file):
        SessionStore(session_file).save(SANCTUM, method="test")

        result = await server.uplers_logout()

        assert "browser profile is untouched" in result["scope"]
        assert "NOTHING was signed out on Uplers' side" in result["scope"]
        assert "session.json" in result["scope"]

    async def test_what_is_lost_and_recover_by_name_real_things(
            self, session_file):
        SessionStore(session_file).save(SANCTUM, method="test")

        result = await server.uplers_logout()

        assert "uplers_my_pipeline" in result["what_is_lost"]
        assert "Nothing local is deleted" in result["what_is_lost"]
        assert result["recover_by"].startswith("uplers_login()")

    async def test_a_second_logout_is_a_different_sentence_not_an_error(
            self, session_file):
        SessionStore(session_file).save(SANCTUM, method="test")
        await server.uplers_logout()

        second = await server.uplers_logout()

        assert second["cleared"] is False
        assert second["authenticated"] is False
        assert "no stored token to delete" in second["reason"]
        assert second["what_is_lost"] == "nothing. There was no token stored."

    async def test_it_never_raises_even_when_the_unlink_fails(
            self, monkeypatch, session_file):
        """A logout is the one operation that must work when things are broken.

        And a removal that did not happen must not report a signed-out state
        it never reached: `authenticated` goes null under a NAMED flag rather
        than claiming the contract's fixed false on a token still sitting on
        disk.
        """
        SessionStore(session_file).save(SANCTUM, method="test")

        def wont_delete(self, missing_ok=False):
            raise OSError(13, "the file is locked by another process")

        monkeypatch.setattr("pathlib.Path.unlink", wont_delete)

        result = await server.uplers_logout()

        assert result["removal_failed"] is True
        assert result["cleared"] is False
        assert result["authenticated"] is None
        assert "STILL ON DISK" in result["reason"]
        assert session_file.is_file()

    async def test_logout_touches_nothing_but_the_session_file(
            self, session_file, tmp_path):
        """The browser profile is not this tool's business and stays that way."""
        profile = tmp_path / "browser_profile"
        profile.mkdir()
        (profile / "Cookies").write_text("pretend jar", encoding="utf-8")
        SessionStore(session_file).save(SANCTUM, method="test")

        await server.uplers_logout()

        assert (profile / "Cookies").read_text(encoding="utf-8") == "pretend jar"


# --- the transform grid, as controls rather than as a script ---------------
#
# `scripts/leak_matrix.py` runs the full 8-test x 9-transform grid and is the
# instrument of record; it takes a couple of minutes and is not something the
# suite should run on every commit. These parametrised controls are the part
# that MUST run every time: they are generated from the adversary's own
# TRANSFORMS tuple, so a transform added there without a decision about it
# fails here immediately rather than sitting unexamined.
#
# MEASURED PROGRESSION, all on 2026-08-23 (see _audit/2026-08-23-build-uplers.md):
#   52/72 green -> hook corrected (four columns were never injected at all)
#   42/72 green -> encoded spellings + 12-char runs + JWT shape added
#   27/72 green -> the last two hand-rolled substring assertions routed
#                  through the detector
#   18/72 green -> every remaining green explained below and correct

#: The only (transform, shape) pairs a PAYLOAD detector cannot fire on, each
#: with its reason. This is an exemption list, not a skip list: every entry is
#: a claim that firing would be WRONG, and each one is asserted below.
EXEMPT = {
    ("in_log", "sanctum"):
        "not a payload rendering at all - the credential goes to a log record "
        "and nowhere else. Caught by test_no_token_reaches_a_log_line, which "
        "is the one assertion in this file that reads caplog.",
    ("in_log", "jwt"):
        "same: the log is the leak path, so the log test is the instrument.",
    ("prefix12", "jwt"):
        "the first twelve characters of a JWT are 'eyJhbGciOiJI' - the base64 "
        "of a standard HS256 header, identical across every token of this "
        "format. Firing here would be the exact false positive removed "
        "earlier today, and it would report prose describing a JWT. The "
        "SANCTUM half of this pair IS caught, because '42|bearer-to' does "
        "identify a credential.",
}


@pytest.mark.parametrize("transform", TRANSFORMS)
@pytest.mark.parametrize("shape", ("sanctum", "jwt"))
def test_the_detector_sees_every_transform__CONTROL(transform, shape):
    """__CONTROL, one cell per (transform, credential shape).

    Generated from `credential_echo_control.TRANSFORMS` rather than from a
    hand-kept list beside it. That is the whole design: the failure mode being
    fixed is not "nine transforms were missed", it is "the enumeration and the
    controls were maintained separately and drifted".
    """
    secret = SANCTUM if shape == "sanctum" else JWT_SIX_MONTHS
    reason = EXEMPT.get((transform, shape))

    if transform == "in_log":
        # The defining property of this transform is that the credential is
        # NOT in the result. Planting it there anyway would test nothing and
        # would make the exemption below look false - which is exactly what
        # the first version of this test did.
        planted = {"credential": {}}
        assert not leaks_of(planted, FRAGMENTS)
        # ...and the SAME detector, pointed at the log text, does see it.
        # That is what test_no_token_reaches_a_log_line does, and it is why
        # this cell being green on the payload tests is coverage rather than
        # a hole.
        assert leaks_of({"log": "bearer token is %s" % secret}, FRAGMENTS)
    else:
        planted = {"credential": {"fingerprint": render(secret, transform)}}

    fired = bool(leaks_of(planted, FRAGMENTS))

    if reason:
        assert not fired, (
            "%s/%s is on the exemption list saying it CANNOT fire, and it "
            "did. Either the detector improved and the exemption is stale, "
            "or the reason was wrong: %s" % (transform, shape, reason)
        )
    else:
        assert fired, (
            "a build echoing the credential under %r (%s) shipped clean. "
            "Add it to EXEMPT with a reason, or teach the detector to see it."
            % (transform, shape)
        )


def test_the_exemption_list_names_only_real_transforms__CONTROL():
    """__CONTROL for the exemption list itself, which is the one place a
    genuine hole could be parked and forgotten.

    A stale entry naming a transform that no longer exists would sit here
    looking like due diligence forever.
    """
    for transform, shape in EXEMPT:
        assert transform in TRANSFORMS, transform
        assert shape in ("sanctum", "jwt"), shape
    # And it must stay small. Three is the measured number; a fourth is a
    # decision somebody has to defend, not a line to slip in.
    assert len(EXEMPT) == 3, sorted(EXEMPT)
