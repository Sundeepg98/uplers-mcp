"""client.py - the HTTP layer.

The whole point of this module is that a failure is LOUD: it raises, or it is
listed in a FetchReport. Nothing is allowed to decay into an empty result that
reads like "no matches". Every request below is served by httpx.MockTransport;
nothing here touches the network.
"""

from __future__ import annotations

import httpx
import pytest

from uplers_server import config
from uplers_server.client import (
    FetchReport,
    RateLimitExhausted,
    UplersClient,
    UplersError,
)

from conftest import AGENTAI, CONFIDO, GOFORMA, load_fixture, make_transport

MISSING = "HR010126120000"

SITEMAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://platform.uplers.com/talent/all-opportunities/" + CONFIDO + "</loc>"
    "<lastmod>2026-08-01</lastmod></url>"
    "</urlset>"
)


def make_client(handler, **kwargs):
    """A client wired to a MockTransport, with politeness delays off."""
    transport, calls = make_transport(handler)
    kwargs.setdefault("delay", 0)
    return (UplersClient(transport=transport, **kwargs), calls)


def serve_fixtures(status_for_missing=404, headers=None):
    """Serve captured records by hr_number; anything unknown gets an error."""

    def handler(request):
        hr_number = request.url.params.get("hr_number")
        if hr_number in (CONFIDO, AGENTAI, GOFORMA):
            return httpx.Response(200, json=load_fixture(hr_number), headers=headers or {})
        return httpx.Response(status_for_missing, text="no such requisition")

    return handler


# --- the happy path -------------------------------------------------------


async def test_get_record_requests_the_public_endpoint_and_returns_the_payload():
    client, calls = make_client(serve_fixtures())
    async with client:
        record = await client.get_record(CONFIDO)

    assert record["HR_Number"] == CONFIDO
    assert len(calls) == 1
    assert calls[0].url.path == config.RECORD_PATH
    assert calls[0].url.params["hr_number"] == CONFIDO
    assert client.requests_made == 1


async def test_get_sitemap_returns_the_xml_text():
    client, calls = make_client(lambda request: httpx.Response(200, text=SITEMAP))
    async with client:
        text = await client.get_sitemap()

    assert text == SITEMAP
    assert calls[0].url.path == config.SITEMAP_PATH


# --- loud failures --------------------------------------------------------


async def test_a_persistent_500_is_retried_and_then_raises():
    client, calls = make_client(lambda request: httpx.Response(500, text="boom"))
    async with client:
        with pytest.raises(UplersError) as excinfo:
            await client.get_record(CONFIDO)

    assert len(calls) == config.MAX_RETRIES == 3
    assert "HTTP 500" in str(excinfo.value)
    assert "3 attempt(s)" in str(excinfo.value)


async def test_a_404_raises_immediately_without_retrying():
    client, calls = make_client(lambda request: httpx.Response(404, text="gone"))
    async with client:
        with pytest.raises(UplersError) as excinfo:
            await client.get_record(MISSING)

    assert len(calls) == 1  # a 4xx will not fix itself
    assert "HTTP 404" in str(excinfo.value)
    assert "1 attempt(s)" in str(excinfo.value)


async def test_a_transport_level_error_is_retried_and_reported_by_name():
    def handler(request):
        raise httpx.ConnectError("no route to host", request=request)

    client, calls = make_client(handler)
    async with client:
        with pytest.raises(UplersError) as excinfo:
            await client.get_record(CONFIDO)

    assert len(calls) == 3
    assert "ConnectError" in str(excinfo.value)


async def test_a_non_json_body_raises_rather_than_returning_nothing():
    def handler(request):
        return httpx.Response(200, text="<html>maintenance</html>",
                              headers={"content-type": "text/html"})

    client, calls = make_client(handler)
    async with client:
        with pytest.raises(UplersError) as excinfo:
            await client.get_record(CONFIDO)

    assert len(calls) == 1
    assert "non-JSON" in str(excinfo.value)
    assert "text/html" in str(excinfo.value)


