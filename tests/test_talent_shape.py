"""talent_shape.py - the authenticated projection, and its refusal to fake one.

The public shaper is tested next door in test_shaping.py. What is new here is
not shaping but REFUSAL. Every reader in this module raises when the envelope
is not the one it expects, because the failure it guards against is invisible:
a silently-empty feed reads as "no jobs matched you today", which is exactly
what a dead session, a renamed key or a changed paginator would also produce.
Most of this file is therefore one argument made repeatedly - an empty result
and a failed fetch must never look alike.

Every authenticated input below is one of the six captured live records plus
the keys a signed-in session adds. Nothing here is a 112-field record invented
from scratch, because such a record would only test the imagination that wrote
it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from uplers_server import fit, shaping, talent_shape
from uplers_server.talent import TalentError
from uplers_server.talent_models import TalentProfileResult

from conftest import (
    AGENTAI,
    AGGREGATED,
    ALL_IDS,
    CONFIDO,
    PRECISELY,
    TALENT_PIPELINE,
    load_fixture,
    load_talent_fixture,
)

#: The keys a session adds to a record the public catalogue also serves. An
#: authenticated record is the same record plus his own state and Uplers' own
#: verdict, so every input here is built by overlaying these on a capture.
SESSION_EXTRAS = {
    "is_intrested": 0,
    "is_saved": 0,
    "job_not_interested": 0,
    "statusName": "Profile Shared",
    "badgeName": "Slots Given",
}


def authenticated(hr_number: str, **extra) -> dict:
    """A captured live record as HIS account would serve it."""
    raw = load_fixture(hr_number)
    raw.update(SESSION_EXTRAS)
    raw.update(extra)
    return raw


def without(raw: dict, *keys: str) -> dict:
    """Drop keys, to model a feed that simply does not report them."""
    for key in keys:
        raw.pop(key, None)
    return raw


# --- unwrap_paginator: the loud-failure contract --------------------------


def test_a_paginated_envelope_yields_its_rows_and_where_in_the_feed_they_sat():
    payload = {
        "hrs": {
            "data": [{"HR_Number": "HR1"}, {"HR_Number": "HR2"}],
            "current_page": 2,
            "last_page": 5,
            "total": 50,
            "per_page": 10,
        }
    }
    rows, meta = talent_shape.unwrap_paginator(payload, route="talent/hr-list")

    assert [row["HR_Number"] for row in rows] == ["HR1", "HR2"]
    assert meta == {"page": 2, "last_page": 5, "total": 50, "per_page": 10}


def test_an_unpaginated_hrs_list_is_read_with_no_meta_rather_than_refused():
    """Some Laravel routes drop the paginator entirely when they do not page.

    That is a different SHAPE, not a broken response, so it must not take the
    raise path - but it also cannot invent page numbers it was never given.
    """
    rows, meta = talent_shape.unwrap_paginator(
        {"hrs": [{"HR_Number": "HR1"}]}, route="talent/hr-list"
    )
    assert [row["HR_Number"] for row in rows] == ["HR1"]
    assert meta == {}


def test_a_missing_hrs_envelope_says_in_words_that_this_is_not_an_empty_feed():
    """The whole module exists for this message.

    A caller that sees zero rows will tell him no jobs matched. The only thing
    standing between a changed API and that lie is this exception, so it has to
    deny the empty-result reading explicitly and show what it did receive.
    """
    with pytest.raises(TalentError) as excinfo:
        talent_shape.unwrap_paginator(
            {"jobs": [], "message": "ok"}, route="talent/hr-list"
        )

    message = str(excinfo.value)
    assert "NOT 'no jobs matched'" in message
    assert "talent/hr-list" in message
    assert "'jobs'" in message and "'message'" in message


@pytest.mark.parametrize(
    "payload",
    [
        ["hrs"],
        "hrs",
        {"data": [], "message": "ok"},
        {"hrs": None},
        {"hrs": "none"},
        {"hrs": 0},
        {"hrs": {"current_page": 1, "total": 0}},
        {"hrs": {"data": {"0": {"HR_Number": "HR1"}}}},
    ],
)
def test_no_malformed_envelope_is_allowed_to_read_as_an_empty_result(payload):
    """Every one of these would return [] under a forgiving reader.

    That is the bug class this server has been bitten by: the reader that
    shrugs produces a result the caller cannot tell from a real zero. There is
    no forgiving branch here on purpose.
    """
    with pytest.raises(TalentError):
        talent_shape.unwrap_paginator(payload, route="talent/hr-list")


@pytest.mark.parametrize(
    "payload, fragment",
    [
        (["hrs"], "returned list, not a JSON object"),
        ({"hrs": "none"}, "`hrs` as str"),
        ({"hrs": 0}, "`hrs` as int"),
        ({"hrs": {"current_page": 1}}, "no `data` list"),
    ],
)
def test_each_refusal_names_the_shape_it_actually_got(payload, fragment):
    """A raise that does not say WHAT arrived leaves the next reader guessing."""
    with pytest.raises(TalentError) as excinfo:
        talent_shape.unwrap_paginator(payload, route="talent/hr-list")
    assert fragment in str(excinfo.value)


def test_one_junk_row_does_not_cost_the_whole_page():
    """A stray null in `data` is a bad row, not a bad response.

    Raising here would throw away the good rows beside it, which is the
    opposite trade from the envelope check: there, nothing could be trusted;
    here, everything else can.
    """
    rows, _ = talent_shape.unwrap_paginator(
        {"hrs": {"data": [{"HR_Number": "HR1"}, "junk", None, 7, {"HR_Number": "HR2"}]}},
        route="talent/hr-list",
    )
    assert [row["HR_Number"] for row in rows] == ["HR1", "HR2"]


# --- truthy: tri-state ----------------------------------------------------


@pytest.mark.parametrize("value", [1, "1", True, "true", "True", "yes"])
def test_every_spelling_uplers_uses_for_yes_reads_as_yes(value):
    """The same flag arrives as 1, "1" and true depending on the route."""
    assert talent_shape.truthy(value) is True


@pytest.mark.parametrize("value", [0, "0", False, "false", "False", "no", ""])
def test_every_spelling_uplers_uses_for_no_reads_as_no(value):
    assert talent_shape.truthy(value) is False


def test_a_flag_the_payload_never_carried_is_none_not_false():
    """None means "this feed does not report it".

    False would be a different claim - that he has NOT applied - and the
    payload never made it. The distinction is load-bearing: uplers_apply
    refuses a duplicate on `applied is True`, so a fabricated False here would
    quietly turn "unknown" into "go ahead", against a route with no undo.
    """
    assert talent_shape.truthy(None) is None


@pytest.mark.parametrize("value", ["maybe", [], {}, 3.7, object()])
def test_an_unrecognised_value_is_none_rather_than_a_guess(value):
    """A value nobody has seen before is not evidence for either answer."""
    assert talent_shape.truthy(value) is None


# --- to_talent_row --------------------------------------------------------


@pytest.mark.parametrize("hr_number", ALL_IDS)
def test_the_row_is_the_public_projection_not_a_second_opinion(hr_number):
    """A fit score must mean the same thing on both tiers.

    It only can if the authenticated row is shaped by the SAME functions as
    the public one, so this asserts against their live output rather than
    against literals - a change in either is meant to move both together.
    """
    raw = authenticated(hr_number)
    opp = shaping.to_opportunity(raw)
    row = talent_shape.to_talent_row(raw)

    assert row.hr_number == opp.hr_number
    assert row.title == opp.title
    assert row.company == opp.company
    assert row.role == opp.role
    assert row.mode == opp.mode_of_work
    assert row.notice == opp.joining_period
    assert row.min_years_experience == opp.min_years_experience
    assert row.pay == fit.render_pay(opp)


def test_both_uplers_ids_are_read_and_neither_is_handed_to_a_caller():
    """`id` is what an apply sends; `enc_id` is what a save sends - and this
    server builds the apply and not the save.

    The record carries both, and NEITHER is returned, because no tool signature
    accepts either: an id a caller cannot pass anywhere is cost with no decision
    behind it. They differ only in how far the drop goes. `job_id` is still READ
    here - `uplers_apply` builds `{"hr_id": row.job_id}` off this object - so it
    survives as an excluded attribute; `enc_id` is consumed by nothing and is
    gone from the model outright.

    tests/test_row_relevance.py owns that rule, the envelope note that says both
    are absent on purpose, and the control proving apply breaks if `job_id` is
    deleted rather than excluded.
    """
    raw = authenticated(CONFIDO)
    assert (raw["id"], raw["enc_id"]) == (99101, "ODhDV1BIOWhmNzRDcEJEVnJ4UTRSQT09")

    row = talent_shape.to_talent_row(raw)
    assert row.job_id == 99101, "still read, off the object"
    assert {"job_id", "enc_id"}.isdisjoint(row.model_dump()), "neither in the payload"


def test_the_descent_still_reads_the_requisitions_enc_id_and_not_the_wrappers():
    """The overlay direction, proven where it now lives: on `job_view`.

    `enc_id` used to prove this from the row, and dropping it from the output
    must not drop the PROOF. On `my-opportunities` the wrapper is his
    application and its `enc_id` is HIS TALENT id - identical on every row -
    while the requisition's sits under `hr` and differs per row. A wrapper-first
    read would silently swap one for the other, so the descent is asserted here
    against the live capture instead of being inferred from a returned field.
    """
    rows = load_talent_fixture(TALENT_PIPELINE)["hrs"]["data"]
    assert len(rows) == 9

    wrapper_ids = {row["enc_id"] for row in rows}
    requisition_ids = {shaping.job_view(row)["enc_id"] for row in rows}

    assert len(wrapper_ids) == 1, "the wrapper's enc_id is his talent id, one value"
    assert len(requisition_ids) == 9, "the job's enc_id differs per requisition"
    assert wrapper_ids.isdisjoint(requisition_ids)


def test_a_missing_numeric_id_never_borrows_the_encrypted_one():
    """The likeliest silent bug against this API, so it gets its own test.

    The two ids live in different spaces, and an apply sent with the wrong one
    is a write against somebody else's requisition. The fixture's enc_id
    happens to be non-numeric, which would hide a fall-through by accident -
    so this hands it a numeric-LOOKING enc_id and still demands job_id be None.

    The plant stays even though `enc_id` is no longer returned: the risk this
    guards is a numeric-looking encrypted id being READ as the apply id, and
    that risk lives on the input side, not on the output side.
    """
    raw = without(authenticated(CONFIDO), "id", "hr_id")
    raw["enc_id"] = "987654"

    row = talent_shape.to_talent_row(raw)
    assert row.job_id is None
    assert "987654" not in str(row.model_dump())


@pytest.mark.parametrize("value", ["", "abc", "99101a", None, [], {"id": 1}])
def test_an_id_that_is_not_a_number_is_refused_rather_than_coerced(value):
    raw = without(authenticated(CONFIDO), "hr_id")
    raw["id"] = value
    assert talent_shape.to_talent_row(raw).job_id is None


def test_his_own_state_reads_uplers_own_spelling_of_it():
    """`is_intrested` is Uplers' spelling, misspelt at their end.

    It is tried FIRST, ahead of the corrected spellings, so the record below
    sets it to 1 while the plausible-looking `is_applied` says False: True
    proves the row followed the API rather than the tidier name.
    """
    raw = authenticated(
        CONFIDO, is_intrested=1, is_applied=False, is_saved=1, job_not_interested=1
    )
    row = talent_shape.to_talent_row(raw)
    assert (row.applied, row.saved, row.not_interested) == (True, True, True)

    quiet = talent_shape.to_talent_row(authenticated(CONFIDO))
    assert (quiet.applied, quiet.saved, quiet.not_interested) == (False, False, False)


def test_state_the_feed_does_not_report_is_none_not_false():
    """None and False are different claims and only one of them is honest here.

    None says the feed did not tell us. False says he has not applied. The
    apply route has no undo and guards on `applied is True`, so inventing the
    stronger claim is the expensive direction to be wrong in.
    """
    raw = without(
        authenticated(CONFIDO),
        "is_intrested",
        "is_interested",
        "applied",
        "is_applied",
        "is_saved",
        "saved",
        "job_not_interested",
    )
    row = talent_shape.to_talent_row(raw)

    assert row.applied is None
    assert row.saved is None
    assert row.not_interested is None


def test_uplers_own_verdict_lands_in_fields_this_server_never_writes():
    """Local state and Uplers state never share a field.

    That convention is the reason the authenticated tier is worth holding a
    session for: a local guess must not be able to overwrite the authoritative
    record. The row therefore has no `status` of its own to collide with.
    """
    row = talent_shape.to_talent_row(
        authenticated(CONFIDO, statusName="Interviewed", badgeName="Interview Scheduled")
    )
    assert row.uplers_status == "Interviewed"
    assert row.uplers_badge == "Interview Scheduled"
    assert not hasattr(row, "status")


def test_a_remote_role_drops_the_city_and_a_hybrid_one_keeps_it():
    """A Remote role's city names an office nobody attends.

    Same record, one field flipped, so the difference cannot be attributed to
    anything else in it.
    """
    hybrid = authenticated(CONFIDO)
    assert (hybrid["ModeOfWork"], hybrid["city"]) == ("Hybrid", "Bengaluru")
    assert talent_shape.to_talent_row(hybrid).city == "Bengaluru"

    remote = authenticated(CONFIDO, ModeOfWork="Remote")
    assert shaping.to_opportunity(remote).city == "Bengaluru"  # the record still names one
    assert talent_shape.to_talent_row(remote).city is None


def test_an_unscored_row_says_nothing_rather_than_scoring_zero():
    """Without a profile there is no basis for a number, and 0 is a number."""
    row = talent_shape.to_talent_row(authenticated(CONFIDO))
    assert row.score is None
    assert row.verdict is None
    assert row.gaps == []
    assert row.blockers == []


def test_a_scored_row_carries_the_fit_engines_own_answer(make_profile):
    """Comparability is the point, so the number is asserted against fit itself.

    If this file hardcoded the score it would still pass after a scoring change
    that silently desynchronised the two tiers.
    """
    profile = make_profile()
    raw = authenticated(CONFIDO)
    assessment = fit.assess(shaping.to_opportunity(raw), profile)

    row = talent_shape.to_talent_row(raw, profile=profile)
    assert row.score == assessment["overall_score"]
    assert row.verdict == fit.compact_verdict(assessment)
    assert row.blockers == assessment["blockers"]
    assert row.gaps == assessment["must_have"]["missing"][:3]
    assert len(row.gaps) <= 3


def test_posted_at_is_trimmed_to_a_date():
    """The seconds in an HR number are exact and nobody needs them."""
    raw = authenticated(CONFIDO)
    assert shaping.to_opportunity(raw).posted_at == "2025-07-10T00:19:19"
    assert talent_shape.to_talent_row(raw).posted_at == "2025-07-10"

    # The aggregated id carries no timestamp at all, and no date is invented.
    assert talent_shape.to_talent_row(authenticated(AGGREGATED)).posted_at is None


# --- to_talent_profile ----------------------------------------------------

PROFILE_PAYLOAD = {
    "talent_details": {
        "full_name": "Sundeep G",
        "headline": "Backend Engineer",
        "total_experience": "6.00",
        "city": "Bengaluru",
        "skills": [{"name": "Node.js"}, {"skill_name": "TypeScript"}],
        "roles": ["Backend Engineer", "SDE II"],
        "notice_period": "30 Days",
        "availability": {"name": "Full Time"},
    },
    "profile_completion_percentage": "85.00",
    "profile_remaining_percentage": "15.00",
}


def test_the_profile_block_projects_what_recruiters_actually_see():
    """This is the profile Uplers matches on, not the local one.

    This is the record Uplers' own matching runs on, so the completeness
    figure is projected beside the content rather than left behind in the
    envelope - reported as their number, not as a verdict on his profile.
    """
    result = talent_shape.to_talent_profile(PROFILE_PAYLOAD)

    assert result.name == "Sundeep G"
    assert result.headline == "Backend Engineer"
    assert result.years_experience == 6.0
    assert result.location == "Bengaluru"
    assert result.skills == ["Node.js", "TypeScript"]
    assert result.titles == ["Backend Engineer", "SDE II"]
    assert result.notice_period == "30 Days"
    assert result.availability == "Full Time"  # unwrapped from {"name": ...}
    assert result.completion_percentage == 85.0
    assert result.remaining_percentage == 15.0


@pytest.mark.parametrize(
    "skills",
    [
        ["Node.js", "TypeScript"],
        [{"name": "Node.js"}, {"skill_name": "TypeScript"}],
        [{"title": "Node.js"}, {"skill": "TypeScript"}],
        "Node.js, TypeScript",
        "Node.js ,  TypeScript ",
    ],
)
def test_skills_parse_from_every_shape_the_feed_has_been_seen_to_use(skills):
    """Three shapes, one list. All three have come off this API.

    The reader accepts all of them because a profile that read as skill-less
    would silently zero every must-have comparison downstream of it.
    """
    payload = {"talent_details": {"full_name": "X", "skills": skills}}
    assert talent_shape.to_talent_profile(payload).skills == ["Node.js", "TypeScript"]


def test_duplicate_skills_collapse_and_the_original_order_survives():
    """Order is meaning here - Uplers' own list is priority-ordered."""
    details = {"full_name": "X", "skills": ["React", "Node.js", "React", "AWS"]}
    assert talent_shape.to_talent_profile({"talent_details": details}).skills == [
        "React",
        "Node.js",
        "AWS",
    ]


