"""saved_filter.py - pinning a contract that fails silently rather than loudly.

Uplers' saved-jobs view answers 200 to a wrong request. Send the flag as a
boolean and their strict `1===` comparison quietly takes the OTHER branch;
send it with `roles` and their ternary quietly discards `roles`. Neither
mistake produces an error, a warning, or an empty list - both produce a
plausible page of jobs that the caller then describes as something it is not.

That is why this file exists and why so much of it is controls. A guard
against a silent failure is itself easy to write silently wrong: the obvious
assertion here, ``params["is_saved_filter"] == 1``, PASSES for ``True``,
because in Python ``True == 1``. A check that cannot fail on the one input it
was written to catch certifies nothing, so every guard below is paired with a
test that runs the same instrument against a known-bad input and requires it
to fail.

The response fixture is `tests/fixtures/saved_filter_page.json`, captured live
on 2026-08-23. It records that he has ZERO jobs saved on the platform, and
that their paginator carries no `total` and no `last_page`.
"""

from __future__ import annotations

import copy
import json

import pytest

from uplers_server import saved_filter
from uplers_server.endpoints import QP_IS_SAVED_FILTER
from uplers_server.saved_filter import SAVED_FILTER_ON, SavedFilterRefused

from conftest import load_talent_fixture

SAVED_PAGE = "saved_filter_page"


@pytest.fixture
def live_page():
    """The captured `is_saved_filter=1` response, whole and unmodified."""
    return load_talent_fixture(SAVED_PAGE)


# --- fact 1: the integer 1, never the boolean true -------------------------


def test_the_parameter_name_is_the_one_uplers_reads():
    """Everything below is about a key whose spelling is not negotiable."""
    assert QP_IS_SAVED_FILTER == "is_saved_filter"
    assert saved_filter.saved_jobs_params()[QP_IS_SAVED_FILTER] == SAVED_FILTER_ON


def test_the_flag_is_the_integer_one_not_the_boolean():
    """VERIFIED in bundle chunk 8562: their test is ``1===t.is_saved_filter``.

    Asserted with ``type(...) is int`` rather than ``== 1``. `isinstance`
    would not discriminate either, because bool subclasses int.
    """
    params = saved_filter.saved_jobs_params()

    assert type(params[QP_IS_SAVED_FILTER]) is int
    assert params[QP_IS_SAVED_FILTER] is not True
    saved_filter.assert_integer_one(params)


def test_the_integer_check_actually_rejects_a_boolean__control():
    """__CONTROL for the test above, and the reason it is not written as ``== 1``.

    Runs the SAME instrument against the one input it exists to catch. The
    naive equality is shown passing on that input first, so the failure below
    is a demonstration that the two checks are not interchangeable.
    """
    wrong = {QP_IS_SAVED_FILTER: True}

    assert wrong[QP_IS_SAVED_FILTER] == 1, "if this fails the whole premise is gone"

    with pytest.raises(AssertionError) as caught:
        saved_filter.assert_integer_one(wrong)
    assert "bool" in str(caught.value)


def test_the_integer_check_also_rejects_the_string__control():
    """__CONTROL. ``"1"`` is the other near-miss a JSON round trip can produce."""
    with pytest.raises(AssertionError):
        saved_filter.assert_integer_one({QP_IS_SAVED_FILTER: "1"})
    with pytest.raises(AssertionError):
        saved_filter.assert_integer_one({})


def test_the_flag_serialises_to_1_and_not_to_true__control():
    """__CONTROL. The wire form is what their comparison sees.

    Encoding both values proves the distinction is not an internal Python
    nicety that disappears on the way out.
    """
    on_the_wire = json.dumps(saved_filter.saved_jobs_params())

    assert '"is_saved_filter": 1' in on_the_wire
    assert '"is_saved_filter": true' not in on_the_wire
    # The contrast: the mistake this guards is a real, reachable encoding.
    assert '"is_saved_filter": true' in json.dumps({QP_IS_SAVED_FILTER: True})


# --- fact 2: the flag is exclusive -----------------------------------------


