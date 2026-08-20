"""brief.py - the assembly behind uplers_daily_brief.

Two properties carry the whole design, and both are about NOT repeating
yourself:

  * the window advances, so calling it twice in a morning gives an almost
    empty second answer rather than the same news again;
  * an alert reports a requisition once in its life.

The third is that an empty brief must be legible as "nothing changed" and
never as "the lookup failed" - so a stale index is called out by name.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from uplers_server import brief, config, ids
from uplers_server.profile import Profile
from uplers_server.shaping import to_opportunity

from conftest import AGENTAI, ANOMALY, CONFIDO, NATIVE_IDS, load_fixture, put_fixtures


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


@pytest.fixture
def loaded(store):
    """A store holding the five native fixtures and a fresh sync stamp."""
    put_fixtures(store, NATIVE_IDS)
    store.set_meta("last_sync", ids.utcnow_iso())
    return store


def ago(**kwargs):
    return (datetime.fromisoformat(ids.utcnow_iso()) - timedelta(**kwargs)).isoformat()


# --- the window -----------------------------------------------------------


def test_the_first_brief_looks_back_a_week(store):
    start, how = brief.window_start(store)

    assert how == "first_brief_7d"
    assert start < ids.utcnow_iso()


def test_a_later_brief_starts_where_the_last_one_ended(store):
    store.set_meta(brief.BRIEF_META_KEY, "2026-08-01T00:00:00")

    assert brief.window_start(store) == ("2026-08-01T00:00:00", "last_brief")


def test_an_explicit_date_is_expanded_to_a_timestamp(store):
    assert brief.window_start(store, since="2026-08-01") == ("2026-08-01T00:00:00", "explicit")


def test_building_advances_the_window(loaded, node_profile, population):
    brief.build(loaded, node_profile, population)

    assert loaded.get_meta(brief.BRIEF_META_KEY) is not None


def test_peek_does_not_advance_the_window(loaded, node_profile, population):
    brief.build(loaded, node_profile, population, peek=True)

    assert loaded.get_meta(brief.BRIEF_META_KEY) is None


def test_the_second_brief_of_a_day_reports_nothing_new(loaded, node_profile, population):
    brief.build(loaded, node_profile, population)

    second = brief.build(loaded, node_profile, population)

    assert second["new_opportunities"]["count"] == 0
    assert any("Nothing has changed" in note for note in second["notes"])


# --- index health ---------------------------------------------------------


def test_a_stale_index_is_called_out_by_name(store, node_profile, population):
    put_fixtures(store, NATIVE_IDS)
    store.set_meta("last_sync", ago(hours=config.INDEX_STALE_HOURS + 5))

    result = brief.build(store, node_profile, population)

    assert any("uplers_sync_index" in note for note in result["notes"])


def test_a_fresh_index_produces_no_staleness_warning(loaded, node_profile, population):
    result = brief.build(loaded, node_profile, population)

    assert not any("older than" in note for note in result["notes"])


def test_unfetched_native_ids_are_surfaced(loaded, node_profile, population):
    loaded.union_ids({"HR010126120000": None})      # known id, no record

    result = brief.build(loaded, node_profile, population)

    assert result["index"]["unfetched_native_ids"] == 1


def test_a_store_that_never_synced_reads_as_stale(store, node_profile, population):
    put_fixtures(store, NATIVE_IDS)

    result = brief.build(store, node_profile, population)

    assert any("never" in note for note in result["notes"])


# --- sections -------------------------------------------------------------


def test_new_requisitions_are_ranked_and_capped(loaded, node_profile, population):
    result = brief.build(loaded, node_profile, population, since="2020-01-01", limit=2)

    # Four of the five: the 13-digit anomaly id decodes to no date, so it can
    # never answer a "what is new since" question. That is by design.
    assert result["new_opportunities"]["count"] == 4
    assert len(result["new_opportunities"]["rows"]) <= 2
    scores = [row.score for row in result["new_opportunities"]["rows"]]
    assert scores == sorted(scores, reverse=True)


def test_blocked_new_requisitions_are_counted_not_shown(loaded, node_profile, population):
    node_profile.notice_period_days = 90      # blocks nearly everything

    result = brief.build(loaded, node_profile, population, since="2020-01-01")

    assert "blocker" in (result["new_opportunities"]["note"] or "")
    assert all(row.blockers == [] for row in result["new_opportunities"]["rows"])


def test_an_alert_fires_once_and_then_stays_quiet(loaded, node_profile, population):
    loaded.put_alert("remote", {"remote_only": True})

    first = brief.build(loaded, node_profile, population, since="2020-01-01")
    second = brief.build(loaded, node_profile, population, since="2020-01-01")

    assert first["alert_hits"][0]["new_matches"] > 0
    assert second["alert_hits"] == []


def test_peek_does_not_consume_alert_hits(loaded, node_profile, population):
    loaded.put_alert("remote", {"remote_only": True})

    brief.build(loaded, node_profile, population, since="2020-01-01", peek=True)
    after = brief.build(loaded, node_profile, population, since="2020-01-01")

    assert after["alert_hits"][0]["new_matches"] > 0


def test_a_broken_alert_does_not_kill_the_brief(loaded, node_profile, population):
    loaded.conn.execute(
        "INSERT INTO alerts (name, criteria, created_at, active) VALUES (?, ?, ?, 1)",
        ("bad", '{"nonsense_key": 1}', ids.utcnow_iso()),
    )
    loaded.conn.commit()

    result = brief.build(loaded, node_profile, population, since="2020-01-01")

    assert any("could not be evaluated" in note for note in result["notes"])
    assert result["new_opportunities"]["count"] > 0


def test_saved_but_untracked_roles_are_surfaced(loaded, node_profile, population):
    loaded.save_job(AGENTAI, title="AI Full Stack Engineer")

    result = brief.build(loaded, node_profile, population)

    assert result["shortlist"]["saved"] == 1
    assert result["shortlist"]["not_yet_actioned"] == 1
    assert any("no tracked status" in action for action in result["actions"])


def test_a_tracked_saved_role_is_not_listed_as_unactioned(loaded, node_profile, population):
    loaded.save_job(AGENTAI)
    loaded.track(AGENTAI, "applied_manually")

    result = brief.build(loaded, node_profile, population)

    assert "not_yet_actioned" not in result["shortlist"]


def test_the_pipeline_counts_by_status(loaded, node_profile, population):
    loaded.track(AGENTAI, "applied_manually")
    loaded.track(CONFIDO, "interviewing")

    result = brief.build(loaded, node_profile, population)

    assert result["pipeline"] == {"applied_manually": 1, "interviewing": 1}


# --- follow-up ------------------------------------------------------------


def test_a_quiet_application_becomes_a_follow_up(loaded, node_profile, population):
    loaded.track(AGENTAI, "applied_manually")
    loaded.conn.execute(
        "UPDATE tracked SET updated_at = ? WHERE hr_number = ?", (ago(days=20), AGENTAI)
    )
    loaded.conn.commit()

    result = brief.build(loaded, node_profile, population)

    assert result["follow_up"][0]["hr_number"] == AGENTAI
    assert "20 days" in result["follow_up"][0]["flags"][0]


def test_a_recent_application_is_not_a_follow_up(loaded, node_profile, population):
    loaded.track(AGENTAI, "applied_manually")

    assert brief.build(loaded, node_profile, population)["follow_up"] == []


def test_a_closed_application_is_never_a_follow_up(loaded, node_profile, population):
    loaded.track(AGENTAI, "rejected")
    loaded.conn.execute(
        "UPDATE tracked SET updated_at = ? WHERE hr_number = ?", (ago(days=90), AGENTAI)
    )
    loaded.conn.commit()

    assert brief.follow_up_due(loaded) == []


def test_follow_ups_are_ordered_oldest_first(loaded):
    loaded.track("HR1", "applied_manually")
    loaded.track("HR2", "applied_manually")
    loaded.conn.execute("UPDATE tracked SET updated_at = ? WHERE hr_number = 'HR1'", (ago(days=10),))
    loaded.conn.execute("UPDATE tracked SET updated_at = ? WHERE hr_number = 'HR2'", (ago(days=40),))
    loaded.conn.commit()

    assert [row["hr_number"] for row in brief.follow_up_due(loaded)] == ["HR2", "HR1"]


# --- new_since ------------------------------------------------------------


def test_an_id_that_decodes_to_no_date_is_never_new(population):
    """HR0191124125506 is 13 digits and carries no timestamp to compare."""
    fresh = brief.new_since(population, "2000-01-01T00:00:00")

    assert ANOMALY not in [opp.hr_number for opp in fresh]
    assert len(fresh) == len(population) - 1


def test_new_since_uses_the_id_derived_timestamp(population):
    fresh = brief.new_since(population, "2026-08-01T00:00:00")

    assert [opp.hr_number for opp in fresh] == [AGENTAI]      # created 2026-08-13


def test_new_since_orders_newest_first(population):
    fresh = brief.new_since(population, "2000-01-01T00:00:00")

    stamps = [opp.posted_at for opp in fresh]
    assert stamps == sorted(stamps, reverse=True)


def test_a_future_window_is_genuinely_empty(population):
    assert brief.new_since(population, "2099-01-01T00:00:00") == []