def test_a_full_name_wins_and_a_lone_surname_is_still_a_name():
    """The name parts are a fallback, not a competitor to full_name."""
    both = {"full_name": "Sundeep Gowda", "first_name": "Sundeep", "last_name": "Gowda"}
    assert talent_shape.to_talent_profile({"talent_details": both}).name == "Sundeep Gowda"

    surname_only = {"last_name": "Gowda", "headline": "Backend Engineer"}
    assert talent_shape.to_talent_profile({"talent_details": surname_only}).name == "Gowda"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "success", "data": {"full_name": "X"}},
        {"talent_details": {}},
        {"talent_details": []},
        {"talent_details": "none"},
        {"talent_details": None},
        "not json",
        None,
        [],
    ],
)
def test_no_unreadable_envelope_is_allowed_to_read_as_an_empty_profile(payload):
    with pytest.raises(TalentError):
        talent_shape.to_talent_profile(payload)


def test_an_unreadable_profile_raises_instead_of_returning_a_blank_one():
    """An empty profile and an unreadable one lead to OPPOSITE actions.

    The first says "go and fill your profile in". The second says "this client
    is broken". The blank result asserted below is what a forgiving reader
    would hand back, and it serialises to nothing at all - literally
    indistinguishable from a real but empty Uplers profile.
    """
    assert TalentProfileResult().model_dump() == {}

    with pytest.raises(TalentError) as excinfo:
        talent_shape.to_talent_profile({"status": "success", "data": {"full_name": "X"}})

    message = str(excinfo.value)
    assert "NOT an empty profile" in message
    assert "talent_details" in message
    assert "'data'" in message and "'status'" in message


