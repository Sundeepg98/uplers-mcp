"""The config seam: what the shared jobhunt.json actually moves in this server.

Four things are proved here, and each one has a control that shows the
assertion is capable of failing:

1. **Nothing moved.** With no config file the scores, the flags and the
   ordering are byte-for-byte what this server produced before any of this
   existed. That is the whole migration strategy in one sentence.
2. **A config change moves a real score.** `scoring.weights`,
   `scoring.skills.weights` and `scoring.bonuses` each move a number on a real
   requisition, by the amount predicted.
3. **The Python tilt is reproducible purely from config.** `PREFERENCE_TILT`
   and its two frozensets are gone; the same -4 comes from a rule in the file,
   deleting the rule removes it, and retargeting it moves it to another stack.
4. **Pay is read in USD/year and only in USD/year.** The lakhs band that lives
   beside it in the same document belongs to the Naukri server. The control
   shows the wrong-unit reading, with its number, so "we read the right one"
   is not taken on trust.

The suite is isolated from the operator's real config by an autouse fixture in
conftest (`JOBHUNT_CONFIG=:none:`); every test here opts back in by writing its
own file into tmp_path and pointing the variable at it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from jobcore import policy as jp
from jobcore import config as jobcore_config

from uplers_server import config as uconfig
from uplers_server import fit
from uplers_server import policy as policy_mod
from uplers_server.models import Opportunity, PayBand, SkillSet
from uplers_server.profile import Profile


# --- harness --------------------------------------------------------------


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Write a partial jobhunt.json, point the loader at it, return a Bound.

    Partial on purpose: that is how a human edits the file, and
    ``Policy.from_dict`` fills in every key he did not mention. A test that
    always wrote the full document would never exercise the merge.
    """

    def build(document: dict):
        path = tmp_path / "jobhunt.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        monkeypatch.setenv("JOBHUNT_CONFIG", str(path))
        policy_mod.invalidate()
        return policy_mod.bind()

    yield build
    policy_mod.invalidate()


@pytest.fixture
def unconfigured():
    """A Bound with no file anywhere. The shipped defaults, no I/O."""
    policy_mod.invalidate()
    return policy_mod.DEFAULTS


def role(hr_number="HR010126120010", must_have=("Node.js", "PostgreSQL", "AWS"),
         **kwargs) -> Opportunity:
    """One requisition, identical in every scored dimension except what a test
    deliberately varies."""
    fields = dict(
        hr_number=hr_number,
        title="Backend Engineer",
        company="Acme",
        min_years_experience=3.0,
        max_years_experience=8.0,
        city="Bangalore",
        mode_of_work="Remote",
        joining_period="30 Days",
        skills=SkillSet(must_have=list(must_have)),
    )
    fields.update(kwargs)
    return Opportunity(**fields)


@pytest.fixture
def me() -> Profile:
    return Profile(
        name="Test",
        years_experience=5.0,
        location="Bangalore, India",
        skills=["Node.js", "TypeScript", "AWS", "PostgreSQL", "Python", "React"],
        notice_period_days=0,
    )


# === 1. NOTHING MOVED =====================================================


class TestDefaultsAreTodaysLiterals:
    """If any of these change, live scoring changed. Never incidentally."""

    def test_no_file_means_the_shipped_policy_exactly(self, unconfigured):
        assert unconfigured.policy_hash == jp.DEFAULT_POLICY.policy_hash
        assert unconfigured.loaded.source is None

    @pytest.mark.parametrize("path,expected", [
        ("servers.uplers.must_have.warn_ratio", 0.5),
        ("servers.uplers.must_have.zero_coverage_blocks", True),
        ("servers.uplers.notice.shortfall_blocks", True),
        ("servers.uplers.notice.tolerance_days", 0),
        ("servers.uplers.experience_slack_years", 1),
        ("servers.uplers.exclude_blocked.rank", True),
        ("servers.uplers.exclude_blocked.brief", True),
        ("servers.uplers.exclude_blocked.alerts", False),
        ("servers.uplers.include_aggregated", False),
        ("servers.uplers.auto_sync.enabled", True),
    ])
    def test_the_schema_default_is_the_literal_this_server_carried(self, path, expected):
        assert jp.SCHEMA[path].default == expected

    @pytest.mark.parametrize("path,constant", [
        ("servers.uplers.index_stale_hours", "INDEX_STALE_HOURS"),
        ("servers.uplers.follow_up_stale_days", "FOLLOW_UP_STALE_DAYS"),
        ("servers.uplers.auto_sync.budget", "AUTO_SYNC_FETCH_BUDGET"),
    ])
    def test_schema_and_uplers_config_cannot_drift(self, path, constant):
        """Two places declare one default; they may never disagree silently.

        This is the same disease as ``min_fit_score`` at six sites with two
        values, one repo over.
        """
        assert jp.SCHEMA[path].default == getattr(uconfig, constant)

    def test_the_sync_cadence_agrees_in_seconds(self):
        assert (
            jp.SCHEMA["servers.uplers.auto_sync.interval_hours"].default * 3600
            == uconfig.AUTO_SYNC_INTERVAL_SECONDS
        )

    def test_an_empty_config_file_scores_identically_to_no_file(self, configured,
                                                                unconfigured, me):
        job = role()
        before = fit.assess(job, me, unconfigured)
        after = fit.assess(job, me, configured({}))
        assert after == before

    def test_the_whole_default_document_scores_identically_too(self, configured,
                                                               unconfigured, me):
        """The example file a reader would copy must be a no-op."""
        job = role()
        bound = configured(jobcore_config.default_document())
        assert fit.assess(job, me, bound) == fit.assess(job, me, unconfigured)
        assert bound.policy_hash == jp.DEFAULT_POLICY.policy_hash


