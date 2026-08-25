"""The two writes that are NOT reversible settings switches.

`test_outreach_write.py` covers the four that CAN be put back and says so in
its first line. These two cannot be filed beside them:

  * `uplers_revoke_email_scan` withdraws Uplers' standing permission to read a
    mailbox. Reversible on their side, but a PERMISSION rather than a setting,
    and re-granting starts a fresh scan rather than resuming the stopped one.
  * `uplers_submit_interview_feedback` is ONE-WAY. No edit route, no delete
    route, complete negative search. Nothing in this repo can take it back.

FIVE GUARDS PER TOOL, AND EVERY ONE HAS A CONTROL THAT FAILS WITH THE GUARD
REMOVED. The controls are not decoration here: a `writes(calls) == []`
assertion is trivially true when no request was made at all, and a `not in`
leak check passes happily against an empty result, so each is paired with a
planted case proving it can see the thing it claims to be watching.

THE THREE PROPERTIES SPECIFIC TO THIS FILE
-------------------------------------------
1.  **The exact KEY SET of the interview-feedback body**, asserted as a set
    equality rather than a membership check, so a third key added by a later
    edit fails loudly. It is a route that cannot be un-sent; a body nobody
    previewed with that key in it is the failure worth designing against.
2.  **The consent DELETE has no body, no params and no path segment.** The URL
    is the entire request, so the assertion is about what did NOT go with it.
3.  **THE MAILBOX ADDRESS.** The consent DELETE's own response carries
    `gmail_email`, and `outreach_write` returns its senders' responses
    verbatim. Copying that here would have printed his address into a
    transcript as a side effect of a call about consent. `consent_write.scrub`
    closes it and two tests here plant the address to prove they would see it.

NO NETWORK. Every request goes through httpx.MockTransport, every payload is
synthetic, and `isolated_snapshots` is autouse so a test cannot write a restore
point into the real data directory by forgetting a fixture. NO WRITE HAS EVER
BEEN FIRED against the operator's account by anything in this file or the
module it tests.
"""

from __future__ import annotations

import json

import httpx
import pytest

import server as server_mod
from conftest import make_transport
from uplers_server import consent_write, endpoints, outreach_write
from uplers_server.profile_write import WriteRefused
from uplers_server.talent import TalentClient

CONSENT_READ_PATH = "/api/" + endpoints.EP_OUTREACH_META_EMAIL
CONSENT_WRITE_PATH = "/api/" + endpoints.EP_CONSENT_EMAIL_JOB_SCAN
INTERVIEWS_PATH = "/api/" + endpoints.EP_INTERVIEW_LIST
FEEDBACK_PATH = "/api/" + endpoints.EP_INTERVIEW_FEEDBACK

TOKEN = "42|bearer-token-that-must-never-be-printed"

#: SYNTHETIC. Every "the address did not leak" assertion checks for this
#: string, so a regression prints an invented address into a test log rather
#: than his. Never the value in tests/fixtures/outreach_meta_email.json.
LIVE_MAILBOX = "a-very-distinctive-mailbox@example.invalid"

#: The caller's own review text. Guard 2 says caller-supplied text is echoed
#: verbatim, so this string is asserted PRESENT in the preview - the opposite
#: direction from the mailbox address above, and the difference is provenance.
CALLER_FEEDBACK = "CALLER-SUPPLIED-REVIEW-TEXT: the loop ran long but was fair."


# --- wiring ----------------------------------------------------------------
#
# Local rather than imported from test_outreach_write, for the reason that file
# gives for its own copy: the orchestrators take a client as an argument
# instead of building one, so there is nothing to monkeypatch and a small local
# factory is a smaller thing to keep working than a cross-file import.


def client_over(handler):
    """(TalentClient, calls) over a MockTransport. `calls` is the risk surface."""
    transport, calls = make_transport(handler)
    return TalentClient(lambda: TOKEN, transport=transport, delay=0), calls


def writes(calls):
    """Every request that was not a read. A write tool's whole risk surface."""
    return [call for call in calls if call.method != "GET"]


class Recorder:
    """A sender that records and never sends.

    `on_send` runs AT SEND TIME, which is how snapshot-before is proved. An
    assertion made after the orchestrator returns cannot tell "written first"
    from "written afterwards", and on these two routes that ordering is the
    only thing separating a restore point from a record of what replaced it.

    `takes_body=False` is the consent DELETE's shape: its sender is called with
    NO arguments at all, because the route has no body and no path segment. A
    Recorder that accepted one would let a body-carrying regression through.
    """

    def __init__(self, response=None, on_send=None, takes_body=True,
                 path=None, method=None):
        self.calls = []
        self._response = response if response is not None else {"status": 200, "data": {}}
        self._on_send = on_send
        self._takes_body = takes_body
        # A real sender carries the route it would hit, so a preview can print
        # the endpoint without the orchestrator holding the constant. A
        # Recorder without these would make `endpoint: None` look like the
        # normal case and hide a wrapper that forgot to supply the route.
        self.path = path if path is not None else (
            endpoints.EP_INTERVIEW_FEEDBACK if takes_body
            else endpoints.EP_CONSENT_EMAIL_JOB_SCAN
        )
        self.method = method if method is not None else (
            "POST application/json" if takes_body else "DELETE"
        )

    async def __call__(self, *args):
        if self._takes_body:
            assert len(args) == 1, "this sender takes exactly one body argument"
            payload = args[0]
        else:
            assert args == (), (
                "the consent DELETE sender must be called with NO arguments - "
                "the route has no body and no path segment. Got %r" % (args,)
            )
            payload = None
        if self._on_send is not None:
            self._on_send(payload)
        self.calls.append(payload)
        return self._response


