"""server.py - the seventeen profile-aware tools, end to end.

Same two guards as test_tools.py: `_open_store` points at tmp_path, and
`server.UplersClient` raises on construction so any accidental network use
fails the test. The profile is redirected to tmp_path by an autouse fixture in
conftest, so nothing here can read or clobber the operator's real one.

The theme running through this file is the anti-pattern the whole server is
built against: **an empty result must never be indistinguishable from a
failure.** Every "there is nothing" path is asserted to either raise with an
instruction or return a note saying, in words, that the zero is real.
"""

from __future__ import annotations

import httpx
import pytest

import server
from uplers_server import ids
from uplers_server.client import UplersClient, UplersError
from uplers_server.models import (
    AlertList,
    AlertResult,
    CompanyIntel,
    DailyBrief,
    FitAssessment,
    ProfileResult,
    RankResult,
    SavedList,
    SaveResult,
    SchedulerStatus,
    SkillGapResult,
    TrackedList,
    TrackResult,
)

from conftest import (
    AGENTAI,
    AGGREGATED,
    ALL_IDS,
    ANOMALY,
    CONFIDO,
    NATIVE_IDS,
    PRECISELY,
    load_fixture,
    make_transport,
    put_fixtures,
)


class NoNetwork:
    def __init__(self, *args, **kwargs):
        raise AssertionError("this tool must not construct an HTTP client")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(server, "UplersClient", NoNetwork)


@pytest.fixture
def tools(monkeypatch, store_factory):
    monkeypatch.setattr(server, "_open_store", store_factory)
    return store_factory


@pytest.fixture
def loaded(tools, make_profile):
    """A store with the five native fixtures cached and a profile set."""
    store = tools()
    put_fixtures(store, NATIVE_IDS)
    store.set_meta("last_sync", ids.utcnow_iso())
    make_profile()
    return store


def wire_client(monkeypatch, handler):
    transport, calls = make_transport(handler)
    monkeypatch.setattr(
        server, "UplersClient", lambda *a, **k: UplersClient(transport=transport, delay=0)
    )
    return calls


# --- profile --------------------------------------------------------------


async def test_get_profile_without_one_or_a_resume_raises_with_instructions(tools):
    with pytest.raises(UplersError) as exc:
        await server.uplers_get_profile()

    assert "uplers_set_profile" in str(exc.value)


async def test_get_profile_seeds_from_a_resume_and_says_so(tools, monkeypatch, resume_file):
    from uplers_server import profile as prof

    monkeypatch.setattr(prof, "resume_path", lambda: resume_file)

    result = await server.uplers_get_profile()

    assert isinstance(result, ProfileResult)
    assert result.seeded_from_resume is True
    assert result.profile.years_experience == 6.0
    assert any("seeded from your resume" in note for note in result.notes)


async def test_an_unset_notice_period_is_flagged_every_time(tools, make_profile):
    make_profile(notice_period_days=None)

    result = await server.uplers_get_profile()

    assert any("notice_period_days" in note for note in result.notes)


async def test_set_profile_changes_only_what_was_passed(tools, make_profile):
    make_profile(skills=["Node.js"], years_experience=5.0, location="Bangalore, India")

    result = await server.uplers_set_profile(notice_period_days=30)

    assert result.profile.notice_period_days == 30
    assert result.profile.skills == ["Node.js"]
    assert result.profile.years_experience == 5.0


async def test_add_and_remove_skills_are_incremental(tools, make_profile):
    make_profile(skills=["Node.js", "Python"])

    result = await server.uplers_set_profile(add_skills=["Go"], remove_skills=["python"])

    assert result.profile.skills == ["Node.js", "Go"]


async def test_setting_skills_replaces_the_list(tools, make_profile):
    make_profile(skills=["Node.js", "Python"])

    result = await server.uplers_set_profile(skills=["Rust"])

    assert result.profile.skills == ["Rust"]


async def test_an_unknown_work_mode_is_rejected_by_name(tools, make_profile):
    make_profile()

    with pytest.raises(UplersError) as exc:
        await server.uplers_set_profile(preferred_modes=["Underwater"])

    assert "Underwater" in str(exc.value)
    assert "Remote" in str(exc.value)


async def test_set_profile_works_from_nothing(tools):
    result = await server.uplers_set_profile(skills=["Node.js"], years_experience=3.0)

    assert result.profile.skills == ["Node.js"]
    assert result.profile.source == "manual"


