"""session.py - token storage, token introspection, and the auth measurement.

Three claims are defended here, in ascending order of what they cost to get
wrong.

The cheapest is storage: a token saved is a token read back, and a session file
that got truncated by a killed process is a re-login rather than a crash.

The middle one is disclosure. `describe()` is what tools print, so it is the
one place a bearer token could escape into a transcript. The test below asserts
the token does not appear in it - not a prefix of it, not its length, not the
shape of it. A leak here is not recoverable by fixing the code afterwards,
because the value is already in somebody's scrollback.

The expensive one is `check_auth`, and it is expensive because the sibling
Instahyre server already paid for it: that server called a session real as soon
as a cookie existed, Django hands those to anonymous visitors, and it reported
`authenticated: true` while every subsequent call 401'd. Uplers wears the same
trap in different clothes - the SPA falls back to an anonymous `guest_token`,
so a 200 from the probe route is NOT proof of a session. The tests here pin
both directions of that: a bare 200 must not become True, and a 500 must not
become False.

No SessionStore in this file is built on the default path; every one of them
lives under tmp_path, so the operator's real data/session.json is never read,
written, or unlinked by the suite. Every HTTP interaction goes through
httpx.MockTransport.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from uplers_server import endpoints, session as sess
from uplers_server.session import SessionStore, check_auth, token_expiry, token_format
from uplers_server.talent import TalentClient

from conftest import leaks_of, make_transport, secret_fragments

TOKEN = "77|leakcanary-do-not-print-this-value"


def make_store(tmp_path):
    """A store on a temp path. Never the real data dir."""
    return SessionStore(tmp_path / "session.json")


def _segment(obj) -> str:
    raw = json.dumps(obj).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def make_jwt(**claims) -> str:
    """A real three-segment JWT, built rather than pasted.

    Built because a hardcoded blob would still pass if _b64url_decode's
    padding arithmetic were wrong - the segment lengths in a pasted token are
    whatever they happened to be. Generating the claims here means the padding
    case actually varies with the test data.
    """
    header = _segment({"alg": "HS256", "typ": "JWT"})
    return header + "." + _segment(claims) + ".signature-is-never-verified-here"


#: TOKEN, and the spellings a leaking build would give it. The decoy is a
#: Sanctum token of the same shape that is never stored, so anything the two
#: share is a property of the format rather than of this credential.
SANCTUM_FRAGMENTS = secret_fragments(
    (TOKEN,), format_decoys=("99|decoy-value-never-stored-anywhere-at-all",)
)


def make_probe_client(handler, token=TOKEN):
    """A TalentClient over MockTransport, for driving check_auth."""
    transport, calls = make_transport(handler)
    return (TalentClient(lambda: token, delay=0, transport=transport), calls)


# --- storage --------------------------------------------------------------


def test_a_saved_token_reads_back(tmp_path):
    store = make_store(tmp_path)
    store.save(TOKEN, method="browser")

    assert store.token() == TOKEN
    assert SessionStore(store.path).token() == TOKEN  # survives a fresh reader


def test_save_lands_whole_and_clear_removes_it(tmp_path):
    """The write goes to a temp file and is renamed over the target.

    A half-written session.json is the worst outcome available here: it reads
    as a corrupt file, so the operator is told to sign in again, and signing
    in writes the same file that just failed.
    """
    store = make_store(tmp_path)
    store.save(TOKEN, method="browser")

    on_disk = json.loads(store.path.read_text(encoding="utf-8"))
    assert on_disk["token"] == TOKEN
    assert list(tmp_path.glob("*.tmp")) == []  # nothing left half-written

    assert store.clear() is True
    assert store.path.exists() is False
    assert store.token() is None
    assert store.clear() is False  # clearing nothing is not an error


def test_saving_an_empty_token_is_refused(tmp_path):
    """An empty token would persist as "logged in with nothing" and turn every
    later 401 into a puzzle about which half of the flow failed."""
    store = make_store(tmp_path)
    with pytest.raises(ValueError):
        store.save("", method="browser")

    assert store.path.exists() is False


def test_a_corrupt_session_file_is_a_relogin_not_a_crash(tmp_path):
    """Killed mid-write, hand-edited, or truncated by a full disk.

    Whatever the cause, the recovery is the same as having no session at all,
    and raising out of read() would instead take down every tool that opens
    the store on the way to doing something unrelated.
    """
    store = make_store(tmp_path)
    store.path.write_text('{"token": "abc", "sav', encoding="utf-8")

    assert store.read() == {}
    assert store.token() is None
    assert store.describe()["token_present"] is False

    # Valid JSON of the wrong type is the same story.
    store.path.write_text("[1, 2, 3]", encoding="utf-8")
    assert store.read() == {}
    assert store.token() is None

    # So is a present-but-unusable token field.
    store.path.write_text('{"token": null}', encoding="utf-8")
    assert store.token() is None
    store.path.write_text('{"token": ""}', encoding="utf-8")
    assert store.token() is None


# --- disclosure -----------------------------------------------------------


def test_describe_never_leaks_the_token(tmp_path):
    """describe() is what tools print. Nothing about the secret may be in it.

    Not the value, not a prefix, not the length. A prefix is enough to
    fingerprint a token across logs, and a length narrows an attack; neither
    buys a caller anything a boolean does not already give. The key set is
    asserted exactly so that a future field cannot slip a preview in without
    this test objecting.
    """
    store = make_store(tmp_path)
    described = store.save(TOKEN, method="browser")  # save returns describe()

    blob = json.dumps(described)
    assert TOKEN not in blob
    for size in range(4, len(TOKEN) + 1):
        assert TOKEN[:size] not in blob, "a %d-char prefix of the token leaked" % size

    assert set(described) == {
        "token_present", "token_format", "saved_at", "method", "expires_at",
    }
    assert not any("len" in key.lower() for key in described)
    assert len(TOKEN) not in [value for value in described.values() if isinstance(value, int)]

    assert described["token_present"] is True
    assert described["token_format"] == "sanctum"
    assert described["method"] == "browser"

    # And the same again through describe() itself, not just save()'s return.
    assert TOKEN not in json.dumps(store.describe())


#: The credential this server really holds is a JWT, and TOKEN above is
#: Sanctum-shaped - a format that wears its secret half in the clear, so any
#: detector at all catches it. The two tests below run the SAME disclosure
#: claims against the JWT arm, through the fragment detector in conftest.
#: Without them, "the token never leaks" was proven only for the shape this
#: server does not use. See tests/conftest.py for the two blind spots that
#: were MEASURED on 2026-08-23.
JWT_TOKEN = make_jwt(sub="talent-identity-must-never-be-printed", exp=2000000000)
JWT_DECOY = make_jwt(sub="decoy-subject-never-stored-anywhere", exp=1)
JWT_FRAGMENTS = secret_fragments((JWT_TOKEN,), format_decoys=(JWT_DECOY,))


def test_describe_never_leaks_a_jwt(tmp_path):
    """The JWT arm of test_describe_never_leaks_the_token.

    A JWT defeats a plain substring hunt twice over: one base64url segment is
    not a superstring of the token, and the decoded claims share no substring
    with it at all. Both are checked here, and the second is not hypothetical -
    `token_expiry` already decodes that segment.
    """
    store = make_store(tmp_path)
    described = store.save(JWT_TOKEN, method="browser")

    assert described["token_format"] == "jwt"
    assert leaks_of(described, JWT_FRAGMENTS) == []
    assert leaks_of(store.describe(), JWT_FRAGMENTS) == []

    # An expiry IS disclosed, deliberately, and it is not a leak: it is a
    # timestamp derived from the claims, not any string out of the credential.
    assert described["expires_at"] is not None


def test_the_jwt_detector_can_actually_fail(tmp_path):
    """__CONTROL for the two tests above. Three plantings, three fires: the
    whole token, one base64url segment of it, and the decoded subject."""
    whole = {"credential": JWT_TOKEN}
    segment = {"credential": JWT_TOKEN.split(".")[1]}
    decoded = {"credential": json.loads(_b64url(JWT_TOKEN.split(".")[1]))}

    assert leaks_of(whole, JWT_FRAGMENTS)
    assert leaks_of(segment, JWT_FRAGMENTS)
    assert leaks_of(decoded, JWT_FRAGMENTS)

    # And the two shapes a substring hunt cannot see really have no substring
    # relation to the token - which is why the control is worth writing.
    assert JWT_TOKEN not in segment["credential"]
    assert decoded["credential"]["sub"] not in JWT_TOKEN


def _b64url(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def test_describe_on_a_missing_file_reports_absence(tmp_path):
    """Asked before the first login, which is when a tool is most likely to
    ask. Absence is an answer, not an exception."""
    described = make_store(tmp_path).describe()

    assert described["token_present"] is False
    assert described["token_format"] == "absent"
    assert described["saved_at"] is None
    assert described["expires_at"] is None
    assert "expired" not in described  # unknown expiry is not a false "fresh"


# --- token introspection --------------------------------------------------


def test_token_format_names_only_what_it_can_prove():
    """Three real shapes and a fourth for nothing at all.

    "jwt" is claimed only when the middle segment actually decodes and parses,
    because the classification's only job is deciding whether an expiry is
    knowable - and guessing there produces an expiry from a token that has none.
    """
    assert token_format(make_jwt(exp=1)) == "jwt"
    assert token_format("12|abcdef") == "sanctum"
    assert token_format("plain-opaque-string") == "opaque"
    assert token_format(None) == "absent"
    assert token_format("") == "absent"


def test_a_three_segment_string_that_is_not_a_jwt_is_only_opaque():
    """Dots are not proof. An undecodable or non-JSON middle segment demotes
    the token to opaque rather than letting a bogus expiry be read out of it."""
    assert token_format("aaa.!!!not-base64!!!.ccc") == "opaque"
    assert token_format("aaa." + base64.urlsafe_b64encode(b"not json").decode().rstrip("=") + ".ccc") == "opaque"


def test_token_expiry_reads_the_exp_claim_of_a_jwt():
    assert token_expiry(make_jwt(exp=1755000000, sub="talent-1")) == 1755000000.0


def test_token_expiry_is_none_whenever_it_is_not_knowable():
    """None means "ask the server", never "never expires".

    Sanctum tokens are opaque strings with a server-side expiry, so None is
    the common answer for a real Uplers session. Treating it as "no expiry"
    would let a stale token look fresh forever.
    """
    assert token_expiry("12|abcdef") is None
    assert token_expiry("plain-opaque-string") is None
    assert token_expiry(None) is None
    assert token_expiry("") is None
    assert token_expiry("aaa.!!!not-base64!!!.ccc") is None
    assert token_expiry("aaa." + base64.urlsafe_b64encode(b"not json").decode().rstrip("=") + ".ccc") is None
    assert token_expiry(make_jwt(sub="talent-1")) is None  # a JWT with no exp claim


def test_describe_flags_a_past_expiry_as_expired(tmp_path):
    store = make_store(tmp_path)
    described = store.save(make_jwt(exp=time.time() - 3600), method="browser")

    assert described["token_format"] == "jwt"
    assert described["expired"] is True
    assert described["expires_at"] is not None


def test_describe_reports_a_future_expiry_as_not_expired(tmp_path):
    store = make_store(tmp_path)
    described = store.save(make_jwt(exp=time.time() + 3600), method="browser")

    assert described["expired"] is False


# --- the measurement ------------------------------------------------------


PROFILE_PAYLOAD = {
    "talent_details": {"full_name": "Sundeep G", "email": "someone@example.com"},
    "profile_completion_percentage": 82,
}


async def test_check_auth_says_true_only_when_the_profile_comes_back():
    """The one path that may return True: HIS profile, returned by the server.

    Proof of identity without printing anything sensitive - a name and a
    completion percentage - so the operator can see WHICH account answered,
    not merely that something did.
    """
    client, calls = make_probe_client(lambda request: httpx.Response(200, json=PROFILE_PAYLOAD))
    async with client:
        result = await check_auth(client)

    assert result["authenticated"] is True
    assert result["signed_in_as"] == "Sundeep G"
    assert result["profile_completion_percentage"] == 82
    assert result["token_present"] is True
    assert result["checked_against"] == endpoints.AUTH_PROBE_NOTE
    assert calls[0].url.path.endswith(endpoints.EP_AUTH_PROBE)


async def test_a_200_without_talent_details_is_unknown_not_authenticated():
    """The anti-false-positive guard, and the reason this module exists.

    Uplers' SPA sends `Authorization: Bearer <token ?? guest_token>`, so an
    ANONYMOUS token can also collect a 200 from this route. "The request did
    not fail" is therefore not evidence of a session - it is precisely the
    too-weak condition that shipped a false `authenticated: true` on the
    sibling Instahyre server. Unknown is the honest answer: it prompts a
    login attempt without asserting a session nobody demonstrated.
    """
    payload = {"status": "success", "message": "ok", "guest": True}
    client, _ = make_probe_client(lambda request: httpx.Response(200, json=payload))
    async with client:
        result = await check_auth(client)

    assert result["authenticated"] is None
    assert result["authenticated"] is not True
    assert result["error"] == "unexpected_shape"
    assert "talent_details" in result["reason"]


async def test_an_empty_talent_details_object_is_not_a_session_either():
    """Present but empty is the same non-evidence as absent: there is no
    profile in it to identify an account with."""
    client, _ = make_probe_client(lambda request: httpx.Response(200, json={"talent_details": {}}))
    async with client:
        result = await check_auth(client)

    assert result["authenticated"] is None


async def test_a_401_with_a_stored_token_says_the_token_was_rejected():
    """The two 401 branches send the operator to different places, so they are
    worded differently: a rejected token is a re-login, no token is a first
    login, and telling him to "sign in again" when he never signed in reads
    like the tool lost something."""
    client, _ = make_probe_client(
        lambda request: httpx.Response(401, json={"message": "Unauthenticated."})
    )
    async with client:
        result = await check_auth(client)

    assert result["authenticated"] is False
    assert result["token_present"] is True
    assert "rejected" in result["reason"]


async def test_a_401_with_no_token_says_there_is_nothing_stored():
    client, _ = make_probe_client(
        lambda request: httpx.Response(401, json={"message": "Unauthenticated."}), token=None
    )
    async with client:
        result = await check_auth(client)

    assert result["authenticated"] is False
    assert result["token_present"] is False
    assert "No Uplers token stored" in result["reason"]


async def test_a_500_is_unknown_rather_than_signed_out():
    """Unknown must not collapse into "logged out".

    "Your session expired, sign in again" costs the operator a browser round
    trip; saying it because the network blipped spends his time to hide our
    own uncertainty. False is reserved for a server that actually said no.
    """
    client, _ = make_probe_client(lambda request: httpx.Response(500, text="boom"))
    async with client:
        result = await check_auth(client)

    assert result["authenticated"] is None
    assert result["authenticated"] is not False
    assert result["error"] == "talent_error"
    assert "Could not determine session state" in result["reason"]
    assert result["token_present"] is True


async def test_a_transport_failure_is_unknown_too():
    def handler(request):
        raise httpx.ConnectError("no route to host", request=request)

    client, _ = make_probe_client(handler)
    async with client:
        result = await check_auth(client)

    assert result["authenticated"] is None
    assert "ConnectError" in result["reason"]


async def test_check_auth_never_returns_the_token(tmp_path):
    """The result goes back to a model, which may well print it verbatim.

    Driven from a real SessionStore rather than a literal so the value under
    test travels the whole path it travels in production: disk, supplier,
    Authorization header, and out through the result dict.
    """
    store = make_store(tmp_path)
    store.save(TOKEN, method="browser")

    transport, calls = make_transport(lambda request: httpx.Response(200, json=PROFILE_PAYLOAD))
    client = TalentClient(store.token, delay=0, transport=transport)
    async with client:
        result = await check_auth(client)

    assert calls[0].headers["authorization"] == "Bearer " + TOKEN  # it did travel
    blob = json.dumps(result)
    assert TOKEN not in blob
    for size in range(4, len(TOKEN) + 1):
        assert TOKEN[:size] not in blob, "a %d-char prefix of the token leaked" % size

    # And through the fragment detector, which sees the spellings the two
    # lines above cannot: a base64, hex or percent-encoded echo shares no
    # substring with the token. Measured on scripts/leak_matrix.py - before
    # this line, this test was GREEN under b64, b64url, hex and percent,
    # meaning a build echoing the whole credential passed it.
    assert leaks_of(result, SANCTUM_FRAGMENTS) == []


async def test_check_auth_never_returns_a_jwt(tmp_path):
    """The JWT arm of the test above, and the one that matters in production:
    his real credential is a JWT, not a Sanctum token."""
    store = make_store(tmp_path)
    store.save(JWT_TOKEN, method="browser")

    transport, calls = make_transport(lambda request: httpx.Response(200, json=PROFILE_PAYLOAD))
    client = TalentClient(store.token, delay=0, transport=transport)
    async with client:
        result = await check_auth(client)

    assert calls[0].headers["authorization"] == "Bearer " + JWT_TOKEN  # it did travel
    assert leaks_of(result, JWT_FRAGMENTS) == []


def test_the_guest_token_key_is_known_and_never_used_to_authenticate():
    """It is read only to be recognised and refused. Naming it here keeps the
    distinction from TOKEN_KEY explicit rather than buried in the login flow."""
    assert sess.TOKEN_KEY == "token"
    assert sess.GUEST_TOKEN_KEY == "guest_token"
    assert sess.TOKEN_KEY != sess.GUEST_TOKEN_KEY
