"""server.py - the AUTHENTICATED tier, and the two failures it exists to prevent.

Thirteen tools live below the `THE AUTHENTICATED TIER` banner in server.py. They
are tested apart from `test_tools.py` for the same reason they are separated in
the source: the difference is a safety property, not bookkeeping. Every tool
here needs a live session, and two of them can change something on Uplers that
this server cannot change back.

Two failure classes drive almost every test in this file.

**A write that was not asked for.** `uplers_apply` expresses interest, which on
Uplers IS applying, and Uplers ships no withdraw, no cancel and no un-apply
anywhere in their product. So the first test in this file does not check what
`confirm=False` RETURNS - it checks what it SENT, by looking at every request
the transport actually served, and asserting the apply route is not among them.
A preview that quietly posted would return a perfectly plausible preview.

**A session that expired reading as "nothing matched today".** Uplers sessions
are short-lived, so a 401 is a routine event rather than an exotic one. An
authenticated read that turned one into `[]` would be indistinguishable from a
genuinely quiet day, and the operator would stop looking. Every read is
therefore checked twice over: once against a 401, and once against a 200 whose
envelope is not the expected one. Both must RAISE.

Isolation, all four autouse and none opt-out-able:
  * NO NETWORK. Every response comes from httpx.MockTransport, handed to a
    TalentClient built by `wire_talent`.
  * NO REAL SESSION FILE. `server._session_store` and `session.session_path` both
    point at tmp_path, so no test can read or delete the operator's real bearer
    token at `data/session.json`.
  * NO REAL DATA DIR. `server._open_store` is a tmp_path factory, and
    `server.UplersClient` (the PUBLIC tier's client) raises on construction, so
    a mis-wired test fails instead of leaving the box.
  * NO REAL BROWSER. `auth.login_via_browser` raises unless a test replaces it.
    The login handshake itself is covered in test_auth.py, over fake browser
    objects; the only login behaviour tested here is what this tool does when
    Playwright is missing.
"""

from __future__ import annotations

import copy
import json

import httpx
import pytest

import server
from uplers_server import auth as auth_mod
from uplers_server import endpoints
from uplers_server import session as session_mod
from uplers_server.client import UplersError
from uplers_server.models import OpportunityDetail
from uplers_server.session import SessionStore
from uplers_server.talent import AuthRequired, TalentClient, TalentError
from uplers_server.talent_models import (
    AuthStatus,
    FieldReport,
    InterviewList,
    LoginResult,
    PipelineResult,
    ProfileComparison,
    TalentFeed,
    TalentProfileResult,
    WritePreview,
    WriteResult,
)

from conftest import AGENTAI, load_fixture, make_transport, put_fixtures

#: The numeric id Uplers' own record for AGENTAI carries. Read from the captured
#: response rather than typed, because `hr_id` is the field an apply sends and a
#: wrong one there is a silent no-op or a 422 - see endpoints.IDENTIFIER_SPACES.
JOB_ID = load_fixture(AGENTAI)["id"]

#: Uplers' MEASURED logged-out body for talent/* with Accept: application/json.
UNAUTHENTICATED = {"message": "Unauthenticated."}

#: A 200 whose body is the wrong shape. Not empty, not an error - just missing
#: the one key each reader needs. This is what a renamed key looks like.
CHANGED_SHAPE = {"message": "ok", "unexpected": True}

TOKEN = "42|bearer-token-that-must-never-be-printed"


# --- records --------------------------------------------------------------


def auth_record(**extra):
    """A captured PUBLIC record dressed as the authenticated view of the same job.

    Built from a real capture rather than invented, so the 112 fields the
    shaping code reads are the ones Uplers actually sends.

    `statusName` is set to a string on every record here, and that is not
    cosmetic. `talent_shape.to_talent_row` resolves `uplers_status` as
    `_first(raw, "statusName", "status_name", "status")`, and every captured
    live record carries `status: 1` - an integer - with no `statusName` beside
    it. A record without a string `statusName` therefore feeds `1` into
    `TalentRow.uplers_status`, which is typed `str | None`. See the bug filed
    against talent_shape.py; these tests pin the intended behaviour of the
    tools, not that defect.
    """
    record = copy.deepcopy(load_fixture(AGENTAI))
    record["statusName"] = "New"
    record.update(extra)
    return record


def paginated(rows, *, page=1, last_page=1, total=None):
    """Uplers' Laravel paginator envelope: rows live at res["hrs"]["data"]."""
    envelope = {"data": list(rows), "current_page": page, "last_page": last_page}
    if total is not None:
        envelope["total"] = total
    return {"hrs": envelope}


# --- handlers -------------------------------------------------------------


def reject(request):
    """Every route answers 401. An expired session, exactly as Uplers sends it."""
    return httpx.Response(401, json=UNAUTHENTICATED)


def serve(payload):
    """Answer every request with the same 200 JSON body."""
    return lambda request: httpx.Response(200, json=payload)


def single_hr_then(record, write_response=None):
    """GET single-hr answers with `record`; every other route is the write."""

    def handler(request):
        if request.url.path.endswith(endpoints.EP_SINGLE_HR):
            return httpx.Response(200, json=record)
        return httpx.Response(200, json=write_response or {"status": "success"})

    return handler


# --- wiring ---------------------------------------------------------------


def wire_talent(monkeypatch, handler, token=TOKEN):
    """Let a tool build a real TalentClient, but over a MockTransport.

    Mirrors `wire_client` in test_tools.py. The returned `calls` list collects
    every httpx.Request the transport served, which is how the write tests
    prove a request was NOT made.
    """
    transport, calls = make_transport(handler)
    monkeypatch.setattr(
        server,
        "TalentClient",
        lambda *a, **k: TalentClient(lambda: token, transport=transport, delay=0),
    )
    return calls


