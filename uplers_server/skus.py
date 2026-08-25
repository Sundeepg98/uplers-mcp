"""The paid candidate SKUs, read back: the resume health check and the tailor.

The ring outside :mod:`uplers_server.agent_surface`. That module reports the
outreach agent's settings; this one reports the two OTHER products on his
account - Uplers' resume health check and its resume tailor - which until now
this server refused to read at all.

WHY THIS MODULE EXISTS AT ALL, since the refusal was explicit
--------------------------------------------------------------
``uplers_server_info``'s ``out_of_scope_by_design`` refused
``talent/resume-health-check/*`` and ``talent/tailor/*`` as "Uplers' own PAID
candidate products", and added a concrete second reason: wrapping them "would
produce tools that fail at runtime" because the account holds zero tailor
credits. That reasoning was sound and its conclusion was HALF WRONG, which is
why the refusal is narrowed rather than deleted.

MEASURED LIVE 2026-08-25 on his own session: all three routes below answered
**HTTP 200 with real data. Zero 403s, zero 402s, no credit gate anywhere on the
read side.** A credit balance gates BUYING a tailored resume; it does not gate
reading the health check he has already had or the plan he already holds. What
stays refused is every ORDERING, TRANSFORMING and REFUNDING route in both
namespaces - ``talent/tailor/order/create``, ``order/capture``,
``refund-request`` - and those keep no constant in :mod:`endpoints`, on the
rule that file already applies to the one-way outreach routes: a constant is an
invitation to call it.

**A READER, AND NOTHING ELSE.** No POST, no PUT, no DELETE, no write path, not
even a disabled one. Two independent reasons that line is load-bearing here.
The namespace: ``get-last-health-check`` sits under ``talent/outreach/*``, one
path segment from ``consent-email-job-scan``. And the COMMERCE:
``talent/tailor/*`` is where the order and refund routes live, so a typo in
this module would not be a failed read, it would be a charge.

**EVERY FUNCTION IS PURE.** No I/O, no network, no clock. The shapers take a
payload and return a dict; ``server.py`` does the fetching. Same discipline as
:mod:`uplers_server.outreach` and :mod:`uplers_server.agent_surface`, and for
the same reason: a shaper that reached the network could not be pinned by a
fixture.

THREE ROUTES, ONE IDIOM - MEASURED, NOT INFERRED
-------------------------------------------------
Captured live by ``scripts/capture_skus.py``, which is where every number in
this module's docstrings was measured::

    fixture                           route                          status
    sku_health_check_last.json        outreach/get-last-health-check 200 (INT)
    sku_health_check_dashboard.json   resume-health-check/dashboard  200 (INT)
    sku_tailor_list.json              tailor/list                    200 (INT)

All three answer the INTEGER. None of them is the string-``"success"`` odd one
out that ``get-message-templates`` turned out to be, and that is stated as a
measurement per route rather than as a pattern, because the last time this
server inferred the idiom from a pattern the pattern was wrong.
:func:`uplers_server.outreach.unwrap` already accepts exactly those two idioms
and refuses everything else, so it is imported rather than reimplemented.

THE REPORT BODY IS NEVER RETURNED
----------------------------------
``get-last-health-check`` carries a ``report_details`` node that is Uplers'
scoring report on his resume. MEASURED: it holds his name, it states his city
outright, and its per-check commentary QUOTES HIS RESUME BACK VERBATIM - whole
bullets naming his employers, his metrics and his projects. This module does
not return it, on exactly the register ``uplers_agent_settings`` already set
for the outreach templates: report that the artifact EXISTS and its metadata,
never the body.

``scripts/capture_skus.py`` does not keep it either, so no fixture pins it and
no shaper here can read it even by accident. THE COST IS STATED RATHER THAN
GLOSSED: the per-section breakdown - the ``check`` / ``points_earned`` /
``red_flag`` triple on each of the twelve checks, including the one measured
red flag - goes with the container. It is not prose and it was not dangerous;
it is lost because the container it lives in is. :data:`UNSURFACED` names it so
a later slice can decide to reach it deliberately instead of rediscovering it.

FILE ADDRESSES ARE DROPPED, ON THE RULE THAT A LINK IS A CREDENTIAL
-------------------------------------------------------------------
``aws_file_name`` is the object-storage name of his resume and
``google_doc_urls`` is a list of links to the transformed copy. Neither is
returned by anything here and neither reaches a fixture. ``file_name``,
``base_resume`` and ``base_resume_text`` go with them for a plainer reason:
on this account a resume filename carries his name.

The caller-visible consequence, stated because a silent omission is
indistinguishable from an oversight: **the rows this module returns have no
name on them.** A health-check row is identified by its date and its score, and
that is enough for the history it exists to report, because no per-row route is
built and nothing here needs a handle to address one.

ABSENT IS NOT ZERO, AND IT IS NOT FALSE
----------------------------------------
Every scalar goes through :func:`uplers_server.outreach._int`,
``_flag`` or ``_text``, all of which answer ``None`` for a key that was not
sent. "He scored 0" and "we did not get a score" are opposite facts about his
account, and so are "his plan is inactive" and "the payload did not say".
``tests/test_skus.py`` holds a control per tool that was watched failing with
the shaper rendering absent as zero.

The verdict field needed one extra distinction on top of that, and it is
MEASURED rather than defensive. ``final_verdict`` is present on every row and
is the EMPTY STRING on all four places it appears - so "Uplers sent no verdict
text" and "the key was missing" would both collapse onto ``None``. They are
different facts, so :func:`verdict_state` reports which one happened.
"""

