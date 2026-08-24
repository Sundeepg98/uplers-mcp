"""The four tools added on 2026-08-23, tested at the TOOL layer.

The pure shapers behind them are covered by test_outreach.py,
test_saved_filter.py, test_preference.py and test_assessment_flags.py. What
those files cannot see is the wiring: which route a tool actually calls, what
query string it actually builds, and - the one that matters here - whether it
is really read-only.

WHY THE READ-ONLY CENSUS IS THE FIRST TEST IN THIS FILE. Three of these four
tools live in or touch `talent/outreach/*`, which is the namespace of Uplers'
PAID outreach-agent product, and that namespace also contains
`interview-feedback`, `consent-email-job-scan` - a write that changes what
Uplers reads out of his mailbox - and `store-employee-requests`, which IS the
outreach send and which Uplers' own copy says cannot be undone. One route away
from every GET here is a POST that acts on his account. "It only reads" is
therefore a claim that has to be MEASURED against the requests that left, not
asserted from reading the code, because the code is one typo from being wrong
and the typo is not visible.

AND THAT ARGUMENT GOT STRONGER ON 2026-08-24, which is why this note is being
updated rather than left alone. `uplers_server/outreach_write.py` now exists
and sends real POSTs and a DELETE into this same namespace. Until then the
worst a typo here could do was call a route nobody had wired; now a wrong
import reaches a module built to write. The tools tested in this file must
still emit nothing but GETs, and that is measured below rather than trusted.

The same reasoning covers `uplers_apply`, which is why no test in this file
goes near it: on Uplers, expressing interest IS applying and there is no
withdraw anywhere in their product.

Every HTTP interaction goes through httpx.MockTransport. Nothing leaves the box.
"""

from __future__ import annotations

import json

import httpx
import pytest

import server
from uplers_server import endpoints
from uplers_server import outreach
from uplers_server import session as session_mod
from uplers_server import saved_filter
from uplers_server.saved_filter import SavedFilterRefused
from uplers_server.session import SessionStore
from uplers_server.talent import TalentClient

from conftest import make_transport

TOKEN = "42|bearer-token-that-must-never-be-printed"

#: The five outreach routes `uplers_agent_readthrough` reads, and the two
#: envelope idioms MEASURED across them: outreach-step answers with the STRING
#: "success", the other four with the INTEGER 200.
OUTREACH_BODIES = {
    endpoints.EP_OUTREACH_STEP: {
        "status": "success",
        "data": {
            "plan": 2,
            "auto_run": 1,
            "outreach_mode": "auto",
            "has_plan_expired": False,
            "plan_end_date": "2026-09-10",
            "credit_added": 0,
            "credit_left": 0,
            "credit_plan": 0,
            "all_over_status": True,
            "conversion_offer": None,
            "status": {
                "step1": True, "step2": True,
                "step_job_recommendation": True, "step_template": True,
            },
            "step1": {"gmail_connected": True, "linkedin_connected": False},
            "step2": {"gmail_template": True, "linkedin_template": False},
        },
    },
    endpoints.EP_OUTREACH_DASHBOARD: {
        "status": 200,
        "message": "ok",
        "data": {
            "total_jobs_run": 48, "total_positive_replies": 8,
            "total_unseen_replies": 7, "reminder_count": 7,
            "total_tailored_resumes": 0, "today_agent_runs": 0,
            "jobs_in_queue": 0, "max_limit": 8, "interview_count": 0,
            "pending_interview_feedback_count": 0,
            "consent_email_job_scan": True, "auto_run_consent": False,
            "agent_pref_fields_submitted": True,
            "has_submitted_happpy_feedback": False,
            "total_unseen_replies_count": 7,
        },
    },
    endpoints.EP_OUTREACH_PENDING: {"status": 200, "message": "ok", "data": []},
    endpoints.EP_OUTREACH_MISSED_FOLLOWUPS: {
        "status": 200,
        "message": "ok",
        "data": {
            "count": 1,
            "days": 15,
            "rows": [{
                "company_name": "Spark Eighteen",
                "job_title": "Fullstack Engineer",
                "employee_name": "Redacted Contact 1",
                "reply_category": "Willing to refer; requests updated resume",
                "reply_summary": "Redacted reply summary 1.",
                "replied_at": "2026-08-11T11:55:27+05:30",
                "thread_sent_at": "2026-08-11T10:30:39+05:30",
                "thread_subject": "need referral",
                "medium": "email",
                "medium_label": "Gmail",
                "gmail_thread_id": "rqyusjqy-nzllgg-2",
                "contact_value": "contact1@example.invalid",
                "employee_business_email": "contact1@example.invalid",
                "employee_linkedin_url": "https://www.linkedin.com/in/redacted-contact-1",
                "from_email": "operator1@example.invalid",
                "to_email": "contact1@example.invalid",
                "message_full": "Redacted reply body 1.",
            }],
        },
    },
    endpoints.EP_OUTREACH_ACTIVITY: {
        "status": 200,
        "message": "ok",
        "data": {
            "total": 1, "page": 1, "limit": 50,
            "filters": {"agent": "all", "status": "all"},
            "list": [{
                "HR_Number": "HR1", "company_name": "Oteemo",
                "job_title": "Full Stack Engineer", "status": 2,
                "status_string": "Completed", "used_agent": "Yes",
                "used_tailor": "No", "activity_date": "2026-08-21 11:41:24",
                "discard_reason": None, "apply_url": "https://example.invalid/j",
            }],
        },
    },
    # The sixth route, added 2026-08-24. It is the ONLY one that counts the
    # replies that said no, which is why the readthrough grew a request for it.
    # The positive total is deliberately the SAME number the dashboard body
    # above carries, because the report cross-checks the two against each other
    # and a fixture that made them differ would be testing a disagreement that
    # was never measured.
    endpoints.EP_OUTREACH_AGENT_META: {
        "status": 200,
        "message": "ok",
        "data": {"total_positive_replies": 8, "total_negative_replies": 2},
    },
}


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
    """Answer each request from `bodies`, keyed by route suffix."""

    def handler(request):
        for route, body in bodies.items():
            if request.url.path.endswith(route):
                return httpx.Response(200, json=body)
        if fallback is None:
            return httpx.Response(404, json={"message": "no stub for %s" % request.url.path})
        return httpx.Response(200, json=fallback)

    return handler


