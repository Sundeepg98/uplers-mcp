"""The agent's OWN settings and the mailbox scan behind it, read back.

The ring outside :mod:`uplers_server.outreach`. That module reports what his
paid agent HAS DONE; this one reports the machinery that decides what it does
next - the Gmail scan that feeds it, the jobs that scan found, and the four
settings surfaces (follow-up, templates, auto-reply, blocklist) that until now
were visible only by opening Uplers' own screens in a browser.

**A READER, AND NOTHING ELSE.** No POST, no DELETE, no PUT, no write path, not
even a disabled one. That line matters more here than almost anywhere else in
this server: every route below lives under ``talent/outreach/*``, and one path
segment away sit ``consent-email-job-scan`` (POST grants, DELETE revokes what
Uplers reads out of his mailbox) and ``consent-auto-run``. A typo in this
module would not be a failed read; it would be an unrequested change to his
account. ``tests/test_agent_surface.py`` measures the requests that actually
left rather than trusting this paragraph.

**EVERY FUNCTION IS PURE.** No I/O, no network, no clock. The shapers take a
payload and return a dict; server.py does the fetching. Same discipline as
:mod:`uplers_server.outreach`, and for the same reason: a shaper that reached
the network could not be pinned by a fixture.

SIX ROUTES, TWO SUCCESS IDIOMS, AND THE SPLIT IS NOT WHERE YOU WOULD GUESS
--------------------------------------------------------------------------
Captured live 2026-08-23 by ``scripts/capture_agent_surface.py``, which is
where every number in this module's docstrings was measured::

    fixture                            route                            status
    outreach_meta_email.json           recommended-jobs-meta-email      200  (INT)
    outreach_scanned_jobs.json         recommended-jobs-email           200  (INT)
    outreach_settings_followup.json    settings/followup                200  (INT)
    outreach_disabled_companies.json   settings/disabled-companies      200  (INT)
    outreach_auto_reply.json           get-auto-reply                   200  (INT)
    outreach_templates.json            get-message-templates       "success" (STR)

One route in six answers with the STRING. It is not the oldest, not the
newest, and not the odd one out by any other visible property - which is
exactly why the idiom is MEASURED per route and never inferred from a pattern.
:func:`uplers_server.outreach.unwrap` already accepts those two and refuses
everything else, so it is imported rather than reimplemented; a second
unwrapper would be a second thing to keep in step and a second thing to be
wrong.

THE CONSENT FINDING, WHICH OVERTURNED WHAT THIS SERVER BELIEVED
---------------------------------------------------------------
``recommended-jobs-meta-email -> has_consent`` is the AUTHORITATIVE state of
the Gmail job-scan consent. Established by static analysis of Uplers' own
frontend bundle (``_audit/_slices/_slice-consent-semantics.md``, chunk 3474):
this is the route the UI re-reads the instant the consent write lands, and its
``has_consent`` is what the entire Recommended-jobs screen switches on. The two
other readings of "consent" in this codebase are NOT peers of it:

*   ``get-outreach-dashboard-data -> consent_email_job_scan`` is a DOWNSTREAM
    COPY of the same fact.
*   ``talent/outreach/interview-list -> meta.has_consent`` is a DIFFERENT
    CONSENT despite the identical field name - the INTERVIEW scan, whose UI
    Uplers designed (the CSS ships) but never built. No shipped code reads it,
    so it cannot be authoritative for anything the platform does.

:mod:`uplers_server.outreach` reports those last two as an unresolved
disagreement, which was the honest position on the evidence available when it
was written. It is now resolved, and this is where the resolution lives.

TWO PLACES A NUMBER COULD HAVE BEEN INVENTED, AND WAS NOT
----------------------------------------------------------
*   **Uplers' own two counters disagree.** ``best_for_you_count`` reads 50
    while ``best_for_you_breakdown`` sums to 51. Both are reported, the
    disagreement is named, and neither is picked or averaged. Picking one
    would be a fabricated answer about his own account, and averaging two
    integers that are both meant to be a count is worse than either.
*   **The scanned jobs are NOT SCORED, and that is a promise being kept.**
    This server's fit scores come from jobcore, shared with the Naukri server,
    so a score means the same thing on both. MEASURED across all 79 captured
    rows: ``skills`` is the empty list on 79/79, ``city`` is empty on 79/79,
    ``HR_Number`` is null on 79/79, ``enc_id`` is empty on 79/79, and
    ``description`` is the same placeholder string on 79/79. There is nothing
    to score. A number computed from an empty skill set would still print as a
    number, and a reader has no way to tell that one apart from a real one -
    which is precisely how a shared scale stops meaning anything.

BODIES ARE NEVER RETURNED
--------------------------
``gmail_template`` is a multi-paragraph self-description carrying his employer
history, his LinkedIn URL and his notice period. The live route returns it;
this module does not, and reports the SUBJECT and the fact of existence
instead - which is what a reader needs to answer "is the template set up".
``message_gmail`` and ``message_linkedin`` on the follow-up route are the same
kind of thing and are withheld on the same grounds, even though they are
shorter. Nothing is dropped silently: :data:`WITHHELD_BODY_KEYS` is named in
the shaped output so a reader knows the payload carried more than was printed.
"""

