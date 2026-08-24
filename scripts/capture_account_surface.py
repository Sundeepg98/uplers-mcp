"""Capture the ACCOUNT-surface READ routes as fixtures, GET only.

Third in the line that starts at `capture_outreach.py` (the five routes behind
`uplers_agent_readthrough`) and continues at `capture_agent_surface.py` (the
Happpy Agent screens). This one steps OUT of the outreach namespace and takes
the account ring: who the platform thinks he is, what he has paid it, and which
of his mailboxes it believes are wired up.

THE ONE THAT MATTERS MOST is `talent/account/status`. The agent's own
`outreach-step` measured `linkedin_connected: false`, and
`_audit/2026-08-23-build-uplers.md` makes that the build's second headline: his
two-channel paid agent is running on one channel, and Uplers' own failure text
names it on 11 of 16 failed runs. `account/status` is the account screen's
SEPARATE reading of the same fact - census row 39 / G10, `res.data.data.{gmail,
linkedin}`. Two readings that agree promote a single measurement to a
corroborated one; two that disagree name a bug in one of them. Either answer is
worth one GET, which is the whole reason this script exists.

`talent/account/outreach-agent` is in NO prior inventory - not the browser
parity census, not the bundle call-site audit. It is captured to find out what
it is, and a 404 is as real a finding as a body.

WHY A GUARD RATHER THAN CARE - the same argument `capture_outreach.py` makes,
and leaving `talent/outreach/*` does not weaken it. `talent/account/*` is the
namespace where the connected-mailbox writes live, and the PAID agent acts on
what it finds there. A typo in this file is not a failed capture, it is an
unrequested change to a real account, and applying on Uplers cannot be undone
anywhere in their product. So the method is pinned to GET and the path to an
allowlist, in code, and a miss raises before the client is built.

`user/me` GETS EXTRA SCRUTINY, and is why the leak check is read here as a gate
rather than as a log line. The census calls it "the richest single response in
the bundle" - `profile_completion_percentage`, `userdata`, `data.enc_id`,
`data.login_provider_type`, `data.linkedin_id`, `snooze`,
`has_auto_fill_extension_installed`. A session-bootstrap route is exactly where
an address, a phone number or a resume URL lives, so its fixture is READ BY A
HUMAN before anything is committed, and a key the DROP/MASK lists do not know
about is a reason to delete the file, not to widen the lists in passing.

WHY A TRANSPORT THAT ONLY WATCHES. `get_json` returns a parsed body and nothing
else, so a 200, a 201 and a 204 are indistinguishable to its caller - and a
findings file that prints "HTTP 200" merely because a call returned is
asserting something it never measured. `_StatusRecorder` reads `status_code`
off the response as it passes and touches nothing else: not the method, not the
path, not the retry policy, not the body. It cannot make this script send
anything the allowlist did not already permit.

Rate discipline: his live session, one request at a time, with the client's own
inter-request delay left at the default rather than zeroed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from capture_outreach import leak_summary, write_fixture  # noqa: E402
from uplers_server.session import SessionStore  # noqa: E402
from uplers_server.talent import TalentClient  # noqa: E402

OUT_DIR = REPO / "tests" / "fixtures"

#: Where a real `HR_Number` is read from. Off disk rather than fetched, so the
#: capture makes no request it does not have to - the same rule
#: `an_outreach_hr_id` in `capture_agent_surface.py` follows.
HR_FIXTURES = (OUT_DIR / "talent_pipeline.json",)

#: (fixture stem, path, params). GET only - see the module docstring.
#: `None` params means the route takes none; a dict is sent as the query string.
CAPTURES = (
    # -- the corroborating reading. The reason this script exists. -----------
    #: NOTE THE STEM. `capture_agent_surface.py` captures this same route, and
    #: the two scripts briefly disagreed about its name: this one wrote
    #: `account_status.json` while the other wrote `talent_account_status.json`
    #: - two byte-identical files for one route, captured a day apart. RESOLVED
    #: 2026-08-24 in favour of the established, already-committed stem, and the
    #: redundant copy was deleted. One route, one fixture name: two scripts
    #: writing one route under two stems is a fixture that can go stale in one
    #: place and look fresh in the other.
    ("talent_account_status", "talent/account/status", None),

    #: In no prior inventory. Captured to learn what it is.
    ("account_outreach_agent", "talent/account/outreach-agent", None),

    # -- session bootstrap: the richest response, and the riskiest ------------
    ("user_me", "user/me", None),

    # -- the agent's own onboarding and template defaults ---------------------
    ("outreach_default_templates",
     "talent/outreach/default-auto-templates", None),
    ("outreach_onboard_jobs", "talent/outreach/onboard-jobs", None),

    # -- referral and marketing panels ---------------------------------------
    ("outreach_referral_list", "talent/outreach/referral-list", None),
    ("outreach_value_with_happy", "talent/outreach/value-with-happy", None),

    # -- what he has actually paid Uplers ------------------------------------
    ("payment_transactions", "talent/payment-transactions", None),
)

#: Routes needing a real `HR_Number`, filled in at runtime from a fixture
#: already on disk. Split out for the reason `PER_JOB` is split out in
#: `capture_agent_surface.py`: the params are not knowable at import time, but
#: the allowlist still has to cover the path.
PER_HR: tuple[tuple[str, str], ...] = (
    ("outreach_preview_config", "talent/outreach/preview-config"),
)

ALLOWED = {path for _, path, _ in CAPTURES} | {path for _, path in PER_HR}


class _StatusRecorder(httpx.AsyncHTTPTransport):
    """Remembers the HTTP status of every response, and changes nothing else.

    Reads `status_code` off the response object as it passes through. It does
    not touch the stream, so nothing downstream sees a consumed body, and it
    has no opinion about method or path.
    """

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[tuple[str, str, int]] = []

    async def handle_async_request(self, request):
        response = await super().handle_async_request(request)
        self.seen.append((request.method, request.url.path, response.status_code))
        return response

    def last_status(self) -> int | None:
        return self.seen[-1][2] if self.seen else None


def an_hr_number() -> str | None:
    """One `HR_Number` off a fixture already on disk, or None.

    Returns the id from the FIRST row that carries a non-empty one. Which row
    does not matter - the point is a real value in the right identifier space,
    and the census measured that `preview-config` wants exactly this column.
    Falls back to the per-requisition `HR*.json` fixtures, whose FILENAME is
    itself an HR_Number, if the pipeline fixture is missing or carries no rows.
    """
    def walk(node):
        if isinstance(node, dict):
            value = node.get("HR_Number")
            if value not in (None, "", 0):
                yield str(value)
            for item in node.values():
                yield from walk(item)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    for source in HR_FIXTURES:
        if not source.exists():
            continue
        found = next(walk(json.loads(source.read_text(encoding="utf-8"))), None)
        if found:
            return found

    for candidate in sorted(OUT_DIR.glob("HR*.json")):
        return candidate.stem
    return None


def envelope(body) -> str:
    """How this response spells `status`, and what its top level holds.

    This API is INCONSISTENT about it - some routes answer `{"status": 200}`
    with an integer and some answer `{"status": "success"}` with a string - and
    reading one idiom as the other has bitten this repo before. So the idiom is
    printed per route rather than assumed once for the bundle.
    """
    if not isinstance(body, dict):
        return "top-level %s, not an object" % type(body).__name__
    keys = ", ".join(sorted(body)) or "(none)"
    if "status" not in body:
        return "no top-level 'status' | keys: %s" % keys
    value = body["status"]
    return "status=%s(%r) | keys: %s" % (type(value).__name__, value, keys)


def key_paths(node, trail="$"):
    """Every distinct key PATH in the payload. Names only, never values.

    List indices collapse to `[]`, so a 90-row array reports the shape of one
    row rather than ninety copies of it, and the inventory stays bounded by the
    schema instead of by the account's data volume.

    Names only is the same discipline `leak_summary` follows, and for the same
    measured reason: a key called `whatsapp_number` is a schema fact worth
    writing down, while its value is the thing the redaction exists to keep off
    disk. This is what makes the inventory safe to print for a route whose
    fixture is about to be DELETED for leaking - which is exactly when somebody
    needs to know what was in it in order to extend DROP/MASK.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            here = "%s.%s" % (trail, key)
            yield here
            yield from key_paths(value, here)
    elif isinstance(node, list):
        for item in node:
            yield from key_paths(item, "%s[]" % trail)


