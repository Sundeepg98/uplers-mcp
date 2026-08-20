"""Persistent local state: the id store and the record cache.

Plain stdlib sqlite3 in one file. No server, no ORM, no migrations framework.

Why an id store exists at all: platform.uplers.com/sitemap.xml is
NON-DETERMINISTIC. Three consecutive fetches on 2026-08-20 returned 33,160 /
39,608 / 10,811 entries. It is a sampler, not an index. The only way to build
a stable picture of the board is to UNION every fetch into a durable set and
never delete on absence. `last_seen` records when an id was last observed, so
staleness is visible instead of silently destructive.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, ids, migrations

SCHEMA = """
CREATE TABLE IF NOT EXISTS ids (
    hr_number       TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    created_at      TEXT,
    sitemap_lastmod TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ids_kind_created ON ids (kind, created_at);

CREATE TABLE IF NOT EXISTS records (
    hr_number         TEXT PRIMARY KEY,
    fetched_at        TEXT NOT NULL,
    is_aggregator_job INTEGER NOT NULL,
    raw               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_agg ON records (is_aggregator_job);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    """The local index + cache. Safe to construct repeatedly."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.path = Path(db_path) if db_path else config.DB_PATH
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=config.SQLITE_TIMEOUT_SECONDS)
        self.conn.row_factory = sqlite3.Row
        # Two MCP clients (Claude Code, Claude Desktop) spawn independent
        # copies of this server against the same file. WAL lets a reader and a
        # writer coexist instead of one blocking the other, and busy_timeout
        # turns the remaining collisions into a short wait instead of an
        # immediate "database is locked".
        self.conn.execute("PRAGMA busy_timeout = %d" % config.SQLITE_BUSY_TIMEOUT_MS)
        if str(self.path) != ":memory:":
            try:
                self.conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError:  # pragma: no cover - exotic filesystems
                pass
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.migrations_applied = migrations.migrate(self.conn)

    @property
    def schema_version(self) -> int:
        return migrations.current_version(self.conn)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- meta --------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    @property
    def last_sync(self) -> str | None:
        return self.get_meta("last_sync")

    # -- ids ---------------------------------------------------------------

    def union_ids(self, discovered: dict[str, str | None]) -> tuple[int, dict[str, int]]:
        """Merge discovered ids into the store. Returns (new_count, new_by_kind).

        `discovered` maps hr_number -> sitemap lastmod (or None). Ids already
        known have last_seen refreshed; ids absent from this fetch are left
        alone, because absence from one sitemap fetch means nothing.
        """
        now = ids.utcnow_iso()
        existing = {row["hr_number"] for row in self.conn.execute("SELECT hr_number FROM ids")}
        new_by_kind: dict[str, int] = {}
        rows = []
        for hr_number, lastmod in discovered.items():
            kind = ids.classify(hr_number)
            if hr_number not in existing:
                new_by_kind[kind] = new_by_kind.get(kind, 0) + 1
            rows.append((hr_number, kind, ids.created_at_iso(hr_number), lastmod, now, now))
        self.conn.executemany(
            "INSERT INTO ids (hr_number, kind, created_at, sitemap_lastmod, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(hr_number) DO UPDATE SET "
            "  last_seen = excluded.last_seen, "
            "  sitemap_lastmod = COALESCE(excluded.sitemap_lastmod, ids.sitemap_lastmod)",
            rows,
        )
        self.conn.commit()
        return (sum(new_by_kind.values()), new_by_kind)

    def count_ids(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT kind, COUNT(*) AS n FROM ids GROUP BY kind").fetchall()
        counts = {row["kind"]: row["n"] for row in rows}
        counts["total"] = sum(counts.values())
        return counts

    def native_ids(self, *, since_iso: str | None = None, newest_first: bool = True) -> list[str]:
        """Native ids, ordered by their decoded creation time.

        Ids whose digits do not decode to a real timestamp (created_at IS NULL)
        are excluded from date-filtered queries but included in unfiltered ones.
        """
        order = "DESC" if newest_first else "ASC"
        if since_iso:
            sql = (
                "SELECT hr_number FROM ids WHERE kind = ? AND created_at IS NOT NULL "
                "AND created_at >= ? ORDER BY created_at " + order
            )
            params: tuple = (ids.KIND_NATIVE, since_iso)
        else:
            sql = (
                "SELECT hr_number FROM ids WHERE kind = ? "
                "ORDER BY created_at IS NULL, created_at " + order
            )
            params = (ids.KIND_NATIVE,)
        return [row["hr_number"] for row in self.conn.execute(sql, params)]

    def known_ids(self) -> set[str]:
        return {row["hr_number"] for row in self.conn.execute("SELECT hr_number FROM ids")}

    # -- records -----------------------------------------------------------

    def put_record(self, hr_number: str, raw: dict) -> None:
        self.conn.execute(
            "INSERT INTO records (hr_number, fetched_at, is_aggregator_job, raw) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(hr_number) DO UPDATE SET "
            "  fetched_at = excluded.fetched_at, "
            "  is_aggregator_job = excluded.is_aggregator_job, "
            "  raw = excluded.raw",
            (
                ids.normalise(hr_number),
                ids.utcnow_iso(),
                1 if raw.get("is_aggregator_job") else 0,
                json.dumps(raw, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def put_records(self, records: dict[str, dict]) -> int:
        for hr_number, raw in records.items():
            self.put_record(hr_number, raw)
        return len(records)

    def get_record(self, hr_number: str) -> tuple[dict, str] | None:
        """Return (raw_record, fetched_at) or None if not cached."""
        row = self.conn.execute(
            "SELECT raw, fetched_at FROM records WHERE hr_number = ?",
            (ids.normalise(hr_number),),
        ).fetchone()
        if row is None:
            return None
        return (json.loads(row["raw"]), row["fetched_at"])

    def iter_records(self, *, include_aggregated: bool = False):
        """Yield (raw_record, fetched_at) for cached records."""
        sql = "SELECT raw, fetched_at FROM records"
        params: tuple = ()
        if not include_aggregated:
            sql += " WHERE is_aggregator_job = 0"
        for row in self.conn.execute(sql, params):
            yield (json.loads(row["raw"]), row["fetched_at"])

    def count_records(self) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN is_aggregator_job = 0 THEN 1 ELSE 0 END) AS native "
            "FROM records"
        ).fetchone()
        total = row["total"] or 0
        native = row["native"] or 0
        return {"total": total, "native": native, "aggregated": total - native}

    def unhydrated_native_count(self) -> int:
        """Native ids known but never fetched.

        Asked directly rather than derived by subtracting record counts from id
        counts: a record can be cached whose id was never unioned in (a direct
        uplers_get_opportunity on an id the sitemap never offered), which makes
        the subtraction understate - or go negative - for no visible reason.
        """
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM ids WHERE kind = ? AND hr_number NOT IN "
            "(SELECT hr_number FROM records)",
            (ids.KIND_NATIVE,),
        ).fetchone()
        return row["n"] or 0

    def unseen_alert_hits(self, alert_id: int, hr_numbers: list[str]) -> list[str]:
        """Which of these an alert has not reported - WITHOUT recording them.

        The read-only twin of record_alert_hits, for peeking at a brief without
        consuming the news it would have shown.
        """
        known = {
            row["hr_number"]
            for row in self.conn.execute(
                "SELECT hr_number FROM alert_hits WHERE alert_id = ?", (alert_id,)
            )
        }
        return [h for h in hr_numbers if h not in known]

    def cached_ids(self) -> set[str]:
        return {row["hr_number"] for row in self.conn.execute("SELECT hr_number FROM records")}

    def stale_or_missing(self, hr_numbers: list[str], ttl_seconds: int) -> list[str]:
        """Which of these ids need a (re)fetch, preserving input order."""
        from datetime import datetime, timedelta

        cutoff = ids.utcnow_iso()
        try:
            cutoff = (
                datetime.fromisoformat(cutoff) - timedelta(seconds=ttl_seconds)
            ).isoformat()
        except ValueError:  # pragma: no cover - fromisoformat on our own output
            return list(hr_numbers)
        fresh = {
            row["hr_number"]
            for row in self.conn.execute(
                "SELECT hr_number FROM records WHERE fetched_at >= ?", (cutoff,)
            )
        }
        return [h for h in hr_numbers if h not in fresh]

    # -- shortlist ---------------------------------------------------------

    def save_job(
        self,
        hr_number: str,
        *,
        note: str | None = None,
        title: str | None = None,
        company: str | None = None,
    ) -> bool:
        """Add to the shortlist. Returns True if newly saved, False if updated.

        A title/company snapshot is stored alongside so `list_saved` stays a
        pure local read and keeps working even if the requisition later
        disappears from Uplers.
        """
        key = ids.normalise(hr_number)
        existed = self.is_saved(key)
        if existed:
            self.conn.execute(
                "UPDATE saved SET note = COALESCE(?, note), "
                "title = COALESCE(?, title), company = COALESCE(?, company) "
                "WHERE hr_number = ?",
                (note, title, company, key),
            )
        else:
            self.conn.execute(
                "INSERT INTO saved (hr_number, saved_at, note, title, company) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, ids.utcnow_iso(), note, title, company),
            )
        self.conn.commit()
        return not existed

    def unsave_job(self, hr_number: str) -> bool:
        """Remove from the shortlist. False means it was not on it."""
        cursor = self.conn.execute(
            "DELETE FROM saved WHERE hr_number = ?", (ids.normalise(hr_number),)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def is_saved(self, hr_number: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM saved WHERE hr_number = ?", (ids.normalise(hr_number),)
        ).fetchone()
        return row is not None

    def list_saved(self) -> list[dict]:
        """Shortlist, newest save first."""
        return [
            dict(row)
            for row in self.conn.execute("SELECT * FROM saved ORDER BY saved_at DESC")
        ]

    def saved_ids(self) -> set[str]:
        return {row["hr_number"] for row in self.conn.execute("SELECT hr_number FROM saved")}

    # -- application tracking ---------------------------------------------

    def track(
        self,
        hr_number: str,
        status: str,
        *,
        notes: str | None = None,
        title: str | None = None,
        company: str | None = None,
    ) -> tuple[str | None, bool]:
        """Record or update a status. Returns (previous_status, is_new).

        Always appends to `tracked_events`, including on a no-op re-statement
        of the same status, because re-confirming on a later date that nothing
        has moved is itself information the follow-up logic uses.
        """
        key = ids.normalise(hr_number)
        now = ids.utcnow_iso()
        row = self.conn.execute(
            "SELECT status FROM tracked WHERE hr_number = ?", (key,)
        ).fetchone()
        previous = row["status"] if row else None
        if row is None:
            self.conn.execute(
                "INSERT INTO tracked (hr_number, status, notes, title, company, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, status, notes, title, company, now, now),
            )
        else:
            self.conn.execute(
                "UPDATE tracked SET status = ?, notes = COALESCE(?, notes), "
                "title = COALESCE(?, title), company = COALESCE(?, company), "
                "updated_at = ? WHERE hr_number = ?",
                (status, notes, title, company, now, key),
            )
        self.conn.execute(
            "INSERT INTO tracked_events (hr_number, from_status, to_status, at, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, previous, status, now, notes),
        )
        self.conn.commit()
        return (previous, row is None)

    def get_tracked(self, hr_number: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM tracked WHERE hr_number = ?", (ids.normalise(hr_number),)
        ).fetchone()
        return dict(row) if row else None

    def list_tracked(self, status: str | None = None) -> list[dict]:
        """Tracked applications, most recently touched first."""
        if status:
            sql = "SELECT * FROM tracked WHERE status = ? ORDER BY updated_at DESC"
            params: tuple = (status,)
        else:
            sql = "SELECT * FROM tracked ORDER BY updated_at DESC"
            params = ()
        return [dict(row) for row in self.conn.execute(sql, params)]

    def tracked_ids(self) -> dict[str, str]:
        return {
            row["hr_number"]: row["status"]
            for row in self.conn.execute("SELECT hr_number, status FROM tracked")
        }

    def tracked_events(self, hr_number: str) -> list[dict]:
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM tracked_events WHERE hr_number = ? ORDER BY at, id",
                (ids.normalise(hr_number),),
            )
        ]

    def count_tracked_by_status(self) -> dict[str, int]:
        return {
            row["status"]: row["n"]
            for row in self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM tracked GROUP BY status"
            )
        }

    # -- alerts ------------------------------------------------------------

    def put_alert(self, name: str, criteria: dict) -> tuple[int, bool]:
        """Create or replace an alert by name. Returns (alert_id, is_new)."""
        row = self.conn.execute("SELECT id FROM alerts WHERE name = ?", (name,)).fetchone()
        blob = json.dumps(criteria, ensure_ascii=False, sort_keys=True)
        if row is None:
            cursor = self.conn.execute(
                "INSERT INTO alerts (name, criteria, created_at, active) VALUES (?, ?, ?, 1)",
                (name, blob, ids.utcnow_iso()),
            )
            self.conn.commit()
            return (int(cursor.lastrowid), True)
        self.conn.execute(
            "UPDATE alerts SET criteria = ?, active = 1 WHERE id = ?", (blob, row["id"])
        )
        # Criteria changed, so previously-reported hits are no longer a valid
        # record of what this alert has shown. Clearing them is the only way a
        # widened alert can report the matches it now covers.
        self.conn.execute("DELETE FROM alert_hits WHERE alert_id = ?", (row["id"],))
        self.conn.commit()
        return (int(row["id"]), False)

    def list_alerts(self, *, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM alerts"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY id"
        out = []
        for row in self.conn.execute(sql):
            record = dict(row)
            try:
                record["criteria"] = json.loads(record["criteria"])
            except (TypeError, ValueError):  # pragma: no cover - we wrote it
                record["criteria"] = {}
            out.append(record)
        return out

    def get_alert(self, name_or_id: str | int) -> dict | None:
        if isinstance(name_or_id, int) or str(name_or_id).isdigit():
            row = self.conn.execute(
                "SELECT * FROM alerts WHERE id = ?", (int(name_or_id),)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM alerts WHERE name = ?", (name_or_id,)
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        try:
            record["criteria"] = json.loads(record["criteria"])
        except (TypeError, ValueError):  # pragma: no cover
            record["criteria"] = {}
        return record

    def delete_alert(self, name_or_id: str | int) -> bool:
        alert = self.get_alert(name_or_id)
        if alert is None:
            return False
        self.conn.execute("DELETE FROM alert_hits WHERE alert_id = ?", (alert["id"],))
        self.conn.execute("DELETE FROM alerts WHERE id = ?", (alert["id"],))
        self.conn.commit()
        return True

    def record_alert_hits(self, alert_id: int, hr_numbers: list[str]) -> list[str]:
        """Register matches, returning only those not seen before by this alert."""
        known = {
            row["hr_number"]
            for row in self.conn.execute(
                "SELECT hr_number FROM alert_hits WHERE alert_id = ?", (alert_id,)
            )
        }
        fresh = [h for h in hr_numbers if h not in known]
        now = ids.utcnow_iso()
        if fresh:
            self.conn.executemany(
                "INSERT OR IGNORE INTO alert_hits (alert_id, hr_number, hit_at, notified) "
                "VALUES (?, ?, ?, 0)",
                [(alert_id, h, now) for h in fresh],
            )
        self.conn.execute(
            "UPDATE alerts SET last_evaluated_at = ? WHERE id = ?", (now, alert_id)
        )
        self.conn.commit()
        return fresh

    def unnotified_hits(self, alert_id: int) -> list[str]:
        return [
            row["hr_number"]
            for row in self.conn.execute(
                "SELECT hr_number FROM alert_hits WHERE alert_id = ? AND notified = 0 "
                "ORDER BY hit_at DESC",
                (alert_id,),
            )
        ]

    def mark_hits_notified(self, alert_id: int, hr_numbers: list[str]) -> int:
        if not hr_numbers:
            return 0
        self.conn.executemany(
            "UPDATE alert_hits SET notified = 1 WHERE alert_id = ? AND hr_number = ?",
            [(alert_id, h) for h in hr_numbers],
        )
        self.conn.commit()
        return len(hr_numbers)

    # -- cross-process lease ----------------------------------------------

    def acquire_lease(self, name: str, owner: str, ttl_seconds: int) -> bool:
        """Take or renew a named lease. False means somebody else holds it.

        The whole decision is one conditional UPDATE, so two processes racing
        cannot both win: sqlite serialises the writes and the loser's WHERE
        clause no longer matches by the time its statement runs.
        """
        from datetime import datetime, timedelta

        now = ids.utcnow_iso()
        expires = (datetime.fromisoformat(now) + timedelta(seconds=ttl_seconds)).isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO leases (name, owner, expires_at, acquired_at) "
            "VALUES (?, '', '', NULL)",
            (name,),
        )
        cursor = self.conn.execute(
            "UPDATE leases SET owner = ?, expires_at = ?, "
            "acquired_at = CASE WHEN owner = ? THEN acquired_at ELSE ? END "
            "WHERE name = ? AND (expires_at < ? OR owner = ? OR owner = '')",
            (owner, expires, owner, now, name, now, owner),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def release_lease(self, name: str, owner: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE leases SET owner = '', expires_at = '' WHERE name = ? AND owner = ?",
            (name, owner),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_lease(self, name: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM leases WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None