from __future__ import annotations

from typing import Any

from . import endpoints, outreach
from .outreach import OutreachError, unwrap

# --- Routes -----------------------------------------------------------------
#
# ALIASES, not definitions. endpoints.py is this server's single route
# authority and carries the live-verification evidence for each one.

ROUTE_HEALTH_CHECK_LAST = endpoints.EP_SKU_HEALTH_CHECK_LAST
ROUTE_HEALTH_CHECK_DASHBOARD = endpoints.EP_SKU_HEALTH_CHECK_DASHBOARD
ROUTE_TAILOR_LIST = endpoints.EP_SKU_TAILOR_LIST

# BORROWED, NOT COPIED - the same call agent_surface.py made and for the same
# reason. These already exist, already have their own tests, and already carry
# the quirks they were written for (`_int` refuses to return 0 for an absent
# key; `_flag` knows about capital-Y "Yes"). Two copies of a coercion table
# drift, and the drift is invisible until a payload lands in the gap.
_flag = outreach._flag
_int = outreach._int
_text = outreach._text
_cross_check = outreach._cross_check

#: Present in the payloads, deliberately never returned. Named in the shaped
#: output so a reader knows the route carried more than was printed, which is
#: the convention `agent_surface.WITHHELD_BODY_KEYS` set.
WITHHELD_KEYS = (
    "report_details",
    "aws_file_name",
    "google_doc_urls",
    "file_name",
    "base_resume",
    "base_resume_text",
    "file_id",
)

#: WHY EACH ONE IS WITHHELD, in the tool output rather than only here, because
#: the person who needs this sentence is the one reading a result and wondering
#: where the filename went.
WITHHELD_REASON = (
    "report_details is Uplers' scoring report on the resume: it carries his "
    "name, states his city, and quotes whole resume bullets back verbatim. "
    "aws_file_name and google_doc_urls are addresses that resolve to his "
    "document, so they are treated as bearer credentials and dropped. "
    "file_name, base_resume and base_resume_text are resume filenames, which "
    "on this account carry his name. None of them reaches a fixture either."
)

