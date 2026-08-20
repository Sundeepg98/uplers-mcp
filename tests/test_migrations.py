"""migrations.py and the tier-2 half of store.py.

The migration tests exist because this server already holds data on the
operator's machine: an ~11 MB id store built over real sync runs. A schema
change that starts from a blank database in every test proves nothing about
the one that matters, so the central test here builds a PRE-MIGRATION database
by hand - the exact three tables and no version row - and upgrades it.
"""

from __future__ import annotations

import sqlite3

import pytest

from uplers_server import migrations
from uplers_server.store import SCHEMA, Store

TIER2_TABLES = {"saved", "tracked", "tracked_events", "alerts", "alert_hits", "leases"}


def table_names(conn) -> set:
    return {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


# --- versioning -----------------------------------------------------------


def test_a_fresh_store_lands_on_the_latest_version(store):
    assert store.schema_version == migrations.LATEST_VERSION
    assert TIER2_TABLES <= table_names(store.conn)


def test_a_second_open_applies_nothing(tmp_path):
    path = tmp_path / "twice.sqlite3"
    first = Store(path)
    first.close()

    second = Store(path)
    try:
        assert second.migrations_applied == []
        assert second.schema_version == migrations.LATEST_VERSION
    finally:
        second.close()


def test_a_database_with_no_meta_table_reads_as_version_zero():
    conn = sqlite3.connect(":memory:")

    assert migrations.current_version(conn) == 0


def test_a_junk_version_value_reads_as_zero_and_re_migrates():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("schema_version", "banana"))

    assert migrations.current_version(conn) == 0
    assert migrations.migrate(conn)
    assert migrations.current_version(conn) == migrations.LATEST_VERSION


# --- the case that actually matters ---------------------------------------


def test_a_pre_existing_v0_database_upgrades_without_losing_data(tmp_path):
    """The operator's live store: ids, records, meta and no version row."""
    path = tmp_path / "legacy.sqlite3"
    legacy = sqlite3.connect(str(path))
    legacy.executescript(SCHEMA)
    legacy.execute(
        "INSERT INTO ids (hr_number, kind, created_at, sitemap_lastmod, first_seen, last_seen) "
        "VALUES ('HR010126120000', 'native', '2026-01-01T12:00:00', NULL, 'x', 'x')"
    )
    legacy.execute(
        "INSERT INTO records (hr_number, fetched_at, is_aggregator_job, raw) "
        "VALUES ('HR010126120000', 'x', 0, '{\"HR_Number\": \"HR010126120000\"}')"
    )
    legacy.execute("INSERT INTO meta (key, value) VALUES ('last_sync', '2026-01-01T00:00:00')")
    legacy.commit()
    legacy.close()

    upgraded = Store(path)
    try:
        assert upgraded.migrations_applied == ["1:tier2_shortlist_tracking_alerts_leases"]
        assert upgraded.schema_version == migrations.LATEST_VERSION
        assert TIER2_TABLES <= table_names(upgraded.conn)
        # Nothing that was there before was touched.
        assert upgraded.count_ids()["total"] == 1
        assert upgraded.count_records()["native"] == 1
        assert upgraded.last_sync == "2026-01-01T00:00:00"
    finally:
        upgraded.close()