def test_sections_present_lists_only_the_blocks_that_carried_content():
    """A key that arrived empty is not a section he has filled in.

    This list is read as "what your profile actually has", so counting empty
    keys would flatter it in exactly the place he would act on it.
    """
    details = {
        "full_name": "Sundeep G",
        "skills": ["React"],
        "resume": "",
        "projects": [],
        "education": None,
        "certificates": {},
    }
    result = talent_shape.to_talent_profile({"talent_details": details})
    assert result.sections_present == ["full_name", "skills"]


# --- field_report: what the session actually buys -------------------------


def test_the_report_names_exactly_what_the_session_buys():
    """The tier's own justification, made measurable.

    If the authenticated record carried nothing the public one lacks there
    would be no reason to hold a session at all, so this list is the argument
    for the whole tier and has to be exact in both directions.
    """
    public = dict(load_fixture(CONFIDO))
    public["public_only"] = "catalogue blurb"
    auth = dict(public)
    del auth["public_only"]
    auth.update({"statusName": "Interviewed", "badgeName": "Slots Given", "is_intrested": 1})

    report = talent_shape.field_report(auth, public)

    assert report.only_in_authenticated == ["badgeName", "is_intrested", "statusName"]
    assert report.only_in_public == ["public_only"]
    assert report.hr_number == CONFIDO
    assert report.title == "Graphic Designer"

    shared = {
        key
        for key in public
        if public.get(key) not in (None, "", [], {}) and key != "public_only"
    }
    assert report.in_both == len(shared)


