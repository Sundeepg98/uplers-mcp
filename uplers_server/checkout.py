"""The four gated writes over Uplers' PAID checkout.

`outreach_write` holds the four REVERSIBLE settings writes; `consent_write`
holds the two that are not reversible settings switches. This module holds the
four that involve MONEY, and it is filed apart from both for the reason those
two files state about each other: a group whose claim is "all of these can be
put back" stops meaning anything the moment a purchase is filed in it.

**These four were ruled IN SCOPE knowingly.** They are not here because a line
moved by accident, and this file does not re-argue it. What it does is make the
spend VISIBLE BEFORE IT HAPPENS, which is the only thing a client can usefully
do about a paid route.

WHAT EACH ONE ACTUALLY DOES, WHICH IS NARROWER THAN "IT BUYS SOMETHING"
-----------------------------------------------------------------------
*   :func:`order_create` and :func:`health_check_order_create` **DO NOT CHARGE
    THE CARD.** They mint a Razorpay ORDER. The card is charged inside
    Razorpay's hosted widget, which this server cannot drive. A confirmed call
    therefore leaves a REAL, UNPAID order record on his account, and paying it
    still requires a browser. Both docstrings say so where he will read it.
*   :func:`request_refund` **RAISES A REQUEST. IT IS NOT A REFUND.** Uplers'
    own confirm dialog reads *"Are you sure you want to raise a refund
    request?"*, and what happens on their side afterwards is UNMEASURED.

THE FIVE GUARDS, AND THE TWO PLACES THIS FILE HAD TO DEPART FROM THEM
----------------------------------------------------------------------
The doctrine is ``outreach_write``'s and is not restated at length. What is
DIFFERENT here:

1.  **read-live.** The tailor order reads the LIVE PLAN CATALOGUE and refuses a
    plan id the platform does not list. The health-check order reads TWO live
    routes (below). **The two refund routes have NO live record to read, and
    that absence is reported rather than papered over**: Uplers publishes no
    route that reports refund state, so reading an unrelated route to have
    something to show would be theatre. Guard 1 is answered by saying so.
2.  **exact-body preview.** Each body's key SET is pinned as a tuple here and
    asserted as a set equality in the suite, so a smuggled extra key fails
    loudly. On a payment route a body nobody previewed with that key in it is
    the failure with no floor under it.
3.  **snapshot-before.** Written to disk before the send. **NONE OF THESE
    SNAPSHOTS IS AN UNDO** and every result says so. What the order snapshots
    record is the PRICE HE WAS SHOWN at the moment he confirmed, which is worth
    having for a different reason than a rollback.
4.  **empty-refusal.** A plan not in the live catalogue, a health check that is
    not the one the account holds, a non-positive amount, a second refund
    request inside 24 hours: all refuse, none sends.
5.  **re-read-verify.** **THERE IS NO READ-BACK ROUTE FOR ANY OF THE FOUR.**
    No route in this server reads orders back, and no route ANYWHERE in Uplers
    reports refund status. So the orders are verified from the CREATE's own
    response - which really does carry the order id, amount and currency - and
    the refunds report their verification as UNAVAILABLE rather than claiming a
    read-back that does not exist. An honest "cannot be verified" is guard 5
    running; a silent skip is guard 5 missing.

THE HEALTH-CHECK JOIN, which a reader should not have to discover
------------------------------------------------------------------
:func:`health_check_order_create` READS TWO ROUTES, and the second one is not
named by the tool. ``talent/outreach/get-last-health-check`` reports the last
health check but **carries no id for it** - MEASURED, its ``health_check``
object holds only ``{created_at, final_verdict, resume_score, status}``, and
that is not a redaction artefact (``id`` is in no drop list in
``scripts/capture_outreach.py``, and ``transform.id`` on the same payload
survives untouched). The ids live on
``talent/resume-health-check/dashboard``. So the id of "the health check this
account holds" is resolved by joining the first route's
``transform.resume_transformation_id`` to the dashboard row carrying the same
value, and the order refuses unless ``health_check_id`` equals what that join
returns. MEASURED on the captured pair: rtid 150705 matches exactly one row,
id 152462.

**A JOIN THAT DOES NOT LAND EXACTLY ONCE REFUSES.** No fallback to a weaker
rule: an absent ``resume_transformation_id``, zero matching rows and more than
one matching row are three different refusals, each naming which happened.

TWO FACTS THAT BELONG IN THIS FILE RATHER THAN IN A COMMIT MESSAGE
--------------------------------------------------------------------
1.  **``order/capture`` IS NOT BUILT AND CANNOT BE.** Its measured body carries
    ``razorpayOrderId``, ``razorpayPaymentId``, ``razorpaySignature``,
    ``order_id`` and ``payment_completed``, and it is called from INSIDE
    RAZORPAY'S OWN HANDLER CALLBACK - those values are minted and signed by
    Razorpay after a real card payment. **No client can produce them.** It is
    UNMEASURABLE WITHOUT SPENDING and unusable from a non-browser client. This
    is a shape refusal, not a policy one: there is no correct body to send.
2.  **CAPTURE LIVES ON A DIFFERENT HOST** - ``https://lrr-platform.uplers.com/
    api/``, not ``platform.uplers.com``. **This server has never contacted that
    host.** ``tailor/create``, ``tailor/upload`` and ``resume-transform`` are on
    it too, so anything built there later inherits an auth question nothing in
    this repo has answered.

THE ORDER RESPONSE CARRIES HIS NAME, and it is the one leak this file closes
-----------------------------------------------------------------------------
``outreach_write`` returns its senders' responses verbatim, which is safe on
routes that answer a bare status. **It is not safe here.** The create response
is ``{id, amount, currency, notes:{name}, created_at}`` - Razorpay order notes
carrying his name - and a tool result ends up in a transcript. Every order
response leaving this module goes through :func:`describe_order_response`,
which keeps the commercially load-bearing fields, drops the ``notes`` VALUES and
reports that it did. The same rule ``consent_write.scrub`` applies to the
mailbox address; different key, same reason.

EVIDENCE
--------
Every wire fact - the routes, the three key sets, the 9 / 1 / 5 call-site
counts, the capture body, the second host, and Uplers' own once-per-day refund
gate - is MEASURED from call sites in Uplers' production bundle. The plan
catalogue and the health-check pair are MEASURED from fixtures captured live
off his own session and committed here.

**NOTHING IN THIS FILE HAS EVER BEEN FIRED AGAINST HIS ACCOUNT.** No order has
been created, no refund has been requested, and the suite that exercises it
runs entirely on ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import config, endpoints, policy
from .outreach import unwrap

# INHERITED, not re-implemented, exactly as `consent_write` inherits them. The
# snapshot writer, the JSON sender seam and the no-sender refusal are
# `outreach_write`'s and stay there: a second copy of "every confirmed write
# writes a restore point first" is a second thing to keep true.
from . import outreach_write

# The shared guard class, imported and NOT subclassed - `consent_write`'s call,
# and for its reason. A caller that catches "this server refused a write"
# should not need a fourth name to know.
from .profile_write import WriteRefused

# --- Read-back routes ------------------------------------------------------
#
# ALIASES. endpoints.py is the route authority and this module holds no path
# strings of its own. **NONE OF THE FOUR WRITE ROUTES IS NAMED HERE** -
# server.py builds every sender and hands it in, so no constant this module
# holds can put anything on the wire. tests/test_checkout.py asserts that
# absence by AST, the same pin test_agent_tools.py keeps on the consent route.

#: Guard 1 for the tailor order. The LIVE price catalogue.
EP_READ_AGENT_PLANS = endpoints.EP_OUTREACH_AGENT_PLANS

#: Guard 1 for the health-check order, first half of the join.
EP_READ_HEALTH_CHECK_LAST = endpoints.EP_SKU_HEALTH_CHECK_LAST

#: Guard 1 for the health-check order, second half. The route that actually
#: carries health-check IDS - see the module docstring.
EP_READ_HEALTH_CHECK_DASHBOARD = endpoints.EP_SKU_HEALTH_CHECK_DASHBOARD


# --- The three body shapes -------------------------------------------------

#: **ONE KEY.** VERIFIED at 9 call sites in Uplers' bundle, all identical, every
#: one a bare variable (`{plan_id:t}`) with no `Number()` cast anywhere.
TAILOR_ORDER_BODY_KEYS = ("plan_id",)

#: **THREE KEYS.** VERIFIED, 1 call site. `is_tailored` goes on the wire as the
#: integer 1 or 0 - never `true`/`false` - which is pinned by its own test.
HEALTH_CHECK_ORDER_BODY_KEYS = ("amount", "health_check_id", "is_tailored")

#: **EMPTY**, and `transformation_id` is added only when one is supplied.
#: VERIFIED, 5 call sites across the two refund routes.
REFUND_BODY_KEYS = ()
REFUND_BODY_KEYS_WITH_TRANSFORMATION = ("transformation_id",)

#: The two products a refund can be requested for. `kind` picks the ROUTE, and
#: server.py owns that mapping - see :func:`refund_sender_for`.
REFUND_KINDS = ("tailor", "resume_health_check")

#: Uplers' own gate, mirrored rather than invented. Their UI writes a
#: `refund-request-raised` timestamp to localStorage after a successful request
#: and rate-limits the button to once per day. This is that day, in seconds.
REFUND_LIMIT_SECONDS = 24 * 60 * 60

#: Their localStorage key, recorded so the refusal can say whose limit it is.
UPLERS_REFUND_MARKER_KEY = "refund-request-raised"

#: Uplers' own confirm copy, quoted verbatim. It says REQUEST, and so does this.
UPLERS_REFUND_CONFIRM_COPY = "Are you sure you want to raise a refund request?"

#: What CANNOT be built, carried as data rather than prose because the claim
#: "no client can produce these" is only as good as the enumeration behind it.
CAPTURE_ROUTES = (
    "talent/tailor/order/capture",
    "talent/resume-health-check/capture-order",
)
CAPTURE_BODY_KEYS = (
    "razorpayOrderId",
    "razorpayPaymentId",
    "razorpaySignature",
    "order_id",
    "payment_completed",
)

#: The host this server has NEVER contacted, and the three other routes on it.
CAPTURE_HOST = "https://lrr-platform.uplers.com/api/"
SECOND_HOST_ROUTES = ("tailor/create", "tailor/upload", "resume-transform")

#: Dropped from every order response this module returns. Razorpay order notes
#: carry his NAME, and a tool result ends up in a transcript.
ORDER_RESPONSE_WITHHELD = ("notes",)


def markers_dir() -> Path:
    """Its own directory, beside the snapshot dirs and deliberately not inside.

    A refund marker is not a restore point and must not list as one: the
    snapshot listers glob their own directories and a marker filed there would
    read as a record somebody could restore from, which is the opposite of what
    it is.
    """
    path = config.DATA_DIR / "checkout_markers"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ===========================================================================
# Reading the live records
# ===========================================================================


def read_agent_plans(payload: Any) -> dict:
    """The live plan catalogue, keyed by the catalogue's OWN key.

    MEASURED: ``data.agent_tailor_plans`` is an OBJECT keyed by the strings
    ``"1"`` and ``"3"``, not a list, and each entry carries ``Name``, ``Price``,
    ``PriceText``, ``Validity`` and ``ValidityText``.

    **THERE IS NO CURRENCY FIELD ANYWHERE IN THIS PAYLOAD**, so ``currency`` is
    reported as ``None`` and the price is an UNLABELLED number. That is not a
    gap in this reader; it is the measurement. Inventing "INR" here - or
    inferring it from unrelated historical transactions on another route -
    would be a guess that reads exactly like a fact, and it would be wrong the
    day Uplers prices anything in another currency.

    ``Price`` is passed through unconverted. It is the platform's number and
    casting it would be this server having an opinion about money.
    """
    data = unwrap(payload, route=EP_READ_AGENT_PLANS, expect=dict)
    raw = data.get("agent_tailor_plans")
    if not isinstance(raw, dict):
        raise WriteRefused(
            "%s returned `agent_tailor_plans` as %s, not the object keyed by "
            "plan id that this route was measured to send. That means the "
            "catalogue changed shape, not that a plan is missing - and an "
            "order must not be sent against a catalogue nothing could read. "
            "Nothing was sent." % (EP_READ_AGENT_PLANS, type(raw).__name__)
        )

    catalogue = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        catalogue[key] = {
            # THE CATALOGUE'S OWN KEY, kept as the platform sent it. This is
            # the value that goes on the wire, uncast in either direction:
            # Uplers' own callers reach the plan via `agent_tailor_plans[t]`
            # and send `{plan_id: t}`, so the wire type is theirs, not ours.
            "plan_id": key,
            "name": entry.get("Name"),
            "price": entry.get("Price"),
            "price_text": entry.get("PriceText"),
            # NOT CARRIED BY THIS ROUTE. See the docstring.
            "currency": None,
            "validity_days": entry.get("Validity"),
            "validity_text": entry.get("ValidityText"),
        }
    return catalogue


def find_plan(catalogue: dict, plan_id: Any) -> dict | None:
    """The catalogue entry for a plan id, or None. Matched as STRINGS.

    Matching is on string form because a caller may reasonably pass ``1`` while
    the catalogue keys it ``"1"`` - the same near-miss
    ``consent_write.find_company`` refuses to be beaten by. **What is SENT is
    still the catalogue's own key**, never the caller's spelling of it, so the
    lookup being lenient does not make the wire value ours.
    """
    wanted = str(plan_id).strip()
    for key, entry in catalogue.items():
        if str(key).strip() == wanted:
            return dict(entry)
    return None


def read_last_transformation_id(payload: Any) -> Any:
    """``transform.resume_transformation_id`` off ``get-last-health-check``.

    THE JOIN KEY, and the only id on that route that identifies the check the
    account holds. MEASURED 150705 on the captured payload.
    """
    data = unwrap(payload, route=EP_READ_HEALTH_CHECK_LAST, expect=dict)
    transform = data.get("transform")
    if not isinstance(transform, dict):
        return None
    return transform.get("resume_transformation_id")


def read_health_check_rows(payload: Any) -> list[dict]:
    """The dashboard's health-check history as ``{id, transformation_id, ...}``.

    **THIS IS THE ROUTE THAT CARRIES HEALTH-CHECK IDS.** MEASURED: three rows,
    ids 152462 / 152456 / 152217, transformation ids 150705 / 150699 / 150460.
    """
    data = unwrap(payload, route=EP_READ_HEALTH_CHECK_DASHBOARD, expect=dict)
    raw_rows = data.get("health_check")
    rows: list[dict] = []
    for raw in raw_rows if isinstance(raw_rows, list) else []:
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "id": raw.get("id"),
                "transformation_id": raw.get("resume_transformation_id"),
                "resume_score": raw.get("resume_score"),
                "created_at": raw.get("created_at"),
                "status_code": raw.get("health_check_status"),
            }
        )
    return rows


def resolve_health_check(transformation_id: Any, rows: list[dict]) -> dict:
    """Join the last check to its dashboard row. Exactly one match, or nothing.

    Returns ``{resolved_id, transformation_id, rows, matched, failure}`` where
    ``failure`` is ``None`` on a clean single match and otherwise names WHICH of
    the three failures happened. The caller refuses on any of them; there is
    deliberately no fallback to a weaker rule, because every weaker rule permits
    ordering against a health check that is not the one the account holds.
    """
    matched = [
        row
        for row in rows
        if row.get("transformation_id") is not None
        and str(row["transformation_id"]) == str(transformation_id)
    ]
    if transformation_id is None:
        failure = "no_transformation_id"
    elif not matched:
        failure = "no_matching_row"
    elif len(matched) > 1:
        failure = "ambiguous"
    else:
        failure = None

    return {
        "resolved_id": matched[0]["id"] if failure is None else None,
        "transformation_id": transformation_id,
        "resume_score": matched[0].get("resume_score") if failure is None else None,
        "created_at": matched[0].get("created_at") if failure is None else None,
        "rows": len(rows),
        "matched": len(matched),
        "failure": failure,
    }


def join_refusal(resolution: dict) -> str:
    """The three join failures, each said differently. Guard 1's refusal text.

    "The health check could not be resolved" is true and useless: the reader
    cannot tell whether they typed a wrong id, whether the account has no check
    at all, or whether this server just read a shape it has never seen.
    """
    failure = resolution["failure"]
    if failure == "no_transformation_id":
        return (
            "%s reported no `transform.resume_transformation_id`, which is the "
            "ONLY id on that route that identifies the health check this "
            "account holds - its `health_check` object carries no id at all. "
            "Without it there is nothing to join to the dashboard, so the id "
            "you passed cannot be checked against anything. Refusing to create "
            "a PAID order against an unverified health check. Nothing was sent."
            % EP_READ_HEALTH_CHECK_LAST
        )
    if failure == "no_matching_row":
        return (
            "The last health check reports transformation id %r, and NONE of "
            "the %d row(s) on %s carries it. The two routes disagree about what "
            "this account holds, and an order sent now would be aimed at a "
            "health check this server cannot identify. Nothing was sent."
            % (
                resolution["transformation_id"],
                resolution["rows"],
                EP_READ_HEALTH_CHECK_DASHBOARD,
            )
        )
    return (
        "Transformation id %r matches %d rows on %s, not one, so the health "
        "check it identifies is AMBIGUOUS. There is deliberately no tie-break "
        "here: every rule that picks one of several is a rule that can pick the "
        "wrong one on a route that spends money. Nothing was sent."
        % (
            resolution["transformation_id"],
            resolution["matched"],
            EP_READ_HEALTH_CHECK_DASHBOARD,
        )
    )


# ===========================================================================
# Values for the wire, refused rather than coerced
# ===========================================================================


def as_amount(value: Any) -> int:
    """A money amount for the body. STRICTER than every other coercion here.

    Refuses anything that is not a positive ``int``: no bool, no float, no
    numeric string. The other id coercions in this repo accept a string and
    convert, and that is right for an id - a wrong id fails. **A wrong amount
    SUCCEEDS**, at the wrong number, and there is no route that reads it back.

    A float is refused rather than rounded for a second reason: ``1499.0`` and
    ``1499`` look the same to a reader and the platform's own caller sends an
    integer, so accepting a float would put this server in the position of
    deciding whether a fractional amount meant rupees or paise.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise WriteRefused(
            "%r is not an amount. This body carries the price ITSELF rather "
            "than resolving it on the platform, so it must be an integer and is "
            "not coerced from anything: a wrong id fails, a wrong amount "
            "succeeds at the wrong number and no route reads it back. Uplers' "
            "own UI sources this from `resume_transform_price`. Nothing was "
            "sent." % (value,)
        )
    if value <= 0:
        raise WriteRefused(
            "%d is not an amount. A non-positive amount on a create-order route "
            "is a mistake rather than a command. Nothing was sent." % value
        )
    return value


