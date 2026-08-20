"""fit.py - the adapter between an Uplers requisition and jobcore.

The scoring maths belongs to jobcore and is tested there against a 179-input
golden corpus. What is tested HERE is the translation, and specifically the
three places it could be wrong in a way that still produces a plausible
number:

  * a rupee band read as dollars,
  * "no upper bound" read as "zero years",
  * a role whose only mandatory skill you lack scored as a strong match.

All three were real: the third was caught on the live 235-record cohort during
the build, where an Angular/.NET requisition ranked first against a Node
profile because its two good-to-have skills matched.
"""

from __future__ import annotations

import pytest

from uplers_server import fit
from uplers_server.models import Opportunity, PayBand, SkillSet
from uplers_server.profile import Profile
from uplers_server.shaping import to_opportunity

from conftest import AGENTAI, AGGREGATED, ANOMALY, CONFIDO, PRECISELY, load_fixture


def opportunity(hr_number):
    return to_opportunity(load_fixture(hr_number))


@pytest.fixture
def node_profile():
    return Profile(
        name="Test",
        years_experience=5.0,
        location="Bangalore, India",
        skills=["Node.js", "TypeScript", "AWS", "PostgreSQL", "Python", "React"],
    )


# --- the units trap -------------------------------------------------------


def test_the_usd_salary_type_does_not_divide_realistic_salaries():
    """jobcore's default config would turn 60,000 into 0.6 lakhs."""
    salary = fit.UsdYearSalary.from_string("60000-90000")

    assert salary.min_lakhs == 60000
    assert salary.max_lakhs == 90000
    assert salary.is_disclosed


def test_a_local_currency_band_is_never_handed_to_the_dollar_parser():
    """An INR band with no USD normalisation must yield no salary string.

    Passing "INR 9,00,000-15,00,000 / year" through would read 900,000 as a US
    salary and score every Indian role as a windfall.
    """
    opp = Opportunity(
        hr_number="HR010126120000",
        pay=PayBand(currency="INR", text="INR 9,00,000-15,00,000 / year", local_min=900000),
    )

    assert fit.usd_salary_string(opp) is None


def test_salary_bonus_is_earned_only_when_a_usd_band_exists(node_profile):
    node_profile.min_pay_usd_year = 50000

    with_band = fit.assess(opportunity(AGENTAI), node_profile)      # $60k-90k
    no_band = fit.assess(
        Opportunity(hr_number="HR010126120000", pay=PayBand(currency="INR", local_min=900000)),
        node_profile,
    )

    assert with_band["bonuses"]["salary"] == 5
    assert no_band.get("bonuses", {}).get("salary", 0) == 0


# --- the unbounded-experience trap ----------------------------------------


def test_unbounded_max_years_does_not_read_as_zero(node_profile):
    """Mavlers asks for 4+ years with no ceiling; a 5-year candidate is in range."""
    opp = opportunity(ANOMALY)

    assert opp.max_years_experience is None
    low, high = fit.experience_bounds(opp, node_profile.years_experience)

    assert (low, high) == (4.0, 5.0)
    assert fit.assess(opp, node_profile)["experience_match"]["score"] == 100


def test_an_unbounded_ceiling_never_falls_below_the_floor():
    opp = Opportunity(hr_number="HR1", min_years_experience=8.0, max_years_experience=None)

    assert fit.experience_bounds(opp, 2.0) == (8.0, 8.0)


def test_a_role_with_no_stated_band_scores_experience_neutrally(node_profile):
    opp = Opportunity(hr_number="HR1", skills=SkillSet(must_have=["Node.js"]))

    result = fit.assess(opp, node_profile)

    assert result["experience_match"]["score"] == 50
    assert any("no experience band" in flag for flag in result["flags"])


# --- the must-have trap ---------------------------------------------------


def test_zero_must_have_coverage_is_a_blocker_not_a_flag(node_profile):
    """The live regression: good-to-haves alone must not produce a strong match."""
    opp = Opportunity(
        hr_number="HR1",
        min_years_experience=3.0,
        max_years_experience=10.0,
        mode_of_work="Remote",
        skills=SkillSet(must_have=[".NET"], good_to_have=["AWS", "Azure"]),
    )

    result = fit.assess(opp, node_profile)

    assert result["overall_score"] >= 60          # jobcore still likes it
    assert any(blocker.startswith("must-have:") for blocker in result["blockers"])


