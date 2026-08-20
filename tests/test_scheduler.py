"""scheduler.py - background freshness that two clients can share.

Claude Code and Claude Desktop both register this server, so two processes run
against one sqlite file. The tests here drive the loop directly rather than
letting it run, and the ones that matter are about NOT syncing: when it is not
due, when another process holds the lease, and when the whole thing is
switched off.

Nothing in this file touches the network - the client is a stub whose only job
is to record that it was constructed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from uplers_server import ids, scheduler
from uplers_server.models import SyncResult
from uplers_server.store import Store


class StubClient:
    """Stands in for UplersClient; records every construction."""

    constructions = 0

    def __init__(self, *args, **kwargs):
        type(self).constructions += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None


@pytest.fixture(autouse=True)
def reset_stub():
    StubClient.constructions = 0
    yield


@pytest.fixture(autouse=True)
def auto_sync_on(monkeypatch):
    """These tests are about the scheduler, so it must be enabled."""
    monkeypatch.setenv("UPLERS_AUTO_SYNC", "1")


@pytest.fixture
def db(tmp_path):
    return tmp_path / "sched.sqlite3"


@pytest.fixture
def fake_sync(monkeypatch):
    """Replace the real sync with a counter. Returns the call log.

    It stamps `last_sync` because the real sync_index does, and the interval
    brake reads it. A stub that skipped that would make every "does it sync
    again" test pass for the wrong reason.
    """
    calls = []

    async def recorder(store, client, **kwargs):
        calls.append(kwargs)
        store.set_meta("last_sync", ids.utcnow_iso())
        return SyncResult(new_ids=2, records_fetched=1)

    monkeypatch.setattr(scheduler, "sync_index", recorder)
    return calls


def make(db, **overrides):
    options = {
        "db_path": db,
        "startup_delay_seconds": 0,
        "poll_seconds": 0,
        "client_factory": StubClient,
    }
    options.update(overrides)
    return scheduler.SyncScheduler(**options)


# --- the due check --------------------------------------------------------


def test_a_store_that_never_synced_is_due():
    assert scheduler.is_due(None, 3600) is True


def test_an_unreadable_timestamp_counts_as_due():
    """A store that cannot say when it synced is stale, not fresh."""
    assert scheduler.is_due("not-a-timestamp", 3600) is True


def test_a_recent_sync_is_not_due():
    recent = (datetime.fromisoformat(ids.utcnow_iso()) - timedelta(minutes=5)).isoformat()

    assert scheduler.is_due(recent, 3600) is False


def test_an_old_sync_is_due():
    old = (datetime.fromisoformat(ids.utcnow_iso()) - timedelta(hours=9)).isoformat()

    assert scheduler.is_due(old, 6 * 3600) is True


# --- what a tick does -----------------------------------------------------


async def test_a_fresh_store_syncs_immediately_rather_than_after_one_interval(db, fake_sync):
    """Catch-up matters: a laptop closed for two days must not wait six hours."""
    outcome = await make(db).tick()

    assert outcome == "synced"
    assert len(fake_sync) == 1
    assert fake_sync[0]["refresh_stale"] is True


async def test_a_recently_synced_store_does_not_sync(db, fake_sync):
    store = Store(db)
    store.set_meta("last_sync", ids.utcnow_iso())
    store.close()

    assert await make(db).tick() == "not_due"
    assert fake_sync == []
    assert StubClient.constructions == 0


async def test_a_lease_held_elsewhere_stops_this_process_syncing(db, fake_sync):
    """The two-client case: exactly one process may fetch."""
    other = Store(db)
    other.acquire_lease(scheduler.LEASE_NAME, "the-other-mcp-client", 600)
    other.close()

    assert await make(db).tick() == "lease_held_elsewhere"
    assert fake_sync == []


async def test_the_lease_is_released_after_a_successful_sync(db, fake_sync):
    task = make(db)

    await task.tick()

    store = Store(db)
    try:
        assert store.get_lease(scheduler.LEASE_NAME)["owner"] == ""
        assert store.acquire_lease(scheduler.LEASE_NAME, "somebody-else", 60) is True
    finally:
        store.close()


async def test_the_lease_is_released_even_when_the_sync_fails(db, monkeypatch):
    async def explode(*args, **kwargs):
        raise RuntimeError("uplers is down")

    monkeypatch.setattr(scheduler, "sync_index", explode)
    task = make(db)

    assert await task.tick() == "error"

    store = Store(db)
    try:
        assert store.acquire_lease(scheduler.LEASE_NAME, "somebody-else", 60) is True
    finally:
        store.close()


async def test_a_persistently_failing_sync_is_not_retried_every_poll(db, monkeypatch):
    """Without an attempt floor, a broken endpoint gets hammered forever.

    `last_sync` is stamped by sync_index, so a failure leaves it old and the
    interval check keeps saying "due" on every single poll.
    """
    async def explode(*args, **kwargs):
        raise RuntimeError("uplers is down")

    monkeypatch.setattr(scheduler, "sync_index", explode)
    task = make(db)

    outcomes = [await task.tick(), await task.tick(), await task.tick()]

    assert outcomes == ["error", "retry_backoff", "retry_backoff"]


async def test_the_retry_floor_can_be_waited_out(db, fake_sync):
    task = make(db, retry_seconds=0)

    assert await task.tick() == "synced"
    # last_sync is now fresh, so the interval brake takes over from the floor.
    assert await task.tick() == "not_due"


async def test_a_failure_is_recorded_rather_than_raised(db, monkeypatch):
    """A background task that throws takes the MCP server's event loop with it."""
    async def explode(*args, **kwargs):
        raise RuntimeError("uplers is down")

    monkeypatch.setattr(scheduler, "sync_index", explode)
    task = make(db)

    await task.tick()

    assert "uplers is down" in task.last_error
    assert "uplers is down" in task.status()["last_error"]


