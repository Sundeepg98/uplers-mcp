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


def normal_key(name: str) -> str:
    """One comparable spelling for a field name.

    `resumePath`, `resume_path`, `ResumePath` and `resume-path` are one field
    wearing four coats, and on 2026-08-24 the difference between two of them
    was the whole defect: `DROP` held exact snake_case names, Uplers answered
    camelCase, and a presigned resume URL walked straight through the gap.
    Folding the case and dropping the separators means every entry below names
    the FIELD rather than one of its spellings.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


#: DELETED outright at any depth, so a test can assert their ABSENCE and a
#: future recapture cannot quietly reintroduce one. Pay, identity documents,
#: and every URL that resolves to a personal file. Compared through
#: `normal_key`, so one entry covers every casing of the same field.
DROP = (
    "current_ctc", "expected_ctc", "monthly_salary", "ctc_breakdown",
    "dob", "contact_number", "contact_number_country_code", "address",
    "email", "profile_pic", "profile_pic_url", "resume", "resume_url",
    "original_resume", "original_resume_url", "ra_resume_url",
    "ra_profile_pic_url", "ra_repository_url", "linkedin_id",

    #: MEASURED 2026-08-24 on `talent/outreach/preview-config`, which answers
    #: `$.data.resumePath.url` - a 466-character presigned S3 URL. Naming it
    #: here is the cheap half of that fix and the half that generalises least:
    #: the rule that would have caught it with NO name at all is
    #: `is_credential_url`, below.
    "resume_path",

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

    # Added for `capture_agent_surface.py`. These are HIS OWN words and HIS OWN
    # mailbox rather than a third party's, which is why they are masked and not
    # dropped: a shaper that reports "a Gmail template exists" or "the follow-up
    # message is set" needs the KEY to survive, and needs nothing of the value.
    #
    # `gmail_email` is the connected mailbox address, echoed by three routes.
    # The templates and follow-up messages are multi-paragraph self-descriptions
    # carrying his employer history, his LinkedIn URL and his notice period.
    "gmail_email": "operator%d@example.invalid",
    "gmail_template": "<p>Redacted outreach template %d.</p>",
    "linkedin_template": "<p>Redacted outreach template %d.</p>",
    "message_gmail": "<p>Redacted follow-up message %d.</p>",
    "message_linkedin": "<p>Redacted follow-up message %d.</p>",
}

#: What the redaction actually consults. Derived once from the two lists above
#: so a spelling-insensitive lookup and a human-readable list cannot drift.
DROP_NORMAL = frozenset(normal_key(name) for name in DROP)
MASK_NORMAL = {normal_key(name): template for name, template in MASK.items()}


def redaction_of(name: str):
    """"DROP", "MASK" or None - what the redaction does to this field name.

    The one place that question is answered, so a capture script printing a
    key inventory reports what the redaction WILL do rather than what a
    second, hand-kept copy of the lists happens to believe.
    """
    folded = normal_key(name)
    if folded in DROP_NORMAL:
        return "DROP"
    if folded in MASK_NORMAL:
        return "MASK"
    return None


#: THE LOAD-BEARING HALF OF THE 2026-08-24 FIX, and the reason it reads the
#: VALUE instead of adding one more name to `DROP`.
#:
#: A presigned object-storage URL is not a reference to a document, it IS the
#: document: the signature in its query string is a bearer credential, so
#: whoever holds the string downloads the file until it expires. A key list can
#: only ever catch the names somebody already enumerated, and `resumePath` got
#: through precisely because nobody had - it was camelCase, and it kept its URL
#: one level down under `.url`. A rule that reads the value needs no
#: enumeration: it catches the next unnamed key on the day the API adds it.
#:
#: Two shapes count, and either alone is enough:
#:   * a SIGNATURE PARAMETER, which is unambiguous - a signed URL exists to be
#:     handed to somebody who is not authenticated;
#:   * an OBJECT-STORAGE HOST, because an unsigned URL into a bucket is still a
#:     direct address for a stored file, and `DROP` has said "every URL that
#:     resolves to a personal file" since it was written.
#:
#: The known cost of the host half: a company logo served out of S3 would be
#: masked too. That is a fixture losing a decoration, and it is worth it. As of
#: 2026-08-24 no tracked file in this repo matches either shape, so the rule
#: costs nothing already committed - measured, not assumed.
SIGNED_URL_PARAM = re.compile(
    r"[?&](?:X-Amz-Signature|X-Amz-Credential|X-Goog-Signature|"
    r"AWSAccessKeyId|GoogleAccessId)=",
    re.IGNORECASE,
)
OBJECT_STORE_HOST = re.compile(
    r"(?:^|//|\.)(?:"
    r"s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com"
    r"|storage\.googleapis\.com"
    r"|blob\.core\.windows\.net"
    r"|r2\.cloudflarestorage\.com"
    r"|[a-z0-9-]+\.digitaloceanspaces\.com"
    r")",
    re.IGNORECASE,
)

#: A value that is nothing but a URL. Free text that merely CONTAINS one is
#: deliberately not rewritten - see `contact_leaks` for why.
BARE_URL = re.compile(r"^\s*https?://\S+\s*$", re.IGNORECASE)

#: Resolves nowhere, by the same reserved-`.invalid` rule the contact
#: placeholders follow, and matches neither shape above so it cannot condemn
#: the fixture it was written into.
CREDENTIAL_URL_PLACEHOLDER = "https://redacted.invalid/object-%d"


def is_credential_url(text: str) -> bool:
    """True when `text` CONTAINS an address for a file in object storage."""
    return bool(SIGNED_URL_PARAM.search(text) or OBJECT_STORE_HOST.search(text))


def is_bare_credential_url(text: str) -> bool:
    """True when `text` IS such an address and nothing else."""
    return bool(BARE_URL.match(text)) and is_credential_url(text)


#: Proof the redaction worked, re-read off disk rather than off the object that
#: was written. Anything matching these outside the placeholder space is a leak.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
LINKEDIN_PROFILE = re.compile(r"linkedin\.com/in/", re.IGNORECASE)
PLACEHOLDER_EMAIL = re.compile(r"^[a-z]+\d+@example\.invalid$")
PLACEHOLDER_LINKEDIN = re.compile(r"^https://www\.linkedin\.com/in/redacted-contact-\d+$")


def redact(node, counter=None):
    """Three redaction layers at any depth. Returns a new tree.

      * a key naming a DROP field disappears;
      * a key naming a MASK field keeps its name and takes a synthetic value;
      * a STRING VALUE that is a presigned object-storage URL is replaced
        whatever key holds it, because there the credential IS the value and
        the key was never the thing worth trusting.

    The counter is shared across all three so each placeholder is numbered and
    two masked fields never collapse into one indistinguishable value. It is
    keyed by NORMALISED name; `$credential-url` cannot collide with one,
    because a normalised name holds only `[a-z0-9]`.
    """
    if counter is None:
        counter = {}
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            verdict = redaction_of(key)
            if verdict == "DROP":
                continue
            if verdict == "MASK" and isinstance(value, str) and value:
                folded = normal_key(key)
                counter[folded] = counter.get(folded, 0) + 1
                out[key] = MASK_NORMAL[folded] % counter[folded]
            else:
                out[key] = redact(value, counter)
        return out
    if isinstance(node, list):
        return [redact(item, counter) for item in node]
    if isinstance(node, str) and is_bare_credential_url(node):
        counter["$credential-url"] = counter.get("$credential-url", 0) + 1
        return CREDENTIAL_URL_PLACEHOLDER % counter["$credential-url"]
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
    """Every string that still looks like a real contact route or credential.

    `credential-url` is checked FIRST, and it fires on text that merely
    CONTAINS such a URL rather than only on text that is one. The asymmetry
    with `redact`, which rewrites only a bare URL, is deliberate: a presigned
    URL buried in an HTML description is a leak, but rewriting it would mean
    scrubbing inside free text - a much weaker guarantee than key-based
    redaction, and the exact reason `capture_agent_surface.py` refuses to
    capture `get-recommended-jobs` at all. So free text carrying a credential
    CONDEMNS the fixture instead of being half-cleaned.
    """
    for trail, text in strings(node):
        if is_credential_url(text):
            yield ("credential-url", trail, text)
        elif EMAIL.search(text) and not PLACEHOLDER_EMAIL.match(text):
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


def leak_summary(leaks) -> str:
    """Name WHERE each leak is, never WHAT it says.

    Two reasons this is not `%r` of the tuples. The obvious one: a leak report
    that prints the leaked value copies personal data into the console
    scrollback and every log that captures it, which is the thing the redaction
    exists to prevent. The measured one: on 2026-08-23 a captured template
    contained an emoji, and printing it raised `UnicodeEncodeError` on a cp1252
    console **part-way through the capture run**, so the routes after it were
    never fetched. A diagnostic that can abort the job it is diagnosing is a
    defect. The trail is what a human needs to fix `DROP`/`MASK` anyway.
    """
    return ", ".join(
        "%s at %s" % (kind, trail) for kind, trail, _ in sorted(leaks)
    )


def write_fixture(target: Path, body) -> tuple:
    """Redact, write, re-read to prove it - and DELETE the file if it leaked.

    Returns `(bytes_on_disk, leaks)`, so a caller can report both AFTER the
    dangerous file is already gone. THE DELETE LIVES HERE, and that is the fix
    rather than a tidy-up.

    It used to live in each caller, on the line BELOW the one that printed the
    verdict, and on 2026-08-24 that ordering cost a live leak: the output was
    piped through `head`, the pipe closed, and the `BrokenPipeError` landed
    inside the report print of a route that had leaked - so the `unlink()`
    under it never ran, and a fixture holding a real LinkedIn profile URL
    survived on disk until it was removed by hand. Python block-buffers to a
    pipe, so the writes kept succeeding long after the reader was gone and the
    failure surfaced at a flush, well past the point the file had been written.
    It was the SECOND firing of one ordering bug: `leak_summary` records a
    `UnicodeEncodeError` from an emoji on a cp1252 console the day before.

    Reporting is the only step in a capture that can fail for reasons having
    nothing to do with the capture, so nothing that can fail may sit between
    the leak verdict and the unlink. That is also why the size is measured
    BEFORE the scan runs rather than between the scan and the delete: it leaves
    only an `if` in between.
    """
    clean = redact(body)
    target.write_text(json.dumps(clean, indent=2, sort_keys=True), encoding="utf-8")
    size = target.stat().st_size
    reread = json.loads(target.read_text(encoding="utf-8"))
    leaks = sorted(set(contact_leaks(reread))) + [
        ("suspicious-key", trail, "") for trail in sorted(set(suspicious_keys(reread)))
    ]
    if leaks:
        target.unlink()
    return size, leaks


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

            # `write_fixture` has ALREADY deleted the file if anything leaked.
            # Nothing below this line can strand a leaking fixture on disk,
            # however it fails.
            size, leaks = write_fixture(target, body)
            print("%-26s %6d bytes%s" % (
                stem, size,
                ("  LEAKED (fixture deleted): %s" % leak_summary(leaks))
                if leaks else "  clean",
            ))
            if leaks:
                print("  ^ fix DROP/MASK before re-running")
    print("requests made: %d" % client.requests_made)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