def test_a_key_that_arrived_empty_counts_as_present_on_neither_side():
    """A null is not a field the session bought.

    Reporting `foo: None` as an authenticated-only field would inflate the
    tier's justification with keys that carry nothing - and the same emptiness
    on the public side would then read as a loss.
    """
    public = {"HR_Number": "HR1", "RequestForTalent": "Backend Engineer"}
    auth = dict(public)
    auth.update({"foo": None, "bar": "", "baz": [], "qux": {}})

    report = talent_shape.field_report(auth, public)

    for key in ("foo", "bar", "baz", "qux"):
        assert key not in report.only_in_authenticated
        assert key not in report.only_in_public
        assert key not in report.values
    assert report.in_both == 2


def test_authenticated_values_are_previewed_never_dumped_whole():
    """A field report nobody can read is not a report.

    A nested company object or a 40-entry list would swamp the page it is
    supposed to justify, so containers report their size and long strings are
    cut - the reader is deciding whether the field EXISTS, not reading it.
    """
    public = {"HR_Number": "HR1"}
    auth = {
        "HR_Number": "HR1",
        "blob": {"a": 1, "b": 2, "c": 3},
        "many": [1, 2, 3, 4, 5],
        "long": "x" * 300,
    }

    report = talent_shape.field_report(auth, public)
    assert report.values["blob"] == "dict(3)"
    assert report.values["many"] == "list(5)"
    assert len(report.values["long"]) == talent_shape._VALUE_PREVIEW_CHARS


