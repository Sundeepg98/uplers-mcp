"""The paid-SKU reads, driven entirely by live-captured payloads.

Every input in this file is one of the three envelopes
`scripts/capture_skus.py` pulled off his live session into
`tests/fixtures/sku_*.json`, or a MUTATION of one of them (a key deleted, a
counter changed, a row's tailored id planted, a dropped key put back). Not one
payload here was written by hand, and that is deliberate: a payload invented by
the same head that wrote the reader agrees with the reader by construction and
proves nothing.

WHY THE READ-ONLY CENSUS IS THE FIRST CLASS IN THIS FILE, and why it is
stricter here than anywhere else in this suite. Two of the three routes live in
namespaces that also contain COMMERCE: `talent/tailor/order/create`,
`order/capture` and `refund-request` are path siblings of `talent/tailor/list`,
and `get-last-health-check` sits under `talent/outreach/*` one segment from
`consent-email-job-scan`. A typo in `uplers_server/skus.py` would not be a
failed read, it would be a charge against his account or a change to what
Uplers reads out of his mailbox. "It only reads" is therefore a claim that has
to be MEASURED against the requests that actually left, because the code is one
character from being wrong and the character is not visible.

CONTROLS. Every guard here is SHOWN FAILING, because a check that cannot fail
certifies nothing. Each was run red before it was run green, with the shaper
temporarily broken in the way the control exists to catch:

    test_an_absent_score_is_none_and_never_zero__CONTROL
        The absent-vs-zero control for uplers_resume_health. Deletes
        `resume_score` from the captured payload and proves it renders None.
        Watched failing with the shaper reading `_int(...) or 0`:
        `assert 0 is None`.

    test_an_absent_plan_flag_is_none_and_never_false__CONTROL
        The absent-vs-zero control for uplers_tailored_resumes. Deletes
        `plan_active` and `remaining_days` and proves both render None rather
        than False and 0. Watched failing with `_flag(...) or False` and
        `_int(...) or 0`: `assert False is None`.

    test_the_census_can_actually_fail__CONTROL
        `writes(calls) == []` is trivially true when no request was made at
        all, so a broken wiring would pass the census by being broken.

    test_a_planted_tailored_row_is_counted__CONTROL
        The capture has ZERO tailored rows, so every assertion about tailored
        counting would pass against a shaper that hard-coded 0. This plants a
        `tailored_resume_id` on the real row and proves the count follows.

    test_a_planted_google_doc_url_is_seen_but_never_returned__CONTROL
        `google_doc_urls` is dropped at capture time, so the fixture cannot
        prove the withholding works - a sweep run only against it would pass by
        having nothing to find. This puts a URL back and proves the shaper
        notices the artifact exists and still never prints the link.

    test_narrowing_to_the_string_arm_refuses_all_three__CONTROL
        Narrows `outreach.SUCCESS_VALUES` to the string arm and proves all
        three real fixtures stop reading. Proves the integer idiom is genuinely
        checked and is not a truthiness test waving anything through.

    test_a_disagreeing_pair_of_routes_really_reports_a_disagreement__CONTROL
        The two captured routes AGREE, so the cross-check would look correct
        while being printed unconditionally. This changes one counter and
        proves the disagreement is computed.
"""

from __future__ import annotations

import copy
import json

import httpx
import pytest

import server
from uplers_server import endpoints, outreach, skus
from uplers_server.outreach import OutreachError
from uplers_server import session as session_mod
from uplers_server.session import SessionStore
from uplers_server.talent import TalentClient

from conftest import load_talent_fixture, make_transport

TOKEN = "42|bearer-token-that-must-never-be-printed"

#: fixture stem -> route. The three captured 2026-08-25. Kept as ONE mapping so
#: the transport, the envelope sweep and the census all read the same list and
#: a fourth route cannot be added to one of them alone.
FIXTURES = {
    "sku_health_check_last": endpoints.EP_SKU_HEALTH_CHECK_LAST,
    "sku_health_check_dashboard": endpoints.EP_SKU_HEALTH_CHECK_DASHBOARD,
    "sku_tailor_list": endpoints.EP_SKU_TAILOR_LIST,
}

