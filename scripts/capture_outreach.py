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

#: DELETED outright at any depth, so a test can assert their ABSENCE and a
#: future recapture cannot quietly reintroduce one. Pay, identity documents,
#: and every URL that resolves to a personal file.
DROP = (
    "current_ctc", "expected_ctc", "monthly_salary", "ctc_breakdown",
    "dob", "contact_number", "contact_number_country_code", "address",
    "email", "profile_pic", "profile_pic_url", "resume", "resume_url",
    "original_resume", "ra_resume_url", "ra_profile_pic_url",
    "ra_repository_url", "linkedin_id",
    "token", "guest_token", "access_token",
)

#: MASKED rather than dropped, and the difference is deliberate.
#:
#: `missed-positive-reply-followups` is the only route here that returns OTHER
#: PEOPLE - named humans at named companies, their business email, their
#: LinkedIn profile, and the words they wrote back. Deleting those keys would
#: make the fixture unable to test the shaper that exists to surface them, so
#: the KEY survives and the VALUE is replaced by a synthetic of the same shape.
#: Placeholders use the RFC 2606 reserved `.invalid` TLD, which can never
#: resolve, so a fixture that leaks into a request cannot reach anybody.
#:
#: `reply_category` is NOT masked: it is a platform-generated enum, not a
#: person's words, and it is the field the shaper actually reads.
#: `thread_subject` is likewise Uplers' own template output, not correspondence.
MASK = {
    "contact_display": "contact%d@example.invalid",
    "contact_value": "contact%d@example.invalid",
    "employee_business_email": "contact%d@example.invalid",
    "to_email": "contact%d@example.invalid",
    "from_email": "operator%d@example.invalid",
    "employee_linkedin_url": "https://www.linkedin.com/in/redacted-contact-%d",
    "employee_name": "Redacted Contact %d",
    "message_full": "Redacted reply body %d. The category field carries the meaning.",
    "reply_summary": "Redacted reply summary %d.",
    "gmail_thread_id": "redacted-thread-%d",
}

#: Proof the redaction worked, re-read off disk rather than off the object that
#: was written. Anything matching these outside the placeholder space is a leak.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LINKEDIN_PROFILE = re.compile(r"linkedin\.com/in/", re.IGNORECASE)
PLACEHOLDER_EMAIL = re.compile(r"^[a-z]+\d+@example\.invalid$")
PLACEHOLDER_LINKEDIN = re.compile(r"^https://www\.linkedin\.com/in/redacted-contact-\d+$")


def redact(node, counter=None):
    """Delete DROP keys and mask MASK keys, at any depth. Returns a new tree."""
    if counter is None:
        counter = {}
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in DROP:
                continue
            if key in MASK and isinstance(value, str) and value:
                counter[key] = counter.get(key, 0) + 1
                out[key] = MASK[key] % counter[key]
            else:
                out[key] = redact(value, counter)
        return out
    if isinstance(node, list):
        return [redact(item, counter) for item in node]
    return node


def strings(node, trail="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from strings(value, "%s.%s" % (trail, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from strings(item, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        yield (trail, node)


def contact_leaks(node):
    """Every string that still looks like a real contact route."""
    for trail, text in strings(node):
        if EMAIL.search(text) and not PLACEHOLDER_EMAIL.match(text):
            yield ("email", trail, text)
        elif LINKEDIN_PROFILE.search(text) and not PLACEHOLDER_LINKEDIN.match(text):
            yield ("linkedin", trail, text)


def suspicious_keys(node, trail="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            if SUSPICIOUS.search(key):
                yield "%s.%s" % (trail, key)
            yield from suspicious_keys(value, "%s.%s" % (trail, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from suspicious_keys(item, "%s[%d]" % (trail, index))


def write_fixture(target: Path, body) -> list:
    """Redact, write, then re-read and prove it. Returns the leaks found."""
    clean = redact(body)
    target.write_text(json.dumps(clean, indent=2, sort_keys=True), encoding="utf-8")
    reread = json.loads(target.read_text(encoding="utf-8"))
    return sorted(set(contact_leaks(reread))) + [
        ("suspicious-key", trail, "") for trail in sorted(set(suspicious_keys(reread)))
    ]


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

            leaks = write_fixture(target, body)
            print("%-26s %6d bytes%s" % (
                stem, target.stat().st_size,
                ("  LEAKED=%r" % leaks) if leaks else "  clean",
            ))
            if leaks:
                target.unlink()
                print("  ^ deleted; fix DROP/MASK before re-running")
    print("requests made: %d" % client.requests_made)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