def writes(calls):
    """Every request that was not a read. The whole risk surface."""
    return [call for call in calls if call.method != "GET"]


# ==========================================================================
# The census. If only one test in this file survives, it should be this one.
# ==========================================================================


class TestNothingHereWrites:

    async def test_the_readthrough_only_ever_reads(self, monkeypatch):
        """Five requests, five GETs, five known routes, and nothing else.

        Asserted as an EXACT route list rather than "no writes", because the
        dangerous mistake in this namespace is not a POST - it is a GET to the
        wrong sibling. `consent-email-job-scan` and `interview-feedback` sit
        one path segment away and both change his account.
        """
        calls = wire(monkeypatch, by_route(OUTREACH_BODIES))

        await server.uplers_agent_readthrough()

        assert writes(calls) == []
        assert len(calls) == 6
        assert sorted(call.url.path.split("/api/")[-1] for call in calls) == sorted([
            endpoints.EP_OUTREACH_STEP,
            endpoints.EP_OUTREACH_DASHBOARD,
            endpoints.EP_OUTREACH_PENDING,
            endpoints.EP_OUTREACH_MISSED_FOLLOWUPS,
            endpoints.EP_OUTREACH_ACTIVITY,
            endpoints.EP_OUTREACH_AGENT_META,
        ])

    async def test_it_reports_the_replies_that_said_no(self, monkeypatch):
        """Every other reply counter in this report is a POSITIVE one.

        The dashboard counts positive and unseen; missed-positive-reply-followups
        returns the positive threads by name. So "8 positive replies came back"
        read as the whole of what came back, and it was not - two more people
        answered and said no. That changes the denominator, which is the
        difference between "8 replies" and "8 of 10".
        """
        wire(monkeypatch, by_route(OUTREACH_BODIES))

        report = await server.uplers_agent_readthrough()

        assert report["needs_reply"]["negative_replies"] == 2
        assert report["needs_reply"]["total_answered"] == 10
        assert report["needs_reply"]["positive_replies"] == 8
        # And the two routes that both count positives are held against each
        # other rather than assumed to share a source.
        check = next(
            item for item in report["cross_checks"]
            if item["claim"] == "positive replies"
        )
        assert check["agree"] is True

    async def test_an_unread_meta_route_reports_none_and_never_zero(self):
        """__CONTROL, and the distinction it guards is the whole point.

        `agent_meta` is optional, so a caller on the old five-request signature
        still works. What must never happen is that absence rendering as 0:
        "nobody said no" and "we did not ask" are opposite facts, and a zero
        would assert the first while meaning the second.
        """
        shaped = outreach.agent_readthrough(
            plan=outreach.shape_agent_plan(
                OUTREACH_BODIES[endpoints.EP_OUTREACH_STEP], today="2026-08-24"
            ),
            dashboard=outreach.shape_agent_dashboard(
                OUTREACH_BODIES[endpoints.EP_OUTREACH_DASHBOARD]
            ),
            pending=outreach.shape_pending_jobs(
                OUTREACH_BODIES[endpoints.EP_OUTREACH_PENDING]
            ),
            missed=outreach.shape_missed_followups(
                OUTREACH_BODIES[endpoints.EP_OUTREACH_MISSED_FOLLOWUPS],
                now="2026-08-24T00:00:00+05:30",
            ),
            activity=outreach.shape_activity(
                OUTREACH_BODIES[endpoints.EP_OUTREACH_ACTIVITY]
            ),
        )

        assert shaped["needs_reply"]["negative_replies"] is None
        assert shaped["needs_reply"]["total_answered"] is None
        assert not any(
            item["claim"] == "positive replies" for item in shaped["cross_checks"]
        )

    async def test_no_tool_added_today_reaches_a_write_route(self, monkeypatch):
        """All four together, against one transport, one census at the end."""
        bodies = dict(OUTREACH_BODIES)
        bodies[endpoints.EP_GET_PREFERENCE] = {"talent": {}, "masters": {}, "snooze": []}
        bodies[endpoints.EP_OPPORTUNITIES] = {
            "hrs": {"data": [{"ai_needed": False, "custom_screening_needed": False}],
                    "current_page": 1, "per_page": "20"},
            "bookmarkedCount": 0,
        }
        calls = wire(monkeypatch, by_route(bodies))

        await server.uplers_agent_readthrough()
        await server.uplers_platform_saved_jobs()
        await server.uplers_my_preferences()
        await server.uplers_assessment_gates()

        assert writes(calls) == []
        forbidden = ("consent-email-job-scan", "interview-feedback", "intrested",
                     "profile-upsert", "update-saved-hr", "cancel-opportunity")
        touched = [call.url.path for call in calls]
        for route in forbidden:
            assert not any(route in path for path in touched), (route, touched)

    def test_the_consent_write_constant_is_reachable_from_nothing(self):
        """EP_CONSENT_EMAIL_JOB_SCAN exists, and NOTHING may reference it.

        The constant predates the ruling that refuses the route - it is what
        explains an empty diary elsewhere - so unlike the ten one-way routes
        beside it, which are recorded in endpoints.py as prose precisely
        because a constant is an invitation to call it, this one is a name
        sitting in the codebase with no guard around it.

        `uplers_server_info` states that nothing reaches it. That sentence is
        either measured or it is decoration, and the runtime census above
        cannot measure it: that census watches the requests four specific tools
        emit, so it would stay green if a FIFTH tool wired the constant
        tomorrow. This reads the source instead, so the property holds for
        every module rather than for the four under test.

        Deliberately a static check and not a call: the route is a POST/DELETE
        that changes what Uplers reads out of his mailbox, and the one thing a
        test of it must never do is exercise it.

        IT PARSES THE AST RATHER THAN GREPPING, and that is not fastidiousness.
        The first version matched the substring and went red on its own
        documentation - the refusal in OUT_OF_SCOPE_BY_DESIGN names the
        constant in prose in order to explain why it is refused. A test that
        fires on a sentence pushes the next maintainer to stop WRITING about
        the refusal so the suite stays green, which is exactly backwards. Names
        in the syntax tree are references; names in strings and comments are
        the documentation this repo is made of.
        """
        import ast
        import pathlib

        root = pathlib.Path(server.__file__).resolve().parent
        sources = [root / "server.py", *sorted((root / "uplers_server").glob("*.py"))]

        def names_in_code(path):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            return {
                node.attr if isinstance(node, ast.Attribute) else node.id
                for node in ast.walk(tree)
                if isinstance(node, (ast.Attribute, ast.Name))
            } | {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }

        referencing = [
            path.name
            for path in sources
            if path.name != "endpoints.py"
            and "EP_CONSENT_EMAIL_JOB_SCAN" in names_in_code(path)
        ]
        assert referencing == [], (
            "these modules REFERENCE the consent-write constant in code: %s. "
            "The route is refused - it changes what Uplers reads out of his "
            "mailbox and that is his call. If wiring it was deliberate, the "
            "refusal in OUT_OF_SCOPE_BY_DESIGN has to be edited in the same "
            "commit." % referencing
        )

        # The constant really is there to be found. Without this the assertion
        # above would pass just as happily against a name nobody ever defined.
        assert "EP_CONSENT_EMAIL_JOB_SCAN" in names_in_code(
            root / "uplers_server" / "endpoints.py"
        )

    async def test_the_census_can_actually_fail(self, monkeypatch):
        """__CONTROL. `writes(calls) == []` is trivially true when no request
        was made at all, so a broken wiring would pass the census by being
        broken. This proves the transport records a write when one happens and
        that `writes` recognises it."""
        calls = wire(monkeypatch, by_route({}, fallback={"status": "success"}))

        async with server._talent_client() as client:
            await client.post_json(endpoints.EP_NOT_INTERESTED, {"hr_id": 1})

        assert len(writes(calls)) == 1
        assert writes(calls)[0].method == "POST"


