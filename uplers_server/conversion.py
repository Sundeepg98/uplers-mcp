"""The CONVERSION ring: who answered, what they asked for, and what is blocked.

Every other read in this server is about DISCOVERY - what is on the board, what
suits him, what the agent queued. This module is about the other end of the
funnel, and it exists because of one number: **nine applications in about two
and a half years, eight of them still sitting at "Added" and one at "Profile
Shared".** Discovery is not the bottleneck on this account. Conversion is.

FOUR ROUTES, TWO TOOLS, AND EVERY FIXTURE WAS ALREADY ON DISK
--------------------------------------------------------------
    tool                        route                                fixture
    uplers_reply_outcomes       talent/outreach/value-with-happy     outreach_value_with_happy
    uplers_agent_pending        talent/outreach/has-pending-action-  outreach_pending_action
                                  manual-outreach-agent
                                talent/outreach/missed-positive-     outreach_followups_pending
                                  reply-followups-pending?days=15
                                talent/outreach/external-job-link-   outreach_external_remaining
                                  remaining

A THIRD TOOL WAS BRIEFED AND IS NOT HERE. `uplers_salary_estimate`, over
`get-company-salary-data`, was designed and then STOPPED on 2026-08-25 when
three separate live measurements contradicted the premises it was to be built
on - among them that the route's success envelope has no `data` key at all, so
:func:`uplers_server.outreach.unwrap` cannot read it. The findings are written
up under `EP_COMPANY_SALARY` in :mod:`uplers_server.endpoints` and the probe
that produced them is `scripts/probe_company_salary.py`. Nothing here reaches
that route, and no half-built gate for it is left in this module: an untested
reader for a shape that was measured to be different is worse than none.

THE FOUR FIXTURES WERE ALREADY COMMITTED AND NOTHING READ THEM. They were
captured live on 2026-08-23/24, cost a live request each, and then sat in a
public repository with no tool consuming one and no test asserting on one - the
PII sweep in `test_fixture_hygiene.py` globbed them, but scanning a payload is
not using it. This module is what makes those four load-bearing. That is stated
here rather than in a changelog because the same thing can happen again the
moment a capture runs ahead of its reader.

ENVELOPES: THREE STRINGS AND AN INTEGER, per route, MEASURED
--------------------------------------------------------------
`value-with-happy`, `has-pending-action-manual-outreach-agent` and
`external-job-link-remaining` answer the STRING `"success"`;
`missed-positive-reply-followups-pending` answers the INTEGER `200`. The split
does not follow the ring, the capture script or the date - it is per route,
which is the third time this API has done that.
:func:`uplers_server.outreach.unwrap` already accepts exactly those two idioms
and refuses everything else, so it is imported rather than reimplemented. A
third unwrapper in this package would be a third thing to keep in step with an
API that changes its mind per route.

THE COUNTERPARTY'S NAME IS NEVER RETURNED
------------------------------------------
`value-with-happy` rows carry `employee_name` - the actual person at the actual
company who answered - and `logo_url`, a CDN address. Neither is returned by
anything here, on exactly the register `uplers_agent_readthrough` already set
for this namespace: the reply category, the company and the channel are what
you act on; the person's name and the addresses belong in the thread they were
written in, not in a transcript. :data:`WITHHELD_KEYS` names them in the tool
output so a reader knows the route carried more than was printed, and
:data:`WITHHELD_REASON` says why in the result rather than only here.

`employee_name` is MASKED at capture time (`capture_outreach.MASK` rewrites it
to "Redacted Contact %d"), so the committed fixture cannot prove the shaper
withholds it - a sweep over the fixture alone would pass by having nothing to
find. `tests/test_conversion.py` plants a real-looking name back on the row and
proves the shaper still never prints it. `logo_url` is NOT masked and is
verbatim in the fixture, so that half is proven against the real payload.

ABSENT IS NOT ZERO, AND ABSENT IS NOT FALSE
--------------------------------------------
Every scalar goes through :func:`uplers_server.outreach._int`, `_flag` or
`_text`, all of which answer `None` for a key that was not sent. "No replies
came back" and "the payload did not carry a count" are opposite facts about
this account, and so are "nothing is pending" and "the route did not say".
`tests/test_conversion.py` carries a control per tool, each watched failing
with the shaper rendering absent as zero or as False.

EVERY FUNCTION IS PURE - no I/O, no network, no clock. `server.py` does the
fetching. Same discipline as :mod:`uplers_server.outreach`,
:mod:`uplers_server.agent_surface` and :mod:`uplers_server.skus`, and for the
same reason: a shaper that reached the network could not be pinned by a fixture.

NO PARAMETERS, EXCEPT ONE WINDOW
---------------------------------
All four routes are plain GETs and only `missed-positive-reply-followups-
pending` takes anything at all (`?days=`). There is no identifier to resolve,
no id space to get wrong, and no write path anywhere in this module or in the
two tools that call it.
"""

