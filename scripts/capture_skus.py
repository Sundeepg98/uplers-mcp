"""Capture the paid-SKU READ routes as fixtures, GET only.

Third in the family after `capture_outreach.py` and `capture_agent_surface.py`,
and it exists because a standing refusal was overturned by measurement rather
than by argument.

WHAT CHANGED. `uplers_server_info`'s `out_of_scope_by_design` refused
`talent/resume-health-check/*` and `talent/tailor/*` as "Uplers' own PAID
candidate products", and reasoned that wrapping them "would produce tools that
fail at runtime" because the account holds zero tailor credits. The first half
of that is still true - these ARE paid products and nothing here buys, orders,
transforms or refunds. The second half was wrong about READS: all three routes
below answered **HTTP 200 with real data on his live session on 2026-08-25**,
zero 403s, zero 402s. A credit balance gates the WRITE side; it does not gate
reading what he has already bought. The refusal stands for every ordering route
in those namespaces and is narrowed to exclude these three reads.

THREE ROUTES, ONE IDIOM. All three answer the INTEGER 200 - none of them is the
string-`"success"` odd one out that `get-message-templates` is. MEASURED, not
inferred: `outreach.unwrap` accepts both idioms and refuses everything else, and
it is imported rather than reimplemented for exactly the reason its docstring
gives.

WHY A GUARD RATHER THAN CARE - the argument `capture_outreach.py` makes, and it
binds here for a second reason on top of the first. The first is the namespace:
`get-last-health-check` lives under `talent/outreach/*`, one path segment from
`consent-email-job-scan`, a write that changes what Uplers reads out of his
mailbox. The second is COMMERCIAL: `talent/tailor/*` also contains
`order/create`, `order/capture` and `refund-request`. A typo here is not a
failed capture; it is an unrequested change to his account or an unrequested
charge against it. So the method is pinned to GET and the path to an allowlist,
in code, and a miss raises before the client is built.

THE PAYLOADS ARE THE MOST PERSONAL THIS REPO HAS CAPTURED, and that is not a
figure of speech. `get-last-health-check` returns Uplers' scoring report on his
resume: his name, his city, and whole bullets of his resume quoted back
verbatim inside the scoring commentary. It is deleted rather than scrubbed -
see `SKU_DROP` in `capture_outreach.py` for why the CONTAINER goes rather than
its leaves, and what that costs. Nothing here re-implements a scrubber; every
response goes through the shared `write_fixture`, so the leak gate runs and a
fixture that leaks is deleted before this script gets to report on it.

NOT CAPTURED, deliberately: every ordering, transforming and refunding route in
both namespaces. They have no constant in `uplers_server/endpoints.py` and no
entry here, because - as endpoints.py already says of the one-way outreach
routes - a constant is an invitation to call it.

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

#: (fixture stem, path, params). GET only - see the module docstring.
#: `None` params means the route takes none. All three take none: MEASURED, and
#: worth stating because two of them look like list endpoints that ought to
#: page and neither accepts a page parameter that changed anything.
CAPTURES = (
    #: CURRENT STATE. The last health check plus the transform that followed
    #: it, and the two attempt counters. MEASURED 2026-08-25: status 200 (INT),
    #: `is_eligible` false, `is_paid` false, `total_attempts` 5,
    #: `user_attempts` 3, `resume_score` 89, `final_verdict` the EMPTY STRING.
    ("sku_health_check_last", "talent/outreach/get-last-health-check", None),

    #: HISTORY, and the corroboration that makes the two attempt counters
    #: readable. MEASURED 2026-08-25: 3 rows, scores 89 / 89 / 87,
    #: `total_resume_health_check` 3 - which AGREES with `user_attempts` 3 on
    #: the route above and is what identifies that counter as the one that has
    #: been spent. `transformed` is the empty list and
    #: `total_resume_transformed` is 0.
    ("sku_health_check_dashboard", "talent/resume-health-check/dashboard", None),

    #: THE TAILOR SURFACE. MEASURED 2026-08-25: `total_tailored_resumes` 0,
    #: `total_records` 1, and the single `resumes_list` row is a SOURCE row
    #: (`list_type: "source"`, `tailored_resume: null`) - a base resume
    #: registered for tailoring, not a tailored output. `plan_details` reads
    #: `plan_active` 0 and `remaining_days` 0 against a `plan_end_date` of
    #: 2026-08-11, so the plan is expired.
    ("sku_tailor_list", "talent/tailor/list", None),
)

#: NOT FETCHED, NOT PROBED, AND NOT NAMED IN `endpoints.py`. Recorded here as
#: prose so nobody re-derives them from the namespace and believes this script
#: declined to capture them for a fixture-size reason. `talent/tailor/order/
#: create`, `order/capture` and `refund-request` alter a live paid
#: subscription; the transform arm spends an attempt. This slice is READS.
NOT_BUILT_COMMERCIAL = (
    "talent/tailor/order/*",
    "talent/tailor/refund-request",
    "talent/resume-health-check/* (every non-dashboard arm)",
)

ALLOWED = {path for _, path, _ in CAPTURES}


async def capture(client, stem, path, params) -> None:
    target = OUT_DIR / ("%s.json" % stem)
    try:
        body = await client.get_json(path, params)
    except Exception as exc:                              # noqa: BLE001
        print("%-30s FAILED  %s: %s" % (stem, type(exc).__name__, exc))
        return

    # `write_fixture` has ALREADY deleted the file if anything leaked - see its
    # docstring for the 2026-08-24 incident that moved the unlink in there.
    # Nothing below this line can strand a leaking fixture on disk, however it
    # fails.
    size, leaks = write_fixture(target, body)
    print("%-30s %6d bytes%s" % (
        stem, size,
        ("  LEAKED (fixture deleted): %s" % leak_summary(leaks))
        if leaks else "  clean",
    ))
    if leaks:
        print("  ^ fix DROP/MASK in capture_outreach.py before re-running")


async def main() -> int:
    if not SessionStore().token():
        print("no session - run uplers_login first")
        return 1

    for _, path, _ in CAPTURES:
        assert path in ALLOWED, path

    client = TalentClient(SessionStore().token)
    async with client:
        for stem, path, params in CAPTURES:
            await capture(client, stem, path, params)

    print("requests made: %d" % client.requests_made)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