def as_wire_flag(value: Any) -> int:
    """``1`` or ``0``. **NEVER ``True``/``False``.**

    VERIFIED: the call site sends the integer, and ``json.dumps`` renders a
    Python bool as the JSON literal ``true`` - a different value on the wire
    from ``1``. The same trap ``saved_filter.assert_integer_one`` exists for,
    and it is pinned by its own test here rather than trusted to this line.
    """
    return 1 if value else 0


def as_transformation_id(value: Any) -> Any:
    """A transformation id, passed through UNCAST once it is known to be sane.

    Refused rather than coerced for the reason ``as_amount`` gives, and passed
    through rather than converted for the reason :func:`read_agent_plans` gives:
    the wire type on this API is the platform's, not this server's.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise WriteRefused(
            "%r is not a transformation id. It is optional on this route - omit "
            "it entirely to send the measured empty body - but when it is "
            "supplied it goes into the body of a request that raises a money "
            "claim, so it is refused rather than coerced. Nothing was sent."
            % (value,)
        )
    if value <= 0:
        raise WriteRefused("%d is not a transformation id. Nothing was sent." % value)
    return value


def as_refund_kind(value: Any) -> str:
    """``"tailor"`` or ``"resume_health_check"``. The kind PICKS THE ROUTE.

    Refused loudly because the failure it prevents is silent: a kind this module
    did not recognise, defaulted to either route, raises a money claim against
    the wrong product.
    """
    text = str(value).strip()
    if text not in REFUND_KINDS:
        raise WriteRefused(
            "%r is not a refund kind. It must be one of %s - the kind PICKS THE "
            "ROUTE, so a value this server does not recognise would raise a "
            "claim against the wrong product. Nothing was sent."
            % (value, " or ".join(repr(kind) for kind in REFUND_KINDS))
        )
    return text


# ===========================================================================
# The bodies. Exact key sets, nothing rides along.
# ===========================================================================


def tailor_order_body(plan_key: Any) -> dict:
    """``{plan_id}``. One key, and the value is the CATALOGUE'S OWN KEY."""
    return {"plan_id": plan_key}


