"""The three writes that spend or claim MONEY.

`test_outreach_write.py` covers the four that can be put back and says so in
its first line. `test_consent_write.py` covers the two that cannot but are not
purchases. These three are neither, and the difference is not academic: on
every route in this file, being wrong costs him money.

  * `uplers_order_create` and `uplers_health_check_order_create` MINT A
    RAZORPAY ORDER. **They do not charge the card** - that happens in
    Razorpay's hosted widget, which this server cannot drive - so a confirmed
    call leaves a REAL, UNPAID order that still needs a browser to pay, and no
    route in Uplers' API cancels one.
  * `uplers_request_refund` RAISES A REQUEST. Nobody has observed a refund
    completing and no route anywhere reports refund status.

THREE TOOLS, FOUR ROUTES. The refund is one tool whose `kind` picks between
`talent/tailor/refund-request` and `talent/resume-health-check/refund-request`.

EVERY GUARD HAS A CONTROL THAT FAILS WITH THE GUARD REMOVED. That is not
decoration: a `writes(calls) == []` assertion is trivially true when no request
was made at all, and a key-set equality passes happily against a body nobody
built. Each is paired with a planted case proving it can see the thing it
claims to watch.

THE FOUR PROPERTIES SPECIFIC TO THIS FILE
------------------------------------------
1.  **THE EXACT KEY SET OF ALL THREE BODIES**, asserted as set equalities
    rather than membership checks, so a fourth key added by a later edit fails
    loudly instead of riding along on a request that spends money. `{plan_id}`,
    `{amount, health_check_id, is_tailored}`, and `{}` / `{transformation_id}`.
2.  **`is_tailored` ON THE WIRE**, asserted against the SERIALISED JSON rather
    than the dict, because `json.dumps(True)` is `true` and that is a different
    value from `1`. A dict-level assertion cannot tell them apart.
3.  **THE PRICES ARE READ LIVE.** The catalogue drives the preview, a plan the
    catalogue does not list refuses, and the catalogue's ABSENT CURRENCY is
    pinned - so a later edit that starts printing "INR" goes red.
4.  **THE ORDER RESPONSE CARRIES HIS NAME.** Razorpay order notes hold it, and
    a tool result ends up in a transcript. The scrub is planted against a
    distinctive synthetic name to prove the assertion would see a leak.

NO NETWORK. Every request goes through `httpx.MockTransport`, every payload is
synthetic or a committed fixture, and both `isolated_snapshots` and
`isolated_markers` are autouse so a test cannot write into the real data
directory by forgetting a fixture. **NO ORDER HAS EVER BEEN CREATED AND NO
REFUND HAS EVER BEEN REQUESTED** by anything in this file or the module it
tests.
"""

from __future__ import annotations

import json

import httpx
import pytest

import server as server_mod
from conftest import load_talent_fixture, make_transport
from uplers_server import checkout, endpoints, outreach_write
from uplers_server.outreach import OutreachError
from uplers_server.profile_write import WriteRefused
from uplers_server.talent import TalentClient

PLANS_PATH = "/api/" + endpoints.EP_OUTREACH_AGENT_PLANS
LAST_HEALTH_PATH = "/api/" + endpoints.EP_SKU_HEALTH_CHECK_LAST
DASHBOARD_PATH = "/api/" + endpoints.EP_SKU_HEALTH_CHECK_DASHBOARD

ORDER_PATH = "/api/" + endpoints.EP_TAILOR_ORDER_CREATE
HEALTH_ORDER_PATH = "/api/" + endpoints.EP_HEALTH_CHECK_ORDER_CREATE
TAILOR_REFUND_PATH = "/api/" + endpoints.EP_TAILOR_REFUND_REQUEST
HEALTH_REFUND_PATH = "/api/" + endpoints.EP_HEALTH_CHECK_REFUND_REQUEST

TOKEN = "42|bearer-token-that-must-never-be-printed"

#: MEASURED, from the committed capture. The join that resolves which health
#: check this account holds: rtid 150705 -> exactly one dashboard row, id
#: 152462.
LIVE_TRANSFORMATION_ID = 150705
LIVE_HEALTH_CHECK_ID = 152462

#: MEASURED plan ids and prices from `tests/fixtures/outreach_agent_plans.json`.
STARTER_PRICE = 1499
ELITE_PRICE = 2999

#: HIS CURRENT PLAN, and it is NOT IN THE CATALOGUE. MEASURED: outreach-step
#: reads `plan: 2` while the catalogue holds only "1" and "3". A naive "look up
#: his plan and order it" would find nothing, which is why the refusal below is
#: the realistic case rather than an edge one.
PLAN_NOT_IN_CATALOGUE = "2"

#: SYNTHETIC. The order-response leak assertions check for this string, so a
#: regression prints an invented name into a test log rather than his.
LIVE_ORDER_NAME = "A-VERY-DISTINCTIVE-ORDER-NOTE-NAME"


# --- wiring ----------------------------------------------------------------
#
# Local rather than imported from the sibling write-test files, for the reason
# they each give for their own copy: the orchestrators take a client as an
# argument instead of building one, so there is nothing to monkeypatch and a
# small local factory is a smaller thing to keep working than a cross-file
# import.


def client_over(handler):
    """(TalentClient, calls) over a MockTransport. `calls` is the risk surface."""
    transport, calls = make_transport(handler)
    return TalentClient(lambda: TOKEN, transport=transport, delay=0), calls


def writes(calls):
    """Every request that was not a read. A write tool's whole risk surface."""
    return [call for call in calls if call.method != "GET"]


def routes_of(calls):
    return [call.url.path.split("/api/")[-1] for call in calls]


class Recorder:
    """A sender that records and never sends.

    `on_send` runs AT SEND TIME, which is how snapshot-before is proved. An
    assertion made after the orchestrator returns cannot tell "written first"
    from "written afterwards", and on a route that creates a paid order the
    ordering is the only thing separating a record of the price he was shown
    from a record of what he was charged.
    """

    def __init__(self, response=None, on_send=None, path=None, method=None, kind=None):
        self.calls = []
        self._response = response if response is not None else {"status": 200}
        self._on_send = on_send
        self.path = path if path is not None else endpoints.EP_TAILOR_ORDER_CREATE
        self.method = method if method is not None else "POST application/json"
        if kind is not None:
            self.kind = kind

    async def __call__(self, body):
        if self._on_send is not None:
            self._on_send(body)
        self.calls.append(body)
        return self._response


