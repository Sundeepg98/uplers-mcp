"""Capture the agent-surface READ routes as fixtures, GET only.

Companion to `capture_outreach.py`, which captured the five routes behind
`uplers_agent_readthrough`. This one captures the NEXT ring: the reads a human
sees on the Happpy Agent screens that no tool reached, enumerated by the
browser-parity census (`_audit/_slices/_slice-browser-parity-census.md`).

THE ONE THAT MATTERS MOST is `recommended-jobs-meta-email`. The bundle analysis
(`_audit/_slices/_slice-consent-semantics.md`) found it is the route the UI
re-reads after granting the Gmail-scan consent, which makes its `has_consent`
the platform's own answer to "is the scan on right now". Every other reading of
that consent in this server is a downstream copy. Capturing it is what lets the
consent be READ before anything offers to write it.

WHY A GUARD RATHER THAN CARE - the same argument `capture_outreach.py` makes,
and it binds harder here. Every path below lives under `talent/outreach/*`,
which is the namespace of Uplers' PAID outreach-agent product, and two of its
siblings (`consent-email-job-scan`, `consent-auto-run`) are writes that change
what Uplers does on his behalf. A typo in this file is not a failed capture, it
is an unrequested change to his account. So the method is pinned to GET and the
path to an allowlist, in code, and a miss raises before the client is built.

NOT CAPTURED HERE, deliberately: `talent/talent-download-resume-profile`. It is
a GET and it is on the census list, but its 200 body is his actual resume as
base64 (`{blob, ext, filename}`). A fixture of it would be a copy of a personal
document sitting in a git repo. `probe_resume_snapshot.py` reads its SHAPE
without ever writing the bytes to disk.

Rate discipline: his live session, one request at a time, with the client's own
inter-request delay left at the default rather than zeroed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from capture_outreach import leak_summary, write_fixture  # noqa: E402
from uplers_server.session import SessionStore  # noqa: E402
from uplers_server.talent import TalentClient  # noqa: E402

OUT_DIR = REPO / "tests" / "fixtures"

#: The row whose ids the two per-job routes need. Read off a fixture this repo
#: already holds rather than re-fetched, so the capture makes no request it does
#: not have to.
ACTIVITY_FIXTURE = OUT_DIR / "outreach_tailor_activity.json"

#: (fixture stem, path, params). GET only - see the module docstring.
#: `None` params means the route takes none; a dict is sent as the query string.
#: A path of the form ("...", DISCOVER) has its params filled in at runtime.
CAPTURES = (
    # -- the consent read-back. The reason this script exists. ---------------
    ("outreach_meta_email", "talent/outreach/recommended-jobs-meta-email", None),

    #: THE JOBS THE SCAN FOUND. `meta_email` says the scan last ran and how many
    #: it holds; this is the list itself, and no tool in this server had it.
    #: `best_for_you` is omitted deliberately: unset returns ALL of them, and
    #: `true` returns the subset, so the wider capture is the one that pins the
    #: shape. MEASURED 2026-08-23: unset -> 79 rows, true -> 51 rows.
    ("outreach_scanned_jobs", "talent/outreach/recommended-jobs-email", None),

    # -- the reply-conversion surface ---------------------------------------
    ("outreach_followups_pending",
     "talent/outreach/missed-positive-reply-followups-pending", {"days": 15}),
    ("outreach_templates", "talent/outreach/get-message-templates", None),
    ("outreach_auto_reply", "talent/outreach/get-auto-reply", None),
    ("outreach_agent_meta", "talent/outreach/get-outreach-agent-meta", None),

    #: The automated follow-up config, per channel. This is the surface that
    #: decides whether an unanswered reply gets chased at all.
    ("outreach_settings_followup", "talent/outreach/settings/followup", None),

    # -- what the agent is asking HIM to do ---------------------------------
    ("outreach_external_pending",
     "talent/outreach/get-external-apply-pending-jobs", None),
    ("outreach_external_today", "talent/outreach/external-job-links-today", None),
    ("outreach_external_remaining",
     "talent/outreach/external-job-link-remaining", None),
    ("outreach_pending_action",
     "talent/outreach/has-pending-action-manual-outreach-agent", None),

    # -- settings a failed run named -----------------------------------------
    #: TWO DIFFERENT LISTS, and confusing them would misreport who is blocked.
    #: `settings/companies` is the alphabetical company PICKER, paginated at 20
    #: rows, where `IsActive` marks a chosen one. `settings/disabled-companies`
    #: is the actual blocklist and returned 16 rows. One of his 16 failed agent
    #: runs was "You blocked this company for outreach", so this is the route
    #: that names which.
    ("outreach_settings_companies", "talent/outreach/settings/companies", None),
    ("outreach_disabled_companies",
     "talent/outreach/settings/disabled-companies", None),

    # -- plan and account, with 18 days left on plan 2 -----------------------
    ("outreach_agent_plans", "talent/outreach/agent-plans", None),
    ("talent_account_status", "talent/account/status", None),
)

#: MEASURED 404, recorded so nobody re-derives them from the bundle inventory
#: and believes they are reachable. Both were listed as buildable GET reads by
#: the browser-parity census; both answered **HTTP 404** on 2026-08-23 with a
#: live session and a real `outreach_hr_id` taken off an `agent-tailor-activity`
#: row. A path that appears in the bundle is not a path the API serves.
#:
#: They are NOT retried. If a later slice wants them, the open question is the
#: parameter space, not the session: the ids were valid for every other route.
MEASURED_404 = (
    "talent/outreach/outreached-people",     # ?outreach_hr_id= -> 404
    "talent/outreach/get-employee-requests",  # ?outreach_hr_id= -> 404
)

#: FETCHED, then deliberately NOT kept as a fixture. `get-recommended-jobs` is
#: a real 200 returning 97 rows - Uplers' OWN board recommendations, which are a
#: different list from the mailbox scan above. Two measured reasons it is not
#: captured, both found by running it:
#:
#:   1. **It leaks other people.** 12 of the 97 `description` bodies contain a
#:      recruiter's email address inline in the job text. Those are third-party
#:      contact routes, and scrubbing inside free-text HTML is a different and
#:      much weaker guarantee than the key-based redaction this policy rests on.
#:   2. **It is 499 KB of near-duplicate.** This server already indexes all
#:      Uplers requisitions locally and ranks them with jobcore's scoring via
#:      `uplers_rank_opportunities`, so the marginal signal is small.
#:
#: `limit` is also accepted and IGNORED here - a `limit=3` request returned all
#: 97 rows - which is worth knowing before anyone builds paging on it.
FETCHED_NOT_KEPT = ("talent/outreach/get-recommended-jobs",)

#: Kept only so `an_outreach_hr_id` still has a caller-visible purpose if a
#: future per-job route is added. Empty today, by measurement.
PER_JOB: tuple[tuple[str, str], ...] = ()

ALLOWED = {path for _, path, _ in CAPTURES} | {path for _, path in PER_JOB}


def an_outreach_hr_id() -> str | None:
    """One `outreach_hr_id` off a fixture already on disk, or None.

    Returns the id from the FIRST row that carries a non-empty one. Which row
    does not matter - the point is a real value in the right identifier space,
    and the census measured that this column is the space these two routes want.
    """
    import json

    if not ACTIVITY_FIXTURE.exists():
        return None
    body = json.loads(ACTIVITY_FIXTURE.read_text(encoding="utf-8"))

    def walk(node):
        if isinstance(node, dict):
            value = node.get("outreach_hr_id")
            if value not in (None, "", 0):
                yield str(value)
            for item in node.values():
                yield from walk(item)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    return next(walk(body), None)


async def capture(client, stem, path, params) -> None:
    target = OUT_DIR / ("%s.json" % stem)
    try:
        body = await client.get_json(path, params)
    except Exception as exc:                              # noqa: BLE001
        print("%-30s FAILED  %s: %s" % (stem, type(exc).__name__, exc))
        return

    leaks = write_fixture(target, body)
    print("%-30s %6d bytes%s" % (
        stem, target.stat().st_size,
        ("  LEAKED: %s" % leak_summary(leaks)) if leaks else "  clean",
    ))
    if leaks:
        target.unlink()
        print("  ^ deleted; fix DROP/MASK in capture_outreach.py before re-running")


async def main() -> int:
    if not SessionStore().token():
        print("no session - run uplers_login first")
        return 1

    for _, path, _ in CAPTURES:
        assert path in ALLOWED, path
    for _, path in PER_JOB:
        assert path in ALLOWED, path

    hr_id = an_outreach_hr_id()
    if hr_id is None:
        print("no outreach_hr_id on disk - skipping the two per-job routes")

    client = TalentClient(SessionStore().token)
    async with client:
        for stem, path, params in CAPTURES:
            await capture(client, stem, path, params)
        if hr_id is not None:
            for stem, path in PER_JOB:
                await capture(client, stem, path, {"outreach_hr_id": hr_id})

    print("requests made: %d" % client.requests_made)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