def test_combining_the_saved_filter_with_roles_is_refused():
    """The headline case. Their ternary drops `roles`; this refuses instead.

    Silently dropping it would return his saved jobs UNFILTERED while the
    caller reported them as filtered by role - a wrong answer with no error
    attached, which is worse than a failure.
    """
    with pytest.raises(SavedFilterRefused) as caught:
        saved_filter.saved_jobs_params(roles=[3, 1])

    message = str(caught.value)
    assert "roles" in message
    assert "UNFILTERED" in message


@pytest.mark.parametrize("name", saved_filter.KNOWN_DROPPED)
def test_every_filter_their_branch_drops_is_refused(name):
    """`roles`, `locations`, `experience`, `engagements` - all short-circuited."""
    with pytest.raises(SavedFilterRefused):
        saved_filter.saved_jobs_params(**{name: "anything"})


def test_a_filter_name_nobody_measured_is_refused_too():
    """Deny by default, because their branch emits `search` and nothing else.

    An enumerated blocklist would pass a filter Uplers adds next month
    straight through, in silence, which is the exact class of bug this module
    exists to close.
    """
    with pytest.raises(SavedFilterRefused) as caught:
        saved_filter.saved_jobs_params(skill_ids=[9])
    assert "skill_ids" in str(caught.value)


def test_search_rides_alongside_the_saved_filter__control():
    """__CONTROL for the refusals above: the guard is not a blanket refusal.

    `search` is the one filter emitted INSIDE their saved branch. If this
    raised, every test above would pass for the wrong reason - a function that
    rejects everything rejects `roles` too.
    """
    params = saved_filter.saved_jobs_params(search="node")

    assert params["search"] == "node"
    assert params[QP_IS_SAVED_FILTER] == SAVED_FILTER_ON


def test_a_blank_search_is_omitted_rather_than_sent_empty():
    """The live response echoes ``search: ""``; sending an empty needle is not
    a search, so the key is left off entirely."""
    assert "search" not in saved_filter.saved_jobs_params(search="   ")
    assert "search" not in saved_filter.saved_jobs_params(search=None)
    assert saved_filter.saved_jobs_params(search="  node  ")["search"] == "node"


def test_the_parameters_outside_the_ternary_are_passed_through():
    """`pagination`, `page`, `is_count` and `activeJob` are sent either way.

    They sit outside `1===t.is_saved_filter ? ... : ...`, so accepting them is
    correct - they are not dropped and refusing them would be wrong.
    """
    params = saved_filter.saved_jobs_params(page=3, pagination=50, is_count=1, activeJob=1)

    assert params["page"] == 3
    assert params["pagination"] == 50
    assert params["is_count"] == 1
    assert params["activeJob"] == 1


def test_is_count_and_active_job_are_not_emitted_by_default():
    """Recorded gap, asserted so it stays a decision rather than an oversight.

    Their client always sends both. Their VALUES were never captured, and a
    guessed value is a different request, so this builder emits neither unless
    a caller supplies one.
    """
    params = saved_filter.saved_jobs_params()

    assert "is_count" not in params
    assert "activeJob" not in params
    assert {"is_count", "activeJob"} <= saved_filter.OUTSIDE_TERNARY


# --- rejected_filters, as a standalone instrument --------------------------


def test_rejected_filters_names_every_ignored_key_in_the_order_given():
    requested = {"search": "node", "page": 2, "roles": [1], "locations": [7], "zzz": 1}

    assert saved_filter.rejected_filters(requested) == ["roles", "locations", "zzz"]


def test_rejected_filters_is_empty_for_a_request_the_server_honours__control():
    """__CONTROL for the test above. An always-non-empty list names nothing."""
    honoured = {
        QP_IS_SAVED_FILTER: SAVED_FILTER_ON,
        "search": "node",
        "page": 1,
        "pagination": 20,
        "is_count": 1,
        "activeJob": 1,
    }

    assert saved_filter.rejected_filters(honoured) == []
    assert saved_filter.rejected_filters({}) == []


# --- page and pagination ---------------------------------------------------


def test_page_and_pagination_must_be_positive_integers():
    for bad in (0, -1, "2", 1.0, None):
        with pytest.raises(SavedFilterRefused):
            saved_filter.saved_jobs_params(page=bad)
        with pytest.raises(SavedFilterRefused):
            saved_filter.saved_jobs_params(pagination=bad)