def test_partial_must_have_coverage_is_a_flag_not_a_blocker(node_profile):
    opp = Opportunity(
        hr_number="HR1",
        skills=SkillSet(must_have=["Node.js", "Go", "Rust", "Elixir"]),
    )

    result = fit.assess(opp, node_profile)

    assert result["blockers"] == []
    assert any("must-have skills" in flag for flag in result["flags"])


def test_must_have_coverage_uses_the_shared_taxonomy(node_profile):
    """'reactjs' on the job and 'React' on the profile are the same skill."""
    opp = Opportunity(hr_number="HR1", skills=SkillSet(must_have=["reactjs"]))

    result = fit.assess(opp, node_profile)

    assert result["must_have"] == {"required": 1, "covered": 1, "missing": []}


def test_a_role_with_no_skills_listed_is_never_must_have_blocked(node_profile):
    opp = Opportunity(hr_number="HR1", min_years_experience=3.0, max_years_experience=8.0)

    assert fit.assess(opp, node_profile)["blockers"] == []


# --- blockers and flags ---------------------------------------------------


def test_an_impossible_notice_period_blocks(node_profile):
    node_profile.notice_period_days = 60

    result = fit.assess(opportunity(AGENTAI), node_profile)      # accepts 15 Days

    assert any(blocker.startswith("notice:") for blocker in result["blockers"])


def test_a_workable_notice_period_does_not_block(node_profile):
    node_profile.notice_period_days = 15

    result = fit.assess(opportunity(AGENTAI), node_profile)

    assert not any(blocker.startswith("notice:") for blocker in result["blockers"])


def test_an_unset_notice_period_is_flagged_and_blocks_nothing(node_profile):
    result = fit.assess(opportunity(AGENTAI), node_profile)

    assert any("notice unknown" in flag for flag in result["flags"])
    assert not any("notice" in blocker for blocker in result["blockers"])


def test_being_far_under_the_experience_floor_blocks(node_profile):
    """Databricks wants 15+ years; five is not a near miss."""
    result = fit.assess(opportunity(AGGREGATED), node_profile)

    assert any(blocker.startswith("experience:") for blocker in result["blockers"])


def test_being_one_year_under_the_floor_does_not_block(node_profile):
    opp = Opportunity(
        hr_number="HR1",
        min_years_experience=6.0,
        max_years_experience=9.0,
        skills=SkillSet(must_have=["Node.js"]),
    )

    assert fit.assess(opp, node_profile)["blockers"] == []


def test_an_avoided_company_blocks(node_profile):
    node_profile.avoid_companies = ["agentai"]

    result = fit.assess(opportunity(AGENTAI), node_profile)

    assert any("avoid list" in blocker for blocker in result["blockers"])


def test_a_non_preferred_mode_is_a_flag_not_a_blocker(node_profile):
    """Confido is Hybrid and a graphic-design role, so it is must-have blocked
    on skills; what matters here is that the MODE contributed no blocker."""
    node_profile.preferred_modes = ["Remote"]

    result = fit.assess(opportunity(CONFIDO), node_profile)

    assert any("mode Hybrid" in flag for flag in result["flags"])
    assert not any("mode" in blocker for blocker in result["blockers"])


def test_pay_below_your_floor_is_a_flag_not_a_blocker(node_profile):
    node_profile.min_pay_usd_year = 200000

    result = fit.assess(opportunity(AGENTAI), node_profile)

    assert result["blockers"] == []
    assert any("below your $200000 floor" in flag for flag in result["flags"])


def test_required_assessments_are_flagged(node_profile):
    result = fit.assess(opportunity(CONFIDO), node_profile)

    assert any("assessment(s) required" in flag for flag in result["flags"])


# --- rendering ------------------------------------------------------------


def test_a_confidential_budget_with_a_usd_estimate_shows_both():
    """Precisely marks the budget confidential but Uplers normalised it anyway.

    The estimate drives the salary bonus, so it must be visible beside it.
    """
    rendered = fit.render_pay(opportunity(PRECISELY))

    assert rendered.startswith("confidential (est. $")


def test_a_published_band_renders_in_thousands():
    assert fit.render_pay(opportunity(AGENTAI)) == "$60k-90k/yr"