def writes(calls):
    """Every request that was not a read. A write tool's whole risk surface."""
    return [call for call in calls if call.method != "GET"]


def paths(calls):
    return [call.url.path for call in calls]


class NoNetwork:
    """Stand-in for the PUBLIC tier's UplersClient: constructing one fails."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("this tool must not construct a public HTTP client")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(server, "UplersClient", NoNetwork)


@pytest.fixture(autouse=True)
def session_file(monkeypatch, tmp_path):
    """No test may read, write or delete the real data/session.json.

    Autouse and belt-and-braces: `server._session_store` is the constructor the
    tools call, and `session.session_path` is what a default-constructed
    SessionStore anywhere else would resolve to. Both go to tmp_path, because
    the file this guards holds a live bearer token and `uplers_logout` deletes
    it.
    """
    path = tmp_path / "session.json"
    monkeypatch.setattr(session_mod, "session_path", lambda: path)
    monkeypatch.setattr(server, "_session_store", lambda: SessionStore(path))
    return path


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    """Nothing here opens a browser. test_auth.py owns the login handshake."""

    def refuse(*args, **kwargs):
        raise AssertionError("no test in this file may open a browser")

    monkeypatch.setattr(auth_mod, "login_via_browser", refuse)


@pytest.fixture(autouse=True)
def tools(monkeypatch, store_factory):
    """Point the tools at a temp store; returns the factory for inspection."""
    monkeypatch.setattr(server, "_open_store", store_factory)
    return store_factory


# ==========================================================================
# GROUP W - the write surface. These are the most important tests here.
# ==========================================================================


async def test_apply_without_confirm_performs_absolutely_nothing(monkeypatch):
    """THE test in this file. `confirm=False` must not touch the apply route.

    This asserts on what was SENT, not on what was returned, and the difference
    is the entire point: a preview that had already posted would still return a
    perfectly plausible preview object, and every other assertion in this file
    would still pass.

    It matters more here than anywhere else in this server because expressing
    interest on Uplers CANNOT BE UNDONE. Their product ships no withdraw, no
    cancel and no un-apply; the only thing that retracts an application is
    deactivating the whole account. A default-argument mistake in this tool is
    therefore not a bug that can be fixed by running it again - it is permanent,
    it lands on a real requisition with a real client on the other end, and the
    operator finds out from a recruiter.

    Building the preview is allowed to READ (it fetches single-hr for the
    numeric id and the current state). It is allowed to send nothing else.
    """
    calls = wire_talent(monkeypatch, single_hr_then(auth_record()))

    result = await server.uplers_apply(AGENTAI)

    # 1. Not one request to the apply route. This is the assertion that counts.
    assert endpoints.EP_INTRESTED not in " ".join(paths(calls))
    assert [call for call in calls if call.url.path.endswith(endpoints.EP_INTRESTED)] == []

    # 2. Nothing was POSTed at all - not to the apply route, not to any other.
    assert writes(calls) == []

    # 3. What it DID do: exactly one read, to build the preview.
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert calls[0].url.path.endswith(endpoints.EP_SINGLE_HR)
    assert calls[0].url.params["hr_number"] == AGENTAI

    # 4. And it says so, rather than leaving "it did not happen" to be inferred.
    assert isinstance(result, WritePreview)
    assert result.performed is False


async def test_apply_preview_states_the_exact_request_and_that_it_is_permanent(monkeypatch):
    wire_talent(monkeypatch, single_hr_then(auth_record()))

    result = await server.uplers_apply(AGENTAI)

    assert result.performed is False
    assert result.reversible is False
    assert result.action == "apply"
    assert result.endpoint == endpoints.EP_INTRESTED
    assert result.method == "POST multipart/form-data"

    # The body is stated exactly, in the identifier space the route wants:
    # the plain numeric id, not enc_id and not the HR number.
    assert result.body == {"hr_id": JOB_ID, "intrested": 1}
    assert isinstance(result.body["hr_id"], int)

    # The warning has to say the thing that makes this different from a save:
    # that there is no way back, in the words Uplers' own product uses.
    assert result.warning is not None
    assert "PERMANENT" in result.warning
    assert "withdraw" in result.warning
    assert "un-apply" in result.warning

    # And the operator is told the one call that would perform it.
    assert result.to_confirm == 'uplers_apply("%s", confirm=True)' % AGENTAI

    # Enough of the job to recognise it before agreeing to something permanent.
    assert result.hr_number == AGENTAI
    assert result.title == "AI Full Stack Engineer"
    assert result.company == "AgentAI"


async def test_apply_with_confirm_posts_multipart_to_the_intrested_route(monkeypatch):
    """confirm=True is the only path that sends, and it sends what a browser sends.

    Uplers' own call site builds a FormData, so this is multipart/form-data and
    not JSON. Getting that wrong is a 422 at best.
    """
    calls = wire_talent(
        monkeypatch, single_hr_then(auth_record(), write_response={"status": "success"})
    )

    result = await server.uplers_apply(AGENTAI, confirm=True)

    posted = writes(calls)
    assert len(posted) == 1
    post = posted[0]
    assert post.method == "POST"
    assert post.url.path.endswith(endpoints.EP_INTRESTED)
    assert post.headers["content-type"].startswith("multipart/form-data")

    body = post.content.decode()
    assert 'name="hr_id"' in body
    assert str(JOB_ID) in body
    assert 'name="intrested"' in body
    assert "application/json" not in post.headers["content-type"]

    assert isinstance(result, WriteResult)
    assert result.performed is True
    assert result.reversible is False
    assert result.reverse_with is None      # because there is no such call
    assert result.response == {"status": "success"}
    assert any("PERMANENT" in note for note in result.notes)


async def test_apply_refuses_to_apply_twice_and_sends_nothing(monkeypatch):
    """Uplers already has him down as interested. A duplicate is not possible."""
    calls = wire_talent(monkeypatch, single_hr_then(auth_record(is_intrested=1)))

    result = await server.uplers_apply(AGENTAI, confirm=True)

    assert writes(calls) == []
    assert len(calls) == 1                  # the read that discovered it, only

    assert isinstance(result, WriteResult)
    assert result.performed is False
    assert result.reversible is False
    assert any("already has you down as interested" in note for note in result.notes)


async def test_apply_refuses_to_guess_an_id_for_a_permanent_action(monkeypatch):
    """No numeric `id` in the record means no apply. It must not improvise one.

    `hr_id` names two different identifier spaces on this API, and sending the
    wrong one is a silent no-op or a 422 rather than an obvious error. On a
    route that cannot be undone, a guess is the wrong kind of helpful.
    """
    without_id = auth_record()
    without_id.pop("id")
    calls = wire_talent(monkeypatch, single_hr_then(without_id))

    with pytest.raises(TalentError) as excinfo:
        await server.uplers_apply(AGENTAI, confirm=True)

    assert "carries no numeric `id`" in str(excinfo.value)
    assert "Refusing to guess" in str(excinfo.value)
    assert writes(calls) == []


async def test_dismiss_without_confirm_performs_nothing_and_says_it_is_reversible(monkeypatch):
    calls = wire_talent(monkeypatch, single_hr_then(auth_record()))

    result = await server.uplers_dismiss(AGENTAI)

    assert writes(calls) == []
    assert [c for c in calls if c.url.path.endswith(endpoints.EP_NOT_INTERESTED)] == []

    assert isinstance(result, WritePreview)
    assert result.performed is False
    assert result.reversible is True
    assert result.action == "dismiss"
    assert result.endpoint == endpoints.EP_NOT_INTERESTED
    assert result.method == "POST application/json"
    assert result.body == {"hr_number": AGENTAI, "reason_ids": []}
    # Reversible, so no scare warning - that is reserved for the one that is not.
    assert result.warning is None
    assert result.to_confirm == 'uplers_dismiss("%s", confirm=True)' % AGENTAI


async def test_dismiss_with_confirm_posts_json_carrying_the_reason_ids(monkeypatch):
    calls = wire_talent(monkeypatch, single_hr_then(auth_record()))

    result = await server.uplers_dismiss(AGENTAI, confirm=True, reason_ids=[2, 5])

    posted = writes(calls)
    assert len(posted) == 1
    post = posted[0]
    assert post.url.path.endswith(endpoints.EP_NOT_INTERESTED)
    assert post.headers["content-type"] == "application/json"
    assert json.loads(post.content) == {"hr_number": AGENTAI, "reason_ids": [2, 5]}

    assert isinstance(result, WriteResult)
    assert result.performed is True
    assert result.reversible is True
    # The opposite call, named. This is what makes "reversible" actionable.
    assert result.reverse_with == 'uplers_dismiss("%s", confirm=True, undo=True)' % AGENTAI


async def test_undo_dismiss_posts_the_reset_flag_and_names_the_opposite_call(monkeypatch):
    calls = wire_talent(monkeypatch, single_hr_then(auth_record()))

    result = await server.uplers_dismiss(AGENTAI, confirm=True, undo=True)

    posted = writes(calls)
    assert len(posted) == 1
    assert posted[0].url.path.endswith(endpoints.EP_NOT_INTERESTED)
    assert json.loads(posted[0].content) == {
        "hr_number": AGENTAI,
        "reset_not_interested": True,
    }

    assert result.action == "undismiss"
    assert result.performed is True
    assert result.reversible is True
    # And back the other way, with no `undo=True` on it.
    assert result.reverse_with == 'uplers_dismiss("%s", confirm=True)' % AGENTAI


async def test_undo_without_confirm_also_performs_nothing(monkeypatch):
    calls = wire_talent(monkeypatch, single_hr_then(auth_record()))

    result = await server.uplers_dismiss(AGENTAI, undo=True)

    assert writes(calls) == []
    assert result.performed is False
    assert result.action == "undismiss"
    assert result.body == {"hr_number": AGENTAI, "reset_not_interested": True}
    assert result.to_confirm == 'uplers_dismiss("%s", confirm=True, undo=True)' % AGENTAI


# ==========================================================================
# GROUP S - session expiry and envelope drift. Both must RAISE, never empty.
# ==========================================================================

#: Every authenticated READ, with the smallest argument set that reaches HTTP.
AUTHENTICATED_READS = [
    ("uplers_my_feed", {}),
    ("uplers_my_pipeline", {}),
    ("uplers_get_opportunity_live", {"hr_number": AGENTAI}),
    ("uplers_tailored_jobs", {}),
    ("uplers_my_profile", {}),
    ("uplers_my_interviews", {}),
    ("uplers_filter_options", {"kind": "role"}),
]

#: The reads whose envelope is a named key. `uplers_get_opportunity_live` is
#: absent because its record is the payload itself, not a wrapper.
ENVELOPE_READS = [
    ("uplers_my_feed", {}, "hrs"),
    ("uplers_my_pipeline", {}, "hrs"),
    ("uplers_tailored_jobs", {}, "data"),
    ("uplers_my_profile", {}, "talent_details"),
    ("uplers_my_interviews", {}, "data"),
    ("uplers_filter_options", {"kind": "role"}, "data"),
]


@pytest.mark.parametrize(
    "tool_name,kwargs", AUTHENTICATED_READS, ids=[name for name, _ in AUTHENTICATED_READS]
)
async def test_an_expired_session_raises_and_names_the_login_tool(
    monkeypatch, tool_name, kwargs
):
    """A 401 is "sign in again", never "no jobs today".

    Uplers sessions are short-lived enough that re-login is close to a daily
    event, so this path is walked constantly. If any read here answered an
    expired session with an empty feed, the operator would read a working
    account as a dead board and stop looking - and nothing would ever surface
    the cause. That failure is silent by construction, which is why it is
    checked on every read rather than on a representative one.
    """
    calls = wire_talent(monkeypatch, reject)

    with pytest.raises(AuthRequired) as excinfo:
        await getattr(server, tool_name)(**kwargs)

    message = str(excinfo.value)
    assert "uplers_login" in message              # it names the fix
    assert "401" in message                       # and what it measured
    assert excinfo.value.kind == "auth_required"
    assert len(calls) == 1                        # a 401 is not retried


@pytest.mark.parametrize(
    "tool_name,kwargs,key",
    ENVELOPE_READS,
    ids=[name for name, _, _ in ENVELOPE_READS],
)
async def test_a_changed_envelope_raises_instead_of_reading_as_empty(
    monkeypatch, tool_name, kwargs, key
):
    """HTTP 200, wrong shape. Also not "no results".

    A renamed key produces exactly this: a successful request whose body no
    longer carries what the reader wanted. Shaping it into `[]` would report a
    broken client as a quiet day, so every reader validates its own envelope
    before it shapes anything.
    """
    wire_talent(monkeypatch, serve(CHANGED_SHAPE))

    with pytest.raises(TalentError) as excinfo:
        await getattr(server, tool_name)(**kwargs)

    message = str(excinfo.value)
    assert key in message                    # it names the key that was missing
    assert "unexpected" in message           # and the keys it did see
    assert not isinstance(excinfo.value, AuthRequired)   # not misreported as expiry


async def test_an_empty_authenticated_record_is_not_read_as_a_missing_job(monkeypatch):
    """A 200 with an empty body is a shape change. A missing job is a 404."""
    wire_talent(monkeypatch, serve({}))

    with pytest.raises(TalentError) as excinfo:
        await server.uplers_get_opportunity_live(AGENTAI)

    assert "NOT 'no such job'" in str(excinfo.value)
    assert "404" in str(excinfo.value)


# ==========================================================================
# GROUP F - feed parameter encoding, verified against Uplers' own bundle.
# ==========================================================================


def feed_handler(rows=None, *, last_page=1, total=None, jobs_count=None):
    """A paginator that also answers the separate is_count=1 request."""
    rows = [auth_record()] if rows is None else rows

    def handler(request):
        if request.url.params.get("is_count") == "1":
            return httpx.Response(200, json={"jobs_count": jobs_count})
        page = int(request.url.params.get("page", 1))
        return httpx.Response(
            200, json=paginated(rows, page=page, last_page=last_page, total=total)
        )

    return handler


async def test_modes_are_sent_as_a_json_array_of_objects(monkeypatch):
    """`engagements` is NOT a comma list. It is a JSON-encoded array of objects.

    Copied from the bundle's own query builder. A plain "Remote,Hybrid" is
    accepted by the route and filters nothing, which is the worst outcome
    available: a feed that looks filtered and is not.
    """
    calls = wire_talent(monkeypatch, feed_handler(total=4))

    await server.uplers_my_feed(modes=["Remote", "Hybrid"], score=False)

    sent = calls[0].url.params["engagements"]
    assert json.loads(sent) == [{"type": "Remote"}, {"type": "Hybrid"}]
    assert sent != "Remote,Hybrid"


async def test_lowercase_modes_are_accepted_and_sent_in_uplers_spelling(monkeypatch):
    calls = wire_talent(monkeypatch, feed_handler(total=4))

    result = await server.uplers_my_feed(modes=["remote"], score=False)

    assert json.loads(calls[0].url.params["engagements"]) == [{"type": "Remote"}]
    assert result.filters_applied["modes"] == ["Remote"]


async def test_experience_is_a_range_string_sent_beside_the_fixed_feed_params(monkeypatch):
    """`experience` is a "min,max" RANGE, not a number of years."""
    calls = wire_talent(monkeypatch, feed_handler(total=4))

    await server.uplers_my_feed(
        experience="4,6", sort="created_at", page_size=12, page=1, score=False
    )

    params = calls[0].url.params
    assert params["experience"] == "4,6"        # verbatim, not reinterpreted
    assert params["sort_field"] == "created_at"
    assert params["pagination"] == "12"
    assert params["page"] == "1"
    assert params["is_count"] == "0"


async def test_an_invalid_sort_is_refused_before_any_request(monkeypatch):
    calls = wire_talent(monkeypatch, feed_handler())

    with pytest.raises(UplersError) as excinfo:
        await server.uplers_my_feed(sort="by_vibes")

    assert "relevance" in str(excinfo.value)
    assert "created_at" in str(excinfo.value)
    assert calls == []                          # refused before the client existed


async def test_an_invalid_mode_says_uplers_calls_it_onsite_not_office(monkeypatch):
    """The one name a human gets wrong, so the error says it outright."""
    calls = wire_talent(monkeypatch, feed_handler())

    with pytest.raises(UplersError) as excinfo:
        await server.uplers_my_feed(modes=["Office"])

    message = str(excinfo.value)
    assert "'Onsite'" in message
    assert "not 'Office'" in message
    assert calls == []


async def test_pages_fetches_that_many_consecutive_pages(monkeypatch):
    calls = wire_talent(monkeypatch, feed_handler(last_page=5, total=50))

    result = await server.uplers_my_feed(pages=3, score=False)

    assert len(calls) == 3                              # and no count call: total came back
    assert [call.url.params["page"] for call in calls] == ["1", "2", "3"]
    assert result.pages_fetched == 3
    assert result.returned == 3


async def test_paging_stops_early_at_the_last_page(monkeypatch):
    calls = wire_talent(monkeypatch, feed_handler(last_page=2, total=20))

    result = await server.uplers_my_feed(pages=3, score=False)

    assert len(calls) == 2                              # asked for 3, there were 2
    assert [call.url.params["page"] for call in calls] == ["1", "2"]
    assert result.pages_fetched == 2
    assert result.last_page == 2


async def test_the_total_comes_from_a_separate_is_count_request(monkeypatch):
    """Uplers reports the count on its own call, so the feed spends one."""
    calls = wire_talent(monkeypatch, feed_handler(jobs_count=87))   # no `total` in envelope

    result = await server.uplers_my_feed(score=False)

    assert len(calls) == 2
    assert calls[0].url.params["is_count"] == "0"
    assert calls[1].url.params["is_count"] == "1"
    # The counting call carries the same filters, or it would count a different set.
    assert calls[1].url.params["sort_field"] == calls[0].url.params["sort_field"]
    assert result.total == 87


async def test_a_failing_count_call_does_not_take_the_feed_down(monkeypatch):
    """The rows are the answer; the total is a nicety. Losing it is a note."""

    def handler(request):
        if request.url.params.get("is_count") == "1":
            return httpx.Response(500, json={"message": "boom"})
        return httpx.Response(200, json=paginated([auth_record()]))

    wire_talent(monkeypatch, handler)

    result = await server.uplers_my_feed(score=False)

    assert isinstance(result, TalentFeed)
    assert result.returned == 1
    assert result.total is None
    assert any("Could not read the total count" in note for note in result.notes)


async def test_an_unscored_feed_says_why_rather_than_reporting_zeroes(monkeypatch):
    """No local profile means no scores, and the rows say so."""
    wire_talent(monkeypatch, feed_handler(total=1))

    result = await server.uplers_my_feed(score=True)

    assert result.rows[0].score is None
    assert result.scored_against is None
    assert any("no usable local profile" in note for note in result.notes)


# ==========================================================================
# GROUP R - the reads.
# ==========================================================================


async def test_pipeline_tallies_uplers_own_status_and_badge_fields(monkeypatch):
    """`statusName` / `badgeName` are Uplers' workflow, and it is authoritative.

    This is the whole reason the pipeline read exists: uplers_list_tracked()
    only knows what the operator told this server, and where the two disagree
    Uplers is right.
    """
    rows = [
        auth_record(statusName="Interviewed", badgeName="Slots Given"),
        auth_record(statusName="Interviewed", badgeName="Interview Scheduled"),
        auth_record(statusName="Shortlisted", badgeName="Slots Given"),
    ]
    calls = wire_talent(monkeypatch, serve(paginated(rows, total=3)))

    result = await server.uplers_my_pipeline()

    assert isinstance(result, PipelineResult)
    assert result.returned == 3
    # Commonest first, so the shape of the pipeline reads off the top.
    assert list(result.by_status.items()) == [("Interviewed", 2), ("Shortlisted", 1)]
    assert list(result.by_badge.items()) == [
        ("Slots Given", 2),
        ("Interview Scheduled", 1),
    ]
    assert result.rows[0].uplers_status == "Interviewed"
    assert calls[0].url.path.endswith(endpoints.EP_MY_OPPORTUNITIES)
    assert calls[0].url.params["pagination"] == "10"


async def test_compare_public_names_the_fields_only_a_session_can_see(monkeypatch, tools):
    """The tier's own justification, made measurable.

    The authenticated record here is the public one plus exactly three keys, so
    the right answer is known before the call and can be asserted by name.
    """
    put_fixtures(tools(), [AGENTAI])        # the public record, cached

    authenticated = auth_record(
        statusName="Interviewed", badgeName="Slots Given", is_intrested=1
    )
    calls = wire_talent(monkeypatch, serve(authenticated))

    report = await server.uplers_get_opportunity_live(AGENTAI, compare_public=True)

    assert isinstance(report, FieldReport)
    assert report.only_in_authenticated == ["badgeName", "is_intrested", "statusName"]
    assert report.only_in_public == []
    assert report.values["statusName"] == "Interviewed"
    assert report.values["badgeName"] == "Slots Given"
    assert report.in_both > 80
    assert report.notes == []               # it found something, so no "buys nothing"

    # One authenticated read. The public side came from the cache, so the
    # PUBLIC client was never built - the autouse `offline` fixture proves it.
    assert len(calls) == 1


async def test_compare_public_says_so_when_the_session_buys_no_extra_field(
    monkeypatch, tools
):
    put_fixtures(tools(), [AGENTAI])
    wire_talent(monkeypatch, serve(load_fixture(AGENTAI)))

    report = await server.uplers_get_opportunity_live(AGENTAI, compare_public=True)

    assert report.only_in_authenticated == []
    assert any("a session buys no extra field" in note for note in report.notes)


async def test_the_live_record_without_a_comparison_is_a_full_detail(monkeypatch):
    wire_talent(monkeypatch, serve(auth_record()))

    detail = await server.uplers_get_opportunity_live(AGENTAI)

    assert isinstance(detail, OpportunityDetail)
    assert detail.hr_number == AGENTAI
    assert detail.company_info.name == "AgentAI"
    assert detail.description_truncated is False


async def test_an_internal_test_requisition_is_discarded_the_way_uplers_discards_it(
    monkeypatch,
):
    """`1 != res.data.is_test_hr` gates whether their own UI renders it at all."""
    wire_talent(monkeypatch, serve(auth_record(is_test_hr=1)))

    with pytest.raises(TalentError) as excinfo:
        await server.uplers_get_opportunity_live(AGENTAI)

    assert "is_test_hr" in str(excinfo.value)
    assert "test requisitions" in str(excinfo.value)


async def test_tailored_jobs_posts_the_anchor_and_hides_test_requisitions(monkeypatch):
    calls = wire_talent(
        monkeypatch,
        serve({"data": [auth_record(), auth_record(is_test_hr=1)]}),
    )

    result = await server.uplers_tailored_jobs(hr_number=AGENTAI, score=False)

    assert calls[0].method == "POST"
    assert calls[0].url.path.endswith(endpoints.EP_TAILOR_JOBS)
    assert json.loads(calls[0].content) == {"HR_Number": AGENTAI}

    assert isinstance(result, TalentFeed)
    assert result.returned == 1             # the test requisition was dropped
    assert result.source == endpoints.EP_TAILOR_JOBS
    assert result.filters_applied == {"anchor": AGENTAI}


async def test_my_profile_shapes_talent_details_and_reports_their_completeness(monkeypatch):
    """Their completeness score is REPORTED, not editorialised.

    It used to say the gap was "costing you visibility". His profile is his
    decision and this server does not know what he decided or why, so it hands
    back Uplers' number and stops."""
    payload = {
        "talent_details": {
            "full_name": "Sundeep G",
            "headline": "Backend Engineer",
            "city": "Bangalore",
            "total_experience": 6,
            "notice_period": "30 days",
            "skills": [{"name": "Node.js"}, {"name": "TypeScript"}, {"name": "Go"}],
        },
        "profile_completion_percentage": 72,
    }
    wire_talent(monkeypatch, serve(payload))

    result = await server.uplers_my_profile()

    assert isinstance(result, TalentProfileResult)
    assert result.name == "Sundeep G"
    assert result.years_experience == 6.0
    assert result.location == "Bangalore"
    assert result.skills == ["Node.js", "TypeScript", "Go"]
    assert result.notice_period == "30 days"
    assert result.completion_percentage == 72.0
    assert "total_experience" in result.sections_present

    note = " ".join(result.notes)
    assert "72%" in note
    # Reported, not judged: no advice, no verdict on his profile.
    for editorialising in ("costing you", "should", "thin", "limits", "visibility"):
        assert editorialising not in note.lower()