# ==========================================================================
# uplers_agent_readthrough
# ==========================================================================


class TestAgentReadthrough:

    async def test_it_surfaces_the_unanswered_replies_and_the_dead_channel(
            self, monkeypatch):
        """The two findings the tool exists for, both reachable without
        digging: a positive reply nobody answered, and a paid two-channel
        agent running on one channel."""
        wire(monkeypatch, by_route(OUTREACH_BODIES))

        result = await server.uplers_agent_readthrough()

        assert result["needs_reply"]["positive_replies"] == 8
        assert result["needs_reply"]["unseen_replies"] == 7
        assert result["needs_reply"]["rows"][0]["company"] == "Spark Eighteen"
        assert result["channels"]["ready"] == ["gmail"]
        assert result["channels"]["not_ready"] == ["linkedin"]

    async def test_it_prints_no_counterparty_contact_route(self, monkeypatch):
        """Their email address and the body of their message stay out of the
        transcript. The category, company, role and thread id are what it
        takes to answer; the rest is somebody else's personal data being
        copied somewhere it does not need to be."""
        wire(monkeypatch, by_route(OUTREACH_BODIES))

        result = await server.uplers_agent_readthrough()

        blob = json.dumps(result)
        assert "contact1@example.invalid" not in blob
        assert "operator1@example.invalid" not in blob
        assert "linkedin.com/in/" not in blob
        assert "Redacted reply body" not in blob
        # ...while the fields that make it actionable DID come through.
        assert "Willing to refer" in blob
        assert "rqyusjqy-nzllgg-2" in blob

    async def test_the_contact_withholding_check_can_actually_fail(
            self, monkeypatch):
        """__CONTROL. The assertions above are `not in` checks, which pass
        happily against an empty result. This plants the same strings in a
        field the shaper DOES print and proves they would be seen."""
        bodies = dict(OUTREACH_BODIES)
        leaky = json.loads(json.dumps(bodies[endpoints.EP_OUTREACH_MISSED_FOLLOWUPS]))
        leaky["data"]["rows"][0]["company_name"] = "contact1@example.invalid"
        bodies[endpoints.EP_OUTREACH_MISSED_FOLLOWUPS] = leaky
        wire(monkeypatch, by_route(bodies))

        result = await server.uplers_agent_readthrough()

        assert "contact1@example.invalid" in json.dumps(result)

    async def test_the_plan_countdown_is_computed_not_omitted(self, monkeypatch):
        """The shapers take an injected clock so tests can pin them; the TOOL
        has to actually pass one. Without this, `days_remaining` silently
        stays None in production and nobody notices the subscription running
        out."""
        wire(monkeypatch, by_route(OUTREACH_BODIES))

        result = await server.uplers_agent_readthrough()

        assert result["plan"]["end_date"] == "2026-09-10"
        assert isinstance(result["plan"]["days_remaining"], int)