def test_a_confidential_budget_with_no_numbers_says_only_confidential():
    opp = Opportunity(hr_number="HR1", pay=PayBand(confidential=True))

    assert fit.render_pay(opp) == "confidential"


def test_verdict_is_derived_from_jobcores_own_wording():
    assert fit.compact_verdict({"recommendation": "Strong match - apply confidently"}) == "strong"
    assert fit.compact_verdict({"recommendation": "Weak match - consider upskilling"}) == "weak"
    assert fit.compact_verdict({}) is None


# --- rows -----------------------------------------------------------------


def test_a_row_drops_every_empty_field(node_profile):
    opp = opportunity(AGENTAI)
    row = fit.to_row(opp, fit.assess(opp, node_profile)).model_dump()

    assert "blockers" not in row          # there are none
    assert "city" not in row              # Remote roles do not name an office
    assert row["hr_number"] == AGENTAI


def test_a_row_trims_the_posted_timestamp_to_a_date(node_profile):
    opp = opportunity(AGENTAI)

    row = fit.to_row(opp, fit.assess(opp, node_profile))

    assert row.posted_at == "2026-08-13"


def test_a_row_keeps_the_city_for_non_remote_roles(node_profile):
    opp = opportunity(CONFIDO)      # Hybrid
    opp.city = "Pune"

    assert fit.to_row(opp, fit.assess(opp, node_profile)).city == "Pune"


def test_a_row_carries_no_url_because_the_id_is_the_key(node_profile):
    """Repeating a 60-character URL on every row is the largest avoidable cost."""
    opp = opportunity(AGENTAI)

    assert "url" not in fit.to_row(opp, fit.assess(opp, node_profile)).model_dump()


# --- ranking --------------------------------------------------------------


def test_ranking_orders_by_score_and_excludes_blocked(node_profile):
    node_profile.notice_period_days = 60      # blocks every 15-day requisition
    population = [opportunity(h) for h in (AGENTAI, ANOMALY, CONFIDO)]

    ranked, blocked = fit.rank(population, node_profile)

    assert blocked >= 1
    assert all(assessment["blockers"] == [] for _, assessment in ranked)
    scores = [assessment["overall_score"] for _, assessment in ranked]
    assert scores == sorted(scores, reverse=True)


def test_ranking_can_keep_blocked_rows_with_their_reasons(node_profile):
    node_profile.notice_period_days = 60
    population = [opportunity(h) for h in (AGENTAI, ANOMALY, CONFIDO)]

    ranked, blocked = fit.rank(population, node_profile, exclude_blocked=False)

    assert len(ranked) == 3
    assert blocked >= 1
    assert any(assessment["blockers"] for _, assessment in ranked)


def test_must_have_coverage_breaks_a_score_tie(node_profile):
    """Equal scores are ordered by coverage; the score itself is untouched."""
    thin = Opportunity(
        hr_number="HR010126120001",
        min_years_experience=3.0,
        max_years_experience=8.0,
        skills=SkillSet(must_have=["Node.js", "Go", "Rust"]),
    )
    thick = Opportunity(
        hr_number="HR010126120002",
        min_years_experience=3.0,
        max_years_experience=8.0,
        skills=SkillSet(must_have=["Node.js"], good_to_have=["Go", "Rust"]),
    )

    ranked, _ = fit.rank([thin, thick], node_profile)

    assert ranked[0][1]["overall_score"] == ranked[1][1]["overall_score"]
    assert ranked[0][0].hr_number == thick.hr_number


def test_ranking_an_empty_cohort_is_empty_not_an_error(node_profile):
    assert fit.rank([], node_profile) == ([], 0)


# --- the stack preference -------------------------------------------------
#
# "Keep Python, but rank it lower." The tests below pin all three halves of
# that: it moves the ORDER, it does not move the SCORE, and it does not
# remove the role.


def _same_shape_role(hr_number, must_have):
    """Two roles identical in every scored dimension except their stack."""
    return Opportunity(
        hr_number=hr_number,
        min_years_experience=3.0,
        max_years_experience=8.0,
        city="Bangalore",
        mode_of_work="Remote",
        skills=SkillSet(must_have=must_have),
    )