def order_response(amount=STARTER_PRICE, currency="INR", order_id="order_MEASURED1"):
    """The MEASURED create-order reply shape, notes and all.

    ``notes.name`` is the leak this module closes, so it is present by default
    rather than only in the test that checks for it - a scrub that is only
    exercised by its own test is a scrub nothing else would notice losing.
    """
    return {
        "id": order_id,
        "amount": amount,
        "currency": currency,
        "notes": {"name": LIVE_ORDER_NAME},
        "created_at": 1756000000,
    }


# --- payload builders ------------------------------------------------------


def plans_payload(plans=None):
    """`agent-plans`, in the MEASURED shape.

    Defaults to the committed capture, so the catalogue every test reads is the
    one the platform actually sent. NOTE the envelope: this route answers the
    STRING "success", not the integer 200 that the SKU reads answer.
    """
    if plans is None:
        return load_talent_fixture("outreach_agent_plans")
    return {
        "status": "success",
        "message": "Agent plans fetched successfully",
        "data": {"agent_tailor_plans": plans},
    }


def last_health_payload(transformation_id=LIVE_TRANSFORMATION_ID, transform=True):
    """`get-last-health-check`. **Its `health_check` object carries NO id.**

    That is the measurement this module's two-route join exists because of, so
    the builder reproduces it exactly rather than adding an id that would make
    the tests pass for a reason the platform does not supply.
    """
    data = {
        "is_eligible": False,
        "is_paid": False,
        "total_attempts": 5,
        "user_attempts": 3,
        "resume_healthchecked": True,
        "current_profile_cv_healthchecked": False,
        "health_check": {
            "created_at": "11-08-2026 17:50:40",
            "final_verdict": "",
            "resume_score": 89,
            "status": 3,
        },
    }
    if transform:
        data["transform"] = {
            "created_at": "11-08-2026 17:50:40",
            "id": "Q1VxWEkrMVR6SElPU3RWTU1OdGcxUT09",
            "is_resume_updated": 0,
            "status": 0,
            "version": 2,
        }
        if transformation_id is not None:
            data["transform"]["resume_transformation_id"] = transformation_id
    return {"status": 200, "message": "Last health check fetched successfully", "data": data}


def dashboard_payload(rows=None):
    """`resume-health-check/dashboard`. **This is where the ids live.**"""
    if rows is None:
        rows = [
            {"id": 152462, "resume_transformation_id": 150705, "resume_score": 89,
             "created_at": "2026-08-11T12:20:40.000000Z", "health_check_status": 3},
            {"id": 152456, "resume_transformation_id": 150699, "resume_score": 89,
             "created_at": "2026-08-11T10:56:57.000000Z", "health_check_status": 3},
            {"id": 152217, "resume_transformation_id": 150460, "resume_score": 87,
             "created_at": "2026-08-01T06:35:20.000000Z", "health_check_status": 3},
        ]
    return {
        "status": 200,
        "message": "Success!",
        "data": {
            "health_check": list(rows),
            "total_resume_health_check": len(rows),
            "total_resume_transformed": 0,
            "transformed": [],
        },
    }


def by_path(bodies, fallback=None):
    """Answer each request from `bodies`, keyed by url path."""

    def handler(request):
        for path, body in bodies.items():
            if request.url.path == path:
                value = body(request) if callable(body) else body
                return httpx.Response(200, json=value)
        if fallback is None:
            return httpx.Response(
                404, json={"message": "no stub for %s" % request.url.path}
            )
        return httpx.Response(200, json=fallback)

    return handler


def health_check_reads(last=None, dashboard=None):
    return by_path(
        {
            LAST_HEALTH_PATH: last if last is not None else last_health_payload(),
            DASHBOARD_PATH: dashboard if dashboard is not None else dashboard_payload(),
        }
    )


@pytest.fixture(autouse=True)
def isolated_snapshots(monkeypatch, tmp_path):
    """Snapshots go to tmp_path. Autouse: a test must not be able to write a
    copy of a real record into the operator's data directory by forgetting a
    fixture. Patched on `outreach_write` because that is where the snapshot
    writer lives - `checkout` inherits it rather than owning a fourth copy, and
    patching a name this module does not define would silently miss.
    """
    directory = tmp_path / "outreach_snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(outreach_write, "snapshots_dir", lambda: directory)
    return directory


@pytest.fixture(autouse=True)
def isolated_markers(monkeypatch, tmp_path):
    """Refund markers go to tmp_path, for the same reason and one more.

    A marker written into the real data directory would silently rate-limit HIS
    next refund request for 24 hours because a test ran. Autouse is not
    optional here.
    """
    directory = tmp_path / "checkout_markers"
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(checkout, "markers_dir", lambda: directory)
    return directory


# ==========================================================================
# The sender seam. No orchestrator can reach the wire without one.
# ==========================================================================