# === 2. A CONFIG CHANGE MOVES A REAL SCORE ================================


class TestAConfigChangeMovesAScore:

    def test_the_skill_experience_split_moves_the_overall_score(self, configured,
                                                                unconfigured, me):
        """0.6/0.4 is the number he asked about by name."""
        job = role(must_have=["Node.js", "Kotlin", "Swift", "Elixir"])
        base = fit.assess(job, me, unconfigured)
        moved = fit.assess(job, me, configured(
            {"scoring": {"weights": {"skills": 0.9, "experience": 0.1}}}))

        skills = base["skill_match"]["score"]
        experience = base["experience_match"]["score"]
        assert skills != experience, "the fixture must not be a tie, or this proves nothing"
        assert moved["overall_score"] != base["overall_score"]
        # The arithmetic, not just the inequality.
        bonus = base["overall_score"] - round(0.6 * skills + 0.4 * experience)
        assert moved["overall_score"] == min(
            100, round(0.9 * skills + 0.1 * experience) + bonus)

    def test_a_per_skill_weight_moves_the_overall_score(self, configured,
                                                        unconfigured, me):
        """`scoring.skills.weights` — the seam, on a real Uplers requisition.

        Direction stated rather than assumed: weighted coverage is
        sum(w[matched]) / sum(w[job]), so DOWN-weighting a skill he LACKS
        RAISES the score of a job that asks for it. That is why this is not a
        substitute for the rank tilt, and the number below is the measurement.
        """
        job = role(must_have=["Node.js", "Django"])
        base = fit.assess(job, me, unconfigured)
        assert base["skill_match"]["score"] == 50

        moved = fit.assess(job, me, configured(
            {"scoring": {"skills": {"weights": {"django": 0.7}}}}))
        # 1.0 / 1.7 = 58.8, rounded to the integer the result dict carries.
        assert moved["skill_match"]["score"] == 59
        assert moved["overall_score"] > base["overall_score"]

    def test_a_per_skill_weight_can_lower_a_score_too(self, configured,
                                                      unconfigured, me):
        """Up-weighting a skill he lacks is the direction that demotes."""
        job = role(must_have=["Node.js", "Django"])
        base = fit.assess(job, me, unconfigured)
        moved = fit.assess(job, me, configured(
            {"scoring": {"skills": {"weights": {"django": 3.0}}}}))
        assert moved["skill_match"]["score"] < base["skill_match"]["score"]
        assert moved["overall_score"] < base["overall_score"]

    def test_a_bonus_change_moves_the_score_by_exactly_that_bonus(self, configured,
                                                                  unconfigured, me):
        """A role well under the cap, so the change is not swallowed by min(100, ...)."""
        job = role(must_have=["Node.js", "Kotlin", "Swift"], city="Bangalore")
        base = fit.assess(job, me, unconfigured)
        assert base["overall_score"] < 100
        assert base["bonuses"]["location"] == 5

        moved = fit.assess(job, me, configured(
            {"scoring": {"bonuses": {"location_match": 0}}}))
        assert moved["bonuses"]["location"] == 0
        assert base["overall_score"] - moved["overall_score"] == 5

    def test_a_verdict_band_change_moves_the_words_and_not_the_number(
            self, configured, unconfigured, me):
        job = role()
        base = fit.assess(job, me, unconfigured)
        moved = fit.assess(job, me, configured({"scoring": {"verdicts": [
            {"min": 95, "label": "Exceptional"},
            {"min": 0, "label": "Everything else"},
        ]}}))
        assert moved["overall_score"] == base["overall_score"]
        assert moved["recommendation"] != base["recommendation"]
        assert fit.compact_verdict(moved) in ("exceptional", "everything")

    def test_CONTROL_the_same_file_with_the_loader_disabled_does_nothing(
            self, tmp_path, monkeypatch, unconfigured, me):
        """The measurement is of the FILE, not of something else in the fixture.

        Same bytes on disk, same call, `:none:` instead of the path: the score
        is the shipped one. Without this, every assertion above could be
        passing for a reason that has nothing to do with the config.
        """
        job = role(must_have=["Node.js", "Kotlin", "Swift", "Elixir"])
        path = tmp_path / "jobhunt.json"
        path.write_text(json.dumps(
            {"scoring": {"weights": {"skills": 0.9, "experience": 0.1}}}),
            encoding="utf-8")

        monkeypatch.setenv("JOBHUNT_CONFIG", str(path))
        policy_mod.invalidate()
        moved = fit.assess(job, me, policy_mod.bind())

        monkeypatch.setenv("JOBHUNT_CONFIG", ":none:")
        policy_mod.invalidate()
        ignored = fit.assess(job, me, policy_mod.bind())

        assert moved["overall_score"] != ignored["overall_score"]
        assert ignored == fit.assess(job, me, unconfigured)

    def test_a_broken_file_falls_back_loudly_rather_than_half_applying(
            self, tmp_path, monkeypatch, unconfigured, me):
        path = tmp_path / "jobhunt.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("JOBHUNT_CONFIG", str(path))
        policy_mod.invalidate()
        bound = policy_mod.bind()

        assert bound.policy_hash == jp.DEFAULT_POLICY.policy_hash
        assert bound.loaded.config_error
        assert any("config:" in note for note in bound.notes())
        assert fit.assess(role(), me, bound) == fit.assess(role(), me, unconfigured)

    def test_an_out_of_range_weight_is_refused_whole(self, configured, unconfigured, me):
        """0.0/1.0 makes the overall score equal one component. Refused."""
        bound = configured({"scoring": {"weights": {"skills": 0.0, "experience": 1.0}}})
        assert bound.policy_hash == jp.DEFAULT_POLICY.policy_hash
        assert bound.loaded.config_error
        assert fit.assess(role(), me, bound) == fit.assess(role(), me, unconfigured)