# --- payload builders ------------------------------------------------------


def consent_payload(
    has_consent=True,
    gmail_connected=True,
    total_jobs=77,
    last_job_scan="2026-08-24 06:58:17",
    granted_at="2026-08-12 01:32:36",
    gmail_email=LIVE_MAILBOX,
):
    """`recommended-jobs-meta-email`, in the MEASURED shape.

    Defaults are the 2026-08-24 measurement this module was built against:
    consent ON, 77 jobs, LinkedIn 77 and every other board 0. The committed
    fixture is the 2026-08-23 capture and reads 79 - one scan earlier, same
    shape. Neither number is asserted on as a fact about the account; they are
    here so the SHAPE is realistic, and every guard reads the live value.
    """
    data = {
        "has_consent": has_consent,
        "consent_email_job_scan": granted_at,
        "gmail_connected": gmail_connected,
        "gmail_email": gmail_email,
        "last_job_scan": last_job_scan,
        "total_jobs": total_jobs,
        "breakdown": {
            "glassdoor": 0,
            "hirist": 0,
            "indeed": 0,
            "linkedin": total_jobs,
            "naukri": 0,
            "wellfound": 0,
        },
    }
    if has_consent is None:
        del data["has_consent"]
    return {"status": 200, "message": "ok", "data": data}


def interviews_payload(rows=(), has_consent=False, gmail_connected=True):
    """`interview-list?detailed=true`. MEASURED default: ZERO rows.

    The empty default is the account's real state and is deliberately what a
    test gets unless it says otherwise - the tool's most common outcome today
    is a refusal, and a suite whose default is a populated list would exercise
    the rare path as though it were the normal one.
    """
    return {
        "status": "success",
        "message": "Interview List",
        "data": list(rows),
        "meta": {
            "consent_interview_email_scan": None,
            "gmail_connected": gmail_connected,
            "has_consent": has_consent,
        },
    }


def interview_row(company_id=41, name="Oteemo", role="Full Stack Engineer",
                  feedback=None):
    return {
        "company_id": company_id,
        "company_name": name,
        "RequestForTalent": role,
        "feedback": feedback,
        "status": "Completed",
    }


def by_path(bodies, fallback=None):
    """Answer each request from `bodies`, keyed by url path."""

    def handler(request):
        for path, body in bodies.items():
            if request.url.path == path:
                value = body(request) if callable(body) else body
                return httpx.Response(200, json=value)
        if fallback is None:
            return httpx.Response(404, json={"message": "no stub for %s" % request.url.path})
        return httpx.Response(200, json=fallback)

    return handler


@pytest.fixture(autouse=True)
def isolated_snapshots(monkeypatch, tmp_path):
    """Snapshots go to tmp_path. Autouse: a test must not be able to write a
    copy of a real record into the operator's data directory by forgetting a
    fixture. Patched on `outreach_write` because that is where the snapshot
    writer lives - `consent_write` inherits it rather than owning a fourth
    copy, and patching a name this module does not define would silently miss.
    """
    directory = tmp_path / "outreach_snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(outreach_write, "snapshots_dir", lambda: directory)
    return directory


# ==========================================================================
# The sender seam. Neither orchestrator can reach the wire without one.
# ==========================================================================


