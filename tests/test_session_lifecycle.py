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

from conftest import make_transport

#: A Sanctum-shaped token: `<id>|<plaintext>`. No expiry is knowable from it.
SANCTUM = "42|bearer-token-that-must-never-be-printed"

#: A bare string that is neither a JWT nor Sanctum-shaped.
OPAQUE = "opaque-secret-that-must-never-be-printed"


def make_jwt(exp: float | None) -> str:
    """A structurally real JWT. The signature is not checked by anything here.

    Built rather than captured because a captured one would be the operator's
    actual credential, and a fixture file is the wrong place for that.
    """

    def seg(payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    claims: dict = {"sub": "talent-must-never-be-printed"}
    if exp is not None:
        claims["exp"] = exp
    return "%s.%s.%s" % (
        seg({"alg": "HS256", "typ": "JWT"}),
        seg(claims),
        "signature-that-must-never-be-printed",
    )


#: Six months out, which is the real token's shape and the whole reason
#: `expiry_is_authoritative` exists.
JWT_SIX_MONTHS = make_jwt(time.time() + 180 * 86400)
JWT_PAST = make_jwt(time.time() - 3 * 86400)
JWT_NO_EXP = make_jwt(None)

#: Every secret string above, so the leak sweep has one list to walk.
SECRETS = (SANCTUM, OPAQUE, JWT_SIX_MONTHS, JWT_PAST, JWT_NO_EXP)


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
            "%s %s = %r" % (name, trail, text)
            for name, payload in payloads.items()
            for trail, text in strings(payload)
            for secret in SECRETS
            if secret in text or (len(secret) > 12 and secret[:12] in text)
        ]
        assert leaks == [], leaks
        # And the sweep must have had something to sweep.
        assert len(payloads) >= 20

    async def test_the_leak_sweep_can_actually_fail(self, session_file):
        """__CONTROL for the sweep above. An instrument never shown failing
        certifies nothing, and this file's whole claim rests on that one."""
        planted = {"credential": {"expiry_source": "token was " + SANCTUM}}

        leaks = [
            trail
            for trail, text in strings(planted)
            for secret in SECRETS
            if secret in text
        ]

        assert leaks == [".credential.expiry_source"]

    async def test_no_token_reaches_a_log_line(
            self, monkeypatch, session_file, caplog):
        """The error paths log; the token must not ride along."""
        SessionStore(session_file).save(SANCTUM, method="test")
        wire(monkeypatch, probe_500)

        with caplog.at_level(0):
            await server.uplers_session_info()
            await server.uplers_logout()

        assert SANCTUM not in caplog.text
        assert SANCTUM[:12] not in caplog.text


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