async def test_a_complete_uplers_profile_gets_no_scolding_note(monkeypatch):
    wire_talent(
        monkeypatch,
        serve(
            {
                "talent_details": {"full_name": "Sundeep G", "city": "Bangalore"},
                "profile_completion_percentage": 100,
            }
        ),
    )

    result = await server.uplers_my_profile()

    assert result.completion_percentage == 100.0
    assert result.notes == []


async def test_compare_profiles_reports_both_directions_and_writes_to_neither(
    monkeypatch, make_profile, isolated_profile
):
    """Two profiles, two jobs, and this tool writes to neither.

    Both lists are still reported, but they no longer mean the same thing.
    Uplers is the source of truth: `only_uplers` is a gap in the LOCAL copy
    that understates every fit score, while `only_local` is a set of skills
    Uplers has not been told about - kept locally, never deleted, and never
    the subject of an instruction to go and edit the authoritative record.

    A byte-identical local file after the call is part of the contract, not an
    implementation detail: the sync is a separate, confirm-gated tool.
    """
    make_profile(
        name="Test Candidate",
        skills=["Node.js", "TypeScript", "AWS", "PostgreSQL", "Python", "React"],
    )
    before = isolated_profile.read_bytes()

    wire_talent(
        monkeypatch,
        serve(
            {
                "talent_details": {
                    "full_name": "Sundeep G",
                    "city": "Bangalore",
                    "skills": [{"name": "Node.js"}, {"name": "TypeScript"}, {"name": "Go"}],
                },
                "profile_completion_percentage": 61,
            }
        ),
    )

    result = await server.uplers_compare_profiles()

    assert isinstance(result, ProfileComparison)
    assert result.source_of_truth == "uplers"
    # Only-local: Uplers has not been told about these. Kept, not deleted.
    assert result.only_local == ["AWS", "PostgreSQL", "Python", "React"]
    # Only-Uplers: known to Uplers, absent from every fit score computed here.
    assert result.only_uplers == ["Go"]

    # The fix flows local <- Uplers, and the wording must say so.
    assert "uplers_sync_profile_from_uplers" in result.recommendation
    assert "platform.uplers.com" not in result.recommendation

    notes = " ".join(result.notes)
    assert "MISSING from the local profile" in notes
    assert "not on Uplers" in notes
    # Neutral about HIS side: his Uplers skills are a decision he made, so the
    # difference is stated and no action on that side is suggested.
    assert "your decision" in notes
    assert "platform.uplers.com" not in notes

    # It changed nothing. Byte-for-byte, not "looks the same".
    assert isolated_profile.read_bytes() == before