from __future__ import annotations

from typing import Any

from . import endpoints, outreach
from .outreach import OutreachError, unwrap

# --- Routes -----------------------------------------------------------------
#
# ALIASES, not definitions. endpoints.py is this server's single route
# authority and carries the live-verification evidence for each one.

ROUTE_REPLY_OUTCOMES = endpoints.EP_OUTREACH_VALUE_WITH_HAPPY
ROUTE_PENDING_ACTION = endpoints.EP_OUTREACH_PENDING_ACTION
ROUTE_FOLLOWUPS_PENDING = endpoints.EP_OUTREACH_FOLLOWUPS_PENDING
ROUTE_EXTERNAL_REMAINING = endpoints.EP_OUTREACH_EXTERNAL_REMAINING

# BORROWED, NOT COPIED - the same call `agent_surface.py` and `skus.py` make,
# for the same reason. These already exist, already have their own tests, and
# already carry the quirks they were written for.
_flag = outreach._flag
_int = outreach._int
_text = outreach._text
_tally = outreach._tally
_cross_check = outreach._cross_check

#: The `days` window `EP_OUTREACH_FOLLOWUPS_PENDING` was CAPTURED at. The route
#: echoes whatever it was sent back under `days`, so the shaper reports the
#: echo rather than this constant - a caller that asked for 30 and was answered
#: about 15 must be able to see that.
CAPTURED_FOLLOWUP_DAYS = 15

#: Present in the `value-with-happy` rows, deliberately never returned. Named
#: in the shaped output so a reader knows the route carried more than was
#: printed - the convention `agent_surface.WITHHELD_BODY_KEYS` set.
WITHHELD_KEYS = ("employee_name", "logo_url")

WITHHELD_REASON = (
    "Withheld from every row, without exception. employee_name is the actual "
    "person at the actual company who answered, and logo_url is a CDN address. "
    "Neither is needed to act on a reply and neither belongs in a transcript - "
    "the same rule uplers_agent_readthrough applies to contact routes and "
    "verbatim reply bodies. The company, the channel and what they asked for "
    "are here; the name is in the thread, which is where to read it."
)

#: The one thing this route CANNOT tell you about a row, said once for the page.
#:
#: It used to be repeated verbatim on every row as `answered_note`. It is a
#: statement about the ROUTE - nothing in `value-with-happy` records whether he
#: answered, and the rows carry no timestamp, thread id or joining key that
#: could - so it is true of all of them or none. The three-valued `answered`
#: flag STAYS on each row: that is the value a caller reads to decide, and this
#: is only the sentence explaining it.
ANSWERED_NOTE = "not recorded on this route - check the thread"


# --- Small guards -----------------------------------------------------------


def _require(value: Any, *, name: str, route: str, caller: str) -> dict:
    """One shaped dict, proven to be the one this slot wants.

    The guard :func:`uplers_server.outreach._require_shape` applies to the
    readthrough, and here for the same reason: :func:`agent_pending` takes
    three shaped dicts that all describe agent state and two of which carry a
    tri-state boolean, so a swapped pair would render as a real read of his
    account rather than as an error.
    """
    if not isinstance(value, dict):
        raise OutreachError(
            "%s got %s for `%s`, not a shaped dict. Pass the output of the "
            "matching shape_* function." % (caller, type(value).__name__, name)
        )
    seen = value.get("route")
    if seen != route:
        raise OutreachError(
            "%s got a shape from route %r for `%s`, which must carry %r. The "
            "inputs are not interchangeable." % (caller, seen, name, route)
        )
    return value