#: MEASURED AND REACHABLE, deliberately NOT surfaced - recorded so a later
#: slice reaches it on purpose rather than rediscovering it.
#:
#: `report_details.sections` holds twelve named checks across four groups
#: (content, format, mandatory_sections, style), each with `check`,
#: `points_earned` and `red_flag`. Those three are not prose and would be
#: genuinely useful: MEASURED 2026-08-25, exactly ONE check carries
#: `red_flag: true` - `format.long_bullet_points`, scoring 0 points. It is
#: unavailable here because the capture drops the whole `report_details`
#: container rather than enumerating its prose leaves, and no shaper may read a
#: field no fixture pins. Reaching it needs a trail-scoped redaction rule in
#: `scripts/capture_outreach.py` first, not a change in this module.
UNSURFACED = (
    "report_details.sections: 12 per-check {check, points_earned, red_flag} "
    "triples, one of which was measured red (format.long_bullet_points). "
    "Dropped with its container at capture time; see uplers_server/skus.py.",
)


def _require(value: Any, *, name: str, route: str) -> dict:
    """One shaped dict, proven to be the one this slot wants.

    The same guard :func:`uplers_server.outreach._require_shape` applies to the
    readthrough, and here for the same reason: :func:`resume_health` takes two
    shaped dicts that both describe health checks and both carry scores, so a
    swapped pair would render as a real read of his account rather than as an
    error.
    """
    if not isinstance(value, dict):
        raise OutreachError(
            "resume_health got %s for `%s`, not a shaped dict. Pass the output "
            "of the matching shape_* function." % (type(value).__name__, name)
        )
    seen = value.get("route")
    if seen != route:
        raise OutreachError(
            "resume_health got a shape from route %r for `%s`, which must "
            "carry %r. The two inputs are not interchangeable."
            % (seen, name, route)
        )
    return value


def verdict_state(raw: Any, key: str = "final_verdict") -> str:
    """``"absent"``, ``"empty"`` or ``"present"`` for a verdict field.

    THE ONE PLACE THIS MODULE NEEDS MORE THAN TRI-STATE ``None``, and it is a
    measurement rather than a precaution. ``_text`` answers ``None`` both for a
    key that was never sent and for the empty string, and on this route those
    are different facts: MEASURED 2026-08-25, ``final_verdict`` is PRESENT and
    EMPTY on all four places it appears - the last check and all three history
    rows. So Uplers ran the check, scored it 89, and shipped no verdict text.
    Reporting that as "no verdict" would be right; reporting it as "we could
    not read the verdict" would be wrong, and ``None`` alone cannot tell them
    apart.
    """
    if not isinstance(raw, dict) or key not in raw:
        return "absent"
    return "empty" if _text(raw.get(key)) is None else "present"


# --- Shapers, one per captured route ---------------------------------------


