"""RELEVANCE, not size: what a row must carry to be worth reading, and what it must not.

The size pass (`test_payload_budgets.py`, `test_market_stats_truncation.py`)
asked "is this payload too big". This file asks the different question that
survives it: **does this field help a caller DECIDE?** A field that cannot is
noise on every row; a field that is MISSING is worse, because recovering it
costs a whole round-trip.

THREE DEFECTS FIXED, AND ONE THAT LOOKS IDENTICAL AND IS NOT.

1.  `uplers_tailored_jobs` repeated a 130-byte `score_basis` on all five rows.
    It is a statement about the SURFACE - `tailor-jobs` publishes no skill list
    at all - so it is true of the route, not of the row, and belongs in the
    envelope once. Moved to `score_basis_all_rows`, byte for byte.

2.  `uplers_reply_outcomes` repeated a 47-byte `answered_note` on all seven
    rows, plus `employee_name_withheld` / `logo_url_withheld`, both `True` on
    every row BY CONSTRUCTION - the shaper never emits those two fields, so
    the marker cannot be anything else. All three moved to the envelope;
    `answered` STAYS on the row because it is three-valued and a future route
    could make it vary.

3.  `enc_id` AND `job_id` were on every row of three tools and **no tool
    accepts either** (MEASURED: 0 of 67 tool signatures take one; `hr_number` is
    taken by 10). A caller could pass neither anywhere, and `hr_number` already
    serves the other thing an id is good for here - correlating a row across
    tools. Both dropped from the payload, with the envelope saying what they
    were and why, so the absence reads as a decision rather than an oversight.

    THEY ARE DROPPED DIFFERENTLY BECAUSE THEY ARE CONSUMED DIFFERENTLY, and
    collapsing that distinction breaks the only write this server performs.
    `enc_id` is consumed by nothing and is gone from the model. `job_id` is
    still an attribute on `TalentRow`, marked `exclude=True` AND
    `SkipJsonSchema`, because `uplers_apply` reads it off the row OBJECT to
    build `{"hr_id": row.job_id}`. The attribute is the server's; the payload is
    the caller's. Two controls below hold that line: one proves apply still
    reads it, one proves no caller ever sees it - in the response OR in the
    advertised schema, which are two different leaks and only one of them is
    visible to a payload measurement.

**AND THE TRAP.** `applied`, `saved` and `not_interested` are `false` on every
`my_feed` row today, which makes them look like exactly the same defect. They
are not, and deleting them would be the worst change in this pass. CONSTANT IN
THIS SAMPLE IS NOT CONSTANT BY CONSTRUCTION: those three are per-row state -
*have I already dealt with this one?* - and they are uniform today only because
he has not applied to any of the jobs currently in his feed. Proof that they
genuinely vary is one fixture away: `saved` measures **two** distinct values
across the nine pipeline rows in `talent_pipeline.json`. The day he applies to
a feed job, `applied` is the most decision-bearing field in its row.

THE TEST TO APPLY BEFORE MOVING ANY FIELD: *could this ever differ between two
rows of one response?* If yes it stays on the row, however uniform today's
capture looks. Only a field the code CANNOT vary may be hoisted. By that test
`rank_opportunities.verdict` and the `search_opportunities` result fields
(`availability`, `job_nature`, `is_native`, `assessments_required`) also stay,
and `channel` / `reply_type` stay on the reply rows - all row-varying, all
uniform by coincidence in the captures.

CONTROLS. Every test here is named for what it stops and was watched RED before
the fix landed - the reversion for each is written above it.
"""

from __future__ import annotations

import inspect
import json

import httpx
import pytest

import server
from uplers_server import conversion, endpoints, talent_shape
from uplers_server import profile as profile_mod
from uplers_server import session as session_mod
from uplers_server.session import SessionStore
from uplers_server.talent import TalentClient

from conftest import (
    CONFIDO,
    TALENT_FEED,
    TALENT_PIPELINE,
    TALENT_TAILOR,
    load_fixture,
    load_talent_fixture,
    make_transport,
    tool_schema,
)

TOKEN = "test-token"