# === 3. THE PYTHON TILT, PURELY FROM CONFIG ===============================


PY_ROLE = role("HR010126120010", ["Python", "PostgreSQL", "AWS"])
NODE_ROLE = role("HR010126120011", ["Node.js", "PostgreSQL", "AWS"])
PHP_ROLE = role("HR010126120012", ["PHP", "PostgreSQL", "AWS"])


class TestTheStackPreferenceIsNowConfig:

    def test_the_deleted_constant_is_really_gone(self):
        assert not hasattr(fit, "PREFERENCE_TILT")
        assert not hasattr(fit, "PYTHON_STACK")
        assert not hasattr(fit, "NODE_STACK")

    def test_the_shipped_default_still_demotes_by_four(self, unconfigured, me):
        assert fit.assess(PY_ROLE, me, unconfigured)["rank_adjustment"] == -4

    def test_deleting_the_rule_removes_the_demotion(self, configured, me):
        bound = configured({"scoring": {"rank_adjustments": []}})
        result = fit.assess(PY_ROLE, me, bound)
        assert "rank_adjustment" not in result
        assert not any("python-leaning" in flag for flag in result["flags"])

    def test_deleting_the_rule_changes_the_ORDER_and_not_the_scores(
            self, configured, unconfigured, me):
        with_tilt, _, _ = fit.rank([PY_ROLE, NODE_ROLE], me, bound=unconfigured)
        without, _, _ = fit.rank([PY_ROLE, NODE_ROLE], me,
                              bound=configured({"scoring": {"rank_adjustments": []}}))

        assert [o.hr_number for o, _ in with_tilt] == [
            NODE_ROLE.hr_number, PY_ROLE.hr_number]
        assert [o.hr_number for o, _ in without] == [
            PY_ROLE.hr_number, NODE_ROLE.hr_number]   # tie, broken by hr_number
        assert {o.hr_number: a["overall_score"] for o, a in with_tilt} == \
            {o.hr_number: a["overall_score"] for o, a in without}

    def test_a_hand_written_rule_reproduces_the_deleted_constant_exactly(
            self, configured, unconfigured, me):
        """The tilt, from config alone, with the shipped rule replaced."""
        bound = configured({"scoring": {"rank_adjustments": [{
            "when_skills_include": ["python", "django", "flask", "fastapi"],
            "and_not": ["javascript", "typescript", "node.js", "express",
                        "nestjs", "next.js"],
            "delta": -4,
            "label": "python-leaning stack",
        }]}})
        assert fit.assess(PY_ROLE, me, bound) == fit.assess(PY_ROLE, me, unconfigured)
        assert fit.assess(NODE_ROLE, me, bound) == fit.assess(NODE_ROLE, me, unconfigured)

    def test_a_retargeted_rule_moves_the_preference_to_another_stack(
            self, configured, me):
        bound = configured({"scoring": {"rank_adjustments": [{
            "when_skills_include": ["php", "laravel"],
            "delta": -3,
            "label": "php shop",
        }]}})
        assert fit.assess(PHP_ROLE, me, bound)["rank_adjustment"] == -3
        assert "rank_adjustment" not in fit.assess(PY_ROLE, me, bound)
        assert any("php shop: ranked -3" in flag
                   for flag in fit.assess(PHP_ROLE, me, bound)["flags"])

    def test_the_and_not_clause_is_what_a_bare_per_skill_weight_cannot_express(
            self, configured, me):
        """A role wanting BOTH stacks is the direction he is moving in."""
        both = role("HR010126120013", ["Python", "Node.js", "PostgreSQL"])
        bound = configured({})
        assert "rank_adjustment" not in fit.assess(both, me, bound)

    def test_an_over_bound_delta_is_refused_and_the_whole_file_falls_back(
            self, configured, unconfigured, me):
        """A tilt that could outrank 'this role is actually remote' is refused."""
        bound = configured({"scoring": {"rank_adjustments": [{
            "when_skills_include": ["python"], "delta": -40, "label": "hide python",
        }]}})
        assert bound.loaded.config_error
        assert "rank_adjustments" in bound.loaded.config_error
        assert fit.assess(PY_ROLE, me, bound) == fit.assess(PY_ROLE, me, unconfigured)

    def test_an_unlabelled_rule_is_refused(self, configured):
        bound = configured({"scoring": {"rank_adjustments": [{
            "when_skills_include": ["python"], "delta": -2,
        }]}})
        assert bound.loaded.config_error
        assert "label" in bound.loaded.config_error

    @pytest.mark.parametrize("document", [
        {},
        {"scoring": {"rank_adjustments": []}},
        {"scoring": {"rank_adjustments": [
            {"when_skills_include": ["python"], "delta": -4, "label": "x"}]}},
        {"scoring": {"rank_adjustments": [
            {"when_skills_include": ["node.js"], "delta": -4, "label": "y"}]}},
    ], ids=["shipped", "off", "python", "node"])
    def test_no_rule_arrangement_can_move_overall_score(self, configured, me, document):
        """The invariant jobcore exists to hold: a 78 means the same everywhere."""
        baseline = fit.assess(PY_ROLE, me, policy_mod.DEFAULTS)["overall_score"]
        assert fit.assess(PY_ROLE, me, configured(document))["overall_score"] == baseline