def test_a_boolean_page_is_refused_too__control():
    """__CONTROL. ``True`` is a positive int by every loose test in Python.

    ``page=True`` would build ``page=1`` and look fine. It is refused for the
    same reason the flag is type-checked: bool is not the type intended, and
    accepting it here would prove the numeric guard is doing ``value >= 1``
    and nothing more.
    """
    with pytest.raises(SavedFilterRefused):
        saved_filter.saved_jobs_params(page=True)
    # The contrast that makes the assertion above meaningful.
    assert True >= 1 and int(True) == 1


# --- the live response -----------------------------------------------------


def test_he_has_zero_saved_jobs_and_that_is_the_measurement(live_page):
    """Captured live 2026-08-23. Not a placeholder, not an empty test double."""
    assert live_page["bookmarkedCount"] == 0
    assert live_page["hrs"]["data"] == []


def test_zero_saved_jobs_renders_as_an_answer_not_as_a_failure(live_page):
    """An empty platform list must read as "you saved nothing", never as a
    broken read - the two look identical to a caller otherwise."""
    shaped = saved_filter.read_saved_page(live_page)

    assert shaped["returned"] == 0
    assert shaped["bookmarked_count"] == 0
    assert shaped["jobs"] == []
    assert "no jobs saved" in shaped["summary"]


def test_the_summary_distinguishes_the_platform_list_from_the_local_one(live_page):
    """The two saved lists are disjoint, so the sentence has to say which."""
    summary = saved_filter.read_saved_page(live_page)["summary"]

    assert "Uplers platform" in summary
    assert "uplers_list_saved" in summary


def test_the_live_paginator_carries_no_total_and_no_last_page(live_page):
    """Measured absence. Reading a field that is not there is the bug this
    prevents, and `total_pages_known` says so out loud."""
    paginator = live_page["hrs"]

    assert "total" not in paginator
    assert "last_page" not in paginator
    assert sorted(paginator) == [
        "current_page",
        "data",
        "first_page_url",
        "from",
        "next_page_url",
        "path",
        "per_page",
        "prev_page_url",
        "to",
    ]
    assert saved_filter.read_saved_page(live_page)["total_pages_known"] is False


def test_per_page_arrives_as_a_string_and_is_coerced__control(live_page):
    """__CONTROL. The coercion is real work, not a no-op on an int.

    Asserting the RAW type first is what makes the coerced assertion mean
    something - an untyped comparison of "20" against 20 is silently False.
    """
    assert live_page["hrs"]["per_page"] == "20"
    assert isinstance(live_page["hrs"]["per_page"], str)

    assert saved_filter.read_saved_page(live_page)["per_page"] == 20


def test_has_more_is_derived_from_next_page_url_because_nothing_else_can(live_page):
    """No `last_page` means `next_page_url` is the only available signal.

    The second half overlays ONE field on the captured envelope rather than
    inventing a payload, so the shape under test stays the live one.
    """
    assert saved_filter.read_saved_page(live_page)["has_more"] is False

    with_more = copy.deepcopy(live_page)
    with_more["hrs"]["next_page_url"] = with_more["hrs"]["path"] + "?page=2"

    shaped = saved_filter.read_saved_page(with_more)
    assert shaped["has_more"] is True
    assert shaped["next_page_url"].endswith("page=2")


def test_the_returned_count_comes_from_the_rows_not_from_from_and_to(live_page):
    """`from` and `to` are BOTH null on the live empty page, so the obvious
    ``to - from + 1`` would raise on the only response ever captured."""
    assert live_page["hrs"]["from"] is None
    assert live_page["hrs"]["to"] is None

    assert saved_filter.read_saved_page(live_page)["returned"] == 0


def test_a_response_that_is_not_the_expected_shape_does_not_explode():
    """A shaper for an empty list must not turn a bad envelope into a crash
    that reads like "no saved jobs"; it reports zero and says nothing else."""
    for junk in ({}, {"hrs": None}, {"hrs": {"data": "nope"}}, None, []):
        shaped = saved_filter.read_saved_page(junk)
        assert shaped["returned"] == 0
        assert shaped["page"] is None or isinstance(shaped["page"], int)
