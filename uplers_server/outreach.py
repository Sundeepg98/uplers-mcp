"""The paid outreach agent's own output, read back and made legible.

He PAYS for Uplers' autonomous application agent - the captured plan record
reads ``plan: 2``, ``auto_run: 1``, ``outreach_mode: "auto"``, paid through
2026-09-10 - and none of that agent's output was visible anywhere in this
server. That is the entire reason this module exists: to report what the agent
HAS DONE, what is PENDING, and what it MISSED.

**A READER, AND NOTHING ELSE.** Nothing here applies, sends, consents,
schedules or writes; there is no write path, not even a disabled one. The
applying agent is Uplers' product and he already owns it. Building a second
applier is out of scope by decision; reading the output of the one he pays for
is in scope for the same reason reading his own mailbox is.

**EVERY FUNCTION IS PURE.** No I/O, no network, and - deliberately - no clock.
A shaper that read the system clock could not be pinned by a test, so the
reference date is INJECTED (``today=``, ``now=``). Omitting it yields ``None``
and a note that says why, never a guessed number. The absence of a clock call
is ASSERTED by a static sweep in tests/test_outreach.py, not merely intended.

FIVE ROUTES, TWO SUCCESS IDIOMS
-------------------------------
Captured live by ``scripts/capture_outreach.py`` into ``tests/fixtures/``,
which is where every number in this docstring was measured::

    fixture                          route                                            status
    outreach_step.json               talent/outreach/outreach-step                    "success"  (STR)
    outreach_dashboard.json          talent/outreach/get-outreach-dashboard-data      200        (INT)
    outreach_pending_jobs.json       talent/outreach/pending-jobs                     200        (INT)
    outreach_missed_followups.json   talent/outreach/missed-positive-reply-followups  200        (INT)
    outreach_tailor_activity.json    talent/outreach/agent-tailor-activity            200        (INT)

One route out of five answers with the STRING "success"; the other four answer
with the INTEGER 200. There is no third measured idiom on these five routes, so
:func:`unwrap` accepts exactly those two and REFUSES everything else loudly -
including the numeric ``1`` that ``endpoints.SUCCESS_NUMERIC`` records for a
DIFFERENT route, because accepting an unmeasured value would weaken the only
guard standing between a changed envelope and a page of confident garbage. This
API has already produced one captured envelope that contradicted a reasonable
reading of Uplers' own bundle (see ``talent_shape.my_assessments_from``), which
is why the rule is capture-then-refuse rather than shape-and-hope.

EMPTY IS NOT MISSING
--------------------
``outreach_pending_jobs.json`` carries ``"data": []``. That is a REAL answer -
the agent has nothing queued - and it must never be confused with a missing or
failed read, which raises. The distinction is load-bearing in both directions:
reporting a failed read as "nothing queued" hides a broken session, and
reporting an empty queue as a failure invents an outage.

WHAT THE CAPTURE MEASURED, AND WHAT IT REFUSES TO CLAIM
-------------------------------------------------------
*   8 positive replies came back; 7 are unseen; 7 reminder rows are waiting.
    Those are three INDEPENDENT counters. The payloads never say the 7 unseen
    are a subset of the 8 positive, so this module reports all three and
    asserts no containment.
*   ``linkedin_connected: false`` and ``linkedin_template: false`` against
    ``gmail_connected: true`` and ``gmail_template: true``: his paid agent runs
    on one of its two channels. That is surfaced as an action line, not buried
    in a flags dict.
*   ``discard_reason`` is populated on ALL 48 activity rows, including the 32
    that COMPLETED. On exactly those 32 it is the canned string in
    :data:`CANNED_DISCARD_REASON`, and on zero of the 16 Failed rows. So on a
    Completed row that field is a placeholder, not a diagnosis, and it is not
    reported as one - a canned "contact support" line presented as a cause is
    exactly the kind of confident nonsense this codebase refuses to print.
*   Two pairs of fields LOOKED like they disagreed, and neither pair did.
    RESOLVED 2026-08-24; both now surface under ``resolved`` rather than
    ``disagreements``, and the module keeps the receipts so the question cannot
    be silently re-opened.

    ``consent_email_job_scan: true`` (dashboard) against ``has_consent: false``
    (``talent/outreach/interview-list``) was a MIS-PAIRING of two different
    consents that share a field name. A third route,
    ``recommended-jobs-meta-email``, is the authoritative one - Uplers' own UI
    re-reads it the moment the consent write lands - and it AGREES with the
    dashboard: the job scan is on, granted 2026-08-12, last run 2026-08-23,
    79 jobs held. The interview-list flag belongs to the INTERVIEW scan, which
    has no reader and no shipped control anywhere in Uplers' frontend. See
    :data:`CONSENT_RESOLUTION`.

    ``auto_run: 1`` (step) against ``auto_run_consent: false`` (dashboard) was
    a MODE read against a PERMISSION. ``auto_run`` is write-only on Uplers'
    side - every occurrence in their bundle is an outbound request body,
    nothing reads it back - so what ``outreach-step`` returns is the last
    stored mode, which is why it agrees with ``outreach_mode: "auto"`` beside
    it. WHAT THE PERMISSION GATES REMAINS UNRESOLVED and is reported as such:
    it reads false while 48 runs are logged, so it plainly does not gate
    whether the agent runs, and the only route that would settle it is a write.

    A pair that measured as agreeing and later stops agreeing is raised as a
    NEW disagreement rather than absorbed by the old answer.

CONTACT DATA
------------
``missed-positive-reply-followups`` is the only route here that returns OTHER
PEOPLE. The person's NAME is the point of the whole report - "somebody at a
named company offered to forward your profile and nobody answered" is not
actionable without it - so the name is reported. Their email addresses and
LinkedIn URL are NOT: ``talent_shape.PRIVATE_KEYS`` already bins "email" as
private, and a shaped result ends up in transcripts. Nothing is dropped
silently; :data:`WITHHELD_CONTACT_KEYS` is named in the shaped output so the
reader knows the payload carried more than was printed.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from . import endpoints
from .talent import TalentError
from .talent_shape import truthy

# --- Routes -----------------------------------------------------------------
#
# ALIASES, not definitions. endpoints.py is this server's single route
# authority and carries the evidence for each one; a second spelling here would
# be a second place to update and a second place to be wrong.

ROUTE_STEP = endpoints.EP_OUTREACH_STEP
ROUTE_DASHBOARD = endpoints.EP_OUTREACH_DASHBOARD
ROUTE_PENDING = endpoints.EP_OUTREACH_PENDING
ROUTE_MISSED = endpoints.EP_OUTREACH_MISSED_FOLLOWUPS
ROUTE_ACTIVITY = endpoints.EP_OUTREACH_ACTIVITY

#: The ONLY two success idioms MEASURED on the five routes above. The string
#: belongs to outreach-step alone; the integer to the other four. Read at call
#: time, so a test can narrow it to one arm and prove the other arm was really
#: being checked rather than waved through by a truthiness test.
SUCCESS_VALUES = ("success", 200)

#: MEASURED on every one of the 32 Completed rows and on none of the 16 Failed
#: rows in ``outreach_tailor_activity.json``. A placeholder, not a diagnosis.
CANNED_DISCARD_REASON = (
    "The job was discarded for an unknown reason. "
    "Please contact support for assistance."
)

#: Present in the payload, deliberately not printed. See the module docstring.
WITHHELD_CONTACT_KEYS = (
    "contact_display",
    "contact_value",
    "employee_business_email",
    "employee_linkedin_url",
    "from_email",
    "message_full",
    "to_email",
)

#: RESOLVED 2026-08-24. This was reported for two days as a live contradiction
#: - `consent_email_job_scan: true` here against `meta.has_consent: false` on
#: `talent/outreach/interview-list` - and it was never one. The two fields are
#: DIFFERENT CONSENTS that happen to share a name, so the pairing was the bug,
#: not either value.
#:
#: How it was settled, without writing anything to his account. Static analysis
#: of Uplers' whole production bundle (`_audit/_slices/_slice-consent-semantics.md`)
#: found a THIRD route, `talent/outreach/recommended-jobs-meta-email`, which the
#: UI re-reads the instant the consent write lands and on which the whole
#: Recommended-jobs screen switches - which makes its `has_consent` the
#: platform's own state and this route's field a downstream copy. Reading it
#: live agreed with this route and added the receipts a boolean cannot carry:
#: consent granted 2026-08-12 01:32:36, scan last ran 2026-08-23 06:58:17,
#: 79 jobs held. **The scan is on, and behaving like it.**
#:
#: The interview-list flag is a different consent entirely - the INTERVIEW
#: scan, named `consent_interview_email_scan` in the same meta block, which has
#: zero readers anywhere in Uplers' frontend and whose enable/revoke UI ships
#: as CSS with no JSX behind it.
#:
#: Kept as a constant rather than deleted so a future capture cannot quietly
#: re-open a question that has been answered. `uplers_email_scan()` reads the
#: authoritative route directly.
CONSENT_RESOLUTION = {
    "field": "consent_email_job_scan",
    "verdict": "not a disagreement - two different consents, paired by mistake",
    "authoritative_route": "talent/outreach/recommended-jobs-meta-email",
    "authoritative_value": True,
    "agrees_with_this_route": True,
    "mis_paired_against": "talent/outreach/interview-list meta.has_consent",
    "mis_paired_value": False,
    "why_different": (
        "interview-list's flag is the INTERVIEW email scan "
        "(consent_interview_email_scan in the same meta block), not the job "
        "scan. It has no reader and no shipped control in Uplers' product."
    ),
    "receipt": (
        "tests/fixtures/outreach_meta_email.json, measured live 2026-08-23; "
        "_audit/_slices/_slice-consent-semantics.md"
    ),
}


class OutreachError(TalentError):
    """A payload that could not be read as the route it claims to be.

    Subclasses TalentError so every existing handler already catches it, and
    carries its own ``kind`` so a shape failure is never mistaken for a
    transport failure or an expired session.
    """

    kind = "outreach_shape"


# --- The one tolerant unwrapper -------------------------------------------


def unwrap(payload: Any, *, route: str, expect: type = dict) -> Any:
    """The ``data`` node of an outreach envelope, or raise.

    Tolerant of the two MEASURED success idioms and of nothing else. Five
    separate refusals, each naming what arrived, because a reader that guesses
    is how a shaper ends up producing rows no API ever sent:

    1.  the payload is not a JSON object at all;
    2.  it carries no ``status`` key (both idioms carry one);
    3.  its ``status`` is neither ``"success"`` nor ``200``;
    4.  it carries no ``data`` key - which is NOT "nothing to report";
    5.  its ``data`` is not the container this route was measured to send.

    ``expect`` is the container type this route sends: ``list`` for
    pending-jobs, ``dict`` for the other four. An EMPTY container of the right
    type passes, and that is the whole point of separating rule 4 from rule 5.
    """
    if not isinstance(payload, dict):
        raise OutreachError(
            "%s returned %s, not a JSON object, so nothing could be read from "
            "it." % (route, type(payload).__name__)
        )
    if "status" not in payload:
        raise OutreachError(
            "%s carried no `status` key (keys: %s). Both measured success "
            "idioms on this API carry one, so a payload without it is an "
            "envelope this reader has never seen and will not guess at."
            % (route, sorted(payload)[:12] or "none")
        )
    status = payload["status"]
    if isinstance(status, bool) or status not in SUCCESS_VALUES:
        raise OutreachError(
            "%s reported status %r. The only success idioms MEASURED on the "
            "outreach routes are the string 'success' (outreach-step) and the "
            "integer 200 (the other four); anything else is refused rather "
            "than shaped, because a wrong envelope read as a right one "
            "produces rows that look like answers." % (route, status)
        )
    if "data" not in payload:
        raise OutreachError(
            "%s carried no `data` key (keys: %s), so there is nothing to "
            "read. This is NOT 'nothing to report' - an empty result arrives "
            "as an empty container under `data`, and that case is reported as "
            "a real answer." % (route, sorted(payload)[:12] or "none")
        )
    data = payload["data"]
    if not isinstance(data, expect) or isinstance(data, bool):
        raise OutreachError(
            "%s returned `data` as %s, not %s. The captured shape for this "
            "route is %s and a different container means the route changed, "
            "not that it is empty."
            % (route, type(data).__name__, expect.__name__, expect.__name__)
        )
    return data


# --- Small readers, each doing exactly one thing --------------------------


def _flag(value: Any) -> bool | None:
    """Tri-state yes/no. ``None`` means the payload did not say, never False.

    MEASURED: ``agent-tailor-activity`` spells its booleans ``"Yes"`` / ``"No"``
    with a capital letter, which ``talent_shape.truthy`` does not accept in
    that capitalisation (its table carries lowercase ``"yes"``). Everything
    else - ``1``, ``0``, ``true``, ``false`` - is delegated rather than
    re-implemented, because a second copy of that table is how the two drift.
    """
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("yes", "y"):
            return True
        if text in ("no", "n"):
            return False
    return truthy(value)


def _int(value: Any) -> int | None:
    """An integer, or None. Never 0 as a stand-in for "the key was absent"."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _text(value: Any) -> str | None:
    """A non-empty string, or None. Numbers are stringified; junk is dropped."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _first(raw: dict, *names: str) -> Any:
    """First present, non-empty value among several candidate spellings."""
    for name in names:
        value = raw.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def _tally(values) -> dict:
    """``{value: count}``, ordered by count descending then key ascending."""
    counts: dict = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], str(pair[0]))))


def _parse_moment(value: Any) -> datetime | None:
    """An ISO-8601 stamp as a datetime, or None. Never a string comparison.

    MEASURED: ``replied_at`` and ``thread_sent_at`` carry an explicit
    ``+05:30`` offset, while ``activity_date`` carries no offset at all. Both
    are parsed here; only the offset-carrying ones are ever ORDERED or
    SUBTRACTED, because assigning a timezone to a naive stamp would be an
    assumption dressed up as a reading.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_day(value: Any) -> date | None:
    """A calendar date from ``YYYY-MM-DD`` or a full ISO stamp, or None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    moment = _parse_moment(value)
    if moment is not None:
        return moment.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _rank_by_staleness(rows: list[dict]) -> list[dict]:
    """Stalest first, on the PARSED instant carried in ``_order``.

    Rows with no orderable stamp sort LAST rather than crashing the sort or
    disappearing from it - a row this reader cannot time is still a person
    waiting for an answer.

    A named function rather than an inline sort so a control can revert it to
    ``lambda rows: rows`` and measure what the ranking is worth.
    """
    return sorted(rows, key=lambda row: (row["_order"] is None, row["_order"] or 0.0))


def _failure_reasons(rows: list[dict]) -> dict:
    """``{reason: count}`` over the FAILED rows only, ranked by count.

    The filter is the whole point. ``discard_reason`` is populated on every
    row, and on the ones that COMPLETED it is always the canned
    :data:`CANNED_DISCARD_REASON` placeholder - counting those would report 32
    phantom discards as the leading cause of failure on a run that succeeded.
    """
    failed = [row for row in rows if (_text(row.get("status_string")) or "") == "Failed"]
    return _tally(
        _text(row.get("discard_reason")) or "(no reason given)" for row in failed
    )


def _days_between(later: Any, earlier: Any) -> int | None:
    """Whole days between two calendar dates, or None if either is unreadable.

    Deliberately a DATE difference rather than a timezone-aware subtraction:
    the reference the caller injects is a day, and "3 days ago" against a
    stamp Uplers recorded in its own +05:30 day is the honest reading of it.
    """
    end = _parse_day(later)
    start = _parse_day(earlier)
    if end is None or start is None:
        return None
    return (end - start).days


# --- Shapers, one per captured route --------------------------------------


def shape_agent_plan(payload: dict, *, today: str | None = None) -> dict:
    """His entitlement and setup, from ``talent/outreach/outreach-step``.

    MEASURED (``tests/fixtures/outreach_step.json``): ``plan: 2``,
    ``outreach_mode: "auto"``, ``auto_run: 1``, ``has_plan_expired: false``,
    ``plan_end_date: "2026-09-10"``, all four setup steps true, all three
    credit counters 0. THE FINDING: ``gmail_connected`` and ``gmail_template``
    are both true while ``linkedin_connected`` and ``linkedin_template`` are
    both false, so a paid agent with two channels is running on one.

    THIS ROUTE IS THE ODD ONE OUT: its ``status`` is the STRING ``"success"``,
    where the other four outreach routes send the INTEGER 200.

    ``today`` is INJECTED, and ``days_remaining`` is ``None`` without it. A
    plan countdown computed from a clock inside the shaper could not be pinned
    by a test, and an unpinnable number on a paid subscription is worse than
    no number.
    """
    data = unwrap(payload, route=ROUTE_STEP, expect=dict)
    steps = data.get("status") if isinstance(data.get("status"), dict) else {}
    step1 = data.get("step1") if isinstance(data.get("step1"), dict) else {}
    step2 = data.get("step2") if isinstance(data.get("step2"), dict) else {}

    channels = []
    for name, connected_key, template_key in (
        ("gmail", "gmail_connected", "gmail_template"),
        ("linkedin", "linkedin_connected", "linkedin_template"),
    ):
        connected = _flag(step1.get(connected_key))
        template = _flag(step2.get(template_key))
        channels.append(
            {
                "channel": name,
                "connected": connected,
                "template": template,
                "ready": bool(connected) and bool(template),
            }
        )
    ready = [row["channel"] for row in channels if row["ready"]]
    not_ready = [row["channel"] for row in channels if not row["ready"]]

    end_date = _text(data.get("plan_end_date"))
    expired = _flag(data.get("has_plan_expired"))
    days_remaining = _days_between(end_date, today) if today else None
    if today and days_remaining is None:
        basis = "plan_end_date %r could not be parsed as a date" % end_date
    elif today:
        basis = "days from %s to plan_end_date %s" % (today, end_date)
    else:
        basis = (
            "no reference date was supplied, so no countdown is reported - "
            "pass today='YYYY-MM-DD' to get one"
        )

    notes: list[str] = []
    if not_ready:
        detail = ", ".join(
            "%s (connected=%r, template=%r)"
            % (row["channel"], row["connected"], row["template"])
            for row in channels
            if not row["ready"]
        )
        notes.append(
            "The paid agent has %d of its %d outreach channels live: %s. Not "
            "live: %s. Every contact reachable only on a dead channel is a "
            "contact this agent cannot reach at all."
            % (len(ready), len(channels), ", ".join(ready) or "none", detail)
        )
    if expired is False and days_remaining is not None:
        notes.append(
            "Plan %s runs to %s, %d days from %s."
            % (data.get("plan"), end_date, days_remaining, today)
        )
    missing_steps = sorted(key for key, value in steps.items() if not _flag(value))
    if missing_steps:
        notes.append(
            "Uplers reports %d setup step(s) incomplete: %s."
            % (len(missing_steps), ", ".join(missing_steps))
        )

    return {
        "route": ROUTE_STEP,
        "plan": _int(data.get("plan")),
        "outreach_mode": _text(data.get("outreach_mode")),
        "auto_run": _flag(data.get("auto_run")),
        "auto_run_raw": data.get("auto_run"),
        "plan_expired": expired,
        "plan_end_date": end_date,
        "days_remaining": days_remaining,
        "days_remaining_basis": basis,
        "credits": {
            "added": _int(data.get("credit_added")),
            "left": _int(data.get("credit_left")),
            "plan": _int(data.get("credit_plan")),
        },
        "setup_steps": {key: _flag(value) for key, value in sorted(steps.items())},
        "setup_complete": bool(steps) and all(_flag(value) for value in steps.values()),
        "channels": channels,
        "channels_ready": ready,
        "channels_not_ready": not_ready,
        # Carried verbatim and read by nothing. Their meaning is not documented
        # anywhere this server can see, so deriving from them would be invention.
        "unread_fields": {
            "all_over_status": data.get("all_over_status"),
            "conversion_offer": data.get("conversion_offer"),
        },
        "notes": notes,
    }


def shape_agent_dashboard(payload: dict) -> dict:
    """The agent's counters, from ``get-outreach-dashboard-data``.

    MEASURED (``tests/fixtures/outreach_dashboard.json``): ``total_jobs_run:
    48``, ``total_positive_replies: 8``, ``total_unseen_replies: 7``,
    ``reminder_count: 7``, ``total_tailored_resumes: 0``, ``today_agent_runs:
    0``, ``jobs_in_queue: 0``, ``max_limit: 8``, ``interview_count: 0``,
    ``pending_interview_feedback_count: 0``.

    THREE INDEPENDENT COUNTERS, NO CONTAINMENT CLAIMED. 8 positive and 7 unseen
    are two different counters on the same payload; the payload never says the
    7 are among the 8, so neither does this function.

    ``max_limit: 8`` is carried verbatim. Uplers caps something at 8 and this
    server has not measured what, so it is reported as Uplers' own number
    rather than described as a daily quota.

    THE CONSENT LINE is emitted here, and which list it lands in depends on
    what this payload says. ``consent_email_job_scan`` was measured AGREEING
    with the authoritative route (``recommended-jobs-meta-email``), so it
    normally reports under ``resolved`` - see :data:`CONSENT_RESOLUTION` for
    how that was settled without writing anything. If this copy ever flips away
    from the authoritative value it becomes a real ``disagreement``, because
    two routes that were measured agreeing and then stopped is a new fact, not
    the old question coming back.
    """
    data = unwrap(payload, route=ROUTE_DASHBOARD, expect=dict)

    positive = _int(data.get("total_positive_replies"))
    unseen = _int(data.get("total_unseen_replies"))
    reminders = _int(data.get("reminder_count"))
    consent_scan = _flag(data.get("consent_email_job_scan"))

    # No disagreement is emitted for the consent any more - see
    # :data:`CONSENT_RESOLUTION` for how it was settled. What IS emitted is the
    # resolution itself, and only when this route still agrees with the
    # authoritative one. If this field ever flips away from it, that is a NEW
    # and genuine disagreement between two routes that were measured agreeing,
    # so it is raised as one rather than being absorbed by the old answer.
    disagreements: list[dict] = []
    resolved: list[dict] = []
    if consent_scan is None:
        pass
    elif consent_scan == CONSENT_RESOLUTION["authoritative_value"]:
        resolved.append(dict(CONSENT_RESOLUTION, this_route_value=consent_scan))
    else:
        disagreements.append(
            {
                "field": "consent_email_job_scan",
                "this_route": ROUTE_DASHBOARD,
                "this_value": consent_scan,
                "other_source": CONSENT_RESOLUTION["authoritative_route"],
                "other_value": CONSENT_RESOLUTION["authoritative_value"],
                "receipt": CONSENT_RESOLUTION["receipt"],
                "note": (
                    "This route now disagrees with the AUTHORITATIVE consent "
                    "route, which is new: on 2026-08-23 they agreed. Trust "
                    "uplers_email_scan(), which reads the authoritative one "
                    "directly, and treat this copy as stale."
                ),
            }
        )

    notes: list[str] = []
    if positive is not None and unseen is not None:
        notes.append(
            "%d positive replies and %d unseen replies are two INDEPENDENT "
            "counters on this payload. It does not say the %d unseen are among "
            "the %d positive, so that is not claimed here."
            % (positive, unseen, unseen, positive)
        )
    if unseen and reminders is not None and unseen == reminders:
        notes.append(
            "The unseen-reply counter and the reminder counter both read %d, "
            "which is agreement between two counters, not proof they count the "
            "same rows." % unseen
        )
    notes.append(
        "max_limit is Uplers' own cap field and reads %r. What it caps has not "
        "been measured by this server, so it is not described as a quota."
        % data.get("max_limit")
    )

    return {
        "route": ROUTE_DASHBOARD,
        "runs": {
            "total_jobs_run": _int(data.get("total_jobs_run")),
            "today_agent_runs": _int(data.get("today_agent_runs")),
            "jobs_in_queue": _int(data.get("jobs_in_queue")),
            "max_limit": _int(data.get("max_limit")),
        },
        "replies": {
            "positive": positive,
            "unseen": unseen,
            "reminders": reminders,
        },
        "tailoring": {"tailored_resumes": _int(data.get("total_tailored_resumes"))},
        "interviews": {
            "count": _int(data.get("interview_count")),
            "pending_feedback": _int(data.get("pending_interview_feedback_count")),
        },
        "flags": {
            "agent_pref_fields_submitted": _flag(
                data.get("agent_pref_fields_submitted")
            ),
            "auto_run_consent": _flag(data.get("auto_run_consent")),
            "consent_email_job_scan": consent_scan,
            # Uplers' own spelling is `has_submitted_happpy_feedback`, with
            # three p's. Recorded here so the source key stays findable.
            "happy_feedback_submitted": _flag(
                data.get("has_submitted_happpy_feedback")
            ),
        },
        "disagreements": disagreements,
        "resolved": resolved,
        "notes": notes,
    }


def shape_pending_jobs(payload: dict) -> dict:
    """What the agent has queued, from ``talent/outreach/pending-jobs``.

    MEASURED (``tests/fixtures/outreach_pending_jobs.json``): ``data`` is the
    EMPTY LIST, under ``status: 200``. That is a real answer - the agent has
    nothing queued - and this function reports it as one. A missing ``data``
    key, or a ``data`` that is not a list, RAISES instead, because "the read
    failed" and "the queue is empty" are opposite facts that would otherwise
    render identically.

    ROW SHAPE IS UNVERIFIED and says so. No non-empty capture of this route
    exists, so the per-row projection below tries the spellings its sibling
    routes use and reports ``fields_seen`` for every row - what actually
    arrived, not what was hoped for. ``row_shape_verified`` is False until a
    non-empty capture lands in the fixtures.
    """
    rows = unwrap(payload, route=ROUTE_PENDING, expect=list)
    dict_rows = [row for row in rows if isinstance(row, dict)]

    jobs = [
        {
            "company": _text(_first(row, "company_name", "company", "CompanyName")),
            "title": _text(_first(row, "job_title", "title", "RequestForTalent")),
            "hr_number": _text(_first(row, "HR_Number", "hr_number")),
            "status": _text(_first(row, "status_string", "status")),
            "fields_seen": sorted(row),
        }
        for row in dict_rows
    ]

    notes: list[str] = []
    if not rows:
        notes.append(
            "The queue is EMPTY: Uplers returned an empty list under a success "
            "status. That is a real answer - the agent has nothing queued right "
            "now - and not a failed read. A failed or shape-changed read raises "
            "instead of arriving here."
        )
    else:
        notes.append(
            "No non-empty capture of this route exists in tests/fixtures, so "
            "the per-row field names below are the sibling routes' spellings "
            "tried against a shape nobody has measured. `fields_seen` reports "
            "what each row actually carried; re-run scripts/capture_outreach.py "
            "while the queue is non-empty to pin it."
        )
    dropped = len(rows) - len(dict_rows)
    if dropped:
        notes.append(
            "%d of %d queue entries were not JSON objects and could not be "
            "read. They are counted in `count` and absent from `jobs`."
            % (dropped, len(rows))
        )

    return {
        "route": ROUTE_PENDING,
        "count": len(rows),
        "queue_empty": not rows,
        "jobs": jobs,
        "row_shape_verified": False,
        "notes": notes,
    }


def shape_missed_followups(payload: dict, *, now: str | None = None) -> dict:
    """The replies nobody answered, STALEST FIRST. The point of the module.

    MEASURED (``tests/fixtures/outreach_missed_followups.json``): ``count: 7``
    over ``days: 15``, seven rows, every one of them arriving over Gmail. Each
    row names a human, a company, a job title and Uplers' own
    ``reply_category`` - and those categories are the reason this matters:
    "Forwarding profile to hiring manager", "Referral submitted", "Willing to
    refer; requests updated resume". People offered to help and nobody wrote
    back.

    RANKED BY PARSED TIME, NEVER BY STRING. ``replied_at`` carries a ``+05:30``
    offset, so it is parsed to an aware datetime and ordered on that. The
    captured list arrives NEWEST first, so a correct ranking genuinely reverses
    it - a string sort or a no-op would put the freshest reply at the top and
    bury the twelve-day-old one.

    ``now`` is INJECTED. Without it, ``age_days`` is ``None`` on every row and
    the ranking still holds, because ordering needs no reference date and a
    staleness NUMBER does.

    Rows whose ``replied_at`` cannot be parsed are ranked LAST and named in the
    notes. They are never dropped: a row this reader cannot time is still a
    person waiting for an answer.
    """
    data = unwrap(payload, route=ROUTE_MISSED, expect=dict)
    raw_rows = data.get("rows")
    if not isinstance(raw_rows, list):
        raise OutreachError(
            "%s returned no `data.rows` array (data keys: %s), so the missed "
            "follow-ups could not be read. This is NOT 'nothing is waiting'."
            % (ROUTE_MISSED, sorted(data)[:12] or "none")
        )

    shaped: list[dict] = []
    unreadable: list[str] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        replied_at = _text(row.get("replied_at"))
        moment = _parse_moment(replied_at)
        ordered = moment is not None and moment.tzinfo is not None
        company = _text(row.get("company_name"))
        if not ordered:
            unreadable.append(
                "%s / %s (replied_at=%r)"
                % (company or "unknown company", _text(row.get("job_title")) or "?",
                   replied_at)
            )
        shaped.append(
            {
                "company": company,
                "job_title": _text(row.get("job_title")),
                "contact_name": _text(row.get("employee_name")),
                "reply_category": _text(row.get("reply_category")),
                "reply_summary": _text(row.get("reply_summary")),
                "replied_at": replied_at,
                "age_days": _days_between(now, replied_at) if now else None,
                "via": _text(row.get("medium_label")) or _text(row.get("medium")),
                "thread_subject": _text(row.get("thread_subject")),
                "thread_sent_at": _text(row.get("thread_sent_at")),
                "gmail_thread_id": _text(row.get("gmail_thread_id")),
                "_order": moment.timestamp() if ordered else None,
            }
        )

    shaped = _rank_by_staleness(shaped)
    for row in shaped:
        del row["_order"]

    reported = _int(data.get("count"))
    window_days = _int(data.get("days"))

    notes: list[str] = []
    if reported is not None and reported != len(shaped):
        notes.append(
            "Uplers reported count=%d but %d readable rows arrived. Both "
            "numbers are printed; neither is corrected into the other."
            % (reported, len(shaped))
        )
    if shaped:
        oldest = shaped[0]
        if oldest["age_days"] is not None:
            notes.append(
                "The oldest unanswered positive reply has been waiting %d days "
                "(%s at %s: %r)."
                % (oldest["age_days"], oldest["contact_name"], oldest["company"],
                   oldest["reply_category"])
            )
        else:
            notes.append(
                "Ranked stalest-first. No reference date was supplied, so no "
                "row carries an age in days - pass now='YYYY-MM-DD' for that."
            )
        channels = _tally(row["via"] for row in shaped)
        notes.append(
            "Every one of these replies arrived over: %s."
            % ", ".join("%s (%d)" % (name, count) for name, count in channels.items())
        )
    if unreadable:
        notes.append(
            "%d row(s) carry a `replied_at` this reader could not parse as an "
            "offset-bearing timestamp and are ranked last, not dropped: %s."
            % (len(unreadable), "; ".join(unreadable))
        )
    notes.append(
        "Contact routes are withheld from this shape by policy and are present "
        "in the raw payload: %s. The person's NAME is reported because the "
        "report is useless without it." % ", ".join(WITHHELD_CONTACT_KEYS)
    )

    return {
        "route": ROUTE_MISSED,
        "count_reported": reported,
        "rows_read": len(shaped),
        "window_days": window_days,
        "window_days_meaning": (
            "Uplers' own `days` field, sent alongside the list. What window it "
            "describes is Uplers' definition and has not been measured here."
        ),
        "rows": shaped,
        "withheld_fields": list(WITHHELD_CONTACT_KEYS),
        "notes": notes,
    }


def shape_activity(payload: dict) -> dict:
    """What the agent actually ran, from ``agent-tailor-activity``.

    MEASURED (``tests/fixtures/outreach_tailor_activity.json``): ``total: 48``,
    ``page: 1``, ``limit: 50``, 48 rows over 42 distinct companies between
    2026-08-01 17:49:24 and 2026-08-21 11:41:24. Status splits 32 Completed /
    16 Failed. ``used_agent`` is "Yes" on all 48 and ``used_tailor`` is "No" on
    all 48 - every run was the agent's, and not one resume was tailored, which
    independently confirms the dashboard's ``total_tailored_resumes: 0``.

    THE CANNED-REASON TRAP. ``discard_reason`` is non-empty on all 48 rows,
    including the 32 that COMPLETED, and on those 32 it is always the same
    canned "unknown reason - contact support" string. It appears on ZERO Failed
    rows. So on a Completed row it is a placeholder, and presenting it as a
    diagnosis would be inventing a failure that did not happen.
    ``failure_reasons`` is therefore built from FAILED ROWS ONLY, and the canned
    string is counted separately in ``canned_reason_rows``.

    The four real failure reasons, ranked, are Uplers' own words and are passed
    through verbatim so the reader can see what the platform actually said.
    """
    data = unwrap(payload, route=ROUTE_ACTIVITY, expect=dict)
    raw_rows = data.get("list")
    if not isinstance(raw_rows, list):
        raise OutreachError(
            "%s returned no `data.list` array (data keys: %s), so the agent's "
            "activity could not be read. This is NOT 'the agent has done "
            "nothing'." % (ROUTE_ACTIVITY, sorted(data)[:12] or "none")
        )
    rows = [row for row in raw_rows if isinstance(row, dict)]

    statuses = [_text(row.get("status_string")) or "unknown" for row in rows]
    agent_flags = [_flag(row.get("used_agent")) for row in rows]
    tailor_flags = [_flag(row.get("used_tailor")) for row in rows]
    labels = [_text(row.get("label")) or "unknown" for row in rows]
    sources = [
        _text((row.get("row") or {}).get("source")) or "unknown"
        if isinstance(row.get("row"), dict)
        else "unknown"
        for row in rows
    ]
    stamps = sorted(
        stamp for stamp in (_text(row.get("activity_date")) for row in rows) if stamp
    )

    failed = [row for row in rows if (_text(row.get("status_string")) or "") == "Failed"]
    reasons = _failure_reasons(rows)
    canned_rows = sum(
        1 for row in rows if _text(row.get("discard_reason")) == CANNED_DISCARD_REASON
    )
    canned_on_failed = sum(
        1 for row in failed if _text(row.get("discard_reason")) == CANNED_DISCARD_REASON
    )

    total_reported = _int(data.get("total"))
    completed = statuses.count("Completed")

    notes: list[str] = []
    if total_reported is not None and total_reported != len(rows):
        notes.append(
            "Uplers reported total=%d but %d rows arrived on this page "
            "(page=%r, limit=%r). Both numbers are printed; neither is "
            "corrected into the other."
            % (total_reported, len(rows), data.get("page"), data.get("limit"))
        )
    if canned_rows:
        notes.append(
            "`discard_reason` carries the canned 'unknown reason - contact "
            "support' string on %d of %d rows, %d of them on rows whose status "
            "is Failed. On a row that COMPLETED it is a placeholder, not a "
            "diagnosis, so it is excluded from `failure_reasons` and is not "
            "presented as a cause of anything."
            % (canned_rows, len(rows), canned_on_failed)
        )
    if failed:
        top_reason, top_count = next(iter(reasons.items()))
        notes.append(
            "%d of %d runs failed. The largest single reason accounts for %d of "
            "them, in Uplers' own words: %s"
            % (len(failed), len(rows), top_count, top_reason)
        )
    if rows and all(flag is True for flag in agent_flags):
        notes.append(
            "All %d rows are agent runs (used_agent=Yes); none was a manual "
            "application through this surface." % len(rows)
        )
    if rows and all(flag is False for flag in tailor_flags):
        notes.append(
            "Not one of the %d runs used the resume tailor (used_tailor=No on "
            "every row), which independently agrees with the dashboard's "
            "total_tailored_resumes." % len(rows)
        )

    return {
        "route": ROUTE_ACTIVITY,
        "total_reported": total_reported,
        "rows_read": len(rows),
        "page": _int(data.get("page")),
        "limit": _int(data.get("limit")),
        "filters": data.get("filters") if isinstance(data.get("filters"), dict) else {},
        "by_status": _tally(statuses),
        "by_agent": {
            "agent_run": sum(1 for flag in agent_flags if flag is True),
            "manual": sum(1 for flag in agent_flags if flag is False),
            "unstated": sum(1 for flag in agent_flags if flag is None),
        },
        "by_tailor": {
            "tailored": sum(1 for flag in tailor_flags if flag is True),
            "not_tailored": sum(1 for flag in tailor_flags if flag is False),
            "unstated": sum(1 for flag in tailor_flags if flag is None),
        },
        "by_label": _tally(labels),
        "by_source": _tally(sources),
        "completed": completed,
        "failed": len(failed),
        "failure_reasons": [
            {"reason": reason, "count": count} for reason, count in reasons.items()
        ],
        "canned_reason_rows": canned_rows,
        "companies": len({_text(row.get("company_name")) for row in rows} - {None}),
        "first_activity": stamps[0] if stamps else None,
        "last_activity": stamps[-1] if stamps else None,
        "activity_stamps_carry_offset": False,
        "notes": notes,
    }


# --- The read-through -----------------------------------------------------


def _require_shape(value: Any, *, name: str, route: str) -> dict:
    """One shaped dict, proven to be the one this slot wants.

    Guards the swap: five shaped dicts of similar shape are easy to pass in the
    wrong order, and a swapped pair would otherwise be reported as a real read
    of somebody's account.
    """
    if not isinstance(value, dict):
        raise OutreachError(
            "agent_readthrough got %s for `%s`, not a shaped dict. Pass the "
            "output of the matching shape_* function."
            % (type(value).__name__, name)
        )
    seen = value.get("route")
    if seen != route:
        raise OutreachError(
            "agent_readthrough got a shape from route %r for `%s`, which must "
            "carry %r. The five inputs are not interchangeable."
            % (seen, name, route)
        )
    return value


def _cross_check(claim: str, **values: Any) -> dict:
    """One agreement test across independently-reported numbers.

    Counters that are absent are listed as unknown rather than folded in as
    zero: a missing counter agrees with nothing.
    """
    known = {name: value for name, value in values.items() if value is not None}
    return {
        "claim": claim,
        "values": dict(sorted(values.items())),
        "agree": len(set(known.values())) <= 1,
        "unknown": sorted(name for name in values if name not in known),
    }


def agent_readthrough(*, plan, dashboard, pending, missed, activity) -> dict:
    """The one report a human reads. Takes the five ALREADY-SHAPED dicts.

    Pure, and assembles nothing it was not given: every number below comes out
    of one of the five shapes, which each came out of one captured fixture.

    THE HEADLINE IS THE UNANSWERED POSITIVE REPLIES, first key in the returned
    dict and first thing in `headline`, because that is the finding: real
    people at named companies offered to forward a profile and the offers went
    unanswered while a paid agent kept running.

    SECOND is the dead channel. ``linkedin`` is not connected and has no
    template, and Uplers' own failure text on the activity log names LinkedIn
    on some of the failed runs. Both halves come from the payloads; the line is
    only emitted when both are true.

    DISAGREEMENTS ARE REPORTED, NOT RESOLVED. ``auto_run`` (step) against
    ``auto_run_consent`` (dashboard) is assembled here because it is the only
    place both payloads are in scope, and the consent disagreement carried up
    from the dashboard shape rides along with it.
    """
    plan = _require_shape(plan, name="plan", route=ROUTE_STEP)
    dashboard = _require_shape(dashboard, name="dashboard", route=ROUTE_DASHBOARD)
    pending = _require_shape(pending, name="pending", route=ROUTE_PENDING)
    missed = _require_shape(missed, name="missed", route=ROUTE_MISSED)
    activity = _require_shape(activity, name="activity", route=ROUTE_ACTIVITY)

    replies = dashboard.get("replies", {})
    runs = dashboard.get("runs", {})
    positive = replies.get("positive")
    unseen = replies.get("unseen")
    rows = missed.get("rows", [])
    oldest = rows[0] if rows else None

    # --- headline -------------------------------------------------------
    parts = []
    if positive is not None and unseen is not None:
        parts.append(
            "%d positive replies came back and %d are unseen." % (positive, unseen)
        )
    if rows:
        parts.append("%d reply threads are waiting on an answer." % len(rows))
    if oldest:
        if oldest.get("age_days") is not None:
            when = "waiting %d days" % oldest["age_days"]
        else:
            when = "replied %s" % (oldest.get("replied_at") or "at an unknown time")
        parts.append(
            "Oldest: %s at %s, %s - %s."
            % (
                oldest.get("contact_name") or "an unnamed contact",
                oldest.get("company") or "an unnamed company",
                when,
                oldest.get("reply_category") or "no category given",
            )
        )
    headline = " ".join(parts) or "No reply counters were readable in these payloads."

    # --- the dead channel ------------------------------------------------
    not_ready = plan.get("channels_not_ready", [])
    blamed = [
        entry
        for entry in activity.get("failure_reasons", [])
        if any(name in (entry.get("reason") or "").lower() for name in not_ready)
    ]
    blamed_count = sum(entry["count"] for entry in blamed)
    channel_action = None
    if not_ready:
        channel_action = (
            "Outreach channels live: %d of %d (%s). Not live: %s."
            % (
                len(plan.get("channels_ready", [])),
                len(plan.get("channels", [])),
                ", ".join(plan.get("channels_ready", [])) or "none",
                ", ".join(not_ready),
            )
        )
        if blamed_count:
            channel_action += (
                " Uplers' own failure text names it on %d of the %d failed runs."
                % (blamed_count, activity.get("failed") or 0)
            )

    # --- cross-checks ----------------------------------------------------
    cross_checks = [
        _cross_check(
            "jobs the agent has run",
            dashboard_total_jobs_run=runs.get("total_jobs_run"),
            activity_total_reported=activity.get("total_reported"),
            activity_rows_read=activity.get("rows_read"),
        ),
        _cross_check(
            "replies waiting on an answer",
            dashboard_reminder_count=replies.get("reminders"),
            missed_count_reported=missed.get("count_reported"),
            missed_rows_read=missed.get("rows_read"),
        ),
        _cross_check(
            "resumes tailored",
            dashboard_total_tailored=dashboard.get("tailoring", {}).get(
                "tailored_resumes"
            ),
            activity_rows_using_tailor=activity.get("by_tailor", {}).get("tailored"),
        ),
        _cross_check(
            "jobs queued",
            dashboard_jobs_in_queue=runs.get("jobs_in_queue"),
            pending_rows=pending.get("count"),
        ),
    ]

    # --- disagreements ---------------------------------------------------
    disagreements = list(dashboard.get("disagreements", []))
    resolved = list(dashboard.get("resolved", []))
    auto_run = plan.get("auto_run")
    auto_consent = dashboard.get("flags", {}).get("auto_run_consent")
    if auto_run is not None and auto_consent is not None and auto_run != auto_consent:
        # ALSO A MIS-PAIRING, resolved 2026-08-24 by the same bundle analysis,
        # but resolved LESS COMPLETELY than the consent one, and the difference
        # is stated rather than smoothed over.
        #
        # What was settled: these are not two readings of one quantity.
        # `auto_run` is WRITE-ONLY on Uplers' side - all eight of its
        # occurrences in their bundle are the same `store-recommended-jobs`
        # request body, and nothing reads it back - so what `outreach-step`
        # returns is the MODE last stored, which is why it agrees with
        # `outreach_mode: "auto"` sitting beside it. `auto_run_consent` is the
        # PERMISSION, and it is the field their Configure-screen toggle binds
        # its checked state to. A mode and a permission can differ without
        # either being wrong.
        #
        # What was NOT settled, and is not claimed: what the permission
        # actually gates. The agent has 48 logged runs while the permission
        # reads false, so it plainly does not gate "does the agent run at all".
        # A client bundle cannot show what a server enforces, and the only
        # route that would answer it is a WRITE. So this stays reported.
        resolved.append(
            {
                "field": "auto_run",
                "verdict": (
                    "not a disagreement - a stored MODE and a PERMISSION, "
                    "paired by mistake"
                ),
                "mode_route": ROUTE_STEP,
                "mode_value": auto_run,
                "mode_raw": plan.get("auto_run_raw"),
                "permission_source": "%s auto_run_consent" % ROUTE_DASHBOARD,
                "permission_value": auto_consent,
                "still_unresolved": (
                    "What auto_run_consent gates. It reads false while 48 runs "
                    "are logged, so it does not gate whether the agent runs. "
                    "Settling it needs a write to his account, which is not "
                    "worth doing to answer a question nothing depends on."
                ),
                "receipt": (
                    "tests/fixtures/outreach_step.json, "
                    "tests/fixtures/outreach_dashboard.json; "
                    "_audit/_slices/_slice-consent-semantics.md"
                ),
            }
        )
    for check in cross_checks:
        if not check["agree"]:
            disagreements.append(
                {
                    "field": check["claim"],
                    "values": check["values"],
                    "note": (
                        "Counters that should describe the same thing do not "
                        "match. All of them are printed; none is chosen."
                    ),
                }
            )

    # --- actions ---------------------------------------------------------
    actions: list[str] = []
    if rows:
        if oldest and oldest.get("age_days") is not None:
            actions.append(
                "Answer %d positive replies that are still unanswered; the "
                "oldest has waited %d days." % (len(rows), oldest["age_days"])
            )
        else:
            actions.append(
                "Answer %d positive replies that are still unanswered." % len(rows)
            )
    if channel_action:
        actions.append(channel_action)
    if runs.get("jobs_in_queue") == 0 and runs.get("today_agent_runs") == 0:
        tail = ""
        if plan.get("days_remaining") is not None:
            tail = " %d days remain on plan %s (ends %s)." % (
                plan["days_remaining"],
                plan.get("plan"),
                plan.get("plan_end_date"),
            )
        actions.append(
            "The agent has 0 jobs queued and made 0 runs today; its most recent "
            "logged activity is %s.%s"
            % (activity.get("last_activity") or "unknown", tail)
        )
    if disagreements:
        actions.append(
            "Resolve %d reported disagreement(s) between fields before trusting "
            "either side of them." % len(disagreements)
        )

    return {
        "headline": headline,
        "needs_reply": {
            "positive_replies": positive,
            "unseen_replies": unseen,
            "waiting": len(rows),
            "window_days": missed.get("window_days"),
            "oldest_age_days": oldest.get("age_days") if oldest else None,
            "rows": rows,
        },
        "channels": {
            "ready": plan.get("channels_ready", []),
            "not_ready": not_ready,
            "detail": plan.get("channels", []),
            "action": channel_action,
            "failures_naming_a_dead_channel": blamed_count,
        },
        "agent_activity": {
            "runs_logged": activity.get("rows_read"),
            "completed": activity.get("completed"),
            "failed": activity.get("failed"),
            "companies": activity.get("companies"),
            "first_activity": activity.get("first_activity"),
            "last_activity": activity.get("last_activity"),
            "failure_reasons": activity.get("failure_reasons", []),
            "tailored_resumes": dashboard.get("tailoring", {}).get("tailored_resumes"),
        },
        "queue": {
            "jobs_in_queue": runs.get("jobs_in_queue"),
            "pending_rows": pending.get("count"),
            "today_agent_runs": runs.get("today_agent_runs"),
            "max_limit": runs.get("max_limit"),
        },
        "plan": {
            "plan": plan.get("plan"),
            "outreach_mode": plan.get("outreach_mode"),
            "expired": plan.get("plan_expired"),
            "end_date": plan.get("plan_end_date"),
            "days_remaining": plan.get("days_remaining"),
            "days_remaining_basis": plan.get("days_remaining_basis"),
            "setup_complete": plan.get("setup_complete"),
        },
        "interviews": dashboard.get("interviews", {}),
        "actions": actions,
        "cross_checks": cross_checks,
        "disagreements": disagreements,
        "resolved": resolved,
        "notes": (
            list(plan.get("notes", []))
            + list(dashboard.get("notes", []))
            + list(pending.get("notes", []))
            + list(missed.get("notes", []))
            + list(activity.get("notes", []))
        ),
    }