# === 4. C4 — PAY IS READ IN USD/YEAR, AND ONLY IN USD/YEAR ================


PAID_ROLE = role(
    "HR010126120020", ["Node.js", "PostgreSQL", "AWS"],
    pay=PayBand(usd_year_min=60000, usd_year_max=90000),
)


class TestPayIsScoredInThisServersOwnUnit:

    def test_the_only_unit_this_server_names_is_usd(self):
        assert policy_mod.PAY_UNIT == "usd_per_year"
        assert policy_mod.PAY_UNIT in jp.PAY_UNITS
        assert policy_mod.FOREIGN_PAY_UNIT in jp.PAY_UNITS

    def test_a_usd_floor_in_the_shared_block_earns_the_salary_bonus(
            self, configured, me):
        bound = configured({"candidate": {"pay": {
            "usd_per_year": {"floor": 20959}}}})
        profile, where = policy_mod.effective_profile(me, bound)
        assert where["min_pay_usd_year"] == "config"
        assert profile.min_pay_usd_year == 20959
        assert fit.assess(PAID_ROLE, profile, bound)["bonuses"]["salary"] == 5

    def test_a_lakhs_band_beside_it_is_never_read_here(self, configured, me):
        """Naukri's 24 lakhs sits in the same document and must not leak."""
        bound = configured({"candidate": {"pay": {
            "inr_lakhs_per_year": {"expected": 24, "floor": 20},
            "usd_per_year": {"floor": 20959},
        }}})
        profile, _ = policy_mod.effective_profile(me, bound)
        assert profile.min_pay_usd_year == 20959
        assert policy_mod.expected_pay(profile) == 20959
        assert bound.pay_band().floor == 20959

    def test_a_lakhs_only_configuration_leaves_this_server_with_no_expectation(
            self, configured, me):
        """Correct: there is no evidence in a unit this board speaks."""
        bound = configured({"candidate": {"pay": {
            "inr_lakhs_per_year": {"expected": 24, "floor": 20}}}})
        profile, _ = policy_mod.effective_profile(me, bound)
        assert profile.min_pay_usd_year is None
        assert fit.assess(PAID_ROLE, profile, bound)["bonuses"]["salary"] == 0

    def test_CONTROL_reading_the_lakhs_band_would_give_the_wrong_answer(
            self, configured, me):
        """The bug this split exists to stop, with its number.

        A 24-lakh expectation read as dollars clears a $60k-90k band by a
        factor of 2,500, so EVERY role on this board would take the +5 - which
        looks exactly like a correctly configured profile.
        """
        bound = configured({"candidate": {"pay": {
            "inr_lakhs_per_year": {"expected": 24, "floor": 20}}}})
        wrong = bound.candidate.pay.for_unit(policy_mod.FOREIGN_PAY_UNIT)
        assert wrong.expected == 24

        mistaken = me.model_copy(update={"min_pay_usd_year": int(wrong.expected)})
        assert fit.assess(PAID_ROLE, mistaken, bound)["bonuses"]["salary"] == 5

        right, _ = policy_mod.effective_profile(me, bound)
        assert fit.assess(PAID_ROLE, right, bound)["bonuses"]["salary"] == 0

    def test_asking_for_an_unknown_unit_raises_rather_than_guessing(self, unconfigured):
        with pytest.raises(jp.PolicyError, match="unknown pay unit"):
            unconfigured.candidate.pay.for_unit("gbp_per_month")

    def test_expected_and_floor_are_two_decisions(self, configured, me):
        """Collapsing them into one number is exactly the H7 disease."""
        bound = configured({"candidate": {"pay": {
            "usd_per_year": {"floor": 20959, "expected": 120000}}}})
        profile, _ = policy_mod.effective_profile(me, bound)
        assert profile.min_pay_usd_year == 20959
        assert policy_mod.expected_pay(profile) == 120000
        # The floor alone would take the +5 (a 60-90k band clears $20,959).
        # Scored against what he actually wants, the band does not reach it.
        assert fit.assess(PAID_ROLE, profile, bound)["bonuses"]["salary"] == 0

        floor_only = me.model_copy(update={"min_pay_usd_year": 20959})
        assert fit.assess(PAID_ROLE, floor_only, bound)["bonuses"]["salary"] == 5

    def test_an_unset_expected_falls_back_to_the_floor_which_is_todays_behaviour(
            self, me):
        profile = me.model_copy(update={"min_pay_usd_year": 20959})
        assert profile.expected_pay_usd_year is None
        assert policy_mod.expected_pay(profile) == 20959

    def test_the_single_scalar_shape_is_refused_by_name(self, configured):
        bound = configured({"candidate": {"pay": {"expected": 24, "unit": "lakhs"}}})
        assert bound.loaded.config_error
        assert "denominated per unit" in bound.loaded.config_error

    def test_absurd_denominations_warn_and_never_convert(self, configured, me):
        bound = configured({"candidate": {"pay": {
            "inr_lakhs_per_year": {"expected": 24},
            "usd_per_year": {"expected": 24},
        }}})
        assert any("INR/USD" in note for note in bound.notes())
        profile, _ = policy_mod.effective_profile(me, bound)
        assert profile.expected_pay_usd_year == 24   # untouched, not converted


# === 5. servers.uplers.* ACTUALLY READS ===================================