class TestTheSenderSeam:

    async def test_the_revoke_refuses_with_no_sender(self):
        """GUARD: no sender, no write. Checked BEFORE anything is snapshotted.

        The seam is what makes "no write happened" a claim about CONTROL FLOW
        rather than about what a mock transport happened to see. Without it the
        only evidence would be a mock that recorded nothing, which is equally
        consistent with a request going somewhere the mock was not watching.
        """
        client, calls = client_over(by_path({CONSENT_READ_PATH: consent_payload()}))

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await consent_write.revoke_email_scan(client, confirm=True, send=None)

        assert "no sender" in str(excinfo.value)
        assert writes(calls) == []

    async def test_the_feedback_refuses_with_no_sender(self):
        client, calls = client_over(
            by_path({INTERVIEWS_PATH: interviews_payload([interview_row()])})
        )

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await consent_write.submit_interview_feedback(
                    client, 41, CALLER_FEEDBACK, confirm=True, send=None
                )

        assert "no sender" in str(excinfo.value)
        assert writes(calls) == []

    async def test_no_sender_refuses_before_a_snapshot_is_written(
        self, isolated_snapshots
    ):
        """ORDERING, not just existence. The refusal lands before disk is touched.

        A call that could never have sent anything must leave nothing behind.
        If the sender check ran after the snapshot, every no-sender call would
        litter a restore point for a write that never happened - and on the
        feedback tool those files are the only local record of anything, so a
        directory full of phantoms is a directory nobody can read.
        """
        client, _ = client_over(
            by_path({INTERVIEWS_PATH: interviews_payload([interview_row()])})
        )

        async with client:
            with pytest.raises(WriteRefused):
                await consent_write.submit_interview_feedback(
                    client, 41, CALLER_FEEDBACK, confirm=True, send=None
                )

        assert list(isolated_snapshots.glob("*.json")) == []

    def test_a_delete_sender_cannot_be_built_from_an_item_url(self):
        """The MIRROR IMAGE of outreach_write.delete_sender_for's guard.

        That one refuses a path with NO `{id}`, because the blocklist's
        collection URL and item URL differ by one segment and a DELETE aimed at
        the collection is not an unblock. This route has no item URL at all, so
        the refusal runs the other way: a template carrying a placeholder is
        another route's constant arriving by copy-paste, and it is refused at
        CONSTRUCTION - which is stronger than checking at send time, because
        such a sender cannot be built to be called later.
        """
        with pytest.raises(WriteRefused) as excinfo:
            consent_write.bare_delete_sender_for(
                object(), endpoints.EP_OUTREACH_DISABLED_COMPANY_DELETE
            )

        assert "placeholder" in str(excinfo.value)

    def test_the_real_constant_builds_a_sender_that_carries_the_route(self):
        """__CONTROL for the refusal above. A guard that refuses EVERYTHING is
        indistinguishable from a broken constructor, so the allowed case is
        proven to still produce a usable sender."""
        send = consent_write.bare_delete_sender_for(
            object(), endpoints.EP_CONSENT_EMAIL_JOB_SCAN
        )

        assert send.path == endpoints.EP_CONSENT_EMAIL_JOB_SCAN
        assert send.method == "DELETE"


# ==========================================================================
# A. uplers_revoke_email_scan
# ==========================================================================