def inventory(body) -> list[str]:
    """The RAW schema, each entry marked with what the redaction did to it.

    Taken off the body as Uplers sent it, not off the redacted copy, because
    the question a reviewer actually has is "what does this route carry" - and
    a key that `DROP` deletes is still a fact about the route even though it
    never reaches disk. `[DROP]` means the key was deleted outright, `[MASK]`
    that the key survived with a synthetic value, and an unmarked key survived
    untouched. So `user/me` reports which personal fields the existing lists
    already catch and, by omission, which ones they do not.

    THE VERDICT IS ASKED OF THE REDACTION, never re-derived from its lists.
    `redaction_of` folds camelCase onto snake_case, so a hand-rolled `leaf in
    DROP` here would under-report exactly the spelling that caused the
    2026-08-24 miss. An unmarked key can still have its VALUE rewritten - the
    credential-URL rule reads values, and a name-only inventory cannot show it.
    """
    from capture_outreach import redaction_of

    seen = []
    for path in key_paths(body):
        leaf = path.rsplit(".", 1)[-1].replace("[]", "")
        verdict = redaction_of(leaf)
        mark = (" [%s]" % verdict) if verdict else ""
        entry = "%s%s" % (path, mark)
        if entry not in seen:
            seen.append(entry)
    return seen


