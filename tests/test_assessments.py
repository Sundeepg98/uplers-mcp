"""His OWN assessment record - the half of the assessment story that was missing.

The catalogue half has been built since day one: every public record carries an
`assessments` array, `Opportunity.assessments_required` counts it, and
`fit.assess` raises a flag when it is non-zero. All of that answers "what does
this REQUISITION demand".

Nothing answered "what has HE already sat", and on this board that is not a
detail: 99 of the 250 records in the local index carry a non-empty assessments
array, so 40% of the reachable work is gated behind an AiInterview or a
TestGorilla test. Without the second half, a required assessment reads as an
obstacle even when it is an afternoon already spent - and, the other way round,
a stalled application gives up no clue that an unsat test is why.

THE ENVELOPE IS A CAPTURE, NOT A GUESS. `tests/fixtures/talent_assessments.json`
came off his live session on 2026-08-22 via `scripts/capture_assessments.py`.
That matters twice over here:

  * the bundle's call site is `(0,i.Yr)(o.TU).then(function(e){t(e.data.data)})`,
    which reads naturally as "data is the list". It is NOT: `data` is an OBJECT
    with four keys and the list is `data.assessments`. A shaper written from the
    bundle alone would have iterated a dict and produced four garbage rows named
    after its keys.
  * `status` on this route is the integer **200** - neither the string
    "success" nor the numeric 1 that `endpoints.py` already warns are both in
    use. Three idioms, on one API.
"""

from __future__ import annotations

import pytest

from conftest import load_talent_fixture
from test_talent_tools import serve, wire_talent, writes

import server
from uplers_server import endpoints, talent_shape
from uplers_server.talent import TalentError
from uplers_server.talent_models import MyAssessments


TALENT_ASSESSMENTS = "talent_assessments"


def live() -> dict:
    """The captured live envelope, verbatim."""
    return load_talent_fixture(TALENT_ASSESSMENTS)


# --- the captured envelope ------------------------------------------------


def test_the_captured_envelope_still_has_the_shape_the_shaper_expects():
    """Pins the capture itself, so a re-capture that drifts fails here first.

    Without this, a shaper bug and a shape change look identical downstream.
    """
    payload = live()
    assert payload["status"] == 200
    assert isinstance(payload["status"], int)
    data = payload["data"]
    assert isinstance(data, dict), "data is an OBJECT, not the list"
    assert sorted(data) == ["assessments", "cleared", "searchedkills", "skillMaster"]
    assert isinstance(data["assessments"], list)


async def test_reads_his_real_record(monkeypatch):
    calls = wire_talent(monkeypatch, serve(live()))

    result = await server.uplers_my_assessments()

    assert isinstance(result, MyAssessments)
    assert result.taken == 0
    assert result.cleared == 0
    assert result.assessments == []
    assert calls[0].url.path.endswith(endpoints.EP_ASSESSMENTS)
    assert not calls[0].url.params, "this route takes no params"


async def test_it_only_reads(monkeypatch):
    calls = wire_talent(monkeypatch, serve(live()))

    await server.uplers_my_assessments()

    assert writes(calls) == []


# --- the zero has two readings and the payload says which -----------------


async def test_an_empty_record_says_it_is_empty_rather_than_looking_broken(monkeypatch):
    """A bare `taken: 0` cannot distinguish "never sat one" from "read failed".

    Same discipline as `interviews_from`: the count alone is ambiguous, so the
    tool must say which zero this is.
    """
    wire_talent(monkeypatch, serve(live()))

    result = await server.uplers_my_assessments()

    assert result.notes, "an empty record must explain itself"
    joined = " ".join(result.notes).lower()
    assert "not" in joined or "no assessment" in joined


async def test_the_empty_note_points_at_where_he_can_sit_one(monkeypatch):
    """An empty record is only useful if it also says what to do about it."""
    wire_talent(monkeypatch, serve(live()))

    result = await server.uplers_my_assessments()

    assert any("assessment" in note.lower() for note in result.notes)


# --- a populated record ---------------------------------------------------


