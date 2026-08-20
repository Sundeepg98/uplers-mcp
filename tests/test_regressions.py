"""Regressions caught by the first live run against the real Uplers API.

Both bugs were of the same family the brief calls out: a tool reporting a
number that quietly understated reality, so the caller could not tell a
truncated page from the whole truth.
"""

from __future__ import annotations

import pytest

import server
from conftest import AGGREGATED, ALL_IDS, NATIVE_IDS, load_fixture, put_fixtures


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


def seed(store_factory, hr_numbers=ALL_IDS):
    store = store_factory()
    put_fixtures(store, hr_numbers)
    store.union_ids({hr_number: None for hr_number in hr_numbers})
    store.close()


async def test_list_new_since_matched_is_the_true_total_not_the_page_size(tools):
    """Live run: since=2026-08-01 and since=2026-07-01 both reported matched=6
    with limit=6, because `matched` came from the already-truncated page. The
    real totals were 66 and 137. `matched` must count every hydrated candidate.
    """
    seed(tools)
    # Four of the six fixtures are native ids with a decodable creation date.
    datable = [
        hr for hr in NATIVE_IDS if server.ids.decode_created_at(hr) is not None
    ]
    assert len(datable) == 4

    page = await server.uplers_list_new_since(iso_date="2025-01-01", limit=2)
    assert page.returned == 2
    assert page.matched == 4, "matched must not be clamped to limit"
    assert any("Showing 2 of 4" in note for note in page.notes)

    whole = await server.uplers_list_new_since(iso_date="2025-01-01", limit=50)
    assert whole.matched == 4
    assert whole.returned == 4
    assert not any(note.startswith("Showing") for note in whole.notes)


async def test_list_new_since_matched_tracks_the_date_filter(tools):
    """A later `since` must genuinely shrink `matched`, not just the page."""
    seed(tools)
    early = await server.uplers_list_new_since(iso_date="2025-01-01", limit=50)
    late = await server.uplers_list_new_since(iso_date="2026-08-01", limit=50)
    assert early.matched == 4
    assert late.matched == 1  # only the 2026-08-13 fixture qualifies
    assert late.results[0].hr_number == "HR130826031902"


async def test_include_aggregated_says_so_when_nothing_aggregated_is_cached(tools):
    """Live run: include_aggregated=True returned only native rows with no
    explanation, because sync hydrates native records only. Silence there is
    indistinguishable from "there are no aggregated jobs", which is false.
    """
    store = tools()
    put_fixtures(store, NATIVE_IDS)          # native records only
    store.union_ids({AGGREGATED: None})      # aggregated id KNOWN but not fetched
    store.close()

    result = await server.uplers_search_opportunities(include_aggregated=True, limit=10)
    assert all(o.is_native for o in result.results)
    explanation = [n for n in result.notes if "had no effect" in n]
    assert explanation, "an ineffective include_aggregated must be explained"
    assert "1 aggregated id(s) are indexed" in explanation[0]


async def test_include_aggregated_does_surface_them_when_they_are_cached(tools):
    """The counterpart: with an aggregated record actually cached, it appears
    and the 'had no effect' note does NOT."""
    seed(tools)
    result = await server.uplers_search_opportunities(include_aggregated=True, limit=10)
    assert any(not o.is_native for o in result.results)
    assert not any("had no effect" in n for n in result.notes)
    assert any("Check `is_native`" in n for n in result.notes)

    native_only = await server.uplers_search_opportunities(limit=10)
    assert all(o.is_native for o in native_only.results)
    assert native_only.matched == len(NATIVE_IDS)


async def test_aggregated_fixture_is_actually_aggregated():
    """Guard the guard: the regression above is meaningless if the fixture
    stopped being an aggregated record."""
    raw = load_fixture(AGGREGATED)
    assert raw["is_aggregator_job"] is True
    assert raw["job_nature"] == "Aggregated"