async def test_compare_profiles_with_no_local_profile_offers_to_build_one_from_uplers(
    monkeypatch,
):
    """With nothing local, the answer is not "go and type your CV in".

    His Uplers profile already holds the whole thing, so the recommendation is
    to copy it down rather than to author a second one by hand.
    """
    wire_talent(
        monkeypatch,
        serve(
            {
                "talent_details": {
                    "full_name": "Sundeep G",
                    "city": "Bangalore",
                    "skills": [{"name": "Node.js"}, {"name": "Go"}],
                }
            }
        ),
    )

    result = await server.uplers_compare_profiles()

    assert result.local is None
    assert "uplers_sync_profile_from_uplers()" in result.recommendation
    assert result.uplers is not None
    assert result.uplers_skill_sections["distinct"] == 2


async def test_my_interviews_asks_uplers_for_the_detailed_record(monkeypatch):
    calls = wire_talent(
        monkeypatch,
        serve(
            {
                "status": "success",
                "data": [
                    {
                        "company_name": "AgentAI",
                        "company_id": "77",
                        "RequestForTalent": "AI Full Stack Engineer",
                        "status": "Scheduled",
                        "scheduled_at": "2026-08-25 10:00",
                        "feedback": 0,
                    }
                ],
            }
        ),
    )

    result = await server.uplers_my_interviews()

    assert isinstance(result, InterviewList)
    assert result.count == 1
    assert result.interviews[0].company == "AgentAI"
    assert result.interviews[0].company_id == 77
    assert result.interviews[0].role == "AI Full Stack Engineer"
    assert result.interviews[0].feedback_given is False
    assert calls[0].url.path.endswith(endpoints.EP_INTERVIEW_LIST)
    assert calls[0].url.params["detailed"] == "true"