class TestTheSenderSeam:

    async def test_the_tailor_order_refuses_with_no_sender(self):
        """GUARD: no sender, no write. Checked BEFORE anything is snapshotted.

        The seam is what makes "no order was created" a claim about CONTROL
        FLOW rather than about what a mock transport happened to see.
        """
        client, calls = client_over(by_path({PLANS_PATH: plans_payload()}))

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.order_create(client, "1", confirm=True, send=None)

        assert "no sender" in str(excinfo.value)
        assert writes(calls) == []

    async def test_the_health_check_order_refuses_with_no_sender(self):
        client, calls = client_over(health_check_reads())

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.health_check_order_create(
                    client, LIVE_HEALTH_CHECK_ID, 499, confirm=True, send=None
                )

        assert "no sender" in str(excinfo.value)
        assert writes(calls) == []

    async def test_the_refund_refuses_with_no_sender(self):
        client, calls = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.request_refund(
                    client, "tailor", confirm=True, send=None
                )

        assert "no sender" in str(excinfo.value)
        assert writes(calls) == []

    async def test_no_sender_refuses_before_a_snapshot_is_written(
        self, isolated_snapshots
    ):
        """ORDERING, not just existence. The refusal lands before disk is touched.

        A call that could never have sent anything must leave nothing behind.
        """
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))

        async with client:
            with pytest.raises(WriteRefused):
                await checkout.order_create(client, "1", confirm=True, send=None)

        assert list(isolated_snapshots.glob("*.json")) == []

    async def test_a_refund_sender_built_for_the_other_kind_is_refused(self):
        """The mismatch that would claim against the WRONG PRODUCT.

        `kind` picks the route, so a sender built for the tailor refund handed
        to a health-check refund call would raise a money claim against the
        wrong thing - and both routes answer the same success shape, so nothing
        downstream would notice. The kind travels ON the sender and is checked.
        """
        client, calls = client_over(by_path({}, fallback={"status": 200, "data": {}}))
        sender = Recorder(path=endpoints.EP_TAILOR_REFUND_REQUEST, kind="tailor")

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.request_refund(
                    client, "resume_health_check", confirm=True, send=sender
                )

        assert "built for" in str(excinfo.value)
        assert sender.calls == []
        assert writes(calls) == []

    async def test_a_matching_refund_sender_is_accepted__CONTROL(self):
        """__CONTROL for the refusal above. A guard that refuses EVERYTHING is
        indistinguishable from a broken check, so the allowed case is proven to
        still reach the sender."""
        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))
        sender = Recorder(path=endpoints.EP_TAILOR_REFUND_REQUEST, kind="tailor")

        async with client:
            result = await checkout.request_refund(
                client, "tailor", confirm=True, send=sender
            )

        assert result["performed"] is True
        assert sender.calls == [{}]

    def test_the_refund_sender_factory_stamps_its_kind(self):
        send = checkout.refund_sender_for(
            object(), endpoints.EP_TAILOR_REFUND_REQUEST, kind="tailor"
        )

        assert send.kind == "tailor"
        assert send.path == endpoints.EP_TAILOR_REFUND_REQUEST
        assert send.method == "POST application/json"

    def test_the_refund_sender_factory_refuses_an_unknown_kind(self):
        with pytest.raises(WriteRefused) as excinfo:
            checkout.refund_sender_for(
                object(), endpoints.EP_TAILOR_REFUND_REQUEST, kind="tailer"
            )

        assert "not a refund kind" in str(excinfo.value)


# ==========================================================================
# A. uplers_order_create - the tailor plan order
# ==========================================================================