class TestTheServerBlockIsRead:

    def test_the_warn_ratio_moves_a_flag(self, configured, unconfigured, me):
        job = role(must_have=["Node.js", "Kotlin", "Swift"])   # 1 of 3 = 0.33
        assert any("covers only 1 of 3" in f
                   for f in fit.assess(job, me, unconfigured)["flags"])

        loose = configured({"servers": {"uplers": {"must_have": {"warn_ratio": 0.2}}}})
        assert not any("covers only" in f for f in fit.assess(job, me, loose)["flags"])

    def test_zero_coverage_can_be_demoted_from_a_blocker_to_a_flag(
            self, configured, unconfigured, me):
        job = role(must_have=[".NET", "Azure"])
        assert any("must-have" in b for b in fit.assess(job, me, unconfigured)["blockers"])

        soft = configured({"servers": {"uplers": {
            "must_have": {"zero_coverage_blocks": False}}}})
        result = fit.assess(job, me, soft)
        assert result["blockers"] == []
        assert any("must-have" in f for f in result["flags"])

    def test_notice_tolerance_unblocks_a_role(self, configured, unconfigured):
        picky = Profile(years_experience=5.0, skills=["Node.js"], notice_period_days=45)
        job = role(joining_period="30 Days")
        assert any("notice" in b for b in
                   fit.blockers_and_flags(job, picky, unconfigured)[0])

        lenient = configured({"servers": {"uplers": {
            "notice": {"tolerance_days": 20}}}})
        assert fit.blockers_and_flags(job, picky, lenient)[0] == []

    def test_notice_shortfall_can_become_a_flag_instead(self, configured):
        picky = Profile(years_experience=5.0, skills=["Node.js"], notice_period_days=45)
        soft = configured({"servers": {"uplers": {
            "notice": {"shortfall_blocks": False}}}})
        blockers, flags = fit.blockers_and_flags(role(joining_period="30 Days"),
                                                 picky, soft)
        assert blockers == []
        assert any("notice" in f for f in flags)

    def test_experience_slack_unblocks_a_junior_candidate(self, configured, unconfigured):
        junior = Profile(years_experience=1.0, skills=["Node.js"], notice_period_days=0)
        job = role(min_years_experience=4.0)
        assert any("experience" in b for b in
                   fit.blockers_and_flags(job, junior, unconfigured)[0])

        generous = configured({"servers": {"uplers": {"experience_slack_years": 5}}})
        assert fit.blockers_and_flags(job, junior, generous)[0] == []

    def test_exclude_blocked_default_for_rank_comes_from_the_file(
            self, configured, unconfigured, me):
        blocked = role("HR010126120099", [".NET", "Azure"])
        kept, _, _ = fit.rank([blocked], me, bound=unconfigured)
        assert kept == []

        shown, count, _ = fit.rank([blocked], me, bound=configured(
            {"servers": {"uplers": {"exclude_blocked": {"rank": False}}}}))
        assert count == 1 and len(shown) == 1

    def test_an_explicit_argument_still_beats_the_file(self, configured, me):
        blocked = role("HR010126120099", [".NET", "Azure"])
        bound = configured({"servers": {"uplers": {
            "exclude_blocked": {"rank": False}}}})
        kept, _, _ = fit.rank([blocked], me, exclude_blocked=True, bound=bound)
        assert kept == []

    def test_a_foreign_servers_block_does_not_reach_this_one(self, configured):
        bound = configured({"servers": {"instahyre": {"exclude_agencies": True}}})
        assert bound.setting("exclude_blocked", "rank") is True
        assert bound.setting("exclude_agencies") is None


# === 6. THE INVARIANT, EXERCISED FROM THIS SERVER =========================


class TestTierCIsNotLoadableFromHere:
    """A config write from any server may not grant autonomous apply authority.

    jobcore holds this and tests it by running the attack. What is asserted
    HERE is the part that belongs to this repo: the refusal is visible to a
    uplers tool call, and it changes nothing about a uplers score.
    """

    #: THE NAMESPACE IS THE POINT, and this fixture used to get it wrong.
    #:
    #: It planted `servers.naukri.*` - a SIBLING's namespace - while the
    #: docstring above claims to assert "the part that belongs to this repo".
    #: Those two things disagreed, and nobody noticed until jobcore moved the
    #: six agent keys to tier B for naukri (`ac189b0`): the plant stopped being
    #: refused, this test went red, and the red was reporting a fact about
    #: naukri's configuration rather than about uplers' safety.
    #:
    #: A test that reaches into another server's namespace to assert something
    #: about its own is not testing what it says it tests, and it fails the day
    #: that other server's owner makes a decision - a decision they are entitled
    #: to make and cannot see this assertion from.
    #:
    #: Measured after the move: the same five-write escalation yields 0 tier-C
    #: refusals for naukri (now tier B), 4 for uplers, 3 for instahyre. The
    #: uplers invariant never weakened; only the namespace being probed was
    #: wrong.
    ESCALATION = {
        "servers": {"uplers": {"agent": {
            "enabled": True,
            "mode": "auto",
            "min_fit_score": 0,
            "blocklist": {"enabled": False},
        }}}
    }

    def test_the_escalation_in_the_file_is_refused_and_reported(self, configured):
        bound = configured(self.ESCALATION)
        refusals = " ".join(bound.loaded.tier_c_refusals)
        for key in ("enabled", "mode", "min_fit_score"):
            assert key in refusals
        assert any("REFUSED" in note for note in bound.notes())

    def test_this_class_probes_its_OWN_namespace__CONTROL(self):
        """__CONTROL. The escalation must target `servers.uplers.*`, always.

        This guard exists because the defect it catches survived undetected
        until a SIBLING made an unrelated decision. The fixture planted
        `servers.naukri.*`, the assertions passed for years because naukri's
        agent keys happened to be tier C, and the day jobcore moved them to
        tier B this suite went red while uplers' own invariant was untouched.

        Red for somebody else's reason is the worst kind of red: it looks like
        your safety property broke, and the temptation is to weaken your own
        assertion to get green again.

        So the namespace is asserted structurally rather than trusted. A future
        edit that reaches into a sibling's namespace fails HERE, with a message
        saying why, instead of failing months later as a mystery.
        """
        servers = self.ESCALATION["servers"]
        assert list(servers) == ["uplers"], (
            "this class asserts a UPLERS invariant, so it must plant in "
            "uplers' namespace. Found %s. A tier change made by the owner of "
            "another server must never turn this suite red - they cannot see "
            "this assertion, and they are entitled to make that change."
            % sorted(servers)
        )

    def test_it_does_not_move_a_uplers_score(self, configured, unconfigured, me):
        bound = configured(self.ESCALATION)
        assert fit.assess(role(), me, bound) == fit.assess(role(), me, unconfigured)

    def test_the_sibling_skills_path_is_bounded_not_open(self, configured, me):
        """Writing every canonical skill into candidate.skills scores 100 on
        every job that exists. The cap is in Python and the file cannot raise it."""
        from jobcore import SKILL_ALIASES

        everything = sorted(SKILL_ALIASES)
        bound = configured({"candidate": {"skills": everything}})
        assert bound.loaded.config_error
        assert "candidate.skills" in bound.loaded.config_error
        profile, where = policy_mod.effective_profile(me, bound)
        assert where["skills"] == "local"
        assert profile.skills == me.skills