def _rows(data: dict, key: str) -> list:
    """The list under `key`, or the empty list if it is not one.

    Deliberately NOT `data.get(key, [])`: a JSON `null`, a dict or a string
    under a key this shaper expects to be a list is drift, and iterating it
    would either raise somewhere unhelpful or silently produce rows. The
    COUNT of what was actually a list is reported separately by each caller,
    so an empty result is never confusable with a shape change.
    """
    value = data.get(key)
    return value if isinstance(value, list) else []


# --- Tool 1: what the replies actually wanted -------------------------------


def shape_reply_outcomes(payload: dict, pending: dict | None = None) -> dict:
    """Reply outcomes, from ``talent/outreach/value-with-happy``.

    **THE ONLY SURFACE IN THIS SERVER THAT SAYS WHAT A REPLY ASKED FOR.** The
    dashboard counts replies; ``get-outreach-agent-meta`` splits them positive
    and negative; ``missed-positive-reply-followups`` returns the threads. None
    of them carries a `reply_category`. This one does, in free text, and the
    difference it makes is the difference between "someone replied" and
    "someone is waiting on a document from you".

    MEASURED (``tests/fixtures/outreach_value_with_happy.json``, captured
    2026-08-24): ``jobs_run: 32``, ``interview_companies`` the EMPTY LIST, and
    ``response`` seven rows - every one ``reply_type: "positive"``, every one
    ``channel: "gmail"``. Their categories name three distinct asks: a request
    for an updated resume, a request for a form, and five variations of "your
    profile has been forwarded".

    **THE COUNT HERE IS NOT THE REPLY LEDGER, AND THE RESULT SAYS SO.**
    ``get-outreach-agent-meta`` measured 8 positive and 2 negative on
    2026-08-23; this route returned 7 positive rows and no negative row at all
    on 2026-08-24. The route's name is the obvious hypothesis - "value with
    HAPPY" reads like a curated subset - and it is a hypothesis, not a
    measurement, so this shaper reports ITS OWN count under a name that says
    whose count it is and points at the route that holds the totals. It does
    not reconcile the two and it does not average them; nobody sent a third
    number.

    ``jobs_run`` is Uplers' count of agent runs, not of replies, and is
    reported under its own name for the same reason.

    THE COUNTERPARTY'S NAME IS NEVER RETURNED. See the module docstring.

    IT IS A SNAPSHOT, NOT A TO-DO LIST, AND THAT DISTINCTION COST SOMEBODY REAL
    TIME. `reply_category` records WHAT WAS ASKED. It carries nothing about
    whether he answered - and a row reading "requests updated resume" with no
    completion state beside it reads as outstanding. It was read that way, out
    loud, on two rows that had both been answered a fortnight earlier: the
    resume went on 11 Aug and the form was completed on 12 Aug with the referral
    confirmed on 14 Aug.

    MEASURED, so the limit is stated rather than guessed. The `response` rows
    carry exactly `channel`, `company_name`, `employee_name`, `logo_url`,
    `reply_category`, `reply_type` - **no timestamp, no thread id, no status,
    and no key that joins to anything that has one.** So a per-row answered flag
    is not merely unbuilt here; the data to build it is not on this route.

    WHAT UPLERS DOES EXPOSE is one account-level BOOLEAN:
    `missed-positive-reply-followups-pending` answers `{days, pending}`, and
    Uplers' own message calls it a *"Reply reminders pending flag"*. It is
    passed in rather than fetched here so this shaper stays a pure function of
    its payloads.

    **AND IT DISAGREES WITH THE MAILBOX, WHICH IS WHY IT IS CARRIED RATHER THAN
    TRUSTED.** MEASURED 2026-08-25: the flag reads **true** at 90 days, while at
    least two of the rows above had been answered a fortnight earlier. It is the
    AGENT's reminder state, not a record of what he sent - his replies happen in
    his own mailbox, which this platform does not read. Reading `true` as "he
    owes replies" would reproduce the exact mistake this field exists to
    prevent, in the opposite direction.

    A NEAR-MISS WORTH RECORDING, because the first version of this code shipped
    the opposite claim. A probe that extracted rows from the payload found none
    and reported "0", and "0 pending" was written up as *nothing is
    outstanding*. The value is not a count and was never 0; it is `true`.
    `outreach._int` is what caught it - it rejects `bool` by design, so the
    field came back None instead of a confident zero. **A helper that refuses to
    coerce is worth more than one that copes.**

    So `completion_state` ships in the PAYLOAD, not only here: a docstring is
    read once and a field is read every time.
    """
    data = unwrap(payload, route=ROUTE_REPLY_OUTCOMES, expect=dict)

    raw_rows = _rows(data, "response")
    rows = [_reply_row(row) for row in raw_rows if isinstance(row, dict)]

    categories = [row["reply_category"] for row in rows if row["reply_category"]]
    types = [row["reply_type"] for row in rows if row["reply_type"]]
    channels = [row["channel"] for row in rows if row["channel"]]

    raw_interviews = _rows(data, "interview_companies")
    interviews = [
        _text(row.get("company_name")) if isinstance(row, dict) else _text(row)
        for row in raw_interviews
    ]
    interviews = [name for name in interviews if name]

    headline: list[str] = []
    if rows:
        headline.append(
            "%d repl%s came back on this route, from %d compan%s."
            % (
                len(rows),
                "y" if len(rows) == 1 else "ies",
                len({row["company_name"] for row in rows if row["company_name"]}),
                "y"
                if len({row["company_name"] for row in rows if row["company_name"]})
                == 1
                else "ies",
            )
        )
        headline.append(
            "WHAT THEY ASKED FOR, at the time they wrote: %s."
            % "; ".join("%s (x%d)" % (text, n) for text, n in _tally(categories).items())
        )
        headline.append(
            "THIS IS A SNAPSHOT OF WHAT WAS ASKED, NOT A LIST OF WHAT IS "
            "OUTSTANDING. Nothing on this route records whether he answered. "
            "Read completion_state before treating any row as an action."
        )
    else:
        headline.append(
            "This route returned NO reply rows. That is its own answer and not "
            "a reading failure - the envelope was valid and `response` was an "
            "empty list."
            if isinstance(data.get("response"), list)
            else "This route carried no `response` LIST at all, which is drift "
            "rather than an empty result. Nothing is counted from it."
        )

    if not interviews:
        headline.append(
            "NO interview has come out of any of them: interview_companies is "
            "empty on the same payload."
        )

    completion = _completion_state(pending)

    return {
        "route": ROUTE_REPLY_OUTCOMES,
        "headline": headline,
        # THE FIELD THIS TOOL EXISTS TO CARRY. A docstring is read once; this is
        # read every call. Never let a row be actioned without it.
        "completion_state": completion,
        # Named for whose count it is. See the docstring: this is NOT the
        # positive/negative ledger and must not be read as one.
        "replies_on_this_route": len(rows),
        "response_was_a_list": isinstance(data.get("response"), list),
        # Named for its SCOPE. It applies to every row below, which is exactly
        # why it is not on any of them.
        "answered_note_all_rows": ANSWERED_NOTE,
        "rows": rows,
        "asks": _tally(categories),
        "by_reply_type": _tally(types),
        "by_channel": _tally(channels),
        "agent_runs_reported": _int(data.get("jobs_run")),
        "interview_companies": interviews,
        "interview_companies_returned": len(interviews),
        "withheld": list(WITHHELD_KEYS),
        "withheld_reason": WITHHELD_REASON,
        "notes": [
            "replies_on_this_route is THIS ROUTE'S count and is not the reply "
            "ledger. talent/outreach/get-outreach-agent-meta holds the "
            "positive/negative totals and measured 8 and 2 on 2026-08-23, "
            "against 7 rows here on 2026-08-24. The two are printed apart "
            "rather than reconciled; read uplers_agent_readthrough for the "
            "totals.",
            "agent_runs_reported is jobs_run - the number of agent RUNS, not "
            "of replies.",
            "reply_category is Uplers' own free text. It is passed through "
            "verbatim and is not mapped onto any category scheme.",
        ],
        "reads_only": True,
    }


