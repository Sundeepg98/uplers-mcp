"""preference.py - proving the id-to-label join actually joins.

`talent/get-preference` stores what he wants as IDS and ships the dictionaries
that name them in the same response. A shaper that returns the ids is
obviously useless and would be caught in a minute. A shaper that resolves them
by POSITION instead of by MATCH is the dangerous one: it returns real labels
from the real table, in the right shape, and is simply wrong. On this payload
a take-the-first resolver would report him as "Remote Only" when he is "Remote
or Office", and as "just_exploring" when he is "actively_applying" - both
credible, neither true.

This repo has been bitten by the un-joined version of this bug already: the
day the profile shaper skipped its masters join it reported a 61-skill profile
as 0 skills and advised him to go and fill it in. `talent_shape.MASTERS_KEY`
carries that receipt. So every join below is asserted against a row that is
NOT at index 0, and each such assertion is paired with a control that computes
what the broken implementation would have said and requires it to differ.

Input is `tests/fixtures/talent_preference.json`, captured live on 2026-08-23
from a real 200. Nothing here is hand-written: a few tests overlay one field
on a deep copy of that capture, which is the only way to exercise a case his
live record does not contain.
"""

from __future__ import annotations

import ast
import copy
import re
from pathlib import Path

import pytest

from uplers_server import preference
from uplers_server.preference import UNRESOLVED, shape_preference

from conftest import load_talent_fixture

PREFERENCE = "talent_preference"

#: Everything the shaper emits. Asserted as a whole so a field cannot appear
#: or vanish without this file being updated on purpose.
SHAPED_KEYS = [
    "applications_per_day",
    "availability",
    "current_location",
    "interested_job_functions",
    "interviews_per_week",
    "job_search_preference",
    "job_search_unavailable_until",
    "job_title",
    "joining_period",
    "last_working_day",
    "masters_present",
    "preferred_cities",
    "preferred_method",
    "preferred_modes",
    "serving_notice_period",
    "snooze_count",
    "target_company_types",
    "top_skills",
    "total_experience",
    "total_experience_years",
    "unresolved",
    "user_journey_status",
    "user_journey_sub_statuses",
]

#: The brief's exclusion list, as one expression. Applied to every key name in
#: the shaped tree, at any depth.
PRIVATE_KEY_RE = re.compile(r"ctc|salary|compensation|resume|email|phone|contact", re.I)


@pytest.fixture
def live():
    """The captured get-preference envelope, whole and unmodified."""
    return load_talent_fixture(PREFERENCE)


@pytest.fixture
def shaped(live):
    return shape_preference(live)


