"""The two pre-apply assessment flags, and what the capture can and cannot prove.

WHAT WAS MEASURED, before `uplers_server/assessment_flags.py` existed. Both
fixtures are Laravel paginators whose rows sit at `payload["hrs"]["data"]`, and
both flags are plain TOP-LEVEL keys of each row - depth one, no nesting:

    fixture                rows   ai_needed              custom_screening_needed
    talent_feed.json         3    3/3 present, bool      3/3 present, bool
                                  False x3               False x3
    talent_pipeline.json     9    9/9 present, bool      9/9 present, bool
                                  False x9               False x9

Twenty-four observations, every one a present JSON `bool` with the value
`False`. Zero absent, zero of any other type, zero true. That AGREES with the
figure this slice was commissioned against: all nine of his applications read
`ai_needed: false`.

THEREFORE THE CAPTURE CANNOT EXERCISE THREE OF THE FOUR STATES. There is no
row anywhere in either fixture that is true, that omits a flag, or that states
one as anything but a bool. `test_the_captures_cannot_exercise_true_unknown_or
_unrecognised` asserts that emptiness directly, so the limitation is a checked
fact rather than a claim in a comment, and every synthetic-row test below
exists because of it. The synthetic rows are SMALL and hand-built on purpose;
no whole payload is pasted in here, because a hand-written payload no live API
ever returned is how this suite once got 864 green tests over a reader that
returned nothing.

WHAT THE FLAGS ARE NOT. They are pre-apply demand - "this requisition will
require an assessment before you can apply" - and they are not pipeline signal.
`test_two_real_applications_had_a_custom_screening_while_the_flag_reads_false`
is the receipt on live rows: `custom_screening_needed` is False on all nine
applications while the neighbouring `is_custome_screening` is True on two of
them, each with a real `custom_screening_at` timestamp. A `gated: 0` summary
therefore says nothing about why his applications stall.

CONTROLS. Every guard here has one, marked `__CONTROL` in its docstring,
because a check never shown failing certifies nothing. Three traps in
particular are controlled for by name: that `== False` passes for the integer
`0`, that a `.get(field, False)` reader makes absent and false indistinguishable,
and that a summariser only ever run against an all-false capture has never been
shown counting anything.
"""

from __future__ import annotations

import json

import pytest

from conftest import TALENT_FEED, TALENT_PIPELINE, load_talent_fixture

from uplers_server.assessment_flags import (
    FLAGS,
    STATE_FALSE,
    STATE_TRUE,
    STATE_UNKNOWN,
    STATE_UNRECOGNISED,
    extract_flags,
    read_flag,
    summarise_flags,
)


def rows(name: str) -> list:
    """The row list off a captured envelope, exactly where the API puts it."""
    return load_talent_fixture(name)["hrs"]["data"]


def counts(true=0, false=0, unknown=0, unrecognised=0) -> dict:
    """One flag's four buckets, spelled out so assertions read as a table."""
    return {
        "true": true,
        "false": false,
        "unknown": unknown,
        "unrecognised": unrecognised,
    }


# --- the captured envelopes ------------------------------------------------


def test_the_captured_feed_still_carries_both_flags_on_every_row():
    """Pins the capture, so a re-capture that drifts fails here first.

    Without this, a reader bug and a shape change look identical downstream.
    """
    data = rows(TALENT_FEED)
    assert len(data) == 3
    for field in FLAGS:
        present = [row for row in data if field in row]
        assert len(present) == 3, field
        # `type(...) is bool` and not `isinstance`, because bool is an int
        # subclass and isinstance(0, int) would admit the integer form.
        assert all(type(row[field]) is bool for row in present), field


def test_the_captured_pipeline_still_carries_both_flags_on_every_row():
    """His nine real applications. Same shape, same type, on every row."""
    data = rows(TALENT_PIPELINE)
    assert len(data) == 9
    for field in FLAGS:
        present = [row for row in data if field in row]
        assert len(present) == 9, field
        assert all(type(row[field]) is bool for row in present), field


def test_every_captured_value_of_both_flags_is_false():
    """The measurement the whole caveat rests on: 24 observations, all False.

    Stated as `is False` rather than `== False` deliberately - see the control
    below, where the equality form passes for an integer 0.
    """
    values = [
        row[field]
        for name in (TALENT_FEED, TALENT_PIPELINE)
        for row in rows(name)
        for field in FLAGS
    ]
    assert len(values) == 24
    assert all(value is False for value in values)