def _completion_state(pending: dict | None) -> dict:
    """Whether he ANSWERED is not on this route. Say so, in the payload.

    Three-valued and `unknown` is the default, because the alternative - an
    absent field - is what a reader turns into "outstanding". The one thing
    this must never do is let a row be mistaken for a task.
    """
    state = {
        "per_reply_answered": "NOT AVAILABLE",
        "why": (
            "These categories record WHAT WAS ASKED, never whether he "
            "answered. The rows carry no timestamp, no thread id and no key "
            "that joins to one, so a per-reply answered flag cannot be "
            "derived from this route at all. CHECK THE THREAD before treating "
            "any row as an action."
        ),
        "measured_absence": (
            "response rows carry exactly: channel, company_name, "
            "employee_name, logo_url, reply_category, reply_type."
        ),
    }
    if not isinstance(pending, dict):
        state["uplers_side_followups_pending"] = None
        state["pending_note"] = (
            "The portfolio-level pending count was not read on this call, so "
            "even the agent-side signal is unknown here."
        )
        return state

    state["uplers_reply_reminder_pending"] = _flag(pending.get("pending"))
    state["pending_window_days"] = _int(pending.get("days"))
    state["pending_note"] = (
        "missed-positive-reply-followups-pending answers {days, pending} where "
        "`pending` is a BOOLEAN - Uplers' own message calls it a 'Reply "
        "reminders pending flag'. It is one flag for the whole account, so it "
        "cannot be attributed to any row above. "
        "AND IT IS NOT A STATEMENT THAT HE DID NOT REPLY: it is the AGENT's "
        "reminder state. MEASURED 2026-08-25 it reads TRUE while at least two "
        "of the rows above were answered a fortnight earlier - the resume went "
        "on 11 Aug, the form on 12 Aug with the referral confirmed on 14 Aug. "
        "So the flag DISAGREES with the mailbox on those rows, and reading it "
        "as 'he owes replies' would reproduce exactly the mistake this field "
        "exists to prevent."
    )
    return state