def all_keys(value, found=None):
    """Every key name anywhere in a nested structure."""
    found = set() if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key))
            all_keys(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            all_keys(item, found)
    return found


# --- the envelope this was built against -----------------------------------


def test_the_capture_is_the_three_block_envelope_the_shaper_expects(live):
    assert sorted(live) == ["masters", "snooze", "talent"]
    assert isinstance(live["talent"], dict)
    assert isinstance(live["masters"], dict)
    assert len(live["masters"]) == 11


def test_the_shaper_emits_exactly_the_documented_field_set(shaped):
    assert sorted(shaped) == SHAPED_KEYS


# --- the join: SELECT, never take-the-first --------------------------------


def test_his_stored_preference_comes_back_as_words_not_ids(shaped, live):
    """The headline. Every one of these is an id in the raw record."""
    masters = live["masters"]

    assert shaped["job_search_preference"]["label"] == "Actively Looking"
    assert shaped["user_journey_status"]["label"] == "actively_applying"
    assert shaped["preferred_method"]["label"] == "Remote or Office"
    assert shaped["current_location"]["label"] == "Bengaluru"
    assert [city["label"] for city in shaped["preferred_cities"]] == ["Bengaluru"]
    # Read from the master rather than typed out: this label is not ASCII.
    assert shaped["target_company_types"][0]["label"] == (
        masters["preferredCompanyTypesMaster"][5]["label"]
    )


def test_the_resolver_selects_the_matching_row_not_the_first__control(shaped, live):
    """__CONTROL. The join is asserted against a row that is NOT index 0.

    His `preferred_method` is "2", and `preferredMethodMaster` holds value 2 at
    index 1. The two rows carry different labels, which is what makes the
    assertion able to fail; if the master ever collapses to one row this test
    stops discriminating, so that is asserted too.
    """
    master = live["masters"]["preferredMethodMaster"]

    assert master[0]["label"] != master[1]["label"], "the control has stopped controlling"
    assert master[1]["value"] == 2
    assert shaped["preferred_method"]["id"] == "2"
    assert shaped["preferred_method"]["label"] == master[1]["label"]
    assert shaped["preferred_method"]["label"] != master[0]["label"]


def test_a_take_the_first_resolver_would_answer_differently_on_four_fields__control(
    shaped, live
):
    """__CONTROL. Computes what ``masters[table][0]`` would have said.

    Four independent fields, four different tables, and in every case the
    broken answer is a real label off the real table - which is exactly why
    this failure survives a naive test.
    """
    masters = live["masters"]
    cases = (
        ("preferred_method", "preferredMethodMaster", shaped["preferred_method"]),
        ("user_journey_status", "userJourneyStatusMaster", shaped["user_journey_status"]),
        ("current_location", "cities", shaped["current_location"]),
        (
            "target_company_types",
            "preferredCompanyTypesMaster",
            shaped["target_company_types"][0],
        ),
    )

    for field, table, entry in cases:
        naive = masters[table][0]["label"]
        assert entry["resolved"] is True, field
        assert entry["label"] != naive, (
            "%s resolved to the FIRST row of %s, which is what a positional "
            "lookup returns instead of a join" % (field, table)
        )


def test_a_master_is_not_ordered_by_its_own_id(live):
    """Why a positional lookup is not merely sloppy but wrong.

    `jobSearchPreferenceMaster` runs 1, 3, 2 - index 1 holds value 3. Anything
    that treats position as identity is broken on this table by construction.
    """
    values = [row["value"] for row in live["masters"]["jobSearchPreferenceMaster"]]

    assert values == [1, 3, 2]
    assert values != sorted(values)


def test_ids_are_matched_across_the_string_integer_divide(shaped, live):
    """The payload disagrees with itself about type, so both sides get str().

    `job_search_preference` is the INTEGER 1; `preferred_method` is the STRING
    "2"; both masters write `value` as an int. An untyped comparison resolves
    one of them and silently misses the other.
    """
    talent = live["talent"]

    assert talent["job_search_preference"] == 1
    assert isinstance(talent["job_search_preference"], int)
    assert talent["preferred_method"][0]["preferred_method"] == "2"
    assert isinstance(talent["preferred_method"][0]["preferred_method"], str)

    assert shaped["job_search_preference"]["resolved"] is True
    assert shaped["preferred_method"]["resolved"] is True


# --- the cities table keys itself differently ------------------------------


def test_cities_key_their_id_under_id_while_every_other_master_uses_value(live):
    """Measured: 10 of 11 masters are {label, value}; `cities` adds `id`.

    In `cities`, `value` carries the city NAME and `id` carries the 277-style
    key his record actually references.
    """
    masters = live["masters"]

    for name, rows in masters.items():
        if name == "cities":
            continue
        assert sorted(rows[0]) == ["label", "value"], name

    assert sorted(masters["cities"][0]) == ["id", "label", "value"]
    assert isinstance(masters["cities"][0]["value"], str)
    assert isinstance(masters["cities"][0]["id"], int)


def test_indexing_cities_by_value_would_not_resolve_his_city__control(live):
    """__CONTROL. Builds the value-keyed index and shows it missing.

    This is the shape `talent_shape.masters_index` builds - correctly, for the
    profile payload's masters, none of which carry an `id`. Reusing it here
    would have produced a name-to-name map and left his city unresolved, with
    no error anywhere.
    """
    cities = live["masters"]["cities"]
    by_value = {str(row["value"]): row["label"] for row in cities}
    by_id = preference._master_lookup(cities)

    assert "277" not in by_value, "the control has stopped controlling"
    assert by_id["277"] == "Bengaluru"
    assert by_value["Bengaluru"] == "Bengaluru"


def test_the_record_label_and_the_master_label_are_both_kept(shaped):
    """They disagree, harmlessly: the record says "Bengaluru, Karnataka" and
    `cities` says "Bengaluru". `label` is always the master's answer."""
    location = shaped["current_location"]

    assert location["label"] == "Bengaluru"
    assert location["given_label"] == "Bengaluru, Karnataka"
    assert location["master"] == "cities"


# --- unresolved is reported, never guessed and never None ------------------


def test_an_id_with_no_master_row_comes_back_as_the_explicit_marker(live):
    """One field overlaid on the capture, because his real record resolves."""
    broken = copy.deepcopy(live)
    broken["talent"]["job_search_preference"] = 999

    entry = shape_preference(broken)["job_search_preference"]

    assert entry["id"] == "999"
    assert entry["label"] == UNRESOLVED
    assert entry["resolved"] is False
    assert entry["master"] == "jobSearchPreferenceMaster"


def test_an_unresolved_id_is_never_none_and_never_a_real_looking_label__control(live):
    """__CONTROL. A silent None reads as "he did not set this", which is a
    different and far less alarming claim than "we could not name what he set".

    The second half is what makes the marker meaningful: the SAME shaper on the
    SAME field with a resolvable id returns a real label, so `UNRESOLVED` is
    not simply what this field always says.
    """
    broken = copy.deepcopy(live)
    broken["talent"]["job_search_preference"] = 999
    entry = shape_preference(broken)["job_search_preference"]

    real_labels = {row["label"] for row in live["masters"]["jobSearchPreferenceMaster"]}
    assert entry["label"] is not None
    assert entry["label"] not in real_labels

    assert shape_preference(live)["job_search_preference"]["label"] == "Actively Looking"


def test_a_field_he_never_set_is_none_rather_than_unresolved(shaped, live):
    """Not-set and cannot-resolve are different answers and must look different.

    `availability` is null on his live record, so there is no id to fail to
    resolve and nothing to report as a gap.
    """
    assert live["talent"]["availability"] is None
    assert shaped["availability"] is None
    assert shaped["last_working_day"] is None
    assert "availabilityMaster:" not in " ".join(shaped["unresolved"])


def test_preferred_modes_have_no_master_in_this_payload_and_say_so(shaped, live):
    """Measured gap, reported rather than filled in.

    The ids are 1 and 3. The `talent/profile` payload names the same two ids
    "Full time" and "Contract", but that is a different response and this one
    cannot prove it, so nothing is imported.
    """
    assert live["talent"]["preferred_modes"] == [1, 3]
    assert "preferred_modes" not in live["masters"]

    assert [entry["id"] for entry in shaped["preferred_modes"]] == ["1", "3"]
    for entry in shaped["preferred_modes"]:
        assert entry["label"] == UNRESOLVED
        assert entry["resolved"] is False
        assert entry["master"] is None


def test_the_journey_sub_statuses_are_reported_rather_than_joined_to_a_guess(shaped):
    """`activelyApplyingJobBoardsMaster` is present and his status is 2, which
    makes a status-selected sub-master plausible. Plausible is not measured, so
    the ids come back unresolved until a second capture can test it."""
    assert [entry["id"] for entry in shaped["user_journey_sub_statuses"]] == ["2", "6"]
    for entry in shaped["user_journey_sub_statuses"]:
        assert entry["resolved"] is False
        assert entry["master"] is None


def test_the_roll_up_lists_every_gap_once(shaped):
    """Reported, not dropped - the standing law in this package."""
    assert shaped["unresolved"] == ["<no master in payload>:2", "<no master in payload>:6",
                                    "<no master in payload>:1", "<no master in payload>:3"]
    assert len(shaped["unresolved"]) == len(set(shaped["unresolved"]))


def test_the_roll_up_is_empty_when_everything_resolves__control(live):
    """__CONTROL for the roll-up. A list that is never empty reports nothing.

    Removing the two fields this payload ships no master for leaves a record
    in which every remaining id joins, and the roll-up must then say so.
    """
    complete = copy.deepcopy(live)
    complete["talent"]["preferred_modes"] = []
    complete["talent"]["user_journey_status"]["sub_statuses"] = []

    assert shape_preference(complete)["unresolved"] == []


# --- fields that carry their own names -------------------------------------


def test_job_functions_read_their_inline_names_and_need_no_master(shaped):
    """`interested_job_functions[].job_function.name` is right there."""
    assert [row["name"] for row in shaped["interested_job_functions"]] == [
        "Full Stack Development",
        "Backend Development",
    ]
    assert shaped["interested_job_functions"][0]["category"] == "Software Engineering"


def test_top_skills_come_back_as_names_in_uplers_own_order(shaped, live):
    raw = live["talent"]["talent_top_skills"]

    assert shaped["top_skills"] == [row["skill"]["name"] for row in raw]
    assert "AWS" in shaped["top_skills"]


def test_total_experience_is_a_string_on_the_record_and_is_also_given_as_a_number(
    shaped, live
):
    assert live["talent"]["total_experience"] == "5.2"
    assert shaped["total_experience"] == "5.2"
    assert shaped["total_experience_years"] == 5.2


def test_joining_period_is_its_own_id_and_still_goes_through_the_master(shaped):
    """`joiningMaster` maps "Immediately" to itself. Resolving it anyway keeps
    one code path, and proves the value is one Uplers recognises."""
    assert shaped["joining_period"]["id"] == "Immediately"
    assert shaped["joining_period"]["label"] == "Immediately"
    assert shaped["joining_period"]["resolved"] is True


# --- privacy ---------------------------------------------------------------


def test_the_shaped_output_carries_no_pay_or_contact_key(shaped):
    offenders = sorted(key for key in all_keys(shaped) if PRIVATE_KEY_RE.search(key))

    assert offenders == []


def test_the_privacy_sweep_can_actually_fail__control():
    """__CONTROL for the sweep above. It runs over an already-scrubbed capture,
    so on this input it cannot fail - and an instrument never shown failing
    certifies nothing.

    The planted keys are nested and inside a list, because a sweep that only
    looks at the top level would pass the shallow version of this test.
    """
    planted = {
        "job_title": "Software Engineer",
        "nested": {"expected_ctc": 1, "rows": [{"contact_number": "x"}]},
    }

    offenders = sorted(key for key in all_keys(planted) if PRIVATE_KEY_RE.search(key))

    assert offenders == ["contact_number", "expected_ctc"]


def test_the_capture_on_disk_carries_no_pay_or_contact_key__control(live):
    """__CONTROL, and the reason the control above exists.

    The pay and contact fields are deleted from the fixture, so the sweep over
    the shaped output is passing on an input that could not have failed it.
    Stating that here keeps the pair honest rather than reassuring.

    Scope, stated precisely because the obvious stronger claim is not true:
    this asserts the WORKING COPY on disk. It says nothing about git history,
    which is not something a test in this file can see.
    """
    assert sorted(key for key in all_keys(live) if PRIVATE_KEY_RE.search(key)) == []


def test_snooze_is_reported_as_a_count_because_its_row_shape_is_unknown(shaped, live):
    """The live list is empty, so nothing establishes what a snooze row holds.

    Passing unknown rows through would be a hole in the guarantee the test
    above asserts, so only the length crosses the boundary.
    """
    assert live["snooze"] == []
    assert shaped["snooze_count"] == 0
    assert "snooze" not in shaped


# --- the route, and the one it is not --------------------------------------


def test_the_nurture_route_is_named_only_as_a_warning_never_as_code__control():
    """__CONTROL against a specific, already-made mistake.

    An earlier pass read the bundle constant `fJ7` - the NURTURE-preference
    route - as get-preference. The warning MUST stay in the prose, so this
    cannot be a plain substring search over the file; it walks the AST and
    checks every string literal that is not the module docstring.

    The last two assertions are what make the first one mean something: they
    prove the walker collected real literals and that the prose still carries
    the warning, so a pass is not an empty file or an empty list.
    """
    source = Path(preference.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstring = ast.get_docstring(tree)
    # The NODE, not the text: `get_docstring` returns a cleaned copy that no
    # longer compares equal to the constant it came from.
    prose = tree.body[0].value

    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node is not prose
    ]

    offenders = [text for text in literals if "fJ7" in text or "nurture" in text.lower()]
    assert offenders == []

    assert UNRESOLVED in literals, "the walker collected nothing - it is not walking"
    assert "fJ7" in docstring and "NURTURE" in docstring, "the warning was deleted"


def test_the_module_is_pure_and_leaves_its_input_alone(live):
    """No I/O, no clock, no mutation. Shaping twice must give the same answer
    and the caller's payload must come back untouched."""
    before = copy.deepcopy(live)

    first = shape_preference(live)
    second = shape_preference(live)

    assert first == second
    assert live == before


def test_a_payload_with_no_masters_still_shapes_and_reports_every_id(live):
    """A caller that fetched only half the response must get ids it cannot
    name, not an empty preference that reads like an unset profile."""
    stripped = copy.deepcopy(live)
    stripped.pop("masters")

    shaped = shape_preference(stripped)

    assert shaped["job_search_preference"]["id"] == "1"
    assert shaped["job_search_preference"]["label"] == UNRESOLVED
    assert shaped["masters_present"] == []
    assert len(shaped["unresolved"]) >= 6


def test_junk_input_shapes_into_an_empty_answer_rather_than_raising():
    for junk in ({}, None, [], {"talent": None, "masters": None}):
        shaped = shape_preference(junk)
        assert sorted(shaped) == SHAPED_KEYS
        assert shaped["job_search_preference"] is None
        assert shaped["unresolved"] == []