# ==========================================================================
# uplers_platform_saved_jobs
# ==========================================================================


class TestPlatformSavedJobs:

    async def test_the_flag_leaves_as_the_integer_one(self, monkeypatch):
        """Sent as `1`, never `true`. Uplers' branch is `1===t.is_saved_filter`,
        so a JSON boolean falls through to the ordinary filtered board and
        returns something that is not his saved list at all."""
        calls = wire(monkeypatch, by_route({endpoints.EP_OPPORTUNITIES: {
            "hrs": {"data": [], "current_page": 1, "per_page": "20"},
            "bookmarkedCount": 0,
        }}))

        await server.uplers_platform_saved_jobs()

        sent = dict(httpx.URL(str(calls[0].url)).params)
        assert sent["is_saved_filter"] == "1"
        assert sent["is_saved_filter"] != "true"

    async def test_an_ignored_filter_cannot_even_be_expressed(
            self, monkeypatch):
        """The failure mode guarded here is not an error - it is a WRONG
        ANSWER that looks right - so the refusal has to land before the wire.

        BE PRECISE ABOUT WHICH GUARD FIRES. At the tool boundary it is
        Python's own TypeError: `uplers_platform_saved_jobs` has no `roles`
        parameter, so the mistake cannot be expressed at all, which is a
        stronger refusal than a runtime check. `SavedFilterRefused` is the
        guard on the layer below, for a caller assembling params itself, and
        the second half of this test drives that path directly so both are
        proven rather than one standing in for the other.
        """
        calls = wire(monkeypatch, by_route({}))

        with pytest.raises(TypeError):
            await server.uplers_platform_saved_jobs(roles="123")   # type: ignore[call-arg]

        assert calls == []

        # The layer below, reached by anyone building params by hand.
        with pytest.raises(SavedFilterRefused):
            saved_filter.saved_jobs_params(roles=["123"])          # type: ignore[call-arg]
        assert saved_filter.rejected_filters({"roles": ["1"], "search": "x"}) == ["roles"]
        assert calls == []

    async def test_search_is_the_one_filter_that_rides_along(self, monkeypatch):
        """__CONTROL for the refusal above. A guard that refuses EVERYTHING is
        indistinguishable from a broken tool, so the allowed case is proven
        to still reach the wire."""
        calls = wire(monkeypatch, by_route({endpoints.EP_OPPORTUNITIES: {
            "hrs": {"data": [], "current_page": 1, "per_page": "20"},
            "bookmarkedCount": 0,
        }}))

        await server.uplers_platform_saved_jobs(search="node")

        assert len(calls) == 1
        assert dict(httpx.URL(str(calls[0].url)).params)["search"] == "node"

    async def test_an_empty_platform_list_is_an_answer_not_a_failure(
            self, monkeypatch):
        """MEASURED live on 2026-08-23: bookmarkedCount 0, zero rows. He has
        nothing saved on Uplers' side, and that has to read as a fact rather
        than as a tool that did not work."""
        wire(monkeypatch, by_route({endpoints.EP_OPPORTUNITIES: {
            "hrs": {"data": [], "current_page": 1, "per_page": "20"},
            "bookmarkedCount": 0, "search": "",
        }}))

        result = await server.uplers_platform_saved_jobs()

        assert result["jobs"] == []
        assert result["bookmarked_count"] == 0
        assert "no jobs saved" in result["summary"].lower()
        assert result["source"] == endpoints.EP_OPPORTUNITIES


