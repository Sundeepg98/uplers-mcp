"""Shared fixtures for the Uplers reader suite.

Four invariants hold in every test file here:

  * NO NETWORK. Every HTTP interaction goes through httpx.MockTransport,
    handed to UplersClient(transport=...). Nothing ever leaves the box.
  * NO REAL DATA DIR. Every Store is built on pytest's tmp_path (or
    ":memory:"), never on config.DB_PATH.
  * NO REAL PROFILE. `profile.json` is redirected to tmp_path and the resume
    seed source is unset, so a test can neither read the operator's real
    profile nor overwrite it. This is autouse and cannot be opted out of by
    forgetting a fixture.
  * NO BACKGROUND SYNC. UPLERS_AUTO_SYNC=0 for the whole suite, so a tool call
    can never spawn the scheduler task and reach the network behind the
    MockTransport's back. The scheduler is tested by driving it directly.
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


# --- tier-2 isolation -----------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_profile(monkeypatch, tmp_path):
    """Redirect profile.json into tmp_path and unset the resume seed source.

    Autouse on purpose. The profile is the one piece of state a test could
    plausibly clobber for real - it lives beside the database rather than in
    it - so isolation must not depend on remembering to ask for it.
    """
    from uplers_server import profile as profile_mod

    path = tmp_path / "profile.json"
    monkeypatch.setattr(profile_mod, "profile_path", lambda: path)
    monkeypatch.setattr(profile_mod, "resume_path", lambda: None)
    return path


@pytest.fixture(autouse=True)
def no_background_sync(monkeypatch):
    """No tool call may start the background sync task during tests."""
    monkeypatch.setenv("UPLERS_AUTO_SYNC", "0")


@pytest.fixture
def make_profile(isolated_profile):
    """Write a profile to the isolated path and return it."""
    from uplers_server import profile as profile_mod

    def build(**overrides):
        fields = {
            "name": "Test Candidate",
            "years_experience": 5.0,
            "location": "Bangalore, India",
            "skills": ["Node.js", "TypeScript", "AWS", "PostgreSQL", "Python", "React"],
            "source": "test",
        }
        fields.update(overrides)
        candidate = profile_mod.Profile(**fields)
        profile_mod.save(candidate, path=isolated_profile)
        return candidate

    return build


RESUME_MARKDOWN = """# JANE DOE

**Backend Software Engineer** with 6 years of experience building things.

## CONTACT DETAILS

- +91-1000000000
- jane@example.com
- Bangalore, India

## TECHNICAL SKILLS

- **Programming Languages:** JavaScript, TypeScript
- **Frameworks & Tools:** Node.js, Express.js
- **Cloud & Infra:** AWS (S3, Lambda), Docker

## WORK EXPERIENCE

### Engineer | Somewhere
"""


@pytest.fixture
def resume_file(tmp_path):
    """A resume on disk with the structure the parser expects."""
    path = tmp_path / "Resume.md"
    path.write_text(RESUME_MARKDOWN, encoding="utf-8")
    return path