def test_the_pipeline_nested_requisition_carries_neither_flag():
    """Why the reader reads the TOP level of the row and does not go hunting.

    On `my-opportunities` the row is the APPLICATION and the requisition hangs
    off `row["hr"]`. That is the surface where this server has been bitten
    before - the wrapper `enc_id` is his talent id, not the job's - so where
    these two flags live is worth pinning rather than assuming.
    """
    nested = [row["hr"] for row in rows(TALENT_PIPELINE)]
    assert len(nested) == 9
    assert all(isinstance(item, dict) for item in nested)
    for field in FLAGS:
        assert [item for item in nested if field in item] == [], field


def test_summarising_his_nine_real_applications_reports_zero_gated():
    """The headline number, and the one most likely to be misread."""
    summary = summarise_flags(rows(TALENT_PIPELINE))
    assert summary["rows"] == 9
    assert summary["gated"] == 0
    assert summary["flags"]["ai_needed"] == counts(false=9)
    assert summary["flags"]["custom_screening_needed"] == counts(false=9)
    assert summary["unrecognised_values"] == []


def test_summarising_the_feed_reports_zero_gated():
    """The other surface, unchanged reader, three rows."""
    summary = summarise_flags(rows(TALENT_FEED))
    assert summary["rows"] == 3
    assert summary["gated"] == 0
    assert summary["flags"]["ai_needed"] == counts(false=3)
    assert summary["flags"]["custom_screening_needed"] == counts(false=3)
    assert summary["unrecognised_values"] == []


def test_the_captures_cannot_exercise_true_unknown_or_unrecognised():
    """The honesty test: the capture's LIMIT, asserted rather than described.

    If a future re-capture ever does contain a true, an absent or a drifted
    value, this fails - and that failure is the signal to move the matching
    synthetic test onto real data instead of leaving it synthetic.
    """
    for name in (TALENT_FEED, TALENT_PIPELINE):
        summary = summarise_flags(rows(name))
        for field in FLAGS:
            bucket = summary["flags"][field]
            assert bucket["true"] == 0, (name, field)
            assert bucket["unknown"] == 0, (name, field)
            assert bucket["unrecognised"] == 0, (name, field)
            assert bucket["false"] == summary["rows"], (name, field)


def test_absence_is_real_on_these_rows_even_though_not_on_these_two_fields():
    """Why the absent path exists at all, proven on the captured rows.

    `ai_mandatory` is the integer 0 on all three feed rows and is ABSENT from
    all nine pipeline rows: one field, two surfaces, present-as-int against
    missing entirely. Neither of THIS module's two fields is ever absent in the
    capture, which is why the absent path is covered synthetically below - but
    the path is not hypothetical, and this is the row set that shows it.
    """
    feed = rows(TALENT_FEED)
    pipeline = rows(TALENT_PIPELINE)

    assert [row["ai_mandatory"] for row in feed] == [0, 0, 0]
    # The line above would also pass if the values were `False`, since
    # False == 0. The type check is what makes it a measurement.
    assert all(type(row["ai_mandatory"]) is int for row in feed)

    assert [row for row in pipeline if "ai_mandatory" in row] == []
    assert read_flag(pipeline[0], "ai_mandatory") == STATE_UNKNOWN
    assert read_flag(feed[0], "ai_mandatory") == STATE_FALSE


def test_two_real_applications_had_a_custom_screening_while_the_flag_reads_false():
    """The receipt for the caveat, on live rows: these are two different facts.

    `custom_screening_needed` is the demand a requisition makes UP FRONT.
    `is_custome_screening` (Uplers' spelling) plus `custom_screening_at` record
    what actually happened to that application. All nine read False on the
    first while two read True on the second. Anyone reading a `gated: 0`
    summary as "nothing is blocked on screening" is reading the wrong field.
    """
    data = rows(TALENT_PIPELINE)

    assert [row for row in data if row["custom_screening_needed"] is not False] == []

    happened = [row for row in data if row.get("is_custome_screening") is True]
    assert len(happened) == 2
    assert all(isinstance(row.get("custom_screening_at"), str) for row in happened)


