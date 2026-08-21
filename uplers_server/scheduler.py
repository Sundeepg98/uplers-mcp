"""Background index freshness, safe when two MCP clients run this server.

Claude Code and Claude Desktop both register `uplers`, and each spawns its own
process against the same sqlite file. A naive "sync every six hours" task
would therefore run twice, double the traffic to a public endpoint we are a
guest on, and race on the same rows. Two guards, both needed and each
insufficient alone:

  * **A lease** (`store.acquire_lease`) - one conditional UPDATE decides who
    syncs, so only one process is ever fetching. It expires, so a process that
    is killed mid-sync does not lock the other out forever.
  * **A due check** on `last_sync` - the lease says who may sync, this says
    whether anyone should. Without it, whichever process happened to be
    holding a free lease would re-sync a minute after the other finished.

Everything else is a consequence of "never break the MCP server it lives in":
the task is started from `main()` only, never at import, so tests and library
users never get a background task they did not ask for; every exception is
caught and recorded rather than raised into the event loop; and a cancellation
releases the lease on the way out.

Catch-up is deliberate. The first due-check runs BEFORE the first sleep, so a
laptop that was closed for two days syncs on the next launch instead of six
hours after it.
"""

from __future__ import annotations

import asyncio
import os
import socket
from datetime import datetime, timedelta

from . import config, ids
from .client import UplersClient
from .store import Store
from .sync import sync_index

LEASE_NAME = "sync"

META_LAST_AT = "auto_sync_last_at"
META_LAST_ATTEMPT = "auto_sync_last_attempt"
META_LAST_RESULT = "auto_sync_last_result"
META_LAST_ERROR = "auto_sync_last_error"
META_RUNS = "auto_sync_runs"


def owner_id() -> str:
    """Who this process is, for the lease. Host included so a shared drive works."""
    return "%s:%d" % (socket.gethostname(), os.getpid())


def enabled(bound=None) -> bool:
    """Off with UPLERS_AUTO_SYNC=0, or servers.uplers.auto_sync.enabled=false.

    The environment variable stays the kill switch and wins outright: it is
    what an MCP host can set without editing a shared file, and turning a
    background network task OFF must never depend on a file being readable.
    The config key can only turn it off as well, never back on.
    """
    from . import policy as policy_mod

    if str(os.environ.get("UPLERS_AUTO_SYNC", "1")).strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return False
    return bool(policy_mod.resolve(bound).setting("auto_sync", "enabled", default=True))


def is_due(last_sync: str | None, interval_seconds: int, *, now: datetime | None = None) -> bool:
    """True when the index has not been synced within the interval.

    An unreadable or missing timestamp counts as due - a store that cannot say
    when it last synced should be treated as stale, not as fresh.
    """
    if not last_sync:
        return True
    try:
        previous = datetime.fromisoformat(last_sync)
    except ValueError:
        return True
    reference = now or datetime.fromisoformat(ids.utcnow_iso())
    return reference - previous >= timedelta(seconds=interval_seconds)


