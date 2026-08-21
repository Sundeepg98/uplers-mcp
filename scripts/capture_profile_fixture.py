"""Capture `talent/profile` as a test fixture, with the private half removed.

Run against a live signed-in session. Produces
`tests/fixtures/talent_profile.json`: the REAL response shape, trimmed and
stripped, so the suite tests what Uplers actually sends rather than a shape
somebody invented.

Why this script exists at all. Every profile test in this suite used to build
its own payload, and every one of them wrote skills as ``[{"name": "Node.js"}]``
- a shape the live API has never once returned. 667 tests passed while the
extractor read zero skills off the real thing. A captured fixture is the only
kind that cannot drift from the API by being imagined.

TWO RULES, both enforced below rather than remembered:

1.  **The private half never lands on disk.** `DROP` names the keys carrying
    pay, contact details, identity documents and file URLs. They are DELETED,
    not masked, so `tests/test_talent_shape.py` can assert their absence and a
    future recapture cannot quietly reintroduce one. `assert_clean` re-reads
    the written file and fails loudly if anything slipped through.

2.  **`masters` is trimmed to the rows the profile references.** The live
    lookup carries 176,329 skills and would be a 40 MB fixture. Only the ids
    this profile actually cites are kept, plus a handful of decoys so a test
    can prove the resolver selects rather than takes whatever is first.
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

OUT = REPO / "tests" / "fixtures" / "talent_profile.json"

#: Deleted outright from the captured record. Pay, contact route, identity
#: document, home address, and every URL that resolves to a personal file.
DROP = (
    "current_ctc",
    "expected_ctc",
    "monthly_salary",
    "dob",
    "contact_number",
    "contact_number_country_code",
    "whatsapp_optin",
    "address",
    "email",
    "profile_pic",
    "profile_pic_url",
    "ra_profile_pic_url",
    "resume",
    "resume_url",
    "ra_resume_url",
    "repository_url",
    "ra_repository_url",
    "linkedin_id",
    "project_url",
    "gender",
)

#: Belt and braces over DROP: catches a key Uplers adds after this was written.
SUSPICIOUS = re.compile(
    r"ctc|salary|compensation|dob|birth|phone|mobile|contact|whatsapp|address|"
    r"email|profile_pic|resume|aadhaar|passport|bank|token|password|otp|secret",
    re.IGNORECASE,
)

#: Enough decoys that a resolver returning "the first row" cannot pass.
DECOY_SKILL_IDS = 40
DECOY_TOOL_IDS = 10


def strip(value):
    """Recursively delete every DROP key. Returns a new structure."""
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in DROP}
    if isinstance(value, list):
        return [strip(item) for item in value]
    return value


def cited_ids(rows, id_key) -> set:
    return {str(row.get(id_key)) for row in rows or [] if isinstance(row, dict)}


def trim_master(rows, wanted: set, decoys: int) -> list:
    """The cited rows, plus `decoys` uncited ones so selection is testable."""
    kept, spare = [], []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("value")) in wanted:
            kept.append(row)
        elif len(spare) < decoys:
            spare.append(row)
    return kept + spare


def assert_clean(path: Path) -> None:
    """Re-read what was written and refuse to leave a leak on disk."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    leaks = []

    def walk(node, trail=""):
        if isinstance(node, dict):
            for key, value in node.items():
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


async def main() -> int:
    store = SessionStore()
    if not store.token():
        print("No session. Run uplers_login() first.")
        return 1
    async with TalentClient(store.token) as client:
        payload = await client.get_json(endpoints.EP_PROFILE)

    details = payload.get("talent_details")
    masters = payload.get("masters") or {}
    if not isinstance(details, dict):
        print("Unexpected payload: no talent_details object.")
        return 2

    skill_ids = cited_ids(details.get("skills"), "skill_id") | cited_ids(
        details.get("primaryskills"), "skill_id"
    )
    tool_ids = cited_ids(details.get("tools"), "tool_id")

    captured = {
        "talent_details": strip(details),
        "masters": {
            "skills": trim_master(masters.get("skills"), skill_ids, DECOY_SKILL_IDS),
            "tools": trim_master(masters.get("tools"), tool_ids, DECOY_TOOL_IDS),
            "preferredMethodMaster": masters.get("preferredMethodMaster") or [],
            "preferredModes": masters.get("preferredModes") or [],
            "joiningMaster": masters.get("joiningMaster") or [],
        },
        "ai_generated_summary": payload.get("ai_generated_summary"),
        "recommandations": payload.get("recommandations") or [],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
    assert_clean(OUT)

    print("wrote %s (%.1f KB)" % (OUT, OUT.stat().st_size / 1024))
    print(
        "  skills=%d primaryskills=%d tools=%d | masters.skills=%d masters.tools=%d"
        % (
            len(captured["talent_details"].get("skills") or []),
            len(captured["talent_details"].get("primaryskills") or []),
            len(captured["talent_details"].get("tools") or []),
            len(captured["masters"]["skills"]),
            len(captured["masters"]["tools"]),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