def shape_last_health_check(payload: dict) -> dict:
    """Current health-check state, from ``get-last-health-check``.

    MEASURED (``tests/fixtures/sku_health_check_last.json``):
    ``is_eligible: false``, ``is_paid: false``, ``total_attempts: 5``,
    ``user_attempts: 3``, ``resume_healthchecked: true``,
    ``current_profile_cv_healthchecked: false``, and a last check scoring
    **89** with ``status: 3`` and an empty ``final_verdict``.

    THE TWO COUNTERS ARE REPORTED UNDER UPLERS' OWN NAMES AND ONE READING IS
    OFFERED, NOT ASSERTED. ``user_attempts`` is the SPENT one - that is not a
    guess, it is corroborated from a second route in :func:`resume_health`,
    where the dashboard's ``total_resume_health_check`` and its actual row
    count both read 3 as well. ``total_attempts`` reading 5 is then most
    naturally the cap, and it is NOT called one here: no route in this API said
    so, and the arithmetic it invites is contradicted by the account itself.

    THE CONTRADICTION IS PRINTED RATHER THAN RESOLVED. 5 minus 3 leaves 2
    unspent, and ``is_eligible`` reads FALSE. Both are facts about his account
    on the same payload and this server does not know which governs -
    ``is_paid: false`` is the obvious candidate and is a hypothesis, not a
    measurement. So the subtraction ships under the name
    ``unspent_by_arithmetic``, which says what it is, beside
    ``eligible_now: false``, which disagrees with it.

    ``status: 3`` and the transform's ``status: 0`` are UNLABELLED ENUMS. No
    legend was measured anywhere - not in a payload, not in the bundle - so the
    integers are passed through under names that mark them as codes and no
    meaning is attached to either.

    THE REPORT BODY IS NEVER RETURNED. See the module docstring.
    """
    data = unwrap(payload, route=ROUTE_HEALTH_CHECK_LAST, expect=dict)

    check = data.get("health_check")
    check = check if isinstance(check, dict) else {}
    transform = data.get("transform")
    transform = transform if isinstance(transform, dict) else {}

    used = _int(data.get("user_attempts"))
    cap = _int(data.get("total_attempts"))
    eligible = _flag(data.get("is_eligible"))

    notes = [
        "user_attempts is the SPENT counter. Corroborated on a second route - "
        "see the cross-check in the assembled report - not inferred from its "
        "name.",
        "total_attempts is NOT called an entitlement here. No route in this "
        "API says it is one, and the subtraction it invites is contradicted by "
        "is_eligible on the same payload.",
        "status and transform.status_code are unlabelled integers. No legend "
        "was measured, so none is attached.",
    ]
    if eligible is False and (used is not None and cap is not None and cap > used):
        notes.append(
            "DISAGREEMENT, printed rather than resolved: %d of %d attempts are "
            "unspent by arithmetic, yet is_eligible reads false. is_paid reads "
            "%r, which is a candidate explanation and not a measured one."
            % (cap - used, cap, _flag(data.get("is_paid")))
        )

    return {
        "route": ROUTE_HEALTH_CHECK_LAST,
        "attempts": {
            "used": used,
            "total": cap,
            # Subtraction, and named as such. Only when BOTH are known: a
            # missing counter makes the difference unknowable, never zero.
            "unspent_by_arithmetic": (
                cap - used if (used is not None and cap is not None) else None
            ),
            "eligible_now": eligible,
        },
        "paid": _flag(data.get("is_paid")),
        "resume_healthchecked": _flag(data.get("resume_healthchecked")),
        "current_profile_cv_healthchecked": _flag(
            data.get("current_profile_cv_healthchecked")
        ),
        "last_check": {
            "present": bool(check),
            "resume_score": _int(check.get("resume_score")),
            "final_verdict": _text(check.get("final_verdict")),
            "final_verdict_state": verdict_state(check),
            "status_code": _int(check.get("status")),
            "created_at": _text(check.get("created_at")),
            "report_body_withheld": True,
        },
        "transform": {
            "present": bool(transform),
            "status_code": _int(transform.get("status")),
            "version": _int(transform.get("version")),
            "resume_updated": _flag(transform.get("is_resume_updated")),
            "created_at": _text(transform.get("created_at")),
            "transformation_id": _int(transform.get("resume_transformation_id")),
            # Existence only. The list itself is a set of links that resolve to
            # his document, so it is dropped at capture time and never counted
            # from a value this module has - `absent` and `empty` are told
            # apart the same way the verdict is.
            "google_docs_state": (
                "withheld_present"
                if transform.get("google_doc_urls")
                else "withheld_or_absent"
            ),
        },
        "withheld": list(WITHHELD_KEYS),
        "withheld_reason": WITHHELD_REASON,
        "notes": notes,
    }


