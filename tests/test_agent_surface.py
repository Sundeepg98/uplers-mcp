"""The agent-surface reads, driven entirely by live-captured payloads.

Every input in this file is one of the six envelopes
`scripts/capture_agent_surface.py` pulled off his live session into
`tests/fixtures/outreach_*.json`, or a MUTATION of one of them (a key deleted,
a flag flipped, a body unmasked, a score planted). Not one payload here was
written by hand, and that is deliberate: a payload invented by the same head
that wrote the reader agrees with the reader by construction and proves
nothing.

WHY THE READ-ONLY CENSUS IS THE FIRST CLASS IN THIS FILE. All six routes live
under `talent/outreach/*`, the namespace of Uplers' PAID outreach-agent
product, and one path segment from every GET here sits `consent-email-job-scan`
- a POST that grants and a DELETE that revokes what Uplers reads out of his
mailbox. "It only reads" is a claim that has to be MEASURED against the
requests that actually left, because the code is one typo from being wrong and
the typo is not visible.

Two of those siblings are traps of a second kind, and the census names both:
`settings/companies` is an alphabetical company PICKER that looks like the
blocklist, and `recommended-jobs-email` differs from `recommended-jobs-meta-email`
by one path segment. Neither is a write, and reading either in the other's
place would report confident nonsense. So the census asserts EXACT route lists,
not merely "no writes".

CONTROLS. Every guard here is SHOWN FAILING, because a check that cannot fail
certifies nothing:

    test_the_census_can_actually_fail
        Proves the transport records a write when one happens and that
        `writes()` recognises it - `writes(calls) == []` is trivially true when
        no request was made at all.

    test_the_no_score_sweep_can_actually_fire
        Plants a `fit_score` on one captured row and proves the sweep that
        guards the no-scoring promise catches it. Without this the sweep might
        be looking at the wrong nodes and passing for that reason.

    test_the_body_sweep_can_actually_fire
        Puts a distinctive template body back into the payload and proves the
        leak sweep catches it. The fixture MASKS the real body, so a sweep run
        only against the fixture could pass by having nothing to find.

    test_narrowing_to_the_integer_arm_refuses_the_templates_route
    test_narrowing_to_the_string_arm_refuses_the_other_five
        Narrow `outreach.SUCCESS_VALUES` to one arm and the OTHER arm's real
        fixtures stop reading. Proves each arm is genuinely checked and that
        the check is not a truthiness test waving both through.

    test_a_disabled_channel_really_reads_as_disabled
        Flips `disabled_followup_gmail` to true on the captured payload and
        proves `enabled` follows it. The capture has BOTH channels enabled, so
        a shaper that hard-coded `True` would pass every unmutated assertion.

    test_a_payload_whose_counters_agree_emits_no_disagreement
        Proves the disagreement is computed from the payload rather than
        printed unconditionally.

    test_the_dashboard_spelling_is_not_read_as_a_grant_time
        Feeds the OTHER route's boolean spelling of `consent_email_job_scan`
        and proves the grant time comes back unknown-with-a-note rather than
        as a fabricated date.
"""

from __future__ import annotations

import copy
import json

import httpx
import pytest

import server
from uplers_server import agent_surface, endpoints, outreach
from uplers_server.agent_surface import AgentSurfaceRefused
from uplers_server.outreach import OutreachError
from uplers_server import session as session_mod
from uplers_server.session import SessionStore
from uplers_server.talent import TalentClient

from conftest import load_talent_fixture, make_transport

TOKEN = "42|bearer-token-that-must-never-be-printed"

#: fixture stem -> route. The six captured 2026-08-23. Kept as one mapping so
#: the transport, the envelope sweep and the census all read the same list and
#: a seventh route cannot be added to one of them alone.
FIXTURES = {
    "outreach_meta_email": endpoints.EP_OUTREACH_META_EMAIL,
    "outreach_scanned_jobs": endpoints.EP_OUTREACH_SCANNED_JOBS,
    "outreach_settings_followup": endpoints.EP_OUTREACH_SETTINGS_FOLLOWUP,
    "outreach_disabled_companies": endpoints.EP_OUTREACH_DISABLED_COMPANIES,
    "outreach_auto_reply": endpoints.EP_OUTREACH_AUTO_REPLY,
    "outreach_templates": endpoints.EP_OUTREACH_TEMPLATES,
}

