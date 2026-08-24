"""The paid agent's read-through, driven entirely by live-captured payloads.

Every input in this file is one of the five envelopes
`scripts/capture_outreach.py` pulled off his live session into
`tests/fixtures/outreach_*.json`, or a MUTATION of one of them (a key deleted,
two real `data` nodes swapped between routes, the row order shuffled). Not one
payload here was written by hand, and that is deliberate: this suite has a scar
about hand-written payloads no live API ever returned, because a payload
invented by the same head that wrote the reader agrees with the reader by
construction and proves nothing.

THE TWO ENVELOPE IDIOMS ARE THE REASON THIS FILE LEADS WITH THEM. Four of the
five routes answer `{"status": 200, ...}` with the INTEGER 200, and
`outreach-step` alone answers `{"status": "success", ...}` with the STRING. A
reader that checked only one of those would have refused a live route; a reader
that checked neither (an `if payload.get("status"):` truthiness test) would
accept both AND accept a 401, which is how a shaper ends up printing confident
rows that no API ever sent.

CONTROLS. Every guard here is SHOWN FAILING, because a check that cannot fail
certifies nothing:

    test_narrowing_to_the_integer_arm_refuses_the_string_route
    test_narrowing_to_the_string_arm_refuses_the_integer_routes
        Narrow outreach.SUCCESS_VALUES to one arm and the OTHER arm's real
        fixtures stop reading. Proves each arm is genuinely checked, and that
        the check is not a truthiness test that waves both through.

    test_the_captured_order_is_not_already_stalest_first
        Proves the ranking has work to do: the captured list arrives NEWEST
        first, so a no-op sort would put a 2-day-old reply above a 12-day-old
        one.

    test_a_shuffled_copy_comes_back_in_the_same_ranked_order
        Feeds a deterministically shuffled copy and gets the identical order
        back, so the ranking is the shaper's doing and not the payload's.

    test_pending_with_its_data_key_deleted_raises
    test_the_empty_and_the_missing_inputs_differ_only_in_that_one_key
        The empty-list queue and the missing-data read are two DIFFERENT
        inputs with two DIFFERENT outputs, and the second test proves the two
        inputs differ in exactly one key, so the difference in output cannot
        come from anywhere else.

    test_the_canned_reason_really_is_in_the_payload
        Proves the canned-reason exclusion is doing real work: the string it
        excludes is present on 32 captured rows.

    test_the_leak_sweep_can_actually_fire
        Proves the contact-route sweep is capable of failing.

    test_the_clock_scanner_fires_on_a_planted_call
        Proves the no-clock scan is capable of failing.

    test_a_swapped_pair_of_shapes_is_refused
        Proves agent_readthrough's slot guard rejects two shapes passed in
        each other's places, which would otherwise render as a real read.

REVERTED-GUARD MEASUREMENTS. Each guard put back the way it would have been
written without the scar behind it, measured against this file's 86 tests on
2026-08-23. A guard whose reversal costs 0 tests is a guard this file does not
actually certify:

    ctl_status   unwrap stops checking `status` (the truthiness version)  -> 17 failed
    ctl_rank     _rank_by_staleness = lambda rows: rows                   ->  7 failed
    ctl_empty    a missing `data` key reads as an empty container         ->  3 failed
    ctl_canned   _failure_reasons counts ALL rows, canned string included ->  2 failed
    ctl_slots    _require_shape stops proving a shape is in its own slot  ->  2 failed

`ctl_canned` and `ctl_slots` costing 2 each is the honest number, not a weak
control: both guard ONE stated fact apiece (a placeholder is not a diagnosis;
five similar dicts are not interchangeable), and two tests are all it takes to
state each one.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

from uplers_server import outreach
from uplers_server.outreach import OutreachError

from conftest import FIXTURE_DIR, load_talent_fixture

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from capture_outreach import contact_leaks  # noqa: E402

STEP = "outreach_step"
DASHBOARD = "outreach_dashboard"
PENDING = "outreach_pending_jobs"
MISSED = "outreach_missed_followups"
ACTIVITY = "outreach_tailor_activity"

INTEGER_ROUTES = (DASHBOARD, PENDING, MISSED, ACTIVITY)

#: Injected everywhere a date is needed. The captures were taken on this day,
#: and injecting it is what makes every number below pinnable at all - a shaper
#: that read the clock would make this whole file expire overnight.
TODAY = "2026-08-23"

#: MEASURED off the captures, and asserted rather than trusted.
TOTAL_RUNS = 48
COMPLETED = 32
FAILED = 16
POSITIVE_REPLIES = 8
UNSEEN_REPLIES = 7
WAITING = 7
OLDEST_AGE_DAYS = 12
PLAN_DAYS_LEFT = 18


def module_source() -> str:
    """The shaper module's own text, for the two static sweeps below."""
    return Path(outreach.__file__).read_text(encoding="utf-8")


def shaper_for(name: str):
    """The shape_* function that owns one captured route."""
    return {
        STEP: outreach.shape_agent_plan,
        DASHBOARD: outreach.shape_agent_dashboard,
        PENDING: outreach.shape_pending_jobs,
        MISSED: outreach.shape_missed_followups,
        ACTIVITY: outreach.shape_activity,
    }[name]