def _reply_row(raw: dict) -> dict:
    """One ``response`` row, minus the person and minus the addresses.

    `employee_name` and `logo_url` are NOT read, not even into a local, so
    there is no path by which either reaches the returned dict. That the route
    carried them and this server refused them is stated in the ENVELOPE, by
    :data:`WITHHELD_KEYS` and :data:`WITHHELD_REASON`, because a silent
    omission is indistinguishable from an oversight.

    WHAT IS ON THE ROW IS WHAT CAN DIFFER BETWEEN ROWS. `channel` and
    `reply_type` read `gmail` and `positive` on all seven rows of the current
    capture and are per-reply facts that will differ the moment a LinkedIn
    reply or a negative one lands - uniform by coincidence, not by
    construction, so they stay. `answered` stays for the stronger reason
    below.

    THREE MARKERS CAME OFF THIS ROW, all of them constant BY CONSTRUCTION.
    `answered_note` said the same 47 bytes seven times; `employee_name_
    withheld` and `logo_url_withheld` could not be anything but True, because
    this function never reads either key. All three are route-level facts and
    are now stated once, in the envelope. Nothing was dropped - `answered_note`
    moved byte for byte, and the withholding is named in `withheld` with a
    reason that says explicitly that it covers every row.
    """
    return {
        "company_name": _text(raw.get("company_name")),
        "channel": _text(raw.get("channel")),
        "reply_category": _text(raw.get("reply_category")),
        "reply_type": _text(raw.get("reply_type")),
        # THREE-VALUED, AND IT IS ALWAYS "unknown" ON THIS ROUTE - but it stays
        # HERE, not in the envelope, and the distinction is deliberate. The row
        # is what gets read aloud, an absent field is what a reader turns into
        # "outstanding", and a route that ever does record completion would make
        # this vary per row. Its explanatory NOTE is route-level and moved up;
        # the value a caller reads to decide did not. `unknown` must never be
        # rendered as an action.
        "answered": "unknown",
    }


# --- Tool 3: is anything blocked on him right now? --------------------------