# --- normalising the types this API is known to mix ------------------------
#
# Small synthetic ROWS, not payloads. The capture states both flags as a bool
# every time, so none of the variants below can be taken from it; inventing a
# whole envelope to carry them would be worse than admitting they are made up.

TRUE_SPELLINGS = [True, 1, 1.0, "1", "1.00", "true", "True", "  TRUE  ",
                  "yes", "y", "t"]
FALSE_SPELLINGS = [False, 0, 0.0, "0", "0.00", "false", "False", "  FALSE  ",
                   "no", "n", "f"]
NOT_STATED = [None, "", "   "]
UNREADABLE = ["2026-08-12 02:58:26", "maybe", "null", 2, -1, 7.5,
              {}, [], {"value": True}, [1]]


@pytest.mark.parametrize("raw", TRUE_SPELLINGS)
def test_every_true_spelling_normalises_to_a_real_bool_True(raw):
    """`is True`, not `== True` - the integer 1 passes the equality form."""
    value = extract_flags({"ai_needed": raw})["ai_needed"]
    assert value is True
    assert type(value) is bool


@pytest.mark.parametrize("raw", FALSE_SPELLINGS)
def test_every_false_spelling_normalises_to_a_real_bool_False(raw):
    """`is False`, not `== False` - the integer 0 passes the equality form."""
    value = extract_flags({"custom_screening_needed": raw})["custom_screening_needed"]
    assert value is False
    assert type(value) is bool


@pytest.mark.parametrize("raw", NOT_STATED)
def test_a_stated_but_empty_value_is_unknown_and_never_false(raw):
    """Null and empty mean the API said nothing. Saying "false" invents a fact."""
    assert extract_flags({"ai_needed": raw})["ai_needed"] is None
    assert read_flag({"ai_needed": raw}, "ai_needed") == STATE_UNKNOWN


@pytest.mark.parametrize("raw", UNREADABLE)
def test_an_unreadable_value_is_reported_not_guessed(raw):
    """A date string in a boolean field is this API's documented disease.

    `is_partner_company` holds one. Plain truthiness would read every such
    value as True and quietly inflate the gated count.
    """
    assert extract_flags({"ai_needed": raw})["ai_needed"] is None
    assert read_flag({"ai_needed": raw}, "ai_needed") == STATE_UNRECOGNISED


def test_the_string_false_does_not_read_as_true():
    """The single most likely normalisation bug, pinned on its own."""
    assert bool("false") is True          # the trap, stated outright
    assert bool("0") is True              # and its numeric twin
    assert extract_flags({"ai_needed": "false"})["ai_needed"] is False
    assert extract_flags({"ai_needed": "0"})["ai_needed"] is False


def test_an_equality_assertion_cannot_catch_an_unnormalised_number__CONTROL():
    """__CONTROL for every `is True` / `is False` assertion in this file.

    In Python `True == 1` and `False == 0`, so a test written the obvious way
    passes against a normaliser that never normalised anything. This builds
    that exact bug and shows the equality form accepting it and the identity
    form rejecting it. Without this, the assertions above could all be the
    weak kind and nothing here would notice.
    """
    unnormalised = {"ai_needed": 1, "custom_screening_needed": 0.0}

    # The assertions this file refuses to write. Both PASS on the bug:
    assert unnormalised["ai_needed"] == True            # noqa: E712
    assert unnormalised["custom_screening_needed"] == False   # noqa: E712

    # The assertions this file does write. Both CATCH it:
    assert unnormalised["ai_needed"] is not True
    assert unnormalised["custom_screening_needed"] is not False
    assert type(unnormalised["ai_needed"]) is not bool
    assert type(unnormalised["custom_screening_needed"]) is not bool

    # And the real extractor does not have the bug it was built to avoid.
    fixed = extract_flags(unnormalised)
    assert fixed["ai_needed"] is True
    assert fixed["custom_screening_needed"] is False
    assert type(fixed["ai_needed"]) is bool
    assert type(fixed["custom_screening_needed"]) is bool


# --- absent is not false ---------------------------------------------------


def test_absent_and_false_produce_different_output():
    """The distinction the whole tri-state exists for."""
    absent = extract_flags({})["ai_needed"]
    stated = extract_flags({"ai_needed": False})["ai_needed"]
    assert absent is None
    assert stated is False
    assert absent is not stated