def shape_health_check_dashboard(payload: dict) -> dict:
    """Health-check HISTORY, from ``resume-health-check/dashboard``.

    MEASURED (``tests/fixtures/sku_health_check_dashboard.json``):
    ``total_resume_health_check: 3``, ``total_resume_transformed: 0``,
    ``health_check`` a list of 3 rows scoring **89, 89 and 87**, and
    ``transformed`` the EMPTY LIST.

    THE EMPTY ``transformed`` LIST IS A REAL ANSWER AND IS REPORTED AS ONE.
    It agrees with ``total_resume_transformed: 0`` from the same payload and
    with ``transform_status: 0`` on all three rows: he has run the health check
    three times and has never taken a transformed resume from it. That is a
    three-way agreement on one payload, so it is reported as an agreement
    rather than as three separate numbers.

    ROWS CARRY NO FILENAME. See the module docstring: a row is identified by
    its date and its score, which is what a history needs.

    ``health_check_status`` and ``transform_status`` are the same unlabelled
    integers the sibling route sends, and get the same treatment - passed
    through as codes with no meaning attached.
    """
    data = unwrap(payload, route=ROUTE_HEALTH_CHECK_DASHBOARD, expect=dict)

    raw_rows = data.get("health_check")
    raw_rows = raw_rows if isinstance(raw_rows, list) else []
    raw_transformed = data.get("transformed")
    raw_transformed = raw_transformed if isinstance(raw_transformed, list) else []

    rows = [_history_row(row) for row in raw_rows if isinstance(row, dict)]
    scores = [row["resume_score"] for row in rows if row["resume_score"] is not None]

    return {
        "route": ROUTE_HEALTH_CHECK_DASHBOARD,
        "checks_reported": _int(data.get("total_resume_health_check")),
        "transforms_reported": _int(data.get("total_resume_transformed")),
        "rows": rows,
        "rows_returned": len(rows),
        "transformed_rows_returned": len(raw_transformed),
        "score_range": (
            {"lowest": min(scores), "highest": max(scores), "scored_rows": len(scores)}
            if scores
            else None
        ),
        "transforms_agreement": _cross_check(
            "no transformed resume has ever been taken",
            total_resume_transformed=_int(data.get("total_resume_transformed")),
            transformed_rows_returned=len(raw_transformed),
            rows_with_a_finished_transform=sum(
                1 for row in rows if row["transform_status_code"] not in (None, 0)
            ),
        ),
        "withheld": list(WITHHELD_KEYS),
        "notes": [
            "Rows carry no filename by design - see uplers_server/skus.py. A "
            "row is its date and its score.",
            "health_check_status and transform_status are unlabelled integers. "
            "No legend was measured, so none is attached.",
        ],
    }


def _history_row(raw: dict) -> dict:
    """One dashboard row. Absent stays absent on every field."""
    return {
        "created_at": _text(raw.get("created_at")),
        "resume_score": _int(raw.get("resume_score")),
        "final_verdict": _text(raw.get("final_verdict")),
        "final_verdict_state": verdict_state(raw),
        "status_code": _int(raw.get("health_check_status")),
        "transform_status_code": _int(raw.get("transform_status")),
        "transform_created_at": _text(raw.get("transform_created_at")),
        "transformation_id": _int(raw.get("resume_transformation_id")),
        "has_uplers": _flag(raw.get("has_uplers")),
        "file_name_withheld": True,
    }


