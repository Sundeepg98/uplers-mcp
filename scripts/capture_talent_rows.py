"""Capture the four AUTHENTICATED row surfaces as test fixtures, private half removed.

Run against a live signed-in session. Produces, under `tests/fixtures/`:

    talent_pipeline.json    GET  talent/hr/my-opportunities   (HIS applications)
    talent_feed.json        GET  talent/hr/opportunities      (his personal feed)
    talent_tailor.json      POST talent/hr/tailor-jobs        (Uplers' suggestions)
    talent_interviews.json  GET  talent/outreach/interview-list

Sibling of `capture_profile_fixture.py` and written for the same reason, one
level out. That script exists because every profile test built its own payload
and wrote skills in a shape the live API has never once returned - 667 tests
green while the extractor read zero skills off the real thing. The same thing
then happened to these four surfaces: each spells the job's title and company
DIFFERENTLY, and three of the four were shaped by a reader that only knew the
public catalogue's spelling. A fixture that is a real capture cannot drift from
the API by being imagined; one that is invented tests only the imagination that
wrote it.

The four differ from each other in exactly the way that matters, which is why
all four are captured rather than one being taken as representative:

    surface     job node        title              company
    catalogue   the row         RequestForTalent   CompanyName (top level)
    feed        the row         RequestForTalent   company.company_name
    pipeline    row["hr"]       hr.RequestForTalent hr.company.company_name
    tailor      the row         title              company (a bare STRING)

TWO RULES, enforced below rather than remembered - both copied from
`capture_profile_fixture.py`, because a pipeline row carries his pay:

1.  **The private half never lands on disk.** `DROP` names the keys carrying
    his expected pay, his fee, his account identifiers and his email address.
    They are DELETED, not masked, so a test can assert their absence and a
    future recapture cannot quietly reintroduce one. `assert_clean` re-reads
    each written file and refuses to leave a leak behind.

2.  **Rows are TRIMMED, not summarised.** Each fixture keeps whole rows,
    verbatim, and simply keeps fewer of them. Nothing is flattened, renamed or
    reordered, because the shape under test IS the nesting.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: THE SHARED REDACTION, and why this script now calls it instead of relying on
#: `strip` alone.
#:
#: MEASURED 2026-08-24. This file owns `talent_feed.json` and
#: `talent_pipeline.json`, and those two carry ALL THREE of the identity
#: findings that are live at HEAD - real people named in `company_pitch`. It
#: also carries `talent_id`, `enc_id`, `ta_id` and the `company_logo` signed
#: URLs. None of that was reachable by anything here: `strip` is an EXACT-NAME
#: key delete with no value rule at all, so it is the pre-2026-08-24
#: `capture_outreach` with the camelCase fix, the MASK layer, the
#: credential-URL rule and the opaque-handle rule all missing.
#:
#: Two redactions with different strength is not a redundancy, it is a hole
#: with a second copy of the rules in front of it. `strip` STAYS - it holds
#: this surface's own pay and recruiter-contact entries, argued in place below
#: - and the shared redaction now runs after it, so a rule added in
#: `capture_outreach.py` protects these four fixtures the day it lands rather
#: than the day somebody remembers this file exists.
from capture_outreach import contact_leaks, leak_summary  # noqa: E402
from capture_outreach import redact as shared_redact  # noqa: E402
from uplers_server import endpoints  # noqa: E402
from uplers_server.session import SessionStore  # noqa: E402
from uplers_server.talent import TalentClient  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"

#: Deleted outright from every captured record. His expected pay, the fee
#: Uplers quotes for him, the account identifiers that name him to their API,
#: and the mailbox address the interview scanner reports.
DROP = (
    "currenct_ctc",          # Uplers' own spelling; his current pay
    "current_ctc",
    "expected_ctc",
    "talent_expected_salary_in_usd",
    "talent_fee_expected_ctc",
    "hr_cost_dp_value",      # the same fee figure, under the job's prefix
    "nr_dp_margin",
    "TalentEncId",
    "gmail_email",
    "email",
    # The client's own point of contact, carried on `hr.detail`. Null in every
    # row of this capture, and DELETED rather than kept-as-null anyway: the
    # rule that survives a recapture is "the key is not in the fixture", not
    # "the key was empty the day somebody looked".
    "client_poc_email",
    "client_poc_name",
    "client_poc_designation",
    "client_poc_linkedin",
    "sales_poc_name",
    # `matcherArray.matcher[]` is the Uplers RECRUITER assigned to the job - a
    # third party's contact card, and the only third-party PII these four
    # surfaces carry. Their `Name` is kept (it is who to chase, and the product
    # shows it); every route to reach them personally is deleted.
    "profile_pic",
    "whatsapp_number",
    "skype_id",
    "linkedin_id",
)

#: Belt and braces over DROP: catches a key Uplers adds after this was written.
SUSPICIOUS = re.compile(
    r"ctc|salary|compensation|dob|birth|phone|mobile|contact|whatsapp|address|"
    r"email|profile_pic|resume|aadhaar|passport|bank|token|password|otp|secret",
    re.IGNORECASE,
)

#: `cost`, `cost_string` and `cost_range` are the JOB's published band, not his
#: pay, and the shaper's whole pay path is tested on them. SUSPICIOUS does not
#: match them, but `talent_fee_expected_ctc` and friends do - which is the
#: distinction being drawn: what the CLIENT pays is public, what HE earns is not.
#:
#: These two match SUSPICIOUS on the word "resume" and are integer FLAGS - "has
#: the video resume been shared with this client", "what state is it in" - not
#: the file, not a URL to it, and not anything that identifies him. Named here
#: with the reason rather than loosened out of the pattern, so the next key that
#: matches still has to be argued for.
#:
#: `consent_interview_email_scan` matches on "email" and is a CONSENT FLAG, not
#: an address - it is the field that explains why the interview list is empty,
#: so redacting it would delete the very thing the fixture exists to pin. The
#: address itself, `gmail_email`, is in DROP.
ALLOWED_SUSPICIOUS = frozenset(
    {"share_video_resume", "video_resume_status", "consent_interview_email_scan"}
)

#: Rows per fixture. Enough to cover the shape variation each surface shows and
#: few enough to read. The pipeline keeps all nine because nine IS his pipeline.
KEEP = {"feed": 3, "tailor": 5}


def strip(value):
    """Recursively delete every DROP key. Returns a new structure."""
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in DROP}
    if isinstance(value, list):
        return [strip(item) for item in value]
    return value


def assert_clean(path: Path) -> None:
    """Re-read what was written and refuse to leave a leak on disk.

    TWO detectors, because they cannot see each other's class. The key walker
    below sees a field that should not exist even when its value is null - a
    value scan is structurally blind to that. `contact_leaks` sees a real
    address, a personal LinkedIn URL, a credential URL, a sign-off name, a NANP
    phone or an opaque handle riding inside a link - none of which a key walker
    can reach, because none of them is a key.

    DELETE BEFORE REPORTING. Nothing that can fail may sit between the verdict
    and the unlink: on 2026-08-24 a `BrokenPipeError` inside a report print
    skipped an unlink in the sibling script and left a leaking fixture on disk.
    Both branches here unlink first and construct their message afterwards.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    leaks = []

    def walk(node, trail=""):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ALLOWED_SUSPICIOUS:
                    continue
                if key in DROP or SUSPICIOUS.search(key):
                    leaks.append("%s.%s" % (trail, key))
                walk(value, "%s.%s" % (trail, key))
        elif isinstance(node, list):
            for item in node:
                walk(item, trail + "[]")

    walk(data)
    if leaks:
        path.unlink()
        raise SystemExit("REFUSED: private keys survived capture: %s" % sorted(set(leaks)))

    values = sorted(set(contact_leaks(data)))
    if values:
        path.unlink()
        # `leak_summary` names WHERE, never WHAT: a report that prints the leak
        # has merely moved it into the console scrollback and every log that
        # captures that.
        raise SystemExit("REFUSED: leaking values survived capture: %s"
                         % leak_summary(values))