from __future__ import annotations

from typing import Any

from . import endpoints, outreach
from .outreach import OutreachError, unwrap

# --- Routes -----------------------------------------------------------------
#
# ALIASES, not definitions. endpoints.py is this server's single route
# authority and carries the live-verification evidence for each one.

ROUTE_META_EMAIL = endpoints.EP_OUTREACH_META_EMAIL
ROUTE_SCANNED_JOBS = endpoints.EP_OUTREACH_SCANNED_JOBS
ROUTE_FOLLOWUP = endpoints.EP_OUTREACH_SETTINGS_FOLLOWUP
ROUTE_DISABLED_COMPANIES = endpoints.EP_OUTREACH_DISABLED_COMPANIES
ROUTE_AUTO_REPLY = endpoints.EP_OUTREACH_AUTO_REPLY
ROUTE_TEMPLATES = endpoints.EP_OUTREACH_TEMPLATES

# BORROWED, NOT COPIED. These four already exist in outreach.py, already have
# their own tests, and already carry the quirks they were written for (`_flag`
# knows about capital-Y "Yes"; `_int` refuses to return 0 for an absent key).
# A private-name import is uglier than a copy and much safer than one: two
# copies of a coercion table drift, and the drift is invisible until a payload
# lands in the gap between them.
_flag = outreach._flag
_int = outreach._int
_text = outreach._text

#: The two channels every settings route below is keyed by. Uplers spells them
#: as suffixes (`interval_days_gmail`, `disabled_followup_linkedin`), so the
#: channel list is the loop variable rather than a hand-written pair of blocks.
CHANNELS = ("gmail", "linkedin")

#: Present in the payloads, deliberately never returned. See the module
#: docstring. Named in the shaped output so the omission is visible.
WITHHELD_BODY_KEYS = (
    "gmail_template",
    "linkedin_template",
    "message_gmail",
    "message_linkedin",
)

#: Also present and also not returned. `gmail_email` is his own mailbox
#: address; whether a mailbox is CONNECTED is the fact a reader needs, and the
#: address itself would only ever be printed into a transcript.
WITHHELD_IDENTITY_KEYS = ("gmail_email",)

#: MEASURED on all 79 captured rows of `recommended-jobs-email`. Uplers sends
#: this string in the `description` slot for every scanned job, so a reader
#: that treated `description` as present would be reporting a placeholder as
#: job text.
PLACEHOLDER_DESCRIPTION = (
    "Job description not available, You click on job link to view the description"
)

#: Why a scanned job carries no fit score. Shipped IN the tool output rather
#: than only living in a docstring, because the person who needs this sentence
#: is the one reading a result and wondering where the scores went.
NO_SCORE_REASON = (
    "Not scored, deliberately. Fit scores in this server come from jobcore and "
    "mean the same thing as on the Naukri server, and these rows carry no "
    "skills, no location and no description - only a placeholder line telling "
    "you to open the link. A score computed from that would be a number with "
    "nothing behind it, indistinguishable on sight from a real one. Open the "
    "apply_url, or score the same role from the Uplers board where the "
    "requisition has real fields."
)

