"""Probe `get-company-salary-data`. GET only, and it CAPTURES NOTHING.

NOT a capture script, and the difference is the point. Its four siblings in
this directory exist to write fixtures; this one exists to answer a question
that was asked wrongly, and it deliberately leaves nothing on disk. A fixture
for a route no tool reads is exactly the orphan problem
`uplers_server/conversion.py` was written to clear up, so this probe would have
manufactured two new orphans by running.

WHAT IT SETTLED, 2026-08-25, on his live session
=================================================
`uplers_salary_estimate` was designed against three premises recorded under
`EP_COMPANY_SALARY` in `uplers_server/endpoints.py`. Running this probe
contradicted all three, and the tool was STOPPED rather than adapted. The
corrected findings live beside that constant; the short version:

1. THE REFUSAL IS NOT AN HTTP 400. A row that fails Uplers' render gate answers
   **HTTP 200** with the body `{"status": 400, "errors": "No HR found.."}`.
   Nothing raises, no exception branch fires, and a client that only checked
   the HTTP status would read a refusal as a success. The recorded "answers
   400" was a BODY status all along.

2. THE SUCCESS ENVELOPE HAS NO `data` KEY. It is
   `{status, company_name, hr_id, salary_data{...}}` - the payload node sits at
   `salary_data`, at the top level. `uplers_server.outreach.unwrap` requires a
   `data` key by design (its rule 4 exists so an empty container can be told
   apart from a missing one), so it CANNOT read this route, and this server
   does not have a reader for it.

3. THE DATE-STRING ROWS ARE REFUSED IN PRACTICE, WHICH IS THE FINDING THAT
   MATTERS MOST. `is_partner_company` is polymorphic and the standing rule is
   to treat a truthy non-boolean as UNKNOWN rather than as "partner". That rule
   is right about what this server may CONCLUDE and wrong about what Uplers
   WILL DO: measured here, every local-index row - all of which carry a date
   string - was refused, and every live-feed row carrying a real boolean
   `false` was answered. Uplers' backend applies the same `!is_partner_company`
   truthiness their frontend does, so a date string behaves as "partner" on the
   wire.

   THE CONSEQUENCE FOR THE BRIEFED DESIGN: a tool that resolves `hr_number` to
   `row.id` against the LOCAL INDEX would be refused on every requisition it
   could name. 250 of 250 local rows carry a date string; 14 of 14 probed
   answered `status: 400`. That is not a tuning problem, it is the wrong
   source, and choosing a different one is a design decision rather than an
   adaptation.

RUN IT to reproduce any of the above. It prints a classification of both
populations and the verdict per probed row, and writes nothing anywhere.

THE GUARD IS THE SAME ONE THE CAPTURE SCRIPTS USE and it binds harder here
because this route is NOT in the `talent/*` namespace: it is a bare top-level
path whose neighbours include `find-similar-job` and `talent-matchmake`, both
POSTs that send his email address in the body. So the method is pinned to GET
and the path to an allowlist, in code, and a miss raises before the client is
built.

Rate discipline: one request at a time, `MAX_PROBES` a hard cap on each
population, and the client's own inter-request delay left at the default.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from uplers_server import assessment_flags, endpoints  # noqa: E402
from uplers_server.session import SessionStore  # noqa: E402
from uplers_server.store import Store  # noqa: E402
from uplers_server.talent import TalentClient, TalentError  # noqa: E402

#: The ONLY paths this probe may request. The feed is here because the whole
#: finding is a COMPARISON between two populations and one of them is only
#: reachable live; it is a plain read this server already makes.
ROUTE_SALARY = endpoints.EP_COMPANY_SALARY
ROUTE_FEED = endpoints.EP_OPPORTUNITIES
ALLOWED = {ROUTE_SALARY, ROUTE_FEED}

#: Hard cap per population.
MAX_PROBES = 8

#: Feed pages to classify. 50 rows each.
FEED_PAGES = (1, 2, 3)

FIELD_PARTNER = "is_partner_company"


def gate_half(raw: dict) -> tuple:
    """(cost_is_confidential, partner_state) - the two halves, read separately.

    `partner_state` comes from `assessment_flags.read_flag`, which is this
    repo's four-way classifier and whose own docstring names "the
    `is_partner_company` disease" as the case it was hardened for. Borrowed
    rather than copied: a second coercion table is how the two drift.
    """
    cost = raw.get("cost_string")
    confidential = isinstance(cost, str) and cost.strip().lower() == "confidential"
    return (confidential, assessment_flags.read_flag(raw, FIELD_PARTNER))


def verdict(body) -> str:
    """One line for what came back, naming the BODY status, never the HTTP one."""
    if not isinstance(body, dict):
        return "non-dict body: %s" % type(body).__name__
    status = body.get("status")
    if status != 200:
        return "body status=%r errors=%r" % (status, body.get("errors"))
    node = body.get("salary_data")
    if not isinstance(node, dict):
        return "body status=200 but no salary_data dict (keys: %s)" % sorted(body)
    return "body status=200 has_salary_data=%r company_matches=%r range=%s" % (
        node.get("has_salary_data"),
        node.get("company_matches"),
        json.dumps(node.get("company_salary_range")),
    )


def local_rows() -> list:
    """(label, hr_number, row_id, state) for local rows passing the cost half."""
    rows = []
    with Store() as store:
        for raw, _fetched_at in store.iter_records():
            hr_number = raw.get("HR_Number")
            row_id = raw.get("id")
            confidential, state = gate_half(raw)
            if not confidential or not isinstance(hr_number, str):
                continue
            if isinstance(row_id, bool) or not isinstance(row_id, int):
                continue
            rows.append(("local", hr_number, row_id, state))
    return sorted(rows, key=lambda row: row[1], reverse=True)


async def feed_rows(client) -> list:
    """(label, hr_number, row_id, state) for live feed rows passing the cost half."""
    seen = {}
    for page in FEED_PAGES:
        body = await client.get_json(
            ROUTE_FEED,
            {"pagination": 50, "page": page, "is_count": "0", "sort_field": "relevance"},
        )
        node = body.get("data") if isinstance(body.get("data"), dict) else body
        for raw in (((node or {}).get("hrs") or {}).get("data") or []):
            if isinstance(raw, dict) and isinstance(raw.get("id"), int):
                seen[raw["id"]] = raw

    rows = []
    for row_id, raw in seen.items():
        confidential, state = gate_half(raw)
        if confidential:
            rows.append(("feed", raw.get("HR_Number"), row_id, state))
    return rows


def classify(rows, label: str) -> None:
    counts = Counter(state for _label, _hr, _id, state in rows)
    print("%s rows passing the COST half of the gate: %d" % (label, len(rows)))
    for state, count in sorted(counts.items()):
        print("    %-14s %d" % (state, count))


async def main() -> int:
    if not SessionStore().token():
        print("no session - run uplers_login first")
        return 1

    for path in (ROUTE_SALARY, ROUTE_FEED):
        assert path in ALLOWED, path

    print("PROBE ONLY. Nothing is written to disk by this script.\n")

    client = TalentClient(SessionStore().token)
    async with client:
        local = local_rows()
        classify(local, "LOCAL INDEX")
        live = await feed_rows(client)
        classify(live, "LIVE FEED")
        print()

        for population in (local, live):
            probed = 0
            for label, hr_number, row_id, state in population:
                if probed >= MAX_PROBES:
                    break
                probed += 1
                try:
                    body = await client.get_json(ROUTE_SALARY, {"hr_id": row_id})
                except TalentError as exc:
                    print("%-6s %-20s id=%-8d partner=%-14s RAISED %s: %s"
                          % (label, hr_number, row_id, state,
                             type(exc).__name__, exc))
                    continue
                print("%-6s %-20s id=%-8d partner=%-14s %s"
                      % (label, hr_number, row_id, state, verdict(body)))
            print()

    print("requests made: %d" % client.requests_made)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