class TestRevokeEmailScan:

    async def test_it_reads_the_live_consent_before_anything_else(self):
        """GUARD 1: read-live. The authoritative route, and only that one.

        Asserted as an EXACT route rather than "a GET happened", because the
        dangerous mistake in this area is not a missing read - it is reading
        the WRONG consent. `interview-list -> meta.has_consent` is a different
        flag wearing the identical field name, and a revoke gated on it would
        fire against a `has_consent: false` that has nothing to do with this
        route.
        """
        client, calls = client_over(by_path({CONSENT_READ_PATH: consent_payload()}))

        async with client:
            result = await consent_write.revoke_email_scan(client, confirm=False)

        assert [call.url.path for call in calls] == [CONSENT_READ_PATH]
        assert result["current"]["has_consent"] is True
        assert result["performed"] is False

    async def test_the_preview_sends_nothing_and_shows_an_empty_body(self):
        """GUARD 2: exact-body, on a route whose body is genuinely nothing.

        `body_keys == []` is the assertion that matters. This DELETE carries no
        body, no query string and no path segment - VERIFIED, Uplers' own
        helper is a bare `delete(url)` - so a body key appearing here later
        means somebody invented a parameter the route was never measured to
        take.
        """
        client, calls = client_over(by_path({CONSENT_READ_PATH: consent_payload()}))
        recorder = Recorder(takes_body=False)

        async with client:
            result = await consent_write.revoke_email_scan(
                client, confirm=False, send=recorder
            )

        assert result["performed"] is False
        assert result["body"] == {}
        assert result["body_keys"] == []
        assert result["path_id"] is None
        assert result["method"] == "DELETE"
        assert result["endpoint"] == endpoints.EP_CONSENT_EMAIL_JOB_SCAN
        assert result["snapshot"] == {"written": False}
        # Both seams agree that nothing was sent.
        assert recorder.calls == []
        assert writes(calls) == []

    async def test_the_preview_states_the_three_things_it_does_not_do(self):
        """The whole decision, in the preview, in Uplers' own words.

        These three facts are why the tool exists in this shape rather than as
        a one-line wrapper: a reader deciding whether to revoke needs to know
        that it does not reach backwards, does not remove what was ingested,
        and does not disconnect the mailbox. A preview that omitted them would
        be technically exact and practically misleading.
        """
        client, _ = client_over(by_path({CONSENT_READ_PATH: consent_payload()}))

        async with client:
            result = await consent_write.revoke_email_scan(client, confirm=False)

        blob = " ".join(result["notes"])
        assert "will no longer scan your job board alert emails" in blob
        assert "NO ROUTE ANYWHERE DELETES ALREADY-INGESTED SCAN DATA" in blob
        assert "DOES NOT DISCONNECT GMAIL" in blob
        assert "talent/account/gmail/disconnect" in blob
        assert result["reversible"] is True
        assert "fresh scan" in " ".join(result["notes"]).lower() or "FRESH" in blob

    async def test_it_refuses_when_the_scan_is_already_off(self):
        """GUARD 4: empty-refusal. Nothing to revoke, so nothing is sent.

        Uplers' own UI cannot reach this button in that state either - their
        revoke handler is gated on `has_consent` already being true - so this
        mirrors their gate rather than inventing a stricter one.
        """
        client, calls = client_over(
            by_path({CONSENT_READ_PATH: consent_payload(has_consent=False)})
        )
        recorder = Recorder(takes_body=False)

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await consent_write.revoke_email_scan(
                    client, confirm=True, send=recorder
                )

        message = str(excinfo.value)
        assert "ALREADY OFF" in message
        assert "Nothing was sent" in message
        assert recorder.calls == []
        assert writes(calls) == []

    async def test_a_missing_consent_field_refuses_and_is_not_read_as_off(self):
        """`None` is not `False`, and the difference decides whether to write.

        A payload that did not carry `has_consent` has not said the scan is
        off. Defaulting it to off would make guard 4 refuse for the wrong
        reason - which is harmless here - but defaulting it to ON would fire a
        DELETE on no evidence, and a tri-state that collapses is one edit from
        collapsing the other way.
        """
        client, calls = client_over(
            by_path({CONSENT_READ_PATH: consent_payload(has_consent=None)})
        )

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await consent_write.revoke_email_scan(
                    client, confirm=True, send=Recorder(takes_body=False)
                )

        assert "UNKNOWN" in str(excinfo.value)
        assert writes(calls) == []

    async def test_the_snapshot_is_on_disk_before_the_send(self, isolated_snapshots):
        """GUARD 3: snapshot-before, asserted from INSIDE the sender.

        Ordering is the property, not existence. This route's read-back returns
        whatever is current, so a snapshot taken after the DELETE would record
        the revoked state and nothing about what was given up.
        """
        seen = {}

        def at_send_time(_payload):
            seen["files"] = sorted(p.name for p in isolated_snapshots.glob("*.json"))

        client, _ = client_over(
            by_path(
                {
                    CONSENT_READ_PATH: _consent_then_revoked(),
                    CONSENT_WRITE_PATH: {"status": 200, "data": {}},
                }
            )
        )
        recorder = Recorder(on_send=at_send_time, takes_body=False)

        async with client:
            result = await consent_write.revoke_email_scan(
                client, confirm=True, send=recorder
            )

        assert len(seen["files"]) == 1, seen
        assert result["snapshot"]["written"] is True
        assert "scan-consent" in result["snapshot"]["snapshot_id"]

    async def test_the_snapshot_records_the_state_and_says_it_is_not_an_undo(
        self, isolated_snapshots
    ):
        """The file holds what was given up; the undo is a ROUTE, not the file.

        Saying so matters more here than on a settings write. Every other
        snapshot in this server can be replayed back through the tool that
        wrote it. This one cannot: re-granting is a POST that starts a fresh
        scan, and a reader who assumed the file was a restore point would think
        they had an undo they do not have.
        """
        client, _ = client_over(
            by_path(
                {
                    CONSENT_READ_PATH: _consent_then_revoked(),
                    CONSENT_WRITE_PATH: {"status": 200, "data": {}},
                }
            )
        )

        async with client:
            result = await consent_write.revoke_email_scan(
                client, confirm=True, send=Recorder(takes_body=False)
            )

        assert "not a value that can be put back" in result["snapshot_is_not_an_undo"]
        assert "POST" in result["reverse_with"]

        written = json.loads(
            next(isolated_snapshots.glob("*.json")).read_text(encoding="utf-8")
        )
        assert written["record"]["has_consent"] is True
        assert written["record"]["total_jobs"] == 77
        # Even the file on disk does not carry the address.
        assert LIVE_MAILBOX not in json.dumps(written)

    async def test_it_re_reads_and_reports_that_the_revoke_landed(self):
        """GUARD 5, and this server does MORE here than Uplers' own client.

        VERIFIED in their bundle: the revoke path patches local state and never
        refetches, and the DELETE's response carries `{gmail_connected,
        gmail_email}` with no `has_consent` in it at all. So there is no field
        in the reply that could confirm this, and the extra GET is the only
        evidence that exists.
        """
        client, calls = client_over(
            by_path(
                {
                    CONSENT_READ_PATH: _consent_then_revoked(),
                    CONSENT_WRITE_PATH: {"status": 200, "data": {}},
                }
            )
        )

        async with client:
            result = await consent_write.revoke_email_scan(
                client, confirm=True, send=Recorder(takes_body=False)
            )

        assert result["performed"] is True
        assert result["verified"]["re_read"] is True
        assert result["verified"]["landed"] is True
        assert result["verified"]["has_consent_now"] is False
        # Two reads: the pre-flight and the verification.
        assert [c.url.path for c in calls] == [CONSENT_READ_PATH, CONSENT_READ_PATH]

    async def test_a_200_that_did_not_move_the_value_reports_landed_false(self):
        """__CONTROL for guard 5. A 200 IS NOT PROOF THE VALUE CHANGED.

        Without this, `landed: True` could be a constant. The route accepts the
        request, answers 200, and the consent still reads true - which must
        report as NOT landed rather than as success.
        """
        client, _ = client_over(
            by_path(
                {
                    CONSENT_READ_PATH: consent_payload(has_consent=True),
                    CONSENT_WRITE_PATH: {"status": 200, "data": {}},
                }
            )
        )

        async with client:
            result = await consent_write.revoke_email_scan(
                client, confirm=True, send=Recorder(takes_body=False)
            )

        assert result["verified"]["landed"] is False
        assert "DID NOT LAND" in result["verified"]["note"]

    async def test_a_failed_read_back_reports_unknown_and_never_no(self):
        """The write already happened. `landed: None` is the honest answer.

        Turning a failed verification into an exception would throw away the
        one fact the caller most needs - that something WAS sent - and reporting
        it as `False` would assert the revoke failed when nobody knows.
        """
        state = {"n": 0}

        def read(_request):
            state["n"] += 1
            if state["n"] == 1:
                return consent_payload(has_consent=True)
            return {"status": 500, "message": "upstream exploded"}

        client, _ = client_over(
            by_path({CONSENT_READ_PATH: read, CONSENT_WRITE_PATH: {"status": 200}})
        )

        async with client:
            result = await consent_write.revoke_email_scan(
                client, confirm=True, send=Recorder(takes_body=False)
            )

        assert result["performed"] is True
        assert result["verified"]["re_read"] is False
        assert result["verified"]["landed"] is None
        assert "UNKNOWN" in result["verified"]["note"]

    async def test_the_mailbox_address_never_reaches_the_result(self):
        """THE LEAK THIS MODULE HAD TO CLOSE, in both directions at once.

        The address is in the READ payload and in the DELETE's own RESPONSE.
        `outreach_write` returns its senders' responses verbatim, which is safe
        on its four routes and would not have been here. Every path out of this
        orchestrator goes through `scrub`, and the omission is REPORTED rather
        than done quietly.
        """
        client, _ = client_over(
            by_path(
                {
                    CONSENT_READ_PATH: _consent_then_revoked(),
                    CONSENT_WRITE_PATH: {"status": 200, "data": {}},
                }
            )
        )
        # The response shape Uplers actually sends back on this DELETE.
        leaky = Recorder(
            response={
                "status": 200,
                "data": {"gmail_connected": True, "gmail_email": LIVE_MAILBOX},
            },
            takes_body=False,
        )

        async with client:
            result = await consent_write.revoke_email_scan(
                client, confirm=True, send=leaky
            )

        assert LIVE_MAILBOX not in json.dumps(result)
        assert result["response_redacted_keys"] == ["gmail_email"]
        assert result["response"]["data"]["gmail_connected"] is True
        assert "gmail_email" in result["withheld"]

    async def test_the_leak_check_can_actually_fail(self):
        """__CONTROL. `not in json.dumps(result)` passes against an empty dict.

        Planted in a field the orchestrator DOES print - the last scan time -
        so the same assertion that guards the address is proven able to see it
        when it is really there.
        """
        client, _ = client_over(
            by_path({CONSENT_READ_PATH: consent_payload(last_job_scan=LIVE_MAILBOX)})
        )

        async with client:
            result = await consent_write.revoke_email_scan(client, confirm=False)

        assert LIVE_MAILBOX in json.dumps(result)


