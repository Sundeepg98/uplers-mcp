"""The two writes that are NOT reversible settings switches.

``outreach_write`` holds the four REVERSIBLE writes and says, in its own first
paragraph, that four routes are in and the rest of the namespace is out **on
one criterion: these four can be put back**. Two routes are admitted here that
do not meet that criterion, and they are admitted for a different reason each,
stated rather than blurred into the sentence next door:

*   ``consent-email-job-scan`` (DELETE) IS reversible - the POST on the
    identical URL re-grants it - but it is not a settings switch. It withdraws
    a standing permission for Uplers to read a mailbox. It was refused for a
    year on WHOSE CALL IT IS rather than on safety, and that refusal has now
    been made: the tool exists so he can make it, and it still performs nothing
    without ``confirm=True``.
*   ``interview-feedback`` (POST) is genuinely ONE-WAY. There is no edit route
    and no delete route for submitted feedback anywhere in Uplers' bundle. It
    is here because the alternative was a review he can only publish from their
    UI, and because a one-way write behind five guards and a preview is a
    smaller hazard than the same write behind a browser form with no preview at
    all. The docstring says ONE-WAY in capitals and the preview says it again.

**They are NOT folded into the agent-config group** in either census, and the
reason is the criterion above: a group whose stated property is "all of these
can be put back" stops meaning anything the moment a one-way write is filed in
it. See ``server.CONSENT_AND_ONE_WAY_WRITE_TOOLS``.

THE FIVE GUARDS, UNCHANGED
--------------------------
The doctrine is ``outreach_write``'s and is not restated here at length; what
follows is only what is DIFFERENT about these two.

1.  **read-live.** Neither route echoes the state it changes, so the live
    record is read from its own GET first - ``recommended-jobs-meta-email`` for
    the consent, ``interview-list?detailed=true`` for the feedback.
2.  **exact-body preview.** Interesting here because NEITHER body is the usual
    case. The consent DELETE has **no body and no params at all** - the URL is
    the entire decision - so the preview prints an empty body and says so.
    The feedback POST has EXACTLY TWO KEYS and the preview asserts the key SET,
    so a third key added by a later edit fails loudly rather than riding along.
3.  **snapshot-before.** Written to disk before the send. For the consent it
    records what was given up (a scan that was on, since when, and how many
    jobs it had found); for the feedback it records the interview list as it
    stood. **NEITHER SNAPSHOT IS AN UNDO.** The consent's undo is a route (the
    POST); the feedback has no undo at all and the snapshot cannot retract what
    Uplers already received. Both results say which.
4.  **empty-refusal.** Consent already off -> nothing to revoke, refuse.
    Company not on the interview list -> refuse rather than post a company id
    the account has no interview with.
5.  **re-read-verify.** Both re-read. For the consent this server does MORE
    than Uplers' own client, deliberately: VERIFIED in the bundle, the revoke
    path updates local state optimistically and **never refetches**, and the
    DELETE response carries ``{gmail_connected, gmail_email}`` with no
    ``has_consent`` in it at all - so their client has no evidence the revoke
    landed and neither would this one without the extra GET.

THE MAILBOX ADDRESS, WHICH IS THE ONE LEAK THIS FILE HAD TO CLOSE
------------------------------------------------------------------
``outreach_write`` returns the send's response verbatim (``result["response"]
= response``), which is safe on its four routes because they answer a bare
status. **It is NOT safe here.** The consent DELETE's measured response is
``res.data.{gmail_connected, gmail_email}`` - his actual mailbox address - and
returning it verbatim would print that address into a transcript as a side
effect of a call about consent. Every response and every record leaving this
module goes through :func:`scrub`, which drops
``agent_surface.WITHHELD_IDENTITY_KEYS`` and names what it dropped. This is the
same rule ``agent_surface.shape_email_scan`` already applies on the read side;
the write side had no equivalent until this file.

EVIDENCE
--------
Every wire fact is VERIFIED against Uplers' production bundle by
``_audit/_slices/_slice-outreach-write-inventory.md`` sections 3.1/3.2 (the
consent pair) and 3.19 (interview-feedback), plus
``_audit/_slices/_slice-consent-semantics.md`` Q3, which quotes both consent
call sites in full. **No write has been fired against his account by anything
in this wave** - the state recorded below came from GETs and from static
analysis, never from exercising either route.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from . import agent_surface, endpoints
from .outreach import unwrap
from .talent import TalentError

# INHERITED, not re-implemented. The snapshot writer, the sender seam for a
# JSON POST, and the no-sender refusal are `outreach_write`'s and stay there: a
# second copy of "every confirmed write writes a restore point first" is a
# second thing to keep true. The private names are used deliberately rather
# than duplicated - they are the doctrine, and a paraphrase of a guard is a
# guard that can drift out of step with the one the other module runs.
from . import outreach_write

# The shared guard class, imported and NOT subclassed. `outreach_write` has its
# own subclass for the settings writes; a third class here would mean a caller
# who catches "this server refused a write" has three names to know instead of
# one, and these two writes have nothing in common with each other that a
# shared class would express.
from .profile_write import WriteRefused

# --- Read-back routes ------------------------------------------------------
#
# ALIASES, exactly as `outreach_write` uses them: endpoints.py is the route
# authority and this module holds no path strings of its own.

#: Guard 1 and guard 5 for the consent. The AUTHORITATIVE consent state - not
#: the dashboard's downstream copy, and NOT `interview-list -> meta.has_consent`,
#: which is a DIFFERENT consent wearing the identical field name. See
#: `agent_surface.CONSENT_AUTHORITY` for the receipt.
EP_READ_SCAN_CONSENT = endpoints.EP_OUTREACH_META_EMAIL

#: Guard 1 and guard 5 for the feedback.
EP_READ_INTERVIEWS = endpoints.EP_INTERVIEW_LIST

#: The interview list's one query parameter, spelled as the STRING "true" -
#: `uplers_my_interviews` sends the same thing. VERIFIED at the browser call
#: site (`_slice-browser-parity-census.md` row 88).
INTERVIEW_LIST_PARAMS = {"detailed": "true"}

#: **EXACTLY TWO KEYS.** VERIFIED at all four `interview-feedback` call sites
#: across three screens (1625, 2063, 6069):
#: ``(0,i.o$)(...+"talent/outreach/interview-feedback",{company_id:t,feedback:n})``.
#: Spelled as a tuple so a third key added by a later edit fails a test loudly
#: instead of quietly riding along on a route that cannot be un-sent.
FEEDBACK_BODY_KEYS = ("company_id", "feedback")

#: Uplers' own success copy on the revoke, quoted verbatim. It is FUTURE TENSE
#: and that is the whole finding: the revoke stops the next scan, it does not
#: reach back. VERIFIED, `_slice-consent-semantics.md` Q3.
REVOKE_SUCCESS_COPY = (
    "Happpy Agent will no longer scan your job board alert emails."
)

#: The complete set of DELETE routes under `talent/outreach/*`, from a complete
#: negative search of the bundle (`_slice-outreach-write-inventory.md` section
#: 1a, 32 verb+route pairs). Recorded as data rather than prose because the
#: claim the revoke docstring makes - "no route anywhere deletes already-ingested
#: scan data" - is only as good as this enumeration being complete.
OUTREACH_DELETE_ROUTES = (
    "talent/outreach/consent-email-job-scan",
    "talent/outreach/settings/disabled-companies/{id}",
    "talent/outreach/external-apply-pending-jobs/{id}",
)

#: A SEPARATE GRANT ON A SEPARATE ROUTE, named so the revoke docstring can say
#: what it is NOT doing without leaving a reader to guess where the other
#: switch lives. Not built anywhere in this server and deliberately has no
#: constant in endpoints.py.
GMAIL_DISCONNECT_ROUTE = "talent/account/gmail/disconnect"


# ===========================================================================
# The mailbox address never leaves
# ===========================================================================


def scrub(value: Any) -> tuple[Any, list[str]]:
    """``(value with identity keys removed, the keys that were removed)``.

    Applied to every record and every response this module returns. The consent
    DELETE answers with ``gmail_email`` in it, and a result dict ends up in a
    transcript - so the address is dropped at the one place it could otherwise
    escape, and the drop is REPORTED rather than done quietly.

    Recurses, because the address arrives one level down inside ``data`` and a
    shallow pop would leave it exactly where it actually is.
    """
    removed: list[str] = []

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            clean = {}
            for key, item in node.items():
                if key in agent_surface.WITHHELD_IDENTITY_KEYS:
                    removed.append(key)
                    continue
                clean[key] = walk(item)
            return clean
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(value), sorted(set(removed))


# ===========================================================================
# Reading the live records
# ===========================================================================


def read_scan_consent(payload: Any) -> dict:
    """The Gmail job scan's live state, WITHOUT the mailbox address.

    Reads the same route and the same field ``agent_surface.shape_email_scan``
    reads, and reads it again here rather than calling that shaper: this needs
    the raw ``has_consent`` for a comparison, and a write that decides whether
    to fire off a presentation shaper is a write that changes behaviour when
    somebody improves a summary.

    ``has_consent`` is TRI-STATE on purpose. ``None`` means the payload did not
    carry the field, which is not ``False`` - "the scan is off" and "the record
    did not say" are different facts, and only one of them means there is
    nothing to revoke.
    """
    data = unwrap(payload, route=EP_READ_SCAN_CONSENT, expect=dict)

    raw_consent = data.get("has_consent")
    granted = data.get("consent_email_job_scan")
    breakdown = data.get("breakdown")

    record = {
        "has_consent": None if raw_consent is None else bool(raw_consent),
        "consent_granted_at": granted if isinstance(granted, str) else None,
        "gmail_connected": bool(data.get("gmail_connected")),
        "last_job_scan": data.get("last_job_scan")
        if isinstance(data.get("last_job_scan"), str)
        else None,
        "total_jobs": data.get("total_jobs"),
        "breakdown": {
            str(board): count
            for board, count in sorted(breakdown.items())
            if isinstance(count, int) and not isinstance(count, bool)
        }
        if isinstance(breakdown, dict)
        else {},
    }
    clean, _ = scrub(record)
    return clean


def read_interview_companies(payload: Any) -> list[dict]:
    """The companies Uplers lists an interview for, as ``{company_id, ...}`` rows.

    **MEASURED: this is the empty list on his account.** The captured fixture
    ``tests/fixtures/talent_interviews.json`` carries ``data: []``, and the
    2026-08-25 measurement that commissioned this module found the same. So
    every feedback call refuses today, and that is the tool working.

    An empty ``data`` here has TWO readings and the payload says which - the
    same distinction ``talent_shape.interviews_from`` draws. ``meta.has_consent``
    on THIS route is the INTERVIEW email scan, a different consent from the
    Gmail JOB scan the other half of this module revokes, wearing the identical
    field name. It is carried into the refusal so an empty list is reported as
    a diagnosis rather than as "no interviews".

    Matching is on ``company_id`` and nothing else. The name is carried for the
    preview to print and is never what a lookup is decided on.
    """
    rows_raw = unwrap(payload, route=EP_READ_INTERVIEWS, expect=list)
    rows: list[dict] = []
    for raw in rows_raw:
        if not isinstance(raw, dict):
            continue
        identifier = raw.get("company_id")
        rows.append(
            {
                "company_id": identifier,
                # The same three spellings `talent_shape.to_interview` accepts,
                # in its order. One reader disagreeing with the other about
                # which key holds the company name is how a preview ends up
                # naming the wrong company.
                "company_name": _first_text(raw, "company_name", "company", "client_name"),
                "role": _first_text(raw, "RequestForTalent", "role", "job_title", "title"),
                "feedback_given": bool(raw.get("feedback")),
            }
        )
    clean, _ = scrub(rows)
    return clean


def _first_text(raw: dict, *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def interview_meta(payload: Any) -> dict:
    """``meta`` off the interview list, for the empty-list diagnosis only.

    Read straight off the envelope rather than through :func:`unwrap`, because
    ``meta`` is a SIBLING of ``data`` and unwrap returns ``data``. Never
    printed with the address in it.
    """
    meta = payload.get("meta") if isinstance(payload, dict) else None
    clean, _ = scrub(meta if isinstance(meta, dict) else {})
    return clean


def find_company(rows: Iterable[dict], company_id: Any) -> dict | None:
    """The interview row for a company, or None. Matches on ``company_id``.

    Compared as STRINGS. Uplers sends the id as an integer on some rows and as
    a numeric string on others across this API, and ``3 != "3"`` would refuse a
    company that is plainly on the list - a refusal the caller cannot act on,
    because nothing they can see distinguishes the two.
    """
    for row in rows:
        if row.get("company_id") is not None and str(row["company_id"]) == str(
            company_id
        ):
            return row
    return None


def as_company_id(value: Any) -> int:
    """A company id for the wire. Refused rather than coerced.

    Same shape and same reason as ``outreach_write._company_id``: this number
    goes into the body of a POST that cannot be un-sent, and a silent
    ``int("company 3")`` failing inside the write is a stack trace where a
    refusal belongs.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError):
            raise WriteRefused(
                "%r is not a company id. Uplers' interview rows carry a numeric "
                "`company_id`; read them with uplers_my_interviews. Nothing was "
                "sent." % (value,)
            ) from None
    if value <= 0:
        raise WriteRefused("%d is not a company id. Nothing was sent." % value)
    return value


