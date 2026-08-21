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