def resume_health(*, last: dict, dashboard: dict) -> dict:
    """The two health-check routes as one report. Takes ALREADY-SHAPED dicts.

    Pure, and assembles nothing it was not given.

    WHY ONE TOOL READS TWO ROUTES. They answer the same question from opposite
    sides - ``get-last-health-check`` is the CURRENT state and
    ``resume-health-check/dashboard`` is the HISTORY - and a caller should not
    have to know that Uplers split them. More than convenience, the pair is
    what makes one number readable: ``user_attempts: 3`` on the first route is
    identifiable as the SPENT counter only because the second route
    independently reports 3 checks and returns exactly 3 rows. One route alone
    would have left "used" and "entitled" as a coin flip between two integers.

    THE CROSS-CHECK IS COMPUTED, NOT ASSERTED. If the three ever stop agreeing
    the report says so rather than picking one, which is the same rule
    ``agent_surface`` applies to Uplers' two disagreeing job counters.

    Nothing here is a recommendation. Every line is a state of his account.
    """
    last = _require(last, name="last", route=ROUTE_HEALTH_CHECK_LAST)
    dashboard = _require(
        dashboard, name="dashboard", route=ROUTE_HEALTH_CHECK_DASHBOARD
    )

    attempts = last.get("attempts", {})
    used = attempts.get("used")

    spent_agreement = _cross_check(
        "user_attempts is the number of checks already spent",
        user_attempts=used,
        total_resume_health_check=dashboard.get("checks_reported"),
        history_rows_returned=dashboard.get("rows_returned"),
    )

    headline: list[str] = []

    score = last.get("last_check", {}).get("resume_score")
    if score is not None:
        headline.append("Latest resume health check scored %d." % score)
    if last.get("last_check", {}).get("final_verdict_state") == "empty":
        headline.append(
            "Uplers shipped NO verdict text with it - final_verdict is present "
            "and empty, which is not the same as this server failing to read "
            "one."
        )

    if used is not None and attempts.get("total") is not None:
        headline.append(
            "%d of %d attempts used." % (used, attempts.get("total"))
        )
    if attempts.get("eligible_now") is False:
        headline.append(
            "is_eligible reads FALSE, so another check is not currently "
            "offered - regardless of what the two counters subtract to."
        )

    if dashboard.get("transforms_reported") == 0:
        headline.append(
            "No transformed resume has ever been taken (0 transforms, 0 rows "
            "in the transformed list)."
        )

    if not spent_agreement["agree"]:
        headline.append(
            "THE TWO ROUTES DISAGREE about how many checks were run: %r. "
            "Neither is picked." % spent_agreement["values"]
        )

    return {
        "headline": headline,
        "current": last,
        "history": dashboard,
        "spent_agreement": spent_agreement,
        "reads_only": True,
        "withheld": list(WITHHELD_KEYS),
        "withheld_reason": WITHHELD_REASON,
        "unsurfaced": list(UNSURFACED),
        "notes": [
            "Two GETs, no writes. Nothing here orders, buys, transforms or "
            "refunds anything; those routes are refused and have no constant "
            "in endpoints.py.",
            "Every line above is a state of the account, not a recommendation.",
        ],
    }