# ===========================================================================
# The sender seam
# ===========================================================================


def bare_delete_sender_for(client: Any, path: str):
    """A DELETE with NO body, NO params and NO path segment. Built by `server.py`.

    The seam is ``outreach_write``'s and the reason is ``outreach_write``'s:
    this module cannot put anything on the wire without being handed one of
    these, so "no write happened" is a claim about control flow.

    **It is a THIRD sender rather than a reuse of ``delete_sender_for``, and
    the guard is the mirror image of that one's.** That sender REFUSES a path
    with no ``{id}`` in it, because the blocklist's collection URL and item URL
    differ by one segment and a DELETE aimed at the collection is not an
    unblock. This route has no item URL at all - VERIFIED, the helper is
    ``r.A.delete(e)`` and takes a URL and nothing else - so here the refusal
    runs the other way: a template carrying a placeholder is the blocklist
    constant arriving by copy-paste, and it is refused at CONSTRUCTION, which
    is stronger than checking at send time.

    ``TalentClient`` has no ``delete`` verb, so this reaches the client's own
    request path directly. The clean home is a ``delete_json`` verb on
    ``TalentClient``; that edit was out of scope for this wave, exactly as
    ``outreach_write.delete_sender_for`` records for the same reason.
    """
    text = str(path)
    if "{" in text or "}" in text:
        raise WriteRefused(
            "A consent DELETE sender was built from %r, which carries a path "
            "placeholder. This route takes NO path segment - Uplers' own helper "
            "is a bare `delete(url)` - so a template with an {id} in it is a "
            "different route's constant arriving by copy-paste. Refusing to "
            "build the sender at all." % text[:80]
        )

    async def send():
        return await client._request("DELETE", text)

    send.path = text
    send.method = "DELETE"
    return send