def _consent_then_revoked():
    """A read that answers ON first and OFF afterwards - a landed revoke.

    A closure rather than two handlers because the pre-flight read and the
    verification read hit the SAME url, and a fixture that answered ON to both
    would make `landed: True` unreachable.
    """
    state = {"n": 0}

    def read(_request):
        state["n"] += 1
        # The FIRST read is the pre-flight one and must say the scan is on -
        # otherwise guard 4 refuses and the write path is never reached.
        return consent_payload(has_consent=state["n"] == 1)

    return read


# ==========================================================================
# B. uplers_submit_interview_feedback - the ONE-WAY one
# ==========================================================================


class TestSubmitInterviewFeedback:

    async def test_the_body_is_exactly_two_keys(self):
        """GUARD 2, as a SET EQUALITY. A third key must fail loudly.

        Asserted as `==` and not as a membership check, and that is the whole
        design of this test. `{"company_id", "feedback"} <= keys` passes
        happily with a `tag` or a `rating` riding along - and this is a route
        that cannot be un-sent, so a key nobody previewed is a key published
        against a real company with no way back.
        """
        client, _ = client_over(
            by_path({INTERVIEWS_PATH: interviews_payload([interview_row()])})
        )

        async with client:
            result = await consent_write.submit_interview_feedback(
                client, 41, CALLER_FEEDBACK, confirm=False
            )

        assert set(result["body"]) == {"company_id", "feedback"}
        assert set(result["body"]) == set(consent_write.FEEDBACK_BODY_KEYS)
        assert result["body"]["company_id"] == 41
        assert result["body"]["feedback"] == CALLER_FEEDBACK
        assert result["body_keys"] == ["company_id", "feedback"]

    async def test_the_exact_key_set_check_can_actually_fail(self):
        """__CONTROL for the assertion above, run against the real builder.

        Proves the key-set equality is a real constraint rather than a
        restatement of whatever `feedback_body` happens to return: a third key
        added to the built body is shown failing the same comparison the test
        above makes.
        """
        body = consent_write.feedback_body(41, CALLER_FEEDBACK)
        assert set(body) == set(consent_write.FEEDBACK_BODY_KEYS)

        smuggled = dict(body, tag="rewrite-message-from-preview")
        assert set(smuggled) != set(consent_write.FEEDBACK_BODY_KEYS)

    async def test_the_callers_own_text_is_echoed_verbatim(self):
        """Provenance is the rule. THIS text is his, so it is shown in full.

        The mirror of the mailbox-address tests above, and deliberately in the
        opposite direction: a preview that hid what the caller typed is not a
        preview, and on a route with no undo this is the only chance anyone has
        to read the review before it is published.
        """
        client, _ = client_over(
            by_path({INTERVIEWS_PATH: interviews_payload([interview_row()])})
        )

        async with client:
            result = await consent_write.submit_interview_feedback(
                client, 41, CALLER_FEEDBACK, confirm=False
            )

        assert CALLER_FEEDBACK in json.dumps(result)

    async def test_it_reads_the_live_interview_list_with_the_detailed_flag(self):
        """GUARD 1, and the query string is part of it.

        `detailed=true` is the STRING, matching `uplers_my_interviews` and the
        browser call site. Pinned because the list is what guard 4 decides on,
        and a request that quietly asked for a narrower record could refuse a
        company that is genuinely there.
        """
        client, calls = client_over(
            by_path({INTERVIEWS_PATH: interviews_payload([interview_row()])})
        )

        async with client:
            await consent_write.submit_interview_feedback(
                client, 41, CALLER_FEEDBACK, confirm=False
            )

        assert len(calls) == 1
        assert calls[0].method == "GET"
        assert calls[0].url.path == INTERVIEWS_PATH
        assert dict(httpx.URL(str(calls[0].url)).params) == {"detailed": "true"}

    async def test_an_empty_list_refuses_and_explains_why_it_is_empty(self):
        """GUARD 4, on the state the account is ACTUALLY in today.

        MEASURED: Uplers lists zero interview companies, so every call refuses -
        which is the tool working. The refusal must not read as "you typed the
        wrong id": nothing could ever match a list with no rows, and the reason
        the list is empty is a consent that governs a DIFFERENT scan and that he
        cannot switch on at all.
        """
        client, calls = client_over(by_path({INTERVIEWS_PATH: interviews_payload()}))
        recorder = Recorder()

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await consent_write.submit_interview_feedback(
                    client, 41, CALLER_FEEDBACK, confirm=True, send=recorder
                )

        message = str(excinfo.value)
        assert "NO interview companies at all" in message
        assert "NOT 'no interviews were arranged'" in message
        assert "DIFFERENT consent" in message
        assert "nothing for you to turn on" in message
        assert "Nothing was sent" in message
        assert recorder.calls == []
        assert writes(calls) == []

    async def test_a_company_not_on_the_list_refuses(self):
        """GUARD 4 again, on the case a populated list makes possible.

        This is the guard the one-way-ness pays for. On a reversible route a
        wrong id is an annoyance; here it publishes a review against a company
        this account never interviewed with, and nothing anywhere can retract
        it. The refusal names what IS on the list so the caller can correct it.
        """
        client, calls = client_over(
            by_path(
                {
                    INTERVIEWS_PATH: interviews_payload(
                        [interview_row(41, "Oteemo"), interview_row(77, "Confido")]
                    )
                }
            )
        )
        recorder = Recorder()

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await consent_write.submit_interview_feedback(
                    client, 999, CALLER_FEEDBACK, confirm=True, send=recorder
                )

        message = str(excinfo.value)
        assert "not among the 2 company" in message
        assert "cannot be un-sent" in message
        assert "41 (Oteemo)" in message
        assert recorder.calls == []
        assert writes(calls) == []

    async def test_a_company_on_the_list_is_not_refused(self):
        """__CONTROL for the two refusals above.

        A guard that refuses EVERYTHING is indistinguishable from a broken
        tool, and on this route "it always refuses" would look exactly like the
        measured empty-list state. The allowed case is proven to reach a
        preview.
        """
        client, _ = client_over(
            by_path({INTERVIEWS_PATH: interviews_payload([interview_row(41)])})
        )

        async with client:
            result = await consent_write.submit_interview_feedback(
                client, 41, CALLER_FEEDBACK, confirm=False
            )

        assert result["performed"] is False
        assert result["company_id"] == 41
        assert result["company_name"] == "Oteemo"

    async def test_an_id_sent_as_a_string_still_matches(self):
        """Uplers is not consistent about this and a strict compare would lie.

        `3 != "3"` would refuse a company plainly on the list, and the caller
        has nothing to look at that would explain why - both render the same.
        Matched as strings; sent as the integer the body was measured to carry.
        """
        client, _ = client_over(
            by_path({INTERVIEWS_PATH: interviews_payload([interview_row("41")])})
        )

        async with client:
            result = await consent_write.submit_interview_feedback(
                client, 41, CALLER_FEEDBACK, confirm=False
            )

        assert result["body"]["company_id"] == 41
        assert isinstance(result["body"]["company_id"], int)

    async def test_empty_feedback_is_refused_before_the_list_is_even_read(self):
        """A blank review on a route with no undo is a mistake, not a command.

        Refused BEFORE the read, so a malformed call costs zero requests - the
        same ordering `outreach_write.set_message_template` uses for a blank
        template, and for the same reason.
        """
        client, calls = client_over(by_path({}))

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await consent_write.submit_interview_feedback(
                    client, 41, "   ", confirm=True, send=Recorder()
                )

        assert "ONE-WAY" in str(excinfo.value)
        assert calls == []

    async def test_the_preview_says_one_way_and_that_the_snapshot_is_not_an_undo(self):
        """The two facts a caller must have before confirming, both stated.

        Not one fact. "There is no undo" and "the file this tool writes is not
        one either" are different claims, and a reader who has only the first
        can still see a `snapshot` key in the result and draw the wrong
        conclusion from it.
        """
        client, _ = client_over(
            by_path({INTERVIEWS_PATH: interviews_payload([interview_row()])})
        )

        async with client:
            result = await consent_write.submit_interview_feedback(
                client, 41, CALLER_FEEDBACK, confirm=False
            )

        blob = " ".join(result["notes"])
        assert result["reversible"] is False
        assert result["one_way"] is True
        assert "no edit route and no delete route" in blob
        assert "LOCAL ONLY" in blob
        assert "PREVIEW - nothing was sent" in result["notes"][0]

    async def test_the_snapshot_is_on_disk_before_the_send(self, isolated_snapshots):
        """GUARD 3, asserted from inside the sender.

        Weaker comfort here than anywhere else in this repo and the result says
        so - the file records the list, not a way back. It is still taken
        first, because "every confirmed write writes a restore point before it
        sends" is one rule to keep true and "these ones do" is a question
        somebody has to re-answer on every edit.
        """
        seen = {}

        def at_send_time(_body):
            seen["files"] = sorted(p.name for p in isolated_snapshots.glob("*.json"))

        client, _ = client_over(
            by_path(
                {
                    INTERVIEWS_PATH: interviews_payload([interview_row()]),
                    FEEDBACK_PATH: {"status": "success", "data": {}},
                }
            )
        )

        async with client:
            result = await consent_write.submit_interview_feedback(
                client,
                41,
                CALLER_FEEDBACK,
                confirm=True,
                send=Recorder(on_send=at_send_time),
            )

        assert len(seen["files"]) == 1, seen
        assert "interview-feedback" in result["snapshot"]["snapshot_id"]
        assert result["reverse_with"].startswith("NOTHING")

    async def test_it_re_reads_and_reports_whether_the_feedback_attached(self):
        """GUARD 5. The POST answers a status string and nothing about the row.

        So the reply cannot say the review is attached to the right company;
        only the list can. The verification reads it back and checks the row.
        """
        state = {"n": 0}

        def read(_request):
            state["n"] += 1
            return interviews_payload(
                [interview_row(41, feedback="already there" if state["n"] > 1 else None)]
            )

        client, calls = client_over(
            by_path({INTERVIEWS_PATH: read, FEEDBACK_PATH: {"status": "success"}})
        )

        async with client:
            result = await consent_write.submit_interview_feedback(
                client, 41, CALLER_FEEDBACK, confirm=True, send=Recorder()
            )

        assert result["performed"] is True
        assert result["verified"]["re_read"] is True
        assert result["verified"]["landed"] is True
        assert [c.url.path for c in calls] == [INTERVIEWS_PATH, INTERVIEWS_PATH]

    async def test_a_success_that_did_not_attach_reports_landed_false(self):
        """__CONTROL for guard 5, and its advice is the one that matters.

        The obvious reaction to "it did not land" is to send again. On this
        route that is exactly wrong: it is one-way and repeat behaviour is
        NOT KNOWN - their own client patches its row either way, so the bundle
        cannot say whether a second POST overwrites or appends. The note has to
        say do not resend, not just report the failure.
        """
        client, _ = client_over(
            by_path(
                {
                    INTERVIEWS_PATH: interviews_payload([interview_row(41)]),
                    FEEDBACK_PATH: {"status": "success"},
                }
            )
        )

        async with client:
            result = await consent_write.submit_interview_feedback(
                client, 41, CALLER_FEEDBACK, confirm=True, send=Recorder()
            )

        assert result["verified"]["landed"] is False
        assert "Do NOT" in result["verified"]["note"]
        assert "one-way" in result["verified"]["note"]

    async def test_existing_feedback_is_flagged_and_not_refused(self):
        """A correction is a legitimate thing to want; the uncertainty is his.

        Not refused, because re-submitting to fix a review is a real use. Named
        loudly, because whether Uplers overwrites or appends is UNMEASURABLE
        from their bundle - so the caller is accepting an unknown, and a tool
        that let them do that silently would be hiding the only interesting
        part of the decision.
        """
        client, _ = client_over(
            by_path(
                {
                    INTERVIEWS_PATH: interviews_payload(
                        [interview_row(41, feedback="an earlier review")]
                    )
                }
            )
        )

        async with client:
            result = await consent_write.submit_interview_feedback(
                client, 41, CALLER_FEEDBACK, confirm=False
            )

        assert result["current"]["feedback_already_given"] is True
        assert "UPLERS ALREADY HAS FEEDBACK FROM YOU" in result["notes"][1]

    async def test_a_non_numeric_company_id_refuses_rather_than_crashing(self):
        client, calls = client_over(by_path({}))

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await consent_write.submit_interview_feedback(
                    client, "Oteemo", CALLER_FEEDBACK, confirm=True, send=Recorder()
                )

        assert "not a company id" in str(excinfo.value)
        assert calls == []