class SyncScheduler:
    """One asyncio task that keeps the local index warm."""

    def __init__(
        self,
        *,
        interval_seconds: int = config.AUTO_SYNC_INTERVAL_SECONDS,
        poll_seconds: int | None = None,
        lease_ttl_seconds: int = config.AUTO_SYNC_LEASE_TTL_SECONDS,
        retry_seconds: int = config.AUTO_SYNC_RETRY_SECONDS,
        fetch_budget: int = config.AUTO_SYNC_FETCH_BUDGET,
        startup_delay_seconds: float = config.AUTO_SYNC_STARTUP_DELAY_SECONDS,
        db_path=None,
        client_factory=None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.poll_seconds = poll_seconds or min(interval_seconds, config.AUTO_SYNC_POLL_SECONDS)
        self.lease_ttl_seconds = lease_ttl_seconds
        self.retry_seconds = retry_seconds
        self.fetch_budget = fetch_budget
        self.startup_delay_seconds = startup_delay_seconds
        self.db_path = db_path
        self.client_factory = client_factory or UplersClient
        self.owner = owner_id()
        self.runs = 0
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> asyncio.Task:
        """Create the polling task on the RUNNING loop. Idempotent.

        get_running_loop rather than get_event_loop: the latter is deprecated
        outside a coroutine and would create a second, orphaned loop if this
        were ever called from synchronous code. There is no loop to attach to
        before mcp.run() starts one, which is why the server calls this from
        its first tool invocation rather than from main().
        """
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run())
        return self._task

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # -- the loop ----------------------------------------------------------

    async def run(self, *, max_cycles: int | None = None) -> int:
        """Poll forever (or `max_cycles` times, which is how tests drive it)."""
        if self.startup_delay_seconds:
            await asyncio.sleep(self.startup_delay_seconds)
        cycles = 0
        try:
            while max_cycles is None or cycles < max_cycles:
                cycles += 1
                await self.tick()
                if max_cycles is not None and cycles >= max_cycles:
                    break
                await asyncio.sleep(self.poll_seconds)
        except asyncio.CancelledError:
            self._release()
            raise
        return cycles

    async def tick(self) -> str:
        """One poll. Returns what happened, and never raises.

        A background task that can throw takes the MCP server's event loop with
        it, so every failure here becomes a recorded string instead.
        """
        try:
            return await self._tick()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - deliberately total
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            try:
                with self._store() as store:
                    store.set_meta(META_LAST_ERROR, self.last_error)
            except Exception:  # pragma: no cover - the store itself is broken
                pass
            return "error"

    async def _tick(self) -> str:
        if not enabled():
            return "disabled"
        with self._store() as store:
            if not is_due(store.last_sync, self.interval_seconds):
                return "not_due"
            # Second, independent brake. `last_sync` is stamped by sync_index,
            # so a sync that FAILS leaves it untouched and the interval check
            # above stays true - without this floor a persistently failing
            # endpoint would be retried on every poll, forever, which is a
            # traffic problem against somebody else's public API. Stamped
            # before the attempt so it holds even if the process dies mid-sync.
            if not is_due(store.get_meta(META_LAST_ATTEMPT), self.retry_seconds):
                return "retry_backoff"
            if not store.acquire_lease(LEASE_NAME, self.owner, self.lease_ttl_seconds):
                # Another process (the other MCP client) is on it.
                return "lease_held_elsewhere"
            store.set_meta(META_LAST_ATTEMPT, ids.utcnow_iso())
        try:
            async with self.client_factory() as client:
                with self._store() as store:
                    result = await sync_index(
                        store,
                        client,
                        hydrate=True,
                        fetch_budget=self.fetch_budget,
                        refresh_stale=True,
                    )
                    self.runs += 1
                    self.last_error = None
                    store.set_meta(META_LAST_AT, ids.utcnow_iso())
                    store.set_meta(
                        META_LAST_RESULT,
                        "new_ids=%d records_fetched=%d failures=%d"
                        % (result.new_ids, result.records_fetched, len(result.failures)),
                    )
                    store.set_meta(META_LAST_ERROR, "")
                    store.set_meta(META_RUNS, str(self.runs))
            return "synced"
        finally:
            self._release()

    # -- helpers -----------------------------------------------------------

    def _store(self) -> Store:
        return Store(self.db_path) if self.db_path else Store()

    def _release(self) -> None:
        try:
            with self._store() as store:
                store.release_lease(LEASE_NAME, self.owner)
        except Exception:  # pragma: no cover - best effort on the way out
            pass

    def status(self) -> dict:
        """What the status tool reports. Reads the store, never the loop's memory."""
        with self._store() as store:
            lease = store.get_lease(LEASE_NAME) or {}
            runs = store.get_meta(META_RUNS)
            return {
                "enabled": enabled(),
                "running": self.running,
                "interval_seconds": self.interval_seconds,
                "owner": lease.get("owner") or None,
                "holds_lease": bool(lease.get("owner")) and lease.get("owner") == self.owner,
                "lease_expires_at": lease.get("expires_at") or None,
                "last_sync": store.last_sync,
                "last_auto_sync_at": store.get_meta(META_LAST_AT),
                "last_attempt_at": store.get_meta(META_LAST_ATTEMPT),
                "last_auto_sync_result": store.get_meta(META_LAST_RESULT),
                "last_error": self.last_error or (store.get_meta(META_LAST_ERROR) or None),
                "runs": int(runs) if runs and runs.isdigit() else self.runs,
            }


# The server's single instance, created on demand so importing this module
# never allocates anything.
_SCHEDULER: SyncScheduler | None = None


def get_scheduler(bound=None) -> SyncScheduler:
    """The process-wide scheduler, built once from the configured cadence.

    Built once on purpose: a second call must not silently start a second
    task. A cadence edit is picked up on the next process start, which is the
    same contract the lease already has.
    """
    global _SCHEDULER
    if _SCHEDULER is None:
        from . import policy as policy_mod

        settings = policy_mod.resolve(bound)
        hours = settings.setting("auto_sync", "interval_hours", default=None)
        _SCHEDULER = SyncScheduler(
            interval_seconds=(
                int(float(hours) * 3600) if hours is not None
                else config.AUTO_SYNC_INTERVAL_SECONDS
            ),
            fetch_budget=settings.setting(
                "auto_sync", "budget", default=config.AUTO_SYNC_FETCH_BUDGET),
        )
    return _SCHEDULER