async def test_filter_options_sends_the_only_company_type_the_bundle_uses(monkeypatch):
    # The rows below are the live 2026-08-22 company-master payload. They used
    # to read `{"id": 3, "name": "Google"}`, a shape this route has never sent,
    # and the test passed while the tool shipped zero options against it.
    calls = wire_talent(
        monkeypatch,
        serve(
            {
                "data": [
                    {
                        "value": 5299,
                        "label": "Google (370)",
                        "label_without_count": "Google",
                        "company_name": "Google",
                        "total_jobs": 370,
                        "selected": False,
                    },
                    {
                        "value": 5305,
                        "label": "Uber (479)",
                        "label_without_count": "Uber",
                        "company_name": "Uber",
                        "total_jobs": 479,
                        "selected": False,
                    },
                ]
            }
        ),
    )

    result = await server.uplers_filter_options("company")

    assert calls[0].url.path.endswith(endpoints.EP_COMPANY_MASTER)
    assert calls[0].url.params["company_type"] == endpoints.DEFAULT_COMPANY_TYPE
    assert calls[0].url.params["company_type"] == "maang"

    assert result["kind"] == "company"
    assert result["options"] == [
        {"id": 5299, "name": "Google (370)"},
        {"id": 5305, "name": "Uber (479)"},
    ]
    assert result["returned"] == 2
    assert result["total_available"] == 2