PYTHON_ROLE = _same_shape_role("HR010126120010", ["Python", "PostgreSQL", "AWS"])
NODE_ROLE = _same_shape_role("HR010126120011", ["Node.js", "PostgreSQL", "AWS"])
BOTH_ROLE = _same_shape_role("HR010126120012", ["Python", "Node.js", "PostgreSQL"])
NEITHER_ROLE = _same_shape_role("HR010126120013", ["Go", "PostgreSQL", "AWS"])


def test_at_a_comparable_fit_the_node_role_outranks_the_python_one(node_profile):
    """The whole point. Both are scored identically by jobcore; the Node one
    is read first."""
    ranked, _ = fit.rank([PYTHON_ROLE, NODE_ROLE], node_profile)

    python_score = dict((o.hr_number, a) for o, a in ranked)[PYTHON_ROLE.hr_number]
    node_score = dict((o.hr_number, a) for o, a in ranked)[NODE_ROLE.hr_number]
    assert python_score["overall_score"] == node_score["overall_score"], (
        "the fixtures must be a genuine tie on score, or this proves nothing"
    )

    assert [o.hr_number for o in (pair[0] for pair in ranked)] == [
        NODE_ROLE.hr_number,
        PYTHON_ROLE.hr_number,
    ]


def test_the_python_role_keeps_its_real_score_and_stays_in_the_results(node_profile):
    """Ranked lower is not hidden, and not zeroed."""
    ranked, blocked = fit.rank([PYTHON_ROLE, NODE_ROLE], node_profile)

    assert blocked == 0
    assert len(ranked) == 2
    _, python = [pair for pair in ranked if pair[0] is PYTHON_ROLE][0]
    assert python["overall_score"] > 0
    assert python["rank_adjustment"] == -fit.PREFERENCE_TILT
    assert any("python-leaning" in flag for flag in python["flags"])


def test_a_role_wanting_both_stacks_is_not_demoted(node_profile):
    """Python ALONGSIDE Node is the path he is already on."""
    assert "rank_adjustment" not in fit.assess(BOTH_ROLE, node_profile)
    assert fit.preference_tilt({"python", "node.js"}) == 0


def test_a_role_wanting_neither_stack_is_left_alone(node_profile):
    assert "rank_adjustment" not in fit.assess(NEITHER_ROLE, node_profile)
    assert fit.preference_tilt({"golang", "postgresql"}) == 0


def test_the_tilt_cannot_outweigh_a_genuinely_better_match(node_profile):
    """It breaks near-ties. It does not overturn a real difference.

    Sized at 4, just under jobcore's smallest structural bonus (+5). A Python
    role that is five points better on the actual fit still ranks first.
    """
    assert fit.PREFERENCE_TILT < 5

    strong_python = _same_shape_role(
        "HR010126120014", ["Python", "PostgreSQL", "AWS", "Docker", "Redis"]
    )
    weak_node = _same_shape_role("HR010126120015", ["Node.js", "Kotlin", "Swift"])

    ranked, _ = fit.rank([weak_node, strong_python], node_profile)
    scores = {o.hr_number: a["overall_score"] for o, a in ranked}
    assert scores[strong_python.hr_number] - scores[weak_node.hr_number] > fit.PREFERENCE_TILT
    assert ranked[0][0].hr_number == strong_python.hr_number


def test_the_tilt_is_reported_separately_from_the_score(node_profile):
    """`overall_score` stays exactly jobcore's, so a 78 here still means what
    a 78 means on the Naukri server."""
    from jobcore import compute_fit_score

    assessment = fit.assess(PYTHON_ROLE, node_profile)
    low, high = fit.experience_bounds(PYTHON_ROLE, node_profile.years_experience)
    raw = compute_fit_score(
        job_skills=fit.parse_skills(PYTHON_ROLE.skills.must_have),
        profile_skills=fit.parse_skills(node_profile.skills),
        job_exp_str=fit.experience_text(low, high) or "",
        profile_exp=node_profile.years_experience,
        job_location=PYTHON_ROLE.city,
        profile_location=node_profile.location,
        job_work_mode=PYTHON_ROLE.mode_of_work,
        job_salary=None,
        profile_expected_ctc=node_profile.min_pay_usd_year,
        experience_min=low,
        experience_max=high,
    )
    assert assessment["overall_score"] == raw["overall_score"]
