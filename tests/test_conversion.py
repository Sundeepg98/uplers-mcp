"""The conversion ring, driven entirely by live-captured payloads.

Every input in this file is one of the four envelopes already committed under
`tests/fixtures/outreach_*.json`, or a MUTATION of one (a key deleted, a
counter changed, a masked name planted back). Not one payload here was written
by hand, and that is deliberate: a payload invented by the same head that wrote
the reader agrees with the reader by construction and proves nothing.

THESE FOUR FIXTURES WERE ORPHANS UNTIL THIS FILE EXISTED. They were captured
off his live session on 2026-08-23/24 and then nothing read them - no tool
consumed one, no test asserted on one. `test_fixture_hygiene.py` globbed them
for the PII sweep, but SCANNING A PAYLOAD IS NOT USING IT: a sweep proves a
file carries no contact route and proves nothing at all about whether the file
earns its place in the repository. `TestTheFourFixturesAreLoadBearing` is the
assertion that they now do, and it is written to go red if a future refactor
quietly stops reading one.

CONTROLS. Every guard here is SHOWN FAILING, because a check that cannot fail
certifies nothing. Each was run red before it was run green, with the shaper
temporarily broken in the way the control exists to catch:

    test_a_planted_employee_name_is_never_returned__CONTROL
        The name-withholding control, and the ONLY one that can prove it. The
        committed fixture has `employee_name` MASKED at capture time to
        "Redacted Contact 1", so a sweep over the fixture alone would pass by
        having nothing to find. This plants a real-looking name back on the row
        and proves the shaper still never prints it. Watched failing with
        `_reply_row` carrying `"employee_name": _text(raw.get("employee_name"))`:
        `assert 'Priya Raghunathan' not in ...`.

    test_the_planted_name_really_is_in_the_input__CONTROL
        __CONTROL for the control above. `name not in output` is trivially true
        if the plant never landed, so this proves the mutated payload actually
        carries the name before the shaper is asked to withhold it.

    test_an_absent_agent_run_count_is_none_and_never_zero__CONTROL
        Deletes `jobs_run` and proves it renders None. Watched failing with
        `_int(data.get("jobs_run")) or 0`: `assert 0 is None`.

    test_an_absent_pending_flag_is_none_and_never_false__CONTROL
        Deletes `has_pending_action` and `pending` and proves both render None
        rather than False - and that the unknown lands in `unknown` rather than
        being read as an all-clear. Watched failing with `_flag(...) or False`:
        `assert False is None`.

    test_an_absent_quota_counter_is_none_and_never_zero__CONTROL
        Deletes `remaining` and proves the counter is None and the cross-check
        goes UNKNOWN rather than agreeing. Watched failing with
        `_int(...) or 0`: `assert 0 is None`.

    test_the_census_can_actually_fail__CONTROL
        `writes(calls) == []` is trivially true when no request was made at
        all, so a broken wiring would pass the census by being broken.

    test_narrowing_to_the_string_arm_refuses_the_integer_route__CONTROL
    test_narrowing_to_the_integer_arm_refuses_the_string_routes__CONTROL
        This ring splits THREE-ONE across the two success idioms, so each arm
        is narrowed in turn and the routes on the other arm are proven to stop
        reading. Proves the envelope check is a real membership test and not a
        truthiness test waving anything through.

    test_a_disagreeing_quota_really_reports_a_disagreement__CONTROL
    test_a_planted_pending_row_contradicts_the_flag__CONTROL
        Both captured payloads AGREE internally, so the cross-checks would look
        correct while being printed unconditionally. Each mutates one field and
        proves the disagreement is computed.
"""

from __future__ import annotations

import copy
import json

import httpx
import pytest

import server
from uplers_server import conversion, endpoints, outreach
from uplers_server.outreach import OutreachError
from uplers_server import session as session_mod
from uplers_server.session import SessionStore
from uplers_server.talent import TalentClient

from conftest import load_talent_fixture, make_transport

TOKEN = "42|bearer-token-that-must-never-be-printed"