class TestTailorOrderCreate:

    async def test_it_reads_the_live_catalogue_before_anything_else(self):
        """GUARD 1: read-live, and the EXACT route.

        Asserted as an exact route rather than "a GET happened", because the
        price in the preview is the whole reason this read exists and a price
        read off the wrong route is worse than no price.
        """
        client, calls = client_over(by_path({PLANS_PATH: plans_payload()}))
        sender = Recorder()

        async with client:
            await checkout.order_create(client, "1", send=sender)

        assert routes_of(calls) == [endpoints.EP_OUTREACH_AGENT_PLANS]
        assert writes(calls) == []
        assert sender.calls == []

    async def test_the_preview_prints_the_live_catalogue_price(self):
        """The price comes from the PLATFORM, never from a constant here."""
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))

        async with client:
            result = await checkout.order_create(client, "1", send=Recorder())

        assert result["performed"] is False
        assert result["catalogue_price"]["price"] == STARTER_PRICE
        assert result["catalogue_price"]["route"] == endpoints.EP_OUTREACH_AGENT_PLANS
        assert result["plan_name"] == "Starter Plan"

    async def test_the_preview_says_the_price_is_the_catalogue_not_the_order(self):
        """The label the ruling asked for, asserted rather than assumed."""
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))

        async with client:
            result = await checkout.order_create(client, "3", send=Recorder())

        block = result["catalogue_price"]
        assert block["price"] == ELITE_PRICE
        assert "CATALOGUE price" in block["is_the_catalogue_price_not_the_order"]
        assert "does not exist until" in block["is_the_catalogue_price_not_the_order"]

    async def test_the_catalogue_carries_no_currency_and_says_so(self):
        """MEASURED ABSENCE, pinned so a later edit cannot invent one.

        `agent-plans` has no currency field on the plan or anywhere else in the
        payload. A future edit that starts printing "INR" - from
        `payment_transactions`, from a locale, from anywhere - goes red here.
        That is the point: an unlabelled number a human can see is safer than a
        labelled one that might be a lie.
        """
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))

        async with client:
            result = await checkout.order_create(client, "1", send=Recorder())

        assert result["catalogue_price"]["currency"] is None
        assert "NO currency field" in result["catalogue_price"][
            "currency_is_unknown_because"
        ]
        # and the raw catalogue really does lack it, so the None above is a
        # measurement rather than this module forgetting to read a field
        raw = load_talent_fixture("outreach_agent_plans")["data"]
        assert "currency" not in json.dumps(raw).lower().replace("currency_", "")

    async def test_the_body_is_exactly_one_key(self):
        """GUARD 2: the exact key SET. A smuggled second key fails loudly."""
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))
        sender = Recorder(response=order_response())

        async with client:
            result = await checkout.order_create(
                client, "1", confirm=True, send=sender
            )

        assert set(sender.calls[0]) == set(checkout.TAILOR_ORDER_BODY_KEYS)
        assert set(sender.calls[0]) == {"plan_id"}
        assert result["body_keys"] == ["plan_id"]

    async def test_the_plan_id_on_the_wire_is_the_catalogues_own_key(self):
        """RULING: send the catalogue's key unchanged, cast in neither direction.

        Uplers' own callers resolve the plan by `agent_tailor_plans[t]` and send
        `{plan_id: t}` with no `Number()` at any of the 9 call sites, so the
        wire type is the platform's. Passing the integer 1 must still send the
        string "1" - the catalogue's key - not the caller's spelling.
        """
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))
        sender = Recorder(response=order_response())

        async with client:
            await checkout.order_create(client, 1, confirm=True, send=sender)

        assert sender.calls[0] == {"plan_id": "1"}
        assert isinstance(sender.calls[0]["plan_id"], str)

    async def test_a_plan_not_in_the_live_catalogue_refuses_and_sends_nothing(self):
        """GUARD 4, and it is the REALISTIC case on this account.

        MEASURED: his outreach-step reads `plan: 2` and the catalogue holds only
        "1" and "3". Anything that "looked up his current plan" would land here.
        """
        client, calls = client_over(by_path({PLANS_PATH: plans_payload()}))
        sender = Recorder()

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.order_create(
                    client, PLAN_NOT_IN_CATALOGUE, confirm=True, send=sender
                )

        message = str(excinfo.value)
        assert "not in Uplers' LIVE plan catalogue" in message
        # the refusal names what IS on offer, so the reader can act on it
        assert "Starter Plan" in message and "Elite Plan" in message
        # and it names the trap rather than leaving it to be rediscovered
        assert "outreach-step record is NOT an index" in message
        assert sender.calls == []
        assert writes(calls) == []

    async def test_the_catalogue_lookup_can_actually_find_a_plan__CONTROL(self):
        """__CONTROL. A lookup that refused EVERYTHING would make the test above
        pass for free while the tool did nothing at all."""
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))
        sender = Recorder(response=order_response())

        async with client:
            result = await checkout.order_create(
                client, "3", confirm=True, send=sender
            )

        assert result["performed"] is True
        assert sender.calls == [{"plan_id": "3"}]

    async def test_the_snapshot_is_written_before_the_send(self, isolated_snapshots):
        """GUARD 3: ORDERING. Asserted AT SEND TIME, not afterwards.

        What it records is the price he was shown when he confirmed. That is
        not a rollback - no route cancels an order - and the result says so.
        """
        seen = {}

        def at_send(body):
            seen["files"] = sorted(p.name for p in isolated_snapshots.glob("*.json"))

        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))

        async with client:
            result = await checkout.order_create(
                client,
                "1",
                confirm=True,
                send=Recorder(response=order_response(), on_send=at_send),
            )

        assert len(seen["files"]) == 1
        assert result["snapshot"]["written"] is True
        assert (
            "no route anywhere in Uplers that cancels an order"
            in result["snapshot_is_not_an_undo"]
        )
        assert "CATALOGUE PRICE you were shown" in result["snapshot_is_not_an_undo"]

    async def test_the_preview_writes_no_snapshot_and_sends_nothing(self):
        client, calls = client_over(by_path({PLANS_PATH: plans_payload()}))
        sender = Recorder()

        async with client:
            result = await checkout.order_create(client, "1", send=sender)

        assert result["performed"] is False
        assert result["snapshot"] == {"written": False}
        assert sender.calls == []
        assert writes(calls) == []

    async def test_the_confirmed_result_prints_the_order_beside_the_catalogue(self):
        """The lead's addition: a mismatch must be VISIBLE, not inferred."""
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))
        sender = Recorder(response=order_response(amount=1199, currency="INR"))

        async with client:
            result = await checkout.order_create(
                client, "1", confirm=True, send=sender
            )

        block = result["order_versus_catalogue"]
        assert block["catalogue_price"] == STARTER_PRICE
        assert block["catalogue_currency"] is None
        assert block["order_amount"] == 1199
        assert block["order_currency"] == "INR"
        assert block["differ"] is True
        assert "THEY DIFFER" in block["note"]

    async def test_matching_prices_are_reported_as_agreeing__CONTROL(self):
        """__CONTROL. A comparator that always cried mismatch would be useless
        and would make the test above pass for the wrong reason."""
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))
        sender = Recorder(response=order_response(amount=STARTER_PRICE))

        async with client:
            result = await checkout.order_create(
                client, "1", confirm=True, send=sender
            )

        assert result["order_versus_catalogue"]["differ"] is False
        assert "THEY AGREE" in result["order_versus_catalogue"]["note"]

    async def test_the_order_response_name_never_leaves(self):
        """THE LEAK THIS MODULE CLOSES. Planted, so the assertion can see it.

        Razorpay order notes carry his name and `outreach_write` returns its
        senders' responses verbatim. Copying that here would print his name into
        a transcript as a side effect of ordering a plan.
        """
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))
        sender = Recorder(response=order_response())

        async with client:
            result = await checkout.order_create(
                client, "1", confirm=True, send=sender
            )

        assert LIVE_ORDER_NAME not in json.dumps(result)
        assert result["response_redacted_keys"] == ["notes"]
        # the DROP is reported rather than done quietly - the reader is told the
        # platform sent notes and that their values were withheld
        assert result["response"]["notes"]["present"] is True
        assert result["response"]["notes"]["keys"] == ["name"]
        # and the commercially load-bearing fields survive, which is the whole
        # reason the response is returned at all
        assert result["response"]["id"] == "order_MEASURED1"
        assert result["response"]["amount"] == STARTER_PRICE

    async def test_the_leak_assertion_can_actually_fail__CONTROL(self):
        """__CONTROL. `X not in dumps(result)` passes trivially against a result
        that never contained X, so the scrub is proven to be what removes it."""
        raw = order_response()

        assert LIVE_ORDER_NAME in json.dumps(raw)
        described, dropped = checkout.describe_order_response(raw)
        assert LIVE_ORDER_NAME not in json.dumps(described)
        assert dropped == ["notes"]

    async def test_guard_5_says_it_is_not_an_independent_read_back(self):
        """Guard 5 answered HONESTLY. No route reads orders back, and it says so
        rather than implying a confirmation it did not make."""
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))

        async with client:
            result = await checkout.order_create(
                client, "1", confirm=True, send=Recorder(response=order_response())
            )

        assert result["verified"]["re_read"] is False
        assert result["verified"]["landed"] is True
        assert result["verified"]["order_id"] == "order_MEASURED1"
        assert "NOT an independent read-back" in result["verified"]["note"]

    async def test_a_response_with_no_order_id_is_reported_as_unknown__CONTROL(self):
        """__CONTROL for the verifier. `landed: True` on every response would
        make the assertion above meaningless."""
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))

        async with client:
            result = await checkout.order_create(
                client, "1", confirm=True, send=Recorder(response={"status": 200})
            )

        assert result["verified"]["landed"] is False
        assert "CARRIED NO ORDER ID" in result["verified"]["note"]

    async def test_it_says_in_the_result_that_it_does_not_pay(self):
        """The sentence that must survive every later edit of this file."""
        client, _ = client_over(by_path({PLANS_PATH: plans_payload()}))

        async with client:
            result = await checkout.order_create(client, "1", send=Recorder())

        joined = " ".join(result["notes"])
        assert "DOES NOT CHARGE THE CARD" in joined
        assert "UNPAID order" in joined
        assert "requires a browser" in joined
        assert "PAYING IS NOT BUILT AND CANNOT BE" in joined


# ==========================================================================
# B. uplers_health_check_order_create
# ==========================================================================