async def test_filter_options_passes_the_search_term_through_for_other_kinds(monkeypatch):
    calls = wire_talent(monkeypatch, serve({"data": [{"id": 9, "name": "Bangalore"}]}))

    await server.uplers_filter_options("location", search="banga")

    assert calls[0].url.path.endswith(endpoints.EP_LOCATION_MASTER)
    assert calls[0].url.params["search"] == "banga"
    assert "company_type" not in calls[0].url.params


async def test_an_unknown_filter_kind_is_refused_before_any_request(monkeypatch):
    calls = wire_talent(monkeypatch, serve({"data": []}))

    with pytest.raises(UplersError) as excinfo:
        await server.uplers_filter_options("planets")

    assert "kind must be one of" in str(excinfo.value)
    assert "'planets'" in str(excinfo.value)
    assert calls == []


# ==========================================================================
# GROUP A - the session tools themselves.
# ==========================================================================


async def test_auth_status_reports_false_on_401_and_never_prints_the_token(
    monkeypatch, session_file
):
    """A `false` here is a measurement. And it costs the token nothing.

    The token is the one secret this server holds. `describe()` is allowed to
    say whether one exists and what shape it has; nothing anywhere may serialise
    the value, a prefix of it, or its length.
    """
    SessionStore(session_file).save(TOKEN, method="test")
    calls = wire_talent(monkeypatch, reject, token=TOKEN)

    result = await server.uplers_auth_status()

    assert isinstance(result, AuthStatus)
    assert result.authenticated is False
    assert result.token_present is True          # a token exists, and it was rejected
    assert result.token_format == "sanctum"
    assert "uplers_login()" in result.reason
    assert result.checked_against == endpoints.AUTH_PROBE_NOTE

    # The measurement really was a request, carrying that exact token.
    assert len(calls) == 1
    assert calls[0].headers["authorization"] == "Bearer " + TOKEN

    # And none of it came back out. Not the value, not the secret half of it,
    # and not under a field of its own.
    serialised = json.dumps(result.model_dump(), default=str)
    assert TOKEN not in serialised
    assert "bearer-token-that-must-never-be-printed" not in serialised
    assert TOKEN.split("|", 1)[1] not in serialised
    assert "Bearer" not in serialised
    assert "token" not in result.model_dump()   # only token_present / token_format