BODIES = {route: load_talent_fixture(stem) for stem, route in FIXTURES.items()}

#: THE ROUTES THAT MUST NEVER BE TOUCHED. Path siblings of the three above,
#: every one of which spends money or an attempt. Named here so the census can
#: assert their ABSENCE by name rather than only asserting "no writes" - a GET
#: at `talent/tailor/order/create` would pass a method check.
FORBIDDEN_SIBLINGS = (
    "talent/tailor/order/create",
    "talent/tailor/order/capture",
    "talent/tailor/refund-request",
    "talent/outreach/consent-email-job-scan",
    "talent/outreach/consent-auto-run",
)


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
    `talent/tailor/list` is a prefix-neighbour of `talent/tailor/order/create`,
    so a loose match is exactly the near-miss this file exists to refuse.
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
# The census. First, because it is the thing that must not be wrong.
# --------------------------------------------------------------------------


class TestNeitherToolCanReachACommercialRoute:
    """MEASURED against the requests that left, not asserted from the source."""

    async def test_resume_health_issues_exactly_two_gets(self, monkeypatch):
        calls = wire(monkeypatch, by_route(BODIES))
        await server.uplers_resume_health()

        assert writes(calls) == []
        assert routes_of(calls) == [
            endpoints.EP_SKU_HEALTH_CHECK_LAST,
            endpoints.EP_SKU_HEALTH_CHECK_DASHBOARD,
        ]

    async def test_tailored_resumes_issues_exactly_one_get(self, monkeypatch):
        calls = wire(monkeypatch, by_route(BODIES))
        await server.uplers_tailored_resumes()

        assert writes(calls) == []
        assert routes_of(calls) == [endpoints.EP_SKU_TAILOR_LIST]

    async def test_no_commercial_sibling_is_ever_requested(self, monkeypatch):
        """An EXACT route list, not merely 'no writes'.

        A GET at `talent/tailor/order/create` would pass a method check and
        still be a request at an ordering route, so the absence is asserted by
        name.
        """
        calls = wire(monkeypatch, by_route(BODIES))
        await server.uplers_resume_health()
        await server.uplers_tailored_resumes()

        seen = routes_of(calls)
        for forbidden in FORBIDDEN_SIBLINGS:
            assert forbidden not in seen

    def test_the_forbidden_siblings_have_no_constant(self):
        """None of them may be a NAME in endpoints.py either.

        The same rule endpoints.py already applies to the one-way outreach
        routes: a constant is an invitation to call it. `consent-email-job-scan`
        is the stated exception that predates this and has its own guard in
        test_agent_tools.py, so only the three commercial ones are checked.
        """
        values = {
            value
            for name, value in vars(endpoints).items()
            if name.startswith("EP_") and isinstance(value, str)
        }
        for forbidden in FORBIDDEN_SIBLINGS[:3]:
            assert forbidden not in values

    async def test_the_census_can_actually_fail__CONTROL(self, monkeypatch):
        """`writes(calls) == []` is trivially true when nothing was requested.

        Proves the transport records a write when one happens and that
        `writes` recognises it, so the three assertions above are measuring
        something.
        """
        calls = wire(monkeypatch, by_route({}, fallback={"status": 200, "data": {}}))
        client = server.TalentClient(lambda: TOKEN)
        async with client:
            await client.post_json("talent/tailor/order/create", {"x": 1})

        assert len(writes(calls)) == 1
        assert routes_of(calls) == ["talent/tailor/order/create"]


# --------------------------------------------------------------------------
# Absent is not zero. The controls the brief for this slice named.
# --------------------------------------------------------------------------