#: The receipt for the consent claim, carried into the output so the claim
#: travels with its evidence instead of arriving as an assertion.
CONSENT_AUTHORITY = {
    "authoritative_field": "has_consent",
    "route": ROUTE_META_EMAIL,
    "established_by": (
        "static analysis of Uplers' frontend bundle, chunk 3474 - this is the "
        "route the UI re-reads immediately after the consent write lands, and "
        "has_consent is what the Recommended-jobs screen switches on"
    ),
    "receipt": "_audit/_slices/_slice-consent-semantics.md",
    "downstream_copy": (
        "get-outreach-dashboard-data -> consent_email_job_scan reports the "
        "same fact second-hand"
    ),
    "different_consent": (
        "talent/outreach/interview-list -> meta.has_consent is the INTERVIEW "
        "scan, not this one, despite the identical field name. Its UI was "
        "designed and never shipped, so no shipped code reads it."
    ),
}


class AgentSurfaceRefused(OutreachError):
    """An argument this module will not send, because it was never measured.

    Subclasses OutreachError - and so TalentError - so existing handlers catch
    it, while its own ``kind`` keeps "you asked for something unmeasured" from
    being read as "the payload was malformed".
    """

    kind = "agent_surface_refused"


# --- Query building ---------------------------------------------------------


def scanned_jobs_params(best_for_you: bool | None) -> dict | None:
    """The query for ``recommended-jobs-email``, or None for the whole list.

    TWO MODES MEASURED, 2026-08-23: unset returned 79 rows and ``true``
    returned 51. Those are the only two this function will build.

    ``False`` IS REFUSED rather than sent. It looks like the obvious third
    mode, and it may well work, but "may well work" is the exact standard this
    module exists to not meet - and the cost of guessing wrong is not a bad
    result, it is a bad result that looks fine. The refusal names the way to
    get the same rows honestly: fetch the whole list, which INCLUDES the
    non-best rows (28 of the 79 carried ``best_for_you: false``), and filter it
    here where the filtering is visible.

    The value is the STRING ``"true"``, matching both the live capture and the
    spelling every other tool in this server sends (``uplers_my_interviews``
    sends ``detailed=true`` the same way). A Python ``True`` would serialise as
    ``True`` with a capital T, which is not what was measured.
    """
    if best_for_you is None:
        return None
    if best_for_you is False:
        raise AgentSurfaceRefused(
            "best_for_you=False was never measured on %s and is not sent. Two "
            "modes were measured live on 2026-08-23: unset -> 79 rows, and "
            "true -> 51. Call this with best_for_you unset - the full list "
            "carries the non-best rows too (28 of the 79 read "
            "best_for_you: false) - and filter them here, where you can see "
            "the filtering happen." % ROUTE_SCANNED_JOBS
        )
    return {"best_for_you": "true"}


# --- Small readers ----------------------------------------------------------


def _sum_breakdown(raw: Any) -> int | None:
    """Total of a per-board breakdown, or None if it is not one.

    None rather than 0 for a missing breakdown: a total of zero is a real
    answer (no board found anything) and must not be spelled the same way as
    "there was no breakdown to add up".
    """
    if not isinstance(raw, dict) or not raw:
        return None
    total = 0
    for value in raw.values():
        number = _int(value)
        if number is None:
            return None
        total += number
    return total


def _board_counts(raw: Any) -> dict:
    """A per-board breakdown as ``{board: count}``, dropping unreadable rows."""
    if not isinstance(raw, dict):
        return {}
    counts = {}
    for board, value in raw.items():
        number = _int(value)
        if number is not None:
            counts[str(board)] = number
    return dict(sorted(counts.items()))