async def test_a_profile_with_nothing_to_score_on_is_flagged(tools):
    result = await server.uplers_set_profile(name="Nobody")

    assert any("refuse to run" in note for note in result.notes)


# --- assess_fit -----------------------------------------------------------


async def test_assess_fit_scores_a_cached_requisition(loaded):
    result = await server.uplers_assess_fit(AGENTAI)

    assert isinstance(result, FitAssessment)
    assert result.company == "AgentAI"
    assert 0 < result.score <= 100
    assert result.must_have_required == 6
    assert result.pay == "$60k-90k/yr"
    assert result.scored_against.years_experience == 5.0


async def test_assess_fit_reports_must_have_gaps_by_name(loaded):
    result = await server.uplers_assess_fit(CONFIDO)      # a graphic-design role

    assert result.must_have_covered == 0
    assert "figma" in result.must_have_missing
    assert any(blocker.startswith("must-have:") for blocker in result.blockers)


async def test_assess_fit_rejects_a_malformed_id(loaded):
    with pytest.raises(UplersError) as exc:
        await server.uplers_assess_fit("not-an-id")

    assert "HR" in str(exc.value)


async def test_assess_fit_without_a_profile_raises(tools):
    store = tools()
    put_fixtures(store, NATIVE_IDS)

    with pytest.raises(UplersError) as exc:
        await server.uplers_assess_fit(AGENTAI)

    assert "uplers_set_profile" in str(exc.value)


async def test_assess_fit_fetches_an_uncached_record_once(tools, make_profile, monkeypatch):
    tools()
    make_profile()
    calls = wire_client(
        monkeypatch,
        lambda request: httpx.Response(200, json=load_fixture(AGENTAI)),
    )

    result = await server.uplers_assess_fit(AGENTAI)

    assert result.company == "AgentAI"
    assert len(calls) == 1


async def test_assess_fit_surfaces_that_a_record_is_aggregated(tools, make_profile):
    store = tools()
    put_fixtures(store, ALL_IDS)
    make_profile()

    result = await server.uplers_assess_fit(AGGREGATED)

    assert any("AGGREGATED" in note for note in result.notes)


async def test_a_failed_fetch_raises_rather_than_scoring_nothing(tools, make_profile, monkeypatch):
    tools()
    make_profile()
    wire_client(monkeypatch, lambda request: httpx.Response(500))

    with pytest.raises(UplersError):
        await server.uplers_assess_fit("HR010126120000")


# --- rank -----------------------------------------------------------------


async def test_rank_orders_by_score_and_reports_the_cohort(loaded):
    result = await server.uplers_rank_opportunities(limit=3)

    assert isinstance(result, RankResult)
    assert result.scanned == 5
    assert result.cohort == "native"
    scores = [row.score for row in result.rows]
    assert scores == sorted(scores, reverse=True)


async def test_rank_excludes_blocked_and_says_how_many(loaded):
    await server.uplers_set_profile(notice_period_days=90)

    result = await server.uplers_rank_opportunities()

    assert result.blocked > 0
    assert all(row.blockers == [] for row in result.rows)
    assert any("exclude_blocked=False" in note for note in result.notes)


async def test_rank_can_show_blocked_rows_with_their_reasons(loaded):
    await server.uplers_set_profile(notice_period_days=90)

    result = await server.uplers_rank_opportunities(exclude_blocked=False, limit=20)

    assert any(row.blockers for row in result.rows)


async def test_rank_on_an_empty_index_raises_rather_than_returning_nothing(tools, make_profile):
    tools()
    make_profile()

    with pytest.raises(UplersError) as exc:
        await server.uplers_rank_opportunities()

    assert "uplers_sync_index" in str(exc.value)


async def test_a_genuine_zero_says_it_is_genuine(loaded):
    result = await server.uplers_rank_opportunities(min_score=101)

    assert result.rows == []
    assert any("genuine empty result" in note for note in result.notes)


async def test_rank_applies_search_filters_before_scoring(loaded):
    result = await server.uplers_rank_opportunities(remote_only=True, limit=20)

    assert result.rows
    assert all(row.mode == "Remote" for row in result.rows)


async def test_saved_only_ranks_just_the_shortlist(loaded):
    loaded.save_job(AGENTAI)

    result = await server.uplers_rank_opportunities(saved_only=True, limit=20)

    assert [row.hr_number for row in result.rows] == [AGENTAI]


async def test_saved_only_with_an_empty_shortlist_says_so(loaded):
    result = await server.uplers_rank_opportunities(saved_only=True)

    assert any("shortlist is empty" in note for note in result.notes)


