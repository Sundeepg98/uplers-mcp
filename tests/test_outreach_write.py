"""The four outreach settings writes: five guards each, and the traps.

These are the only writes in ``talent/outreach/*`` this server has, and they
are in for one reason - they can be put back. One path segment away sit
``store-employee-requests`` (the send, which Uplers' own UI says cannot be
undone), ``reveal-email`` and ``discard-job``. So the properties this suite
pins are not "does it work"; they are the ones that keep a reversible write
from becoming an irreversible one.

FIVE GUARDS, EVERY WRITE, and a control for each that FAILS with the guard
removed:

  1.  **read-live**   - the record is read from its GET before the body is
      built. On a whole-record route, building off anything else silently
      rewrites the fields nobody mentioned.
  2.  **exact-body**  - `confirm=False` returns the literal dict that would go
      on the wire, and the follow-up route's key SET is asserted so a tenth key
      or a missing ninth fails loudly.
  3.  **snapshot-before** - written to disk BEFORE the send, asserted from
      INSIDE the sender rather than after the call.
  4.  **empty-refusal** - a write that would change nothing raises.
  5.  **re-read-verify** - a 200 that did not move the value reports
      `landed: False`.

THE TWO TRAPS THIS FILE EXISTS FOR
-----------------------------------
*   **The inversion.** Uplers stores `disabled_followup_gmail: false` to mean
    the gmail channel is ON. Both directions are pinned, and so is the case a
    single-direction test cannot see: a DOUBLE negation reads as correct at
    every individual site and produces a request that switches off the channel
    the caller asked to switch on.
*   **The two id spaces on one row.** A blocklist row carries `id` (the row)
    and `company_id` (the company); both are small integers, the POST takes one
    and the DELETE takes the other as a path segment, and swapping them removes
    a different company with a 200 either way.

NO NETWORK. Every request goes through httpx.MockTransport and every payload
here is synthetic - there is no captured template or follow-up message in this
file, and the two personal-text controls assert on strings this file invented
precisely so a failure cannot print a real one. `isolated_snapshots` is autouse
so a test cannot write a restore point into the real data directory by
forgetting a fixture.
"""

from __future__ import annotations

import json

import httpx
import pytest

from conftest import make_transport
from uplers_server import endpoints, outreach_write
from uplers_server.profile_write import WriteRefused
from uplers_server.talent import TalentClient

FOLLOWUP_PATH = "/api/" + endpoints.EP_OUTREACH_SETTINGS_FOLLOWUP
AUTO_REPLY_READ_PATH = "/api/" + endpoints.EP_OUTREACH_AUTO_REPLY
AUTO_REPLY_WRITE_PATH = "/api/" + endpoints.EP_OUTREACH_UPDATE_AUTO_REPLY
TEMPLATES_READ_PATH = "/api/" + endpoints.EP_OUTREACH_TEMPLATES
TEMPLATES_WRITE_PATH = "/api/" + endpoints.EP_OUTREACH_STORE_TEMPLATE
BLOCKLIST_PATH = "/api/" + endpoints.EP_OUTREACH_DISABLED_COMPANIES

TOKEN = "42|bearer-token-that-must-never-be-printed"

#: Synthetic personal text. Every assertion that something was NOT printed
#: checks for these strings, so a regression prints an invented sentence into a
#: test log rather than one of his.
LIVE_GMAIL_MESSAGE = (
    "Hi {{outreachEmployee}}, following up on {{jobTitle}} - SYNTHETIC-GMAIL-FOLLOWUP."
)
LIVE_LINKEDIN_MESSAGE = (
    "Hello {{outreachEmployee}} about {{jobTitle}} - SYNTHETIC-LINKEDIN-FOLLOWUP."
)
LIVE_TEMPLATE_BODY = (
    "<p>SYNTHETIC-EXISTING-TEMPLATE-BODY: eight years at a company that does not "
    "exist, notice period nine weeks.</p>"
)
LIVE_TEMPLATE_SUBJECT = "Looking to apply for {{title}} at {{company}}, need referral"

NEW_TEMPLATE_BODY = "<p>CALLER-SUPPLIED-TEMPLATE-BODY, which the preview must echo.</p>"

#: The eight measured on his account, in `tests/fixtures/outreach_auto_reply.json`.
LIVE_CATEGORIES = list(outreach_write.KNOWN_AUTO_REPLY_CATEGORIES)