def _require(value: Any, *, name: str, route: str) -> dict:
    """One shaped dict, proven to be the one this slot wants.

    The same guard :func:`outreach._require_shape` applies to the readthrough,
    and here for the same reason: :func:`agent_settings` takes four shaped
    dicts of similar shape, and a swapped pair would render as a real read of
    his account rather than as an error.
    """
    if not isinstance(value, dict):
        raise OutreachError(
            "agent_settings got %s for `%s`, not a shaped dict. Pass the "
            "output of the matching shape_* function." % (type(value).__name__, name)
        )
    seen = value.get("route")
    if seen != route:
        raise OutreachError(
            "agent_settings got a shape from route %r for `%s`, which must "
            "carry %r. The four inputs are not interchangeable." % (seen, name, route)
        )
    return value


# --- Shapers, one per captured route ---------------------------------------


def shape_email_scan(payload: dict) -> dict:
    """The Gmail job scan's state, from ``recommended-jobs-meta-email``.

    MEASURED (``tests/fixtures/outreach_meta_email.json``): ``has_consent:
    true``, ``consent_email_job_scan: "2026-08-12 01:32:36"``,
    ``gmail_connected: true``, ``last_job_scan: "2026-08-23 06:58:17"``,
    ``job_function_id: 3`` / ``job_function_name: "Full Stack Development"``,
    ``total_jobs: 79``, ``best_for_you_count: 50``, and a
    ``best_for_you_breakdown`` whose only non-zero board is ``linkedin: 51``.

    ``has_consent`` HERE IS THE AUTHORITATIVE ANSWER to "is the scan on", and
    the receipt travels with it in :data:`CONSENT_AUTHORITY`. See the module
    docstring for what the two lookalike fields on other routes actually are.

    ``consent_email_job_scan`` IS A TIMESTAMP ON THIS ROUTE, not the boolean
    the dashboard reports under the identical key. It is surfaced as the GRANT
    TIME. Coercing it to a bool would throw away the only record this account
    has of WHEN he turned the scan on, and would do it invisibly, because
    ``bool("2026-08-12 01:32:36")`` is ``True`` and so is the right answer for
    the wrong reason.

    THE TWO COUNTERS ARE BOTH REPORTED. ``best_for_you_count`` and the sum of
    ``best_for_you_breakdown`` disagree by one, and the disagreement is emitted
    only when it actually exists - a future capture where they agree drops the
    line by itself.
    """
    data = unwrap(payload, route=ROUTE_META_EMAIL, expect=dict)

    granted_raw = data.get("consent_email_job_scan")
    granted_at = _text(granted_raw) if isinstance(granted_raw, str) else None

    count = _int(data.get("best_for_you_count"))
    breakdown_best = _board_counts(data.get("best_for_you_breakdown"))
    breakdown_total = _sum_breakdown(data.get("best_for_you_breakdown"))

    disagreements: list[dict] = []
    if count is not None and breakdown_total is not None and count != breakdown_total:
        disagreements.append(
            {
                "field": "best_for_you",
                "route": ROUTE_META_EMAIL,
                "best_for_you_count": count,
                "best_for_you_breakdown_total": breakdown_total,
                "breakdown": breakdown_best,
                "note": (
                    "Uplers' own two counters for the same set disagree by %d "
                    "on one payload: the scalar says %d and its own per-board "
                    "breakdown adds up to %d. Both are reported. Neither is "
                    "picked and they are not averaged - which one is right has "
                    "not been measured, and an average of two counts would be "
                    "a third number nobody sent."
                    % (abs(count - breakdown_total), count, breakdown_total)
                ),
            }
        )

    notes: list[str] = []
    if granted_at is not None:
        notes.append(
            "consent_email_job_scan on THIS route is a timestamp (%r), not the "
            "boolean the dashboard route reports under the same key. It is "
            "reported above as consent_granted_at." % granted_at
        )
    elif granted_raw is not None:
        notes.append(
            "consent_email_job_scan arrived as %r (%s). The captured shape for "
            "this route is a timestamp STRING, so the grant time is reported "
            "as unknown rather than guessed from this value."
            % (granted_raw, type(granted_raw).__name__)
        )
    notes.append(
        "The mailbox address (gmail_email) is in the payload and is not "
        "returned; whether a mailbox is connected is the fact, and the address "
        "would only ever be printed into a transcript."
    )

    return {
        "route": ROUTE_META_EMAIL,
        "scan": {
            "enabled": _flag(data.get("has_consent")),
            "consent_granted_at": granted_at,
            "last_run_at": _text(data.get("last_job_scan")),
            "job_function": {
                "id": _int(data.get("job_function_id")),
                "name": _text(data.get("job_function_name")),
            },
        },
        "mailbox": {
            "connected": _flag(data.get("gmail_connected")),
            "address_withheld": True,
        },
        "jobs": {
            "total": _int(data.get("total_jobs")),
            "breakdown": _board_counts(data.get("breakdown")),
        },
        "best_for_you": {
            "count": count,
            "breakdown": breakdown_best,
            "breakdown_total": breakdown_total,
            "counters_agree": (
                None
                if count is None or breakdown_total is None
                else count == breakdown_total
            ),
        },
        "consent_authority": dict(CONSENT_AUTHORITY),
        "withheld": list(WITHHELD_IDENTITY_KEYS),
        "disagreements": disagreements,
        "notes": notes,
    }