BODIES = {route: load_talent_fixture(stem) for stem, route in FIXTURES.items()}

#: A key carrying one of these words, with a NUMBER for a value, is a fit score
#: by another name. The scanned-job rows must never carry one.
SCORE_WORDS = ("score", "fit", "rank", "rating", "match", "grade", "percentile")

#: Exactly the keys a scanned-job row may carry. An exact set rather than a
#: subset check: this is the assertion that fires if anybody ever adds a
#: scored field to these rows, whatever they choose to call it.
ROW_KEYS = {
    "title",
    "company",
    "apply_url",
    "job_board",
    "publish_datetime",
    "best_for_you",
}


def fixture(stem: str) -> dict:
    """A deep copy of one captured envelope, safe to mutate."""
    return copy.deepcopy(load_talent_fixture(stem))


def numeric_score_fields(node, trail="$") -> list:
    """Every (path, value) where a score-ish KEY carries a NUMBER.

    Booleans are excluded deliberately: `scored: False` is the module DECLARING
    that it did not score, which is the opposite of the thing being hunted. A
    number is the danger, because a number prints identically whether or not
    anything is behind it.
    """
    hits = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = "%s.%s" % (trail, key)
            if (
                any(word in str(key).lower() for word in SCORE_WORDS)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                hits.append((path, value))
            hits.extend(numeric_score_fields(value, path))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            hits.extend(numeric_score_fields(item, "%s[%d]" % (trail, index)))
    return hits


def find_text(node, needle: str) -> bool:
    """True if `needle` appears in any string anywhere in the structure."""
    return needle in json.dumps(node, default=str)


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

    Exact rather than `endswith`, because two of these routes differ by one
    path segment (`recommended-jobs-email` and `recommended-jobs-meta-email`)
    and a suffix match is the kind of near-miss this whole file exists to
    refuse.
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


# ==========================================================================
# The census. If only one test in this file survives, it should be this one.
# ==========================================================================


class TestNothingHereWrites:

    async def test_email_scan_reads_one_route_and_it_is_the_meta_one(
        self, monkeypatch
    ):
        calls = wire(monkeypatch, by_route(BODIES))

        await server.uplers_email_scan()

        assert writes(calls) == []
        assert routes_of(calls) == [endpoints.EP_OUTREACH_META_EMAIL]

    async def test_scanned_jobs_reads_one_route_and_it_is_the_list_one(
        self, monkeypatch
    ):
        calls = wire(monkeypatch, by_route(BODIES))

        await server.uplers_scanned_jobs()

        assert writes(calls) == []
        assert routes_of(calls) == [endpoints.EP_OUTREACH_SCANNED_JOBS]
        # And NOT its one-segment-away neighbour, which is a different tool's
        # route and a different answer.
        assert endpoints.EP_OUTREACH_META_EMAIL not in routes_of(calls)

    async def test_agent_settings_reads_exactly_its_four_routes(self, monkeypatch):
        calls = wire(monkeypatch, by_route(BODIES))

        await server.uplers_agent_settings()

        assert writes(calls) == []
        assert sorted(routes_of(calls)) == sorted(
            [
                endpoints.EP_OUTREACH_SETTINGS_FOLLOWUP,
                endpoints.EP_OUTREACH_DISABLED_COMPANIES,
                endpoints.EP_OUTREACH_AUTO_REPLY,
                endpoints.EP_OUTREACH_TEMPLATES,
            ]
        )

    async def test_no_tool_here_reaches_a_write_or_a_lookalike(self, monkeypatch):
        """All three together, one transport, one census at the end."""
        calls = wire(monkeypatch, by_route(BODIES))

        await server.uplers_email_scan()
        await server.uplers_scanned_jobs()
        await server.uplers_agent_settings()

        assert writes(calls) == []
        assert len(calls) == 6

        forbidden = (
            # writes, one path segment away from every GET above
            "consent-email-job-scan",
            "consent-auto-run",
            "interview-feedback",
            "store-recommended-jobs",
            "auto-run-request",
            "intrested",
            # NOT a write, but the wrong list: the alphabetical company picker
            # that would report the first 20 companies in the alphabet as
            # blocked.
            "settings/companies",
        )
        touched = routes_of(calls)
        for route in forbidden:
            assert not any(route in path for path in touched), (route, touched)

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

    def test_the_module_contains_no_write_verb_at_all(self):
        """Not one `post_`/`delete_`/`put_` call anywhere in the module.

        The census above measures the three tools. This measures the MODULE,
        so a helper that writes but is not yet called by a tool cannot sit
        there waiting to be wired up.
        """
        from pathlib import Path

        source = Path(agent_surface.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        for verb in ("post_json", "post_form", "delete_json", "put_json"):
            assert verb not in code, verb


# ==========================================================================
# The two envelope idioms
# ==========================================================================


class TestEnvelopes:

    def test_the_captured_idioms_are_the_two_the_unwrapper_accepts(self):
        """The split MEASURED: five integers, one string, and which is which."""
        seen = {stem: load_talent_fixture(stem)["status"] for stem in FIXTURES}

        assert seen["outreach_templates"] == "success"
        assert isinstance(seen["outreach_templates"], str)
        for stem in FIXTURES:
            if stem != "outreach_templates":
                assert seen[stem] == 200, stem
                assert isinstance(seen[stem], int), stem
        assert set(seen.values()) <= set(outreach.SUCCESS_VALUES)

    def test_narrowing_to_the_integer_arm_refuses_the_templates_route(
        self, monkeypatch
    ):
        """__CONTROL. Proves the string arm is genuinely being used."""
        monkeypatch.setattr(outreach, "SUCCESS_VALUES", (200,))

        with pytest.raises(OutreachError) as excinfo:
            agent_surface.shape_templates(fixture("outreach_templates"))

        assert "status 'success'" in str(excinfo.value)

    def test_narrowing_to_the_string_arm_refuses_the_other_five(self, monkeypatch):
        """__CONTROL. Proves the integer arm is genuinely being used."""
        monkeypatch.setattr(outreach, "SUCCESS_VALUES", ("success",))
        shapers = {
            "outreach_meta_email": agent_surface.shape_email_scan,
            "outreach_scanned_jobs": agent_surface.shape_scanned_jobs,
            "outreach_settings_followup": agent_surface.shape_followup_settings,
            "outreach_disabled_companies": agent_surface.shape_disabled_companies,
            "outreach_auto_reply": agent_surface.shape_auto_reply,
        }

        for stem, shaper in shapers.items():
            with pytest.raises(OutreachError) as excinfo:
                shaper(fixture(stem))
            assert "status 200" in str(excinfo.value), stem

    def test_a_missing_data_key_raises_rather_than_reading_as_empty(self):
        payload = fixture("outreach_disabled_companies")
        del payload["data"]

        with pytest.raises(OutreachError) as excinfo:
            agent_surface.shape_disabled_companies(payload)

        assert "no `data` key" in str(excinfo.value)

    def test_a_list_route_refuses_a_dict_and_a_dict_route_refuses_a_list(self):
        as_dict = fixture("outreach_disabled_companies")
        as_dict["data"] = {"company_name": "Nope"}
        with pytest.raises(OutreachError):
            agent_surface.shape_disabled_companies(as_dict)

        as_list = fixture("outreach_auto_reply")
        as_list["data"] = []
        with pytest.raises(OutreachError):
            agent_surface.shape_auto_reply(as_list)

    def test_an_empty_blocklist_is_an_answer_not_a_failure(self):
        payload = fixture("outreach_disabled_companies")
        payload["data"] = []

        result = agent_surface.shape_disabled_companies(payload)

        assert result["count"] == 0
        assert result["rows"] == []


# ==========================================================================
# uplers_email_scan - the consent
# ==========================================================================


class TestEmailScan:

    def test_it_reports_the_scan_as_on_with_its_mailbox_and_function(self):
        result = agent_surface.shape_email_scan(fixture("outreach_meta_email"))

        assert result["scan"]["enabled"] is True
        assert result["scan"]["last_run_at"] == "2026-08-23 06:58:17"
        assert result["scan"]["job_function"] == {
            "id": 3,
            "name": "Full Stack Development",
        }
        assert result["mailbox"]["connected"] is True
        assert result["jobs"]["total"] == 79
        assert result["jobs"]["breakdown"]["linkedin"] == 79

    def test_the_grant_time_survives_as_a_timestamp_not_a_bool(self):
        """The measurement this tool exists to preserve.

        `bool("2026-08-12 01:32:36")` is True, which is the RIGHT answer for
        the WRONG reason - and coercing it would throw away the only record
        the account holds of when the scan was switched on.
        """
        result = agent_surface.shape_email_scan(fixture("outreach_meta_email"))

        granted = result["scan"]["consent_granted_at"]
        assert granted == "2026-08-12 01:32:36"
        assert isinstance(granted, str)
        assert granted is not True
        assert any("timestamp" in note for note in result["notes"])

    def test_the_dashboard_spelling_is_not_read_as_a_grant_time(self):
        """__CONTROL. The same key is a BOOLEAN on the dashboard route.

        Fed that spelling, the shaper must report the grant time as unknown
        and say what arrived - not invent a date, and not report `True` as
        though it were one.
        """
        payload = fixture("outreach_meta_email")
        payload["data"]["consent_email_job_scan"] = True

        result = agent_surface.shape_email_scan(payload)

        assert result["scan"]["consent_granted_at"] is None
        assert result["scan"]["enabled"] is True          # has_consent is untouched
        assert any("arrived as True" in note for note in result["notes"])

    def test_it_carries_the_receipt_for_calling_this_route_authoritative(self):
        result = agent_surface.shape_email_scan(fixture("outreach_meta_email"))

        authority = result["consent_authority"]
        assert authority["authoritative_field"] == "has_consent"
        assert authority["route"] == endpoints.EP_OUTREACH_META_EMAIL
        assert "_slice-consent-semantics.md" in authority["receipt"]
        assert "consent_email_job_scan" in authority["downstream_copy"]
        assert "second-hand" in authority["downstream_copy"]
        assert "interview-list" in authority["different_consent"]
        assert "INTERVIEW" in authority["different_consent"]

    def test_both_counters_are_reported_and_neither_is_picked(self):
        """Uplers' own two counters disagree by one. Both ship; neither wins."""
        result = agent_surface.shape_email_scan(fixture("outreach_meta_email"))

        best = result["best_for_you"]
        assert best["count"] == 50
        assert best["breakdown_total"] == 51
        assert best["breakdown"]["linkedin"] == 51
        assert best["counters_agree"] is False
        # Not averaged, not silently reconciled into one number.
        assert 50.5 not in best.values()
        assert len(result["disagreements"]) == 1
        note = result["disagreements"][0]["note"]
        assert "50" in note and "51" in note
        assert "not averaged" in note or "not been measured" in note

    def test_a_payload_whose_counters_agree_emits_no_disagreement(self):
        """__CONTROL. Proves the line is computed, not printed unconditionally."""
        payload = fixture("outreach_meta_email")
        payload["data"]["best_for_you_count"] = 51

        result = agent_surface.shape_email_scan(payload)

        assert result["best_for_you"]["counters_agree"] is True
        assert result["disagreements"] == []

    def test_the_mailbox_address_never_leaves(self):
        payload = fixture("outreach_meta_email")
        payload["data"]["gmail_email"] = "a-very-distinctive-address@example.invalid"

        result = agent_surface.shape_email_scan(payload)

        assert not find_text(result, "a-very-distinctive-address")
        assert result["mailbox"]["address_withheld"] is True
        assert "gmail_email" in result["withheld"]

    async def test_the_tool_returns_the_shape_of_the_captured_route(
        self, monkeypatch
    ):
        wire(monkeypatch, by_route(BODIES))

        result = await server.uplers_email_scan()

        assert result["route"] == endpoints.EP_OUTREACH_META_EMAIL
        assert result["scan"]["enabled"] is True


# ==========================================================================
# uplers_scanned_jobs - and the promise about fit scores
# ==========================================================================


class TestScannedJobs:

    def test_it_lists_the_rows_with_the_fields_a_reader_can_act_on(self):
        result = agent_surface.shape_scanned_jobs(
            fixture("outreach_scanned_jobs"), limit=100
        )

        assert result["total_rows"] == 79
        assert result["returned"] == 79
        assert result["last_job_scan"] == "2026-08-23 06:58:17"
        assert result["breakdown"]["linkedin"] == 79
        assert result["best_for_you_rows"] == 51

        first = result["rows"][0]
        assert first["title"] == "Senior Software Engineer"
        assert first["company"] == "Kobie"
        assert first["apply_url"].startswith("https://www.linkedin.com/")
        assert first["job_board"] == "linkedin"
        assert first["publish_datetime"] == "2026-08-23"
        assert first["best_for_you"] is True

    def test_no_row_carries_a_score_of_any_kind(self):
        """THE PROMISE. A fit score in this server comes from jobcore and means
        the same thing as on the Naukri server. These rows have nothing to
        score, so they get no number - not under any name."""
        result = agent_surface.shape_scanned_jobs(
            fixture("outreach_scanned_jobs"), limit=100
        )

        for row in result["rows"]:
            assert set(row) == ROW_KEYS, set(row) ^ ROW_KEYS

        assert numeric_score_fields(result["rows"]) == []
        assert numeric_score_fields(result) == []
        assert result["scoring"]["scored"] is False
        assert "jobcore" in result["scoring"]["why"]

    def test_the_no_score_sweep_can_actually_fire(self):
        """__CONTROL. Plants a score on a captured row.

        Without this the sweep might be walking the wrong nodes and passing for
        that reason, which would leave the promise above certified by nothing.
        """
        result = agent_surface.shape_scanned_jobs(
            fixture("outreach_scanned_jobs"), limit=3
        )
        result["rows"][1]["fit_score"] = 72

        hits = numeric_score_fields(result["rows"])

        assert hits == [("$[1].fit_score", 72)]
        assert set(result["rows"][1]) != ROW_KEYS

    def test_the_emptiness_the_no_score_rule_rests_on_is_real(self):
        """Verified against the fixture directly, not through the shaper.

        If this ever fails, the REASON for not scoring has changed and the
        decision deserves re-taking on the new evidence - which is a different
        act from a shaper quietly starting to emit numbers.
        """
        rows = load_talent_fixture("outreach_scanned_jobs")["data"]

        assert len(rows) == 79
        assert [row for row in rows if row["skills"]] == []
        assert [row for row in rows if row["city"]] == []
        assert [row for row in rows if row["HR_Number"] is not None] == []
        assert [row for row in rows if row["enc_id"]] == []
        assert {row["description"] for row in rows} == {
            agent_surface.PLACEHOLDER_DESCRIPTION
        }

    def test_the_derived_emptiness_counts_track_the_payload(self):
        """__CONTROL for the note: give one row real skills and watch it move."""
        clean = agent_surface.shape_scanned_jobs(fixture("outreach_scanned_jobs"))
        assert clean["scoring"]["rows_with_skills"] == 0
        assert not any("now carry skills" in note for note in clean["notes"])

        payload = fixture("outreach_scanned_jobs")
        payload["data"][0]["skills"] = ["node.js"]
        changed = agent_surface.shape_scanned_jobs(payload)

        assert changed["scoring"]["rows_with_skills"] == 1
        assert any("now carry skills" in note for note in changed["notes"])
        # ...and it STILL does not score.
        assert changed["scoring"]["scored"] is False
        assert numeric_score_fields(changed["rows"]) == []

    def test_limit_truncates_output_but_never_the_count(self):
        result = agent_surface.shape_scanned_jobs(
            fixture("outreach_scanned_jobs"), limit=5
        )

        assert result["returned"] == 5
        assert len(result["rows"]) == 5
        assert result["total_rows"] == 79
        assert result["best_for_you_rows"] == 51      # counted over ALL rows
        assert any("Showing 5 of 79" in note for note in result["notes"])
        assert any("no working limit of its own" in note for note in result["notes"])

    def test_an_untruncated_read_says_nothing_about_truncation(self):
        result = agent_surface.shape_scanned_jobs(
            fixture("outreach_scanned_jobs"), limit=100
        )

        assert not any("Showing" in note for note in result["notes"])

    def test_the_envelope_metadata_lives_outside_data(self):
        """The shape trap on this route, asserted from both sides.

        `last_job_scan` and `breakdown` are SIBLINGS of `data`. A shaper that
        only looked inside the unwrapped node would report no scan time, and
        would do it silently.
        """
        payload = fixture("outreach_scanned_jobs")

        assert "last_job_scan" not in payload["data"][0]
        assert "last_job_scan" in payload
        assert "breakdown" in payload

        result = agent_surface.shape_scanned_jobs(payload)
        assert result["last_job_scan"] == payload["last_job_scan"]
        assert result["plan"] == {"limit": 8, "type": "paid"}

    def test_the_measured_true_arm_sends_the_lowercase_string(self):
        assert agent_surface.scanned_jobs_params(None) is None
        assert agent_surface.scanned_jobs_params(True) == {"best_for_you": "true"}
        # A Python True would serialise with a capital T, which is not what was
        # measured against the live route.
        assert agent_surface.scanned_jobs_params(True)["best_for_you"] != "True"

    def test_the_unmeasured_false_arm_is_refused_and_names_the_way_round(self):
        with pytest.raises(AgentSurfaceRefused) as excinfo:
            agent_surface.scanned_jobs_params(False)

        message = str(excinfo.value)
        assert "never measured" in message
        assert "unset" in message
        assert "79" in message and "51" in message

    async def test_the_tool_sends_the_filter_only_when_asked(self, monkeypatch):
        calls = wire(monkeypatch, by_route(BODIES))

        await server.uplers_scanned_jobs()
        assert "best_for_you" not in calls[0].url.params

        await server.uplers_scanned_jobs(best_for_you=True)
        assert calls[1].url.params["best_for_you"] == "true"

    async def test_the_tool_refuses_false_before_any_request(self, monkeypatch):
        calls = wire(monkeypatch, by_route(BODIES))

        with pytest.raises(AgentSurfaceRefused):
            await server.uplers_scanned_jobs(best_for_you=False)

        assert calls == []

    async def test_the_tool_echoes_the_filter_it_used(self, monkeypatch):
        wire(monkeypatch, by_route(BODIES))

        result = await server.uplers_scanned_jobs(limit=2)

        assert result["best_for_you_filter"] is None
        assert result["returned"] == 2
        assert result["total_rows"] == 79
        assert numeric_score_fields(result) == []


# ==========================================================================
# uplers_agent_settings - follow-up, templates, auto-reply, blocklist
# ==========================================================================


class TestFollowupSettings:

    def test_the_inverted_flag_is_read_as_enabled(self):
        result = agent_surface.shape_followup_settings(
            fixture("outreach_settings_followup")
        )

        for channel in ("gmail", "linkedin"):
            assert result["channels"][channel]["enabled"] is True
            assert result["channels"][channel]["interval_days"] == 1
            assert (
                result["channels"][channel]["source_field"]
                == "disabled_followup_%s" % channel
            )

    def test_a_disabled_channel_really_reads_as_disabled(self):
        """__CONTROL. The capture has BOTH channels enabled, so a shaper that
        hard-coded True - or forgot the negation and got lucky - would pass
        every unmutated assertion above."""
        payload = fixture("outreach_settings_followup")
        payload["data"]["disabled_followup_gmail"] = True

        result = agent_surface.shape_followup_settings(payload)

        assert result["channels"]["gmail"]["enabled"] is False
        assert result["channels"]["linkedin"]["enabled"] is True

    def test_a_missing_flag_is_unknown_rather_than_enabled(self):
        payload = fixture("outreach_settings_followup")
        del payload["data"]["disabled_followup_linkedin"]

        result = agent_surface.shape_followup_settings(payload)

        assert result["channels"]["linkedin"]["enabled"] is None

    def test_the_followup_bodies_never_leave(self):
        payload = fixture("outreach_settings_followup")
        payload["data"]["message_gmail"] = "<p>DISTINCTIVE-FOLLOWUP-BODY</p>"

        result = agent_surface.shape_followup_settings(payload)

        assert not find_text(result, "DISTINCTIVE-FOLLOWUP-BODY")
        assert result["channels"]["gmail"]["message_withheld"] is True
        assert "message_gmail" in result["withheld"]


class TestTemplates:

    def test_it_reports_existence_and_subject_per_channel(self):
        result = agent_surface.shape_templates(fixture("outreach_templates"))

        assert result["channels"]["gmail"]["exists"] is True
        assert result["channels"]["gmail"]["subject"] == (
            "Looking to apply for {{title}} at {{company}}, need referral"
        )
        assert result["channels"]["linkedin"]["exists"] is False

    def test_no_template_body_is_ever_returned(self):
        """THE OTHER PROMISE. The live gmail template is a multi-paragraph
        self-description carrying employer history, a LinkedIn URL and a notice
        period. The fixture masks it; the tool withholds it either way."""
        result = agent_surface.shape_templates(fixture("outreach_templates"))

        raw = load_talent_fixture("outreach_templates")["data"]["gmail_template"]
        assert raw                                   # there IS a body to leak
        assert not find_text(result, raw)
        assert result["channels"]["gmail"]["body_withheld"] is True
        assert "gmail_template" in result["withheld"]
        assert not find_text(result, "<p>")

    def test_the_body_sweep_can_actually_fire(self):
        """__CONTROL. The fixture MASKS the real body, so a sweep run only
        against the fixture could pass by having nothing to find. This puts a
        distinctive body back and proves the sweep catches it."""
        payload = fixture("outreach_templates")
        secret = "I am currently serving a 60 day notice period at ACME"
        payload["data"]["gmail_template"] = "<p>%s</p>" % secret

        leaked = agent_surface.shape_templates(payload)
        assert not find_text(leaked, secret)

        # ...and the sweep itself is capable of failing, proven on a structure
        # that really does carry the body.
        assert find_text({"body": payload["data"]["gmail_template"]}, secret)

    def test_an_empty_template_reads_as_absent_rather_than_missing(self):
        """`linkedin_template` is `""` - a real measured value, not a gap."""
        raw = load_talent_fixture("outreach_templates")["data"]
        assert raw["linkedin_template"] == ""
        assert "linkedin_template" in raw

        result = agent_surface.shape_templates(fixture("outreach_templates"))

        assert result["channels"]["linkedin"]["exists"] is False
        assert result["channels"]["linkedin"]["subject"] is None
        assert any("dead at both ends" in note for note in result["notes"])


class TestAutoReply:

    def test_it_reports_the_switch_the_delay_and_the_categories(self):
        result = agent_surface.shape_auto_reply(fixture("outreach_auto_reply"))

        assert result["enabled"] is False
        assert result["delay_hours"] == 2
        assert result["category_count"] == 8
        assert "asking_resume" in result["categories"]

    def test_it_states_the_asking_resume_fact_without_recommending_anything(self):
        result = agent_surface.shape_auto_reply(fixture("outreach_auto_reply"))

        note = next(note for note in result["notes"] if "asking_resume" in note)
        assert "OFF" in note
        # The forbidden strings are IMPERATIVES. The note's own disclaimer
        # ("no recommendation either way") is the opposite of a recommendation
        # and must not be caught by its own guard.
        for phrase in ("you should", "consider turning", "we recommend",
                       "turn it on", "worth enabling", "would be wise"):
            assert phrase not in note.lower(), phrase

    def test_an_enabled_auto_reply_drops_the_off_note(self):
        """__CONTROL. Proves the note is conditional on the measured state."""
        payload = fixture("outreach_auto_reply")
        payload["data"]["handle_auto_reply"] = True

        result = agent_surface.shape_auto_reply(payload)

        assert result["enabled"] is True
        assert not any("asking_resume" in note for note in result["notes"])


class TestBlockedCompanies:

    def test_it_lists_the_sixteen_with_name_reason_and_time(self):
        result = agent_surface.shape_disabled_companies(
            fixture("outreach_disabled_companies")
        )

        assert result["count"] == 16
        assert result["rows"][0] == {
            "company_name": "Infosys Finacle",
            "reason": None,
            "created_at": "2026-08-12T02:15:04+05:30",
        }
        assert {row["company_name"] for row in result["rows"]} >= {
            "Accenture India",
            "Cognizant",
            "Infosys",
        }

    def test_the_empty_reason_column_is_reported_as_measured(self):
        result = agent_surface.shape_disabled_companies(
            fixture("outreach_disabled_companies")
        )

        assert result["rows_with_reason"] == 0
        assert any("never captured" in note for note in result["notes"])

    def test_it_names_the_picker_route_as_the_wrong_list(self):
        result = agent_surface.shape_disabled_companies(
            fixture("outreach_disabled_companies")
        )

        assert any("settings/companies" in note for note in result["notes"])
        assert any("blocked this company for outreach" in note for note in result["notes"])

    def test_the_two_routes_really_are_different_lists(self):
        """Measured, so the docstring warning is a receipt and not a worry.

        The picker's rows carry `enc_id` and `company_name_initials` and are
        paginated at 20; the blocklist's rows carry `reason` and `created_at`
        and there are 16 of them. Nothing about the two shapes is the same.
        """
        picker = load_talent_fixture("outreach_settings_companies")["data"]
        blocklist = load_talent_fixture("outreach_disabled_companies")["data"]

        assert len(picker) == 20
        assert len(blocklist) == 16
        assert "company_name_initials" in picker[0]
        assert "company_name_initials" not in blocklist[0]
        assert "reason" in blocklist[0]
        assert "reason" not in picker[0]


class TestAgentSettingsReport:

    def shapes(self):
        return {
            "followup": agent_surface.shape_followup_settings(
                fixture("outreach_settings_followup")
            ),
            "templates": agent_surface.shape_templates(fixture("outreach_templates")),
            "auto_reply": agent_surface.shape_auto_reply(
                fixture("outreach_auto_reply")
            ),
            "blocked": agent_surface.shape_disabled_companies(
                fixture("outreach_disabled_companies")
            ),
        }

    def test_the_headline_names_what_is_off(self):
        result = agent_surface.agent_settings(**self.shapes())

        headline = " | ".join(result["headline"])
        assert "linkedin" in headline
        assert "no template exists" in headline
        assert "auto-reply is OFF" in headline
        assert "16 companies are blocked" in headline

    def test_a_swapped_pair_of_shapes_is_refused(self):
        """__CONTROL. Four shaped dicts of similar shape are easy to pass in
        the wrong order, and a swapped pair would otherwise render as a real
        read of his account."""
        shapes = self.shapes()
        shapes["followup"], shapes["templates"] = (
            shapes["templates"],
            shapes["followup"],
        )

        with pytest.raises(OutreachError) as excinfo:
            agent_surface.agent_settings(**shapes)

        assert "not interchangeable" in str(excinfo.value)

    def test_a_raw_payload_in_a_shaped_slot_is_refused(self):
        shapes = self.shapes()
        shapes["auto_reply"] = fixture("outreach_auto_reply")

        with pytest.raises(OutreachError) as excinfo:
            agent_surface.agent_settings(**shapes)

        assert "shape_* function" in str(excinfo.value) or "carry" in str(excinfo.value)

    async def test_the_tool_assembles_all_four_and_leaks_no_body(
        self, monkeypatch
    ):
        wire(monkeypatch, by_route(BODIES))

        result = await server.uplers_agent_settings()

        assert result["reads_only"] is True
        assert result["blocked_companies"]["count"] == 16
        assert result["auto_reply"]["enabled"] is False
        assert result["templates"]["channels"]["gmail"]["exists"] is True
        assert not find_text(result, "Redacted outreach template")
        assert not find_text(result, "Redacted follow-up message")