#: The wording that moved, held here BYTE FOR BYTE. If a fix "moved" a caveat
#: by paraphrasing it, the caveat did not move - it was rewritten, and the
#: reader lost the sentence that was proven against the payload.
SCORE_BASIS = (
    "partial evidence: this surface publishes no skill list, so that half of "
    "the score is jobcore's neutral default rather than a match"
)
ANSWERED_NOTE = "not recorded on this route - check the thread"


def tailor_rows() -> list[dict]:
    return load_talent_fixture(TALENT_TAILOR)["data"]


def feed_rows() -> list[dict]:
    return load_talent_fixture(TALENT_FEED)["hrs"]["data"]


def pipeline_rows() -> list[dict]:
    return load_talent_fixture(TALENT_PIPELINE)["hrs"]["data"]


def wire_bytes(payload) -> int:
    """As the transport serialises it. `len(str(...))` would undercount."""
    if hasattr(payload, "model_dump_json"):
        return len(payload.model_dump_json().encode("utf-8"))
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


@pytest.fixture
def profile(isolated_profile):
    candidate = profile_mod.Profile(
        name="Test Candidate",
        years_experience=5.0,
        location="Bangalore, India",
        skills=["Node.js", "TypeScript", "AWS", "PostgreSQL", "Python", "React"],
        source="test",
    )
    profile_mod.save(candidate, path=isolated_profile)
    return candidate


@pytest.fixture(autouse=True)
def isolated_tools(monkeypatch, tmp_path, store_factory):
    """No real session file, no real store - the same guards test_talent_tools.py
    installs, which is where the reasoning for each one is written down."""
    path = tmp_path / "session.json"
    monkeypatch.setattr(session_mod, "session_path", lambda: path)
    monkeypatch.setattr(server, "_session_store", lambda: SessionStore(path))
    monkeypatch.setattr(server, "_open_store", store_factory)