def health_check_order_body(amount: Any, health_check_id: Any, is_tailored: Any) -> dict:
    """``{amount, health_check_id, is_tailored}``. Three keys, `is_tailored` 1/0.

    Built in the measured order. The key SET is what the suite asserts; the
    order is here so a reader comparing this line to the call site sees the same
    thing twice.
    """
    return {
        "amount": amount,
        "health_check_id": health_check_id,
        "is_tailored": as_wire_flag(is_tailored),
    }


def refund_body(transformation_id: Any = None) -> dict:
    """``{}``, or ``{transformation_id}`` when one is supplied.

    The EMPTY body is the measured default and is not padded out. A key added to
    "make the request more complete" is a key nobody measured on a route that
    raises a money claim.
    """
    if transformation_id is None:
        return {}
    return {"transformation_id": as_transformation_id(transformation_id)}


def describe_order_response(response: Any) -> tuple[dict, list[str]]:
    """``(response with the notes VALUES dropped, what was dropped)``.

    The create response is ``{id, amount, currency, notes:{name}, created_at}``
    and ``notes.name`` is HIS NAME. The commercially load-bearing fields are the
    whole point of returning the response at all, so they stay; the notes are
    reported as present, with their key names, and without their values.
    Dropping the container silently would hide that the platform sent it.
    """
    if not isinstance(response, dict):
        return {}, []

    clean = {}
    dropped: list[str] = []
    for key, value in response.items():
        if key in ORDER_RESPONSE_WITHHELD:
            dropped.append(key)
            clean[key] = {
                "present": True,
                "keys": sorted(value) if isinstance(value, dict) else None,
                "values_withheld": True,
                "why": (
                    "Razorpay order notes carry his name, and a tool result "
                    "ends up in a transcript."
                ),
            }
            continue
        clean[key] = value
    return clean, sorted(set(dropped))