#: fixture stem -> route. Kept as ONE mapping so the transport, the envelope
#: sweep and the census all read the same list and a fifth route cannot be
#: added to one of them alone.
FIXTURES = {
    "outreach_value_with_happy": endpoints.EP_OUTREACH_VALUE_WITH_HAPPY,
    "outreach_pending_action": endpoints.EP_OUTREACH_PENDING_ACTION,
    "outreach_followups_pending": endpoints.EP_OUTREACH_FOLLOWUPS_PENDING,
    "outreach_external_remaining": endpoints.EP_OUTREACH_EXTERNAL_REMAINING,
}

BODIES = {route: load_talent_fixture(stem) for stem, route in FIXTURES.items()}

#: The routes that must never be touched. Path siblings in `talent/outreach/*`,
#: every one of which sends something on his behalf or spends an entitlement.
#: Named so the census can assert their ABSENCE by name rather than only
#: asserting "no writes" - a GET at `store-employee-requests` would pass a
#: method check and still be a request at the send route.
FORBIDDEN_SIBLINGS = (
    "talent/outreach/store-employee-requests",
    "talent/outreach/reveal-email",
    "talent/outreach/discard-job",
    "talent/outreach/auto-run-request",
    "talent/outreach/consent-email-job-scan",
)

#: A name with the shape of a real one, planted where the capture masked one.
PLANTED_NAME = "Priya Raghunathan"


def fixture(stem: str) -> dict:
    """A deep copy of one captured envelope, safe to mutate."""
    return copy.deepcopy(load_talent_fixture(stem))


def strings_in(node) -> str:
    return json.dumps(node, default=str)


@pytest.fixture(autouse=True)
def session_file(monkeypatch, tmp_path):
    """No test here may read, write or delete the real data/session.json."""
    path = tmp_path / "session.json"
    monkeypatch.setattr(session_mod, "session_path", lambda: path)
    monkeypatch.setattr(server, "_session_store", lambda: SessionStore(path))
    SessionStore(path).save(TOKEN, method="test")
    return path


def wire(monkeypatch, handler):
    """Let a tool build a real TalentClient, but over a MockTransport."""
    transport, calls = make_transport(handler)
    monkeypatch.setattr(
        server,
        "TalentClient",
        lambda *a, **k: TalentClient(lambda: TOKEN, transport=transport, delay=0),
    )
    return calls


def by_route(bodies, fallback=None):
    """Answer each request from `bodies`, keyed by EXACT route.

    Exact rather than `endswith`, and here that is not a stylistic choice:
    `missed-positive-reply-followups` is a strict PREFIX of
    `missed-positive-reply-followups-pending`, and the two are different routes
    returning different shapes. A loose match is exactly the near-miss this
    file exists to refuse.
    """

    def handler(request):
        route = request.url.path.split("/api/")[-1]
        if route in bodies:
            return httpx.Response(200, json=bodies[route])
        if fallback is None:
            return httpx.Response(404, json={"message": "no stub for %s" % route})
        return httpx.Response(200, json=fallback)

    return handler


def writes(calls):
    """Every request that was not a read. The whole risk surface."""
    return [call for call in calls if call.method != "GET"]


def routes_of(calls) -> list:
    return [call.url.path.split("/api/")[-1] for call in calls]


# --------------------------------------------------------------------------
# The orphan question, first, because it is why this file exists.
# --------------------------------------------------------------------------


class TestTheFourFixturesAreLoadBearing:
    """Each captured payload is EVIDENCE for a tool, not merely PII-swept."""

    @pytest.mark.parametrize("stem", sorted(FIXTURES))
    def test_the_fixture_exists_and_parses(self, stem):
        assert isinstance(load_talent_fixture(stem), dict)

    async def test_every_captured_route_is_one_a_tool_actually_requests(
        self, monkeypatch
    ):
        """The assertion that turns "captured" into "used".

        MEASURED, not listed: both tools are run over a recording transport and
        the routes that actually left are compared against the four fixture
        stems. If a tool stops reading one of these routes, this goes red
        rather than the fixture quietly becoming an orphan again.

        Deliberately SELF-CONTAINED. An earlier draft collected the routes in
        the census class below and asserted against them here, which passed
        only because pytest happened to run the classes in that order - a test
        that depends on another test having run first is not a control, it is a
        coincidence with an assert in it.
        """
        calls = wire(monkeypatch, by_route(BODIES))
        await server.uplers_reply_outcomes()
        await server.uplers_agent_pending()

        assert set(routes_of(calls)) == set(FIXTURES.values())

    def test_every_captured_route_has_a_constant(self):
        """No tool may reach a route this server has not named in endpoints.py."""
        values = {
            value
            for name, value in vars(endpoints).items()
            if name.startswith("EP_") and isinstance(value, str)
        }
        for route in FIXTURES.values():
            assert route in values