def wire_talent(monkeypatch, payload):
    """Let a tool build a real TalentClient over a MockTransport serving *payload*."""
    transport, calls = make_transport(lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr(
        server,
        "TalentClient",
        lambda *a, **k: TalentClient(lambda: TOKEN, transport=transport, delay=0),
    )
    return calls


# ==========================================================================
# CONTROL 1 - the envelope carries what the row lost.
# ==========================================================================


def test_the_shared_score_basis_moves_to_the_envelope_byte_for_byte(profile):
    """__CONTROL. WATCH IT FAIL by deleting `score_basis_all_rows` from the
    TalentFeed the tool returns: the caveat then exists nowhere, and five rows
    scoring an identical 80 read as a finding about the jobs instead of a
    finding about the payload.

    The caveat itself is NOT relaxed: every one of these rows still had 60% of
    its score supplied by jobcore's neutral default, and a reader who acts on
    an 80 without knowing that is the exact reader this sentence was written
    for. What changed is that it is said ONCE.
    """
    rows = [talent_shape.to_talent_row(raw, profile=profile) for raw in tailor_rows()]
    assert len(rows) == 5
    assert all(
        row.score_basis == SCORE_BASIS for row in rows
    ), "premise check - before the hoist every row carried the same string"

    shared = talent_shape.hoist_shared_score_basis(rows)

    assert shared == SCORE_BASIS
    assert all(row.score_basis is None for row in rows)


async def test_the_tailored_jobs_TOOL_returns_that_envelope_not_just_the_shaper(
    monkeypatch, profile
):
    """A test exercising a copy of the tool proves nothing about the tool."""
    wire_talent(monkeypatch, load_talent_fixture(TALENT_TAILOR))

    result = await server.uplers_tailored_jobs(score=True)

    assert result.score_basis_all_rows == SCORE_BASIS
    assert [row.score_basis for row in result.rows] == [None] * len(result.rows)


def test_the_answered_note_moves_to_the_envelope_byte_for_byte():
    """__CONTROL. WATCH IT FAIL by deleting `answered_note_all_rows` from the
    shaped envelope.

    This one is the author's own defect, committed the day before this pass:
    the same 47-byte sentence on all seven rows. It must survive the move
    intact, because it is the sentence that stops a snapshot being read as a
    to-do list - a mistake that has already been made out loud, on two rows
    that had been answered a fortnight earlier.
    """
    shaped = conversion.shape_reply_outcomes(load_fixture("outreach_value_with_happy"))

    assert shaped["answered_note_all_rows"] == ANSWERED_NOTE
    assert all("answered_note" not in row for row in shaped["rows"])


def test_the_withheld_markers_move_up_and_the_envelope_says_they_cover_every_row():
    """__CONTROL. WATCH IT FAIL by dropping `every row` from WITHHELD_REASON.

    `employee_name_withheld` and `logo_url_withheld` were `True` on all seven
    rows BY CONSTRUCTION - `_reply_row` never reads either key, so the marker
    could not have been anything else. The envelope already named both fields;
    what it did not say was that the withholding covers every row, and a
    route-level list beside per-row markers reads as though it might not.
    """
    shaped = conversion.shape_reply_outcomes(load_fixture("outreach_value_with_happy"))

    assert shaped["withheld"] == ["employee_name", "logo_url"]
    assert "every row" in shaped["withheld_reason"]
    for row in shaped["rows"]:
        assert "employee_name_withheld" not in row
        assert "logo_url_withheld" not in row


def test_the_three_valued_answered_flag_stays_on_the_row():
    """The note moved; the FLAG did not, and the difference is the whole rule.

    `answered` is what a caller reads to decide whether a row is an action. It
    is three-valued, and a future route that records completion would make it
    vary per row - so it is row data even while it reads `unknown` on all
    seven today. `unknown` must never render as absent, because an absent
    field is what a reader turns into "outstanding".
    """
    shaped = conversion.shape_reply_outcomes(load_fixture("outreach_value_with_happy"))

    assert shaped["rows"], "premise check - there are rows to assert about"
    assert all(row["answered"] == "unknown" for row in shaped["rows"])


# ==========================================================================
# CONTROL 2 - a row-varying field is STILL ON THE ROW.
#
# THIS IS THE TEST THAT STOPS A FUTURE PASS "OPTIMISING" THEM AWAY. A detector
# looking for constant columns flags these three, correctly and uselessly:
# they are uniform in the capture and per-row by nature. Anyone who hoists them
# because a measurement said "1 distinct value across 12 rows" lands here.
# ==========================================================================


def test_his_own_state_stays_on_every_feed_row_even_though_it_is_uniform_today(profile):
    """__CONTROL. WATCH IT FAIL by removing `applied` from TalentRow.

    `applied`, `saved`, `not_interested` answer *have I already dealt with this
    one?* - the first thing read on a feed row. They are `false` on every row
    of the current capture only because he has not applied to any job currently
    in his feed. Hoisting them to the envelope would delete the answer the day
    it stops being uniform, which is the day it matters most.
    """
    rows = [talent_shape.to_talent_row(raw, profile=profile) for raw in feed_rows()]
    assert rows, "premise check - the feed fixture has rows"

    for row in rows:
        fields = row.__class__.model_fields
        assert "applied" in fields
        assert "saved" in fields
        assert "not_interested" in fields
        assert row.applied is False
        assert row.saved is False
        assert row.not_interested is False


def test_the_uniform_feed_flag_is_PROVEN_row_varying_on_the_pipeline_capture(profile):
    """The evidence that the test above is not superstition.

    `saved` is uniform across the three feed rows and carries TWO distinct
    values across the nine pipeline rows, in a committed capture, today. So the
    field demonstrably varies between rows of one response and the feed's
    uniformity is a fact about his account this week, not about the schema.
    """
    rows = [talent_shape.to_talent_row(raw, profile=profile) for raw in pipeline_rows()]
    assert len(rows) == 9
    assert len({row.saved for row in rows}) == 2


def test_a_mixed_page_keeps_its_score_basis_on_the_rows(profile):
    """The hoist must be lossless, so it must REFUSE a page it cannot cover.

    A page where one row rests on a default and another does not has no single
    envelope sentence. Hoisting the majority value would attach a caveat to a
    row that earned its score honestly, and drop it from one that did not.
    """
    rows = [talent_shape.to_talent_row(raw, profile=profile) for raw in tailor_rows()]
    rows[0].score_basis = None

    assert talent_shape.hoist_shared_score_basis(rows) is None
    assert [row.score_basis for row in rows[1:]] == [SCORE_BASIS] * 4


# ==========================================================================
# CONTROL 3 - no enc_id in row output, and the envelope explains its absence.
# ==========================================================================


def test_no_tool_in_this_server_accepts_an_enc_id_argument():
    """The MEASUREMENT the drop rests on, kept as a test rather than a memory.

    If a write against `talent/hr/update-saved-hr` is ever built, it will take
    an `enc_id`, this test goes red, and the red is the reminder to put the
    field back on the row rather than a failure to route around.
    """
    accepting = [
        name
        for name, function in vars(server).items()
        if name.startswith("uplers_")
        and callable(function)
        and "enc_id" in inspect.signature(function).parameters
    ]
    assert accepting == []


@pytest.mark.parametrize("surface", ["tailored_jobs", "my_feed", "my_pipeline"])
def test_neither_uplers_id_reaches_a_row_of_any_authenticated_surface(profile, surface):
    """__CONTROL. WATCH IT FAIL by restoring `enc_id` to TalentRow, or by
    dropping `exclude=True` from `job_id`.

    Both were ids a caller could not pass anywhere - measured, 0 of 67 tool
    signatures accept either - riding on every row of three tools. `hr_number`
    is the handle every tool here takes, it is accepted by 10 of them, and it
    already serves the other job an id could do here: correlating one row
    across tools. So it stays and they do not.

    THE TWO ARE DROPPED DIFFERENTLY AND THE ASSERTIONS SAY SO. `enc_id` is gone
    from the model. `job_id` is still an attribute, because `uplers_apply` reads
    it off the row OBJECT - it is excluded from the PAYLOAD, which is the only
    place a caller ever sees. The next test is the one that stops that nuance
    being flattened into a delete.
    """
    raw = {
        "tailored_jobs": tailor_rows(),
        "my_feed": feed_rows(),
        "my_pipeline": pipeline_rows(),
    }[surface]
    rows = [talent_shape.to_talent_row(row, profile=profile) for row in raw]

    assert rows, "premise check - the fixture has rows"
    for row in rows:
        # enc_id: not on the model at all.
        assert "enc_id" not in row.__class__.model_fields
        assert "enc_id" not in row.model_dump()
        # job_id: on the model, never in the payload.
        assert "job_id" in row.__class__.model_fields
        assert "job_id" not in row.model_dump()
        assert "job_id" not in json.loads(row.model_dump_json())
        assert row.hr_number, "the handle a caller CAN act with must survive"


async def test_apply_still_reads_the_job_id_the_payload_no_longer_carries(
    monkeypatch, profile
):
    """__CONTROL. WATCH IT FAIL by deleting `job_id` from TalentRow the way
    `enc_id` was deleted: `uplers_apply` then raises AttributeError on
    `row.job_id` and the only write this server performs stops working.

    This is the test that makes the exclusion safe to keep. `job_id` is hidden
    from callers because no signature accepts it - but it is READ, off the row
    object, to build the apply body, and the two facts are easy to collapse into
    "unused, delete it". The preview path asserts the sent body without sending
    anything, which is exactly what it is for.
    """
    record = load_fixture(CONFIDO)
    record.update({"is_intrested": 0, "is_saved": 0, "job_not_interested": 0})
    wire_talent(monkeypatch, record)

    preview = await server.uplers_apply(record["HR_Number"], confirm=False)

    assert preview.performed is False, "a preview must send nothing"
    assert preview.body == {"hr_id": record["id"], "intrested": 1}
    assert record["id"] == 99101, "premise check - the numeric id is the one sent"


@pytest.mark.parametrize(
    "tool", ["uplers_my_feed", "uplers_my_pipeline", "uplers_tailored_jobs"]
)
async def test_no_tool_ADVERTISES_a_row_field_its_responses_never_contain(tool):
    """__CONTROL. WATCH IT FAIL by dropping `SkipJsonSchema` from `job_id`.

    FOUND BY HAND, AND IT IS THE HALF A PAYLOAD MEASUREMENT CANNOT SEE.
    `exclude=True` alone keeps a field out of every response while FastMCP goes
    on advertising it in the tool's declared output schema, because that schema
    is generated in VALIDATION mode. The payload measured clean and the contract
    still promised a `job_id` no response could ever carry.

    That is not a cosmetic mismatch - it is exactly the defect this whole pass
    calls the expensive one, inverted. A caller reads the schema, plans around a
    field, receives nothing, and spends a round-trip finding out. Better to
    never promise it.
    """
    tools = {t.name: t for t in await server.mcp.list_tools()}
    # Via the shared helper, NOT a hard-coded attribute name: this test read
    # `outputSchema` and found nothing on mcp 2.0.0, where it is `output_schema`.
    # Its premise check below is the only reason that did not pass vacuously.
    schema = tool_schema(tools[tool], "output")
    row_schema = (schema.get("$defs") or {}).get("TalentRow", {})

    advertised = set(row_schema.get("properties", {}))
    assert advertised, "premise check - the row schema was found"
    assert "hr_number" in advertised, "the handle must be advertised"
    assert not advertised & {"enc_id", "job_id"}, (
        "the schema promises an id no response contains"
    )


async def test_the_envelope_says_what_enc_id_was_and_why_it_is_gone(monkeypatch, profile):
    """__CONTROL. WATCH IT FAIL by deleting `row_fields_not_returned`.

    A silently absent field is indistinguishable from an oversight, and the
    next reader re-derives the whole question. The envelope names the field,
    names the route it addressed, and says it comes back if that write is
    built - so the absence reads as a decision.
    """
    wire_talent(monkeypatch, load_talent_fixture(TALENT_TAILOR))

    result = await server.uplers_tailored_jobs(score=True)

    dropped = result.row_fields_not_returned
    assert "enc_id" in dropped
    assert endpoints.EP_UPDATE_SAVED_HR in dropped["enc_id"]
    assert "hr_number" in dropped["enc_id"]


# ==========================================================================
# CONTROL 4 - sizes. Secondary here: relevance was the objective and the bytes
# are its by-product, so these are reported rather than chased.
#
# THE CEILINGS ARE ON THE ROWS, NOT ON THE PAYLOAD, and that is deliberate: the
# envelope GAINED the sentences the rows lost, and a budget that counted both
# would punish saying them at all. Neither is a round guess - each is the
# measured size plus enough headroom that rewording stays green and a hoisted
# block coming back goes red. Restoring `score_basis` per row costs 735; the
# `answered_note` and withheld markers cost 833 between them.
# ==========================================================================

#: MEASURED 2026-08-25 on tests/fixtures/talent_tailor.json: 1,842 bytes before
#: the hoist, 1,107 after. Budget 1,250 - 143 bytes of headroom, against 735
#: for the repeated caveat returning.
TAILORED_ROWS_BUDGET = 1250

#: MEASURED 2026-08-25 on tests/fixtures/outreach_value_with_happy.json: 1,887
#: bytes before, 1,054 after. Budget 1,150 - 96 bytes of headroom, against 448
#: for `answered_note` alone returning.
REPLY_ROWS_BUDGET = 1150


def test_the_tailored_rows_lost_the_repeated_prose_and_kept_everything_else(profile):
    rows = [talent_shape.to_talent_row(raw, profile=profile) for raw in tailor_rows()]
    talent_shape.hoist_shared_score_basis(rows)

    size = wire_bytes([row.model_dump() for row in rows])
    assert size <= TAILORED_ROWS_BUDGET, "tailored_jobs rows measured %d bytes" % size
    assert all(
        row.title and row.company and row.score for row in rows
    ), "nothing that informs the decision was dropped to hit the number"


def test_the_reply_rows_lost_the_repeated_prose_and_kept_everything_else():
    shaped = conversion.shape_reply_outcomes(load_fixture("outreach_value_with_happy"))

    size = wire_bytes(shaped["rows"])
    assert size <= REPLY_ROWS_BUDGET, "reply_outcomes rows measured %d bytes" % size
    for row in shaped["rows"]:
        assert row["company_name"]
        assert row["reply_category"]
        assert row["answered"] == "unknown"