async def test_success_records_a_result_line_and_clears_the_error(db, fake_sync):
    task = make(db)

    await task.tick()
    status = task.status()

    assert status["last_auto_sync_at"] is not None
    assert "records_fetched=1" in status["last_auto_sync_result"]
    assert status["last_error"] is None
    assert status["runs"] == 1


async def test_disabling_it_stops_everything(db, fake_sync, monkeypatch):
    monkeypatch.setenv("UPLERS_AUTO_SYNC", "0")

    assert await make(db).tick() == "disabled"
    assert fake_sync == []


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
def test_the_off_switch_accepts_the_obvious_spellings(value, monkeypatch):
    monkeypatch.setenv("UPLERS_AUTO_SYNC", value)

    assert scheduler.enabled() is False


def test_it_is_on_by_default(monkeypatch):
    monkeypatch.delenv("UPLERS_AUTO_SYNC", raising=False)

    assert scheduler.enabled() is True


# --- the loop -------------------------------------------------------------


async def test_the_loop_runs_the_requested_number_of_cycles(db, fake_sync):
    task = make(db)

    cycles = await task.run(max_cycles=3)

    assert cycles == 3
    # Only the first cycle fetches; the rest see a fresh last_sync.
    assert len(fake_sync) == 1


async def test_two_schedulers_on_one_file_do_not_both_sync(db, fake_sync):
    """The whole reason the lease exists."""
    first, second = make(db), make(db)
    second.owner = "the-other-mcp-client"

    outcomes = [await first.tick(), await second.tick()]

    assert outcomes == ["synced", "not_due"]
    assert len(fake_sync) == 1


async def test_status_reports_who_holds_the_lease(db):
    holder = Store(db)
    holder.acquire_lease(scheduler.LEASE_NAME, "the-other-mcp-client", 600)
    holder.close()

    status = make(db).status()

    assert status["owner"] == "the-other-mcp-client"
    assert status["holds_lease"] is False


async def test_status_works_before_anything_has_ever_run(db):
    status = make(db).status()

    assert status["enabled"] is True
    assert status["running"] is False
    assert status["last_sync"] is None
    assert status["runs"] == 0


def test_owner_ids_are_distinct_per_process():
    assert ":" in scheduler.owner_id()
    assert scheduler.owner_id() == scheduler.owner_id()


def test_the_module_level_scheduler_is_created_only_on_demand():
    scheduler._SCHEDULER = None

    first = scheduler.get_scheduler()
    second = scheduler.get_scheduler()

    assert first is second
    scheduler._SCHEDULER = None