# --------------------------------------------------------------------------
# The census. What actually left the client.
# --------------------------------------------------------------------------


class TestNeitherToolCanReachAWriteRoute:
    """MEASURED against the requests that left, not asserted from the source."""

    async def test_reply_outcomes_issues_exactly_two_gets(self, monkeypatch):
        """Two now, and the second one is the point.

        It was one GET until 2026-08-25. The reply rows say what was ASKED and
        carry nothing about whether he answered, and the tool was read aloud as
        a to-do list on two rows that had been answered a fortnight earlier. So
        it now also reads the only resolution signal Uplers exposes, rather
        than leaving a caller to know to look for it.

        Pinned as an ordered list so the SECOND read cannot be quietly dropped:
        without it `completion_state` degrades to "we did not ask", which is a
        weaker answer than the one available.
        """
        calls = wire(monkeypatch, by_route(BODIES))
        await server.uplers_reply_outcomes()

        assert writes(calls) == []
        assert routes_of(calls) == [
            endpoints.EP_OUTREACH_VALUE_WITH_HAPPY,
            endpoints.EP_OUTREACH_FOLLOWUPS_PENDING,
        ]

    async def test_an_unknown_answered_state_never_renders_as_outstanding__CONTROL(
        self, monkeypatch
    ):
        """__CONTROL. The defect this whole change exists to prevent.

        A row saying "requests updated resume" with no completion state beside
        it reads as a task. Both halves are asserted: every row carries
        `answered` and it is `unknown`, and the payload carries a
        `completion_state` saying per-reply resolution is NOT AVAILABLE.

        Watched failing by deleting the per-row marker: the rows come back
        looking exactly like a to-do list, which is what a human did with them.
        """
        wire(monkeypatch, by_route(BODIES))
        result = await server.uplers_reply_outcomes()

        assert result["rows"], "no rows means this control proves nothing"
        for row in result["rows"]:
            assert row["answered"] == "unknown", row
        state = result["completion_state"]
        assert state["per_reply_answered"] == "NOT AVAILABLE"
        assert "check the thread" in state["why"].lower()

    async def test_an_unreadable_pending_count_is_none_and_never_zero__CONTROL(
        self, monkeypatch
    ):
        """__CONTROL. "Nothing outstanding" and "we could not ask" are opposite.

        If the pending route fails, the count must render None. A zero there
        would assert the strongest possible claim - nothing is outstanding -
        on the strength of a failed request.
        """
        def handler(request):
            import httpx
            if endpoints.EP_OUTREACH_FOLLOWUPS_PENDING in str(request.url):
                return httpx.Response(500, json={"message": "boom"})
            return by_route(BODIES)(request)

        wire(monkeypatch, handler)
        result = await server.uplers_reply_outcomes()

        assert result["completion_state"]["uplers_side_followups_pending"] is None

    async def test_agent_pending_issues_exactly_three_gets(self, monkeypatch):
        calls = wire(monkeypatch, by_route(BODIES))
        await server.uplers_agent_pending()

        assert writes(calls) == []
        assert routes_of(calls) == [
            endpoints.EP_OUTREACH_PENDING_ACTION,
            endpoints.EP_OUTREACH_FOLLOWUPS_PENDING,
            endpoints.EP_OUTREACH_EXTERNAL_REMAINING,
        ]

    async def test_the_window_travels_as_a_query_parameter(self, monkeypatch):
        """`days` must reach the wire, and only on the route that takes it."""
        calls = wire(monkeypatch, by_route(BODIES))
        await server.uplers_agent_pending(days=30)

        windowed = [
            call
            for call in calls
            if call.url.path.endswith(endpoints.EP_OUTREACH_FOLLOWUPS_PENDING)
        ]
        assert len(windowed) == 1
        assert windowed[0].url.params.get("days") == "30"

        for call in calls:
            if call is not windowed[0]:
                assert "days" not in call.url.params

    async def test_no_write_sibling_is_ever_requested(self, monkeypatch):
        """An EXACT route list, not merely 'no writes'.

        A GET at `store-employee-requests` would pass a method check and still
        be a request at the outreach SEND route, so the absence is asserted by
        name.
        """
        calls = wire(monkeypatch, by_route(BODIES))
        await server.uplers_reply_outcomes()
        await server.uplers_agent_pending()

        seen = routes_of(calls)
        for forbidden in FORBIDDEN_SIBLINGS:
            assert forbidden not in seen

    def test_the_conversion_module_names_no_write_route(self):
        """Not one of them may be a STRING in `uplers_server/conversion.py`.

        The census measures one run; this measures the module. A route that
        never fires today but is spelled in the source is one edit away from
        firing, which is the rule endpoints.py already applies: a constant is
        an invitation to call it.
        """
        source = (
            __import__("pathlib").Path(conversion.__file__).read_text(encoding="utf-8")
        )
        for forbidden in FORBIDDEN_SIBLINGS:
            assert forbidden not in source

    async def test_the_census_can_actually_fail__CONTROL(self, monkeypatch):
        """`writes(calls) == []` is trivially true when nothing was requested.

        Proves the transport records a write when one happens and that
        `writes` recognises it, so the assertions above are measuring
        something.
        """
        calls = wire(monkeypatch, by_route({}, fallback={"status": 200, "data": {}}))
        client = server.TalentClient(lambda: TOKEN)
        async with client:
            await client.post_json("talent/outreach/store-employee-requests", {"x": 1})

        assert len(writes(calls)) == 1
        assert routes_of(calls) == ["talent/outreach/store-employee-requests"]