class TestAbsentIsNotZeroAndIsNotFalse:
    """"He scored 0" and "we did not get a score" are opposite facts."""

    def test_the_captured_score_reads_89(self):
        """The baseline the controls below mutate away from."""
        shaped = skus.shape_last_health_check(fixture("sku_health_check_last"))
        assert shaped["last_check"]["resume_score"] == 89

    def test_an_absent_score_is_none_and_never_zero__CONTROL(self):
        """__CONTROL. Deletes `resume_score` and proves it renders None.

        WATCHED FAILING. With `shape_last_health_check` reading
        `_int(check.get("resume_score")) or 0` this test went red on
        `assert 0 is None`, and `test_the_captured_score_reads_89` above stayed
        green - which is the point: the happy path cannot see this defect,
        because 89 survives `or 0` unchanged. Only the absent case can.
        """
        payload = fixture("sku_health_check_last")
        del payload["data"]["health_check"]["resume_score"]

        shaped = skus.shape_last_health_check(payload)

        assert shaped["last_check"]["resume_score"] is None
        assert shaped["last_check"]["resume_score"] is not False
        # And an absent score must not become a headline claiming a score.
        report = skus.resume_health(
            last=shaped,
            dashboard=skus.shape_health_check_dashboard(
                fixture("sku_health_check_dashboard")
            ),
        )
        assert not any("scored" in line for line in report["headline"])

    def test_an_absent_plan_flag_is_none_and_never_false__CONTROL(self):
        """__CONTROL. The same proof for the tailor tool's plan state.

        WATCHED FAILING. With `shape_tailor_list` reading
        `_flag(plan_raw.get("plan_active")) or False` and
        `_int(plan_raw.get("remaining_days")) or 0` this went red on
        `assert False is None`. Both defects are invisible on the captured
        payload, where the real values are 0 and 0 and therefore render
        identically either way - which is exactly why the control deletes them.
        """
        payload = fixture("sku_tailor_list")
        del payload["data"]["plan_details"]["plan_active"]
        del payload["data"]["plan_details"]["remaining_days"]

        shaped = skus.shape_tailor_list(payload)

        assert shaped["plan"]["active"] is None
        assert shaped["plan"]["remaining_days"] is None
        # "the payload did not say" must not print as "the plan is inactive".
        assert not any("INACTIVE" in line for line in shaped["headline"])
        # An unknown cannot agree with anything.
        agreement = shaped["plan_over_agreement"]
        assert sorted(agreement["unknown"]) == ["no_days_remaining", "plan_inactive"]

    def test_an_absent_attempt_counter_leaves_the_difference_unknown(self):
        """A missing counter makes the subtraction unknowable, never zero."""
        payload = fixture("sku_health_check_last")
        del payload["data"]["total_attempts"]

        shaped = skus.shape_last_health_check(payload)

        assert shaped["attempts"]["total"] is None
        assert shaped["attempts"]["unspent_by_arithmetic"] is None
        assert shaped["attempts"]["used"] == 3

    def test_a_zero_score_is_reported_as_zero_not_as_absent(self):
        """The other half of the same distinction, and the one a `or 0` fix
        would break in the opposite direction. A real 0 must survive."""
        payload = fixture("sku_health_check_last")
        payload["data"]["health_check"]["resume_score"] = 0

        shaped = skus.shape_last_health_check(payload)

        assert shaped["last_check"]["resume_score"] == 0
        assert shaped["last_check"]["resume_score"] is not None


# --------------------------------------------------------------------------
# The verdict, which needed a third state.
# --------------------------------------------------------------------------


class TestTheEmptyVerdictIsDistinguishedFromAMissingOne:
    """MEASURED: `final_verdict` is present and EMPTY on all four rows."""

    def test_the_captured_verdict_is_present_and_empty(self):
        shaped = skus.shape_last_health_check(fixture("sku_health_check_last"))
        assert shaped["last_check"]["final_verdict"] is None
        assert shaped["last_check"]["final_verdict_state"] == "empty"

    def test_every_captured_history_row_says_the_same(self):
        shaped = skus.shape_health_check_dashboard(
            fixture("sku_health_check_dashboard")
        )
        assert [row["final_verdict_state"] for row in shaped["rows"]] == [
            "empty",
            "empty",
            "empty",
        ]

    def test_a_deleted_verdict_key_reads_absent_not_empty__CONTROL(self):
        """__CONTROL. Without this, `verdict_state` could return "empty"
        unconditionally and every assertion above would still pass."""
        payload = fixture("sku_health_check_last")
        del payload["data"]["health_check"]["final_verdict"]

        shaped = skus.shape_last_health_check(payload)

        assert shaped["last_check"]["final_verdict_state"] == "absent"

    def test_a_real_verdict_reads_present(self):
        payload = fixture("sku_health_check_last")
        payload["data"]["health_check"]["final_verdict"] = "Needs work"

        shaped = skus.shape_last_health_check(payload)

        assert shaped["last_check"]["final_verdict"] == "Needs work"
        assert shaped["last_check"]["final_verdict_state"] == "present"


