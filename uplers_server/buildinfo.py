"""What code THIS process holds - resolved once, at import, and then frozen.

A fix committed to disk changes nothing for a server that is already up. On
2026-08-21 that cost real time on this family of servers: a bug was diagnosed
as a regression and an agent was dispatched to re-fix it, and the correction
came back that the fix was already on disk and the *process* was stale. Every
check available at the time was a behavioural fingerprint - does this field
appear, is that count right - and a stale process passes and fails those for
the same reasons a genuinely buggy one does.

THE FREEZE IS THE WHOLE POINT, NOT A PERFORMANCE NOTE. A ``git rev-parse`` run
per request from a stale process reports the NEW commit sitting on disk, which
is worse than reporting nothing: it reads as confirmation that the fix is
loaded, and what it confirms is false. So these are module CONSTANTS, bound at
import, and ``uplers_server_info()`` reads them. It must never re-resolve, and
``tests/test_server_info.py`` proves it by making ``subprocess.run`` raise and
calling the tool twice.

TWO REPOSITORIES ARE STAMPED, DELIBERATELY. This server's scoring IS jobcore's
- ``policy.py`` binds a ``ScoringEngine`` out of it and ``fit.py`` does nothing
else - so a stale jobcore moves this server's numbers while this server's own
commit reads perfectly current. One commit field covering only this checkout
would hide exactly half the surface that can be stale. jobcore is installed
editable from a sibling checkout, so it has its own HEAD and its own dirty
flag, and ``jobcore.__file__`` is the honest way to find that checkout from
inside this process rather than guessing at a sibling directory that a
non-editable install would not have.

Nothing here may break server import: every git call inside jobcore is bounded
by a timeout and every failure degrades to ``source="unknown"`` with a reason,
never to a plausible-looking hash nobody measured.
"""

from __future__ import annotations

import jobcore
from jobcore import buildinfo as _jc

from . import config

#: The uplers checkout's git state, frozen at the moment this module imported.
#: Compare ``BUILD.commit`` against ``git rev-parse HEAD`` in the checkout: a
#: mismatch means this process predates the commit on disk and no behaviour
#: debugging is worth doing until it is restarted.
BUILD = _jc.stamp(config.REPO_ROOT)

#: jobcore's checkout, stamped separately for the reason in the module
#: docstring. ``jobcore.__file__`` points inside the installed package; jobcore
#: walks up from it to find the work tree.
JOBCORE_BUILD = _jc.stamp(jobcore.__file__)

#: When this process came up and how long it has been up. Unlike the two stamps
#: this is NOT frozen - uptime is derived fresh on every read, because a cached
#: uptime is a lie that grows.
CLOCK = _jc.ProcessClock()


def build_block() -> dict:
    """The ``build`` block of the ``uplers_server_info()`` payload.

    Reads the three constants above and resolves nothing. Assembled here rather
    than in ``server.py`` so the tool has no opportunity to call ``stamp`` or
    ``resolve`` itself.
    """
    return {
        "code": BUILD.as_dict(),
        "jobcore": JOBCORE_BUILD.as_dict(),
        "process": CLOCK.as_dict(),
    }
