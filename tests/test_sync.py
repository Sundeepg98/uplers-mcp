"""sync.py - sitemap parsing and the id union + record hydration loop.

The sitemap is a sampler, not an index, so sync_index is judged on what it
UNIONS in and on how honestly it reports what it could not fetch.
"""

from __future__ import annotations

import httpx
import pytest

from uplers_server import config, sync
from uplers_server.client import UplersClient, UplersError

from conftest import AGENTAI, AGGREGATED, load_fixture, make_transport

S1 = "HR010126120000"   # 2026-01-01T12:00:00
S2 = "HR020126120000"   # 2026-01-02T12:00:00
S3 = "HR030126120000"   # 2026-01-03T12:00:00

LOC = "https://platform.uplers.com/talent/all-opportunities/%s"

SITEMAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>" + LOC % S1 + "</loc><lastmod>2026-01-01</lastmod></url>"
    "<url><loc>" + LOC % S2 + "</loc></url>"
    "<url><loc>https://platform.uplers.com/about</loc><lastmod>2026-01-05</lastmod></url>"
    "<url><loc>" + LOC % AGGREGATED + "</loc><lastmod>2026-01-04</lastmod></url>"
    "<url><loc>" + LOC % S3 + "</loc><lastmod>2026-01-03</lastmod></url>"
    "</urlset>"
)


def record_for(hr_number):
    """A real captured record re-labelled with the requested id."""
    raw = dict(load_fixture(AGENTAI))
    raw["HR_Number"] = hr_number
    return raw


def board(sitemap_text=SITEMAP, broken_ids=()):
    """Handler serving the sitemap plus one record per requested hr_number."""

    def handler(request):
        if request.url.path == config.SITEMAP_PATH:
            return httpx.Response(200, text=sitemap_text)
        hr_number = request.url.params.get("hr_number")
        if hr_number in broken_ids:
            return httpx.Response(404, text="gone")
        return httpx.Response(200, json=record_for(hr_number))

    return handler


def make_client(handler):
    transport, calls = make_transport(handler)
    return (UplersClient(transport=transport, delay=0), calls)


def record_calls(calls):
    return [c.url.params["hr_number"] for c in calls if c.url.path == config.RECORD_PATH]


# --- parse_sitemap --------------------------------------------------------


def test_parse_sitemap_maps_ids_to_lastmod_and_counts_every_url():
    discovered, entries = sync.parse_sitemap(SITEMAP)

    assert entries == 5              # the id-less /about entry is counted
    assert len(discovered) == 4      # ... but contributes no id
    assert discovered[S1] == "2026-01-01"
    assert discovered[S2] is None    # the <lastmod> element was absent
    assert discovered[AGGREGATED] == "2026-01-04"
    assert list(discovered) == [S1, S2, AGGREGATED, S3]  # document order


def test_parse_sitemap_keeps_the_first_lastmod_for_a_repeated_id():
    xml = (
        "<urlset>"
        "<url><loc>" + LOC % S1 + "</loc><lastmod>2026-01-01</lastmod></url>"
        "<url><loc>" + LOC % S1 + "</loc><lastmod>2026-02-02</lastmod></url>"
        "</urlset>"
    )
    discovered, entries = sync.parse_sitemap(xml)

    assert entries == 2
    assert discovered == {S1: "2026-01-01"}


def test_parse_sitemap_falls_back_to_raw_id_extraction_without_url_wrappers():
    xml = "<urlset>%s %s %s</urlset>" % (S1, AGGREGATED, S1)
    discovered, entries = sync.parse_sitemap(xml)

    assert discovered == {S1: None, AGGREGATED: None}
    assert entries == 2  # no <url> elements, so the id count stands in


def test_parse_sitemap_on_a_document_with_no_ids_at_all():
    assert sync.parse_sitemap("<urlset></urlset>") == ({}, 0)


# --- sync_index -----------------------------------------------------------


async def test_sync_index_unions_ids_then_hydrates_only_native_records(store):
    client, calls = make_client(board())
    async with client:
        result = await sync.sync_index(store, client)

    assert result.sitemap_entries == 5
    assert result.ids_in_this_fetch == 4
    assert result.new_ids == 4
    assert result.new_native_ids == 3
    assert result.new_aggregated_ids == 1
    assert result.total_known_ids == 4
    assert result.total_known_native == 3
    assert result.total_known_aggregated == 1
    assert result.total_known_unknown_kind == 0

    assert result.native_records_missing == 3
    assert result.records_fetched == 3
    assert result.records_cached_total == 3
    assert result.requests_made == 4      # 1 sitemap + 3 records
    assert result.failures == {}
    assert result.newest_native == [S3, S2, S1]

    # The records really landed, and the aggregated posting was never fetched.
    assert store.cached_ids() == {S1, S2, S3}
    assert store.get_record(S2)[0]["HR_Number"] == S2
    assert AGGREGATED in store.known_ids()
    assert AGGREGATED not in record_calls(calls)
    assert len(store.get_meta("last_sync")) == 19
    assert any("never deleted on absence" in note for note in result.notes)


async def test_fetch_budget_caps_the_batch_and_says_how_many_remain(store):
    client, calls = make_client(board())
    async with client:
        result = await sync.sync_index(store, client, fetch_budget=2)

    assert result.native_records_missing == 3
    assert result.records_fetched == 2
    assert sorted(record_calls(calls)) == sorted([S3, S2])  # newest first
    assert store.cached_ids() == {S2, S3}
    assert any(
        "1 native record(s) still need fetching; fetch_budget was 2" in note
        for note in result.notes
    )


async def test_a_second_sync_adds_no_ids_and_refetches_nothing_fresh(store):
    client, calls = make_client(board())
    async with client:
        first = await sync.sync_index(store, client)
        second = await sync.sync_index(store, client)

    assert first.new_ids == 4
    assert second.new_ids == 0
    assert second.total_known_ids == 4          # union, not replace
    assert second.native_records_missing == 0
    assert second.records_fetched == 0
    # Exactly one round of record fetches happened, during the first sync.
    assert sorted(record_calls(calls)) == sorted([S1, S2, S3])


async def test_hydrate_false_indexes_ids_without_fetching_records(store):
    client, calls = make_client(board())
    async with client:
        result = await sync.sync_index(store, client, hydrate=False)

    assert result.total_known_ids == 4
    assert result.records_fetched == 0
    assert result.native_records_missing == 3
    assert record_calls(calls) == []
    assert len(calls) == 1
    assert any("hydrate=False" in note for note in result.notes)


async def test_a_failed_record_is_reported_never_silently_skipped(store):
    client, _ = make_client(board(broken_ids=(S2,)))
    async with client:
        result = await sync.sync_index(store, client)

    assert result.records_fetched == 2
    assert list(result.failures) == [S2]
    assert "HTTP 404" in result.failures[S2]
    assert store.cached_ids() == {S1, S3}
    assert any("NOT silently skipped" in note for note in result.notes)


async def test_a_sitemap_failure_raises_instead_of_looking_like_an_empty_board(store):
    def handler(request):
        return httpx.Response(503, text="maintenance")

    client, _ = make_client(handler)
    async with client:
        with pytest.raises(UplersError) as excinfo:
            await sync.sync_index(store, client)

    assert "HTTP 503" in str(excinfo.value)
    assert store.known_ids() == set()
    assert store.count_records()["total"] == 0