class TestHealthCheckOrderCreate:

    async def test_it_reads_both_routes_of_the_join_and_only_those(self):
        """GUARD 1: read-live, ACROSS TWO ROUTES.

        The second route is not in this tool's name and a reader should not
        have to discover it, so the pair is asserted exactly.
        """
        client, calls = client_over(health_check_reads())
        sender = Recorder(path=endpoints.EP_HEALTH_CHECK_ORDER_CREATE)

        async with client:
            await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, send=sender
            )

        assert routes_of(calls) == [
            endpoints.EP_SKU_HEALTH_CHECK_LAST,
            endpoints.EP_SKU_HEALTH_CHECK_DASHBOARD,
        ]
        assert writes(calls) == []

    async def test_the_join_resolves_the_measured_pair(self):
        """MEASURED: rtid 150705 -> exactly one row -> id 152462."""
        client, _ = client_over(health_check_reads())

        async with client:
            result = await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, send=Recorder()
            )

        block = result["resolved_from"]
        assert block["transformation_id"] == LIVE_TRANSFORMATION_ID
        assert block["dashboard_rows"] == 3
        assert block["matching_rows"] == 1
        assert result["health_check_id"] == LIVE_HEALTH_CHECK_ID
        assert block["dashboard_route"] == endpoints.EP_SKU_HEALTH_CHECK_DASHBOARD

    async def test_the_join_runs_against_the_committed_captures(self):
        """The FIXTURES, not hand-built payloads. The join must hold against the
        bytes the platform actually sent, which is what makes the restored
        `outreach_agent_plans.json` and these two load-bearing rather than
        decorative."""
        client, _ = client_over(
            by_path(
                {
                    LAST_HEALTH_PATH: load_talent_fixture("sku_health_check_last"),
                    DASHBOARD_PATH: load_talent_fixture("sku_health_check_dashboard"),
                }
            )
        )

        async with client:
            result = await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, send=Recorder()
            )

        assert result["health_check_id"] == LIVE_HEALTH_CHECK_ID
        assert result["resolved_from"]["transformation_id"] == LIVE_TRANSFORMATION_ID

    async def test_a_health_check_id_that_is_not_the_live_one_refuses(self):
        """GUARD 4. A paid order must not be aimed at somebody else's check."""
        client, calls = client_over(health_check_reads())
        sender = Recorder()

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.health_check_order_create(
                    client, 152456, 499, confirm=True, send=sender
                )

        message = str(excinfo.value)
        assert "is not the health check this account holds" in message
        assert str(LIVE_HEALTH_CHECK_ID) in message
        assert sender.calls == []
        assert writes(calls) == []

    async def test_a_missing_transformation_id_refuses_with_its_own_reason(self):
        """The FIRST of three join failures, said differently from the others."""
        client, calls = client_over(
            health_check_reads(last=last_health_payload(transformation_id=None))
        )

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.health_check_order_create(
                    client, LIVE_HEALTH_CHECK_ID, 499, confirm=True, send=Recorder()
                )

        assert "reported no `transform.resume_transformation_id`" in str(excinfo.value)
        assert writes(calls) == []

    async def test_a_transformation_id_matching_no_row_refuses(self):
        """The SECOND join failure: the two routes disagree."""
        client, calls = client_over(
            health_check_reads(last=last_health_payload(transformation_id=999999))
        )

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.health_check_order_create(
                    client, LIVE_HEALTH_CHECK_ID, 499, confirm=True, send=Recorder()
                )

        assert "NONE of the 3 row(s)" in str(excinfo.value)
        assert writes(calls) == []

    async def test_an_ambiguous_join_refuses_rather_than_picking_one(self):
        """The THIRD join failure, and the one where a tie-break would be worst.

        Every rule that picks one of several is a rule that can pick the wrong
        one on a route that spends money, so there is deliberately none.
        """
        duplicated = dashboard_payload(
            rows=[
                {"id": 152462, "resume_transformation_id": 150705, "resume_score": 89,
                 "created_at": "2026-08-11T12:20:40.000000Z", "health_check_status": 3},
                {"id": 152999, "resume_transformation_id": 150705, "resume_score": 91,
                 "created_at": "2026-08-12T12:20:40.000000Z", "health_check_status": 3},
            ]
        )
        client, calls = client_over(health_check_reads(dashboard=duplicated))

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.health_check_order_create(
                    client, LIVE_HEALTH_CHECK_ID, 499, confirm=True, send=Recorder()
                )

        assert "matches 2 rows" in str(excinfo.value)
        assert "AMBIGUOUS" in str(excinfo.value)
        assert writes(calls) == []

    async def test_the_body_is_exactly_three_keys(self):
        """GUARD 2: the exact key SET."""
        client, _ = client_over(health_check_reads())
        sender = Recorder(response=order_response(amount=499))

        async with client:
            result = await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, confirm=True, send=sender
            )

        assert set(sender.calls[0]) == set(checkout.HEALTH_CHECK_ORDER_BODY_KEYS)
        assert set(sender.calls[0]) == {"amount", "health_check_id", "is_tailored"}
        assert result["body_keys"] == ["amount", "health_check_id", "is_tailored"]

    async def test_is_tailored_goes_on_the_wire_as_one_and_zero(self):
        """THE WIRE SHAPE, asserted against SERIALISED JSON.

        `json.dumps(True)` is `true`, a different value from `1`. A dict-level
        assertion cannot tell them apart, so this checks the bytes.
        """
        client, _ = client_over(health_check_reads())
        on_sender = Recorder(response=order_response(amount=499))

        async with client:
            await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, is_tailored=True,
                confirm=True, send=on_sender,
            )

        body = on_sender.calls[0]
        assert body["is_tailored"] == 1
        assert body["is_tailored"] is not True
        assert '"is_tailored": 1' in json.dumps(body, indent=1).replace("\n", "")
        assert "true" not in json.dumps(body)

        off_sender = Recorder(response=order_response(amount=499))
        client, _ = client_over(health_check_reads())
        async with client:
            await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, is_tailored=False,
                confirm=True, send=off_sender,
            )

        assert off_sender.calls[0]["is_tailored"] == 0
        assert off_sender.calls[0]["is_tailored"] is not False
        assert "false" not in json.dumps(off_sender.calls[0])

    async def test_the_bool_trap_is_real__CONTROL(self):
        """__CONTROL. Proves `json.dumps` really does render a bool as `true`,
        so the assertions above are watching a live hazard rather than a
        hypothetical one."""
        assert json.dumps({"is_tailored": True}) == '{"is_tailored": true}'
        assert json.dumps({"is_tailored": 1}) == '{"is_tailored": 1}'
        assert json.dumps(checkout.as_wire_flag(True)) == "1"
        assert json.dumps(checkout.as_wire_flag(False)) == "0"

    async def test_the_preview_prints_the_amount_with_its_unlabelled_currency(self):
        """The amount is IN THE BODY here, so the preview has it pre-flight."""
        client, _ = client_over(health_check_reads())

        async with client:
            result = await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, send=Recorder()
            )

        assert result["amount"]["value"] == 499
        assert result["amount"]["currency"] is None
        assert "nothing on any route" in result["amount"]["currency_is_unknown_because"]
        assert "carries the amount ITSELF" in result["amount"][
            "in_the_body_not_resolved_by_the_platform"
        ]

    @pytest.mark.parametrize("bad", [0, -1, -1499])
    async def test_a_non_positive_amount_refuses(self, bad):
        client, calls = client_over(health_check_reads())

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.health_check_order_create(
                    client, LIVE_HEALTH_CHECK_ID, bad, confirm=True, send=Recorder()
                )

        assert "is not an amount" in str(excinfo.value)
        assert writes(calls) == []

    @pytest.mark.parametrize("bad", ["1499", 1499.0, True, None, [1499]])
    async def test_a_non_integer_amount_refuses_rather_than_coercing(self, bad):
        """STRICTER than every other coercion in this repo, on purpose.

        A wrong id fails; a wrong amount SUCCEEDS at the wrong number and no
        route reads it back. `True` is in this list because `isinstance(True,
        int)` is True in Python and a bool reaching a price is nonsense.
        """
        client, calls = client_over(health_check_reads())

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.health_check_order_create(
                    client, LIVE_HEALTH_CHECK_ID, bad, confirm=True, send=Recorder()
                )

        assert "is not an amount" in str(excinfo.value)
        assert writes(calls) == []

    async def test_a_valid_amount_is_accepted__CONTROL(self):
        """__CONTROL. A validator that refused every amount would make the two
        tests above pass while the tool did nothing."""
        client, _ = client_over(health_check_reads())
        sender = Recorder(response=order_response(amount=499))

        async with client:
            result = await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, confirm=True, send=sender
            )

        assert result["performed"] is True
        assert sender.calls[0]["amount"] == 499

    async def test_the_amount_is_refused_before_anything_is_read(self):
        """ORDERING. A bad amount must not even cost two GETs against his
        account, let alone reach a snapshot."""
        client, calls = client_over(health_check_reads())

        async with client:
            with pytest.raises(WriteRefused):
                await checkout.health_check_order_create(
                    client, LIVE_HEALTH_CHECK_ID, 0, confirm=True, send=Recorder()
                )

        assert calls == []

    async def test_the_snapshot_is_written_before_the_send(self, isolated_snapshots):
        seen = {}

        def at_send(body):
            seen["files"] = sorted(p.name for p in isolated_snapshots.glob("*.json"))

        client, _ = client_over(health_check_reads())

        async with client:
            result = await checkout.health_check_order_create(
                client,
                LIVE_HEALTH_CHECK_ID,
                499,
                confirm=True,
                send=Recorder(response=order_response(amount=499), on_send=at_send),
            )

        assert len(seen["files"]) == 1
        assert result["snapshot"]["written"] is True

    async def test_the_order_response_name_never_leaves(self):
        client, _ = client_over(health_check_reads())

        async with client:
            result = await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, confirm=True,
                send=Recorder(response=order_response(amount=499)),
            )

        assert LIVE_ORDER_NAME not in json.dumps(result)
        assert result["response_redacted_keys"] == ["notes"]

    async def test_it_says_in_the_result_that_it_does_not_pay(self):
        client, _ = client_over(health_check_reads())

        async with client:
            result = await checkout.health_check_order_create(
                client, LIVE_HEALTH_CHECK_ID, 499, send=Recorder()
            )

        joined = " ".join(result["notes"])
        assert "DOES NOT CHARGE THE CARD" in joined
        assert "PAYING IS NOT BUILT AND CANNOT BE" in joined