# ===========================================================================
# The refund marker. Uplers' once-per-day gate, mirrored locally.
# ===========================================================================


def marker_path(kind: str) -> Path:
    return markers_dir() / ("refund-%s.json" % str(kind).replace("_", "-"))


def read_refund_marker(kind: str) -> dict | None:
    """The last refund request recorded for this kind, or None.

    An unreadable marker reads as None - as "no record", never as "recently
    requested". A corrupt file must not lock him out of a claim on his own money
    for a day; it is a local convenience mirroring somebody else's localStorage,
    not an authority.
    """
    path = marker_path(kind)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    stamp = data.get("requested_at")
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    return data


def refund_gate(kind: str, *, now: float | None = None) -> dict:
    """``{allowed, last_requested_at, seconds_remaining, ...}`` for this kind."""
    marker = read_refund_marker(kind)
    moment = time.time() if now is None else now
    if marker is None:
        return {
            "allowed": True,
            "last_requested_at": None,
            "last_requested_at_iso": None,
            "seconds_remaining": 0,
            "limit_seconds": REFUND_LIMIT_SECONDS,
        }
    remaining = REFUND_LIMIT_SECONDS - (moment - marker["requested_at"])
    return {
        "allowed": remaining <= 0,
        "last_requested_at": marker["requested_at"],
        "last_requested_at_iso": outreach_write.stamp_to_iso(marker["requested_at"]),
        "seconds_remaining": int(remaining) if remaining > 0 else 0,
        "limit_seconds": REFUND_LIMIT_SECONDS,
    }


def rate_limit_refusal(kind: str, gate: dict) -> str:
    """Guard 4's refusal for the once-per-day gate, naming WHOSE limit it is."""
    hours = gate["seconds_remaining"] / 3600.0
    return (
        "A %s refund request was already raised %s and **UPLERS RATE-LIMITS "
        "THIS TO ONCE PER DAY** - their own UI writes a `%s` timestamp to "
        "localStorage after a successful request and disables the button until "
        "it expires. This is their limit mirrored locally, not a rule this "
        "server invented. About %.1f hour(s) remain. Nothing was sent.\n"
        "IF THE FIRST REQUEST IS THE PROBLEM, a second one is not the fix: "
        "nothing measured anywhere reports refund status, so a duplicate would "
        "be a second claim with no way to see what either did."
        % (kind, gate["last_requested_at_iso"], UPLERS_REFUND_MARKER_KEY, hours)
    )