# --- compare_profiles -----------------------------------------------------


def test_agreement_and_disagreement_are_reported_apart(make_profile):
    """Reports, never overwrites - which one is WRONG is his call.

    Case and surrounding blanks are not disagreements; a different number of
    years is.
    """
    local = make_profile(
        name="Sundeep G",
        location="Bengaluru",
        years_experience=5.0,
        notice_period_days=60,
    )
    remote = TalentProfileResult(
        name="sundeep g",
        location="  Bengaluru  ",
        years_experience=6.0,
        notice_period="30",
    )

    agree, differ, _, _, _ = talent_shape.compare_profiles(local, remote)
    assert "name" in agree
    assert "location" in agree

    by_field = {diff.field: diff for diff in differ}
    assert by_field["years_experience"].local == "5.0"
    assert by_field["years_experience"].uplers == "6.0"
    assert by_field["notice_period"].local == "60 days"
    assert by_field["notice_period"].uplers == "30"


def test_a_field_uplers_does_not_report_is_a_silence_not_a_disagreement(make_profile):
    """Silences must appear in NEITHER list.

    Uplers holding no headline is not Uplers disagreeing about his headline.
    Filing it as a diff would bury the two or three real conflicts under a
    dozen fields nobody is arguing about, which is how a comparison stops
    being read at all.
    """
    local = make_profile(headline="Backend Engineer", notice_period_days=30)
    remote = TalentProfileResult(name=local.name)

    agree, differ, _, _, _ = talent_shape.compare_profiles(local, remote)

    assert "headline" not in agree
    assert "headline" not in [diff.field for diff in differ]
    assert "notice_period" not in agree
    assert "notice_period" not in [diff.field for diff in differ]
    assert agree == ["name"]