# ==========================================================================
# C + D. uplers_request_refund - one tool, two routes
# ==========================================================================


class TestRequestRefund:

    async def test_the_body_is_empty_by_default(self):
        """GUARD 2. The MEASURED default is `{}` and it is not padded out."""
        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))
        sender = Recorder(path=endpoints.EP_TAILOR_REFUND_REQUEST, kind="tailor")

        async with client:
            result = await checkout.request_refund(
                client, "tailor", confirm=True, send=sender
            )

        assert sender.calls == [{}]
        assert set(sender.calls[0]) == set(checkout.REFUND_BODY_KEYS)
        assert result["body_keys"] == []

    async def test_a_supplied_transformation_id_is_the_only_addition(self):
        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))
        sender = Recorder(
            path=endpoints.EP_HEALTH_CHECK_REFUND_REQUEST, kind="resume_health_check"
        )

        async with client:
            result = await checkout.request_refund(
                client,
                "resume_health_check",
                transformation_id=LIVE_TRANSFORMATION_ID,
                confirm=True,
                send=sender,
            )

        assert sender.calls == [{"transformation_id": LIVE_TRANSFORMATION_ID}]
        assert set(sender.calls[0]) == set(
            checkout.REFUND_BODY_KEYS_WITH_TRANSFORMATION
        )
        assert result["body_keys"] == ["transformation_id"]

    @pytest.mark.parametrize("bad", ["150705", 150705.0, True, 0, -1])
    async def test_a_bad_transformation_id_refuses(self, bad):
        client, calls = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.request_refund(
                    client, "tailor", transformation_id=bad, confirm=True,
                    send=Recorder(kind="tailor"),
                )

        assert "not a transformation id" in str(excinfo.value)
        assert writes(calls) == []

    async def test_an_unknown_kind_refuses_rather_than_defaulting(self):
        """The kind PICKS THE ROUTE, so a default would claim against the wrong
        product."""
        client, calls = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.request_refund(
                    client, "tailer", confirm=True, send=Recorder(kind="tailor")
                )

        assert "not a refund kind" in str(excinfo.value)
        assert writes(calls) == []

    async def test_a_second_request_within_24h_refuses(self, isolated_markers):
        """UPLERS' OWN ONCE-PER-DAY LIMIT, mirrored locally.

        Their UI writes a `refund-request-raised` stamp to localStorage after a
        successful request and disables the button for a day. The first request
        here writes the marker; the second must be refused by it.
        """
        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))
        first = Recorder(path=endpoints.EP_TAILOR_REFUND_REQUEST, kind="tailor")

        async with client:
            performed = await checkout.request_refund(
                client, "tailor", confirm=True, send=first
            )

        assert performed["performed"] is True
        assert performed["rate_limit_marker"]["written"] is True
        assert first.calls == [{}]

        second = Recorder(path=endpoints.EP_TAILOR_REFUND_REQUEST, kind="tailor")
        client, calls = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            with pytest.raises(WriteRefused) as excinfo:
                await checkout.request_refund(
                    client, "tailor", confirm=True, send=second
                )

        message = str(excinfo.value)
        assert "ONCE PER DAY" in message
        # the refusal says WHOSE limit it is rather than implying it is ours
        assert checkout.UPLERS_REFUND_MARKER_KEY in message
        assert "not a rule this server invented" in message
        assert second.calls == []
        assert writes(calls) == []

    async def test_the_rate_limit_is_per_kind(self):
        """A tailor request must not block a health-check one. They are claims
        against different products and Uplers gates them separately."""
        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            await checkout.request_refund(
                client, "tailor", confirm=True,
                send=Recorder(kind="tailor"),
            )

        other = Recorder(kind="resume_health_check")
        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            result = await checkout.request_refund(
                client, "resume_health_check", confirm=True, send=other
            )

        assert result["performed"] is True
        assert other.calls == [{}]

    async def test_the_limit_expires__CONTROL(self, isolated_markers):
        """__CONTROL. A gate that refused FOREVER would pass the test above and
        lock him out of his own money permanently. The window really is 24h."""
        checkout.write_refund_marker(
            "tailor", body={}, now=1_000_000.0
        )

        blocked = checkout.refund_gate("tailor", now=1_000_000.0 + 3600)
        assert blocked["allowed"] is False
        assert blocked["seconds_remaining"] > 0

        expired = checkout.refund_gate(
            "tailor", now=1_000_000.0 + checkout.REFUND_LIMIT_SECONDS + 1
        )
        assert expired["allowed"] is True
        assert expired["seconds_remaining"] == 0

    async def test_the_preview_sets_no_marker_and_sends_nothing(self, isolated_markers):
        """A preview must not consume today's single request."""
        client, calls = client_over(by_path({}, fallback={"status": 200, "data": {}}))
        sender = Recorder(kind="tailor")

        async with client:
            result = await checkout.request_refund(client, "tailor", send=sender)

        assert result["performed"] is False
        assert result["snapshot"] == {"written": False}
        assert sender.calls == []
        assert writes(calls) == []
        assert list(isolated_markers.glob("*.json")) == []
        assert checkout.refund_gate("tailor")["allowed"] is True

    async def test_the_marker_is_written_after_the_send_not_before(
        self, isolated_markers
    ):
        """ORDERING, and this one runs the OPPOSITE way from the snapshot.

        Uplers write their stamp in the success handler, and this mirrors that
        deliberately: writing first would lock him out for a day on a request
        that never left the machine.
        """
        seen = {}

        def at_send(body):
            seen["files"] = sorted(p.name for p in isolated_markers.glob("*.json"))

        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            await checkout.request_refund(
                client, "tailor", confirm=True,
                send=Recorder(kind="tailor", on_send=at_send),
            )

        assert seen["files"] == []
        assert sorted(p.name for p in isolated_markers.glob("*.json")) == [
            "refund-tailor.json"
        ]

    async def test_the_snapshot_is_written_before_the_send(self, isolated_snapshots):
        seen = {}

        def at_send(body):
            seen["files"] = sorted(p.name for p in isolated_snapshots.glob("*.json"))

        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            result = await checkout.request_refund(
                client, "tailor", confirm=True,
                send=Recorder(kind="tailor", on_send=at_send),
            )

        assert len(seen["files"]) == 1
        assert result["snapshot"]["written"] is True

    async def test_it_reads_no_live_route_and_says_why(self):
        """GUARD 1 ANSWERED BY AN ABSENCE, which is the honest answer here.

        There is no route that reports refund state, so this tool reads NOTHING
        live - and it must not fetch an unrelated route in order to look like it
        checked something. The zero-request count is the assertion.
        """
        client, calls = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            result = await checkout.request_refund(
                client, "tailor", confirm=True, send=Recorder(kind="tailor")
            )

        assert calls == []
        assert "NO route that reports refund state" in result[
            "guard_1_has_no_live_record"
        ]

    async def test_guard_5_reports_that_it_cannot_verify(self):
        """The measurement, not a shortfall: nothing reports refund status."""
        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            result = await checkout.request_refund(
                client, "tailor", confirm=True, send=Recorder(kind="tailor")
            )

        assert result["verified"]["re_read"] is False
        assert result["verified"]["landed"] is None
        assert result["verified"]["route"] is None
        assert "NO ROUTE ANYWHERE IN UPLERS REPORTS REFUND STATUS" in result[
            "verified"
        ]["note"]
        assert "Nobody has observed a refund completing" in result["verified"]["note"]

    async def test_it_is_named_and_described_as_a_request(self):
        """Uplers' own copy, quoted rather than paraphrased."""
        client, _ = client_over(by_path({}, fallback={"status": 200, "data": {}}))

        async with client:
            result = await checkout.request_refund(
                client, "tailor", send=Recorder(kind="tailor")
            )

        assert checkout.UPLERS_REFUND_CONFIRM_COPY in result[
            "it_is_a_request_not_a_refund"
        ]
        assert "raise a refund request?" in result["it_is_a_request_not_a_refund"]
        joined = " ".join(result["notes"])
        assert "IT IS A REQUEST, NOT A REFUND" in joined
        assert "NOBODY HAS OBSERVED A REFUND COMPLETING" in joined