def shape_scanned_jobs(payload: dict, *, limit: int = 25) -> dict:
    """The jobs the mailbox scan found, from ``recommended-jobs-email``.

    MEASURED (``tests/fixtures/outreach_scanned_jobs.json``): 79 rows, every
    one of them ``job_board: "linkedin"`` and ``is_aggregator_job: true``; 51
    carry ``best_for_you: true``.

    THIS ROUTE PUTS ITS METADATA OUTSIDE ``data``. ``last_job_scan``,
    ``breakdown`` and ``plan`` are SIBLINGS of ``data``, not children of it -
    the only route in this ring shaped that way - so this function reads the
    whole envelope rather than just the unwrapped node. A shaper that only
    looked inside ``data`` would silently report no scan time.

    ``limit`` TRUNCATES THIS FUNCTION'S OUTPUT AND NOTHING ELSE. The route has
    no working limit of its own: a ``limit=3`` against its sibling
    ``get-recommended-jobs`` came back with all 97 rows. So the full list is
    always fetched and always counted, and the truncation is named in a note -
    "showing 25 of 79" is a different statement from "there are 25".

    NO FIT SCORE IS COMPUTED HERE, and :data:`NO_SCORE_REASON` ships in the
    output saying why. The emptiness that reason rests on is RE-DERIVED from
    the payload on every call (``rows_with_skills``, ``rows_with_description``)
    rather than asserted from the capture, so a future payload that starts
    carrying real fields will say so in its own output instead of quietly
    disagreeing with this docstring.
    """
    rows_raw = unwrap(payload, route=ROUTE_SCANNED_JOBS, expect=list)

    rows = []
    for raw in rows_raw:
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                # Uplers' own spelling for the job title on this route is
                # `RequestForTalent`, which is the requisition-shaped name it
                # uses everywhere. Recorded here so the source key stays
                # findable from the output.
                "title": _text(raw.get("RequestForTalent")),
                "company": _text(raw.get("company_name")),
                "apply_url": _text(raw.get("apply_url")),
                "job_board": _text(raw.get("job_board")),
                "publish_datetime": _text(raw.get("publish_datetime")),
                "best_for_you": _flag(raw.get("best_for_you")),
            }
        )

    with_skills = sum(
        1 for raw in rows_raw if isinstance(raw, dict) and raw.get("skills")
    )
    with_description = sum(
        1
        for raw in rows_raw
        if isinstance(raw, dict)
        and (_text(raw.get("description")) or "") not in ("", PLACEHOLDER_DESCRIPTION)
    )
    best_rows = sum(1 for row in rows if row["best_for_you"] is True)

    shown = rows[: max(0, limit)]

    notes: list[str] = []
    if len(shown) < len(rows):
        notes.append(
            "Showing %d of %d rows. The truncation is THIS server's, applied "
            "after the whole list arrived: %s has no working limit of its own "
            "(a limit=3 against its sibling get-recommended-jobs returned all "
            "97 rows), so raise `limit` to see more without costing another "
            "request." % (len(shown), len(rows), ROUTE_SCANNED_JOBS)
        )
    notes.append(
        "%d of %d rows carry a non-empty `skills` list and %d carry a real "
        "description. Both counts are re-derived from this payload on every "
        "call rather than quoted from the capture."
        % (with_skills, len(rows_raw), with_description)
    )
    if with_skills:
        notes.append(
            "Some rows now carry skills, which the capture of 2026-08-23 did "
            "not. That is a change in the route, not a licence for this tool "
            "to start scoring - scoring stays a decision somebody makes on the "
            "evidence, not a switch that flips itself."
        )

    return {
        "route": ROUTE_SCANNED_JOBS,
        "last_job_scan": _text(payload.get("last_job_scan")),
        "breakdown": _board_counts(payload.get("breakdown")),
        "plan": payload.get("plan") if isinstance(payload.get("plan"), dict) else None,
        "total_rows": len(rows_raw),
        "returned": len(shown),
        "best_for_you_rows": best_rows,
        "rows": shown,
        "scoring": {
            "scored": False,
            "why": NO_SCORE_REASON,
            "rows_with_skills": with_skills,
            "rows_with_description": with_description,
        },
        "notes": notes,
    }