def test_a_field_only_uplers_has_is_a_diff_that_says_local_is_not_set(make_profile):
    """The reverse silence IS actionable: it names something to copy home."""
    local = make_profile(headline=None)
    remote = TalentProfileResult(headline="Senior Node.js Engineer")

    _, differ, _, _, _ = talent_shape.compare_profiles(local, remote)
    diff = next(item for item in differ if item.field == "headline")

    assert diff.local == "(not set)"
    assert diff.uplers == "Senior Node.js Engineer"
    assert diff.note == "Only Uplers has this - copy it into the local profile."


def test_skill_case_is_not_a_disagreement(make_profile):
    """"React" and "react" are the same skill and jobcore already knows it.

    A case-sensitive diff would report a dozen conflicts across two identical
    lists, and he would stop reading the list that is supposed to catch the
    real gap.
    """
    local = make_profile(skills=["React", "Node.js", "AWS"])
    remote = TalentProfileResult(skills=["react", "NODE.JS", "aws"])

    agree, _, only_local, only_uplers, _ = talent_shape.compare_profiles(local, remote)
    assert only_local == []
    assert only_uplers == []
    assert "skills" in agree


def test_the_only_lists_are_sorted_and_keep_the_original_spelling(make_profile):
    """Matching is case-insensitive; DISPLAY is not.

    He has to recognise his own skill in the list, so the spelling that comes
    back is the one that was written, not the lowercased comparison key.
    """
    local = make_profile(skills=["React", "Kubernetes", "AWS"])
    remote = TalentProfileResult(skills=["react", "Terraform", "Docker"])

    agree, _, only_local, only_uplers, _ = talent_shape.compare_profiles(local, remote)
    assert only_local == ["AWS", "Kubernetes"]
    assert only_uplers == ["Docker", "Terraform"]
    assert "skills" not in agree


