"""Shared fixtures for the Uplers reader suite.

Five invariants hold in every test file here:

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
  * NO AMBIENT CONFIG. JOBHUNT_CONFIG=:none: for the whole suite, so a shared
    jobhunt.json anywhere up the tree cannot change what a test asserts. Also
    autouse, for the same reason.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# scripts/ carries credential_echo_control, whose TRANSFORMS tuple the leak
# controls parametrise off. Importing the adversary's own list is the point:
# a spelling with no control cannot exist if the controls are generated from
# the list rather than kept by hand beside it.
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

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


# The four AUTHENTICATED envelopes, captured live by
# `scripts/capture_talent_rows.py` with the private half deleted. They exist
# because the four surfaces spell the SAME two fields differently, and three of
# the four were being read with the public catalogue's spelling. See
# tests/fixtures/MANIFEST.md.
TALENT_PIPELINE = "talent_pipeline"    # GET  talent/hr/my-opportunities
TALENT_FEED = "talent_feed"            # GET  talent/hr/opportunities
TALENT_TAILOR = "talent_tailor"        # POST talent/hr/tailor-jobs
TALENT_INTERVIEWS = "talent_interviews"  # GET talent/outreach/interview-list


def load_talent_fixture(name: str) -> dict:
    """Read one captured AUTHENTICATED envelope, whole and unmodified."""
    with (FIXTURE_DIR / (name + ".json")).open(encoding="utf-8") as handle:
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


@pytest.fixture(autouse=True)
def no_ambient_config(monkeypatch):
    """NO AMBIENT CONFIG. The suite never reads the operator's real jobhunt.json.

    The fifth invariant, and the same reason as the fourth: a shared config
    file sitting anywhere up the tree from this checkout would silently change
    what these tests assert, and the failure would look like a scoring bug on
    whichever machine happened to have one. `:none:` is jobcore's explicit
    disable token - an EMPTY value deliberately means "unset, keep searching",
    so setting the variable to "" would not isolate anything.

    A test that wants a config writes one and passes its path; see
    tests/test_policy_wiring.py.
    """
    monkeypatch.setenv("JOBHUNT_CONFIG", ":none:")
    monkeypatch.delenv("JOBHUNT_HOME", raising=False)
    monkeypatch.delenv("JOBHUNT_DISABLE", raising=False)
    from uplers_server import policy as policy_mod

    policy_mod.invalidate()
    yield
    policy_mod.invalidate()


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


# --- the credential leak detector ------------------------------------------
#
# Every "the token never leaks" assertion in this suite runs through the two
# functions below, so the detector is written ONCE and its controls live in
# tests/test_session_lifecycle.py rather than being re-improvised per file.
#
# WHY IT IS NOT JUST `secret in text`. The credential this server actually
# holds is a JWT: three base64url segments. That shape defeats a substring
# hunt in two directions at once, and BOTH were MEASURED blind on this suite
# on 2026-08-23 before this was written:
#
#   * a payload echoing only the CLAIMS SEGMENT (`token.split(".")[1]`) is not
#     a superstring of the token, so `secret in text` never fires - yet that
#     one segment carries the whole identity half of the credential;
#   * a payload echoing the DECODED claims (which `session.token_expiry` already
#     parses, so the decoded form is one line away in production code) shares no
#     substring with the token at all, because the marker inside a base64url
#     segment is not present in the encoded form.
#
# The sibling naukri server was bitten by the second shape directly: its walker
# hunted a plaintext marker that never appears inside a base64url JWT, so every
# leak test there would have passed a result echoing the entire credential.
#
# WHY THE OLD PREFIX RULE WAS WORSE THAN NOTHING. The rule it replaces was
# `secret in text or secret[:12] in text`. For a JWT, `secret[:12]` is
# "eyJhbGciOiJI" - the base64 of a standard HS256 header, IDENTICAL across
# every token of that format and MEASURED identical across all three JWTs in
# this suite. It therefore contributed zero credential-specific signal on the
# one shape that matters, while firing on any prose that merely describes what
# a JWT looks like. A check that matches a constant is not guarding a secret.

#: Below this length a fragment stops being an identifier and starts being a
#: word, and the detector would report prose. It is also the RUN length: every
#: window of this size inside a fragment is hunted, not just the whole
#: fragment, because the two leaks a whole-string hunt cannot see are a
#: TRUNCATING redaction ("safe" 12-char fingerprints) and a value SPLIT across
#: two display fields. Both were MEASURED green on 2026-08-23 by
#: scripts/leak_matrix.py before this was written.
MIN_FRAGMENT = 12

#: Any three base64url segments. The ONLY rule here that can catch a leak of
#: his REAL token down a path no test planted a canary into - every other rule
#: needs to know the value in advance, and by construction no test knows the
#: live credential.
JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")


def _b64url_json(segment: str):
    """One base64url segment decoded as JSON, or None if it is not that."""
    try:
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        return json.loads(raw)
    except Exception:                                    # noqa: BLE001
        return None


def _encodings(secret: str) -> set:
    """The same credential, spelled the ways a leaking build spells it.

    THE ENCODING DOES NOT HAVE TO LIVE IN THE CREDENTIAL - IT CAN LIVE IN THE
    LEAK PATH. A build that base64s the token on its way out shares no
    substring with the token, so hunting the token finds nothing while the
    whole value ships. Measured, not argued: before these four spellings were
    added, `scripts/leak_matrix.py` reported the b64, b64url and hex rows
    caught by exactly ONE of eight guarded assertions.

    Kept in step with `scripts/credential_echo_control.py::render`, which is
    the adversary these exist to answer.
    """
    raw = secret.encode("utf-8")
    return {
        base64.b64encode(raw).decode("ascii"),
        base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="),
        raw.hex(),
        quote(secret, safe=""),
    }


def _raw_fragments(secret: str) -> set:
    """Every string derivable FROM this credential that would disclose it."""
    found = {secret}
    for segment in secret.split("."):
        if len(segment) >= MIN_FRAGMENT:
            found.add(segment)
        claims = _b64url_json(segment)
        if isinstance(claims, dict):
            for value in claims.values():
                if isinstance(value, str) and len(value) >= MIN_FRAGMENT:
                    found.add(value)
    if "|" in secret:
        tail = secret.split("|", 1)[1]
        if len(tail) >= MIN_FRAGMENT:
            found.add(tail)
    found |= _encodings(secret)
    return {piece for piece in found if len(piece) >= MIN_FRAGMENT}


def _runs(piece: str) -> set:
    """Every MIN_FRAGMENT-length window of a fragment.

    A truncated fingerprint and a value split across two fields are both
    SUBSTRINGS of the credential rather than the whole of it, so a whole-string
    hunt is structurally unable to see either.
    """
    if len(piece) <= MIN_FRAGMENT:
        return {piece}
    return {piece[i:i + MIN_FRAGMENT] for i in range(len(piece) - MIN_FRAGMENT + 1)}


def secret_fragments(secrets, format_decoys=()) -> dict:
    """Map each secret to the RUNS whose appearance would disclose it.

    `format_decoys` are credentials of the SAME FORMAT but a different value.
    Anything a secret shares with a decoy is derivable from the format alone -
    a JWT's header segment is the whole reason this argument exists - and is
    therefore NOT evidence that this credential leaked. Subtracting them keeps
    the detector from reporting prose, and it is a measurement rather than a
    judgement: two unrelated credentials sharing a string is exactly what "not
    identifying" means.

    THE SUBTRACTION HAPPENS AT RUN LEVEL, NOT FRAGMENT LEVEL, and that is not
    a detail. Subtracting whole fragments removes the header segment but
    leaves every 12-character window INSIDE it, so the moment run-hunting was
    added the generic-header false positive came straight back - measured on
    2026-08-23, two controls red. A rule and its exception have to be written
    at the same granularity or the exception does not apply.

    Runs are expanded once, here, rather than per-payload in `leaks_of`.
    """
    generic = set()
    for decoy in format_decoys:
        for piece in _raw_fragments(decoy):
            generic |= _runs(piece)

    hunted = {}
    for secret in secrets:
        runs = set()
        for piece in _raw_fragments(secret):
            runs |= _runs(piece)
        hunted[secret] = frozenset(runs - generic)
    return hunted


def leaks_of(payload, fragments) -> list:
    """Every (trail, secret, fragment) where a credential surfaced in a payload.

    `fragments` is a mapping from :func:`secret_fragments`. Returns a list so a
    failing assertion prints WHAT leaked and WHERE, not just that it did.

    Three rules, and they fail in different directions on purpose:
      * every RUN of every fragment, which covers truncation and splitting;
      * the encoded spellings, which cover a leak path that re-encodes;
      * JWT_SHAPE, which needs no canary at all and is therefore the only rule
        that could catch his real token escaping down an unplanted path.
    """
    found = []
    for trail, text in walk_strings(payload):
        shaped = JWT_SHAPE.search(text)
        if shaped:
            found.append((trail, "<jwt-shape>", shaped.group()[:16]))
        for secret, runs in fragments.items():
            for run in runs:
                if run in text:
                    found.append((trail, secret, run))
                    break
    return found


def walk_strings(node, trail="$"):
    """Every string in a payload, with the path that reached it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(value, "%s.%s" % (trail, key))
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            yield from walk_strings(item, "%s[%d]" % (trail, index))
    elif isinstance(node, str):
        yield (trail, node)


def tool_schema(tool, which="output"):
    """A tool's declared schema, whichever spelling this mcp uses.

    `Tool` spells these `inputSchema`/`outputSchema` on mcp 1.26 and
    `input_schema`/`output_schema` on mcp 2.0.0, and requirements.txt declares
    `mcp[cli]>=1.26,<3` - so BOTH are inside the supported range and a test that
    picks one is blind on the other half of it.

    THIS EXISTS BECAUSE THE SAME DEFECT HAPPENED TWICE. It was found and fixed
    once in `test_server_info.py`, and the fix was local to that file, so the
    knowledge did not travel: a later test read `outputSchema` on a 2.0.0 box,
    found nothing, and was saved only by its own premise check. A rule written
    in one test's docstring is not a rule; a shared helper is.

    Returns `{}` when the tool declares no such schema, so a caller can tell
    "no schema" from "wrong attribute name" - the second is what this prevents.
    """
    camel = "%sSchema" % which
    snake = "%s_schema" % which
    return getattr(tool, camel, None) or getattr(tool, snake, None) or {}