def shape_followup_settings(payload: dict) -> dict:
    """Whether an unanswered reply gets chased, from ``settings/followup``.

    MEASURED (``tests/fixtures/outreach_settings_followup.json``):
    ``disabled_followup_gmail: false``, ``disabled_followup_linkedin: false``,
    ``interval_days_gmail: 1``, ``interval_days_linkedin: 1``.

    THE FLAG IS INVERTED AND THE INVERSION IS THE WHOLE TRAP. Uplers stores
    ``disabled_followup_gmail``, so ``false`` means the channel is ON. A reader
    that passed that field through under a name like ``followup_gmail`` would
    report every enabled channel as disabled and every disabled one as
    enabled - a wrong answer that reads perfectly plausibly. This function
    returns ``enabled`` and does the negation once, here.

    ``message_gmail`` and ``message_linkedin`` are the follow-up BODIES and are
    not returned; see :data:`WITHHELD_BODY_KEYS`.
    """
    data = unwrap(payload, route=ROUTE_FOLLOWUP, expect=dict)

    channels: dict = {}
    for channel in CHANNELS:
        disabled = _flag(data.get("disabled_followup_%s" % channel))
        channels[channel] = {
            "enabled": None if disabled is None else (not disabled),
            "interval_days": _int(data.get("interval_days_%s" % channel)),
            "source_field": "disabled_followup_%s" % channel,
            "message_withheld": bool(data.get("message_%s" % channel)),
        }

    return {
        "route": ROUTE_FOLLOWUP,
        "channels": channels,
        "withheld": [key for key in WITHHELD_BODY_KEYS if key.startswith("message_")],
        "notes": [
            "Uplers stores this INVERTED, as disabled_followup_<channel>. The "
            "`enabled` values above are the negation, done once here; the raw "
            "field name is carried on each channel as source_field so the two "
            "can be checked against each other.",
            "The follow-up message bodies are in the payload and are not "
            "returned. message_withheld says whether one is set.",
        ],
    }