# --- interviews -----------------------------------------------------------


def test_a_success_envelope_yields_the_interviews_it_carries():
    payload = {
        "status": "success",
        "data": [
            {
                "company_name": "Acme",
                "company_id": "42",
                "RequestForTalent": "Backend Engineer",
                "status": "Scheduled",
                "scheduled_at": "2026-08-01 10:30:00",
                "is_feedback_given": 1,
            },
            "junk",
        ],
    }
    interviews, notes = talent_shape.interviews_from(payload)

    assert len(interviews) == 1  # the junk row is skipped, not fatal
    assert interviews[0].company == "Acme"
    assert interviews[0].company_id == 42
    assert interviews[0].role == "Backend Engineer"
    assert interviews[0].status == "Scheduled"
    assert interviews[0].scheduled_at == "2026-08-01 10:30:00"
    assert interviews[0].feedback_given is True
    assert notes == []


@pytest.mark.parametrize(
    "payload",
    [{"status": "success"}, {"status": "success", "data": {}}, {"data": "none"}, None, []],
)
def test_a_missing_data_array_never_reads_as_an_empty_diary(payload):
    """An empty diary is a fact about his week; this is a fact about the client.

    Confusing them would tell him nothing is scheduled on the day a broken
    session means he cannot see what is.
    """
    with pytest.raises(TalentError):
        talent_shape.interviews_from(payload)


def test_the_refusal_denies_the_empty_diary_reading_in_words():
    with pytest.raises(TalentError) as excinfo:
        talent_shape.interviews_from({"status": "success", "message": "ok"})

    message = str(excinfo.value)
    assert "NOT 'no interviews scheduled'" in message
    assert "'message'" in message and "'status'" in message


def test_a_non_success_status_is_surfaced_rather_than_swallowed():
    """The rows are readable, so this is a note and not a raise.

    But it is still something the client said about its own answer, and
    dropping it would let a degraded response pass as a clean one.
    """
    interviews, notes = talent_shape.interviews_from({"status": "error", "data": []})
    assert interviews == []
    assert any("error" in note for note in notes)
    # An empty list now also carries its own diagnosis, so this is no longer the
    # only note. The count was never what mattered - that the client's own
    # complaint survives is.
    assert any("meta" in note for note in notes)


# --- is_test_record / rows_from -------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"is_test_hr": 1}, True),
        ({"is_test_hr": "1"}, True),
        ({"is_test_hr": True}, True),
        ({"is_test_hr": 0}, False),
        ({"is_test_hr": None}, False),
        ({}, False),
    ],
)
def test_only_an_explicit_test_flag_marks_a_test_requisition(raw, expected):
    """Uplers' own UI gates rendering on `1 != is_test_hr`, so this matches it.

    An absent flag is not a test record - defaulting the other way would hide
    real requisitions from a feed whose whole job is to show them.
    """
    assert talent_shape.is_test_record(raw) is expected


