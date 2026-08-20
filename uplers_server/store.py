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

from . import config, ids

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
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

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