def shape_tailor_list(payload: dict) -> dict:
    """Tailored resumes and the tailor plan, from ``talent/tailor/list``.

    MEASURED (``tests/fixtures/sku_tailor_list.json``):
    ``total_tailored_resumes: 0``, ``total_records: 1``, one row in
    ``resumes_list``, and a ``plan_details`` reading ``plan_active: 0``,
    ``remaining_days: 0``, ``plan_type: 4``, ``status: 2`` against a
    ``plan_end_date`` of ``2026-08-11``.

    THE TRAP ON THIS ROUTE IS ``total_records``, AND IT IS THE WHOLE REASON
    THIS SHAPER IS CAREFUL. It reads 1 while ``total_tailored_resumes`` reads
    0, so a reader that treated the row count as the tailored count would
    report a tailored resume that does not exist. MEASURED on the single row:
    ``list_type: "source"``, ``tailored_resume: null``,
    ``tailored_resume_id: null``, ``hr_number: null``. It is a BASE resume
    registered as tailoring INPUT, not a tailored output. So the two counts are
    kept apart by name and the row is classified from its own fields rather
    than from its presence in the list.

    THREE INDEPENDENT FIELDS SAY THE PLAN IS OVER - ``plan_active: 0``,
    ``remaining_days: 0``, and an end date in the past - and they are reported
    as an agreement rather than as one conclusion. This module has no clock, so
    the date is passed through and never compared to today: a shaper that
    reached for the current time could not be pinned by a fixture, and "expired"
    would then mean something different on every run.

    ``plan_type`` and ``status`` are UNLABELLED ENUMS, like the health check's.
    Worth one specific note: ``talent/outreach/agent-plans`` catalogues plan ids
    1 and 3 only, and this reads ``plan_type: 4``, so it is NOT a lookup into
    that catalogue and is not treated as one.

    Filenames are withheld - see the module docstring.
    """
    data = unwrap(payload, route=ROUTE_TAILOR_LIST, expect=dict)

    raw_rows = data.get("resumes_list")
    raw_rows = raw_rows if isinstance(raw_rows, list) else []
    rows = [_tailor_row(row) for row in raw_rows if isinstance(row, dict)]
    tailored_rows = [row for row in rows if row["is_tailored"]]

    plan_raw = data.get("plan_details")
    plan_raw = plan_raw if isinstance(plan_raw, dict) else {}
    plan = {
        "present": bool(plan_raw),
        "active": _flag(plan_raw.get("plan_active")),
        "remaining_days": _int(plan_raw.get("remaining_days")),
        "plan_type_code": _int(plan_raw.get("plan_type")),
        "status_code": _int(plan_raw.get("status")),
        "plan_end_date": _text(plan_raw.get("plan_end_date")),
        "temp_plan_end_date": _text(plan_raw.get("temp_plan_end_date")),
        "created_at": _text(plan_raw.get("created_at")),
        "updated_at": _text(plan_raw.get("updated_at")),
        # Existence, not the handle. `None` really is what the live payload
        # sends, so "no transaction is recorded" is a measured answer.
        "has_transaction": plan_raw.get("talent_transaction_id") is not None,
    }

    tailored_reported = _int(data.get("total_tailored_resumes"))

    headline: list[str] = []
    if tailored_reported == 0 and not tailored_rows:
        headline.append(
            "NO tailored resume exists. total_tailored_resumes reads 0 and no "
            "row in the list carries a tailored output - two independent "
            "readings of the same payload agreeing."
        )
    if rows and not tailored_rows:
        headline.append(
            "total_records reads %r, but every row is a SOURCE row - a base "
            "resume registered as tailoring input, not a tailored result. The "
            "row count is not the tailored count."
            % _int(data.get("total_records"))
        )
    if plan["active"] is False:
        headline.append(
            "The tailor plan is INACTIVE: plan_active 0, remaining_days %r, "
            "plan_end_date %r. This module has no clock and does not compare "
            "that date to today."
            % (plan["remaining_days"], plan["plan_end_date"])
        )

    return {
        "route": ROUTE_TAILOR_LIST,
        "headline": headline,
        "tailored_resumes_reported": tailored_reported,
        "rows_reported": _int(data.get("total_records")),
        "rows_returned": len(rows),
        "tailored_rows_returned": len(tailored_rows),
        "rows": rows,
        "plan": plan,
        "plan_over_agreement": _cross_check(
            "the tailor plan is no longer running",
            # Both rendered as 0/1 so they are comparable at all; either being
            # absent leaves the claim unknown rather than agreed.
            plan_inactive=(None if plan["active"] is None else int(not plan["active"])),
            no_days_remaining=(
                None
                if plan["remaining_days"] is None
                else int(plan["remaining_days"] <= 0)
            ),
        ),
        "reads_only": True,
        "withheld": list(WITHHELD_KEYS),
        "withheld_reason": WITHHELD_REASON,
        "notes": [
            "One GET, no writes. talent/tailor/order/create, order/capture and "
            "refund-request are refused and have no constant in endpoints.py - "
            "nothing here can buy, order or refund anything.",
            "plan_type and status are unlabelled integers. plan_type reads 4 "
            "and talent/outreach/agent-plans catalogues only ids 1 and 3, so "
            "this is NOT an index into that catalogue.",
            "Every line above is a state of the account, not a recommendation.",
        ],
    }


def _tailor_row(raw: dict) -> dict:
    """One ``resumes_list`` row. Classified from its own fields.

    ``is_tailored`` is computed from ``tailored_resume_id`` rather than from
    the row being in the list, which is the distinction the route's own
    ``total_records`` / ``total_tailored_resumes`` split turns on.
    """
    return {
        "list_type": _text(raw.get("list_type")),
        "is_tailored": raw.get("tailored_resume_id") is not None,
        "tailored_for_hr_number": _text(raw.get("hr_number")),
        "status_code": _int(raw.get("status")),
        "source_type_code": _int(raw.get("source_type")),
        "last_updated_at": _text(raw.get("last_updated_at")),
        "file_name_withheld": True,
    }