# === 7. THE SCORING PATH READS NO FILE ====================================


class TestScoringDoesNoIO:

    def test_assess_never_reaches_the_loader(self, monkeypatch, unconfigured, me):
        """fit.py takes a binding; it must not go looking for one.

        This is jobcore's independence rule one layer up: the same requisition
        has to score the same on two machines.
        """
        def explode(*args, **kwargs):
            raise AssertionError("the scoring path read the config")

        monkeypatch.setattr(jobcore_config, "current", explode)
        assert fit.assess(role(), me, unconfigured)["overall_score"] > 0
        assert fit.rank([role()], me, bound=unconfigured)[0]
        assert fit.preference_tilt({"python"}, unconfigured) == (
            -4, ("python-leaning stack",))

    def test_the_module_imports_nothing_that_reads_at_import_time(self):
        """policy.py is the only module here allowed to touch jobcore.config."""
        import inspect

        source = inspect.getsource(fit)
        assert "jobcore.config" not in source
        assert "jobcore_config" not in source


# === 8. THE CANDIDATE BLOCK, LAYERED OVER data/profile.json ===============


class TestCandidateLayering:

    def test_an_unconfigured_field_stays_local(self, configured, me):
        profile, where = policy_mod.effective_profile(me, configured({}))
        assert profile == me
        assert set(where.values()) == {"local"}

    def test_a_configured_field_wins(self, configured, me):
        bound = configured({"candidate": {"skills": ["rust", "go"]}})
        profile, where = policy_mod.effective_profile(me, bound)
        assert profile.skills == ["rust", "go"]
        assert where["skills"] == "config"
        assert where["years_experience"] == "local"
        assert profile.years_experience == me.years_experience

    def test_provenance_not_emptiness_decides(self, configured):
        """The trap: candidate.notice_period_days defaults to 0, and 0 is also
        a real answer. An emptiness rule would silently overwrite 30 with 0."""
        local = Profile(years_experience=5.0, skills=["Node.js"],
                        notice_period_days=30)
        bound = configured({"candidate": {"name": "G. Sundeep"}})

        assert bound.candidate.notice_period_days == 0          # the shipped default
        profile, where = policy_mod.effective_profile(local, bound)
        assert profile.notice_period_days == 30
        assert where["notice_period_days"] == "local"

    def test_CONTROL_an_emptiness_rule_would_have_clobbered_it(self, configured):
        """What the wrong discriminator produces, so the guard is not on trust."""
        local = Profile(years_experience=5.0, skills=["Node.js"],
                        notice_period_days=30)
        bound = configured({"candidate": {"name": "G. Sundeep"}})
        naive = local.notice_period_days if bound.candidate.notice_period_days else 0
        assert naive == 0
        assert policy_mod.effective_profile(local, bound)[0].notice_period_days == 30

    def test_an_explicit_zero_in_the_file_does_win(self, configured):
        local = Profile(years_experience=5.0, skills=["Node.js"],
                        notice_period_days=30)
        bound = configured({"candidate": {"notice_period_days": 0}})
        profile, where = policy_mod.effective_profile(local, bound)
        assert profile.notice_period_days == 0
        assert where["notice_period_days"] == "config"

    def test_the_first_configured_location_becomes_the_scored_one(self, configured, me):
        bound = configured({"candidate": {"locations": ["Pune", "Bangalore"]}})
        profile, where = policy_mod.effective_profile(me, bound)
        assert profile.location == "Pune"
        assert where["location"] == "config"

    def test_layering_never_mutates_the_local_profile(self, configured, me):
        before = me.model_dump()
        policy_mod.effective_profile(me, configured({"candidate": {"skills": ["rust"]}}))
        assert me.model_dump() == before

    # -- the generated-template trap ---------------------------------------
    #
    # The three above establish that PROVENANCE decides, and they are right
    # about the case they cover. These four cover the case they do not: a file
    # that names EVERY key because a generator wrote it, not because a human
    # answered it.

    def test_the_documented_on_ramp_does_not_wipe_his_profile(self, configured):
        """Copying the shipped example - or `default_document()`, which is the
        same shape - must be inert. MEASURED before this guard: three scores
        went 100 -> 30, 88 -> 23, 80 -> 20 and every "Strong match" became
        "Weak match", because the template's `skills: []` and `pay.floor: null`
        are provenance "file" on every key."""
        local = Profile(
            years_experience=5.0,
            skills=["Node.js", "TypeScript", "AWS"],
            location="Bangalore, India",
            min_pay_usd_year=20959,
        )
        bound = configured(jobcore_config.default_document())

        profile, where = policy_mod.effective_profile(local, bound)
        assert profile.skills == local.skills
        assert profile.min_pay_usd_year == 20959
        assert profile.location == "Bangalore, India"
        assert where["skills"] == "local"
        assert where["min_pay_usd_year"] == "local"

    def test_CONTROL_provenance_alone_would_have_wiped_it(self, configured):
        """The old rule, run on the same input, so the harm is a number."""
        bound = configured(jobcore_config.default_document())
        assert bound.configured("candidate.skills") is True
        assert bound.candidate.skills == ()
        # Provenance says "the file set it"; the file set it to nothing.
        assert policy_mod.states_nothing(bound.candidate.skills)

    def test_a_key_the_file_names_but_does_not_answer_is_reported(self, configured):
        """Not silent in either direction: local wins AND the reader is told."""
        bound = configured(jobcore_config.default_document())
        unanswered = bound.named_but_unanswered()
        assert "candidate.skills" in unanswered
        assert any("without answering" in note for note in bound.notes())

    def test_a_key_the_file_actually_answers_is_not_reported(self, configured):
        bound = configured({"candidate": {"skills": ["rust", "go"]}})
        assert "candidate.skills" not in bound.named_but_unanswered()