def shape_pending_action(payload: dict) -> dict:
    """From ``has-pending-action-manual-outreach-agent``.

    MEASURED (``tests/fixtures/outreach_pending_action.json``, captured
    2026-08-23): ``{"data": {"has_pending_action": false, "hrs": []},
    "status": "success"}`` - the STRING idiom.

    **THE ENVELOPE WAS PINNED BY THAT CAPTURE AND NOT BY THE BUNDLE.** Uplers'
    own UI fires this request and discards the response, so static analysis
    could say the route existed and could not say what it answered. The
    fixture could. It is still read DEFENSIVELY - `data_keys` reports what the
    payload actually carried - because one capture on one day is one
    observation, and a route whose response nobody in Uplers' own frontend
    reads is a route with nothing keeping its shape honest.

    ``has_pending_action`` false with an empty ``hrs`` list is an AGREEMENT
    between two fields of one payload and is reported as one. An absent flag
    is ``None``, never False: "nothing is pending" and "the route did not say"
    are different answers and only one of them is good news.
    """
    data = unwrap(payload, route=ROUTE_PENDING_ACTION, expect=dict)

    raw_rows = _rows(data, "hrs")
    pending = _flag(data.get("has_pending_action"))

    return {
        "route": ROUTE_PENDING_ACTION,
        "has_pending_action": pending,
        "hrs_returned": len(raw_rows),
        "hrs_was_a_list": isinstance(data.get("hrs"), list),
        # Field NAMES, never values. Reported because this route's shape has
        # nothing in Uplers' own frontend holding it steady, so drift here
        # would otherwise be invisible until a shaper read a key that moved.
        "data_keys": sorted(str(key) for key in data),
        "agreement": _cross_check(
            "nothing is waiting on him on this route",
            # Both rendered 0/1 so they are comparable at all; either being
            # absent leaves the claim unknown rather than agreed.
            flag_says_pending=(None if pending is None else int(pending)),
            rows_present=int(bool(raw_rows)),
        ),
        "notes": [
            "The response envelope was established by CAPTURE, not by reading "
            "Uplers' bundle - their UI discards this response. data_keys is "
            "reported so a shape change is visible rather than silent.",
        ],
    }


def shape_followups_pending(payload: dict) -> dict:
    """From ``missed-positive-reply-followups-pending?days=<n>``.

    **THE CONVERSION BIT.** A boolean: are there positive replies inside the
    window that were never followed up. MEASURED
    (``tests/fixtures/outreach_followups_pending.json``, captured 2026-08-23 at
    ``days=15``): ``{"days": 15, "pending": true}`` under the INTEGER 200 -
    ``pending`` reads **TRUE**.

    NOT THE SAME ROUTE as ``missed-positive-reply-followups``, which returns
    the THREADS and is already read by ``uplers_agent_readthrough``. This one
    is the flag; the two differ by a suffix and mixing them up would report a
    list where a boolean was asked for.

    THE ECHOED WINDOW IS REPORTED, NOT THE ONE THAT WAS SENT. The route echoes
    ``days`` back, and this shaper reads the echo, so a caller who asked for 30
    and was answered about 15 can see that. The shaper does not know what was
    sent - it is pure and never saw the request.
    """
    data = unwrap(payload, route=ROUTE_FOLLOWUPS_PENDING, expect=dict)
    pending = _flag(data.get("pending"))

    return {
        "route": ROUTE_FOLLOWUPS_PENDING,
        "pending": pending,
        "days_echoed": _int(data.get("days")),
        "notes": [
            "days_echoed is what the ROUTE said, not what was sent. If it "
            "differs from the window you asked for, the answer is about the "
            "window it names.",
            "This is the FLAG route. talent/outreach/missed-positive-reply-"
            "followups (no -pending suffix) returns the threads themselves and "
            "is read by uplers_agent_readthrough.",
        ],
    }


def shape_external_remaining(payload: dict) -> dict:
    """From ``external-job-link-remaining``. QUOTA CONTEXT, not an action.

    MEASURED (``tests/fixtures/outreach_external_remaining.json``, captured
    2026-08-23): ``{"limit": 8, "remaining": 8, "used": 0}`` under the STRING
    idiom.

    ``used + remaining == limit`` is CHECKED rather than assumed, and reported
    as a cross-check rather than as a derived total. Uplers sends all three, so
    a reader that recomputed one of them from the other two would be inventing
    agreement instead of measuring it. On the captured payload the three agree.

    An absent counter is ``None`` and the arithmetic is then simply unknown -
    never 0, which on a quota is the difference between "none left" and "we
    could not read how many are left".
    """
    data = unwrap(payload, route=ROUTE_EXTERNAL_REMAINING, expect=dict)

    limit = _int(data.get("limit"))
    used = _int(data.get("used"))
    remaining = _int(data.get("remaining"))

    return {
        "route": ROUTE_EXTERNAL_REMAINING,
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "counters_agree": _cross_check(
            "used and remaining account for the whole limit",
            limit=limit,
            used_plus_remaining=(
                used + remaining if (used is not None and remaining is not None) else None
            ),
        ),
        "notes": [
            "Uplers sends all three counters. None is recomputed from the "
            "others - they are held against each other instead.",
        ],
    }


