"""store.py - the durable id union and the record cache.

The sitemap is a non-deterministic sampler, so the store's contract is:
UNION every fetch in, never delete on absence, and keep first_seen /
last_seen honest. Those are the properties tested here.
"""

from __future__ import annotations

import pytest

from uplers_server import config, ids
from uplers_server.store import Store

from conftest import (
    AGGREGATED,
    ALL_IDS,
    ANOMALY,
    CONFIDO,
    NATIVE_IDS,
    load_fixture,
    put_fixtures,
)

# Hand-built ids: all 12-digit natives whose digits decode to real dates.
N1 = "HR010126120000"   # 2026-01-01T12:00:00
N2 = "HR020126120000"   # 2026-01-02T12:00:00
N3 = "HR030126120000"   # 2026-01-03T12:00:00
UNDATED_NATIVE = "HR999999999999"  # 12 digits, but day 99 / month 99 -> no date


def _row(store, hr_number):
    return store.conn.execute(
        "SELECT * FROM ids WHERE hr_number = ?", (hr_number,)
    ).fetchone()


# --- records --------------------------------------------------------------


def test_in_memory_store_round_trips_a_record():
    store = Store(":memory:")
    try:
        store.put_record(CONFIDO, load_fixture(CONFIDO))
        assert store.count_records() == {"total": 1, "native": 1, "aggregated": 0}
    finally:
        store.close()


def test_get_record_returns_the_payload_verbatim(store):
    original = load_fixture(CONFIDO)
    store.put_record(CONFIDO, original)

    raw, fetched_at = store.get_record(CONFIDO)
    assert raw == original          # survives the JSON round trip, non-ASCII included
    assert len(fetched_at) == 19    # ids.utcnow_iso() stamp


def test_get_record_normalises_the_id_on_both_sides(store):
    store.put_record(CONFIDO.lower(), load_fixture(CONFIDO))
    assert store.cached_ids() == {CONFIDO}
    assert store.get_record(CONFIDO.lower())[0]["HR_Number"] == CONFIDO


def test_get_record_is_none_when_nothing_is_cached(store):
    assert store.get_record(N1) is None


def test_put_records_reports_how_many_it_wrote(store):
    written = store.put_records({h: load_fixture(h) for h in NATIVE_IDS})
    assert written == 5
    assert store.cached_ids() == set(NATIVE_IDS)


def test_count_records_splits_native_from_aggregated(store):
    put_fixtures(store, ALL_IDS)
    assert store.count_records() == {"total": 6, "native": 5, "aggregated": 1}


# --- the native / aggregated separation (group A) -------------------------


def test_iter_records_hides_aggregated_postings_by_default(store):
    put_fixtures(store, ALL_IDS)

    native_only = [raw["HR_Number"] for raw, _ in store.iter_records()]
    assert sorted(native_only) == sorted(NATIVE_IDS)
    assert AGGREGATED not in native_only


def test_iter_records_can_opt_in_to_aggregated(store):
    put_fixtures(store, ALL_IDS)

    everything = [raw["HR_Number"] for raw, _ in store.iter_records(include_aggregated=True)]
    assert sorted(everything) == sorted(ALL_IDS)
    assert AGGREGATED in everything


# --- the id union (group E) ----------------------------------------------


def test_union_ids_counts_new_ids_by_kind(store):
    new_count, by_kind = store.union_ids({N1: "2026-01-01", AGGREGATED: None, ANOMALY: None})

    assert new_count == 3
    assert by_kind == {"native": 1, "aggregated": 1, "unknown": 1}
    assert store.count_ids() == {"native": 1, "aggregated": 1, "unknown": 1, "total": 3}