# --------------------------------------------------------------------------
# The counterparty's name. The control the brief for this slice named.
# --------------------------------------------------------------------------


class TestTheCounterpartyIsNeverNamed:
    """`employee_name` and `logo_url` may not reach a caller, ever."""

    def test_the_captured_rows_read_seven_positive_gmail_replies(self):
        """The baseline the controls below mutate away from."""
        shaped = conversion.shape_reply_outcomes(fixture("outreach_value_with_happy"))
        assert shaped["replies_on_this_route"] == 7
        assert shaped["by_reply_type"] == {"positive": 7}
        assert shaped["by_channel"] == {"gmail": 7}
        assert shaped["agent_runs_reported"] == 32
        assert shaped["interview_companies"] == []

    def test_the_asks_survive_verbatim(self):
        """The whole point of the tool: what each reply wanted."""
        shaped = conversion.shape_reply_outcomes(fixture("outreach_value_with_happy"))
        assert "Willing to refer; requests updated resume" in shaped["asks"]
        assert "Requests form, will proceed with referral" in shaped["asks"]
        assert sum(shaped["asks"].values()) == 7

    def test_the_planted_name_really_is_in_the_input__CONTROL(self):
        """__CONTROL for the withholding control below.

        `name not in output` is trivially true if the plant never landed, so
        this proves the mutated payload carries the name before the shaper is
        asked to withhold it.
        """
        payload = fixture("outreach_value_with_happy")
        payload["data"]["response"][0]["employee_name"] = PLANTED_NAME
        assert PLANTED_NAME in strings_in(payload)

    def test_a_planted_employee_name_is_never_returned__CONTROL(self):
        """__CONTROL. The ONLY test that can prove the withholding works.

        WATCHED FAILING. With `_reply_row` carrying
        `"employee_name": _text(raw.get("employee_name"))` this went red on
        `assert 'Priya Raghunathan' not in ...`, and every other test in this
        class stayed green - which is the point: the committed fixture has the
        name MASKED to "Redacted Contact 1" at capture time, so a sweep run
        only against it passes by having nothing to find.
        """
        payload = fixture("outreach_value_with_happy")
        payload["data"]["response"][0]["employee_name"] = PLANTED_NAME

        shaped = conversion.shape_reply_outcomes(payload)

        assert PLANTED_NAME not in strings_in(shaped)
        assert shaped["rows"][0]["employee_name_withheld"] is True
        assert "employee_name" in shaped["withheld"]

    def test_the_masked_name_is_not_returned_either(self):
        """Even the SUBSTITUTE stays out. The key is refused, not the value."""
        shaped = conversion.shape_reply_outcomes(fixture("outreach_value_with_happy"))
        assert "Redacted Contact" not in strings_in(shaped)

    def test_the_logo_url_is_never_returned(self):
        """This half is proven against the REAL payload, not a mutation.

        `logo_url` is NOT masked at capture time - the committed fixture
        carries the live CDN addresses verbatim - so unlike the name, the
        fixture itself is sufficient evidence here.
        """
        payload = fixture("outreach_value_with_happy")
        assert "cloudfront.net" in strings_in(payload)

        shaped = conversion.shape_reply_outcomes(payload)

        assert "cloudfront.net" not in strings_in(shaped)
        assert "http" not in strings_in(shaped)
        assert shaped["rows"][0]["logo_url_withheld"] is True
        assert "logo_url" in shaped["withheld"]

    async def test_the_tool_withholds_it_too_not_just_the_shaper(self, monkeypatch):
        """A test exercising a copy of the tool proves nothing about the tool."""
        payload = fixture("outreach_value_with_happy")
        payload["data"]["response"][0]["employee_name"] = PLANTED_NAME
        wire(
            monkeypatch,
            by_route({endpoints.EP_OUTREACH_VALUE_WITH_HAPPY: payload}),
        )

        result = await server.uplers_reply_outcomes()

        assert PLANTED_NAME not in strings_in(result)
        assert "cloudfront.net" not in strings_in(result)


