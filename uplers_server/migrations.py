"""Versioned schema migrations for the local sqlite store.

This server already holds data on the operator's machine - an ~11 MB id store
built over real sync runs - so the schema cannot simply be redefined. Every
change ships as a numbered migration that runs once, in order, and records
itself in `meta.schema_version`.

Two invariants:

  * IDEMPOTENT. Every statement is CREATE ... IF NOT EXISTS or an additive
    ALTER guarded by a column probe, so re-running a half-applied migration
    is safe. A crash between statements is recoverable by running again.
  * FORWARD ONLY. There is no down-migration. Nothing here drops or rewrites
    a column that holds user data; a mistake is corrected by a new migration,
    never by editing an old one (a database that already ran migration 2 will
    never run it again, so editing it changes nothing on the machine that
    matters).

The pre-migration database - `ids`, `records`, `meta`, no version row - is
version 0 and is detected by the absence of the version key, not by guessing.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION_KEY = "schema_version"

# --- migration 1: the tier-2 tables ---------------------------------------
# Shortlist, application tracking, alerts, and the cross-process sync lease.
_M1 = """
CREATE TABLE IF NOT EXISTS saved (
    hr_number  TEXT PRIMARY KEY,
    saved_at   TEXT NOT NULL,
    note       TEXT,
    title      TEXT,
    company    TEXT
);

CREATE TABLE IF NOT EXISTS tracked (
    hr_number  TEXT PRIMARY KEY,
    status     TEXT NOT NULL,
    notes      TEXT,
    title      TEXT,
    company    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracked_status ON tracked (status);

-- Every status transition, kept forever. The history is what makes
-- "you applied 11 days ago and heard nothing" answerable at all.
CREATE TABLE IF NOT EXISTS tracked_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hr_number   TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    at          TEXT NOT NULL,
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_hr ON tracked_events (hr_number, at);

CREATE TABLE IF NOT EXISTS alerts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,
    criteria          TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    last_evaluated_at TEXT,
    active            INTEGER NOT NULL DEFAULT 1
);

-- One row per (alert, requisition) so an alert reports a match exactly once.
CREATE TABLE IF NOT EXISTS alert_hits (
    alert_id  INTEGER NOT NULL,
    hr_number TEXT NOT NULL,
    hit_at    TEXT NOT NULL,
    notified  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (alert_id, hr_number)
);
CREATE INDEX IF NOT EXISTS idx_hits_notified ON alert_hits (alert_id, notified);

-- Cross-process advisory lease. Two MCP clients (Claude Code and Claude
-- Desktop) each spawn their own copy of this server against the SAME sqlite
-- file; without a lease both would run the background sync and double the
-- traffic to Uplers. See scheduler.py.
CREATE TABLE IF NOT EXISTS leases (
    name       TEXT PRIMARY KEY,
    owner      TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    acquired_at TEXT
);
"""

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "tier2_shortlist_tracking_alerts_leases", _M1),
]

LATEST_VERSION = max(version for version, _, _ in MIGRATIONS)


def current_version(conn: sqlite3.Connection) -> int:
    """Read the applied schema version. A store with no version row is 0."""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (SCHEMA_VERSION_KEY,)
        ).fetchone()
    except sqlite3.OperationalError:
        return 0  # `meta` itself does not exist yet
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every migration newer than the recorded version.

    Returns the names applied this call - empty when already current, which
    is the normal case on every connection after the first.
    """
    version = current_version(conn)
    applied: list[str] = []
    for number, name, sql in sorted(MIGRATIONS):
        if number <= version:
            continue
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION_KEY, str(number)),
        )
        conn.commit()
        applied.append("%d:%s" % (number, name))
    return applied
