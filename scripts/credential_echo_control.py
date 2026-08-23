"""A LEAKING build of this server's auth results, for showing the leak tests fail.

WHY THIS FILE IS IN THE REPO
----------------------------
Every "the token never leaks" assertion here hunts for strings DERIVED FROM
the credential. That family has a blind spot, and it is not the one it looks
like: the dangerous encoding does not have to live in the credential, it can
live in the LEAK PATH. A build that base64s the token on its way out shares no
substring with the token, so a walker hunting the token - or a marker planted
inside it - sees nothing at all.

The sibling naukri server was caught by exactly that: its walker hunted a
plaintext marker, its credential was a base64url JWT, and the marker does not
survive the encoding. **Uplers is the most exposed of the four, because its
credential IS a base64url JWT.**

That is why this file exists rather than an argument about it. It is a pytest
plugin that wraps the five result-producing auth entry points, reads the
credential THE TEST ITSELF PLANTED (via SessionStore.token, so it echoes the
real value rather than a constant of its own), and puts it back into the
result under one chosen transform. Every transform below is a way a credential
has actually escaped a real program: a "safe" truncated fingerprint, a debug
blob, a url parameter, a value split across two display fields, an exception
repr, a log line nobody read.

The requirement is total: **every guarded test must go RED under every single
transform.** A green cell is a leak this suite would ship.

HOW TO RUN IT
-------------
    UPLERS_LEAK_TRANSFORM=b64 PYTHONPATH=scripts \\
        venv/Scripts/python -m pytest -p credential_echo_control tests/test_session.py

    # PowerShell
    $env:UPLERS_LEAK_TRANSFORM="b64"; $env:PYTHONPATH="scripts"
    venv/Scripts/python -m pytest -p credential_echo_control tests/test_session.py

`scripts/leak_matrix.py` runs the whole grid and prints the table. Adapted
from `linkedin/scripts/credential_echo_control.py`, where the transform list
was derived; the list is the valuable part and is kept identical so a finding
on one server is comparable with the other three.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Optional
from urllib.parse import quote

#: Every way the wrapped payload can carry the credential back out.
#: tests/test_session_lifecycle.py parametrises its controls off THIS tuple,
#: so a transform without a control cannot exist.
TRANSFORMS = (
    "verbatim",
    "prefix12",
    "b64",
    "b64url_nopad",
    "hex",
    "percent",
    "split",
    "repr_escaped",
    "in_log",
)

_LOG = logging.getLogger("uplers_server.session")

#: The last credential SessionStore handed out. The tests plant their own, and
#: echoing THAT is the whole point - a constant of our own would prove nothing
#: about the value the code actually handles.
_LAST_TOKEN: Optional[str] = None


def render(secret: str, transform: str) -> Any:
    """One credential, rendered the way the chosen leak would render it."""
    raw = secret.encode("utf-8")
    if transform == "verbatim":
        return secret
    if transform == "prefix12":
        # The "safe fingerprint" that is not safe. On a JWT it is worse than
        # useless in the other direction too: the first twelve characters are
        # the base64 of a standard header and identify nothing.
        return secret[:12] + "..."
    if transform == "b64":
        return base64.b64encode(raw).decode("ascii")
    if transform == "b64url_nopad":
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if transform == "hex":
        return raw.hex()
    if transform == "percent":
        return quote(secret, safe="")
    if transform == "split":
        half = len(secret) // 2
        return [secret[:half], secret[half:]]
    if transform == "repr_escaped":
        # An OSError stringifies its filename through repr(). That rendering
        # already defeated an exact-substring PATH check in this repo - see
        # tests/test_path_hygiene.py - so drive it at a credential instead.
        return str(OSError(2, "no such file", secret))
    raise AssertionError("unknown transform " + repr(transform))


def _inject(payload: Any, transform: str) -> Any:
    """Put the credential back into a result the way a leaking build would."""
    secret = _LAST_TOKEN
    if not secret:
        return payload

    if transform == "in_log":
        # Not in the result at all. Only in a log record - which is exactly
        # where a leak hides from a test that reads only the return value.
        _LOG.debug("uplers bearer token for this profile is %s", secret)
        return payload

    rendered = render(secret, transform)

    if isinstance(payload, dict):
        credential = payload.get("credential")
        if isinstance(credential, dict):
            credential["fingerprint"] = rendered      # where a redaction bug lives
        else:
            payload["fingerprint"] = rendered
        return payload

    # Pydantic results (AuthStatus and friends). Appending to a free-text
    # field is the realistic shape here: a reason string that quotes what was
    # sent is how a credential reaches a transcript in practice.
    for field in ("reason", "message", "note"):
        current = getattr(payload, field, None)
        if isinstance(current, str):
            try:
                setattr(payload, field, "%s [%s]" % (current, rendered))
            except Exception:                          # noqa: BLE001 - frozen model
                break
            return payload
    return payload


def pytest_configure(config) -> None:                  # noqa: ARG001
    transform = os.environ.get("UPLERS_LEAK_TRANSFORM")
    if not transform:
        return
    if transform not in TRANSFORMS:
        raise SystemExit("unknown UPLERS_LEAK_TRANSFORM %r" % transform)

    import server
    from uplers_server import session as session_mod

    store_cls = session_mod.SessionStore
    real_read = store_cls.read
    real_describe = store_cls.describe
    real_check_auth = session_mod.check_auth

    def read(self, *a, **k):
        """Hooked at READ, not at token().

        MEASURED, and it is the difference between a grid that means something
        and one that does not: `describe()` calls `self.read()` directly and
        never goes through `token()`. Hooking `token()` left the describe-only
        tests with NO credential to echo, so they passed under every transform
        including `verbatim` - four whole columns green for the uninteresting
        reason that nothing was ever injected. `read()` is the one funnel both
        paths share.
        """
        global _LAST_TOKEN
        data = real_read(self, *a, **k)
        value = data.get("token") if isinstance(data, dict) else None
        if isinstance(value, str) and value:
            _LAST_TOKEN = value
        return data

    def describe(self, *a, **k):
        return _inject(real_describe(self, *a, **k), transform)

    async def check_auth(*a, **k):
        return _inject(await real_check_auth(*a, **k), transform)

    store_cls.read = read
    store_cls.describe = describe
    session_mod.check_auth = check_auth
    # server.py imported check_auth by value, so rebind there too.
    if hasattr(server, "check_auth"):
        server.check_auth = check_auth

    for name in ("uplers_session_info", "uplers_logout", "uplers_auth_status"):
        tool = getattr(server, name, None)
        if tool is None:
            continue

        def wrap(inner):
            async def leaking(*a, **k):
                return _inject(await inner(*a, **k), transform)
            return leaking

        setattr(server, name, wrap(tool))