async def test_auth_status_reports_true_only_when_the_profile_comes_back(
    monkeypatch, session_file
):
    """A 200 is necessary and not sufficient - a guest token can get one too."""
    SessionStore(session_file).save(TOKEN, method="test")
    wire_talent(
        monkeypatch,
        serve(
            {
                "talent_details": {"full_name": "Sundeep G"},
                "profile_completion_percentage": 82,
            }
        ),
    )

    result = await server.uplers_auth_status()

    assert result.authenticated is True
    assert result.signed_in_as == "Sundeep G"
    assert result.profile_completion_percentage == 82
    assert TOKEN not in json.dumps(result.model_dump(), default=str)


async def test_auth_status_says_unknown_rather_than_logged_out_on_a_200_with_no_profile(
    monkeypatch, session_file
):
    """Unknown does not collapse into false. False costs a browser round trip."""
    SessionStore(session_file).save(TOKEN, method="test")
    wire_talent(monkeypatch, serve({"message": "ok"}))

    result = await server.uplers_auth_status()

    assert result.authenticated is None
    assert result.error == "unexpected_shape"
    assert "guest token" in result.reason


async def test_logout_clears_the_store_and_reports_what_it_found(session_file):
    store = SessionStore(session_file)
    store.save(TOKEN, method="test")
    assert session_file.is_file()

    first = await server.uplers_logout()

    assert first.authenticated is False
    assert first.token_present is False
    assert "Token deleted" in first.reason
    assert not session_file.exists()
    assert store.token() is None

    # A second logout is not an error - it is a different sentence.
    second = await server.uplers_logout()
    assert second.authenticated is False
    assert "no stored token to delete" in second.reason


