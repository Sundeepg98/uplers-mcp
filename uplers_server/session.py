"""Where the bearer token lives, and the one honest way to ask "am I logged in".

Two rules govern this module, and the second one is the expensive one.

**The token never leaves this process except as a header.** It is written to
`data/session.json` (already gitignored, chmod 0600 where the OS honours it),
never logged, never returned by a tool, never put in an error message. What
callers get is its *shape*: present or absent, expiring when, and nothing else.

**Authentication is measured, never inferred.** `uplers_auth_status` must be
able to return a truthful `false`, so the answer comes from an actual request
to a route that 401s when logged out - not from a file existing on disk.

That second rule is written in blood. The sibling Instahyre server shipped a
login tool that returned success the moment a session cookie appeared; Django
issues those to anonymous visitors, so the condition was already true when the
login page finished rendering. It closed the browser before the operator could
type and reported `authenticated: true` while every real call 401'd.

Uplers has the identical trap wearing different clothes: the SPA falls back to
``localStorage["guest_token"]`` when there is no real token, so a token can be
*present and anonymous*. Hence :data:`GUEST_TOKEN_KEY` is read only to be
recognised and refused - never to authenticate with.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config, endpoints

#: The localStorage key holding a real, signed-in token.
TOKEN_KEY = "token"

#: The localStorage key holding an ANONYMOUS token. Never authenticates.
GUEST_TOKEN_KEY = "guest_token"


def session_path() -> Path:
    return config.DATA_DIR / "session.json"


def browser_profile_path() -> Path:
    """Persistent Chrome profile, so a second login is usually free."""
    path = config.DATA_DIR / "browser_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- token introspection --------------------------------------------------


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def token_format(token: str | None) -> str:
    """Classify a token without asserting anything we cannot prove.

    Returns "jwt" when it really parses as one, "sanctum" for Laravel's
    ``<id>|<plaintext>`` personal-access-token shape, "opaque" otherwise, and
    "absent" for nothing at all. Used only to decide whether an expiry is
    knowable; never used to decide whether a token works.
    """
    if not token:
        return "absent"
    parts = token.split(".")
    if len(parts) == 3:
        try:
            json.loads(_b64url_decode(parts[1]))
            return "jwt"
        except (ValueError, binascii.Error, UnicodeDecodeError):
            pass
    if "|" in token and token.split("|", 1)[0].isdigit():
        return "sanctum"
    return "opaque"


def token_expiry(token: str | None) -> float | None:
    """Unix expiry from a JWT's `exp` claim, or None when it is not knowable.

    Laravel Sanctum tokens are opaque strings with a server-side expiry, so
    None is the *common* answer here and does not mean "never expires". The
    honest reading of None is "ask the server" - which is what
    :func:`check_auth` does anyway.
    """
    if token_format(token) != "jwt":
        return None
    try:
        claims = json.loads(_b64url_decode(token.split(".")[1]))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    exp = claims.get("exp")
    return float(exp) if isinstance(exp, (int, float)) else None


def _iso(stamp: float | None) -> str | None:
    if stamp is None:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat(timespec="seconds")


class SessionStore:
    """Reads and writes the bearer token. Nothing else touches that file."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or session_path()

    def read(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            with self.path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            # A corrupt session file is a re-login, not a crash.
            return {}
        return data if isinstance(data, dict) else {}

    def token(self) -> str | None:
        value = self.read().get("token")
        return value if isinstance(value, str) and value else None

    def save(self, token: str, *, method: str) -> dict:
        """Persist a token. Returns metadata ABOUT it, never the token itself."""
        if not token:
            raise ValueError("refusing to save an empty token")
        expires = token_expiry(token)
        payload = {
            "saved_at": time.time(),
            "method": method,
            "token": token,
            "token_format": token_format(token),
            "expires_at": expires,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(temp, self.path)
        _restrict(self.path)
        return self.describe()

    def clear(self) -> bool:
        """Forget the token. A logout must not be able to raise.

        `missing_ok` rather than an is_file() check because the two calls are
        not atomic: on Windows a lock or a racing writer between them would
        otherwise throw out of a logout, which is the one operation that has to
        work when things are already going wrong.
        """
        existed = self.path.is_file()
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            return False
        return existed

    def describe(self) -> dict:
        """Everything a caller may know about the stored session.

        Deliberately contains no token, no prefix of one, and no length -
        a length is a small leak and buys nothing a boolean does not.
        """
        data = self.read()
        token = data.get("token")
        expires = data.get("expires_at")
        out = {
            "token_present": bool(token),
            "token_format": data.get("token_format") or token_format(token),
            "saved_at": _iso(data.get("saved_at")),
            "method": data.get("method"),
            "expires_at": _iso(expires),
        }
        if isinstance(expires, (int, float)):
            out["expired"] = expires <= time.time()
        return out


def _restrict(path: Path) -> None:
    """Best-effort owner-only. Windows ACLs are not POSIX modes, so this is a
    floor, not a guarantee - the real protection is that `data/` is gitignored."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


# --- the measurement ------------------------------------------------------


async def check_auth(client) -> dict:
    """Ask the server whether this token works. The only source of a `true`.

    `client` is a :class:`~uplers_server.talent.TalentClient`. One cheap GET to
    a route whose logged-out behaviour was measured live, so neither answer is
    a guess.

    Returns `authenticated` True, False, or **None** - None meaning the state
    could not be determined (network down, unexpected 500). Unknown does not
    collapse into false, because "you are logged out, go and sign in again" is
    a lie that costs the operator a browser round trip.
    """
    from .talent import AuthRequired, TalentError

    has_token = client.has_token()
    try:
        payload = await client.get_json(endpoints.EP_AUTH_PROBE)
    except AuthRequired:
        return {
            "authenticated": False,
            "reason": (
                "The stored token was rejected. Uplers sessions are short-lived; "
                "run uplers_login() to sign in again."
                if has_token
                else "No Uplers token stored. Run uplers_login() to sign in."
            ),
            "token_present": has_token,
            "checked_against": endpoints.AUTH_PROBE_NOTE,
        }
    except TalentError as exc:
        return {
            "authenticated": None,
            "reason": "Could not determine session state: %s" % exc,
            "error": getattr(exc, "kind", "error"),
            "token_present": has_token,
            "checked_against": endpoints.AUTH_PROBE_NOTE,
        }

    # A 200 is necessary but NOT sufficient. The bundle falls back to an
    # anonymous `guest_token`, so an anonymous 200 is a real possibility, and
    # "the request did not fail" is precisely the too-weak condition that shipped
    # a false success on the sibling Instahyre server. The token only counts as
    # live when the response actually carries HIS profile back.
    details = payload.get("talent_details") if isinstance(payload, dict) else None
    if not isinstance(details, dict) or not details:
        return {
            "authenticated": None,
            "reason": (
                "%s returned HTTP 200 but no `talent_details` object, so this is not "
                "proof of a signed-in session - an anonymous guest token can also get "
                "a 200 here. Treating the state as unknown rather than claiming a "
                "session that was not demonstrated. Keys seen: %s"
                % (
                    endpoints.EP_AUTH_PROBE,
                    sorted(payload)[:8] if isinstance(payload, dict) else type(payload).__name__,
                )
            ),
            "error": "unexpected_shape",
            "token_present": has_token,
            "checked_against": endpoints.AUTH_PROBE_NOTE,
        }

    out = {
        "authenticated": True,
        "token_present": has_token,
        "checked_against": endpoints.AUTH_PROBE_NOTE,
    }
    # Proof it is HIS account and not somebody else's, without printing anything
    # sensitive: a name and the completion percentage.
    name = details.get("full_name") or details.get("name") or details.get("first_name")
    if name:
        out["signed_in_as"] = name
    if payload.get("profile_completion_percentage") is not None:
        out["profile_completion_percentage"] = payload["profile_completion_percentage"]
    return out


# --- the lifecycle report -------------------------------------------------
#
# `uplers_session_info` and `uplers_logout` are built here rather than inline
# in server.py so that the sentences below have ONE home. Most of what those
# two tools return is prose, and prose that says how long a credential lasts
# is load-bearing: it is what the operator plans his day around. A second copy
# of it in a docstring is a second copy to get wrong.


#: The sentence this whole module exists to enforce, said in every path.
TOKEN_IS_NOT_A_SESSION = (
    "a token in the store is NOT a session. Its presence means a sign-in "
    "happened once; it does not mean Uplers still honours it. Their bundle "
    "also hands anonymous visitors a `guest_token`, so even a well-formed "
    "token can belong to nobody. Only the live check establishes a session."
)

#: Uplers' stored JWT carries an `exp` roughly six months out. That number is
#: TRUE and it is also USELESS on its own, and the gap between those two facts
#: is the most dangerous thing this tool could get wrong: reporting it flatly
#: would tell the operator he has half a year when he has about a day.
EXPIRY_IS_A_CEILING = (
    "the JWT's own `exp` claim, read from the token this server stores. It is "
    "a CEILING THE TOKEN CLAIMS, not a promise Uplers keeps. Uplers revokes "
    "server-side far sooner: this server's own login docstring and its MCP "
    "instructions both say sessions here are SHORT-LIVED and that a re-login "
    "is needed roughly daily. Read the date as the latest the token could "
    "possibly still be good, never as how long it will last. Only the live "
    "check settles which of those it is today."
)

#: A Sanctum or opaque token keeps its expiry on Uplers' servers and never
#: sends it here. `expired` is null in that case and MUST NOT be false: "I
#: cannot tell" and "it is fine" are different answers to the same question.
NO_KNOWABLE_EXPIRY = (
    "not knowable from here. A %s token is a bare string whose expiry lives "
    "on Uplers' servers and is never sent to this client, so there is no date "
    "to read. `expired` is null rather than false, because 'I cannot tell' "
    "and 'it is fine' are different answers. Only the live check settles it."
)

#: The fourth case, and the reason the branch below is not an if/else: a token
#: can parse as a JWT and still carry no `exp` claim.
JWT_WITHOUT_EXP = (
    "the stored token parses as a JWT but carries no readable `exp` claim, so "
    "there is no date to read and `expired` is null rather than false. Only "
    "the live check settles it."
)

#: There is no `uplers_reauth` and there is not going to be one. Ruled with
#: evidence 2026-08-23; the reasoning is kept here because the operator will
#: eventually ask why this server has one fewer tool than its siblings.
RENEWAL_WHY = (
    "there is nothing here to renew FROM. On the sibling servers a durable "
    "store outlives the credential in use, and that is what a silent renew "
    "spends. On Uplers it is the other way round: the BEARER TOKEN is the "
    "long-lived layer and the BROWSER PROFILE is the short one. That "
    "profile's `uplers_session` cookie has already lapsed, and its `talent`, "
    "`l` and `source` cookies are session-only rows that die with the "
    "browser, so nothing durable survives to mint a fresh token from. The "
    "exhaustive 214-route sweep recorded in endpoints.py found no refresh "
    "route, and the SPA simply reads localStorage['token'] with no renew flow "
    "at all. A `uplers_reauth` here would therefore be `uplers_login` wearing "
    "a different name, so it is deliberately not shipped. Recovery is "
    "uplers_login() and the Google sign-in, done by hand."
)

#: `renewal.mechanism` and `renewal.uses_browser` were added by a late contract
#: amendment, and the defect they close is worth stating: the two servers that
#: DO ship a reauth both drive a browser - naukri navigates a pooled page,
#: instahyre launches a headless Chromium - and neither said so, which let
#: "silent renew" read as "free". It is not free. So the mechanism and its cost
#: are declared everywhere, including here where the answer is "there isn't one".
#:
#: Written as a STRAIGHT ANSWER rather than a pointer at `renewal.why`. A
#: caller reading `mechanism` across four servers should not have to follow a
#: cross-reference on one of them to learn what recovery costs.
RENEWAL_MECHANISM = (
    "none - there is no silent renew on this platform, so nothing runs in the "
    "background to get the session back. Recovery is uplers_login(), which "
    "opens a browser window at Uplers' login page and waits for the OPERATOR "
    "to complete the Google sign-in BY HAND. That is a human action, not an "
    "automated one, and this server never handles a password: budget a "
    "person's attention for it, not a retry. `uses_browser` is null rather "
    "than false for the same reason there is no `uplers_reauth` - there is no "
    "renewal mechanism here to characterise, and false would assert that a "
    "silent renew exists and merely happens not to use a browser, which is a "
    "claim about a thing that does not exist."
)

#: `renewal.session_lapses_at` answers a DIFFERENT question from
#: `credential.expires_at`, and the difference is why it is a separate field:
#: "when must he sign in BY HAND" rather than "when does this credential die".
#: On the sibling naukri server those two answers differ by 188 days - its
#: `nauk_at` measures half an hour out while the session behind it does not
#: lapse for six months - so a client comparing `expires_at` across the four
#: servers would read naukri as nearly dead. On Uplers the two coincide, and
#: WHY they coincide is the entire content of this field.
SESSION_LAPSES_SOURCE = (
    "the `token` credential above, and the two dates are IDENTICAL here "
    "because there is no silent renew on this platform. With nothing to renew "
    "from, the session cannot outlive the credential that carries it. READ "
    "THE SAME WARNING INTO THIS FIELD AS INTO `expiry_is_authoritative`, "
    "because this is the field most likely to be mistaken for a deadline: the "
    "date is the token's own `exp` claim, which is the LATEST the session "
    "could possibly still be good and NOT how long it will last. Uplers "
    "revokes server-side far sooner - expect to sign in again roughly daily. "
    "A caller who plans against this number as a runway will be wrong in the "
    "expensive direction."
)

#: The null case. Both dates go null together and this says which fact was
#: missing - never a zero, never a false.
SESSION_LAPSES_UNKNOWN = (
    "the `token` credential above, whose expiry is not knowable from here "
    "(%s), so this date is null rather than guessed. The two fields would "
    "still coincide if it were readable: there is no silent renew on this "
    "platform, so the session cannot outlive the credential that carries it. "
    "Only the live check establishes whether the session is alive today."
)

#: What the tools do about an expiry, and the way back, named.
ON_EXPIRY = (
    "authenticated tools raise with the session-expired reason; not one of "
    "them returns an empty list in place of a refusal, because a quiet day "
    "and a dead session must never look alike. The public tier is unaffected "
    "and keeps serving from the local index. Recover by calling "
    "uplers_login(), which opens a browser window for the Google sign-in - "
    "this server never handles a password."
)

#: Where the facts came from, and why `supporting` is empty rather than absent.
CREDENTIAL_SOURCE = (
    "the on-disk store, read without a browser. `supporting` is empty because "
    "there is genuinely nothing to put in it: Uplers authenticates with the "
    "bearer token alone, and this server holds no csrf token and no refresh "
    "token beside it. That empty list is a measured absence, not an unfilled "
    "field."
)

#: Uplers is the one server in this family where the credential's own stated
#: expiry is NOT authoritative, so this is a module constant rather than
#: something computed per call. Nothing this server can read would justify
#: flipping it to true; only Uplers changing how they revoke would.
EXPIRY_IS_AUTHORITATIVE = False


def _iso_z(stamp: float | None) -> str | None:
    """ISO8601 in the auth contract's exact spelling, ``YYYY-MM-DDTHH:MM:SSZ``.

    Deliberately NOT :func:`_iso`, which renders ``+00:00`` and is already
    published by ``uplers_auth_status``. Same instant, two spellings, and the
    contract names this one. Unifying them would move an existing tool's
    output, which is a separate decision from adding this one.
    """
    if stamp is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))


def credential_report(store: "SessionStore") -> dict:
    """The stored credential's shape. Never its value, its length or a prefix.

    ``format`` is derived from the token itself rather than from the metadata
    field written beside it at save time, because the token is the thing that
    is actually going to be sent.
    """
    described = store.describe()
    token = store.token()
    fmt = token_format(token)
    expires = token_expiry(token)

    out = {
        "kind": "bearer_token",
        "name": TOKEN_KEY,
        "present": bool(described.get("token_present")),
        "format": fmt,
        "expires_at": None,
        "expires_in_days": None,
        "expired": None,
        "expiry_source": "",
        "expiry_is_authoritative": EXPIRY_IS_AUTHORITATIVE,
    }

    if expires is not None:
        remaining = expires - time.time()
        out["expires_at"] = _iso_z(expires)
        out["expires_in_days"] = round(remaining / 86400.0, 1)
        out["expired"] = remaining <= 0
        out["expiry_source"] = EXPIRY_IS_A_CEILING
    elif fmt == "absent":
        out["expiry_source"] = (
            "no token is stored, so there is no expiry to read. `expired` is "
            "null rather than true: nothing expired, there is simply nothing."
        )
    elif fmt == "jwt":
        out["expiry_source"] = JWT_WITHOUT_EXP
    else:
        out["expiry_source"] = NO_KNOWABLE_EXPIRY % fmt

    return out


def _durability(store: "SessionStore") -> dict:
    """Where the token lives and what it survives. Path relativised, not deleted."""
    from . import policy

    return {
        "stored_in": policy.display_path(str(store.path)),
        "survives_server_restart": True,
        "survives_machine_reboot": True,
        "why": (
            "the token is a FILE on disk, not state held in this process, so "
            "stopping the server or rebooting the machine leaves it exactly "
            "where it was. What ends it is Uplers revoking it server-side, "
            "uplers_logout() deleting the file, or the data directory going "
            "away. Note which way round that is: the FILE outlives the "
            "process comfortably, while the SESSION it names usually does not "
            "outlive the day."
        ),
    }


def _lapse_unknown_reason(fmt: str) -> str:
    """Which missing fact left `session_lapses_at` null. Never a bare 'unknown'."""
    if fmt == "absent":
        return "no token is stored"
    if fmt == "jwt":
        return "the stored JWT carries no readable `exp` claim"
    return "a %s token keeps its expiry on Uplers' servers" % fmt


def _renewal(credential: dict) -> dict:
    """Renewal, plus the date the operator must sign in by hand.

    Takes the ALREADY BUILT credential block rather than rebuilding it, so
    `session_lapses_at` and `credential.expires_at` are the same values by
    construction. Computing them twice would let a rounding tick put a tenth
    of a day between two fields that are defined to be equal here.
    """
    lapses_at = credential.get("expires_at")
    return {
        "silent_renew_available": False,
        # NULL, not False. Same three-valued discipline as `authenticated`:
        # there is no mechanism here to characterise, so a False would be a
        # claim about something that does not exist.
        "uses_browser": None,
        "tool": None,
        "mechanism": RENEWAL_MECHANISM,
        "why": RENEWAL_WHY,
        "session_lapses_at": lapses_at,
        "session_lapses_in_days": credential.get("expires_in_days"),
        "session_lapses_source": (
            SESSION_LAPSES_SOURCE
            if lapses_at
            else SESSION_LAPSES_UNKNOWN % _lapse_unknown_reason(
                credential.get("format") or "absent"
            )
        ),
    }


def _what_it_means(authenticated: bool | None) -> str:
    if authenticated is True:
        return (
            "the probe route was asked and answered with his profile in the "
            "body, so 'authenticated' above is a measurement. It was not "
            "inferred from the token being on disk."
        )
    if authenticated is False:
        return (
            "Uplers was asked and REFUSED the stored token. That is a real "
            "no, not an unknown, and the way back is uplers_login()."
        )
    return (
        "'authenticated' is null because the live check produced no verdict, "
        "NOT because Uplers said no. A null is not a refusal and is not a "
        "reason to sign in again yet. Everything else here is read from this "
        "machine, and " + TOKEN_IS_NOT_A_SESSION
    )


def session_info_offline(
    store: "SessionStore",
    *,
    why_no_live_check: str,
    attempted: bool = False,
) -> dict:
    """Store facts only, with no network and no browser touched at all.

    ``authenticated`` is null here and STAYS null. The token's presence is
    reported under its own label, next to a live_check block that says in
    plain words that no verdict was obtained and why. Deriving a verdict from
    presence is the exact bug ``scripts/presence_is_auth_control.py``
    re-creates, and the tests in ``tests/test_session_lifecycle.py`` go red
    under it.

    ``attempted`` separates two different facts that share one null: "you
    asked me not to try" and "I tried and could not". The operator acts
    differently on each, so they do not share a field.
    """
    credential = credential_report(store)
    return {
        "server": "uplers",
        "authenticated": None,
        "checked_against": endpoints.AUTH_PROBE_NOTE,
        "live_check": {
            "attempted": attempted,
            "completed": False,
            "endpoint": endpoints.AUTH_PROBE_NOTE,
            "why_not": why_no_live_check,
            "what_it_means": _what_it_means(None),
        },
        "credential": credential,
        "supporting": [],
        "credential_source": CREDENTIAL_SOURCE,
        "durability": _durability(store),
        "renewal": _renewal(credential),
        "on_expiry": ON_EXPIRY,
    }


async def session_info(store: "SessionStore", client) -> dict:
    """Measure the session, then report what the store says about it.

    :func:`check_auth` is the ONLY source of the ``authenticated`` verdict and
    it already returns True / False / None correctly. Nothing here re-derives
    it, softens it, or fills a null in from the credential block below.
    """
    status = await check_auth(client)
    authenticated = status.get("authenticated")
    credential = credential_report(store)

    live = {
        "attempted": True,
        "completed": authenticated is not None,
        "endpoint": endpoints.AUTH_PROBE_NOTE,
        "what_it_means": _what_it_means(authenticated),
    }
    if authenticated is None:
        live["why_not"] = status.get("reason") or (
            "the probe ran and returned no usable verdict."
        )

    out = {
        "server": "uplers",
        "authenticated": authenticated,
        "checked_against": status.get("checked_against") or endpoints.AUTH_PROBE_NOTE,
        "live_check": live,
        "credential": credential,
        "supporting": [],
        "credential_source": CREDENTIAL_SOURCE,
        "durability": _durability(store),
        "renewal": _renewal(credential),
        "on_expiry": ON_EXPIRY,
    }
    if status.get("signed_in_as"):
        out["signed_in_as"] = status["signed_in_as"]
    if authenticated is False and status.get("reason"):
        out["reason"] = status["reason"]
    return out


def logout_report(store: "SessionStore") -> dict:
    """Delete the local token and say exactly what that cost. Never raises.

    The ``authenticated: false`` here is the one false in this server that is
    not a measurement, and it is legitimate for a reason worth stating: with
    no credential left there is no authenticated request that CAN be made from
    here, so the false is provable rather than observed.

    That reasoning collapses if the file is still on disk afterwards, which is
    possible on Windows where a lock can survive an unlink that did not raise.
    The removal is therefore CONFIRMED, and a removal that did not happen
    reports ``authenticated`` null under a named ``removal_failed`` flag
    rather than claiming a signed-out state it never reached. That branch is
    the only place this tool departs from the contract's fixed ``false``, and
    it departs in the direction the contract exists to protect.
    """
    from . import policy

    cleared = store.clear()
    where = policy.display_path(str(store.path))
    scope = (
        "the stored bearer token at %s, and nothing else. The persistent "
        "browser profile is untouched, and NOTHING was signed out on Uplers' "
        "side - this server can delete its own copy of the credential and "
        "cannot reach their session record." % where
    )
    recover_by = (
        "uplers_login(), which opens a browser window for the Google sign-in. "
        "The persistent browser profile was NOT cleared, so this is usually a "
        "few seconds and no password."
    )

    if store.path.is_file():
        # The unlink did not raise and the file is still there. Saying "signed
        # out" now would be a guess dressed as a fact, which is the one thing
        # this contract forbids everywhere else.
        return {
            "cleared": False,
            "removal_failed": True,
            "scope": scope,
            "authenticated": None,
            "reason": (
                "the session file could not be removed and is STILL ON DISK, "
                "so the credential may well still work. Signed out is not "
                "established here and is not being claimed. Check whether "
                "another process is holding the file, then try again."
            ),
            "what_is_lost": "nothing. The removal did not take effect.",
            "recover_by": recover_by,
        }

    return {
        "cleared": cleared,
        "scope": scope,
        "authenticated": False,
        "reason": (
            "provable rather than measured: there is no credential left to "
            "send, so no authenticated request can be made from here at all. "
            "This is the one false in this server that needs no live check "
            "behind it."
            if cleared
            else
            "provable rather than measured: there was no stored token to "
            "delete, so there was nothing to send before this call either. "
            "Already signed out locally is not an error, it is a different "
            "sentence."
        ),
        "what_is_lost": (
            "the authenticated tier only. uplers_my_feed, uplers_my_pipeline, "
            "uplers_my_profile and the rest will report an expired session "
            "until you sign in again. Nothing local is deleted: the cached "
            "index, the tracked applications, the saved shortlist and the "
            "profile snapshots all survive, and the whole public tier keeps "
            "working at no cost."
            if cleared
            else "nothing. There was no token stored."
        ),
        "recover_by": recover_by,
    }
