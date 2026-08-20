"""insight.py - skill gap and company intel.

The load-bearing idea in the skill gap is `sole_blocker`: the count of
requisitions where a skill is the ONLY must-have you are missing. Raw demand
is already available from uplers_get_market_stats, and it answers the wrong
question - a skill named by forty roles you would fail anyway is worth less
than one gating six you would otherwise pass.

The load-bearing idea in company intel is refusing to guess. A fragment
matching several distinct end clients returns the candidates, not the biggest.
"""

from __future__ import annotations

import pytest

from uplers_server import insight
from uplers_server.models import Opportunity, PayBand, SkillSet
from uplers_server.profile import Profile
from uplers_server.shaping import to_opportunity

from conftest import AGENTAI, ALL_IDS, ANOMALY, CONFIDO, NATIVE_IDS, load_fixture


@pytest.fixture
def population():
    return [to_opportunity(load_fixture(hr_number)) for hr_number in NATIVE_IDS]


@pytest.fixture
def pairs():
    return [(load_fixture(hr_number), to_opportunity(load_fixture(hr_number))) for hr_number in ALL_IDS]


@pytest.fixture
def node_profile():
    return Profile(
        years_experience=5.0,
        skills=["Node.js", "TypeScript", "AWS", "Python", "React"],
    )


def job(hr_number, must, good=(), pay=None):
    return Opportunity(
        hr_number=hr_number,
        company="Client " + hr_number[-1],
        skills=SkillSet(must_have=list(must), good_to_have=list(good)),
        pay=PayBand(usd_year_max=pay) if pay else PayBand(),
    )


# --- sole blocker ---------------------------------------------------------


def test_sole_blocker_counts_only_roles_where_one_skill_is_the_last_gap():
    profile = Profile(years_experience=5.0, skills=["Python"])
    population = [
        job("HR1", ["Python", "Kubernetes"]),          # kubernetes is the only gap
        job("HR2", ["Python", "Kubernetes"]),          # same
        job("HR3", ["Python", "Kubernetes", "Rust"]),  # two gaps, unlocks nothing alone
    ]

    result = insight.skill_gap(population, profile, min_roles=1)
    rows = {row["skill"]: row for row in result["missing_skills"]}

    assert rows["kubernetes"]["sole_blocker"] == 2
    assert rows["kubernetes"]["roles"] == 3
    assert rows["rust"]["sole_blocker"] is None


def test_a_good_to_have_gap_never_counts_as_a_blocker():
    profile = Profile(years_experience=5.0, skills=["Python"])
    population = [job("HR1", ["Python"], good=["Kubernetes"])]

    result = insight.skill_gap(population, profile, min_roles=1)
    rows = {row["skill"]: row for row in result["missing_skills"]}

    assert rows["kubernetes"]["sole_blocker"] is None
    assert rows["kubernetes"]["roles"] == 1


def test_missing_skills_are_ordered_by_unlock_not_by_popularity():
    profile = Profile(years_experience=5.0, skills=["Python"])
    population = [
        job("HR1", ["Python", "Go"]),                     # go unlocks this one
        job("HR2", ["Rust", "Elixir", "Haskell"]),        # popular but unwinnable
        job("HR3", ["Rust", "Elixir", "Haskell"]),
        job("HR4", ["Rust", "Elixir", "Haskell"]),
    ]

    result = insight.skill_gap(population, profile, min_roles=1)

    # "Go" canonicalises to "golang" through the shared taxonomy.
    assert result["missing_skills"][0]["skill"] == "golang"
    assert result["missing_skills"][0]["roles"] < result["missing_skills"][1]["roles"]


def test_the_pay_delta_is_measured_against_the_cohort_median():
    profile = Profile(years_experience=5.0, skills=["Python"])
    population = [
        job("HR1", ["Python"], pay=40000),
        job("HR2", ["Python"], pay=40000),
        job("HR3", ["Kubernetes"], pay=90000),
        job("HR4", ["Kubernetes"], pay=90000),
    ]

    result = insight.skill_gap(population, profile, min_roles=1)
    rows = {row["skill"]: row for row in result["missing_skills"]}

    assert result["cohort_median_pay_usd"] == 65000      # median of the four
    assert rows["kubernetes"]["median_pay_usd"] == 90000
    assert rows["kubernetes"]["pay_delta_usd"] == 25000
    # The skill you already have sits on the other side of the median.
    held = {row["skill"]: row for row in result["your_skills_in_demand"]}
    assert held["python"]["pay_delta_usd"] == -25000