async def test_login_turns_a_missing_browser_into_a_result_not_a_crash(monkeypatch):
    """The rest of the handshake is test_auth.py's job; this is the tool's edge.

    Playwright not being installed is a setup problem with a fix the operator
    can act on, so it comes back as a LoginResult carrying the reason rather
    than as a traceback out of an MCP tool.
    """

    async def unavailable(*args, **kwargs):
        raise auth_mod.BrowserUnavailable(
            "Playwright is not installed. Run: pip install playwright"
        )

    monkeypatch.setattr(server.auth_mod, "login_via_browser", unavailable)

    result = await server.uplers_login(wait_seconds=1)

    assert isinstance(result, LoginResult)
    assert result.authenticated is False
    assert result.error == "browser_unavailable"
    assert "Playwright is not installed" in result.reason


# --- filter_options over the shape the master lists ACTUALLY send ----------
#
# The fixtures below are the live 2026-08-22 payloads, not invented ones. The
# pre-existing tests in this file fed `{"id": ..., "name": ...}`, which no
# master route has ever returned, and passed while the tool emitted zero
# options against every real call.

LIVE_ROLE_MASTER = {
    "status": True,
    "message": "",
    "data": [
        {"label": "Backend Development", "value": 1, "category": "Software Engineering"},
        {"label": "Frontend Development", "value": 2, "category": "Software Engineering"},
    ],
}
LIVE_SKILL_MASTER = {
    "status": True,
    "message": "",
    "data": [
        {
            "value": 3890198,
            "label": "react (1975)",
            "label_without_count": "react",
            "skill_name": "react",
            "hr_count": 1975,
            "selected": False,
        }
    ],
}
LIVE_LOCATION_MASTER = {
    "status": True,
    "message": "",
    "data": [
        {
            "label": "Bengaluru (Karnataka)",
            "value": 277,
            "city": "Bengaluru",
            "state": "Karnataka",
            "selected": False,
        }
    ],
}


async def test_filter_options_reads_the_id_key_the_master_routes_actually_send(
    monkeypatch,
):
    """The id lives in `value`, never in `id`.

    This tool exists to turn "React" into the numeric id uplers_my_feed()
    filters need. Reading `row.get("id")` made every id None, and the
    `id is not None` filter then dropped every option -- so the tool returned
    an empty list on all four kinds, for every search, always. Measured live
    2026-08-22 against role/skill/location/company: 0 options returned each
    time, while `total_available` reported 46/6/2/5.
    """
    wire_talent(monkeypatch, serve(LIVE_ROLE_MASTER))

    result = await server.uplers_filter_options("role")

    assert result["options"] == [
        {"id": 1, "name": "Backend Development"},
        {"id": 2, "name": "Frontend Development"},
    ]


async def test_filter_options_count_cannot_disagree_with_the_list_it_ships(
    monkeypatch,
):
    """`returned` counted the list BEFORE the drop-nothing filter.

    That is the part that hid the bug: the payload said `returned: 5` beside
    `options: []`, so a caller reading the count had no reason to look. A
    count that describes a different list than the one shipped is worse than
    no count.
    """
    wire_talent(monkeypatch, serve(LIVE_SKILL_MASTER))

    result = await server.uplers_filter_options("skill", search="react")

    assert result["returned"] == len(result["options"])
    assert result["options"] == [{"id": 3890198, "name": "react (1975)"}]


async def test_filter_options_names_a_location_from_its_label(monkeypatch):
    """Locations carry `label`, `city` and `state`; the label is the useful one."""
    wire_talent(monkeypatch, serve(LIVE_LOCATION_MASTER))

    result = await server.uplers_filter_options("location", search="bang")

    assert result["options"] == [{"id": 277, "name": "Bengaluru (Karnataka)"}]
    assert result["returned"] == 1