# ==========================================================================
# The shared scrubber
# ==========================================================================


class TestScrub:

    def test_it_reaches_the_address_one_level_down(self):
        """Where the address actually is. A shallow pop would miss it entirely.

        Both payloads that carry `gmail_email` nest it inside `data`, so a
        scrubber that only looked at the top level would report success while
        changing nothing - the most dangerous shape a redaction can have.
        """
        clean, removed = consent_write.scrub(
            {"status": 200, "data": {"gmail_connected": True, "gmail_email": LIVE_MAILBOX}}
        )

        assert removed == ["gmail_email"]
        assert clean == {"status": 200, "data": {"gmail_connected": True}}

    def test_it_reaches_into_lists_of_rows(self):
        clean, removed = consent_write.scrub(
            [{"company_id": 1, "gmail_email": LIVE_MAILBOX}, {"company_id": 2}]
        )

        assert removed == ["gmail_email"]
        assert clean == [{"company_id": 1}, {"company_id": 2}]

    def test_it_reports_nothing_when_there_was_nothing_to_remove(self):
        """__CONTROL. `removed` must be computed, not printed unconditionally.

        A scrubber that always claimed to have redacted something would make
        every `response_redacted_keys` assertion above meaningless.
        """
        clean, removed = consent_write.scrub({"status": 200, "data": {"a": 1}})

        assert removed == []
        assert clean == {"status": 200, "data": {"a": 1}}