# --------------------------------------------------------------------------
# The two counts on the tailor route, which is where a reader gets it wrong.
# --------------------------------------------------------------------------


class TestTheRowCountIsNotTheTailoredCount:
    """MEASURED: `total_records` 1, `total_tailored_resumes` 0, one SOURCE row."""

    def test_the_captured_account_has_no_tailored_resume(self):
        shaped = skus.shape_tailor_list(fixture("sku_tailor_list"))

        assert shaped["tailored_resumes_reported"] == 0
        assert shaped["rows_reported"] == 1
        assert shaped["rows_returned"] == 1
        assert shaped["tailored_rows_returned"] == 0
        assert shaped["rows"][0]["is_tailored"] is False
        assert shaped["rows"][0]["list_type"] == "source"

    def test_a_planted_tailored_row_is_counted__CONTROL(self):
        """__CONTROL. The capture has ZERO tailored rows, so every assertion
        above would pass against a shaper that hard-coded 0. This plants a
        `tailored_resume_id` on the REAL row and proves the count follows the
        payload."""
        payload = fixture("sku_tailor_list")
        payload["data"]["resumes_list"][0]["tailored_resume_id"] = 4242
        payload["data"]["resumes_list"][0]["hr_number"] = "HR-99999"

        shaped = skus.shape_tailor_list(payload)

        assert shaped["tailored_rows_returned"] == 1
        assert shaped["rows"][0]["is_tailored"] is True
        assert shaped["rows"][0]["tailored_for_hr_number"] == "HR-99999"
        # And the "no tailored resume exists" headline must retract itself.
        assert not any("NO tailored resume" in line for line in shaped["headline"])

    def test_the_row_count_is_never_read_as_the_tailored_count(self):
        """The trap, stated as an assertion: 1 row, 0 tailored, and the tool
        says so in a headline rather than leaving the reader to notice."""
        shaped = skus.shape_tailor_list(fixture("sku_tailor_list"))
        assert any("row count is not the tailored count" in line
                   for line in shaped["headline"])


# --------------------------------------------------------------------------
# Personal data. The rule this slice was given.
# --------------------------------------------------------------------------