def shape_templates(payload: dict) -> dict:
    """Which outreach templates exist, from ``get-message-templates``.

    THE ONE ROUTE IN THIS RING THAT ANSWERS ``{"status": "success"}`` - the
    STRING - where the other five answer the integer 200.

    MEASURED (``tests/fixtures/outreach_templates.json``): a non-empty
    ``gmail_template`` with the subject "Looking to apply for {{title}} at
    {{company}}, need referral", and ``linkedin_template: ""`` with an empty
    subject.

    THE BODY IS NEVER RETURNED. The live ``gmail_template`` is a
    multi-paragraph self-description carrying employer history, a LinkedIn URL
    and a notice period; the fixture masks it and this function would withhold
    it either way, because a tool result ends up in a transcript. What a reader
    needs is whether a template EXISTS and what it says in the subject line,
    and both of those are here.

    THE EMPTY LINKEDIN TEMPLATE CORROBORATES A FINDING FROM A DIFFERENT ROUTE.
    ``outreach-step`` measured ``linkedin_connected: false``; this route
    measures the template as the empty string. Two independent routes, one
    conclusion: the LinkedIn channel is dead at both ends, not connected and
    with nothing to send.
    """
    data = unwrap(payload, route=ROUTE_TEMPLATES, expect=dict)

    channels: dict = {}
    for channel in CHANNELS:
        body = data.get("%s_template" % channel)
        channels[channel] = {
            # Existence is the non-emptiness of the body, computed here and
            # then the body is dropped. `""` is a real, measured value - an
            # empty template - and is reported as "does not exist" rather than
            # as a missing key.
            "exists": bool(_text(body)),
            "subject": _text(data.get("%s_template_subject" % channel)),
            "body_withheld": True,
        }

    dead = [name for name, row in channels.items() if not row["exists"]]
    notes = [
        "Template BODIES are never returned by this tool, on any channel. The "
        "gmail one is a multi-paragraph self-description carrying employer "
        "history, a LinkedIn URL and a notice period.",
    ]
    if dead:
        notes.append(
            "No template exists for: %s. On linkedin that agrees with "
            "outreach-step's linkedin_connected: false, measured on a "
            "different route - the channel is dead at both ends."
            % ", ".join(sorted(dead))
        )

    return {
        "route": ROUTE_TEMPLATES,
        "channels": channels,
        "withheld": [key for key in WITHHELD_BODY_KEYS if key.endswith("_template")],
        "notes": notes,
    }


def shape_auto_reply(payload: dict) -> dict:
    """The auto-reply switch and its categories, from ``get-auto-reply``.

    MEASURED (``tests/fixtures/outreach_auto_reply.json``):
    ``handle_auto_reply: false``, ``hours: 2``, and 8 categories.

    ``hours`` IS CARRIED UNDER UPLERS' OWN NAME AND DESCRIBED AS A DELAY, which
    is what the route's own message ("Auto reply hours fetched successfully")
    and the field's position support. What it is a delay BEFORE has not been
    measured by this server, so it is not described as one thing or another
    beyond that.

    ``asking_resume`` is one of the 8 categories. It is stated as a fact - the
    feature exists, it is off, and that category is in its list. No
    recommendation is attached: whether to let software answer a person who
    asked him for his resume is his call, not a tool's.
    """
    data = unwrap(payload, route=ROUTE_AUTO_REPLY, expect=dict)

    raw_categories = data.get("auto_reply_categories")
    categories = (
        [text for text in (_text(item) for item in raw_categories) if text]
        if isinstance(raw_categories, list)
        else []
    )
    enabled = _flag(data.get("handle_auto_reply"))

    notes = [
        "`hours` is Uplers' own field name and is reported as a delay in "
        "hours. Exactly what it delays has not been measured here, so it is "
        "not described more precisely than the payload supports.",
    ]
    if enabled is False and "asking_resume" in categories:
        notes.append(
            "Auto-reply is OFF, and `asking_resume` is one of the %d "
            "categories it would answer if it were on. Stated as a fact about "
            "the account; no recommendation either way." % len(categories)
        )

    return {
        "route": ROUTE_AUTO_REPLY,
        "enabled": enabled,
        "delay_hours": _int(data.get("hours")),
        "categories": categories,
        "category_count": len(categories),
        "notes": notes,
    }