def test_migrating_a_half_applied_schema_is_safe():
    """A crash between statements must be recoverable by running again."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.execute("CREATE TABLE saved (hr_number TEXT PRIMARY KEY, saved_at TEXT NOT NULL)")
    conn.commit()

    applied = migrations.migrate(conn)

    assert applied
    assert TIER2_TABLES <= table_names(conn)


# --- shortlist ------------------------------------------------------------


def test_saving_reports_new_versus_updated(store):
    assert store.save_job("HR010126120000", note="first") is True
    assert store.save_job("HR010126120000", note="second") is False
    assert store.list_saved()[0]["note"] == "second"


def test_saving_normalises_the_id(store):
    store.save_job("hr010126120000")

    assert store.is_saved("HR010126120000")
    assert store.saved_ids() == {"HR010126120000"}


def test_an_update_never_erases_a_snapshot_it_was_not_given(store):
    store.save_job("HR010126120000", title="Engineer", company="Acme")
    store.save_job("HR010126120000", note="thinking about it")

    row = store.list_saved()[0]

    assert row["title"] == "Engineer"
    assert row["company"] == "Acme"


def test_unsaving_something_absent_reports_false(store):
    assert store.unsave_job("HR010126120000") is False


# --- tracking -------------------------------------------------------------


def test_tracking_records_the_previous_status(store):
    assert store.track("HR1", "interested") == (None, True)
    assert store.track("HR1", "applied_manually") == ("interested", False)


def test_every_call_appends_history_including_a_repeat(store):
    store.track("HR1", "applied_manually")
    store.track("HR1", "applied_manually", notes="still nothing")

    events = store.tracked_events("HR1")

    assert [event["to_status"] for event in events] == ["applied_manually", "applied_manually"]
    assert events[1]["note"] == "still nothing"


def test_status_counts_reflect_only_the_current_status(store):
    store.track("HR1", "interested")
    store.track("HR1", "rejected")
    store.track("HR2", "interested")

    assert store.count_tracked_by_status() == {"rejected": 1, "interested": 1}


def test_listing_can_filter_by_status(store):
    store.track("HR1", "interested")
    store.track("HR2", "rejected")

    assert [row["hr_number"] for row in store.list_tracked("rejected")] == ["HR2"]


# --- alerts ---------------------------------------------------------------


def test_an_alert_reports_each_requisition_once(store):
    alert_id, _ = store.put_alert("nodes", {"skill": "node"})

    first = store.record_alert_hits(alert_id, ["HR1", "HR2"])
    second = store.record_alert_hits(alert_id, ["HR1", "HR2", "HR3"])

    assert first == ["HR1", "HR2"]
    assert second == ["HR3"]


def test_rewriting_criteria_clears_the_seen_list(store):
    """A widened alert that stayed silent about its new matches is a bug."""
    alert_id, _ = store.put_alert("nodes", {"skill": "node"})
    store.record_alert_hits(alert_id, ["HR1"])

    same_id, created = store.put_alert("nodes", {"skill": "node", "remote_only": True})

    assert (same_id, created) == (alert_id, False)
    assert store.record_alert_hits(alert_id, ["HR1"]) == ["HR1"]


def test_evaluating_stamps_the_alert(store):
    alert_id, _ = store.put_alert("nodes", {"skill": "node"})
    store.record_alert_hits(alert_id, [])

    assert store.get_alert("nodes")["last_evaluated_at"] is not None


def test_an_alert_can_be_fetched_by_name_or_id(store):
    alert_id, _ = store.put_alert("nodes", {"skill": "node"})

    assert store.get_alert("nodes")["id"] == alert_id
    assert store.get_alert(alert_id)["name"] == "nodes"
    assert store.get_alert("missing") is None


def test_deleting_removes_the_alert_and_its_hits(store):
    alert_id, _ = store.put_alert("nodes", {"skill": "node"})
    store.record_alert_hits(alert_id, ["HR1"])

    assert store.delete_alert("nodes") is True
    assert store.delete_alert("nodes") is False
    assert store.unnotified_hits(alert_id) == []


def test_criteria_survive_the_json_round_trip(store):
    store.put_alert("rich", {"skill": "node", "min_pay_usd_year": 40000, "remote_only": True})

    assert store.get_alert("rich")["criteria"] == {
        "skill": "node",
        "min_pay_usd_year": 40000,
        "remote_only": True,
    }


def test_hits_can_be_marked_notified(store):
    alert_id, _ = store.put_alert("nodes", {"skill": "node"})
    store.record_alert_hits(alert_id, ["HR1", "HR2"])

    store.mark_hits_notified(alert_id, ["HR1"])

    assert store.unnotified_hits(alert_id) == ["HR2"]


# --- the cross-process lease ----------------------------------------------


def test_only_one_owner_can_hold_a_lease(store):
    assert store.acquire_lease("sync", "process-a", 60) is True
    assert store.acquire_lease("sync", "process-b", 60) is False


def test_the_holder_can_renew_without_losing_the_acquisition_time(store):
    store.acquire_lease("sync", "process-a", 60)
    first = store.get_lease("sync")["acquired_at"]

    store.acquire_lease("sync", "process-a", 60)

    assert store.get_lease("sync")["acquired_at"] == first


def test_an_expired_lease_is_takeable(store):
    store.acquire_lease("sync", "dead-process", -1)      # already expired

    assert store.acquire_lease("sync", "live-process", 60) is True
    assert store.get_lease("sync")["owner"] == "live-process"


def test_releasing_frees_it_for_anyone(store):
    store.acquire_lease("sync", "process-a", 600)
    store.release_lease("sync", "process-a")

    assert store.acquire_lease("sync", "process-b", 60) is True


def test_a_non_holder_cannot_release_someone_elses_lease(store):
    store.acquire_lease("sync", "process-a", 600)

    assert store.release_lease("sync", "process-b") is False
    assert store.get_lease("sync")["owner"] == "process-a"


def test_two_separate_connections_contend_for_one_lease(tmp_path):
    """The real shape of the problem: two processes, one sqlite file."""
    path = tmp_path / "shared.sqlite3"
    first, second = Store(path), Store(path)
    try:
        assert first.acquire_lease("sync", "code", 600) is True
        assert second.acquire_lease("sync", "desktop", 600) is False
    finally:
        first.close()
        second.close()