def write(name: str, payload) -> None:
    path = FIXTURES / (name + ".json")
    path.write_text(
        json.dumps(shared_redact(strip(payload)), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert_clean(path)
    print("wrote %s" % path)


def trim_paginator(payload: dict, keep: int | None) -> dict:
    """Keep `keep` rows of a Laravel paginator, leaving its meta untouched.

    The meta is deliberately NOT adjusted to match: `total` and `last_page`
    describing more rows than `data` carries is exactly what page 1 of a real
    paginator looks like, and the reader is supposed to survive it.
    """
    out = dict(payload)
    envelope = dict(out.get("hrs") or {})
    rows = envelope.get("data") or []
    if keep is not None:
        envelope["data"] = rows[:keep]
    out["hrs"] = envelope
    return out


async def main() -> int:
    store = SessionStore()
    if not store.token():
        print("No session. Run uplers_login() first.")
        return 1

    async with TalentClient(store.token) as client:
        pipeline = await client.get_json(
            endpoints.EP_MY_OPPORTUNITIES, {"pagination": 10, "page": 1}
        )
        feed = await client.get_json(
            endpoints.EP_OPPORTUNITIES, {"page": 1, "pagination": 3, "sortBy": "relevance"}
        )
        tailor = await client.post_json(endpoints.EP_TAILOR_JOBS, {})
        interviews = await client.get_json(endpoints.EP_INTERVIEW_LIST, {"detailed": "true"})

    write("talent_pipeline", trim_paginator(pipeline, None))
    write("talent_feed", trim_paginator(feed, KEEP["feed"]))
    tailor_out = dict(tailor)
    tailor_out["data"] = (tailor.get("data") or [])[: KEEP["tailor"]]
    write("talent_tailor", tailor_out)
    write("talent_interviews", interviews)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