def test_union_never_deletes_and_only_counts_genuinely_new(store, monkeypatch):
    """The property that defeats a non-deterministic sitemap.

    Fetch B omits N1 and AGGREGATED entirely and adds N3. Nothing may be
    dropped, and only N3 may be reported as new.
    """
    clock = ["2026-08-01T00:00:00"]
    monkeypatch.setattr(ids, "utcnow_iso", lambda: clock[0])

    first_new, _ = store.union_ids({N1: "2026-01-01", N2: None, AGGREGATED: None})
    assert first_new == 3

    clock[0] = "2026-08-02T00:00:00"
    second_new, second_by_kind = store.union_ids({N2: None, N3: "2026-02-02"})

    # (i) nothing from fetch A was deleted
    assert store.known_ids() == {N1, N2, N3, AGGREGATED}
    # (ii) only the genuinely new id is reported as new
    assert second_new == 1
    assert second_by_kind == {"native": 1}
    # (iii) a re-seen id keeps first_seen and advances last_seen
    reseen = _row(store, N2)
    assert reseen["first_seen"] == "2026-08-01T00:00:00"
    assert reseen["last_seen"] == "2026-08-02T00:00:00"
    # an id absent from fetch B keeps its ORIGINAL last_seen, so staleness shows
    assert _row(store, N1)["last_seen"] == "2026-08-01T00:00:00"


def test_a_known_lastmod_is_not_overwritten_by_a_later_none(store):
    store.union_ids({N1: "2026-01-01"})
    assert _row(store, N1)["sitemap_lastmod"] == "2026-01-01"

    store.union_ids({N1: None})  # a later fetch that omitted <lastmod>
    assert _row(store, N1)["sitemap_lastmod"] == "2026-01-01"

    store.union_ids({N1: "2026-03-03"})  # a real new value does land
    assert _row(store, N1)["sitemap_lastmod"] == "2026-03-03"


def test_union_decodes_created_at_from_native_ids_only(store):
    store.union_ids({N1: None, AGGREGATED: None, ANOMALY: None})

    assert _row(store, N1)["created_at"] == "2026-01-01T12:00:00"
    assert _row(store, AGGREGATED)["created_at"] is None
    assert _row(store, ANOMALY)["created_at"] is None
    assert _row(store, ANOMALY)["kind"] == "unknown"


# --- native_ids ordering / filtering --------------------------------------


def test_native_ids_since_excludes_undated_ids(store):
    # Pin the premise: this id IS classified native but decodes to no date.
    assert ids.classify(UNDATED_NATIVE) == "native"
    assert ids.created_at_iso(UNDATED_NATIVE) is None

    store.union_ids({N1: None, N2: None, N3: None, UNDATED_NATIVE: None, AGGREGATED: None})

    assert store.native_ids(since_iso="2026-01-02T00:00:00") == [N3, N2]
    assert store.native_ids(since_iso="2026-01-02T00:00:00", newest_first=False) == [N2, N3]
    assert store.native_ids(since_iso="2027-01-01T00:00:00") == []


def test_unfiltered_native_ids_keep_the_undated_one_last(store):
    store.union_ids({N1: None, N3: None, UNDATED_NATIVE: None, AGGREGATED: None})

    listed = store.native_ids()
    assert listed == [N3, N1, UNDATED_NATIVE]
    assert AGGREGATED not in listed


# --- staleness ------------------------------------------------------------


def test_stale_or_missing_returns_uncached_ids_in_input_order(store):
    store.put_record(CONFIDO, load_fixture(CONFIDO))

    wanted = store.stale_or_missing([N1, CONFIDO, N2], config.RECORD_TTL_SECONDS)
    assert wanted == [N1, N2]  # the freshly cached record is omitted


def test_stale_or_missing_returns_a_cached_record_once_it_ages_past_the_ttl(store):
    store.put_record(CONFIDO, load_fixture(CONFIDO))
    assert store.stale_or_missing([CONFIDO], config.RECORD_TTL_SECONDS) == []

    store.conn.execute(
        "UPDATE records SET fetched_at = ? WHERE hr_number = ?",
        ("2020-01-01T00:00:00", CONFIDO),
    )
    store.conn.commit()

    assert store.stale_or_missing([CONFIDO], config.RECORD_TTL_SECONDS) == [CONFIDO]
    # ... and a TTL wide enough to cover 2020 counts it as fresh again.
    ten_years = 10 * 365 * 24 * 3600
    assert store.stale_or_missing([CONFIDO], ten_years) == []


# --- meta -----------------------------------------------------------------


def test_meta_round_trips_and_overwrites(store):
    assert store.get_meta("last_sync") is None
    assert store.last_sync is None

    store.set_meta("last_sync", "2026-08-20T10:00:00")
    assert store.last_sync == "2026-08-20T10:00:00"

    store.set_meta("last_sync", "2026-08-21T11:00:00")
    assert store.last_sync == "2026-08-21T11:00:00"
    assert store.get_meta("nothing_here") is None
