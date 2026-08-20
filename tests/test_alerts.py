"""alerts.py - stored criteria evaluated against the local cohort.

The interesting behaviour is refusal. An alert that quietly matches everything
because a field name was misspelled is worse than no alert: it fires every
morning, is ignored within a week, and hides the thing it was meant to catch.
So an unknown key is an error and an empty criteria set is an error.
"""

from __future__ import annotations

import pytest

from uplers_server import alerts
from uplers_server.profile import Profile
from uplers_server.shaping import to_opportunity

from conftest import AGENTAI, ANOMALY, CONFIDO, GOFORMA, NATIVE_IDS, PRECISELY, load_fixture


@pytest.fixture
def population():
    return [to_opportunity(load_fixture(hr_number)) for hr_number in NATIVE_IDS]


@pytest.fixture
def node_profile():
    return Profile(
        years_experience=5.0,
        location="Bangalore, India",
        skills=["Node.js", "TypeScript", "AWS", "Python", "React"],
    )


# --- criteria validation --------------------------------------------------


def test_an_unknown_key_is_rejected_by_name():
    with pytest.raises(alerts.AlertError) as exc:
        alerts.normalise_criteria({"min_salary": 10})

    assert "min_salary" in str(exc.value)
    assert "min_pay_usd_year" in str(exc.value)


def test_criteria_that_would_match_the_whole_board_are_rejected():
    with pytest.raises(alerts.AlertError) as exc:
        alerts.normalise_criteria({"skill": None, "remote_only": False})

    assert "every requisition" in str(exc.value)


def test_empty_values_are_dropped_but_real_ones_kept():
    cleaned = alerts.normalise_criteria(
        {"skill": "node", "title": "", "company": None, "remote_only": True}
    )

    assert cleaned == {"skill": "node", "remote_only": True}


def test_zero_is_a_real_value_not_an_empty_one():
    assert alerts.normalise_criteria({"min_notice_days": 0}) == {"min_notice_days": 0}


def test_criteria_split_into_search_filters_and_score_gates():
    filters, scoring = alerts.split_criteria(
        {"skill": "node", "min_score": 70, "exclude_blocked": True}
    )

    assert filters == {"skill": "node"}
    assert scoring == {"min_score": 70, "exclude_blocked": True}


# --- evaluation -----------------------------------------------------------


def test_a_filter_only_alert_needs_no_profile(population):
    matches = alerts.evaluate(population, {"remote_only": True})

    assert matches
    assert all(assessment is None for _, assessment in matches)
    assert all(opp.mode_of_work == "Remote" for opp, _ in matches)


def test_a_score_gate_filters_and_orders_by_score(population, node_profile):
    matches = alerts.evaluate(population, {"remote_only": True, "min_score": 50}, node_profile)

    scores = [assessment["overall_score"] for _, assessment in matches]
    assert scores == sorted(scores, reverse=True)
    assert all(score >= 50 for score in scores)


def test_exclude_blocked_drops_hard_incompatibilities(population, node_profile):
    node_profile.notice_period_days = 60

    kept = alerts.evaluate(population, {"remote_only": True, "exclude_blocked": True}, node_profile)
    all_of_them = alerts.evaluate(population, {"remote_only": True}, node_profile)

    assert len(kept) < len(all_of_them)
    assert all(assessment["blockers"] == [] for _, assessment in kept)


def test_a_matchless_alert_returns_an_empty_list_not_an_error(population):
    assert alerts.evaluate(population, {"skill": "cobol"}) == []


def test_no_profile_means_no_scoring_pass_at_all(population, monkeypatch):
    """A filter-only alert is free: ranking every record is skipped entirely."""
    from uplers_server import fit

    def explode(*args, **kwargs):
        raise AssertionError("assess() must not run without a profile")

    monkeypatch.setattr(fit, "assess", explode)

    assert alerts.evaluate(population, {"skill": "python"})


def test_a_score_gate_without_a_profile_raises_rather_than_matching_everything(population):
    """Silently dropping the gate would make the alert fire on the whole board."""
    with pytest.raises(alerts.AlertError) as exc:
        alerts.evaluate(population, {"skill": "python", "min_score": 70})

    assert "uplers_set_profile" in str(exc.value)


def test_a_profile_scores_every_hit_even_with_no_gate(population, node_profile):
    matches = alerts.evaluate(population, {"remote_only": True}, node_profile)

    assert matches
    assert all(assessment is not None for _, assessment in matches)


def test_describe_renders_criteria_as_one_short_line():
    assert alerts.describe({"skill": "node", "remote_only": True}) == "remote_only=True, skill=node"