def shape_disabled_companies(payload: dict) -> dict:
    """The outreach blocklist, from ``settings/disabled-companies``.

    MEASURED (``tests/fixtures/outreach_disabled_companies.json``): 16 rows,
    all blocked within about an hour on 2026-08-12, and ``reason`` is null on
    every single one.

    THIS IS THE LIST A FAILED AGENT RUN IS TALKING ABOUT when it says "You
    blocked this company for outreach". It is NOT ``settings/companies``, which
    is the alphabetical company picker paginated at 20 rows; reading a
    blocklist off that route would report the first twenty companies in the
    alphabet as blocked.

    ``reason`` IS REPORTED EVEN THOUGH IT IS EMPTY. Uplers carries the field
    and his rows have never used it, and "the field exists and is unused" is a
    different fact from "there is no such field" - the first one tells a reader
    not to go looking elsewhere for the reasons.
    """
    rows_raw = unwrap(payload, route=ROUTE_DISABLED_COMPANIES, expect=list)

    rows = []
    for raw in rows_raw:
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "company_name": _text(raw.get("company_name")),
                "reason": _text(raw.get("reason")),
                "created_at": _text(raw.get("created_at")),
            }
        )

    with_reason = sum(1 for row in rows if row["reason"])
    notes = [
        "This is the real blocklist. talent/outreach/settings/companies is a "
        "DIFFERENT route - an alphabetical picker paginated at 20 - and is not "
        "where this list comes from.",
        'An agent run that failed with "You blocked this company for '
        'outreach" was blocked by one of these rows.',
    ]
    if rows and not with_reason:
        notes.append(
            "None of the %d rows carries a reason. The field exists in Uplers' "
            "payload and is null on every one, so the reasons are not recorded "
            "somewhere else - they were never captured." % len(rows)
        )

    return {
        "route": ROUTE_DISABLED_COMPANIES,
        "count": len(rows),
        "rows": rows,
        "rows_with_reason": with_reason,
        "notes": notes,
    }


# --- The assembled settings report -----------------------------------------


def agent_settings(*, followup, templates, auto_reply, blocked) -> dict:
    """The four settings surfaces as one report. Takes ALREADY-SHAPED dicts.

    Pure, and assembles nothing it was not given.

    THE HEADLINE IS WHAT IS OFF. Three of the four surfaces here describe
    machinery that can be switched off without any sign of it in the agent's
    output - a dead channel, a template that was never written, an auto-reply
    that never fires - and a blocklist that silently removes companies from
    every run. Each of those is a reason his paid agent does less than he
    thinks it does, and none of them appears in the agent's own activity log.

    Nothing here is a recommendation. Every line is a state of his account.
    """
    followup = _require(followup, name="followup", route=ROUTE_FOLLOWUP)
    templates = _require(templates, name="templates", route=ROUTE_TEMPLATES)
    auto_reply = _require(auto_reply, name="auto_reply", route=ROUTE_AUTO_REPLY)
    blocked = _require(blocked, name="blocked", route=ROUTE_DISABLED_COMPANIES)

    headline: list[str] = []

    for channel in CHANNELS:
        follow_row = followup.get("channels", {}).get(channel, {})
        template_row = templates.get("channels", {}).get(channel, {})
        if template_row.get("exists") is False and follow_row.get("enabled") is True:
            headline.append(
                "%s: follow-up is ON but no template exists on that channel."
                % channel
            )
        elif follow_row.get("enabled") is False:
            headline.append("%s: follow-up is OFF." % channel)

    if auto_reply.get("enabled") is False:
        headline.append(
            "auto-reply is OFF (%d categories configured, delay %r hours)."
            % (auto_reply.get("category_count") or 0, auto_reply.get("delay_hours"))
        )

    count = blocked.get("count") or 0
    if count:
        headline.append(
            "%d companies are blocked for outreach; the agent skips them "
            "silently." % count
        )

    return {
        "headline": headline,
        "followup": followup,
        "templates": templates,
        "auto_reply": auto_reply,
        "blocked_companies": blocked,
        "reads_only": True,
        "notes": [
            "Four GETs, no writes, and none of the write routes in this "
            "namespace is reachable from this tool. Two of them ARE now built "
            "elsewhere and are named rather than hidden: "
            "uplers_revoke_email_scan reaches consent-email-job-scan (DELETE "
            "only) and uplers_submit_interview_feedback reaches "
            "interview-feedback, which is ONE-WAY. consent-auto-run and the "
            "GRANT arm of the consent are still not built at all.",
            "Every line above is a state of the account, not a recommendation.",
        ],
    }