# --------------------------------------------------------------------------
# Absent is not zero, and absent is not false.
# --------------------------------------------------------------------------


class TestAbsentIsNotZeroAndIsNotFalse:
    """"Nothing is pending" and "the route did not say" are opposite facts."""

    def test_an_absent_agent_run_count_is_none_and_never_zero__CONTROL(self):
        """__CONTROL. Deletes `jobs_run` and proves it renders None.

        WATCHED FAILING with `_int(data.get("jobs_run")) or 0`:
        `assert 0 is None`. The happy path cannot see this defect - 32 survives
        `or 0` unchanged - so only the absent case can.
        """
        payload = fixture("outreach_value_with_happy")
        del payload["data"]["jobs_run"]

        shaped = conversion.shape_reply_outcomes(payload)

        assert shaped["agent_runs_reported"] is None

    def test_an_absent_pending_flag_is_none_and_never_false__CONTROL(self):
        """__CONTROL for both tri-state flags in `uplers_agent_pending`.

        WATCHED FAILING with `_flag(...) or False` in both shapers:
        `assert False is None`. The captured payloads read false and true
        respectively, so neither happy path can see it.
        """
        action = fixture("outreach_pending_action")
        del action["data"]["has_pending_action"]
        followups = fixture("outreach_followups_pending")
        del followups["data"]["pending"]

        shaped_action = conversion.shape_pending_action(action)
        shaped_followups = conversion.shape_followups_pending(followups)

        assert shaped_action["has_pending_action"] is None
        assert shaped_followups["pending"] is None

    def test_an_unknown_flag_is_not_read_as_an_all_clear__CONTROL(self):
        """__CONTROL. The consequence of the tri-state, at the report level.

        An unread flag must land in `unknown` and NEVER in `blocked_on_you`,
        and `anything_blocked` must not be allowed to read as good news while
        something is unknown. WATCHED FAILING with `blocked` built from
        `if value is not False`: the unknown flag appeared in `blocked_on_you`.
        """
        action = fixture("outreach_pending_action")
        del action["data"]["has_pending_action"]
        followups = fixture("outreach_followups_pending")
        del followups["data"]["pending"]

        report = conversion.agent_pending(
            pending_action=conversion.shape_pending_action(action),
            followups=conversion.shape_followups_pending(followups),
            external=conversion.shape_external_remaining(
                fixture("outreach_external_remaining")
            ),
        )

        assert report["blocked_on_you"] == []
        assert sorted(report["unknown"]) == [
            "agent_pending_action",
            "missed_followups",
        ]
        assert report["anything_blocked"] is False
        assert "UNKNOWN" in strings_in(report["headline"])

    def test_an_absent_quota_counter_is_none_and_never_zero__CONTROL(self):
        """__CONTROL. Deletes `remaining`; the counter AND the cross-check.

        WATCHED FAILING with `_int(...) or 0`: `assert 0 is None`. On a quota
        the difference is between "none left" and "we could not read how many
        are left", and the cross-check must go UNKNOWN rather than agreeing
        with a zero nobody sent.
        """
        payload = fixture("outreach_external_remaining")
        del payload["data"]["remaining"]

        shaped = conversion.shape_external_remaining(payload)

        assert shaped["remaining"] is None
        assert shaped["counters_agree"]["values"]["used_plus_remaining"] is None
        assert shaped["counters_agree"]["unknown"] == ["used_plus_remaining"]

    def test_an_absent_window_is_none_and_never_zero(self):
        """A window of 0 days and an unreported window are different answers."""
        payload = fixture("outreach_followups_pending")
        del payload["data"]["days"]

        assert conversion.shape_followups_pending(payload)["days_echoed"] is None