# ==========================================================================
# uplers_my_preferences and uplers_assessment_gates
# ==========================================================================


class TestPreferencesAndGates:

    async def test_preferences_reads_get_preference_and_not_its_sibling(
            self, monkeypatch):
        """`user/job-search-preference` is a WRITE that changes how recruiters
        see him, and a prior slice already confused two constants in this
        area. The route is pinned by name for that reason."""
        calls = wire(monkeypatch, by_route({
            endpoints.EP_GET_PREFERENCE: {
                "talent": {"job_title": "Software Engineer"},
                "masters": {}, "snooze": [],
            },
        }))

        result = await server.uplers_my_preferences()

        assert len(calls) == 1
        assert calls[0].method == "GET"
        assert calls[0].url.path.endswith(endpoints.EP_GET_PREFERENCE)
        assert "nurture" not in calls[0].url.path
        assert result["source"] == endpoints.EP_GET_PREFERENCE

    async def test_gates_counts_the_flags_and_says_what_it_did_not_see(
            self, monkeypatch):
        """One page is one page. A summary that does not say so gets read as a
        statement about the whole 250-requisition board."""
        wire(monkeypatch, by_route({endpoints.EP_OPPORTUNITIES: {"hrs": {"data": [
            {"ai_needed": True, "custom_screening_needed": False},
            {"ai_needed": False, "custom_screening_needed": False},
            {},
        ], "current_page": 1}}}))

        result = await server.uplers_assessment_gates()

        assert result["rows"] == 3
        assert result["flags"]["ai_needed"]["true"] == 1
        assert result["flags"]["ai_needed"]["false"] == 1
        assert result["flags"]["ai_needed"]["unknown"] == 1     # absent, not false
        assert "one feed page of 3 row(s)" in result["scope"]

    async def test_gates_survives_a_payload_with_no_rows_at_all(
            self, monkeypatch):
        """__CONTROL for the extraction path. `payload["hrs"]["data"]` is three
        assumptions deep and every one of them can be absent; a KeyError here
        would be a tool that fails on an empty board rather than reporting
        one."""
        wire(monkeypatch, by_route({endpoints.EP_OPPORTUNITIES: {"message": "nothing"}}))

        result = await server.uplers_assessment_gates()

        assert result["rows"] == 0
        assert "one feed page of 0 row(s)" in result["scope"]