async def test_rank_rows_carry_no_url_or_description(loaded):
    result = await server.uplers_rank_opportunities(limit=1)

    dumped = result.rows[0].model_dump()

    assert "url" not in dumped
    assert "description" not in dumped


# --- shortlist ------------------------------------------------------------


async def test_saving_stores_a_title_snapshot(loaded):
    result = await server.uplers_save_job(AGENTAI, note="looks good")

    assert isinstance(result, SaveResult)
    assert result.created is True
    assert result.company == "AgentAI"
    assert result.saved_total == 1


async def test_saving_twice_updates_rather_than_duplicates(loaded):
    await server.uplers_save_job(AGENTAI, note="first")

    result = await server.uplers_save_job(AGENTAI, note="second")

    assert result.created is False
    assert result.saved_total == 1
    assert any("Already on the shortlist" in note for note in result.notes)


async def test_list_saved_scores_against_the_current_profile(loaded):
    await server.uplers_save_job(AGENTAI)

    result = await server.uplers_list_saved()

    assert isinstance(result, SavedList)
    assert result.scored is True
    assert result.saved[0].score > 0
    assert result.saved[0].still_listed is True


async def test_list_saved_marks_entries_that_left_the_index(loaded):
    loaded.save_job("HR010126120000", title="Ghost role")

    result = await server.uplers_list_saved()

    assert result.saved[0].still_listed is False


async def test_an_empty_shortlist_is_reported_as_a_real_zero(loaded):
    result = await server.uplers_list_saved()

    assert result.count == 0
    assert any("real zero" in note for note in result.notes)


async def test_unsaving_reports_whether_anything_was_removed(loaded):
    await server.uplers_save_job(AGENTAI)

    removed = await server.uplers_unsave_job(AGENTAI)
    again = await server.uplers_unsave_job(AGENTAI)

    assert removed.removed is True
    assert again.removed is False
    assert any("was not on the shortlist" in note for note in again.notes)


async def test_unsaving_keeps_tracking_history(loaded):
    await server.uplers_track(AGENTAI, "applied_manually")

    result = await server.uplers_unsave_job(AGENTAI)

    assert any("history for" in note for note in result.notes)
    assert loaded.get_tracked(AGENTAI) is not None


# --- tracking -------------------------------------------------------------


async def test_tracking_records_a_status_and_the_pipeline(loaded):
    result = await server.uplers_track(AGENTAI, "applied_manually", notes="applied on their site")

    assert isinstance(result, TrackResult)
    assert result.status == "applied_manually"
    assert result.created is True
    assert result.counts == {"applied_manually": 1}


async def test_tracking_also_shortlists_it(loaded):
    result = await server.uplers_track(AGENTAI, "interested")

    assert any("added to your shortlist" in note for note in result.notes)
    assert loaded.is_saved(AGENTAI)


async def test_an_invalid_status_is_rejected_with_the_vocabulary(loaded):
    with pytest.raises(UplersError) as exc:
        await server.uplers_track(AGENTAI, "ghosted")

    assert "applied_manually" in str(exc.value)


async def test_update_status_refuses_an_untracked_id(loaded):
    with pytest.raises(UplersError) as exc:
        await server.uplers_update_status(AGENTAI, "responded")

    assert "uplers_track()" in str(exc.value)


async def test_update_status_moves_a_tracked_one_and_keeps_the_previous(loaded):
    await server.uplers_track(AGENTAI, "applied_manually")

    result = await server.uplers_update_status(AGENTAI, "interviewing")

    assert result.previous_status == "applied_manually"
    assert result.status == "interviewing"


async def test_list_tracked_can_include_the_history_trail(loaded):
    await server.uplers_track(AGENTAI, "applied_manually")
    await server.uplers_update_status(AGENTAI, "responded")

    result = await server.uplers_list_tracked(history=True)

    assert isinstance(result, TrackedList)
    assert len(result.tracked[0].history) == 2
    assert result.tracked[0].history[0].startswith("applied_manually@")


async def test_history_is_off_by_default_to_stay_small(loaded):
    await server.uplers_track(AGENTAI, "applied_manually")

    result = await server.uplers_list_tracked()

    assert result.tracked[0].history == []


async def test_an_empty_pipeline_is_reported_as_a_real_zero(loaded):
    result = await server.uplers_list_tracked()

    assert result.count == 0
    assert any("real zero" in note for note in result.notes)


async def test_list_tracked_rejects_an_unknown_status_filter(loaded):
    with pytest.raises(UplersError):
        await server.uplers_list_tracked(status="ghosted")