def test_a_get_with_a_false_default_would_collapse_the_two__CONTROL():
    """__CONTROL for the pair above. Shows the obvious reader losing the
    distinction, so that test is not merely asserting a tautology.

    `record.get(field, False)` is the one-liner anyone would reach for. On
    these two inputs it returns the identical value, and the value it invents
    for the row that never carried the field is `False` - a confident lie
    about what the API said.
    """
    absent, stated = {}, {"ai_needed": False}

    naive_absent = absent.get("ai_needed", False)
    naive_stated = stated.get("ai_needed", False)
    assert naive_absent is naive_stated       # indistinguishable
    assert naive_absent is False              # and it INVENTED the false

    real_absent = extract_flags(absent)["ai_needed"]
    real_stated = extract_flags(stated)["ai_needed"]
    assert real_absent is None
    assert real_stated is False
    assert real_absent is not real_stated


def test_extract_flags_returns_exactly_the_two_flags():
    """Two keys, always, whatever else the eighty-key row carries."""
    assert sorted(FLAGS) == ["ai_needed", "custom_screening_needed"]
    assert sorted(extract_flags({})) == ["ai_needed", "custom_screening_needed"]
    assert sorted(extract_flags(rows(TALENT_PIPELINE)[0])) == list(sorted(FLAGS))


def test_the_reader_does_not_pick_up_the_neighbouring_screening_fields():
    """The adjacent fields are a different fact and are deliberately not read."""
    row = {
        "custom_screening_needed": False,
        "is_custome_screening": True,
        "custom_screening_at": "2026-08-12 02:58:26",
    }
    flags = extract_flags(row)
    assert flags["custom_screening_needed"] is False
    assert set(flags) == set(FLAGS)


# --- the summariser --------------------------------------------------------


def test_the_summariser_counts_a_known_mix__CONTROL():
    """__CONTROL for the two fixture summaries above.

    Those run against an all-false capture, where a summariser that returned
    zeros for `true` no matter what would look perfect. This feeds a hand-built
    mix with counts known by construction - three true, two false, one absent
    on `ai_needed` - and asserts the exact numbers, so the counter is shown
    actually counting.
    """
    mix = [
        {"ai_needed": True, "custom_screening_needed": False},
        {"ai_needed": True, "custom_screening_needed": False},
        {"ai_needed": True, "custom_screening_needed": False},
        {"ai_needed": False, "custom_screening_needed": False},
        {"ai_needed": False, "custom_screening_needed": True},
        {"custom_screening_needed": False},          # ai_needed never present
    ]

    summary = summarise_flags(mix)

    assert summary["rows"] == 6
    assert summary["flags"]["ai_needed"] == counts(true=3, false=2, unknown=1)
    assert summary["flags"]["custom_screening_needed"] == counts(true=1, false=5)
    # Three rows gated by ai_needed, one more by custom_screening_needed.
    assert summary["gated"] == 4
    assert summary["unrecognised_values"] == []


def test_a_collapsing_summariser_would_miscount_the_same_rows__CONTROL():
    """__CONTROL for the `unknown` bucket. Names the exact wrong number.

    Two rows state false, one never carried the field. The obvious reader
    reports three falses and is wrong about the third row; this one reports
    two and says so about the third.
    """
    partial = [{"ai_needed": False}, {"ai_needed": False}, {}]

    naive_false = sum(1 for row in partial if not row.get("ai_needed", False))
    assert naive_false == 3                   # the confident lie

    summary = summarise_flags(partial)
    assert summary["flags"]["ai_needed"] == counts(false=2, unknown=1)


def test_the_summariser_reports_an_unreadable_value_instead_of_guessing():
    """Drift surfaces as data, deduped, and never inflates `gated`."""
    drifted = [
        {"ai_needed": "2026-08-12 02:58:26", "custom_screening_needed": False},
        {"ai_needed": "2026-08-12 02:58:26", "custom_screening_needed": False},
        {"ai_needed": True, "custom_screening_needed": False},
    ]

    summary = summarise_flags(drifted)

    assert summary["flags"]["ai_needed"] == counts(true=1, unrecognised=2)
    assert summary["flags"]["custom_screening_needed"] == counts(false=3)
    # One gated row, not three: the date strings did not read as truthy.
    assert summary["gated"] == 1
    assert summary["unrecognised_values"] == [
        {"field": "ai_needed", "value": repr("2026-08-12 02:58:26"), "rows": 2}
    ]


