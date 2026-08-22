"""Capture HIS assessment record as a test fixture, private half removed.

Run against a live signed-in session. Produces, under `tests/fixtures/`:

    talent_assessments.json    GET  v2/assessments   (assessments HE has taken)

Sibling of `capture_talent_rows.py` and `capture_profile_fixture.py`, and
written for the reason spelled out at the top of the first: a fixture that is a
real capture cannot drift from the API by being imagined; one that is invented
tests only the imagination that wrote it. That is not a hypothetical here - 667
tests were once green against a profile shape the live API has never returned.

**Why this surface is worth a route of its own.** 99 of the 250 requisitions in
the local index carry a non-empty `assessments` array, so 40% of this board
gates you behind an AiInterview or a TestGorilla test. The catalogue already
reports what a job REQUIRES (`Opportunity.assessments_required`). Nothing
reported what he has already SAT. Those are different questions and only the
second one can tell him whether a required assessment is an obstacle or an
afternoon he has already spent.

The sanitisation rules are imported from `capture_talent_rows` rather than
restated, so a key added to DROP there protects this capture too.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture_talent_rows import write  # noqa: E402
from uplers_server import endpoints  # noqa: E402
from uplers_server.session import SessionStore  # noqa: E402
from uplers_server.talent import TalentClient  # noqa: E402


async def main() -> int:
    store = SessionStore()
    if not store.token():
        print("No session. Run uplers_login() first.")
        return 1

    async with TalentClient(store.token) as client:
        payload = await client.get_json(endpoints.EP_ASSESSMENTS, None)

    print("raw top-level type: %s" % type(payload).__name__)
    if isinstance(payload, dict):
        print("raw top-level keys: %s" % sorted(payload))
        rows = payload.get("data")
        print("data type: %s" % type(rows).__name__)
        if isinstance(rows, list):
            print("row count: %d" % len(rows))
            if rows and isinstance(rows[0], dict):
                print("row 0 keys: %s" % sorted(rows[0]))
                print(json.dumps(rows[0], indent=1)[:1500])

    write("talent_assessments", payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