async def capture(client, recorder, stem, path, params) -> None:
    target = OUT_DIR / ("%s.json" % stem)
    try:
        body = await client.get_json(path, params)
    except Exception as exc:                              # noqa: BLE001
        print("%-28s HTTP %-5s FAILED  %s: %s" % (
            stem, recorder.last_status(), type(exc).__name__, exc))
        return

    # DELETE BEFORE REPORTING, and the order is load-bearing - which is why it
    # is no longer implemented here. This script got the ordering right and its
    # two siblings did not, so all three now share the ONE gate in
    # `capture_outreach.write_fixture`, which unlinks a leaking fixture before
    # it returns. Three copies of an invariant are three chances to lose it;
    # the incident that proved this one is written up in that docstring.
    #
    # Printing is the only step here that can fail for reasons unrelated to the
    # capture, and by the time any of it runs there is nothing left to strand.
    size, leaks = write_fixture(target, body)

    print("%-28s HTTP %-5s %7d bytes  %s" % (
        stem, recorder.last_status(), size,
        ("LEAKED (fixture deleted): %s" % leak_summary(leaks)) if leaks
        else "clean",
    ))
    print("    %s" % envelope(body))
    keys = inventory(body)
    print("    %d distinct key paths:" % len(keys))
    for entry in keys:
        print("      %s" % entry)
    if leaks:
        print("    ^ fix DROP/MASK in capture_outreach.py before re-running")


async def main() -> int:
    if not SessionStore().token():
        print("no session - run uplers_login first")
        return 1

    for _, path, _ in CAPTURES:
        assert path in ALLOWED, path
    for _, path in PER_HR:
        assert path in ALLOWED, path

    hr_number = an_hr_number()
    if hr_number is None:
        print("no HR_Number on disk - skipping %d per-requisition route(s)"
              % len(PER_HR))
    else:
        print("using HR_Number %s off a local fixture" % hr_number)

    recorder = _StatusRecorder()
    client = TalentClient(SessionStore().token, transport=recorder)
    async with client:
        for stem, path, params in CAPTURES:
            await capture(client, recorder, stem, path, params)
        if hr_number is not None:
            for stem, path in PER_HR:
                await capture(client, recorder, stem, path,
                              {"HR_Number": hr_number})

    print("requests made: %d" % client.requests_made)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