class TestNoPersonalArtifactAddressIsEverReturned:
    """Existence and metadata, never a body and never a link."""

    async def test_neither_tool_returns_a_withheld_key(self, monkeypatch):
        calls = wire(monkeypatch, by_route(BODIES))
        health = await server.uplers_resume_health()
        tailor = await server.uplers_tailored_resumes()
        assert calls  # the tools really ran

        for result in (health, tailor):
            rendered = strings_in(result)
            for key in skus.WITHHELD_KEYS:
                assert '"%s":' % key not in rendered

    def test_the_shaper_says_what_it_withheld_rather_than_dropping_silently(self):
        shaped = skus.shape_last_health_check(fixture("sku_health_check_last"))
        assert "report_details" in shaped["withheld"]
        assert "aws_file_name" in shaped["withheld"]
        assert "google_doc_urls" in shaped["withheld"]
        assert shaped["last_check"]["report_body_withheld"] is True

    def test_a_planted_google_doc_url_is_seen_but_never_returned__CONTROL(self):
        """__CONTROL. `google_doc_urls` is dropped at CAPTURE time, so the
        fixture cannot prove the withholding works - a sweep run only against
        it would pass by having nothing to find. This puts a link back on the
        payload, the way the live route sends it, and proves two things at
        once: the shaper NOTICES the artifact exists, and the link itself never
        appears in the output."""
        payload = fixture("sku_health_check_last")
        payload["data"]["transform"]["google_doc_urls"] = [
            "https://docs.google.com/document/d/PLANTED-DOC-ID/edit"
        ]

        shaped = skus.shape_last_health_check(payload)

        assert shaped["transform"]["google_docs_state"] == "withheld_present"
        assert "PLANTED-DOC-ID" not in strings_in(shaped)
        assert "docs.google.com" not in strings_in(shaped)

    def test_a_planted_filename_never_reaches_the_output__CONTROL(self):
        """__CONTROL. Same argument for the filenames, which the capture also
        deletes. Puts one back under every key the live routes use."""
        payload = fixture("sku_health_check_last")
        payload["data"]["health_check"]["file_name"] = "PLANTED_Resume_v9.pdf"
        payload["data"]["health_check"]["aws_file_name"] = "PLANTED-aws-object-name"

        shaped = skus.shape_last_health_check(payload)

        assert "PLANTED" not in strings_in(shaped)

    def test_a_planted_report_body_never_reaches_the_output__CONTROL(self):
        """__CONTROL. The most dangerous node: Uplers' scoring report quotes
        his resume back verbatim. The capture drops it, so this puts a
        recognisable body back and proves the shaper does not walk into it."""
        payload = fixture("sku_health_check_last")
        payload["data"]["health_check"]["report_details"] = {
            "candidate_name": "PLANTED PERSON",
            "sections": {"content": {"quantify_impact": {
                "message": "PLANTED verbatim resume bullet naming an employer.",
            }}},
        }

        shaped = skus.shape_last_health_check(payload)

        assert "PLANTED" not in strings_in(shaped)

    def test_a_planted_base_resume_name_never_reaches_the_tailor_output__CONTROL(self):
        payload = fixture("sku_tailor_list")
        payload["data"]["resumes_list"][0]["base_resume"] = "PLANTED_Base.pdf"
        payload["data"]["resumes_list"][0]["base_resume_text"] = "PLANTED text name"

        shaped = skus.shape_tailor_list(payload)

        assert "PLANTED" not in strings_in(shaped)
        assert shaped["rows"][0]["file_name_withheld"] is True

    def test_the_committed_fixtures_carry_none_of_those_keys(self):
        """The capture-side half. If `SKU_DROP` regressed, this fires."""
        for stem in FIXTURES:
            rendered = strings_in(load_talent_fixture(stem))
            for key in skus.WITHHELD_KEYS:
                assert '"%s"' % key not in rendered, (stem, key)


# --------------------------------------------------------------------------
# The envelope, and the cross-checks between the two health routes.
# --------------------------------------------------------------------------


class TestTheEnvelopeIsCheckedRatherThanAssumed:

    def test_all_three_captured_routes_answer_the_integer_200(self):
        for stem in FIXTURES:
            assert load_talent_fixture(stem)["status"] == 200

    def test_narrowing_to_the_string_arm_refuses_all_three__CONTROL(
        self, monkeypatch
    ):
        """__CONTROL. Narrow `SUCCESS_VALUES` to the string arm and every real
        fixture here must stop reading. Proves the integer idiom is genuinely
        checked and is not a truthiness test waving anything through."""
        monkeypatch.setattr(outreach, "SUCCESS_VALUES", frozenset({"success"}))

        with pytest.raises(OutreachError):
            skus.shape_last_health_check(fixture("sku_health_check_last"))
        with pytest.raises(OutreachError):
            skus.shape_health_check_dashboard(fixture("sku_health_check_dashboard"))
        with pytest.raises(OutreachError):
            skus.shape_tailor_list(fixture("sku_tailor_list"))

    def test_a_missing_data_node_is_refused_not_read_as_empty(self):
        payload = fixture("sku_tailor_list")
        del payload["data"]
        with pytest.raises(OutreachError):
            skus.shape_tailor_list(payload)

    def test_a_swapped_pair_of_shapes_is_refused(self):
        """`resume_health` takes two shaped dicts that both describe health
        checks and both carry scores. A swap must raise, not render."""
        last = skus.shape_last_health_check(fixture("sku_health_check_last"))
        dashboard = skus.shape_health_check_dashboard(
            fixture("sku_health_check_dashboard")
        )
        with pytest.raises(OutreachError):
            skus.resume_health(last=dashboard, dashboard=last)