# ==========================================================================
# The census this module has to satisfy on its own account
# ==========================================================================


class TestTheModuleCannotReachAWriteRouteByItself:

    def test_checkout_names_none_of_the_four_write_constants(self):
        """THE SEAM, asserted by AST rather than by trust.

        The same pin `test_agent_tools.py` keeps on the consent route, and it
        binds hardest here: `checkout.py` builds the bodies, and if it also held
        the route strings then "no order was created" would rest on nobody
        having written the two lines that would create one. server.py builds
        every sender and hands it in, so the module CANNOT reach the wire.

        Parses the syntax tree rather than grepping, for the reason that test
        gives: this file's own documentation names these routes in prose in
        order to explain them, and a substring match would push the next
        maintainer to stop writing about them.
        """
        import ast
        import pathlib

        path = pathlib.Path(checkout.__file__)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.attr if isinstance(node, ast.Attribute) else node.id
            for node in ast.walk(tree)
            if isinstance(node, (ast.Attribute, ast.Name))
        }

        for constant in (
            "EP_TAILOR_ORDER_CREATE",
            "EP_HEALTH_CHECK_ORDER_CREATE",
            "EP_TAILOR_REFUND_REQUEST",
            "EP_HEALTH_CHECK_REFUND_REQUEST",
        ):
            assert constant not in names, (
                "checkout.py names %s in code. It must not: server.py builds "
                "the sender and hands it in, which is what makes 'this module "
                "cannot spend money' a claim about control flow." % constant
            )

        # and the READ constants really are there, so the assertions above are
        # not passing against a module that names nothing at all
        assert "EP_OUTREACH_AGENT_PLANS" in names
        assert "EP_SKU_HEALTH_CHECK_DASHBOARD" in names

    def test_server_owns_the_kind_to_route_mapping(self):
        """One dict, pinned against endpoints.py.

        A third kind added to `checkout.REFUND_KINDS` without a route here
        would `KeyError` at call time on a money tool; a route added here
        without a kind would be unreachable. Pinning both directions makes
        either half fail in the suite instead.
        """
        assert set(server_mod.REFUND_ROUTES) == set(checkout.REFUND_KINDS)
        assert server_mod.REFUND_ROUTES["tailor"] == endpoints.EP_TAILOR_REFUND_REQUEST
        assert (
            server_mod.REFUND_ROUTES["resume_health_check"]
            == endpoints.EP_HEALTH_CHECK_REFUND_REQUEST
        )
        # the two routes are DIFFERENT strings - a mapping where both kinds
        # pointed at one route would satisfy a laxer check and claim against
        # the wrong product every time
        assert len(set(server_mod.REFUND_ROUTES.values())) == 2

    def test_the_capture_routes_are_recorded_as_impossible_not_merely_absent(self):
        """What CANNOT be built, carried as data so the claim is checkable."""
        assert checkout.CAPTURE_ROUTES == (
            "talent/tailor/order/capture",
            "talent/resume-health-check/capture-order",
        )
        assert set(checkout.CAPTURE_BODY_KEYS) == {
            "razorpayOrderId",
            "razorpayPaymentId",
            "razorpaySignature",
            "order_id",
            "payment_completed",
        }
        assert checkout.CAPTURE_HOST == "https://lrr-platform.uplers.com/api/"
        assert checkout.CAPTURE_HOST not in json.dumps(
            [value for name, value in vars(endpoints).items() if name.startswith("EP_")]
        )

    def test_neither_capture_route_has_a_constant(self):
        """The rule endpoints.py states: a constant is an invitation to call it.

        These two can never acquire one - their body carries values Razorpay
        mints and SIGNS after a real card payment.
        """
        values = {
            value
            for name, value in vars(endpoints).items()
            if name.startswith("EP_") and isinstance(value, str)
        }
        for route in checkout.CAPTURE_ROUTES:
            assert route not in values

    def test_the_second_host_is_reachable_from_nothing_that_sends(self):
        """It is DOCUMENTED in three files and REACHABLE from none of them.

        WRITTEN THIS WAY AFTER THE OBVIOUS VERSION FAILED, and the failure was
        the test being wrong rather than the server. A "no file may contain
        this string" sweep went red naming `server.py` and `endpoints.py` -
        both of which name the host in PROSE, in order to record that it has
        never been contacted. That is the substring trap
        `test_agent_tools.py` documents: a check that fires on documentation
        pushes the next maintainer to stop writing the documentation.

        So the assertion moved to what actually decides whether a request can
        go there: the client's base URL, and whether any route constant carries
        it. A path constant is joined onto `API_BASE`, so a route can only
        reach another host by that host appearing in one of those two places.
        """
        from uplers_server import config

        assert checkout.CAPTURE_HOST not in endpoints.API_BASE
        assert "lrr-platform" not in endpoints.API_BASE
        assert "lrr-platform" not in config.BASE_URL

        constants = {
            name: value
            for name, value in vars(endpoints).items()
            if name.startswith("EP_") and isinstance(value, str)
        }
        carrying = sorted(
            name for name, value in constants.items() if "lrr-platform" in value
        )
        assert carrying == [], (
            "these route constants carry the capture host, which this server "
            "has never contacted: %s" % carrying
        )

        # and the capture SCRIPTS - the only things in this repo that fire at
        # his live account - do not name it at all, in prose or otherwise
        import pathlib

        root = pathlib.Path(checkout.__file__).resolve().parent.parent
        firing = sorted(
            path.name
            for path in (root / "scripts").glob("*.py")
            if "lrr-platform" in path.read_text(encoding="utf-8")
        )
        assert firing == [], (
            "these capture scripts name the capture host: %s" % firing
        )