# === 9. THE uplers_config TOOL ============================================


class TestTheConfigTool:
    """The one tool in this server that can write a file other servers read."""

    async def test_it_reports_the_defaults_when_the_loader_is_disabled(
            self, make_profile):
        import server

        make_profile()
        policy_mod.invalidate()
        report = await server.uplers_config()

        assert report.source is None
        assert "built-in defaults" in report.status
        assert report.policy_hash == jp.DEFAULT_POLICY.policy_hash
        assert report.server["must_have"]["warn_ratio"] == 0.5
        assert report.write == {}

    async def test_a_missing_file_names_every_path_tried(self, make_profile,
                                                         monkeypatch, tmp_path):
        """"I edited it and nothing happened" is usually "you edited the wrong one"."""
        import server

        make_profile()
        monkeypatch.setenv("JOBHUNT_CONFIG", str(tmp_path / "absent.json"))
        policy_mod.invalidate()
        report = await server.uplers_config()

        assert report.source is None
        # RELATIVISED, not raw and not dropped. The path is rendered so the
        # payload publishes no machine layout, and it still NAMES the file
        # tried - which is the whole use of this field. Two different searched
        # paths must still render to two different strings; that is pinned in
        # tests/test_path_hygiene.py.
        assert report.searched == [policy_mod.display_path(str(tmp_path / "absent.json"))]
        assert report.searched[0].endswith("absent.json")
        assert not re.search(r"[A-Za-z]:[\\/]", report.searched[0])
        assert report.policy_hash == jp.DEFAULT_POLICY.policy_hash

    async def test_it_reports_the_file_and_its_provenance(self, configured,
                                                          make_profile):
        import server

        make_profile()
        configured({"scoring": {"weights": {"skills": 0.7, "experience": 0.3}}})
        report = await server.uplers_config()

        assert report.source is not None
        assert report.scoring["weights"] == {"skills": 0.7, "experience": 0.3}
        assert report.provenance.get("scoring.weights.skills") == "file"
        assert "scoring.bonuses.remote" not in report.provenance   # a default

    async def test_it_surfaces_a_tier_c_refusal_rather_than_swallowing_it(
            self, configured, make_profile):
        import server

        make_profile()
        # OWN namespace, not a sibling's - see the note on
        # TestTierCIsNotLoadableFromHere.ESCALATION for why this matters.
        configured({"servers": {"uplers": {"agent": {"enabled": True,
                                                     "mode": "auto"}}}})
        report = await server.uplers_config()

        assert report.refused
        assert any("REFUSED" in line for line in report.refused)
        assert any("mode" in line for line in report.refused)

    async def test_write_candidate_refuses_when_there_is_no_file_and_says_where(
            self, make_profile, monkeypatch):
        import server

        make_profile()
        monkeypatch.setenv("JOBHUNT_CONFIG", ":none:")
        policy_mod.invalidate()
        report = await server.uplers_config(write_candidate=True)

        assert report.write["status"] == "no_config_file"
        assert any("no jobhunt.json yet" in note for note in report.notes)

    async def test_write_candidate_copies_the_local_profile_into_the_file(
            self, configured, make_profile, tmp_path):
        import server

        make_profile(skills=["Node.js", "TypeScript"], years_experience=5.0,
                     location="Bangalore, India", min_pay_usd_year=20959)
        configured({})
        report = await server.uplers_config(write_candidate=True,
                                            allow_score_raising=True)

        assert report.write["status"] == "ok", report.write
        written = json.loads((tmp_path / "jobhunt.json").read_text(encoding="utf-8"))
        assert written["candidate"]["skills"] == ["Node.js", "TypeScript"]
        assert written["candidate"]["locations"] == ["Bangalore, India"]
        assert written["candidate"]["pay"]["usd_per_year"]["floor"] == 20959
        # And nothing else was touched.
        assert "scoring" not in written or written["scoring"] == {}
        assert "servers" not in written or written["servers"] == {}

    async def test_the_write_never_emits_a_lakhs_band(self, configured, make_profile,
                                                      tmp_path):
        import server

        make_profile(min_pay_usd_year=20959)
        configured({})
        await server.uplers_config(write_candidate=True, allow_score_raising=True)
        written = json.loads((tmp_path / "jobhunt.json").read_text(encoding="utf-8"))

        pay = written["candidate"]["pay"]
        assert policy_mod.PAY_UNIT in pay
        assert policy_mod.FOREIGN_PAY_UNIT not in pay

    async def test_adding_skills_needs_the_score_raising_flag(self, configured,
                                                             make_profile):
        import server

        make_profile(skills=["Node.js", "TypeScript", "AWS"])
        configured({})
        report = await server.uplers_config(write_candidate=True)

        assert report.write["status"] == "refused"
        assert any("candidate.skills" in line for line in report.write["refusals"])

    @pytest.mark.parametrize("patch", [
        {"scoring": {"weights": {"skills": 0.9, "experience": 0.1}}},
        {"servers": {"naukri": {"display_min_score": 10}}},
        {"servers": {"uplers": {"include_aggregated": True}}},
    ], ids=["scoring", "sibling-server", "own-server"])
    async def test_the_tools_section_scoping_refuses_everything_but_candidate(
            self, configured, make_profile, patch):
        """The tool passes allowed_sections=("candidate",) and nothing widens it.

        Even its OWN server block is out of scope: this tool exists to migrate
        a profile, and a write surface that can also retune the board is a
        different tool with a different worst case.
        """
        import server

        make_profile()
        configured({})
        refused = jobcore_config.apply_patch(
            patch,
            path=Path(policy_mod.snapshot().source),
            allowed_sections=("candidate",),
            actor="test",
        )
        assert refused["status"] == "refused"
        assert any("not writable from here" in line for line in refused["refusals"])
        assert server.uplers_config.__doc__