# --- wiring ----------------------------------------------------------------
#
# Local rather than imported from another suite, for the reason
# test_resume_write gives: the orchestrators take a client as an argument
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

    The confirm gate and the snapshot precondition are claims about CONTROL
    FLOW, so they are asserted on the seam itself as well as on the transport:
    "the sender was never called" cannot be satisfied by a request that went
    somewhere the mock was not watching.

    `on_send` runs at send time, which is how snapshot-BEFORE is proved. An
    assertion made after the orchestrator returns cannot tell "written first"
    from "written afterwards".
    """

    def __init__(self, response=None, on_send=None):
        self.calls = []
        self._response = response if response is not None else {"status": 200, "data": {}}
        self._on_send = on_send

    async def __call__(self, payload):
        if self._on_send is not None:
            self._on_send(payload)
        self.calls.append(payload)
        return self._response


# --- payload builders ------------------------------------------------------


def followup_payload(
    gmail_disabled=False,
    linkedin_disabled=False,
    gmail_interval=1,
    linkedin_interval=1,
    gmail_message=LIVE_GMAIL_MESSAGE,
    linkedin_message=LIVE_LINKEDIN_MESSAGE,
    legacy=None,
):
    """The measured envelope: integer 200 and `data` at the top level.

    Shaped after `tests/fixtures/outreach_settings_followup.json`, which carries
    NO singular `interval_days` and NO `message` - the legacy fields exist only
    on the older shape, and `legacy` is how a test asks for that one.
    """
    data = {"id": 3044}
    if legacy is not None:
        data.update(legacy)
    else:
        data.update(
            {
                "disabled_followup_gmail": gmail_disabled,
                "disabled_followup_linkedin": linkedin_disabled,
                "interval_days_gmail": gmail_interval,
                "interval_days_linkedin": linkedin_interval,
                "message_gmail": gmail_message,
                "message_linkedin": linkedin_message,
            }
        )
    return {"status": 200, "message": "Follow-up settings fetched", "data": data}


def auto_reply_payload(enabled=False, hours=2, categories=None):
    return {
        "status": 200,
        "message": "Auto reply hours fetched successfully",
        "data": {
            "handle_auto_reply": enabled,
            "hours": hours,
            "auto_reply_categories": (
                list(LIVE_CATEGORIES) if categories is None else list(categories)
            ),
        },
    }


def templates_payload(
    gmail_body=LIVE_TEMPLATE_BODY,
    gmail_subject=LIVE_TEMPLATE_SUBJECT,
    linkedin_body="",
    linkedin_subject="",
):
    """The one route in this ring that answers the STRING "success"."""
    return {
        "status": "success",
        "data": {
            "gmail_template": gmail_body,
            "gmail_template_subject": gmail_subject,
            "linkedin_template": linkedin_body,
            "linkedin_template_subject": linkedin_subject,
        },
    }


def blocklist_payload(rows=None):
    """Rows carry BOTH ids, exactly as the captured fixture does."""
    if rows is None:
        rows = [
            {"id": 261, "company_id": 19868, "company_name": "Synthetic Systems"},
            {"id": 260, "company_id": 1092, "company_name": "Imaginary Consulting"},
        ]
    return {"status": 200, "data": list(rows)}


def routes(
    followup=None,
    auto_reply=None,
    templates=None,
    blocklist=None,
    on_write=None,
    write_response=None,
):
    """Serve the four GETs; anything unrouted is a 404.

    A 404 rather than a friendly default on purpose: a request to a route these
    writes have no business making must show up as a failure, not as a pass.

    Each GET reads its payload through a callable when given one, so a test can
    make the SECOND read (guard 5's) answer differently from the first - which
    is the only way to tell "landed" from "the route said 200".
    """

    def resolve(value, default):
        if value is None:
            return default
        return value() if callable(value) else value

    def handler(request):
        path = request.url.path
        if request.method == "GET":
            if path == FOLLOWUP_PATH:
                return httpx.Response(200, json=resolve(followup, followup_payload()))
            if path == AUTO_REPLY_READ_PATH:
                return httpx.Response(
                    200, json=resolve(auto_reply, auto_reply_payload())
                )
            if path == TEMPLATES_READ_PATH:
                return httpx.Response(200, json=resolve(templates, templates_payload()))
            if path == BLOCKLIST_PATH:
                return httpx.Response(200, json=resolve(blocklist, blocklist_payload()))
        else:
            if on_write is not None:
                on_write(request)
            return httpx.Response(200, json=write_response or {"status": 200, "data": {}})
        return httpx.Response(404, json={"message": "unrouted: %s" % path})

    return handler


# --- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_snapshots(monkeypatch, tmp_path):
    """Snapshots go to tmp_path. Autouse: a test must not be able to write a
    copy of a real settings record into the operator's data directory by
    forgetting a fixture."""
    directory = tmp_path / "outreach_snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(outreach_write, "snapshots_dir", lambda: directory)
    return directory


def snapshot_files(directory):
    return sorted(path.name for path in directory.iterdir())


# ===========================================================================
# 1. THE CONFIRM GATE - no confirm means no request, on all four writes
# ===========================================================================


async def test_no_write_sends_or_snapshots_without_confirm(isolated_snapshots):
    """All four, in one test, because the claim is identical for each.

    Asserted three ways because they fail in different directions: the seam
    (the sender object), the transport (any non-GET), and the disk (a restore
    point for a write that never happened). The request assertions come FIRST -
    a planted control that removes the gate must report the damage, not a flag
    describing it.
    """
    client, calls = client_over(routes())
    senders = [Recorder() for _ in range(5)]

    results = [
        await outreach_write.set_followup(
            client, gmail_enabled=False, confirm=False, send=senders[0]
        ),
        await outreach_write.set_auto_reply(
            client, enabled=True, confirm=False, send=senders[1]
        ),
        await outreach_write.set_message_template(
            client, "gmail", NEW_TEMPLATE_BODY, "New subject", confirm=False,
            send=senders[2],
        ),
        await outreach_write.block_company(client, 4242, confirm=False, send=senders[3]),
        await outreach_write.unblock_company(
            client, 19868, confirm=False, send=senders[4]
        ),
    ]

    assert [sender.calls for sender in senders] == [[], [], [], [], []]
    assert writes(calls) == []
    assert snapshot_files(isolated_snapshots) == []
    assert [result["performed"] for result in results] == [False] * 5
    await client.aclose()


# ===========================================================================
# 2. THE SENDER SEAM - no sender, no write, on all four
# ===========================================================================


async def test_a_confirmed_write_with_no_sender_refuses_before_snapshotting(
    isolated_snapshots,
):
    """The seam, asserted as a seam.

    This module cannot send by itself; `server.py` hands it the route. The
    check runs BEFORE the snapshot so a call that could never have sent
    anything does not leave a restore point behind for a write that was never
    going to happen.
    """
    client, calls = client_over(routes())

    for call in (
        lambda: outreach_write.set_followup(client, gmail_enabled=False, confirm=True),
        lambda: outreach_write.set_auto_reply(client, enabled=True, confirm=True),
        lambda: outreach_write.set_message_template(
            client, "gmail", NEW_TEMPLATE_BODY, confirm=True
        ),
        lambda: outreach_write.block_company(client, 4242, confirm=True),
        lambda: outreach_write.unblock_company(client, 19868, confirm=True),
    ):
        with pytest.raises(WriteRefused) as caught:
            await call()
        assert "no sender" in str(caught.value)

    assert writes(calls) == []
    assert snapshot_files(isolated_snapshots) == []
    await client.aclose()


async def test_a_delete_sender_cannot_be_built_from_the_collection_path():
    """The unblock's path template must carry {id}, and this refuses at BUILD.

    The collection URL and the item URL differ by one path segment and both
    exist. A sender built from the collection constant by a copy-paste would
    issue DELETE at the whole collection - so it cannot be built at all, which
    is stronger than checking at send time.
    """
    client, _ = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        outreach_write.delete_sender_for(client, endpoints.EP_OUTREACH_DISABLED_COMPANIES)

    assert "{id}" in str(caught.value)
    # And the real constant builds one.
    sender = outreach_write.delete_sender_for(
        client, endpoints.EP_OUTREACH_DISABLED_COMPANY_DELETE
    )
    assert sender.method == "DELETE"
    await client.aclose()


# ===========================================================================
# 3. GUARD 1 - read-live. The body is built off the record, not off a default
# ===========================================================================


async def test_the_followup_body_carries_the_live_record_not_defaults():
    """Eight of the nine keys are resent from the record that was just read.

    This is the control for read-live: with the live read replaced by anything
    else - a blank record, a cached one, a fixture - the intervals below come
    back as 1 and the messages as None, and a write that was supposed to change
    one flag silently rewrites four other fields.
    """
    client, calls = client_over(
        routes(followup=followup_payload(gmail_interval=5, linkedin_interval=9))
    )

    result = await outreach_write.set_followup(
        client, gmail_enabled=False, confirm=False, send=Recorder()
    )

    assert calls[0].method == "GET"
    assert calls[0].url.path == FOLLOWUP_PATH
    body = result["body"]
    assert body["interval_days_gmail"] == 5
    assert body["interval_days_linkedin"] == 9
    assert result["current"]["gmail_message_set"] is True
    await client.aclose()


async def test_the_auto_reply_body_carries_the_live_record_not_defaults():
    """Read-live on the auto-reply route. All three keys go every time, so the
    two the caller did not name are resent from the record just read - and this
    server refuses to invent an `hours` it was not given and could not read."""
    client, calls = client_over(
        routes(auto_reply=auto_reply_payload(enabled=False, hours=6))
    )

    result = await outreach_write.set_auto_reply(
        client, enabled=True, confirm=False, send=Recorder()
    )

    assert calls[0].url.path == AUTO_REPLY_READ_PATH
    assert result["body"]["hours"] == 6
    assert result["body"]["auto_reply_categories"] == LIVE_CATEGORIES
    await client.aclose()


async def test_the_template_preview_reports_the_live_subject_and_length():
    """Read-live on the template route. The existing template's subject and
    size are read from the account, not assumed - they are the only two facts a
    reader gets about what is about to be overwritten."""
    client, calls = client_over(routes())

    result = await outreach_write.set_message_template(
        client, "gmail", NEW_TEMPLATE_BODY, "New subject", confirm=False,
        send=Recorder(),
    )

    assert calls[0].url.path == TEMPLATES_READ_PATH
    assert result["current"]["exists"] is True
    assert result["current"]["subject"] == LIVE_TEMPLATE_SUBJECT
    assert result["current"]["body_length"] == len(LIVE_TEMPLATE_BODY)
    await client.aclose()


async def test_the_followup_read_falls_back_to_the_legacy_singular_fields():
    """Uplers' GET falls back from the per-channel fields to `disabled_followup`
    and `interval_days`; the server may still answer with that older shape.

    The fallback belongs to the READER only. The POST has no `disabled_followup`
    key at all, which the key-set assertion in section 4 pins from the other
    side.
    """
    current = outreach_write.read_followup(
        followup_payload(legacy={"disabled_followup": True, "interval_days": 4})
    )

    assert current["disabled_followup_gmail"] is True
    assert current["disabled_followup_linkedin"] is True
    assert current["interval_days_gmail"] == 4
    assert current["interval_days_linkedin"] == 4


async def test_the_unblock_reads_the_live_list_to_resolve_the_row_id():
    """THE TWO ID SPACES. The caller names a COMPANY; the DELETE takes the ROW.

    `company_id: 19868` sits on row `id: 261`. Sending 19868 as the path
    segment would delete a different row - or none - and answer 200 either way.
    The only way to know which is which is to read the list, which is what
    guard 1 is for on this write.
    """
    client, _ = client_over(routes())

    result = await outreach_write.unblock_company(client, 19868, confirm=False)

    assert result["company_id"] == 19868
    assert result["blocklist_row_id"] == 261
    assert result["path_id"] == 261
    await client.aclose()


async def test_the_unblock_sends_the_row_id_as_the_path_segment():
    """End to end through a real DELETE sender: 261 in the path, not 19868."""
    seen = []
    client, _ = client_over(routes(on_write=seen.append))
    sender = outreach_write.delete_sender_for(
        client, endpoints.EP_OUTREACH_DISABLED_COMPANY_DELETE
    )

    await outreach_write.unblock_company(client, 19868, confirm=True, send=sender)

    assert len(seen) == 1
    assert seen[0].method == "DELETE"
    assert seen[0].url.path == BLOCKLIST_PATH + "/261"
    assert not seen[0].content
    await client.aclose()


# ===========================================================================
# 4. GUARD 2 - the exact body, and the key SET
# ===========================================================================


async def test_the_followup_body_is_exactly_nine_keys():
    """A key added or dropped by a future edit must fail HERE, loudly.

    Their POST is a flat literal with no spread: every key on every call. A
    tenth key would be a shape their client never sends, and a missing ninth
    would be a partial body against a route that overwrites the whole record.
    """
    client, _ = client_over(routes())

    result = await outreach_write.set_followup(
        client, gmail_enabled=False, confirm=False, send=Recorder()
    )

    assert set(result["body"]) == set(outreach_write.FOLLOWUP_BODY_KEYS)
    assert len(outreach_write.FOLLOWUP_BODY_KEYS) == 9
    # The legacy singular flag is a READ-side fallback and must never be sent.
    assert "disabled_followup" not in result["body"]
    assert result["body"]["channel"] == "both"
    await client.aclose()


async def test_the_auto_reply_body_is_exactly_three_keys():
    client, _ = client_over(routes())

    result = await outreach_write.set_auto_reply(
        client, enabled=True, confirm=False, send=Recorder()
    )

    assert set(result["body"]) == set(outreach_write.AUTO_REPLY_BODY_KEYS)
    assert result["body"]["handle_auto_reply"] is True
    await client.aclose()


async def test_the_template_body_is_exactly_three_keys_and_carries_no_tag():
    """Path B, the template editor. Path A adds `tag` and is not built."""
    client, _ = client_over(routes())

    result = await outreach_write.set_message_template(
        client, "gmail", NEW_TEMPLATE_BODY, "New subject", confirm=False,
        send=Recorder(),
    )

    assert set(result["body"]) == set(outreach_write.TEMPLATE_BODY_KEYS)
    assert "tag" not in result["body"]
    await client.aclose()


async def test_the_previewed_body_is_what_the_sender_actually_receives():
    """A preview that does not match the request is not a preview.

    The one permitted departure is redaction of CARRIED-OVER personal text,
    which is why this test changes both messages: with the caller supplying
    every personal field, the shown body and the sent body must be identical,
    key for key.
    """
    client, _ = client_over(routes())
    sender = Recorder()

    preview = await outreach_write.set_followup(
        client,
        gmail_enabled=False,
        gmail_message="Bye {{outreachEmployee}} re {{jobTitle}}",
        linkedin_message="Bye {{outreachEmployee}} re {{jobTitle}}",
        message="singular",
        confirm=False,
        send=sender,
    )
    performed = await outreach_write.set_followup(
        client,
        gmail_enabled=False,
        gmail_message="Bye {{outreachEmployee}} re {{jobTitle}}",
        linkedin_message="Bye {{outreachEmployee}} re {{jobTitle}}",
        message="singular",
        confirm=True,
        send=sender,
    )

    assert preview["body_redacted_keys"] == []
    assert sender.calls == [performed["body"]]
    assert preview["body"] == sender.calls[0]
    await client.aclose()


# ===========================================================================
# 5. GUARD 3 - the snapshot, and that it lands BEFORE the send
# ===========================================================================


async def test_every_confirmed_write_snapshots_before_it_sends(isolated_snapshots):
    """Asserted from INSIDE the sender. After the call is too late to tell.

    A snapshot taken after the write records the NEW value: every read-back
    here returns whatever is current, so an after-the-fact snapshot is not a
    degraded restore point, it is not one at all.

    **EACH WRITE IS MEASURED AGAINST ITS OWN BEFORE-COUNT, and the first
    version of this test was not.** It asserted the directory was non-empty at
    send time, which every write after the first satisfies for free - the
    earlier writes' snapshots are still sitting there. Planting the defect
    proved it: moving the TEMPLATE snapshot after its send left this test
    GREEN. A check that cannot fail certifies nothing, so the claim is now
    "this write's own snapshot appeared before this write's own request".
    """
    client, _ = client_over(routes())
    at_send: list[tuple[str, int, int]] = []

    async def measure(label, call):
        before = len(snapshot_files(isolated_snapshots))

        def watch(_payload):
            at_send.append((label, before, len(snapshot_files(isolated_snapshots))))

        await call(Recorder(on_send=watch))

    await measure(
        "followup",
        lambda sender: outreach_write.set_followup(
            client, gmail_enabled=False, confirm=True, send=sender
        ),
    )
    await measure(
        "auto_reply",
        lambda sender: outreach_write.set_auto_reply(
            client, enabled=True, confirm=True, send=sender
        ),
    )
    await measure(
        "template",
        lambda sender: outreach_write.set_message_template(
            client, "gmail", NEW_TEMPLATE_BODY, confirm=True, send=sender
        ),
    )
    await measure(
        "block",
        lambda sender: outreach_write.block_company(
            client, 4242, confirm=True, send=sender
        ),
    )
    await measure(
        "unblock",
        lambda sender: outreach_write.unblock_company(
            client, 19868, confirm=True, send=sender
        ),
    )

    assert [row[0] for row in at_send] == [
        "followup",
        "auto_reply",
        "template",
        "block",
        "unblock",
    ]
    for label, before, during in at_send:
        assert during == before + 1, (
            "%s: its own snapshot was not on disk when its request went out "
            "(%d files before, %d at send)" % (label, before, during)
        )
    await client.aclose()


async def test_the_template_snapshot_holds_the_prior_body_because_nothing_else_can(
    isolated_snapshots,
):
    """There is NO delete-template route on Uplers. The file is the only way back.

    So this is the one place in this server where personal text is deliberately
    written to disk, and the test asserts it is really there - a snapshot that
    quietly dropped the body would look identical from the outside and would be
    worthless at the only moment it matters.
    """
    client, _ = client_over(routes())

    result = await outreach_write.set_message_template(
        client, "gmail", NEW_TEMPLATE_BODY, confirm=True, send=Recorder()
    )

    record = outreach_write.load_snapshot(result["snapshot"]["snapshot_id"])
    assert record["record"]["gmail"]["message_template"] == LIVE_TEMPLATE_BODY
    assert record["record"]["gmail"]["message_subject"] == LIVE_TEMPLATE_SUBJECT
    await client.aclose()


async def test_a_snapshot_id_that_is_not_one_is_refused_before_any_file_is_opened():
    """Inherited from the sibling servers, where the version without this
    resolved `../not-a-snapshot` and restored it over real data."""
    with pytest.raises(WriteRefused):
        outreach_write.load_snapshot("../not-a-snapshot")
    with pytest.raises(WriteRefused):
        outreach_write.load_snapshot("")


# ===========================================================================
# 6. GUARD 4 - empty refusal, on all four writes
# ===========================================================================


async def test_a_followup_write_that_changes_nothing_refuses():
    """The live record says gmail is ON; asking for it to be ON is a no-op.

    On a route that rewrites all nine keys a no-op is not free - it is a full
    rewrite whose only possible effect is getting one of the eight untouched
    fields wrong.
    """
    client, calls = client_over(routes(followup=followup_payload(gmail_disabled=False)))
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await outreach_write.set_followup(
            client, gmail_enabled=True, confirm=True, send=sender
        )

    assert "Nothing would change" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_an_auto_reply_write_that_changes_nothing_refuses():
    client, calls = client_over(routes(auto_reply=auto_reply_payload(enabled=False)))
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await outreach_write.set_auto_reply(
            client, enabled=False, hours=2, confirm=True, send=sender
        )

    assert "Nothing would change" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_reordering_the_auto_reply_categories_is_not_a_change():
    """Uplers' payload is a list and nothing in their client reads it
    positionally, so a re-ordered list is the same set - and would otherwise
    look like a real edit forever."""
    client, _ = client_over(routes())
    sender = Recorder()

    with pytest.raises(WriteRefused):
        await outreach_write.set_auto_reply(
            client,
            categories=list(reversed(LIVE_CATEGORIES)),
            confirm=True,
            send=sender,
        )

    assert sender.calls == []
    await client.aclose()


async def test_writing_the_same_template_again_refuses():
    """On a route with no undo, overwriting a template with itself is all risk
    and no change."""
    client, calls = client_over(routes())
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await outreach_write.set_message_template(
            client,
            "gmail",
            LIVE_TEMPLATE_BODY,
            LIVE_TEMPLATE_SUBJECT,
            confirm=True,
            send=sender,
        )

    assert "Nothing would change" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_blocking_an_already_blocked_company_refuses():
    client, calls = client_over(routes())
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await outreach_write.block_company(client, 19868, confirm=True, send=sender)

    assert "already on the outreach blocklist" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_unblocking_a_company_that_is_not_blocked_refuses():
    client, calls = client_over(routes())
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await outreach_write.unblock_company(client, 777777, confirm=True, send=sender)

    assert "not on the outreach blocklist" in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


# ===========================================================================
# 7. GUARD 5 - re-read and verify. A 200 is not proof
# ===========================================================================


async def test_a_confirmed_followup_write_re_reads_and_reports_it_landed():
    """The second GET is the evidence; the write's own 200 is not."""
    answers = [followup_payload(gmail_disabled=False), followup_payload(gmail_disabled=True)]
    client, calls = client_over(routes(followup=lambda: answers.pop(0)))

    result = await outreach_write.set_followup(
        client, gmail_enabled=False, confirm=True, send=Recorder()
    )

    reads = [call for call in calls if call.url.path == FOLLOWUP_PATH and call.method == "GET"]
    assert len(reads) == 2
    assert result["verified"]["re_read"] is True
    assert result["verified"]["landed"] is True
    await client.aclose()


async def test_a_200_that_did_not_move_the_value_reports_landed_false():
    """THE POINT OF GUARD 5. The route answers 200 and the record is unchanged;
    a write tool that reported success off the status would be lying."""
    client, _ = client_over(routes(followup=followup_payload(gmail_disabled=False)))

    result = await outreach_write.set_followup(
        client, gmail_enabled=False, confirm=True, send=Recorder()
    )

    assert result["performed"] is True
    assert result["verified"]["landed"] is False
    assert {row["field"] for row in result["verified"]["mismatches"]} == {
        "disabled_followup_gmail"
    }
    assert "DID NOT LAND" in result["verified"]["note"]
    await client.aclose()


async def test_a_failed_re_read_reports_unknown_and_never_raises():
    """The write already happened. Raising here would throw away the one fact
    the caller most needs - that something was sent."""
    state = {"reads": 0}

    def handler(request):
        if request.method != "GET":
            return httpx.Response(200, json={"status": 200, "data": {}})
        if request.url.path == BLOCKLIST_PATH:
            state["reads"] += 1
            if state["reads"] == 1:
                return httpx.Response(200, json=blocklist_payload())
            return httpx.Response(500, json={"message": "gone"})
        return httpx.Response(404, json={})

    client, _ = client_over(handler)
    sender = Recorder()

    result = await outreach_write.block_company(
        client, 4242, confirm=True, send=sender
    )

    assert result["performed"] is True
    assert sender.calls == [{"company_id": 4242}]
    assert result["verified"]["re_read"] is False
    assert result["verified"]["landed"] is None
    await client.aclose()


async def test_a_block_that_did_not_land_reports_landed_false():
    """The blocklist pair verifies by reading the LIST back, not by the status.

    Its DELETE arm's response is only a status - their own client checks
    nothing else - so on this route especially the record is the only evidence.
    """
    client, _ = client_over(routes())

    result = await outreach_write.block_company(
        client, 4242, confirm=True, send=Recorder()
    )

    assert result["performed"] is True
    assert result["verified"]["re_read"] is True
    assert result["verified"]["landed"] is False
    assert "DID NOT LAND" in result["verified"]["note"]
    await client.aclose()


async def test_an_unblock_that_did_not_land_reports_landed_false():
    seen = []
    client, _ = client_over(routes(on_write=seen.append))
    sender = outreach_write.delete_sender_for(
        client, endpoints.EP_OUTREACH_DISABLED_COMPANY_DELETE
    )

    result = await outreach_write.unblock_company(
        client, 19868, confirm=True, send=sender
    )

    assert len(seen) == 1
    assert result["verified"]["landed"] is False
    await client.aclose()


async def test_a_block_reports_the_new_row_id_after_verifying():
    """The row id only exists after the write, and it is what an unblock needs."""
    answers = [
        blocklist_payload(),
        blocklist_payload(
            [
                {"id": 262, "company_id": 4242, "company_name": "Newly Blocked"},
                {"id": 261, "company_id": 19868, "company_name": "Synthetic Systems"},
            ]
        ),
    ]
    client, _ = client_over(routes(blocklist=lambda: answers.pop(0)))

    result = await outreach_write.block_company(
        client, 4242, confirm=True, send=Recorder()
    )

    assert result["verified"]["landed"] is True
    assert result["verified"]["blocklist_row_id"] == 262
    assert result["reverse_with"] == "uplers_unblock_company(4242, confirm=True)"
    await client.aclose()


# ===========================================================================
# 8. THE INVERSION TRAP - both directions, and the double negation
# ===========================================================================


def test_the_negation_is_pinned_in_both_directions():
    """The unit, straight. ON means `disabled: false`; OFF means `disabled: true`."""
    assert outreach_write.to_disabled(True) is False
    assert outreach_write.to_disabled(False) is True
    assert outreach_write.from_disabled(False) is True
    assert outreach_write.from_disabled(True) is False
    # Tri-state on the read side: a payload that did not say has not said "off".
    assert outreach_write.from_disabled(None) is None


@pytest.mark.parametrize(
    "gmail_enabled,linkedin_enabled,expect_gmail,expect_linkedin",
    [
        (True, True, False, False),
        (True, False, False, True),
        (False, True, True, False),
        (False, False, True, True),
    ],
)
async def test_the_wire_flags_are_the_negation_of_the_public_ones(
    gmail_enabled, linkedin_enabled, expect_gmail, expect_linkedin
):
    """All four corners.

    A MISSING negation fails the (True -> False) rows. A DOUBLE negation - the
    one that reads as correct at every individual site - fails them too, in the
    same direction, which is why the enabled=True rows are here at all: a
    suite that only tested "disable it" would pass with the polarity inverted
    everywhere.
    """
    # Live state is the opposite of what is asked for on both channels, so
    # every row is a real change and nothing is refused by guard 4.
    client, _ = client_over(
        routes(
            followup=followup_payload(
                gmail_disabled=not expect_gmail, linkedin_disabled=not expect_linkedin
            )
        )
    )

    result = await outreach_write.set_followup(
        client,
        gmail_enabled=gmail_enabled,
        linkedin_enabled=linkedin_enabled,
        confirm=False,
        send=Recorder(),
    )

    assert result["body"]["disabled_followup_gmail"] is expect_gmail
    assert result["body"]["disabled_followup_linkedin"] is expect_linkedin
    await client.aclose()


async def test_an_untouched_channel_is_carried_over_unflipped():
    """The double-negation catcher that does not depend on the caller's value.

    gmail is asked about; linkedin is not. Linkedin's live flag must arrive on
    the wire EXACTLY as it was read - and it travels through from_disabled() and
    to_disabled() to get there, so a bug in either shows up here as a channel
    switching state on its own.
    """
    client, _ = client_over(
        routes(followup=followup_payload(gmail_disabled=False, linkedin_disabled=True))
    )

    result = await outreach_write.set_followup(
        client, gmail_enabled=False, confirm=False, send=Recorder()
    )

    assert result["body"]["disabled_followup_gmail"] is True     # asked for: OFF
    assert result["body"]["disabled_followup_linkedin"] is True  # untouched: still OFF
    assert result["current"]["linkedin_enabled"] is False
    await client.aclose()


async def test_the_public_parameter_and_the_wire_field_disagree_on_purpose():
    """The one-line statement of the whole trap, as an assertion.

    `gmail_enabled=True` and `disabled_followup_gmail: False` are the SAME
    request. Anything that made those two read alike would be the bug.
    """
    client, _ = client_over(routes(followup=followup_payload(gmail_disabled=True)))

    result = await outreach_write.set_followup(
        client, gmail_enabled=True, confirm=False, send=Recorder()
    )

    assert result["body"]["disabled_followup_gmail"] is False
    assert result["changes"] == [
        {"field": "disabled_followup_gmail", "from": True, "to": False}
    ]
    await client.aclose()


# ===========================================================================
# 9. UPLERS' OWN GATES - the two template variables, and both exemptions
# ===========================================================================


@pytest.mark.parametrize("variable", ["{{outreachEmployee}}", "{{jobTitle}}"])
@pytest.mark.parametrize("channel", ["gmail", "linkedin"])
async def test_a_followup_message_missing_a_required_variable_is_refused(
    channel, variable
):
    """Uplers' own wording, and the refusal costs zero requests."""
    other = [name for name in outreach_write.REQUIRED_MESSAGE_VARIABLES if name != variable]
    message = "Hi there %s" % other[0]

    client, calls = client_over(routes())
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await outreach_write.set_followup(
            client,
            confirm=True,
            send=sender,
            **{"%s_message" % channel: message},
        )

    text = str(caught.value)
    assert outreach_write.CHANNEL_LABELS[channel] in text
    assert variable in text
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_the_variable_gate_is_exempt_when_the_channel_is_disabled():
    """First exemption, VERIFIED in their own branch: a disabled channel sends
    nothing, so its message is not checked."""
    client, _ = client_over(routes())

    result = await outreach_write.set_followup(
        client,
        gmail_enabled=False,
        gmail_message="no variables here at all",
        confirm=False,
        send=Recorder(),
    )

    assert result["body"]["message_gmail"] == "no variables here at all"
    assert result["body"]["disabled_followup_gmail"] is True
    await client.aclose()


async def test_the_variable_gate_is_exempt_when_the_message_is_empty():
    """Second exemption: an empty message means "use whatever Uplers has", a
    state their own UI allows, and `R.message_x || null` puts null on the wire."""
    client, _ = client_over(routes())

    result = await outreach_write.set_followup(
        client, gmail_message="", confirm=False, send=Recorder()
    )

    assert result["body"]["message_gmail"] is None
    assert result["body"]["disabled_followup_gmail"] is False
    await client.aclose()


async def test_enabling_auto_reply_with_no_categories_is_refused():
    """Uplers' own text, quoted: an auto-reply switched on with nothing to
    answer is a setting that cannot do anything."""
    client, calls = client_over(routes())
    sender = Recorder()

    with pytest.raises(WriteRefused) as caught:
        await outreach_write.set_auto_reply(
            client, enabled=True, categories=[], confirm=True, send=sender
        )

    assert outreach_write.AUTO_REPLY_EMPTY_CATEGORIES_ERROR in str(caught.value)
    assert sender.calls == []
    assert writes(calls) == []
    await client.aclose()


async def test_disabling_auto_reply_with_no_categories_is_allowed():
    """Their gate is `!handle_auto_reply || length !== 0` - it fires only on
    ENABLE. A guard stricter than theirs refuses what the platform accepts."""
    client, _ = client_over(routes(auto_reply=auto_reply_payload(enabled=True)))

    result = await outreach_write.set_auto_reply(
        client, enabled=False, categories=[], confirm=False, send=Recorder()
    )

    assert result["body"]["handle_auto_reply"] is False
    assert result["body"]["auto_reply_categories"] == []
    await client.aclose()


async def test_an_unknown_category_is_reported_and_not_rejected():
    """The eight known names came from ONE capture of his account, not from
    Uplers' enum - so an unknown one is named in the preview, where a typo is
    visible before confirming, and is NOT refused."""
    client, _ = client_over(routes())

    result = await outreach_write.set_auto_reply(
        client,
        categories=LIVE_CATEGORIES + ["asking_resumee"],
        confirm=False,
        send=Recorder(),
    )

    assert result["unknown_categories"] == ["asking_resumee"]
    assert "asking_resumee" in result["body"]["auto_reply_categories"]
    await client.aclose()


# ===========================================================================
# 10. THE PROVIDER ENUM - a number, not a string
# ===========================================================================


@pytest.mark.parametrize("channel,provider", [("linkedin", 1), ("gmail", 2)])
async def test_the_provider_is_the_integer_for_the_channel(channel, provider):
    """VERIFIED three ways in their bundle. Passing the string would be a
    different call to the same route, not a synonym."""
    # The mapping itself first, so a broken enum reports as a broken enum
    # rather than as whatever downstream line happens to trip over it.
    assert outreach_write.provider_for(channel) == provider
    assert isinstance(outreach_write.provider_for(channel), int)
    assert not isinstance(outreach_write.provider_for(channel), bool)

    client, _ = client_over(routes())

    result = await outreach_write.set_message_template(
        client, channel, NEW_TEMPLATE_BODY, "s", confirm=False, send=Recorder()
    )

    assert result["body"]["provider"] == provider
    assert result["body"]["provider"] is not True  # not a bool masquerading as 1
    assert isinstance(result["body"]["provider"], int)
    assert not isinstance(result["body"]["provider"], str)
    await client.aclose()


async def test_the_provider_reaches_the_wire_as_a_json_number():
    """The assertion one level down: `1` and `"1"` are different bytes."""
    seen = []
    client, _ = client_over(routes(on_write=seen.append))
    sender = outreach_write.json_sender_for(
        client, endpoints.EP_OUTREACH_STORE_TEMPLATE
    )

    await outreach_write.set_message_template(
        client, "gmail", NEW_TEMPLATE_BODY, "s", confirm=True, send=sender
    )

    raw = seen[0].content.decode("utf-8")
    assert '"provider": 2' in raw or '"provider":2' in raw
    assert '"provider": "gmail"' not in raw and '"provider":"2"' not in raw
    assert isinstance(json.loads(raw)["provider"], int)
    await client.aclose()


async def test_an_unknown_channel_is_refused_before_anything_is_read():
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await outreach_write.set_message_template(
            client, "whatsapp", NEW_TEMPLATE_BODY, confirm=True, send=Recorder()
        )

    assert "not a channel" in str(caught.value)
    assert calls == []
    await client.aclose()


# ===========================================================================
# 11. PERSONAL TEXT - the two cases that look the same and are not
# ===========================================================================


async def test_the_template_preview_never_contains_the_existing_body():
    """The rule the whole repo already keeps, on the write side.

    An existing template is a multi-paragraph self-description carrying
    employer history, a LinkedIn URL and a notice period, and a tool result
    ends up in a transcript. Existence, subject and length are reported; the
    text is not.
    """
    client, _ = client_over(routes())

    result = await outreach_write.set_message_template(
        client, "gmail", NEW_TEMPLATE_BODY, "New subject", confirm=False,
        send=Recorder(),
    )

    assert LIVE_TEMPLATE_BODY not in json.dumps(result)
    assert "SYNTHETIC-EXISTING-TEMPLATE-BODY" not in json.dumps(result)
    assert result["current"]["body_withheld"] is True
    assert result["current"]["body_length"] == len(LIVE_TEMPLATE_BODY)
    # ...and the caller's own text IS echoed. That is what a preview is for.
    assert result["body"]["message_template"] == NEW_TEMPLATE_BODY
    await client.aclose()


async def test_the_template_result_never_contains_the_existing_body_either(
    isolated_snapshots,
):
    """The performed half, which is the one that also carries a `response` and
    a `verified` block - three more places a body could ride out."""
    client, _ = client_over(routes())

    result = await outreach_write.set_message_template(
        client, "gmail", NEW_TEMPLATE_BODY, "New subject", confirm=True,
        send=Recorder(),
    )

    assert "SYNTHETIC-EXISTING-TEMPLATE-BODY" not in json.dumps(result)
    assert result["performed"] is True
    # It is on disk, where the rollback needs it.
    assert snapshot_files(isolated_snapshots)
    await client.aclose()


async def test_a_carried_over_followup_message_is_described_not_printed():
    """The case that exists only because this route resends the whole record.

    Asking to change an interval must not print his follow-up message back into
    the transcript as a side effect of a write about a number.
    """
    client, _ = client_over(routes())

    result = await outreach_write.set_followup(
        client, gmail_interval_days=7, confirm=False, send=Recorder()
    )

    rendered = json.dumps(result)
    assert "SYNTHETIC-GMAIL-FOLLOWUP" not in rendered
    assert "SYNTHETIC-LINKEDIN-FOLLOWUP" not in rendered
    assert result["body"]["message_gmail"].startswith("<carried over unchanged")
    assert "message_gmail" in result["body_redacted_keys"]
    assert "message_linkedin" in result["body_redacted_keys"]
    await client.aclose()


async def test_the_real_carried_over_message_still_reaches_the_sender():
    """Redaction is a RENDERING, not a change to the request.

    The body that goes on the wire carries the real text - it has to, since the
    route rewrites all nine keys - and only the returned copy is described. A
    module that redacted the outgoing body would blank his follow-up messages
    on every unrelated write.
    """
    client, _ = client_over(routes())
    sender = Recorder()

    result = await outreach_write.set_followup(
        client, gmail_interval_days=7, confirm=True, send=sender
    )

    assert sender.calls[0]["message_gmail"] == LIVE_GMAIL_MESSAGE
    assert result["body"]["message_gmail"] != LIVE_GMAIL_MESSAGE
    await client.aclose()


async def test_caller_supplied_text_is_echoed_but_carried_over_text_is_not():
    """Both cases in one request, so the difference is provenance and nothing
    else: the same key, redacted on one channel and printed on the other."""
    client, _ = client_over(routes())
    mine = "Hi {{outreachEmployee}} about {{jobTitle}} - CALLER-SUPPLIED-FOLLOWUP."

    result = await outreach_write.set_followup(
        client, gmail_message=mine, confirm=False, send=Recorder()
    )

    assert result["body"]["message_gmail"] == mine
    assert result["body"]["message_linkedin"].startswith("<carried over unchanged")
    assert result["body_redacted_keys"] == ["message_linkedin"]
    assert "SYNTHETIC-LINKEDIN-FOLLOWUP" not in json.dumps(result)
    await client.aclose()


async def test_a_diff_row_for_a_message_carries_lengths_and_not_text():
    """A diff would otherwise print BOTH the old text and the new one, which is
    the leak this module spends the most effort avoiding."""
    client, _ = client_over(routes())
    mine = "Hi {{outreachEmployee}} about {{jobTitle}} - CALLER-SUPPLIED-FOLLOWUP."

    result = await outreach_write.set_followup(
        client, gmail_message=mine, confirm=False, send=Recorder()
    )

    row = [item for item in result["changes"] if item["field"] == "message_gmail"][0]
    assert row["changed"] is True
    assert row["from_length"] == len(LIVE_GMAIL_MESSAGE)
    assert row["to_length"] == len(mine)
    assert "from" not in row and "to" not in row
    await client.aclose()


# ===========================================================================
# 12. HOUSEKEEPING
# ===========================================================================


async def test_the_endpoint_shown_is_the_one_the_sender_holds():
    """This module names no write route. The endpoint in a preview comes off
    the sender `server.py` supplied, which is what keeps that true."""
    client, _ = client_over(routes())
    sender = outreach_write.json_sender_for(
        client, endpoints.EP_OUTREACH_UPDATE_AUTO_REPLY
    )

    result = await outreach_write.set_auto_reply(
        client, enabled=True, confirm=False, send=sender
    )

    assert result["endpoint"] == endpoints.EP_OUTREACH_UPDATE_AUTO_REPLY
    assert result["method"] == "POST application/json"
    await client.aclose()


def test_the_module_names_no_write_only_route_constant():
    """The property `server.py` supplies the route FOR.

    Two of these four routes serve their GET and their POST on the same path
    string, so this module must name those two to read the record back - that
    is Uplers' doing and it is stated in the module docstring. The three
    constants that are write-only must appear nowhere in the file.
    """
    import ast
    from pathlib import Path

    source = Path(outreach_write.__file__).read_text(encoding="utf-8")
    for name in (
        "EP_OUTREACH_UPDATE_AUTO_REPLY",
        "EP_OUTREACH_STORE_TEMPLATE",
        "EP_OUTREACH_DISABLED_COMPANY_DELETE",
    ):
        assert name not in source

    # And no route STRING either. Walked through the AST rather than grepped,
    # so a docstring naming a route in prose - which several here do, because
    # the evidence belongs beside the code - does not have to be spelled around.
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    live_strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    for route in (
        "update-auto-reply",
        "store-message-template",
        "store-employee-requests",
    ):
        assert not [text for text in live_strings if route in text], route

    # The two shared paths need a different check, and finding that out is why
    # this assertion is shaped the way it is. A substring hunt for
    # "settings/disabled-companies" fires on a NOTE - prose in a tool result
    # telling the reader which route the blocklist came from and warning them
    # off settings/companies - which is a sentence, not a call. What must not
    # exist is a string literal that IS a path, and on this API every path
    # starts "talent/". A hardcoded route fails here; a note naming one does not.
    assert not [text for text in live_strings if text.startswith("talent/")]


async def test_the_interval_clamp_mirrors_their_own():
    """`t = e > 0 ? e : 1`, VERIFIED at both the GET seed and the POST body."""
    assert outreach_write.clamp_interval(0) == 1
    assert outreach_write.clamp_interval(-3) == 1
    assert outreach_write.clamp_interval(5) == 5

    # The live record says 5, so clamping a requested 0 to 1 IS a change and
    # guard 4 does not swallow the case this test is about.
    client, _ = client_over(routes(followup=followup_payload(gmail_interval=5)))
    result = await outreach_write.set_followup(
        client, gmail_interval_days=0, confirm=False, send=Recorder()
    )
    assert result["body"]["interval_days_gmail"] == 1
    await client.aclose()


async def test_the_singular_interval_seeds_to_one_when_the_record_omits_it():
    """The captured record carries no `interval_days` and no `message`, but the
    POST must send both. Their GET seeds the interval with `?? 1` and never
    seeds the message, so `R.message || null` puts null on the wire."""
    client, _ = client_over(routes())

    result = await outreach_write.set_followup(
        client, gmail_enabled=False, confirm=False, send=Recorder()
    )

    assert result["body"]["interval_days"] == 1
    assert result["body"]["message"] is None
    await client.aclose()


async def test_a_blank_template_is_refused_rather_than_blanking_the_account():
    """This one is THIS SERVER's guard, not Uplers' - their editor will send an
    empty string. With no delete-template route, blanking a template is
    treated as a mistake rather than as a command."""
    client, calls = client_over(routes())

    with pytest.raises(WriteRefused) as caught:
        await outreach_write.set_message_template(
            client, "gmail", "   ", confirm=True, send=Recorder()
        )

    assert "empty" in str(caught.value)
    assert writes(calls) == []
    await client.aclose()
