"""Capture the READ-ONLY routes behind the agent read-through, as fixtures.

Run against a live signed-in session. Writes one file per route into
`tests/fixtures/`, so the suite tests the shape Uplers actually sends rather
than a shape somebody invented - the same rule `capture_profile_fixture.py`
exists to enforce.

WHY A GUARD RATHER THAN CARE. Every route here lives under
``talent/outreach/*``, which is the namespace of Uplers' PAID outreach-agent
product, and one of its siblings (``consent-email-job-scan``) is a write that
changes what Uplers reads out of his mailbox. A typo in this file is therefore
not a failed capture, it is an unrequested change to his account. So the
method is pinned to GET and the path to an allowlist, in code, and a miss
raises before the client is built.

Rate discipline: his live session, one request at a time, with the client's
own inter-request delay left at the default rather than zeroed.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from uplers_server import endpoints  # noqa: E402
from uplers_server.session import SessionStore  # noqa: E402
from uplers_server.talent import TalentClient  # noqa: E402

OUT_DIR = REPO / "tests" / "fixtures"

#: (fixture stem, path, params). GET only - see the module docstring.
CAPTURES = (
    ("outreach_step", "talent/outreach/outreach-step", None),
    ("outreach_dashboard", "talent/outreach/get-outreach-dashboard-data", None),
    ("outreach_pending_jobs", "talent/outreach/pending-jobs", None),
    ("outreach_missed_followups", "talent/outreach/missed-positive-reply-followups", None),
    ("outreach_tailor_activity", "talent/outreach/agent-tailor-activity", None),
    ("talent_preference", "talent/get-preference", None),
    ("saved_filter_page", endpoints.EP_OPPORTUNITIES,
     {"is_saved_filter": 1, "pagination": 20, "page": 1}),
)

ALLOWED = {path for _, path, _ in CAPTURES}

#: Same belt-and-braces rule as the profile capture: a key Uplers adds after
#: this was written must not land on disk unnoticed.
SUSPICIOUS = re.compile(
    r"ctc|salary|compensation|dob|birth|phone|mobile|whatsapp|aadhaar|passport|"
    r"bank|token|password|otp|secret|authorization",
    re.IGNORECASE,
)

#: Deleted outright wherever they appear, at any depth.
DROP = (
    "email", "contact_number", "contact_number_country_code", "address",
    "profile_pic", "profile_pic_url", "resume", "resume_url", "dob",
    "linkedin_id", "token", "guest_token", "access_token",
)


def scrub(node):
    """Delete DROP keys at every depth. Returns a new structure."""
    if isinstance(node, dict):
        return {k: scrub(v) for k, v in node.items() if k not in DROP}
    if isinstance(node, list):
        return [scrub(item) for item in node]
    return node


def suspicious_keys(node, trail="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            if SUSPICIOUS.search(key):
                yield "%s.%s" % (trail, key)
            yield from suspicious_keys(value, "%s.%s" % (trail, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from suspicious_keys(item, "%s[%d]" % (trail, index))


async def main() -> int:
    token = SessionStore().token()
    if not token:
        print("no session - run uplers_login first")
        return 1

    for _, path, _ in CAPTURES:
        assert path in ALLOWED, path

    client = TalentClient(SessionStore().token)
    async with client:
        for stem, path, params in CAPTURES:
            target = OUT_DIR / ("%s.json" % stem)
            try:
                body = await client.get_json(path, params)
            except Exception as exc:                      # noqa: BLE001
                print("%-26s FAILED  %s: %s" % (stem, type(exc).__name__, exc))
                continue

            clean = scrub(body)
            flagged = sorted(set(suspicious_keys(clean)))
            target.write_text(json.dumps(clean, indent=2, sort_keys=True), encoding="utf-8")
            print("%-26s %6d bytes  top=%s%s" % (
                stem,
                target.stat().st_size,
                sorted(clean)[:6] if isinstance(clean, dict) else type(clean).__name__,
                ("  SUSPICIOUS=%s" % flagged) if flagged else "",
            ))
    print("requests made: %d" % client.requests_made)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