# === 10. NO CALL SITE MAY SILENTLY IGNORE THE CONFIG ======================


#: How many arguments each scoring entry point takes before ``bound``.
SCORING_ENTRY_POINTS = {"assess": 2, "rank": 2, "parse_skills": 1}

PRODUCTION_MODULES = (
    "server.py",
    "uplers_server/alerts.py",
    "uplers_server/brief.py",
    "uplers_server/insight.py",
    "uplers_server/talent_shape.py",
)


def unbound_call_sites(source: str) -> list[str]:
    """Every ``fit.<entry point>`` call in *source* reached without a binding.

    ``bound=None`` means "the shipped defaults", which is what keeps an
    unmigrated caller working - and is therefore exactly how a call site could
    silently ignore the operator's file while still returning a plausible
    number. So the invariant is checked structurally rather than trusted.
    """
    import ast

    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "fit"
                and func.attr in SCORING_ENTRY_POINTS):
            continue
        before = SCORING_ENTRY_POINTS[func.attr]
        positional = len(node.args) > before
        keyword = any(kw.arg == "bound" for kw in node.keywords)
        if not (positional or keyword):
            found.append("line %d: fit.%s(...)" % (node.lineno, func.attr))
    return found


class TestEveryCallSiteBindsTheConfig:

    @pytest.mark.parametrize("relative", PRODUCTION_MODULES)
    def test_no_production_call_site_scores_on_the_defaults(self, relative):
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parent.parent
        source = (root / relative).read_text(encoding="utf-8")
        assert unbound_call_sites(source) == [], relative

    def test_CONTROL_the_scan_catches_a_bare_call(self):
        """The checker has been shown failing, on all three entry points."""
        assert unbound_call_sites("fit.assess(opp, profile)") == [
            "line 1: fit.assess(...)"]
        assert unbound_call_sites("fit.rank(jobs, profile, exclude_blocked=True)") == [
            "line 1: fit.rank(...)"]
        assert unbound_call_sites("fit.parse_skills(raw)") == [
            "line 1: fit.parse_skills(...)"]

    def test_CONTROL_the_scan_accepts_both_spellings(self):
        assert unbound_call_sites("fit.assess(opp, profile, bound)") == []
        assert unbound_call_sites("fit.assess(opp, profile, bound=bound)") == []
        assert unbound_call_sites("fit.rank(jobs, profile, bound=bound)") == []


class TestSetProfileCarriesTheSplit:

    async def test_the_expected_pay_field_round_trips(self, make_profile):
        import server
        from uplers_server import profile as prof

        make_profile(min_pay_usd_year=20959)
        result = await server.uplers_set_profile(expected_pay_usd_year=120000)

        assert result.profile.expected_pay_usd_year == 120000
        assert result.profile.min_pay_usd_year == 20959
        assert prof.load(path=prof.profile_path()).expected_pay_usd_year == 120000

    async def test_the_missing_pay_note_names_both_fields(self, make_profile):
        import server

        make_profile(min_pay_usd_year=None)
        result = await server.uplers_get_profile()

        assert any("expected_pay_usd_year" in note and "min_pay_usd_year" in note
                   for note in result.notes)

    async def test_a_floor_alone_silences_the_note(self, make_profile):
        import server

        make_profile(min_pay_usd_year=20959)
        result = await server.uplers_get_profile()

        assert not any("salary bonus never applies" in note for note in result.notes)