# ==========================================================================
# The envelope idiom, measured per route rather than assumed
# ==========================================================================


class TestTheCatalogueEnvelope:

    def test_the_catalogue_answers_the_string_success_not_the_integer(self):
        """MEASURED, and it differs from the three SKU reads beside it.

        `outreach.unwrap` takes both idioms and refuses everything else, which
        is exactly why the difference is pinned per route instead of assumed
        from a neighbour.
        """
        assert load_talent_fixture("outreach_agent_plans")["status"] == "success"
        assert load_talent_fixture("sku_health_check_last")["status"] == 200

    def test_a_catalogue_in_an_unreadable_shape_refuses_rather_than_guessing(self):
        """A LIST where an object was measured means the route changed, not that
        a plan is missing - and those two need different refusals."""
        with pytest.raises(WriteRefused) as excinfo:
            checkout.read_agent_plans(
                {"status": "success", "data": {"agent_tailor_plans": []}}
            )

        assert "not the object keyed by plan id" in str(excinfo.value)

    def test_a_broken_envelope_is_refused_by_unwrap__CONTROL(self):
        """__CONTROL. Proves the reader really does go through `unwrap` rather
        than reaching into `data` and hoping."""
        with pytest.raises(OutreachError):
            checkout.read_agent_plans({"data": {"agent_tailor_plans": {}}})

    def test_the_measured_catalogue_reads_two_plans(self):
        catalogue = checkout.read_agent_plans(plans_payload())

        assert sorted(catalogue) == ["1", "3"]
        assert catalogue["1"]["price"] == STARTER_PRICE
        assert catalogue["3"]["price"] == ELITE_PRICE
        assert catalogue["1"]["currency"] is None
        assert catalogue["3"]["currency"] is None