# --------------------------------------------------------------------------
# The envelope. Three strings and an integer, per route.
# --------------------------------------------------------------------------


class TestTheEnvelopeIsCheckedAndNotGuessed:
    """`outreach.unwrap` is the only reader; both idioms are exercised."""

    def test_the_captured_idioms_are_what_this_ring_measured(self):
        """Pins the three-one split so a recapture that moved one goes red."""
        assert load_talent_fixture("outreach_value_with_happy")["status"] == "success"
        assert load_talent_fixture("outreach_pending_action")["status"] == "success"
        assert load_talent_fixture("outreach_external_remaining")["status"] == "success"
        assert load_talent_fixture("outreach_followups_pending")["status"] == 200

    def test_narrowing_to_the_string_arm_refuses_the_integer_route__CONTROL(
        self, monkeypatch
    ):
        """__CONTROL. Proves the integer idiom is genuinely checked."""
        monkeypatch.setattr(outreach, "SUCCESS_VALUES", ("success",))

        with pytest.raises(OutreachError) as caught:
            conversion.shape_followups_pending(fixture("outreach_followups_pending"))

        assert "status 200" in str(caught.value)

    def test_narrowing_to_the_integer_arm_refuses_the_string_routes__CONTROL(
        self, monkeypatch
    ):
        """__CONTROL. The mirror, for the three that answer the string."""
        monkeypatch.setattr(outreach, "SUCCESS_VALUES", (200,))

        for stem, shaper in (
            ("outreach_value_with_happy", conversion.shape_reply_outcomes),
            ("outreach_pending_action", conversion.shape_pending_action),
            ("outreach_external_remaining", conversion.shape_external_remaining),
        ):
            with pytest.raises(OutreachError) as caught:
                shaper(fixture(stem))
            assert "'success'" in str(caught.value)

    @pytest.mark.parametrize(
        "stem,shaper",
        [
            ("outreach_value_with_happy", conversion.shape_reply_outcomes),
            ("outreach_pending_action", conversion.shape_pending_action),
            ("outreach_followups_pending", conversion.shape_followups_pending),
            ("outreach_external_remaining", conversion.shape_external_remaining),
        ],
    )
    def test_a_missing_data_key_is_refused_not_read_as_empty(self, stem, shaper):
        """Rule 4: no `data` key is NOT "nothing to report"."""
        payload = fixture(stem)
        del payload["data"]

        with pytest.raises(OutreachError) as caught:
            shaper(payload)

        assert "no `data` key" in str(caught.value)

    def test_a_list_where_a_dict_was_measured_is_refused(self):
        """Rule 5. A container change means the route moved, not that it is empty."""
        payload = fixture("outreach_value_with_happy")
        payload["data"] = []

        with pytest.raises(OutreachError):
            conversion.shape_reply_outcomes(payload)


# --------------------------------------------------------------------------
# Drift, disagreement, and the swap guard.
# --------------------------------------------------------------------------