def write_refund_marker(kind: str, *, body: dict, now: float | None = None) -> dict:
    """Record that a refund request was raised for this kind.

    **WRITTEN AFTER A SUCCESSFUL SEND, not before**, which mirrors Uplers - who
    write their localStorage stamp in the success handler - and picks the safer
    of two imperfect failure modes. Writing first would lock him out for a day
    on a request that never left; writing after loses the gate if the process
    dies between the send and this line. A lost gate costs a duplicate request
    that Uplers' own server-side limit still sees; a phantom gate costs him a
    day of not being able to ask for his money back.

    A marker that cannot be written does NOT undo the request and must not
    raise: the send already happened, and turning a bookkeeping failure into an
    exception would throw away the result the caller most needs.
    """
    moment = time.time() if now is None else now
    record = {
        "kind": kind,
        "requested_at": moment,
        "requested_at_iso": outreach_write.stamp_to_iso(moment),
        "body_keys": sorted(body),
        "mirrors": UPLERS_REFUND_MARKER_KEY,
    }
    path = marker_path(kind)
    try:
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    except OSError as exc:
        return {
            "written": False,
            "path": policy.display_path(str(path)),
            "error": "%s: %s" % (type(exc).__name__, exc),
            "note": (
                "THE REQUEST WAS STILL SENT. Only the local once-per-day marker "
                "failed to write, so this server will not stop a second request "
                "within 24 hours. Uplers' own limit is unaffected."
            ),
        }
    return {
        "written": True,
        "path": policy.display_path(str(path)),
        "requested_at_iso": record["requested_at_iso"],
    }


# ===========================================================================
# The sender seam
# ===========================================================================


def refund_sender_for(client: Any, path: str, *, kind: str):
    """A JSON POST sender STAMPED with the kind it was built for.

    The seam is ``outreach_write``'s and this adds one thing to it. The refund
    tool takes ``kind`` as an argument and ``kind`` PICKS THE ROUTE, so the one
    mistake worth designing against is a sender built for one product being
    handed to a call about the other - which would raise a claim against the
    wrong thing and look entirely normal in every log. The kind travels ON the
    sender, and :func:`request_refund` refuses a mismatch.

    It carries no route string of its own: ``path`` is supplied by server.py,
    which owns the kind-to-route mapping.
    """
    send = outreach_write.json_sender_for(client, path)
    send.kind = as_refund_kind(kind)
    return send


def _require_matching_sender(send: Any, kind: str) -> None:
    """The sender must have been built for THIS kind. Checked before anything."""
    outreach_write._require_sender(send)
    stamped = getattr(send, "kind", None)
    if stamped != kind:
        raise WriteRefused(
            "This is a %r refund, but the sender it was handed was built for "
            "%r. The kind picks the route, so sending anyway would raise a "
            "money claim against the wrong product - and both routes answer the "
            "same success shape, so nothing downstream would notice. Nothing "
            "was sent." % (kind, stamped)
        )


# ===========================================================================
# Guard 5, answered honestly on routes with no read-back
# ===========================================================================


def verify_order(response: Any, *, expected_amount: Any = None) -> dict:
    """Guard 5 for the two order creates. **FROM THE RESPONSE, not a re-read.**

    There is no route in this server that reads orders back, so this states
    ``re_read: False`` rather than implying an independent confirmation. What it
    does have is real: the create answers the order's own ``id``, ``amount`` and
    ``currency``, so "an order exists" rests on the platform's reply.

    Never raises. A verification that threw on an odd response would discard the
    fact that a paid order was just created.
    """
    data = response if isinstance(response, dict) else {}
    order_id = data.get("id")
    amount = data.get("amount")
    currency = data.get("currency")

    matches = None
    if expected_amount is not None and amount is not None:
        matches = str(amount) == str(expected_amount)

    return {
        "re_read": False,
        "landed": order_id is not None,
        "route": None,
        "order_id": order_id,
        "order_amount": amount,
        "order_currency": currency,
        "expected_amount": expected_amount,
        "amount_matches_expected": matches,
        "note": (
            "Verified FROM THE CREATE'S OWN RESPONSE, which carries the order "
            "id, amount and currency. NOT an independent read-back: no route in "
            "this server reads Uplers' orders, so nothing here re-reads the "
            "order after making it."
        )
        if order_id is not None
        else (
            "THE RESPONSE CARRIED NO ORDER ID. The route accepted the request "
            "and this server cannot tell whether an order exists - there is no "
            "route it can read to find out. Check the Uplers billing screen "
            "before ordering again, or a duplicate unpaid order is the likely "
            "result."
        ),
    }


def verify_refund() -> dict:
    """Guard 5 for the refunds. **UNAVAILABLE, and that is the measurement.**

    Takes no arguments because there is nothing to take. NO ROUTE ANYWHERE IN
    UPLERS REPORTS REFUND STATUS - their own client shows a request being raised
    and a toast echoing ``res.data.message``, and nothing after that. So this
    reports the absence rather than skipping guard 5 quietly, which is the
    difference between a guard that answers "cannot be verified" and a guard
    that is missing.
    """
    return {
        "re_read": False,
        "landed": None,
        "route": None,
        "note": (
            "NOT VERIFIABLE, and this is measured rather than a shortfall. NO "
            "ROUTE ANYWHERE IN UPLERS REPORTS REFUND STATUS - not this "
            "server's, not their own client's. What is known is that a request "
            "was accepted; what happens on their side afterwards is UNMEASURED. "
            "Nobody has observed a refund completing."
        ),
    }


def capture_note() -> str:
    """The one sentence every order result carries about what is NOT built."""
    return (
        "PAYING IS NOT BUILT AND CANNOT BE. The capture routes (%s) are called "
        "from inside Razorpay's own handler callback with %s - values minted and "
        "signed by Razorpay after a real card payment, which no client can "
        "produce. They also live on a DIFFERENT HOST (%s) that this server has "
        "never contacted."
        % (" and ".join(CAPTURE_ROUTES), ", ".join(CAPTURE_BODY_KEYS), CAPTURE_HOST)
    )


# ===========================================================================
# A. Create a tailor plan order
# ===========================================================================