class TestTheTwoHealthRoutesCrossCheckEachOther:
    """The reason one tool reads both."""

    def test_the_captured_routes_agree_that_three_checks_were_spent(self):
        report = skus.resume_health(
            last=skus.shape_last_health_check(fixture("sku_health_check_last")),
            dashboard=skus.shape_health_check_dashboard(
                fixture("sku_health_check_dashboard")
            ),
        )
        agreement = report["spent_agreement"]

        assert agreement["agree"] is True
        assert agreement["values"] == {
            "history_rows_returned": 3,
            "total_resume_health_check": 3,
            "user_attempts": 3,
        }

    def test_a_disagreeing_pair_of_routes_really_reports_a_disagreement__CONTROL(
        self,
    ):
        """__CONTROL. The two captured routes AGREE, so the cross-check would
        look correct while being printed unconditionally. This changes one
        counter on the real payload and proves the verdict is computed."""
        dashboard_payload = fixture("sku_health_check_dashboard")
        dashboard_payload["data"]["total_resume_health_check"] = 9

        report = skus.resume_health(
            last=skus.shape_last_health_check(fixture("sku_health_check_last")),
            dashboard=skus.shape_health_check_dashboard(dashboard_payload),
        )

        assert report["spent_agreement"]["agree"] is False
        assert any("DISAGREE" in line for line in report["headline"])

    def test_the_eligibility_contradiction_is_printed_not_resolved(self):
        """MEASURED: 2 attempts unspent by arithmetic AND is_eligible false.
        Both must appear; neither may be dropped in favour of the other."""
        report = skus.resume_health(
            last=skus.shape_last_health_check(fixture("sku_health_check_last")),
            dashboard=skus.shape_health_check_dashboard(
                fixture("sku_health_check_dashboard")
            ),
        )

        assert report["current"]["attempts"]["unspent_by_arithmetic"] == 2
        assert report["current"]["attempts"]["eligible_now"] is False
        assert any("is_eligible reads FALSE" in line for line in report["headline"])
        assert any("DISAGREEMENT" in note for note in report["current"]["notes"])

    def test_an_eligible_account_emits_no_contradiction_note__CONTROL(self):
        """__CONTROL. Proves the contradiction note is computed from the
        payload rather than printed unconditionally."""
        payload = fixture("sku_health_check_last")
        payload["data"]["is_eligible"] = True

        shaped = skus.shape_last_health_check(payload)

        assert not any("DISAGREEMENT" in note for note in shaped["notes"])
        assert shaped["attempts"]["eligible_now"] is True


# --------------------------------------------------------------------------
# End to end, through the real tools.
# --------------------------------------------------------------------------


class TestTheToolsReturnTheMeasuredAccount:

    async def test_resume_health_reports_the_score_and_the_history(
        self, monkeypatch
    ):
        wire(monkeypatch, by_route(BODIES))
        result = await server.uplers_resume_health()

        assert result["reads_only"] is True
        assert result["current"]["last_check"]["resume_score"] == 89
        assert result["history"]["rows_returned"] == 3
        assert result["history"]["score_range"] == {
            "lowest": 87,
            "highest": 89,
            "scored_rows": 3,
        }
        assert result["history"]["transforms_reported"] == 0
        assert result["unsurfaced"]  # the cost is stated, not hidden

    async def test_tailored_resumes_reports_no_tailored_resume_and_a_dead_plan(
        self, monkeypatch
    ):
        wire(monkeypatch, by_route(BODIES))
        result = await server.uplers_tailored_resumes()

        assert result["reads_only"] is True
        assert result["tailored_resumes_reported"] == 0
        assert result["tailored_rows_returned"] == 0
        assert result["plan"]["active"] is False
        assert result["plan"]["remaining_days"] == 0
        assert result["plan"]["has_transaction"] is False
        assert result["plan_over_agreement"]["agree"] is True

    async def test_neither_tool_prints_the_bearer_token(self, monkeypatch):
        wire(monkeypatch, by_route(BODIES))
        health = await server.uplers_resume_health()
        tailor = await server.uplers_tailored_resumes()

        for result in (health, tailor):
            assert TOKEN not in strings_in(result)
            assert "bearer-token" not in strings_in(result)