#: One sat assessment. Field spellings are VERIFIED from two places, because
#: his own list is empty and could not supply them:
#:   * the master shape carried on every public record's `assessments[]`
#:     (`tests/fixtures/_survey.json` -> `assessment_shape`): `name`,
#:     `assessment_tool`, `duration_formatted`, `enc_id`, nested `assessment`.
#:   * the bundle's `assign-assessment` / `re-test` call sites, which read
#:     `enc_id`, `status` (numeric; 4 == complete), `result` ("Passed") and
#:     `assessment_tool` off an assessment row.
SAT_ROW = {
    "id": 272,
    "enc_id": "G7X0jfndlaq3PPp8MQTgcc2pOLFcZV91",
    "name": "AiInterview",
    "assessment_tool": "AiInterview",
    "status": 4,
    "result": "Passed",
    "duration_formatted": " 30 Mins",
    "assessment": {"name": "AiInterview"},
}


def populated(rows, cleared=1):
    return {
        "status": 200,
        "data": {
            "assessments": rows,
            "skillMaster": [],
            "searchedkills": [],
            "cleared": cleared,
        },
    }


async def test_a_sat_assessment_is_read_in_full(monkeypatch):
    wire_talent(monkeypatch, serve(populated([SAT_ROW])))

    result = await server.uplers_my_assessments()

    assert result.taken == 1
    assert result.cleared == 1
    row = result.assessments[0]
    assert row.name == "AiInterview"
    assert row.tool == "AiInterview"
    assert row.result == "Passed"
    assert row.duration == "30 Mins"
    assert row.complete is True


async def test_an_in_progress_assessment_is_not_reported_as_complete(monkeypatch):
    """VERIFIED in the bundle: status 4 means complete, anything below does not."""
    wire_talent(monkeypatch, serve(populated([{**SAT_ROW, "status": 2, "result": None}])))

    result = await server.uplers_my_assessments()

    assert result.assessments[0].complete is False
    assert result.assessments[0].result is None


async def test_a_row_that_yields_nothing_recognisable_is_flagged_not_dropped(monkeypatch):
    """His list was empty at capture, so the ROW shape is the one unverified part.

    A row spelled some other way must therefore surface as a note rather than
    vanish - a silently dropped row would read as "you have sat fewer than you
    have", which is the failure this tool exists to prevent.
    """
    wire_talent(monkeypatch, serve(populated([{"unexpected_key": 1}], cleared=0)))

    result = await server.uplers_my_assessments()

    assert result.taken == 1, "the row is still counted"
    assert any("could not be read" in note.lower() for note in result.notes)


# --- loud failure ---------------------------------------------------------


async def test_a_missing_data_object_raises_rather_than_reporting_zero(monkeypatch):
    """"No assessments" and "the read failed" must never render the same."""
    wire_talent(monkeypatch, serve({"status": 200}))

    with pytest.raises(TalentError) as excinfo:
        await server.uplers_my_assessments()

    assert "assessments" in str(excinfo.value).lower()


async def test_a_data_list_instead_of_an_object_raises(monkeypatch):
    """The shape a bundle-only reading would have produced. It must not pass."""
    wire_talent(monkeypatch, serve({"status": 200, "data": []}))

    with pytest.raises(TalentError):
        await server.uplers_my_assessments()


async def test_a_missing_assessments_key_raises(monkeypatch):
    wire_talent(monkeypatch, serve({"status": 200, "data": {"cleared": 0}}))

    with pytest.raises(TalentError):
        await server.uplers_my_assessments()


async def test_an_unhappy_status_is_reported_but_does_not_hide_the_rows(monkeypatch):
    """Third success idiom on this API. An odd value is worth saying out loud."""
    payload = populated([SAT_ROW])
    payload["status"] = 500
    wire_talent(monkeypatch, serve(payload))

    result = await server.uplers_my_assessments()

    assert result.taken == 1
    assert any("500" in note for note in result.notes)


# --- the shaper, directly -------------------------------------------------


def test_shaper_rejects_a_non_dict_payload():
    with pytest.raises(TalentError):
        talent_shape.my_assessments_from([])


def test_shaper_keeps_cleared_even_when_it_disagrees_with_the_row_count():
    """`cleared` is Uplers' own counter, not something to recompute from rows.

    Reporting a derived count would silently overwrite their number with ours
    on any row shape we read imperfectly.
    """
    result = talent_shape.my_assessments_from(populated([SAT_ROW], cleared=7))

    assert result.cleared == 7
    assert result.taken == 1