async def order_create(
    client: Any,
    plan_id: Any,
    *,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Create a Razorpay order for one of Uplers' tailor plans. **DOES NOT PAY.**

    ``POST talent/tailor/order/create``, body ``{plan_id}`` - **ONE KEY**,
    VERIFIED at 9 call sites in Uplers' bundle, all identical.

    **IT DOES NOT CHARGE THE CARD.** It mints a Razorpay ORDER and answers
    ``{id, amount, currency, notes, created_at}``. The card is charged inside
    Razorpay's hosted widget, which this server cannot drive - see
    :func:`capture_note`. **A confirmed call leaves a REAL, UNPAID order record
    on the account, and paying it still requires a browser.**

    THE PRICE IS READ LIVE, AND WHAT THAT CAN AND CANNOT TELL YOU
    -------------------------------------------------------------
    Guard 1 reads ``talent/outreach/agent-plans`` on every call and the preview
    prints THAT PLAN'S CATALOGUE PRICE - explicitly labelled as the catalogue
    price, because the order does not exist yet and its amount comes back FROM
    this call. **A plan id the live catalogue does not list is REFUSED**, so an
    order is never sent for a plan the platform does not sell.

    That refusal is not hypothetical on this account. MEASURED: the catalogue
    holds exactly two entries, ``"1"`` (Starter, 1499) and ``"3"`` (Elite,
    2999), while his own ``outreach-step`` reads ``plan: 2`` - **a plan that is
    not in the catalogue at all.** Anything that "looked up his current plan"
    would find nothing; the catalogue is read live and the two numbers are not
    the same kind of thing.

    **THE CATALOGUE CARRIES NO CURRENCY**, so the previewed price is an
    unlabelled number and says so. The confirmed result prints the order's own
    ``amount`` and ``currency`` beside the catalogue price it previewed, so a
    difference between them is visible rather than inferred.

    THE PLAN ID GOES ON THE WIRE AS THE CATALOGUE'S OWN KEY, uncast. Uplers'
    callers resolve the plan by ``agent_tailor_plans[t]`` and send ``{plan_id:
    t}`` with no ``Number()`` anywhere, so the wire type is theirs.
    """
    payload = await client.get_json(EP_READ_AGENT_PLANS, None)
    catalogue = read_agent_plans(payload)
    entry = find_plan(catalogue, plan_id)

    if entry is None:
        raise WriteRefused(
            "Plan %r is not in Uplers' LIVE plan catalogue, so this would send "
            "a plan id the platform does not list to a route that creates a "
            "paid order. Nothing was sent. %s lists %d plan(s) right now: %s.\n"
            "NOTE, because it is the trap here: the `plan` number on his "
            "outreach-step record is NOT an index into this catalogue - "
            "MEASURED, it reads 2, which this catalogue has never contained."
            % (
                plan_id,
                EP_READ_AGENT_PLANS,
                len(catalogue),
                ", ".join(
                    "%s (%s, price %s)"
                    % (row["plan_id"], row["name"] or "unnamed", row["price"])
                    for row in catalogue.values()
                )
                or "none",
            )
        )

    body = tailor_order_body(entry["plan_id"])

    common = {
        "action": "order_create",
        "plan_id": entry["plan_id"],
        "plan_name": entry["name"],
        "method": outreach_write._method_of(send, "POST application/json"),
        "endpoint": outreach_write._endpoint_of(send),
        "body": dict(body),
        "body_keys": sorted(body),
        "reversible": False,
        "catalogue_price": {
            "price": entry["price"],
            "price_text": entry["price_text"],
            # NOT CARRIED BY THE CATALOGUE ROUTE. See read_agent_plans.
            "currency": None,
            "validity_days": entry["validity_days"],
            "validity_text": entry["validity_text"],
            "route": EP_READ_AGENT_PLANS,
            "is_the_catalogue_price_not_the_order": (
                "This is the PLAN CATALOGUE price read live from %s, NOT the "
                "order's amount. The order does not exist until this call is "
                "confirmed and its amount comes back from it."
                % EP_READ_AGENT_PLANS
            ),
            "currency_is_unknown_because": (
                "MEASURED: the catalogue payload carries NO currency field on "
                "the plan or anywhere else in it, so this price is an "
                "UNLABELLED number. Only the created order reports a currency. "
                "No currency is inferred from any other route."
            ),
        },
        "notes": [
            "IT DOES NOT CHARGE THE CARD. This creates a Razorpay ORDER. A "
            "confirmed call leaves a REAL, UNPAID order on the account and "
            "paying it still requires a browser.",
            capture_note(),
            "The body is exactly one key, plan_id, VERIFIED at 9 call sites. "
            "The value is the CATALOGUE'S OWN KEY, sent uncast.",
            "The price above is the CATALOGUE price, read live. It is not the "
            "order amount, and the catalogue carries no currency.",
        ],
    }

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = "uplers_order_create(%r, confirm=True)" % (
            entry["plan_id"],
        )
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent and no snapshot was written. Confirming "
            "records the price you were shown, then sends, then reports the "
            "order's own amount and currency beside it.",
        )
        return result

    outreach_write._require_sender(send)
    # THE PRICE HE WAS SHOWN, at the moment he confirmed. Not a rollback -
    # there is no route that cancels an order - but it is the only record of
    # what this server told him before he agreed to it.
    snapshot = outreach_write.write_snapshot(
        {"plan": entry, "body": dict(body), "catalogue_size": len(catalogue)},
        kind="tailor-order",
        label="pre-create",
    )

    response = await send(body)

    described, dropped = describe_order_response(response)
    verification = verify_order(response, expected_amount=entry["price"])

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["snapshot_is_not_an_undo"] = (
        "It records the CATALOGUE PRICE you were shown before confirming. There "
        "is no route anywhere in Uplers that cancels an order, so nothing local "
        "can remove the order this created."
    )
    result["response"] = described
    result["response_redacted_keys"] = dropped
    result["verified"] = verification
    result["order_versus_catalogue"] = _order_versus_catalogue(
        verification, entry
    )
    result["reverse_with"] = (
        "NOTHING in this server. No route cancels a created order. The order is "
        "unpaid until it is paid in Razorpay's widget in a browser, so leaving "
        "it unpaid is what 'not going through with it' looks like."
    )
    return result


def _order_versus_catalogue(verification: dict, entry: dict) -> dict:
    """The two prices side by side, and whether they differ. Said plainly.

    The lead's addition and it earns its place: the catalogue has a price and no
    currency, the order has both, and a reader comparing two numbers in
    different parts of a result will not notice a mismatch reliably.
    """
    order_amount = verification.get("order_amount")
    catalogue_price = entry["price"]
    if order_amount is None:
        differs = None
        line = (
            "The order's amount could not be read from the response, so it "
            "cannot be compared with the catalogue price."
        )
    elif str(order_amount) == str(catalogue_price):
        differs = False
        line = (
            "THEY AGREE. The order came back at %s, the same number the "
            "catalogue previewed. The order also reports currency %r, which the "
            "catalogue does not carry at all."
            % (order_amount, verification.get("order_currency"))
        )
    else:
        differs = True
        line = (
            "**THEY DIFFER.** The catalogue previewed %s and the order came "
            "back at %s (currency %r). The order is what will be charged. This "
            "is reported rather than resolved: a discount, an offer or a price "
            "change are all candidates and none of them was measured here."
            % (catalogue_price, order_amount, verification.get("order_currency"))
        )
    return {
        "catalogue_price": catalogue_price,
        "catalogue_currency": None,
        "order_amount": order_amount,
        "order_currency": verification.get("order_currency"),
        "differ": differs,
        "note": line,
    }


# ===========================================================================
# B. Create a resume health-check order
# ===========================================================================


async def health_check_order_create(
    client: Any,
    health_check_id: Any,
    amount: Any,
    *,
    is_tailored: Any = False,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Create a Razorpay order for a resume health check. **DOES NOT PAY.**

    ``POST talent/resume-health-check/create-order``, body
    ``{amount, health_check_id, is_tailored}`` - **THREE KEYS**, VERIFIED, 1
    call site. ``is_tailored`` goes on the wire as the INTEGER ``1`` or ``0``,
    never ``true``/``false``.

    **IT DOES NOT CHARGE THE CARD**, for :func:`order_create`'s reason and with
    the same consequence: a confirmed call leaves a REAL, UNPAID order record,
    and paying it needs a browser.

    THE AMOUNT IS IN THE BODY, WHICH MAKES THIS THE DANGEROUS ONE
    -------------------------------------------------------------
    Unlike the tailor order, the price is not resolved by the platform - **this
    request carries the number itself**, so the preview has it pre-flight and
    prints it. Uplers' own UI sources it from ``resume_transform_price``. The
    caller must pass it rather than have this server invent one, and a
    non-positive or non-integer amount is REFUSED: a wrong id fails, but a wrong
    amount succeeds at the wrong number and no route reads it back.

    **THE AMOUNT'S CURRENCY IS UNLABELLED HERE TOO.** Nothing in the request or
    in any route this server reads says what unit it is in, so the preview
    prints the number with an explicit "currency not carried" rather than
    attaching one.

    IT READS TWO ROUTES, AND THE SECOND IS NOT IN THIS TOOL'S NAME
    --------------------------------------------------------------
    Guard 1 resolves WHICH health check this account holds, and it takes both
    halves of a join to do it. ``talent/outreach/get-last-health-check`` reports
    the last check but **carries no id for it** - MEASURED, and not a redaction
    artefact. The ids live on ``talent/resume-health-check/dashboard``. So the
    last check's ``transform.resume_transformation_id`` is joined to the
    dashboard row carrying the same value, and **this REFUSES unless
    ``health_check_id`` equals the id that join returns.** MEASURED on the
    captured pair: rtid 150705 -> exactly one row -> id 152462.

    A join that does not land exactly once refuses too, and says which of the
    three ways it failed. There is deliberately no weaker fallback: every weaker
    rule permits creating a paid order against a health check that is not the
    one the account holds.
    """
    amount_value = as_amount(amount)
    tailored_flag = as_wire_flag(is_tailored)

    last_payload = await client.get_json(EP_READ_HEALTH_CHECK_LAST, None)
    transformation_id = read_last_transformation_id(last_payload)

    dashboard_payload = await client.get_json(EP_READ_HEALTH_CHECK_DASHBOARD, None)
    rows = read_health_check_rows(dashboard_payload)

    resolution = resolve_health_check(transformation_id, rows)
    if resolution["failure"] is not None:
        raise WriteRefused(join_refusal(resolution))

    resolved_id = resolution["resolved_id"]
    if str(health_check_id) != str(resolved_id):
        raise WriteRefused(
            "health_check_id %r is not the health check this account holds. "
            "Resolved from the platform: %s reports transformation id %r, which "
            "matches exactly one row on %s, whose id is %r. Sending yours would "
            "create a PAID order against a health check that is not this "
            "account's. Nothing was sent."
            % (
                health_check_id,
                EP_READ_HEALTH_CHECK_LAST,
                transformation_id,
                EP_READ_HEALTH_CHECK_DASHBOARD,
                resolved_id,
            )
        )

    # The RESOLVED id goes on the wire, not the caller's spelling of it, and it
    # is sent with the type the platform reported it in.
    body = health_check_order_body(amount_value, resolved_id, tailored_flag)

    common = {
        "action": "health_check_order_create",
        "health_check_id": resolved_id,
        "method": outreach_write._method_of(send, "POST application/json"),
        "endpoint": outreach_write._endpoint_of(send),
        "body": dict(body),
        "body_keys": sorted(body),
        "reversible": False,
        "amount": {
            "value": amount_value,
            "currency": None,
            "currency_is_unknown_because": (
                "MEASURED: nothing in this request, and nothing on any route "
                "this server reads, labels the unit. Uplers' UI sources this "
                "number from `resume_transform_price`. It is printed as the "
                "unlabelled integer it is rather than given a currency this "
                "server cannot evidence."
            ),
            "in_the_body_not_resolved_by_the_platform": (
                "This route carries the amount ITSELF, so this number is what "
                "the order will be created for. That is why it is refused "
                "rather than coerced and why it is printed pre-flight."
            ),
        },
        "resolved_from": {
            "last_health_check_route": EP_READ_HEALTH_CHECK_LAST,
            "dashboard_route": EP_READ_HEALTH_CHECK_DASHBOARD,
            "transformation_id": transformation_id,
            "dashboard_rows": resolution["rows"],
            "matching_rows": resolution["matched"],
            "resume_score": resolution["resume_score"],
            "why_two_routes": (
                "get-last-health-check reports the last check but carries NO id "
                "for it - its health_check object holds only created_at, "
                "final_verdict, resume_score and status. The ids are on the "
                "dashboard, so the two are joined on "
                "transform.resume_transformation_id."
            ),
        },
        "is_tailored": {
            "asked_for": bool(is_tailored),
            "on_the_wire": tailored_flag,
            "note": (
                "Sent as the INTEGER %d, never true/false. json.dumps renders a "
                "Python bool as the JSON literal `true`, which is a different "
                "value on the wire from 1." % tailored_flag
            ),
        },
        "notes": [
            "IT DOES NOT CHARGE THE CARD. This creates a Razorpay ORDER. A "
            "confirmed call leaves a REAL, UNPAID order on the account and "
            "paying it still requires a browser.",
            capture_note(),
            "The body is exactly three keys - amount, health_check_id, "
            "is_tailored - VERIFIED at the single call site. Nothing else.",
            "THE AMOUNT IS IN THE BODY, so this number is what the order is "
            "created for. It is not resolved by the platform and this server "
            "does not invent one.",
            "The health check was RESOLVED FROM TWO LIVE ROUTES, not taken on "
            "trust - see resolved_from.",
        ],
    }

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = (
            "uplers_health_check_order_create(%r, %d, is_tailored=%r, "
            "confirm=True)" % (resolved_id, amount_value, bool(is_tailored))
        )
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent and no snapshot was written. This is "
            "the only chance to read the exact amount before an order is "
            "created for it.",
        )
        return result

    outreach_write._require_sender(send)
    snapshot = outreach_write.write_snapshot(
        {
            "resolution": dict(resolution),
            "body": dict(body),
            "dashboard_rows": rows,
        },
        kind="health-check-order",
        label="pre-create",
    )

    response = await send(body)

    described, dropped = describe_order_response(response)
    verification = verify_order(response, expected_amount=amount_value)

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["snapshot_is_not_an_undo"] = (
        "It records the amount and the health check this order was created for. "
        "No route anywhere in Uplers cancels an order, so nothing local can "
        "remove it."
    )
    result["response"] = described
    result["response_redacted_keys"] = dropped
    result["verified"] = verification
    result["reverse_with"] = (
        "NOTHING in this server. No route cancels a created order. It stays "
        "unpaid until it is paid in Razorpay's widget in a browser."
    )
    return result