async def test_a_json_payload_without_hr_number_raises():
    client, _ = make_client(lambda request: httpx.Response(200, json={"error": "nope"}))
    async with client:
        with pytest.raises(UplersError) as excinfo:
            await client.get_record(CONFIDO)

    assert "unexpected payload" in str(excinfo.value)


async def test_a_json_payload_that_is_not_an_object_raises():
    client, _ = make_client(lambda request: httpx.Response(200, json=[1, 2, 3]))
    async with client:
        with pytest.raises(UplersError) as excinfo:
            await client.get_record(CONFIDO)

    assert "unexpected payload" in str(excinfo.value)
    assert "list" in str(excinfo.value)


async def test_get_sitemap_rejects_a_body_that_is_not_a_sitemap():
    client, _ = make_client(lambda request: httpx.Response(200, text="<html>hello</html>"))
    async with client:
        with pytest.raises(UplersError) as excinfo:
            await client.get_sitemap()

    assert "did not look like a sitemap" in str(excinfo.value)


# --- batches report both halves ------------------------------------------


async def test_get_records_reports_failures_alongside_successes():
    client, calls = make_client(serve_fixtures())
    async with client:
        report = await client.get_records([CONFIDO, MISSING, AGENTAI])

    assert sorted(report.records) == sorted([CONFIDO, AGENTAI])
    assert report.records[CONFIDO]["HR_Number"] == CONFIDO
    # The failing id is named, with a reason. It does NOT vanish.
    assert list(report.failures) == [MISSING]
    assert "HTTP 404" in report.failures[MISSING]
    assert MISSING not in report.records
    assert report.ok is False
    assert report.requests_made == 3
    assert len(calls) == 3


async def test_get_records_is_ok_only_when_every_id_landed():
    client, _ = make_client(serve_fixtures())
    async with client:
        report = await client.get_records([CONFIDO, AGENTAI, GOFORMA])

    assert sorted(report.records) == sorted([AGENTAI, CONFIDO, GOFORMA])
    assert report.failures == {}
    assert report.ok is True


async def test_an_empty_batch_makes_no_requests():
    client, calls = make_client(serve_fixtures())
    async with client:
        report = await client.get_records([])

    assert calls == []
    assert report.records == {}
    assert report.ok is True


# --- rate limiting --------------------------------------------------------


async def test_a_healthy_ratelimit_header_is_recorded_and_does_not_stop_anything():
    client, _ = make_client(serve_fixtures(headers={"X-RateLimit-Remaining": "468"}))
    async with client:
        await client.get_record(CONFIDO)

    assert client.ratelimit_remaining == 468


async def test_a_ratelimit_below_the_abort_floor_raises_out_of_get_record():
    low = str(config.RATELIMIT_ABORT_BELOW - 15)  # 5, well under the floor of 20
    client, _ = make_client(serve_fixtures(headers={"X-RateLimit-Remaining": low}))
    async with client:
        with pytest.raises(RateLimitExhausted) as excinfo:
            await client.get_record(CONFIDO)

    assert isinstance(excinfo.value, UplersError)
    assert "abort floor 20" in str(excinfo.value)
    assert client.ratelimit_remaining == 5


async def test_a_ratelimit_abort_is_reported_by_the_batch_not_raised_out_of_it():
    client, _ = make_client(serve_fixtures(headers={"X-RateLimit-Remaining": "5"}))
    async with client:
        report = await client.get_records([CONFIDO])

    assert isinstance(report, FetchReport)
    assert report.records == {}
    assert report.aborted_reason is not None
    assert "rate-limit window" in report.aborted_reason
    assert report.ratelimit_remaining == 5
    assert report.ok is False


async def test_an_unparseable_ratelimit_header_is_ignored():
    client, _ = make_client(serve_fixtures(headers={"X-RateLimit-Remaining": "plenty"}))
    async with client:
        record = await client.get_record(CONFIDO)

    assert record["HR_Number"] == CONFIDO
    assert client.ratelimit_remaining is None
