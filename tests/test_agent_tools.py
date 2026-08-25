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

IT GOT STRONGER AGAIN ON 2026-08-25. `uplers_server/consent_write.py` wired
the last two of those named routes: `consent-email-job-scan` (DELETE only) and
`interview-feedback`, which is ONE-WAY and has no undo anywhere in Uplers'
product. So the paragraph above no longer describes them as merely nearby - a
typo in this file can now reach a route that publishes a review that cannot be
retracted. The forbidden-route list below still names both, and still must:
these four tools may not touch them, whoever else may.

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


# --- static reachability, shared by the two route-constant pins -------------
#
# The two tests below ask the same question of two different constants: which
# modules NAME this route in code. Factored out rather than copied, because a
# copy that drifts would leave one of the two pins measuring something subtly
# different from the other while both stayed green.


def _package_root():
    import pathlib

    return pathlib.Path(server.__file__).resolve().parent


def _names_in_code(path):
    """Every identifier that appears in the SYNTAX TREE of one module.

    Names in strings and comments are deliberately NOT collected - see the
    docstring on the consent pin for why a substring match on this question is
    actively harmful.
    """
    import ast

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


def _modules_naming(constant):
    """Sorted names of the modules that reference `constant`, endpoints.py aside.

    endpoints.py is excluded because it DEFINES these constants; including it
    would make every pin read "endpoints.py plus whoever calls it" and bury the
    one name the pin is actually about.
    """
    root = _package_root()
    sources = [root / "server.py", *sorted((root / "uplers_server").glob("*.py"))]
    return sorted(
        path.name
        for path in sources
        if path.name != "endpoints.py" and constant in _names_in_code(path)
    )


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

    def test_the_consent_write_constant_is_reachable_only_from_its_wrapper(self):
        """EP_CONSENT_EMAIL_JOB_SCAN is named by server.py, and by NOTHING else.

        REWRITTEN 2026-08-25, and the rewrite is the point of the old version.
        This test used to assert that NOTHING referenced the constant at all,
        and its own docstring said that if wiring it was ever deliberate, the
        refusal in OUT_OF_SCOPE_BY_DESIGN had to be edited in the same commit.
        The route was wired that day, this test went red naming `server.py`,
        and the refusal was edited. A tripwire that fires and is then NARROWED
        rather than deleted is the whole reason it was worth having.

        WHAT IT PINS NOW IS STRICTLY STRONGER THAN A BARE "SOMETHING USES IT",
        and it is two claims rather than one:

        1.  `server.py` names it - the thin wrapper that builds the DELETE
            sender and hands it to the orchestrator. That is the doctrine
            `outreach_write` states: an orchestrator is HANDED a `send`
            callable and REFUSES without one, so "this route is reachable" is a
            fact about ONE wrapper rather than about a module that could grow a
            second caller quietly.
        2.  **`consent_write.py` does NOT name it.** This is the property
            `outreach_write` wishes it had and says so in its own docstring:
            its four settings routes serve the GET and the POST on the SAME
            path string, so the module that builds the bodies must also name
            the string a POST would use, and only the sender seam stays
            structural there. Here the read-back is a DIFFERENT route
            (`recommended-jobs-meta-email`), so the write path string has no
            business in the body-building module at all - and its absence is
            ASSERTED rather than left to hold by luck.

        Deliberately a static check and not a call: this is a DELETE that
        withdraws Uplers' permission to read a mailbox, and the one thing a
        test of it must never do is exercise it.

        IT PARSES THE AST RATHER THAN GREPPING, and that is not fastidiousness.
        The first version matched the substring and went red on its own
        documentation - the refusals in OUT_OF_SCOPE_BY_DESIGN and the comments
        in endpoints.py name the constant in prose in order to explain it. A
        test that fires on a sentence pushes the next maintainer to stop
        WRITING about the route so the suite stays green, which is exactly
        backwards. Names in the syntax tree are references; names in strings
        and comments are the documentation this repo is made of.
        """
        referencing = _modules_naming("EP_CONSENT_EMAIL_JOB_SCAN")
        assert referencing == ["server.py"], (
            "the consent-write constant must be referenced by server.py and by "
            "nothing else; these modules reference it in code: %s. server.py is "
            "the wrapper that builds the DELETE sender and hands it in, so a "
            "second referencing module means some other code path can reach a "
            "route that withdraws Uplers' permission to read his mailbox. If "
            "that was deliberate, the refusal in OUT_OF_SCOPE_BY_DESIGN and the "
            "comment on EP_CONSENT_EMAIL_JOB_SCAN both have to be edited in the "
            "same commit." % referencing
        )

        # The orchestrator does not name the write path. Asserted separately
        # from the list above so a failure says WHICH property broke: the list
        # growing to two names and the BODY-BUILDER being one of those two are
        # different mistakes with different fixes.
        assert "EP_CONSENT_EMAIL_JOB_SCAN" not in _names_in_code(
            _package_root() / "uplers_server" / "consent_write.py"
        ), (
            "consent_write.py names the consent route constant. It must not: "
            "its read-back is recommended-jobs-meta-email, a DIFFERENT route, "
            "so the write path string has no reason to exist in the module that "
            "builds the request. Only the sender - built in server.py and handed "
            "in - may carry it."
        )

        # The constant really is there to be found. Without this, both
        # assertions above would pass just as happily against a name nobody
        # ever defined.
        assert "EP_CONSENT_EMAIL_JOB_SCAN" in _names_in_code(
            _package_root() / "uplers_server" / "endpoints.py"
        )

    def test_the_one_way_feedback_constant_is_reachable_only_from_its_wrapper(self):
        """The same pin on EP_INTERVIEW_FEEDBACK, which is the ONE-WAY one.

        It gets its own test rather than a second loop inside the one above,
        because the two constants were refused - and then admitted - for
        different reasons, and one shared failure message could only ever state
        one of them.

        This route has NO edit route and NO delete route anywhere in Uplers'
        product. It is also the ONE deliberate exception to endpoints.py's rule
        that one-way routes are recorded as prose and never given a constant.
        "Exactly one module may name it, and that module is the thin wrapper"
        is the guard that buys the exception, so it is measured here rather
        than asserted in the comment that claims it.
        """
        referencing = _modules_naming("EP_INTERVIEW_FEEDBACK")
        assert referencing == ["server.py"], (
            "EP_INTERVIEW_FEEDBACK must be referenced by server.py and nothing "
            "else; these modules reference it in code: %s. This route is "
            "ONE-WAY - no edit route, no delete route, complete negative "
            "search - and it is the single exception to the rule in "
            "endpoints.py that one-way routes get no constant. A second caller "
            "retires the argument that bought the exception." % referencing
        )
        assert "EP_INTERVIEW_FEEDBACK" in _names_in_code(
            _package_root() / "uplers_server" / "endpoints.py"
        )

    def test_the_reachability_pin_can_actually_fail(self):
        """__CONTROL for both tests above, and it is not decoration.

        `_modules_naming` is an AST walk, and the failure mode that matters is
        it returning nothing - a walk that silently stops collecting turns both
        assertions above into `[] == ["server.py"]`, which at least goes red,
        but the SECOND assertion in each (`not in`) would pass for free forever.
        This proves the collector genuinely finds a name that is genuinely
        there, and genuinely does not find one that is not.
        """
        # A name every module in the package really does reference.
        assert "server.py" in _modules_naming("endpoints")
        # And one nothing does.
        assert _modules_naming("EP_NOT_A_REAL_CONSTANT_NAME") == []

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