def agent_pending(*, pending_action: dict, followups: dict, external: dict) -> dict:
    """The three no-param GETs as one answer to "is anything blocked on me?".

    Takes ALREADY-SHAPED dicts. Pure, and assembles nothing it was not given.

    WHY ONE TOOL READS THREE ROUTES. They are three different senses of
    "waiting", and only together do they say whether the next move is his:
    ``has_pending_action`` is the agent asking him to do something,
    ``pending`` is a positive reply going stale, and the quota is the context
    that says whether he could act even if he wanted to. Any one alone answers
    a third of the question.

    THE MIDDLE ONE IS THE CONVERSION ONE and is ranked first in the headline
    for that reason. A positive reply that was never followed up is the exact
    failure mode this account has: replies came back and the pipeline did not
    move.

    Nothing here is a recommendation. Every line is a state of his account.
    """
    pending_action = _require(
        pending_action,
        name="pending_action",
        route=ROUTE_PENDING_ACTION,
        caller="agent_pending",
    )
    followups = _require(
        followups,
        name="followups",
        route=ROUTE_FOLLOWUPS_PENDING,
        caller="agent_pending",
    )
    external = _require(
        external,
        name="external",
        route=ROUTE_EXTERNAL_REMAINING,
        caller="agent_pending",
    )

    headline: list[str] = []

    stale = followups.get("pending")
    if stale is True:
        headline.append(
            "POSITIVE REPLIES ARE UNANSWERED inside the last %s days - Uplers' "
            "own follow-up flag reads TRUE. This is the conversion one: read "
            "uplers_agent_readthrough for the threads, uplers_reply_outcomes "
            "for what each one asked for."
            % (followups.get("days_echoed") if followups.get("days_echoed") is not None
               else "reported")
        )
    elif stale is False:
        headline.append(
            "No positive reply inside the last %s days is unanswered."
            % (followups.get("days_echoed") if followups.get("days_echoed") is not None
               else "reported")
        )
    else:
        headline.append(
            "The follow-up flag did NOT say - it is unknown, not false. That is "
            "a reading gap, not a clean bill."
        )

    action = pending_action.get("has_pending_action")
    if action is True:
        headline.append(
            "The outreach agent has a PENDING ACTION for you (%d row(s) named)."
            % pending_action.get("hrs_returned", 0)
        )
    elif action is False:
        headline.append("The outreach agent is not waiting on you.")
    else:
        headline.append(
            "Whether the agent is waiting on you is UNKNOWN - the route did not "
            "carry the flag."
        )

    remaining = external.get("remaining")
    if remaining is not None:
        headline.append(
            "%d of %s external job-link slots remain."
            % (remaining, external.get("limit") if external.get("limit") is not None
               else "an unreported number of")
        )

    blocked = [
        name
        for name, value in (
            ("missed_followups", stale),
            ("agent_pending_action", action),
        )
        if value is True
    ]
    unknown = [
        name
        for name, value in (
            ("missed_followups", stale),
            ("agent_pending_action", action),
        )
        if value is None
    ]

    return {
        "headline": headline,
        # TRUE only where a route SAID true. A route that did not answer lands
        # in `unknown` and never in `blocked` - the whole point of the tri-state.
        "blocked_on_you": blocked,
        "unknown": unknown,
        "anything_blocked": bool(blocked),
        "missed_followups": followups,
        "agent_action": pending_action,
        "external_link_quota": external,
        "reads_only": True,
        "notes": [
            "Three GETs, no writes, no parameters except the follow-up window.",
            "`anything_blocked` is False only when every route ANSWERED and "
            "answered no. Check `unknown` before reading a False as an all-clear.",
            "Every line above is a state of the account, not a recommendation.",
        ],
    }