def test_skills_below_the_threshold_are_excluded():
    profile = Profile(years_experience=5.0, skills=["Python"])
    population = [job("HR1", ["Python", "Cobol"])]

    result = insight.skill_gap(population, profile, min_roles=2)

    assert result["missing_skills"] == []


def test_profile_skills_nobody_wants_are_reported_as_unused(population, node_profile):
    node_profile.skills = node_profile.skills + ["Fortran"]

    result = insight.skill_gap(population, node_profile, min_roles=1)

    assert "fortran" in result["unused_skills"]


def test_your_in_demand_skills_are_ranked_by_how_many_roles_want_them(population, node_profile):
    result = insight.skill_gap(population, node_profile, min_roles=1)

    counts = [row["roles"] for row in result["your_skills_in_demand"]]

    assert counts == sorted(counts, reverse=True)
    assert all(row["skill"] in insight.fit.parse_skills(node_profile.skills)
               for row in result["your_skills_in_demand"])


def test_coverage_is_a_real_fraction_of_the_boards_vocabulary(population, node_profile):
    result = insight.skill_gap(population, node_profile, min_roles=1)

    assert "of" in result["coverage"]
    have, total = result["coverage"].split(" of ")
    assert int(have) <= int(total.split()[0])


def test_an_empty_cohort_gives_an_empty_gap_not_a_crash(node_profile):
    result = insight.skill_gap([], node_profile)

    assert result["population"] == 0
    assert result["missing_skills"] == []
    assert result["cohort_median_pay_usd"] is None


# --- company intel --------------------------------------------------------


def test_an_exact_name_resolves_to_that_client(pairs):
    intel = insight.company_intel(pairs, "AgentAI")

    assert intel["company"] == "AgentAI"
    assert intel["open_requisitions"] == 1
    assert intel["industry"]


def test_matching_is_case_insensitive(pairs):
    assert insight.company_intel(pairs, "agentai")["company"] == "AgentAI"


def test_an_unknown_name_reports_zero_with_no_candidates(pairs):
    intel = insight.company_intel(pairs, "Nonesuch Ltd")

    assert intel["open_requisitions"] == 0
    assert intel["candidates"] == []


def test_a_fragment_hitting_several_clients_refuses_to_pick_one():
    """'Acme' must not silently resolve to whichever sorts first."""
    first = job("HR1", ["Python"])
    first.company = "Acme Health"
    second = job("HR2", ["Python"])
    second.company = "Acme Logistics"
    pairs = [({}, first), ({}, second)]

    intel = insight.company_intel(pairs, "Acme")

    assert intel["open_requisitions"] == 0
    assert intel["candidates"] == ["Acme Health", "Acme Logistics"]


def test_an_exact_name_wins_over_a_longer_sibling():
    exact = job("HR1", ["Python"])
    exact.company = "Acme"
    longer = job("HR2", ["Python"])
    longer.company = "Acme Logistics"
    pairs = [({}, exact), ({}, longer)]

    intel = insight.company_intel(pairs, "Acme")

    assert intel["company"] == "Acme"
    assert intel["open_requisitions"] == 1


def test_multiple_requisitions_aggregate_into_one_posture():
    one = job("HR010126120000", ["Python"], pay=40000)
    one.company = "Acme"
    one.mode_of_work = "Remote"
    one.joining_period = "15 Days"
    one.min_years_experience = 3.0
    two = job("HR020126120000", ["Go"], pay=80000)
    two.company = "Acme"
    two.mode_of_work = "Remote"
    two.joining_period = "30 Days"
    two.min_years_experience = 5.0
    pairs = [({}, one), ({}, two)]

    intel = insight.company_intel(pairs, "Acme")

    assert intel["open_requisitions"] == 2
    assert intel["pay_usd_year"] == "$40000-80000"
    assert intel["modes"] == {"Remote": 2}
    assert intel["joining_periods"] == {"15 Days": 1, "30 Days": 1}
    assert intel["median_min_yoe"] == 4.0


def test_a_profile_attaches_a_ranking(pairs, node_profile):
    intel = insight.company_intel(pairs, "AgentAI", node_profile)

    assert "_ranked" in intel
    assert intel["_ranked"][0][1]["overall_score"] > 0


def test_no_profile_means_no_ranking_key(pairs):
    assert "_ranked" not in insight.company_intel(pairs, "AgentAI")


def test_an_empty_query_matches_nothing(pairs):
    assert insight.company_intel(pairs, "")["open_requisitions"] == 0
