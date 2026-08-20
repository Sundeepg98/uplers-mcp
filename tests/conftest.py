"""Shared fixtures for the Uplers reader suite.

Two invariants hold in every test file here:

  * NO NETWORK. Every HTTP interaction goes through httpx.MockTransport,
    handed to UplersClient(transport=...). Nothing ever leaves the box.
  * NO REAL DATA DIR. Every Store is built on pytest's tmp_path (or
    ":memory:"), never on config.DB_PATH.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

# The six captured live responses. Comments record why each one is here; the
# values are asserted against tests/fixtures/MANIFEST.md.
CONFIDO = "HR100725001919"          # native, "Upto INR" ceiling, Hybrid, 1 assessment
AGENTAI = "HR130826031902"          # native, USD/year band, Remote, 0 assessments
PRECISELY = "HR290626125252"        # native, Confidential budget, joining "Immediately"
GOFORMA = "HR310725131019"          # native, GBP/month band, Part Time
ANOMALY = "HR0191124125506"         # 13-digit id -> classify() "unknown", record is native
AGGREGATED = "HR1173448373079993"   # 16-digit id, is_aggregator_job True

NATIVE_IDS = (CONFIDO, AGENTAI, PRECISELY, GOFORMA, ANOMALY)
ALL_IDS = NATIVE_IDS + (AGGREGATED,)


def load_fixture(hr_number: str) -> dict:
    """Read one captured response. UTF-8 always - the bodies are not ASCII."""
    path = FIXTURE_DIR / (hr_number + ".json")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def put_fixtures(store, hr_numbers=ALL_IDS):
    """Cache the given captured records in a Store."""
    for hr_number in hr_numbers:
        store.put_record(hr_number, load_fixture(hr_number))
    return store


def make_transport(handler):
    """(MockTransport, calls) - `calls` collects every httpx.Request served."""
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    return (httpx.MockTransport(wrapped), calls)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Politeness delays and retry backoffs must not cost wall-clock time.

    Yields to the loop exactly like the real sleep, but for 0 seconds, so
    retry/abort ordering is preserved while the suite stays fast.
    """
    real_sleep = asyncio.sleep

    async def instant(delay, result=None):
        return await real_sleep(0, result)

    monkeypatch.setattr(asyncio, "sleep", instant)


@pytest.fixture
def store_factory(tmp_path):
    """Factory of FRESH Store objects over one temp sqlite file.

    A factory rather than a single object because the tools run
    `with _open_store() as store:` and Store.__exit__ closes the connection.
    """
    from uplers_server.store import Store

    db_path = tmp_path / "t.sqlite3"
    opened = []

    def make():
        store = Store(db_path)
        opened.append(store)
        return store

    yield make
    for store in opened:
        store.close()


@pytest.fixture
def store(store_factory):
    return store_factory()


@pytest.fixture
def fixture_record():
    return load_fixture


@pytest.fixture
def all_records():
    """All six captured records, in a fixed order."""
    return [load_fixture(hr_number) for hr_number in ALL_IDS]


@pytest.fixture
def native_records():
    """The five records whose is_aggregator_job is False."""
    return [load_fixture(hr_number) for hr_number in NATIVE_IDS]