def test_rows_from_hides_test_requisitions_and_says_how_many_in_words():
    """A row silently removed is a row he cannot ask about.

    The count is stated because "9 of 10" with no explanation is exactly the
    unexplained shortfall this server refuses to produce anywhere else.
    """
    payload = {
        "hrs": {
            "data": [
                authenticated(CONFIDO),
                authenticated(PRECISELY, is_test_hr=1),
                authenticated(AGENTAI),
            ],
            "current_page": 1,
            "last_page": 3,
        }
    }
    rows, meta, notes = talent_shape.rows_from(payload, route="talent/hr-list")

    assert [row.hr_number for row in rows] == [CONFIDO, AGENTAI]
    assert meta["page"] == 1
    assert meta["last_page"] == 3
    assert len(notes) == 1
    assert "1 internal test requisition" in notes[0]
    assert "is_test_hr" in notes[0]


def test_rows_from_stays_quiet_when_there_was_nothing_to_hide():
    """A note that always fires is a note nobody reads."""
    rows, _, notes = talent_shape.rows_from(
        {"hrs": {"data": [authenticated(CONFIDO)]}}, route="talent/hr-list"
    )
    assert len(rows) == 1
    assert notes == []


def test_a_caller_can_ask_to_see_the_test_records():
    """The drop is a default, not a censor - otherwise it could not be audited."""
    payload = {"hrs": {"data": [authenticated(CONFIDO), authenticated(PRECISELY, is_test_hr=1)]}}
    rows, _, notes = talent_shape.rows_from(
        payload, route="talent/hr-list", drop_test_records=False
    )
    assert [row.hr_number for row in rows] == [CONFIDO, PRECISELY]
    assert notes == []


def test_rows_from_raises_on_a_bad_envelope_like_everything_else_here():
    """The drop-and-count path must not become a way to launder a zero."""
    with pytest.raises(TalentError):
        talent_shape.rows_from({"message": "ok"}, route="talent/hr-list")


def test_tally_counts_uplers_own_statuses_commonest_first():
    rows, _, _ = talent_shape.rows_from(
        {
            "hrs": {
                "data": [
                    authenticated(CONFIDO, statusName="Interviewed"),
                    authenticated(AGENTAI, statusName="Profile Shared"),
                    authenticated(PRECISELY, statusName="Interviewed"),
                ]
            }
        },
        route="talent/hr-list",
    )
    assert talent_shape.tally(rows, "uplers_status") == {"Interviewed": 2, "Profile Shared": 1}


# --- regression tests for two defects found by testing, now fixed ---------
#
# Both were found by writing these tests against what the module's docstrings
# SAID it did, and both were pinned as xfail(strict=True) until the fix landed.
# They stay because each one describes a mistake that is easy to make again:
# guessing an extra field spelling that turns out to name a different field,
# and writing a fallback branch that an earlier candidate makes unreachable.


def test_a_record_that_carries_no_status_name_still_shapes():
    """Every captured live record carries `status: 1`.

    That is a numeric state flag, not a pipeline status - and `status` is the
    third candidate spelling to_talent_row tries for uplers_status. A record
    without a statusName therefore hands an int to a str field. This is not a
    hypothetical path: uplers_apply and uplers_dismiss both shape a record
    resolved from the store, which is exactly this shape.
    """
    row = talent_shape.to_talent_row(load_fixture(CONFIDO))
    assert row.uplers_status is None or isinstance(row.uplers_status, str)


def test_both_name_parts_survive_when_there_is_no_full_name():
    """The fallback is written as first + last but cannot reach that branch.

    `_first` lists `first_name` among its own candidates, so it returns a
    truthy value and the concatenation below it never runs. A profile carrying
    both parts comes back as the given name alone, and the surname is lost
    without a word.
    """
    details = {"first_name": "Sundeep", "last_name": "Gowda"}
    assert talent_shape.to_talent_profile({"talent_details": details}).name == "Sundeep Gowda"