# ===========================================================================
# A. Revoke the Gmail job-board scan
# ===========================================================================


async def revoke_email_scan(
    client: Any,
    *,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Withdraw Uplers' permission to scan his job-board alert emails.

    ``DELETE talent/outreach/consent-email-job-scan`` - **no body, no params,
    no path segment. The URL is the entire request.** VERIFIED at the only
    revoke call site in 13.4 MB of bundle: ``(0,c.rn)(s.Xkg)``, where ``rn`` is
    ``r.A.delete(e)`` and takes a URL and nothing else.

    WHAT IT ACTUALLY DOES, WHICH IS NARROWER THAN IT SOUNDS
    -------------------------------------------------------
    **IT STOPS FUTURE SCANS ONLY.** Uplers' own success copy is future tense
    and is quoted here rather than paraphrased: *"Happpy Agent will no longer
    scan your job board alert emails."* That is the whole claim their product
    makes for this button, and this tool does not make a larger one on its
    behalf.

    **NO ROUTE ANYWHERE DELETES ALREADY-INGESTED SCAN DATA.** Complete negative
    search over their bundle: the only three DELETE routes under
    ``talent/outreach/*`` are this consent, ``settings/disabled-companies/{id}``
    and ``external-apply-pending-jobs/{id}``. The jobs the scan has already
    pulled out of the mailbox stay where they are; the revoke path in their own
    client clears the LIST ON SCREEN and nothing on the server. If having the
    ingested data removed is the point, this is not the tool that does it and
    nothing in their API is - that is a support request.

    **IT DOES NOT DISCONNECT GMAIL.** The mailbox connection is a separate
    grant on a separate route, ``talent/account/gmail/disconnect``, which this
    server does not build. After this revoke the mailbox stays connected and
    Uplers stops scanning it; ``gmail_connected`` is reported before and after
    so that is visible rather than asserted.

    **IT IS REVERSIBLE, and this is the one genuinely reassuring fact here.**
    ``POST`` to the SAME url with a literal ``{}`` body re-grants it - VERIFIED,
    both call sites use the identical route constant. **Re-granting starts a
    FRESH scan**: their own enable path zeroes ``last_job_scan`` and
    ``total_jobs`` in local state and then refetches, so the counters restart
    rather than resuming. That POST is not built here; the re-grant is a
    decision of the same size as the revoke and would need its own tool.

    THE STATE THIS WAS WRITTEN AGAINST
    -----------------------------------
    MEASURED 2026-08-24: consent is **ON** (``has_consent: true``), last scan
    2026-08-24, 77 jobs found, breakdown LinkedIn 77 and every other board 0.
    The committed fixture ``tests/fixtures/outreach_meta_email.json`` is the
    2026-08-23 capture and reads 79 with LinkedIn 79 - one scan earlier, same
    shape. Both are recorded so a reader comparing them does not read a daily
    scan's own movement as a contradiction. Guard 1 reads the live value on
    every call regardless, and nothing here is decided from either number.

    Guard 4 is the specific case worth naming: **if ``has_consent`` already
    reads false there is nothing to revoke and this REFUSES.** Uplers' own UI
    cannot reach this button in that state either - their revoke handler is
    gated on ``Oe?.has_consent`` being true.
    """
    payload = await client.get_json(EP_READ_SCAN_CONSENT, None)
    current = read_scan_consent(payload)

    if current["has_consent"] is None:
        raise WriteRefused(
            "The live consent record carried no `has_consent` field, so whether "
            "the scan is on is UNKNOWN - which is not the same as 'it is on'. "
            "Refusing to send a revoke without knowing there is something to "
            "revoke. Nothing was sent."
        )
    if current["has_consent"] is False:
        raise WriteRefused(
            "The Gmail job-board scan is ALREADY OFF (has_consent: false on %s), "
            "so there is nothing to revoke and this would change nothing. Uplers' "
            "own UI cannot reach this button in that state either - their revoke "
            "handler is gated on has_consent being true. Nothing was sent. To "
            "turn the scan back ON, that is a POST to the same URL with a literal "
            "{} body, and it is not built here."
            % EP_READ_SCAN_CONSENT
        )

    common = {
        "action": "revoke_email_scan",
        "method": outreach_write._method_of(send, "DELETE"),
        "endpoint": outreach_write._endpoint_of(send),
        # Guard 2 on a route with nothing to preview but its URL. The empty
        # dict is the literal truth of the request, and `body_keys` being
        # empty is asserted by a test so a body arriving here later is loud.
        "body": {},
        "body_keys": [],
        "path_id": None,
        "reversible": True,
        "reversible_how": (
            "POST to the same URL with a literal {} body re-grants it. Not built "
            "here - re-granting is a decision the same size as revoking."
        ),
        "current": dict(current),
        "withheld": list(agent_surface.WITHHELD_IDENTITY_KEYS),
        "notes": [
            "THE DELETE CARRIES NO BODY, NO QUERY STRING AND NO PATH SEGMENT. "
            "The URL is the entire request; Uplers' own helper for it is a bare "
            "delete(url). That is why the body above is empty rather than "
            "summarised.",
            "IT STOPS FUTURE SCANS ONLY. Uplers' own success copy is future "
            'tense: "%s"' % REVOKE_SUCCESS_COPY,
            "NO ROUTE ANYWHERE DELETES ALREADY-INGESTED SCAN DATA. Complete "
            "negative search: the only three DELETE routes under "
            "talent/outreach/* are this consent, %s and %s. The %s job(s) this "
            "scan has already found stay where they are."
            % (
                OUTREACH_DELETE_ROUTES[1],
                OUTREACH_DELETE_ROUTES[2],
                current.get("total_jobs"),
            ),
            "IT DOES NOT DISCONNECT GMAIL. That is a separate grant on a "
            "separate route (%s) which this server does not build. The mailbox "
            "stays connected (gmail_connected is %r right now) and Uplers stops "
            "reading it." % (GMAIL_DISCONNECT_ROUTE, current.get("gmail_connected")),
            "RE-GRANTING STARTS A FRESH SCAN rather than resuming this one: "
            "their enable path zeroes last_job_scan and total_jobs and then "
            "refetches.",
            "The mailbox ADDRESS is in this route's payload and in the DELETE's "
            "own response, and is dropped from everything returned here. A tool "
            "result ends up in a transcript.",
        ],
    }

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = "uplers_revoke_email_scan(confirm=True)"
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent and no snapshot was written. Confirming "
            "writes the current scan record to disk first, then sends the "
            "DELETE, then re-reads the consent to check it actually landed.",
        )
        return result

    outreach_write._require_sender(send)
    # The SHAPED record, which is the one with no address in it. The snapshot
    # file is not a transcript, but it is a file, and there is no reason for
    # the address to be in it when nothing restores from that field.
    snapshot = outreach_write.write_snapshot(
        current, kind="scan-consent", label="pre-revoke"
    )

    response = await send()

    verification = await _verify_consent_off(client)

    scrubbed_response, dropped = scrub(response if isinstance(response, dict) else {})

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["snapshot_is_not_an_undo"] = (
        "The snapshot records what the scan HELD, not a value that can be put "
        "back. The undo is a route - POST the same URL with {} - and it starts a "
        "fresh scan rather than restoring this one."
    )
    result["response"] = scrubbed_response
    result["response_redacted_keys"] = dropped
    result["verified"] = verification
    result["reverse_with"] = (
        "POST %s with a literal {} body. Not built in this server; re-granting "
        "restarts the scan from zero." % EP_READ_SCAN_CONSENT
    )
    return result


async def _verify_consent_off(client: Any) -> dict:
    """Guard 5. Re-read the consent and say whether the revoke actually landed.

    **THIS SERVER RE-READS WHERE UPLERS' OWN CLIENT DOES NOT.** VERIFIED: their
    enable path awaits a refetch of this same route; their revoke path does
    not - it patches local state optimistically and stops. And the DELETE's own
    response carries ``{gmail_connected, gmail_email}`` with no ``has_consent``
    in it at all, so there is no field in the reply that could confirm this.
    The extra GET is the only evidence that exists.

    A failure HERE must not raise, for ``outreach_write._verify``'s reason: the
    write already happened, and turning a failed read-back into an exception
    throws away the one fact the caller most needs. It reads as UNKNOWN, never
    as "landed".
    """
    try:
        payload = await client.get_json(EP_READ_SCAN_CONSENT, None)
        current = read_scan_consent(payload)
    except TalentError as exc:
        return {
            "re_read": False,
            "landed": None,
            "route": EP_READ_SCAN_CONSENT,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "note": (
                "The revoke was sent and the read-back failed, so whether it "
                "landed is UNKNOWN - not 'no'. Read uplers_email_scan() to find "
                "out."
            ),
        }

    landed = current["has_consent"] is False
    return {
        "re_read": True,
        "landed": landed,
        "route": EP_READ_SCAN_CONSENT,
        "has_consent_now": current["has_consent"],
        "gmail_connected_now": current["gmail_connected"],
        "note": (
            "Verified by reading the consent back, which is MORE than Uplers' own "
            "client does - its revoke path never refetches, and the DELETE's "
            "response carries no has_consent to check."
        )
        if landed
        else (
            "THE REVOKE DID NOT LAND. The route accepted the request and the "
            "consent still reads %r." % (current["has_consent"],)
        ),
    }


# ===========================================================================
# B. Submit interview feedback - ONE WAY
# ===========================================================================


def feedback_body(company_id: Any, feedback: Any) -> dict:
    """The exact TWO-key body. Nothing else may ride along.

    VERIFIED at all four call sites across three screens:
    ``{company_id: t, feedback: n}``. The key set is pinned by
    :data:`FEEDBACK_BODY_KEYS` and asserted in the suite, because this route
    cannot be un-sent and a third key added later would go out on a request
    nobody previewed with it in.

    An empty ``feedback`` is REFUSED rather than sent. Uplers reads a
    validation error back at ``res.data.errors.feedback[0]``, so their server
    has an opinion about it; more to the point, a blank review published on a
    one-way route is a mistake and not a command, which is the same call
    ``outreach_write.template_body`` makes about a blank template.
    """
    identifier = as_company_id(company_id)
    text = "" if feedback is None else str(feedback)
    if not text.strip():
        raise WriteRefused(
            "The feedback text is empty. This route is ONE-WAY - there is no "
            "edit route and no delete route for submitted feedback anywhere in "
            "Uplers' product - so publishing a blank review is treated as a "
            "mistake rather than a command. Nothing was sent."
        )
    return {"company_id": identifier, "feedback": text}


async def submit_interview_feedback(
    client: Any,
    company_id: Any,
    feedback: Any,
    *,
    confirm: bool = False,
    send: Any = None,
) -> dict:
    """Publish your review of a company you interviewed with. **ONE WAY.**

    ``POST talent/outreach/interview-feedback``, body ``{company_id, feedback}``
    - exactly two keys, VERIFIED at the call site.

    **THERE IS NO EDIT ROUTE AND NO DELETE ROUTE FOR SUBMITTED FEEDBACK.**
    Complete negative search over Uplers' bundle found neither. The only thing
    that can follow this write is another POST for the same ``company_id``, and
    whether their server treats that as an overwrite or as a second record is
    NOT decidable from their client - it patches its own row either way, so the
    bundle cannot answer it and this docstring does not guess. **The snapshot
    this tool takes is local only and cannot retract what Uplers received.**
    Treat every submission as final and public.

    **MEASURED: ``interview-list`` RETURNS ZERO COMPANIES.** The captured
    fixture ``tests/fixtures/talent_interviews.json`` carries ``data: []`` and
    the 2026-08-25 measurement agrees. So there is nothing to give feedback
    about right now, and **every call refuses today - that is the tool working,
    not the tool broken.** The refusal names the empty list and says why it is
    empty rather than reporting a company id as merely "not found".

    Guard 4 is that refusal: **if ``company_id`` is not among the companies
    Uplers lists, this REFUSES rather than posting a company id the account has
    no interview with.** On a route with no undo, "the id was probably right" is
    not a standard worth writing against - and a wrong id publishes a review
    against a company he never met.

    An empty list is NOT the same as "no interviews", and the refusal says so.
    Uplers builds this list by scanning a mailbox, and ``meta.has_consent`` on
    THIS route governs that scan - a DIFFERENT consent from the Gmail job scan
    the other half of this module revokes, wearing the identical field name.
    MEASURED: it reads false while ``gmail_connected`` reads true.
    """
    body = feedback_body(company_id, feedback)
    identifier = body["company_id"]

    payload = await client.get_json(EP_READ_INTERVIEWS, dict(INTERVIEW_LIST_PARAMS))
    rows = read_interview_companies(payload)
    meta = interview_meta(payload)
    existing = find_company(rows, identifier)

    if existing is None:
        raise WriteRefused(_not_on_the_list(identifier, rows, meta))

    common = {
        "action": "submit_interview_feedback",
        "company_id": identifier,
        "company_name": existing.get("company_name"),
        "role": existing.get("role"),
        "method": outreach_write._method_of(send, "POST application/json"),
        "endpoint": outreach_write._endpoint_of(send),
        # The caller's own text, echoed in full. Guard 2's whole point is that
        # they are authorising exactly this, and a preview that hides what they
        # typed is not a preview. It is theirs, not somebody else's, which is
        # the distinction `outreach_write.render_body` draws.
        "body": dict(body),
        "body_keys": sorted(body),
        "reversible": False,
        "one_way": True,
        "current": {
            "interview_companies": len(rows),
            "feedback_already_given": existing.get("feedback_given"),
        },
        "notes": [
            "ONE WAY. There is no edit route and no delete route for submitted "
            "feedback anywhere in Uplers' product - a complete negative search "
            "found neither. Once this lands you cannot take it back from here.",
            "The snapshot taken before this write is LOCAL ONLY. It records the "
            "interview list as it stood; it cannot retract what Uplers received.",
            "The body is exactly two keys, company_id and feedback, VERIFIED at "
            "all four call sites in Uplers' own bundle. Nothing else is sent.",
            "A repeat POST for the same company_id is the only way to change "
            "this, and whether their server overwrites or appends is NOT known - "
            "their client patches its own row either way, so the bundle cannot "
            "answer it and this does not guess.",
        ],
    }
    if existing.get("feedback_given"):
        common["notes"].insert(
            0,
            "UPLERS ALREADY HAS FEEDBACK FROM YOU FOR THIS COMPANY. Sending "
            "again is the repeat-POST case above, whose behaviour is unknown - "
            "it may overwrite, it may append a second review. Not refused, "
            "because a correction is a legitimate thing to want; named here so "
            "the uncertainty is yours to accept before you confirm.",
        )

    if not confirm:
        result = dict(common)
        result["performed"] = False
        result["snapshot"] = {"written": False}
        result["to_confirm"] = (
            "uplers_submit_interview_feedback(%d, <the same text>, confirm=True)"
            % identifier
        )
        result["notes"].insert(
            0,
            "PREVIEW - nothing was sent and no snapshot was written. There is no "
            "undo for this write, so this preview is the only chance to read the "
            "exact text before it is published.",
        )
        return result

    outreach_write._require_sender(send)
    snapshot = outreach_write.write_snapshot(
        rows, kind="interview-feedback", label="pre-submit"
    )

    response = await send(body)

    verification = await _verify_feedback(client, identifier)

    scrubbed_response, dropped = scrub(response if isinstance(response, dict) else {})

    result = dict(common)
    result["performed"] = True
    result["snapshot"] = dict(snapshot, written=True)
    result["snapshot_is_not_an_undo"] = (
        "It records the interview list as it stood before the write. Uplers has "
        "the review; nothing local can take it back."
    )
    result["response"] = scrubbed_response
    result["response_redacted_keys"] = dropped
    result["verified"] = verification
    result["reverse_with"] = (
        "NOTHING. There is no edit route and no delete route for submitted "
        "feedback on Uplers."
    )
    return result


def _not_on_the_list(identifier: int, rows: list[dict], meta: dict) -> str:
    """Guard 4's refusal, and the empty list gets its own diagnosis.

    "Company 7 is not on the list" is true and useless when the list has zero
    rows for a reason - the reader is left thinking they typed the wrong id
    when in fact nothing could ever match.
    """
    if not rows:
        consent = meta.get("has_consent")
        connected = meta.get("gmail_connected")
        return (
            "Uplers lists NO interview companies at all, so there is nothing to "
            "give feedback about and company %d cannot be on a list with zero "
            "rows. Nothing was sent.\n"
            "THIS IS NOT 'no interviews were arranged'. Uplers builds this list "
            "by scanning a mailbox, and this route's own meta reports "
            "has_consent=%r for that INTERVIEW email scan (gmail_connected=%r). "
            "That is a DIFFERENT consent from the Gmail JOB scan - it wears the "
            "identical field name and it is not the same switch. There is "
            "nothing for you to turn on: MEASURED across Uplers' entire bundle, "
            "the consent this flag names has no client reader and its UI ships "
            "as CSS with nothing rendering it."
            % (identifier, consent, connected)
        )
    listed = ", ".join(
        "%s (%s)" % (row.get("company_id"), row.get("company_name") or "unnamed")
        for row in rows[:12]
    )
    return (
        "Company %d is not among the %d company/companies Uplers lists an "
        "interview for, so this would publish a review against a company this "
        "account has no interview with - on a route that cannot be un-sent. "
        "Nothing was sent. Uplers lists: %s."
        % (identifier, len(rows), listed)
    )


async def _verify_feedback(client: Any, identifier: int) -> dict:
    """Guard 5. Re-read the interview list and check the row now carries feedback.

    The POST answers ``res.data.status === "success"`` and nothing about the
    record, so the reply cannot confirm the review is actually attached to the
    right company. Only the list can.

    Does not raise on a failed read-back, for ``_verify_consent_off``'s reason.
    """
    try:
        payload = await client.get_json(EP_READ_INTERVIEWS, dict(INTERVIEW_LIST_PARAMS))
        rows = read_interview_companies(payload)
    except TalentError as exc:
        return {
            "re_read": False,
            "landed": None,
            "route": EP_READ_INTERVIEWS,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "note": (
                "The feedback was sent and the read-back failed, so whether it "
                "landed is UNKNOWN - not 'no'. IT CANNOT BE RESENT SAFELY on "
                "that basis: this route is one-way and a second POST has "
                "unknown behaviour. Read uplers_my_interviews() first."
            ),
        }

    row = find_company(rows, identifier)
    return {
        "re_read": True,
        "landed": bool(row and row.get("feedback_given")),
        "route": EP_READ_INTERVIEWS,
        "company_id": identifier,
        "row_found": row is not None,
        "note": (
            "Verified by reading the interview list back - the POST's own reply "
            "is only a status string and says nothing about the record."
        )
        if row and row.get("feedback_given")
        else (
            "THE WRITE MAY NOT HAVE LANDED: the route accepted the request and "
            "the interview row does not report feedback against it. Do NOT "
            "simply resend - this route is one-way and repeat behaviour is "
            "unknown."
        ),
    }