# ==========================================================================
# The server.py wrappers - where the ROUTE CONSTANT is supplied
# ==========================================================================


class TestTheToolWrappers:
    """The orchestrators above are tested with a Recorder standing in for the
    sender, so nothing there can catch the one mistake only the wrapper can
    make: HANDING IN THE WRONG ROUTE.

    That is not a hypothetical class of bug in this repo - `endpoints.py`
    records a prior slice confusing two constants, and `test_agent_tools`
    opens by saying the dangerous mistake in this namespace is not a POST, it
    is a request aimed at the wrong sibling. `consent-email-job-scan` sits one
    path segment from `consent-auto-run`, and `interview-feedback` one from
    `interview-list`. A wrapper that named the neighbour would pass every test
    above.

    So these drive the registered tools over a MockTransport and assert the
    endpoint each one would hit, from the preview - which sends nothing.
    """

    @pytest.fixture(autouse=True)
    def session(self, monkeypatch, tmp_path):
        from uplers_server import session as session_mod
        from uplers_server.session import SessionStore

        path = tmp_path / "session.json"
        monkeypatch.setattr(session_mod, "session_path", lambda: path)
        monkeypatch.setattr(server_mod, "_session_store", lambda: SessionStore(path))
        SessionStore(path).save(TOKEN, method="test")
        return path

    def wire(self, monkeypatch, handler):
        transport, calls = make_transport(handler)
        monkeypatch.setattr(
            server_mod,
            "TalentClient",
            lambda *a, **k: TalentClient(lambda: TOKEN, transport=transport, delay=0),
        )
        return calls

    async def test_the_revoke_wrapper_aims_at_the_consent_route(self, monkeypatch):
        calls = self.wire(monkeypatch, by_path({CONSENT_READ_PATH: consent_payload()}))

        result = await server_mod.uplers_revoke_email_scan()

        assert result["performed"] is False
        assert result["endpoint"] == endpoints.EP_CONSENT_EMAIL_JOB_SCAN
        assert result["method"] == "DELETE"
        # It is NOT the neighbouring consent, which turns the paid applier on
        # and off and is refused outright.
        assert "consent-auto-run" not in result["endpoint"]
        assert writes(calls) == []
        assert [c.url.path for c in calls] == [CONSENT_READ_PATH]

    async def test_the_feedback_wrapper_aims_at_the_feedback_route(self, monkeypatch):
        calls = self.wire(
            monkeypatch,
            by_path({INTERVIEWS_PATH: interviews_payload([interview_row(41)])}),
        )

        result = await server_mod.uplers_submit_interview_feedback(41, CALLER_FEEDBACK)

        assert result["performed"] is False
        assert result["endpoint"] == endpoints.EP_INTERVIEW_FEEDBACK
        # It is NOT the READ route it pairs with - the two differ by one path
        # segment and one is a plain GET of his own calendar.
        assert result["endpoint"] != endpoints.EP_INTERVIEW_LIST
        assert set(result["body"]) == {"company_id", "feedback"}
        assert writes(calls) == []

    async def test_the_measured_state_reaches_the_tool_as_a_refusal(
        self, monkeypatch
    ):
        """END TO END, on the state the account is ACTUALLY in.

        Every other test here builds a list so the write path can be exercised.
        This one uses the MEASURED payload - zero interview companies - and
        asserts that the registered tool refuses, sends nothing, and explains
        the empty list. It is the outcome a caller gets today, and it should be
        pinned as such rather than only reachable by a unit test.
        """
        calls = self.wire(
            monkeypatch, by_path({INTERVIEWS_PATH: interviews_payload()})
        )

        with pytest.raises(WriteRefused) as excinfo:
            await server_mod.uplers_submit_interview_feedback(
                41, CALLER_FEEDBACK, confirm=True
            )

        assert "NO interview companies at all" in str(excinfo.value)
        assert writes(calls) == []