def strings(node, trail="$"):
    """Every string in a shaped result, with the path that reached it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from strings(value, "%s.%s" % (trail, key))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from strings(item, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        yield (trail, node)


@pytest.fixture
def plan():
    return outreach.shape_agent_plan(load_talent_fixture(STEP), today=TODAY)


@pytest.fixture
def dashboard():
    return outreach.shape_agent_dashboard(load_talent_fixture(DASHBOARD))


@pytest.fixture
def pending():
    return outreach.shape_pending_jobs(load_talent_fixture(PENDING))


@pytest.fixture
def missed():
    return outreach.shape_missed_followups(load_talent_fixture(MISSED), now=TODAY)


@pytest.fixture
def activity():
    return outreach.shape_activity(load_talent_fixture(ACTIVITY))


@pytest.fixture
def report(plan, dashboard, pending, missed, activity):
    return outreach.agent_readthrough(
        plan=plan,
        dashboard=dashboard,
        pending=pending,
        missed=missed,
        activity=activity,
    )


# --- the envelope ---------------------------------------------------------


class TestTwoSuccessIdiomsOneUnwrapper:

    def test_the_string_success_arm_reads(self):
        """outreach-step is the only route sending the STRING 'success'."""
        payload = load_talent_fixture(STEP)
        assert payload["status"] == "success"

        data = outreach.unwrap(payload, route=outreach.ROUTE_STEP, expect=dict)

        assert data["plan"] == 2
        assert data["outreach_mode"] == "auto"

    @pytest.mark.parametrize("name", INTEGER_ROUTES)
    def test_the_integer_200_arm_reads(self, name):
        """The other four send the INTEGER 200, and all four must read."""
        payload = load_talent_fixture(name)
        assert payload["status"] == 200
        assert not isinstance(payload["status"], bool)

        container = list if name == PENDING else dict
        data = outreach.unwrap(payload, route=name, expect=container)

        assert isinstance(data, container)

    def test_every_captured_route_shapes_without_raising(self):
        """All five, through their own shapers, off disk. The floor."""
        for name in (STEP, DASHBOARD, PENDING, MISSED, ACTIVITY):
            shaped = shaper_for(name)(load_talent_fixture(name))
            assert isinstance(shaped, dict) and shaped["route"]


class TestTheUnwrapperRefusesEverythingElse:

    def test_an_unparsed_body_is_refused(self):
        """A real payload left as TEXT is not an envelope."""
        with pytest.raises(OutreachError, match="not a JSON object"):
            outreach.unwrap(
                json.dumps(load_talent_fixture(DASHBOARD)),
                route=DASHBOARD,
                expect=dict,
            )

    def test_a_bare_data_node_is_refused(self):
        """The `data` node of a real capture, handed over as the payload."""
        with pytest.raises(OutreachError, match="not a JSON object"):
            outreach.unwrap(
                load_talent_fixture(PENDING)["data"], route=PENDING, expect=list
            )

    def test_a_payload_with_no_status_key_is_refused(self):
        payload = copy.deepcopy(load_talent_fixture(DASHBOARD))
        del payload["status"]

        with pytest.raises(OutreachError, match="no .status. key"):
            outreach.shape_agent_dashboard(payload)

    @pytest.mark.parametrize("status", [401, 500, "error", "fail", 1, 0, None, True])
    def test_an_unmeasured_status_is_refused(self, status):
        """Including 1 - endpoints.SUCCESS_NUMERIC, measured on a DIFFERENT
        route. Accepting an unmeasured value to be helpful is how the guard
        stops guarding."""
        payload = copy.deepcopy(load_talent_fixture(DASHBOARD))
        payload["status"] = status

        with pytest.raises(OutreachError, match="reported status"):
            outreach.shape_agent_dashboard(payload)

    def test_a_missing_data_key_is_refused_and_says_it_is_not_emptiness(self):
        payload = copy.deepcopy(load_talent_fixture(MISSED))
        del payload["data"]

        with pytest.raises(OutreachError) as excinfo:
            outreach.shape_missed_followups(payload)

        assert "no `data` key" in str(excinfo.value)
        assert "NOT" in str(excinfo.value)

    def test_a_list_where_an_object_belongs_is_refused(self):
        """Two REAL captured `data` nodes, swapped between their routes."""
        payload = copy.deepcopy(load_talent_fixture(DASHBOARD))
        payload["data"] = load_talent_fixture(PENDING)["data"]

        with pytest.raises(OutreachError, match="returned .data. as list"):
            outreach.shape_agent_dashboard(payload)

    def test_an_object_where_a_list_belongs_is_refused(self):
        payload = copy.deepcopy(load_talent_fixture(PENDING))
        payload["data"] = load_talent_fixture(DASHBOARD)["data"]

        with pytest.raises(OutreachError, match="returned .data. as dict"):
            outreach.shape_pending_jobs(payload)

    def test_a_null_data_node_is_refused(self):
        payload = copy.deepcopy(load_talent_fixture(PENDING))
        payload["data"] = None

        with pytest.raises(OutreachError, match="NoneType"):
            outreach.shape_pending_jobs(payload)

    def test_a_missing_inner_rows_array_is_refused(self):
        """`data` present and an object, but the rows gone. Not 'nothing waiting'."""
        payload = copy.deepcopy(load_talent_fixture(MISSED))
        del payload["data"]["rows"]

        with pytest.raises(OutreachError, match="NOT .nothing is waiting"):
            outreach.shape_missed_followups(payload)

    def test_a_missing_inner_list_array_is_refused(self):
        payload = copy.deepcopy(load_talent_fixture(ACTIVITY))
        del payload["data"]["list"]

        with pytest.raises(OutreachError, match="NOT .the agent has done nothing"):
            outreach.shape_activity(payload)


class TestEachArmIsReallyChecked:
    """__CONTROL group. Narrow the accepted set to one arm and the other
    arm's REAL fixtures must stop reading. If they kept reading, the status
    check would be decorative - which is exactly what an `if status:`
    truthiness test would be, since it accepts both arms AND a 401."""

    def test_narrowing_to_the_integer_arm_refuses_the_string_route(self, monkeypatch):
        """__CONTROL. With only 200 accepted, outreach-step must break."""
        monkeypatch.setattr(outreach, "SUCCESS_VALUES", (200,))

        with pytest.raises(OutreachError, match="reported status 'success'"):
            outreach.shape_agent_plan(load_talent_fixture(STEP))

    @pytest.mark.parametrize("name", INTEGER_ROUTES)
    def test_narrowing_to_the_string_arm_refuses_the_integer_routes(
        self, monkeypatch, name
    ):
        """__CONTROL. With only "success" accepted, all four must break."""
        monkeypatch.setattr(outreach, "SUCCESS_VALUES", ("success",))

        with pytest.raises(OutreachError, match="reported status 200"):
            shaper_for(name)(load_talent_fixture(name))

    def test_with_both_arms_accepted_all_five_read(self):
        """The other half of the control: unnarrowed, nothing raises."""
        for name in (STEP, DASHBOARD, PENDING, MISSED, ACTIVITY):
            shaper_for(name)(load_talent_fixture(name))


# --- empty is not missing -------------------------------------------------


class TestAnEmptyQueueIsARealAnswer:

    def test_the_captured_pending_route_is_empty(self):
        assert load_talent_fixture(PENDING)["data"] == []

    def test_an_empty_list_reports_an_empty_queue(self, pending):
        assert pending["count"] == 0
        assert pending["queue_empty"] is True
        assert pending["jobs"] == []
        assert any("real answer" in note for note in pending["notes"])
        assert any("not a failed read" in note for note in pending["notes"])

    def test_pending_with_its_data_key_deleted_raises(self):
        """__CONTROL for the pair above. Same route, one key removed, and the
        outcome must be a REFUSAL rather than the same empty queue."""
        payload = copy.deepcopy(load_talent_fixture(PENDING))
        del payload["data"]

        with pytest.raises(OutreachError, match="no `data` key"):
            outreach.shape_pending_jobs(payload)

    def test_the_empty_and_the_missing_inputs_differ_only_in_that_one_key(self):
        """__CONTROL. Two inputs, two outcomes - and the inputs differ in
        exactly one key, so nothing else can be producing the difference."""
        empty = load_talent_fixture(PENDING)
        missing = copy.deepcopy(empty)
        del missing["data"]

        assert set(empty) - set(missing) == {"data"}
        assert {key: empty[key] for key in missing} == missing

        assert outreach.shape_pending_jobs(empty)["queue_empty"] is True
        with pytest.raises(OutreachError):
            outreach.shape_pending_jobs(missing)

    def test_a_non_empty_queue_reports_what_it_actually_saw(self):
        """Row shape is UNVERIFIED (no non-empty capture exists), so the row
        carries `fields_seen`. Driven by a REAL row from the sibling activity
        capture rather than an invented one - it proves the projection reports
        what arrived, which is the only claim being made."""
        payload = copy.deepcopy(load_talent_fixture(PENDING))
        real_row = copy.deepcopy(load_talent_fixture(ACTIVITY)["data"]["list"][0])
        payload["data"] = [real_row]

        shaped = outreach.shape_pending_jobs(payload)

        assert shaped["count"] == 1
        assert shaped["queue_empty"] is False
        assert shaped["row_shape_verified"] is False
        assert shaped["jobs"][0]["company"] == real_row["company_name"]
        assert shaped["jobs"][0]["fields_seen"] == sorted(real_row)
        assert any("has measured" in note for note in shaped["notes"])


# --- staleness ------------------------------------------------------------


class TestTheRankingIsStalestFirst:

    def test_the_captured_order_is_not_already_stalest_first(self):
        """__CONTROL. The ranking must have work to do, or the two tests below
        would pass against a shaper that did nothing at all. MEASURED: the
        capture arrives NEWEST first."""
        captured = [
            row["replied_at"] for row in load_talent_fixture(MISSED)["data"]["rows"]
        ]

        assert captured != sorted(captured)
        assert captured == sorted(captured, reverse=True)

    def test_rows_come_back_stalest_first(self, missed):
        order = [row["replied_at"] for row in missed["rows"]]

        assert order == sorted(order)
        assert missed["rows_read"] == WAITING
        assert missed["rows"][0]["age_days"] == OLDEST_AGE_DAYS
        assert missed["rows"][-1]["age_days"] == 2

    def test_a_shuffled_copy_comes_back_in_the_same_ranked_order(self):
        """__CONTROL. Deterministic shuffle, identical ranked output - so the
        order is the shaper's doing, not the payload's."""
        payload = copy.deepcopy(load_talent_fixture(MISSED))
        rows = payload["data"]["rows"]
        random.Random(20260823).shuffle(rows)

        assert [row["replied_at"] for row in rows] != [
            row["replied_at"] for row in load_talent_fixture(MISSED)["data"]["rows"]
        ]

        shuffled = outreach.shape_missed_followups(payload, now=TODAY)
        straight = outreach.shape_missed_followups(
            load_talent_fixture(MISSED), now=TODAY
        )

        assert shuffled["rows"] == straight["rows"]

    def test_the_ranking_is_not_a_string_comparison(self):
        """Same instants, one written in UTC. A string sort would put the
        'Z' rows in a different place; a parsed sort cannot tell them apart."""
        payload = copy.deepcopy(load_talent_fixture(MISSED))
        for row in payload["data"]["rows"]:
            moment = row["replied_at"]
            hour = int(moment[11:13])
            row["replied_at"] = "%sT%02d:%s:00+00:00" % (
                moment[:10],
                (hour - 5) % 24,
                moment[14:16],
            )

        shaped = outreach.shape_missed_followups(payload, now=TODAY)
        companies = [row["company"] for row in shaped["rows"]]
        straight = outreach.shape_missed_followups(
            load_talent_fixture(MISSED), now=TODAY
        )

        assert companies == [row["company"] for row in straight["rows"]]

    def test_an_unreadable_stamp_ranks_last_and_is_named(self):
        """A row this reader cannot time is still a person waiting."""
        payload = copy.deepcopy(load_talent_fixture(MISSED))
        payload["data"]["rows"][3]["replied_at"] = "not a timestamp"
        broken_company = payload["data"]["rows"][3]["company_name"]

        shaped = outreach.shape_missed_followups(payload, now=TODAY)

        assert shaped["rows_read"] == WAITING
        assert shaped["rows"][-1]["company"] == broken_company
        assert shaped["rows"][-1]["age_days"] is None
        assert any("ranked last, not dropped" in note for note in shaped["notes"])


class TestTheClockIsInjectedNeverRead:

    def test_no_reference_date_means_no_age_and_a_note_saying_so(self):
        shaped = outreach.shape_missed_followups(load_talent_fixture(MISSED))

        assert [row["age_days"] for row in shaped["rows"]] == [None] * WAITING
        assert [row["replied_at"] for row in shaped["rows"]] == sorted(
            row["replied_at"] for row in shaped["rows"]
        )
        assert any("no row carries an age" in note.lower() for note in shaped["notes"])

    def test_no_reference_date_means_no_plan_countdown(self):
        shaped = outreach.shape_agent_plan(load_talent_fixture(STEP))

        assert shaped["days_remaining"] is None
        assert "no reference date" in shaped["days_remaining_basis"]

    def test_the_injected_date_pins_the_countdown(self, plan):
        assert plan["plan_end_date"] == "2026-09-10"
        assert plan["days_remaining"] == PLAN_DAYS_LEFT
        assert outreach.shape_agent_plan(
            load_talent_fixture(STEP), today="2026-09-10"
        )["days_remaining"] == 0

    def test_the_module_never_reads_a_clock(self):
        """Static sweep. A shaper that read the clock could not be pinned by
        any test in this file, so the absence is asserted, not assumed."""
        assert self.clock_calls(module_source()) == []

    def test_the_clock_scanner_fires_on_a_planted_call(self):
        """__CONTROL for the sweep above."""
        planted = "    age = (datetime.now().date() - replied.date()).days\n"

        assert self.clock_calls(planted) == ["datetime.now("]

    @staticmethod
    def clock_calls(source: str) -> list[str]:
        needles = ("datetime.now(", "date.today(", "utcnow(", "time.time(")
        return [needle for needle in needles if needle in source]

    def test_the_shapers_do_not_mutate_what_they_are_given(self):
        """Pure in the other sense too: an argument comes back unchanged."""
        for name in (STEP, DASHBOARD, PENDING, MISSED, ACTIVITY):
            payload = load_talent_fixture(name)
            before = copy.deepcopy(payload)
            shaper_for(name)(payload)
            assert payload == before, name


# --- the plan and its dead channel ----------------------------------------


class TestThePlanAndTheChannels:

    def test_the_entitlement_is_read_verbatim(self, plan):
        assert plan["plan"] == 2
        assert plan["outreach_mode"] == "auto"
        assert plan["auto_run"] is True
        assert plan["auto_run_raw"] == 1
        assert plan["plan_expired"] is False
        assert plan["setup_complete"] is True
        assert plan["credits"] == {"added": 0, "left": 0, "plan": 0}

    def test_one_of_two_channels_is_live(self, plan):
        assert plan["channels_ready"] == ["gmail"]
        assert plan["channels_not_ready"] == ["linkedin"]
        assert plan["channels"] == [
            {"channel": "gmail", "connected": True, "template": True, "ready": True},
            {
                "channel": "linkedin",
                "connected": False,
                "template": False,
                "ready": False,
            },
        ]

    def test_the_dead_channel_is_an_actionable_line_not_a_flags_dict(self, report):
        assert report["channels"]["not_ready"] == ["linkedin"]
        assert "linkedin" in report["channels"]["action"]
        assert any("linkedin" in action for action in report["actions"])

    def test_the_dead_channel_is_tied_to_uplers_own_failure_text(self, report):
        """11 of the 16 failed runs carry Uplers' own text naming LinkedIn.
        Both halves come out of the captures; neither is asserted alone."""
        assert report["channels"]["failures_naming_a_dead_channel"] == 11
        assert "11 of the 16 failed runs" in report["channels"]["action"]

    def test_the_two_opaque_fields_are_carried_and_not_interpreted(self, plan):
        assert plan["unread_fields"] == {
            "all_over_status": True,
            "conversion_offer": None,
        }


# --- the counters ---------------------------------------------------------


class TestTheDashboardCounters:

    def test_every_counter_is_read_verbatim(self, dashboard):
        assert dashboard["runs"] == {
            "total_jobs_run": TOTAL_RUNS,
            "today_agent_runs": 0,
            "jobs_in_queue": 0,
            "max_limit": 8,
        }
        assert dashboard["replies"] == {
            "positive": POSITIVE_REPLIES,
            "unseen": UNSEEN_REPLIES,
            "reminders": 7,
        }
        assert dashboard["tailoring"] == {"tailored_resumes": 0}
        assert dashboard["interviews"] == {"count": 0, "pending_feedback": 0}

    def test_the_three_p_typo_key_is_read_at_its_real_spelling(self, dashboard):
        """Uplers spells it `has_submitted_happpy_feedback`. Reading it at a
        corrected spelling would silently return None forever."""
        assert "has_submitted_happpy_feedback" in load_talent_fixture(DASHBOARD)["data"]
        assert dashboard["flags"]["happy_feedback_submitted"] is False

    def test_containment_between_the_reply_counters_is_never_claimed(self, dashboard):
        note = " ".join(dashboard["notes"])

        assert "INDEPENDENT" in note
        assert "does not say the 7 unseen are among the 8 positive" in note

    def test_the_cap_field_is_not_described_as_a_quota(self, dashboard):
        note = " ".join(dashboard["notes"])

        assert "max_limit is Uplers' own cap field" in note
        assert "not described as a quota" in note


# --- the activity log -----------------------------------------------------


class TestTheActivityLog:

    def test_the_run_totals(self, activity):
        assert activity["total_reported"] == TOTAL_RUNS
        assert activity["rows_read"] == TOTAL_RUNS
        assert activity["by_status"] == {"Completed": COMPLETED, "Failed": FAILED}
        assert activity["completed"] == COMPLETED
        assert activity["failed"] == FAILED
        assert activity["companies"] == 42
        assert activity["page"] == 1
        assert activity["limit"] == 50

    def test_agent_versus_manual_and_tailored_versus_not(self, activity):
        assert activity["by_agent"] == {"agent_run": 48, "manual": 0, "unstated": 0}
        assert activity["by_tailor"] == {
            "tailored": 0,
            "not_tailored": 48,
            "unstated": 0,
        }

    def test_the_yes_no_spelling_is_actually_handled(self):
        """MEASURED: this route spells its booleans "Yes"/"No" with a capital,
        which talent_shape.truthy answers None to. If that were left
        unhandled every row would land in `unstated`."""
        rows = load_talent_fixture(ACTIVITY)["data"]["list"]

        assert {row["used_agent"] for row in rows} == {"Yes"}
        assert {row["used_tailor"] for row in rows} == {"No"}

    def test_label_and_source_splits(self, activity):
        assert activity["by_label"] == {"Uplers": 46, "Extension": 2}
        assert activity["by_source"] == {"internal": 46, "external": 2}

    def test_the_window_of_logged_activity(self, activity):
        assert activity["first_activity"] == "2026-08-01 17:49:24"
        assert activity["last_activity"] == "2026-08-21 11:41:24"
        assert activity["activity_stamps_carry_offset"] is False


class TestTheCannedReasonIsNotADiagnosis:

    def test_the_canned_reason_really_is_in_the_payload(self):
        """__CONTROL. The exclusion below only means something because the
        string is there: MEASURED on all 32 Completed rows and on none of the
        16 Failed ones."""
        rows = load_talent_fixture(ACTIVITY)["data"]["list"]
        canned = [
            row
            for row in rows
            if row["discard_reason"] == outreach.CANNED_DISCARD_REASON
        ]

        assert len(canned) == COMPLETED
        assert {row["status_string"] for row in canned} == {"Completed"}
        assert all(row["discard_reason"] for row in rows)

    def test_it_never_becomes_a_failure_reason(self, activity):
        reasons = [entry["reason"] for entry in activity["failure_reasons"]]

        assert outreach.CANNED_DISCARD_REASON not in reasons
        assert sum(entry["count"] for entry in activity["failure_reasons"]) == FAILED
        assert activity["canned_reason_rows"] == COMPLETED

    def test_the_real_reasons_are_uplers_own_words_ranked(self, activity):
        counts = [entry["count"] for entry in activity["failure_reasons"]]

        assert counts == sorted(counts, reverse=True)
        assert counts == [11, 3, 1, 1]
        assert "LinkedIn" in activity["failure_reasons"][0]["reason"]

    def test_the_placeholder_is_called_a_placeholder(self, activity):
        note = " ".join(activity["notes"])

        assert "placeholder, not a diagnosis" in note


# --- the read-through -----------------------------------------------------


class TestTheHeadlineIsImpossibleToMiss:

    def test_the_headline_is_the_first_key_and_names_the_numbers(self, report):
        assert list(report)[0] == "headline"
        assert list(report)[1] == "needs_reply"
        assert "8 positive replies" in report["headline"]
        assert "7 are unseen" in report["headline"]
        assert "7 reply threads are waiting" in report["headline"]

    def test_the_headline_names_the_stalest_reply_with_company_and_category(
        self, report, missed
    ):
        oldest = missed["rows"][0]

        assert oldest["company"] in report["headline"]
        assert oldest["contact_name"] in report["headline"]
        assert oldest["reply_category"] in report["headline"]
        assert "waiting %d days" % OLDEST_AGE_DAYS in report["headline"]

    def test_every_waiting_row_carries_what_it_takes_to_act(self, report):
        rows = report["needs_reply"]["rows"]

        assert len(rows) == WAITING
        for row in rows:
            assert row["company"]
            assert row["job_title"]
            assert row["contact_name"]
            assert row["reply_category"]
            assert row["age_days"] is not None
            assert row["via"] == "Gmail"

    def test_the_needs_reply_block_carries_the_counters_and_the_window(self, report):
        assert report["needs_reply"]["positive_replies"] == POSITIVE_REPLIES
        assert report["needs_reply"]["unseen_replies"] == UNSEEN_REPLIES
        assert report["needs_reply"]["waiting"] == WAITING
        assert report["needs_reply"]["window_days"] == 15
        assert report["needs_reply"]["oldest_age_days"] == OLDEST_AGE_DAYS

    def test_the_first_action_is_answering_them(self, report):
        assert report["actions"][0].startswith("Answer 7 positive replies")
        assert "oldest has waited 12 days" in report["actions"][0]


class TestTheReadThroughCrossChecks:

    def test_the_four_cross_checks_all_agree_on_the_captures(self, report):
        assert [check["agree"] for check in report["cross_checks"]] == [True] * 4
        assert [check["claim"] for check in report["cross_checks"]] == [
            "jobs the agent has run",
            "replies waiting on an answer",
            "resumes tailored",
            "jobs queued",
        ]

    def test_a_cross_check_can_actually_fail(self):
        """__CONTROL. Move one counter in one payload and the agreement that
        the four checks report must break - otherwise they certify nothing."""
        payload = copy.deepcopy(load_talent_fixture(DASHBOARD))
        payload["data"]["total_jobs_run"] = 47

        report = outreach.agent_readthrough(
            plan=outreach.shape_agent_plan(load_talent_fixture(STEP), today=TODAY),
            dashboard=outreach.shape_agent_dashboard(payload),
            pending=outreach.shape_pending_jobs(load_talent_fixture(PENDING)),
            missed=outreach.shape_missed_followups(
                load_talent_fixture(MISSED), now=TODAY
            ),
            activity=outreach.shape_activity(load_talent_fixture(ACTIVITY)),
        )

        assert report["cross_checks"][0]["agree"] is False
        assert report["cross_checks"][0]["values"] == {
            "activity_rows_read": 48,
            "activity_total_reported": 48,
            "dashboard_total_jobs_run": 47,
        }
        assert any(
            entry.get("field") == "jobs the agent has run"
            for entry in report["disagreements"]
        )

    def test_a_swapped_pair_of_shapes_is_refused(self, plan, dashboard, pending,
                                                 missed, activity):
        """__CONTROL for the slot guard. Five similar dicts are easy to pass in
        the wrong order, and a swapped pair would render as a real read."""
        with pytest.raises(OutreachError, match="not interchangeable"):
            outreach.agent_readthrough(
                plan=dashboard,
                dashboard=plan,
                pending=pending,
                missed=missed,
                activity=activity,
            )

    def test_an_unshaped_payload_in_a_slot_is_refused(self, plan, dashboard,
                                                      pending, missed):
        with pytest.raises(OutreachError, match="not a shaped dict"):
            outreach.agent_readthrough(
                plan=plan,
                dashboard=dashboard,
                pending=pending,
                missed=missed,
                activity=load_talent_fixture(ACTIVITY)["data"]["list"],
            )


class TestTheTwoMisPairingsAreResolvedNotReported:
    """Both "disagreements" turned out to be mis-pairings, settled 2026-08-24.

    These tests replaced four that pinned the OLD behaviour - both pairs
    emitted as unresolved disagreements. Those four went red the moment the
    resolution landed, which is what they were for.
    """

    def test_neither_mis_pairing_is_reported_as_a_disagreement_any_more(self, report):
        fields = [entry["field"] for entry in report["disagreements"]]

        assert "consent_email_job_scan" not in fields
        assert "auto_run" not in fields

    def test_both_are_reported_as_resolved_instead(self, report):
        fields = sorted(entry["field"] for entry in report["resolved"])

        assert fields == ["auto_run", "consent_email_job_scan"]

    def test_the_consent_resolution_names_the_authoritative_route(self, report):
        entry = next(
            item
            for item in report["resolved"]
            if item["field"] == "consent_email_job_scan"
        )

        assert entry["authoritative_route"] == (
            "talent/outreach/recommended-jobs-meta-email"
        )
        assert entry["authoritative_value"] is True
        assert entry["agrees_with_this_route"] is True
        assert entry["this_route_value"] is True
        # The mis-paired side is kept, so the record says what was ruled out.
        assert entry["mis_paired_value"] is False
        assert "consent_interview_email_scan" in entry["why_different"]
        # The receipt is a file on disk, not a recollection.
        assert (FIXTURE_DIR / "outreach_meta_email.json").is_file()

    def test_the_authoritative_fixture_actually_says_what_is_claimed(self):
        """The resolution rests on a captured payload; read it off disk."""
        meta = load_talent_fixture("outreach_meta_email")["data"]

        assert meta["has_consent"] is True
        assert meta["consent_email_job_scan"] == "2026-08-12 01:32:36"
        assert meta["last_job_scan"] == "2026-08-23 06:58:17"
        assert meta["total_jobs"] == 79
        # And the dashboard copy agrees with it, which is why it is `resolved`.
        assert load_talent_fixture(DASHBOARD)["data"]["consent_email_job_scan"] is True

    def test_the_auto_run_resolution_admits_what_it_did_not_settle(self, report):
        """A mode and a permission, not two readings of one thing - but what
        the permission GATES was never measured, and the record says so."""
        entry = next(
            item for item in report["resolved"] if item["field"] == "auto_run"
        )

        assert entry["mode_value"] is True
        assert entry["mode_raw"] == 1
        assert entry["permission_value"] is False
        assert "MODE" in entry["verdict"] and "PERMISSION" in entry["verdict"]
        assert entry["still_unresolved"]
        assert "48" in entry["still_unresolved"]

    def test_a_dashboard_that_stops_agreeing_becomes_a_real_disagreement(self):
        """__CONTROL, and its meaning is INVERTED from the test it replaced.

        The old control flipped this field and expected the disagreement to
        vanish. Now the captured value AGREES with the authoritative route, so
        flipping it is a route going stale against a measured answer - a new
        fact, and reported as one rather than absorbed by the old ruling.
        """
        payload = copy.deepcopy(load_talent_fixture(DASHBOARD))
        payload["data"]["consent_email_job_scan"] = False

        shaped = outreach.shape_agent_dashboard(payload)

        assert shaped["resolved"] == []
        assert len(shaped["disagreements"]) == 1
        entry = shaped["disagreements"][0]
        assert entry["field"] == "consent_email_job_scan"
        assert entry["other_source"] == outreach.CONSENT_RESOLUTION[
            "authoritative_route"
        ]
        assert "stale" in entry["note"]

    def test_an_agreeing_capture_emits_no_disagreement(self):
        """__CONTROL, the other arm: the resolved line is emitted because the
        values MATCH, not because it is hardcoded."""
        shaped = outreach.shape_agent_dashboard(load_talent_fixture(DASHBOARD))

        assert shaped["disagreements"] == []
        assert len(shaped["resolved"]) == 1


class TestTheReportSaysNothingItCannotDerive:

    def test_no_contact_route_reaches_the_shaped_output(self, report):
        leaks = [
            "%s = %r" % (trail, text)
            for trail, text in strings(report)
            if "@" in text or "linkedin.com/in" in text.lower()
        ]

        assert leaks == []

    def test_the_leak_sweep_can_actually_fire(self):
        """__CONTROL. A sweep never shown failing certifies nothing."""
        planted = {
            "needs_reply": {
                "rows": [{"contact_name": "someone@example.invalid"}],
            }
        }

        leaks = [trail for trail, text in strings(planted) if "@" in text]

        assert leaks == ["$.needs_reply.rows[0].contact_name"]

    def test_the_payload_really_did_carry_the_routes_that_were_withheld(self, missed):
        """Nothing is dropped silently: what is withheld is named, and it was
        genuinely present.

        THE SECOND HALF READS THE SPECIMEN, NOT THE CAPTURED FIXTURE, and the
        reason is the whole point of this test. It used to read
        `outreach_missed_followups.json`. On 2026-08-24 that capture stopped
        recording contact routes at all - the publish-gate census found real
        signature blocks surviving in its `message_full` prose after a scrub
        that had walked only the structured fields, so the redactor now DROPS
        those keys at capture time.

        That is the right fix to the leak and it silently guts this proof: a
        row that no longer carries the keys satisfies "they were withheld"
        vacuously, and the test would have gone green while proving nothing.
        It is the same shape as the defect recorded at the top of
        `test_fixture_hygiene.py`, where a rewrite deleted a specimen and a
        control turned into a skip.

        The specimen exists for exactly this. It is synthetic, committed, owned
        by this repository, and its contact fields are PRESENT ON PURPOSE, so
        the claim stays falsifiable without a real value on disk.
        """
        specimen = json.loads(
            (FIXTURE_DIR / "_specimens" / "outreach_contact_leak.json").read_text(
                encoding="utf-8"
            )
        )
        row = specimen["data"]["rows"][0]

        assert missed["withheld_fields"] == list(outreach.WITHHELD_CONTACT_KEYS)
        for key in outreach.WITHHELD_CONTACT_KEYS:
            assert row[key], (
                "the specimen no longer carries %r, so 'it was withheld' is "
                "vacuously true and this test proves nothing" % key
            )
        assert any("withheld from this shape" in note for note in missed["notes"])

    def test_the_captured_fixture_carries_no_real_contact_value__CONTROL(self):
        """__CONTROL. The live-derived fixture must be clean, by measurement.

        The pair is the point. The test above proves the withheld keys are real
        keys by finding them in the specimen; this one proves the live-derived
        fixture carries nothing real. Passing only the first would be satisfied
        by a redactor that cleaned nothing.

        TWO DIFFERENT TREATMENTS, and the distinction is worth stating because
        the first draft of this control got it wrong and demanded the stricter
        one everywhere. The STRUCTURED contact fields are SUBSTITUTED, not
        deleted - they keep their names and take synthetic values, so the row
        still exercises the shaping code. The PROSE field `message_full` is
        DELETED outright, because prose cannot be substituted field-by-field
        and it was the one that actually leaked: the 2026-08-24 census found
        intact email signature blocks surviving inside it, carrying a given
        name, a job title, an employer and two phone numbers, in a file whose
        structured fields had all been correctly scrubbed years-of-effort ago.
        The scrubbed neighbours are what made it read as synthetic.
        """
        row = load_talent_fixture(MISSED)["data"]["rows"][0]

        assert "message_full" not in row, (
            "the prose field is back. It is the field that leaked, and it "
            "cannot be scrubbed in place -- it is dropped or it is a leak."
        )
        leaks = list(contact_leaks(load_talent_fixture(MISSED)))
        assert leaks == [], (
            "the detector still finds contact routes in the captured fixture: "
            "%s" % [trail for _, trail, _ in leaks][:5]
        )

    def test_the_window_days_meaning_is_not_invented(self, missed):
        assert missed["window_days"] == 15
        assert "has not been measured here" in missed["window_days_meaning"]

    def test_every_emitted_number_traces_to_a_captured_field(self, report):
        """The numbers on the face of the report, each against its source."""
        step = load_talent_fixture(STEP)["data"]
        dash = load_talent_fixture(DASHBOARD)["data"]
        rows = load_talent_fixture(MISSED)["data"]
        runs = load_talent_fixture(ACTIVITY)["data"]

        assert report["needs_reply"]["positive_replies"] == dash["total_positive_replies"]
        assert report["needs_reply"]["unseen_replies"] == dash["total_unseen_replies"]
        assert report["needs_reply"]["waiting"] == len(rows["rows"]) == rows["count"]
        assert report["needs_reply"]["window_days"] == rows["days"]
        assert report["queue"]["jobs_in_queue"] == dash["jobs_in_queue"]
        assert report["queue"]["today_agent_runs"] == dash["today_agent_runs"]
        assert report["queue"]["max_limit"] == dash["max_limit"]
        assert report["agent_activity"]["runs_logged"] == runs["total"]
        assert report["agent_activity"]["tailored_resumes"] == dash["total_tailored_resumes"]
        assert report["plan"]["plan"] == step["plan"]
        assert report["plan"]["end_date"] == step["plan_end_date"]
        assert report["interviews"]["count"] == dash["interview_count"]

    def test_the_whole_report_is_json_serialisable(self, report):
        """It is going out through an MCP tool, so it has to survive the wire."""
        assert json.loads(json.dumps(report))["headline"] == report["headline"]


class TestTheModuleHasNoWritePath:
    """The slice's own boundary, asserted rather than promised: this module
    reads the agent he already pays for and never becomes a second one."""

    def test_the_contract_is_the_six_names_the_server_wires(self):
        for name in (
            "shape_agent_plan",
            "shape_agent_dashboard",
            "shape_pending_jobs",
            "shape_missed_followups",
            "shape_activity",
            "agent_readthrough",
            "unwrap",
        ):
            assert callable(getattr(outreach, name)), name

    def test_no_function_here_is_named_for_an_action(self):
        acting = sorted(
            name
            for name in vars(outreach)
            if not name.startswith("_")
            and callable(getattr(outreach, name))
            and any(
                verb in name.lower()
                for verb in ("apply", "send", "post", "consent", "run", "write",
                             "save", "update", "delete", "set_")
            )
        )

        assert acting == []

    def test_nothing_in_the_module_can_reach_the_network(self):
        source = module_source().lower()

        for verb in ("httpx", "requests.", "urllib", "aiohttp", "socket",
                     "def apply", "async def"):
            assert verb not in source, verb