class TestDisagreementIsComputedAndNotPrinted:
    """The captured payloads AGREE, so agreement alone proves nothing."""

    def test_the_captured_quota_agrees(self):
        shaped = conversion.shape_external_remaining(
            fixture("outreach_external_remaining")
        )
        assert shaped["counters_agree"]["agree"] is True
        assert (shaped["limit"], shaped["used"], shaped["remaining"]) == (8, 0, 8)

    def test_a_disagreeing_quota_really_reports_a_disagreement__CONTROL(self):
        """__CONTROL. Changes one counter and proves the check is computed."""
        payload = fixture("outreach_external_remaining")
        payload["data"]["used"] = 3

        shaped = conversion.shape_external_remaining(payload)

        assert shaped["counters_agree"]["agree"] is False
        assert shaped["counters_agree"]["values"]["used_plus_remaining"] == 11

    def test_the_captured_pending_action_agrees(self):
        shaped = conversion.shape_pending_action(fixture("outreach_pending_action"))
        assert shaped["has_pending_action"] is False
        assert shaped["hrs_returned"] == 0
        assert shaped["agreement"]["agree"] is True

    def test_a_planted_pending_row_contradicts_the_flag__CONTROL(self):
        """__CONTROL. A row present while the flag says nothing is pending.

        This route's response is DISCARDED by Uplers' own UI, so nothing in
        their frontend holds its shape steady. A flag and a list that disagree
        is exactly the drift this reports rather than resolves.
        """
        payload = fixture("outreach_pending_action")
        payload["data"]["hrs"] = [{"id": 1}]

        shaped = conversion.shape_pending_action(payload)

        assert shaped["hrs_returned"] == 1
        assert shaped["agreement"]["agree"] is False

    def test_the_data_keys_are_reported_so_drift_is_visible(self):
        """Field NAMES, never values - the drift detector for a route

        whose response nobody in Uplers' own frontend reads.
        """
        shaped = conversion.shape_pending_action(fixture("outreach_pending_action"))
        assert shaped["data_keys"] == ["has_pending_action", "hrs"]

    def test_a_non_list_where_a_list_was_measured_is_reported_not_iterated(self):
        """`hrs` as a dict is drift; it must not silently become rows."""
        payload = fixture("outreach_pending_action")
        payload["data"]["hrs"] = {"unexpected": True}

        shaped = conversion.shape_pending_action(payload)

        assert shaped["hrs_returned"] == 0
        assert shaped["hrs_was_a_list"] is False

    def test_a_swapped_pair_is_refused_not_reported(self):
        """Three shaped dicts of similar shape are easy to pass in the wrong order."""
        action = conversion.shape_pending_action(fixture("outreach_pending_action"))
        followups = conversion.shape_followups_pending(
            fixture("outreach_followups_pending")
        )
        external = conversion.shape_external_remaining(
            fixture("outreach_external_remaining")
        )

        with pytest.raises(OutreachError) as caught:
            conversion.agent_pending(
                pending_action=followups, followups=action, external=external
            )

        assert "not interchangeable" in str(caught.value)

    def test_a_raw_payload_where_a_shape_was_wanted_is_refused(self):
        with pytest.raises(OutreachError):
            conversion.agent_pending(
                pending_action=fixture("outreach_pending_action"),
                followups=conversion.shape_followups_pending(
                    fixture("outreach_followups_pending")
                ),
                external=conversion.shape_external_remaining(
                    fixture("outreach_external_remaining")
                ),
            )


# --------------------------------------------------------------------------
# The assembled reports.
# --------------------------------------------------------------------------