def test_the_four_buckets_always_sum_to_the_row_count():
    """The invariant that makes the counts readable as a partition."""
    mix = [
        {"ai_needed": True, "custom_screening_needed": "no"},
        {"ai_needed": None, "custom_screening_needed": 1},
        {"ai_needed": "2026-08-12", "custom_screening_needed": False},
        {},
    ]
    summary = summarise_flags(mix)
    assert summary["rows"] == 4
    for field in FLAGS:
        assert sum(summary["flags"][field].values()) == 4, field


def test_the_bucket_sum_can_actually_disagree__CONTROL():
    """__CONTROL for the invariant above, which would hold trivially if the
    summariser simply dropped rows it could not read.

    A summariser that skipped the unreadable row would return buckets summing
    to 3 for a 4-row input. The shape below is what that looks like, and the
    assertion above is what rejects it.
    """
    dropped_a_row = counts(true=1, false=1, unknown=1)
    assert sum(dropped_a_row.values()) == 3
    assert sum(dropped_a_row.values()) != 4


def test_an_empty_row_list_summarises_to_zero_rows():
    """Zero rows is a legitimate answer and must not raise."""
    summary = summarise_flags([])
    assert summary["rows"] == 0
    assert summary["gated"] == 0
    assert summary["flags"]["ai_needed"] == counts()
    assert summary["unrecognised_values"] == []


def test_two_summaries_do_not_share_counter_state():
    """A module-level counts dict would leak the first call into the second."""
    first = summarise_flags([{"ai_needed": True, "custom_screening_needed": True}])
    second = summarise_flags([])
    assert first["flags"]["ai_needed"]["true"] == 1
    assert second["flags"]["ai_needed"]["true"] == 0


def test_neither_function_mutates_the_row_it_was_given():
    """Both are pure. A reader that edited his pipeline rows would be a bug
    that only showed up in whatever ran after it."""
    row = rows(TALENT_PIPELINE)[0]
    before = json.dumps(row, sort_keys=True, default=str)

    extract_flags(row)
    summarise_flags([row])

    assert json.dumps(row, sort_keys=True, default=str) == before


# --- the guards ------------------------------------------------------------


def test_summarise_flags_rejects_the_whole_envelope():
    """The likeliest wiring mistake, caught loudly rather than counted as zero.

    Iterating the envelope dict yields its KEYS, so a lenient reader would
    return a tidy `rows: 1` summary of nothing at all.
    """
    with pytest.raises(TypeError) as excinfo:
        summarise_flags(load_talent_fixture(TALENT_PIPELINE))
    assert "hrs" in str(excinfo.value)


def test_summarise_flags_rejects_a_non_dict_row():
    """A list of ids instead of rows names the offending index and type."""
    with pytest.raises(TypeError) as excinfo:
        summarise_flags([{"ai_needed": True}, "HR100725001919"])
    message = str(excinfo.value)
    assert "Row 1" in message
    assert "str" in message


def test_read_flag_rejects_a_non_dict():
    """Same rule one level down, so the error names the real cause."""
    with pytest.raises(TypeError):
        read_flag(["ai_needed"], "ai_needed")
    with pytest.raises(TypeError):
        extract_flags("HR100725001919")


def test_the_guards_still_admit_a_real_row__CONTROL():
    """__CONTROL for the three rejections above.

    A guard that rejected everything would pass all three of them and certify
    nothing. These are the inputs that must NOT raise: a captured row, a
    one-row list, and an empty list.
    """
    real = rows(TALENT_PIPELINE)[0]
    assert read_flag(real, "ai_needed") == STATE_FALSE
    assert extract_flags(real)["ai_needed"] is False
    assert summarise_flags([real])["rows"] == 1
    assert summarise_flags([])["rows"] == 0


def test_read_flag_states_are_the_four_documented_strings():
    """The state vocabulary, pinned so a rename cannot pass silently."""
    assert read_flag({"ai_needed": True}, "ai_needed") == STATE_TRUE
    assert read_flag({"ai_needed": False}, "ai_needed") == STATE_FALSE
    assert read_flag({}, "ai_needed") == STATE_UNKNOWN
    assert read_flag({"ai_needed": {}}, "ai_needed") == STATE_UNRECOGNISED
    assert len({STATE_TRUE, STATE_FALSE, STATE_UNKNOWN, STATE_UNRECOGNISED}) == 4