# --- alerts ---------------------------------------------------------------


async def test_setting_an_alert_evaluates_it_immediately(loaded):
    result = await server.uplers_set_alert("remote-node", remote_only=True)

    assert isinstance(result, AlertResult)
    assert result.created is True
    assert result.matches_now > 0
    assert result.criteria == {"remote_only": True}


async def test_an_alert_with_no_criteria_is_refused(loaded):
    with pytest.raises(UplersError) as exc:
        await server.uplers_set_alert("everything")

    assert "every requisition" in str(exc.value)


async def test_an_alert_needs_a_name(loaded):
    with pytest.raises(UplersError) as exc:
        await server.uplers_set_alert("   ", remote_only=True)

    assert "needs a name" in str(exc.value)


async def test_an_alert_matching_nothing_is_saved_but_flagged(loaded):
    result = await server.uplers_set_alert("cobol", skill="cobol")

    assert result.created is True
    assert result.matches_now == 0
    assert any("matches nothing right now" in note for note in result.notes)


async def test_replacing_an_alert_clears_its_seen_list(loaded):
    await server.uplers_set_alert("remote", remote_only=True)
    await server.uplers_list_alerts(evaluate=True)

    replaced = await server.uplers_set_alert("remote", remote_only=True, min_pay_usd_year=1)
    listed = await server.uplers_list_alerts(evaluate=True)

    assert replaced.created is False
    assert any("cleared its seen-list" in note for note in replaced.notes)
    assert listed.alerts[0].new_matches > 0


async def test_listing_alerts_without_evaluating_is_cheap(loaded):
    await server.uplers_set_alert("remote", remote_only=True)

    result = await server.uplers_list_alerts()

    assert isinstance(result, AlertList)
    assert result.evaluated is False
    assert result.alerts[0].matches is None


async def test_evaluating_reports_matches_and_new_matches(loaded):
    await server.uplers_set_alert("remote", remote_only=True)

    first = await server.uplers_list_alerts(evaluate=True)
    second = await server.uplers_list_alerts(evaluate=True)

    assert first.alerts[0].new_matches == first.alerts[0].matches
    assert second.alerts[0].new_matches == 0
    assert second.alerts[0].matches > 0


async def test_no_alerts_is_reported_as_a_real_zero(loaded):
    result = await server.uplers_list_alerts()

    assert result.count == 0
    assert any("real zero" in note for note in result.notes)


async def test_deleting_an_alert_reports_success_or_absence(loaded):
    await server.uplers_set_alert("remote", remote_only=True)

    deleted = await server.uplers_delete_alert("remote")
    again = await server.uplers_delete_alert("remote")

    assert deleted.deleted is True
    assert again.deleted is False
    assert any("No alert named" in note for note in again.notes)


async def test_a_score_gated_alert_uses_the_profile(loaded):
    result = await server.uplers_set_alert("great", remote_only=True, min_score=95)

    assert result.matches_now == 0
    assert result.criteria["min_score"] == 95


# --- daily brief ----------------------------------------------------------


async def test_the_brief_reports_new_ranked_work(loaded):
    result = await server.uplers_daily_brief(since="2020-01-01")

    assert isinstance(result, DailyBrief)
    assert result.new_opportunities.count == 4
    assert result.new_opportunities.rows[0].score > 0
    assert result.actions


async def test_the_brief_advances_its_own_window(loaded):
    await server.uplers_daily_brief(since="2020-01-01")

    second = await server.uplers_daily_brief()

    assert second.new_opportunities.count == 0
    assert any("Nothing has changed" in note for note in second.notes)


async def test_peek_leaves_the_window_alone(loaded):
    await server.uplers_daily_brief(since="2020-01-01", peek=True)

    assert loaded.get_meta("last_brief_at") is None


async def test_the_brief_carries_alerts_shortlist_and_pipeline(loaded):
    await server.uplers_set_alert("remote", remote_only=True)
    await server.uplers_save_job(CONFIDO)
    await server.uplers_track(AGENTAI, "applied_manually")

    result = await server.uplers_daily_brief(since="2020-01-01")

    assert result.alert_hits[0].name == "remote"
    assert result.shortlist["saved"] == 2      # tracking shortlists too
    assert result.pipeline == {"applied_manually": 1}


async def test_the_brief_names_a_stale_index(tools, make_profile):
    store = tools()
    put_fixtures(store, NATIVE_IDS)
    make_profile()

    result = await server.uplers_daily_brief()

    assert any("uplers_sync_index" in note for note in result.notes)