# ===========================================================================
# C + D. Raise a refund REQUEST - not a refund
# ===========================================================================


async def request_refund(
    client: Any,
    kind: Any,
    *,
    transformation_id: Any = None,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Ask Uplers to refund a tailor plan or a resume health check. **A REQUEST.**

    ``POST talent/tailor/refund-request`` or
    ``talent/resume-health-check/refund-request`` - ``kind`` picks which. Body
    ``{}``, plus ``transformation_id`` only when one is supplied. VERIFIED, 5
    call sites across the pair.

    **IT IS A REQUEST, NOT A REFUND, AND THE NAME SAYS SO.** Uplers' own confirm
    dialog reads *"Are you sure you want to raise a refund request?"* - quoted
    rather than paraphrased, because it is the whole claim their product makes
    for this button.

    **NOBODY HAS OBSERVED A REFUND COMPLETING.** What the bundle shows is a
    request being raised and a success toast echoing ``res.data.message``.
    **There is no route anywhere that reports refund status** - not in this
    server, not in their own client. So what this does on their side is
    UNMEASURED beyond "a request was accepted", and guard 5 reports that
    absence rather than pretending to a read-back.

    ONCE PER DAY, AND THE LIMIT IS UPLERS' OWN
    -------------------------------------------
    Their UI writes a ``refund-request-raised`` timestamp to localStorage after
    a successful request and disables the button for 24 hours. **This mirrors
    that limit with a local marker and REFUSES a second request for the same
    kind inside 24 hours**, naming whose limit it is. The marker is written
    AFTER a successful send, for the reason :func:`write_refund_marker` gives.

    GUARD 1 HAS NOTHING TO READ, and that is reported rather than faked. There
    is no live record of refund state to read before writing, so this tool does
    NOT read an unrelated route in order to look like it checked something. The
    live read it does perform is of its own marker.
    """
    refund_kind = as_refund_kind(kind)
    body = refund_body(transformation_id)
    gate = refund_gate(refund_kind)

    if not gate["allowed"]:
        raise WriteRefused(rate_limit_refusal(refund_kind, gate))

    common = {
        "action": "request_refund",
        "kind": refund_kind,
        "method": outreach_write._method_of(send, "POST application/json"),
        "endpoint": outreach_write._endpoint_of(send),
        "body": dict(body),
        "body_keys": sorted(body),
        "reversible": False,
        "it_is_a_request_not_a_refund": (
            "Uplers' own confirm copy, verbatim: \"%s\". Raising it is the whole "
            "of what this does." % UPLERS_REFUND_CONFIRM_COPY
        ),
        "rate_limit": dict(gate),
        "guard_1_has_no_live_record": (
            "There is NO route that reports refund state, so there is nothing "
            "live to read before this write and none is read. This tool does "
            "not fetch an unrelated route in order to appear to have checked "
            "something. The only state it reads is its own local marker."
        ),
        "notes": [
            "IT IS A REQUEST, NOT A REFUND. Uplers' own dialog says so.",
            "NOBODY HAS OBSERVED A REFUND COMPLETING. The bundle shows a "
            "request being raised and a success toast echoing res.data.message. "
            "There is NO ROUTE ANYWHERE that reports refund status, so what "
            "happens on their side is UNMEASURED beyond 'a request was "
            "accepted'.",
            "UPLERS RATE-LIMITS THIS TO ONCE PER DAY - their UI writes a `%s` "
            "timestamp to localStorage and disables the button. This server "
            "mirrors that limit locally; it did not invent it."
            % UPLERS_REFUND_MARKER_KEY,
            "The body is EMPTY unless a transformation_id is supplied, which is "
            "the measured shape at all 5 call sites. Nothing is added to make "
            "it look more complete.",
        ],
    }

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = "uplers_request_refund(%r%s, confirm=True)" % (
            refund_kind,
            ""
            if transformation_id is None
            else ", transformation_id=%r" % (transformation_id,),
        )
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent, no snapshot was written and no "
            "once-per-day marker was set. Confirming consumes today's single "
            "request for this kind.",
        )
        return result

    _require_matching_sender(send, refund_kind)
    snapshot = outreach_write.write_snapshot(
        {
            "kind": refund_kind,
            "body": dict(body),
            "prior_marker": read_refund_marker(refund_kind),
        },
        kind="refund-request",
        label="pre-request",
    )

    response = await send(body)

    marker = write_refund_marker(refund_kind, body=body)

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["snapshot_is_not_an_undo"] = (
        "It records that a request was raised and with what body. There is no "
        "route that withdraws a refund request, so nothing local can retract "
        "what Uplers received."
    )
    result["response"] = response if isinstance(response, dict) else {}
    result["verified"] = verify_refund()
    result["rate_limit_marker"] = marker
    result["reverse_with"] = (
        "NOTHING. There is no route that withdraws a refund request, and no "
        "route that reports what became of one."
    )
    return result