class TestTheAssembledReports:
    """What a caller actually sees."""

    async def test_agent_pending_reads_the_account_as_captured(self, monkeypatch):
        """MEASURED 2026-08-23: the follow-up flag reads TRUE."""
        wire(monkeypatch, by_route(BODIES))
        report = await server.uplers_agent_pending()

        assert report["blocked_on_you"] == ["missed_followups"]
        assert report["unknown"] == []
        assert report["anything_blocked"] is True
        assert report["missed_followups"]["pending"] is True
        assert report["missed_followups"]["days_echoed"] == 15
        assert report["agent_action"]["has_pending_action"] is False
        assert report["external_link_quota"]["remaining"] == 8
        assert report["reads_only"] is True

    async def test_reply_outcomes_says_whose_count_it_is(self, monkeypatch):
        """The 7-vs-8 gap must be visible, not reconciled away."""
        wire(monkeypatch, by_route(BODIES))
        result = await server.uplers_reply_outcomes()

        assert result["replies_on_this_route"] == 7
        assert "not the reply ledger" in strings_in(result["notes"])
        assert "get-outreach-agent-meta" in strings_in(result["notes"])

    def test_an_empty_response_list_is_an_answer_not_a_failure(self):
        """Rule 4's whole point, at the tool level."""
        payload = fixture("outreach_value_with_happy")
        payload["data"]["response"] = []

        shaped = conversion.shape_reply_outcomes(payload)

        assert shaped["replies_on_this_route"] == 0
        assert shaped["response_was_a_list"] is True
        assert "NO reply rows" in strings_in(shaped["headline"])

    def test_a_missing_response_list_is_drift_not_an_empty_result(self):
        payload = fixture("outreach_value_with_happy")
        del payload["data"]["response"]

        shaped = conversion.shape_reply_outcomes(payload)

        assert shaped["replies_on_this_route"] == 0
        assert shaped["response_was_a_list"] is False
        assert "drift" in strings_in(shaped["headline"])

    @pytest.mark.parametrize("bad", [0, -1, True, 1.5, "15", None])
    async def test_a_bad_window_is_refused_before_any_request(
        self, monkeypatch, bad
    ):
        """A window that is not a positive whole number never reaches the wire."""
        calls = wire(monkeypatch, by_route(BODIES))

        with pytest.raises(server.UplersError):
            await server.uplers_agent_pending(days=bad)

        assert calls == []


# --------------------------------------------------------------------------
# The route that was briefed and NOT built.
# --------------------------------------------------------------------------


class TestTheSalaryRouteStaysUnbuilt:
    """`get-company-salary-data` was stopped on measurement, and stays stopped.

    Recorded as a test rather than only as prose because the next session to
    read `EP_COMPANY_SALARY` will find a constant with a full shape write-up
    beside it, which reads exactly like an invitation. These assertions say
    plainly that nothing calls it and that the corrections are still on record.
    """

    def test_no_module_anywhere_names_the_salary_constant_in_code(self):
        """The constant exists; a CALLER does not. Asked of the SYNTAX TREE.

        BORROWED, NOT COPIED: `_modules_naming` is the same AST walker
        `test_agent_tools.py` uses to pin the consent constant to one module,
        and it is imported rather than reimplemented for the reason its own
        docstring gives - a drifted copy would leave one pin measuring
        something subtly different while both stayed green.

        AST rather than a substring search, and that is load-bearing HERE in
        particular: `EP_COMPANY_SALARY` is named in the PROSE of both
        `conversion.py` and `server.py`, which is exactly where it should be
        named - those comments are the record of why the tool was not built. A
        text search would report them as callers and force the explanation to
        be deleted to make the test pass.
        """
        from test_agent_tools import _modules_naming

        assert _modules_naming("EP_COMPANY_SALARY") == []

    def test_the_prose_that_explains_the_refusal_is_still_there__CONTROL(self):
        """__CONTROL for the pin above.

        `_modules_naming(...) == []` would also hold if every mention of this
        route had been deleted from the repository, which is the failure that
        would leave a future session with a bare constant and no reason. This
        proves the explanation survives in both modules while neither calls it.
        """
        import pathlib

        for module in (conversion, server):
            text = pathlib.Path(module.__file__).read_text(encoding="utf-8")
            assert "EP_COMPANY_SALARY" in text

    def test_the_three_corrections_are_recorded_on_the_constant(self):
        """Prose, but load-bearing prose: it is why the tool was not built."""
        import pathlib

        text = pathlib.Path(endpoints.__file__).read_text(encoding="utf-8")
        assert "THE REFUSAL IS NOT AN HTTP 400" in text
        assert "THE SUCCESS ENVELOPE HAS NO `data` KEY" in text
        assert "THE DATE-STRING ROWS ARE REFUSED" in text