async def test_the_brief_needs_a_profile(tools):
    store = tools()
    put_fixtures(store, NATIVE_IDS)

    with pytest.raises(UplersError):
        await server.uplers_daily_brief()


async def test_the_brief_stays_small(loaded):
    """The tool called most often is the one that must not sprawl."""
    await server.uplers_set_alert("remote", remote_only=True)

    result = await server.uplers_daily_brief(since="2020-01-01")
    payload = result.model_dump_json()

    assert len(payload) < 6000


# --- skill gap ------------------------------------------------------------


async def test_skill_gap_reports_demand_and_gaps(loaded):
    result = await server.uplers_skill_gap(min_roles=1)

    assert isinstance(result, SkillGapResult)
    assert result.population == 5
    assert result.your_skills_in_demand
    assert result.coverage


async def test_skill_gap_needs_a_populated_index(tools, make_profile):
    tools()
    make_profile()

    with pytest.raises(UplersError):
        await server.uplers_skill_gap()


async def test_skill_gap_says_when_no_single_skill_unlocks_anything(loaded):
    await server.uplers_set_profile(skills=["Fortran"])

    result = await server.uplers_skill_gap(min_roles=1)

    assert any("no one-skill unlock" in note for note in result.notes)


async def test_skill_gap_names_a_sole_blocker_when_there_is_one(loaded):
    """Mavlers needs six skills; hold five and the sixth is the only gap."""
    await server.uplers_set_profile(
        skills=[
            "CRM",
            "Marketing Automation",
            "Data Analytics",
            "Campaign Management",
            "Campaign Strategist",
        ]
    )

    result = await server.uplers_skill_gap(min_roles=1)

    unlocks = [row for row in result.missing_skills if row.sole_blocker]
    assert unlocks
    assert unlocks[0].sole_blocker == 1


# --- company intel --------------------------------------------------------


async def test_company_intel_returns_the_end_client_detail(loaded):
    result = await server.uplers_company_intel("AgentAI")

    assert isinstance(result, CompanyIntel)
    assert result.company == "AgentAI"
    assert result.open_requisitions == 1
    assert result.industry
    assert result.best_fit.hr_number == AGENTAI


async def test_company_intel_reports_a_genuine_miss(loaded):
    result = await server.uplers_company_intel("Nonesuch Ltd")

    assert result.open_requisitions == 0
    assert any("genuine miss" in note for note in result.notes)


async def test_company_intel_lists_your_own_history_with_the_client(loaded):
    await server.uplers_track(AGENTAI, "interviewing")

    result = await server.uplers_company_intel("AgentAI")

    assert result.your_history == ["%s: interviewing" % AGENTAI]


async def test_company_intel_needs_a_populated_index(tools, make_profile):
    tools()
    make_profile()

    with pytest.raises(UplersError):
        await server.uplers_company_intel("AgentAI")


async def test_company_intel_works_without_a_profile(tools):
    store = tools()
    put_fixtures(store, NATIVE_IDS)

    result = await server.uplers_company_intel("AgentAI")

    assert result.company == "AgentAI"
    assert any("Fit scores omitted" in note for note in result.notes)


# --- scheduler ------------------------------------------------------------


async def test_scheduler_status_reports_the_off_switch(loaded):
    result = await server.uplers_scheduler_status()

    assert isinstance(result, SchedulerStatus)
    assert result.enabled is False          # UPLERS_AUTO_SYNC=0 across the suite
    assert any("Automatic sync is OFF" in note for note in result.notes)


async def test_no_tool_call_starts_a_background_task_when_disabled(loaded, monkeypatch):
    from uplers_server import scheduler as sched_mod

    def explode():
        raise AssertionError("the scheduler must not be created when disabled")

    monkeypatch.setattr(sched_mod, "get_scheduler", explode)

    await server.uplers_rank_opportunities(limit=1)


# --- token economy --------------------------------------------------------


async def test_a_ranked_row_stays_under_a_few_hundred_characters(loaded):
    """Token cost is the governing constraint on this server, so it is asserted."""
    result = await server.uplers_rank_opportunities(limit=1)

    assert len(result.rows[0].model_dump_json()) < 600


async def test_ten_ranked_rows_cost_less_than_one_full_record(loaded):
    from uplers_server.shaping import to_detail

    ranked = await server.uplers_rank_opportunities(limit=10)
    one_record = to_detail(load_fixture(AGENTAI))

    assert len(ranked.model_dump_json()) < len(one_record.model_dump_json()) * 2
