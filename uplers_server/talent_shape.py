"""Project authenticated payloads onto the typed shapes.

**This module writes no scoring and no pay parsing.** A requisition seen
through his account is the same requisition the public catalogue serves, so it
runs through the same `shaping.to_opportunity` and the same `fit` scorer, and a
fit score therefore means the same thing on both tiers - which is the only
reason the two tiers can be compared at all. What this module adds is the layer
the public record cannot have: what HE has done about each job, and what
Uplers' recruiters have since done with it.

**Envelopes are validated, never trusted.** Every read here raises when the
expected key is absent instead of shaping an empty list. That rule exists
because the failure it prevents is invisible: a silently-empty feed reads as
"no jobs match you today", which is exactly what a broken session, a renamed
key, or a changed paginator would also produce. This server has been bitten by
that class before, so the envelope check is the first thing every reader does.

Field names come from Uplers' own bundle call sites, recorded with verbatim
evidence in `_audit/2026-08-21-uplers-bundle-callsites.md`. Where the bundle
proves a name, it is used. Where it does not, several plausible spellings are
tried and the miss is REPORTED rather than defaulted - see `_first`.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import fit, shaping
from .models import Opportunity
from .search import notice_days
from .talent import TalentError
from .talent_models import (
    EducationEntry,
    ExperienceEntry,
    FieldDiff,
    FieldReport,
    Interview,
    ProjectEntry,
    TalentProfileResult,
    TalentRow,
)

#: Values Uplers uses for "yes" in flags that are sometimes 1, sometimes true,
#: sometimes "1". Normalised in one place so no caller invents its own test.
_TRUE = (1, "1", True, "true", "True", "yes")


def truthy(value: Any) -> bool | None:
    """Tri-state: True, False, or None when the key was simply absent.

    None matters. `applied: None` means "this feed does not report it"; a
    default of False would assert he has not applied, which is a claim the
    payload never made.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if value in _TRUE:
        return True
    if value in (0, "0", False, "false", "False", "no", ""):
        return False
    return None


def _first(raw: dict, *names: str) -> Any:
    """First present, non-empty value among several candidate spellings."""
    for name in names:
        value = raw.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def unwrap_paginator(payload: Any, *, route: str) -> tuple[list[dict], dict]:
    """`(rows, page_meta)` from a Laravel paginator envelope, or raise.

    VERIFIED shape: rows live at ``res["hrs"]["data"]`` with ``current_page``
    and ``last_page`` beside them. A payload that does not carry ``hrs`` is a
    changed API or a session that answered something other than data, and in
    both cases returning ``[]`` would be a lie.
    """
    if not isinstance(payload, dict):
        raise TalentError(
            "%s returned %s, not a JSON object. The authenticated API may have "
            "changed shape." % (route, type(payload).__name__)
        )
    envelope = payload.get("hrs")
    if envelope is None:
        raise TalentError(
            "%s returned no `hrs` envelope, so there are no rows to read. This is "
            "NOT 'no jobs matched' - the response did not have the expected shape. "
            "Top-level keys were: %s" % (route, sorted(payload)[:12] or "none")
        )
    if isinstance(envelope, list):
        # Some Laravel routes drop the paginator when unpaginated.
        return ([row for row in envelope if isinstance(row, dict)], {})
    if not isinstance(envelope, dict):
        raise TalentError(
            "%s returned `hrs` as %s; expected an object or a list."
            % (route, type(envelope).__name__)
        )
    rows = envelope.get("data")
    if not isinstance(rows, list):
        raise TalentError(
            "%s returned `hrs` with no `data` list (keys: %s), so no rows could be "
            "read." % (route, sorted(envelope)[:12] or "none")
        )
    meta = {
        "page": envelope.get("current_page"),
        "last_page": envelope.get("last_page"),
        "total": envelope.get("total"),
        "per_page": envelope.get("per_page"),
    }
    return ([row for row in rows if isinstance(row, dict)], meta)


def is_test_record(raw: dict) -> bool:
    """Uplers' own UI throws these away and redirects; so do we.

    VERIFIED at the `single-hr` call site: ``1 != res.data.is_test_hr`` gates
    whether the record is rendered at all.

    Read through `job_view` for the same reason every other job field is: the
    flag describes the REQUISITION, so on `my-opportunities` it would arrive
    under ``hr`` and a wrapper-level read would never see it. No captured list
    payload carries the key at all today, so this changes nothing observable -
    it stops the filter being silently dead if one ever does.
    """
    return truthy(shaping.job_view(raw).get("is_test_hr")) is True


def to_talent_row(
    raw: dict,
    *,
    profile=None,
    opportunity: Opportunity | None = None,
    bound=None,
    explain: bool = False,
) -> TalentRow:
    """One authenticated row: the public projection plus his own state.

    Scoring is optional and is jobcore's, unchanged. When `profile` is given
    the row carries a score comparable with every other score in this server.

    `explain` only means anything alongside a profile: with no profile there is
    no assessment, so the row is unscored and carries no block. That is the
    same condition the tools' `score=False` produces, and it is why passing
    `score=False, explain=True` is a no-op rather than an error.
    """
    opp = opportunity or shaping.to_opportunity(raw)

    score = verdict = None
    unscorable: str | None = None
    basis: str | None = None
    working: dict | None = None
    gaps: list[str] = []
    blockers: list[str] = []
    if profile is not None:
        try:
            assessment = fit.assess(opp, profile, bound, explain=explain)
        except fit.UnscorableOpportunity as exc:
            # A page of rows must not die on one unreadable record, and must not
            # quietly ship it at jobcore's neutral 50 either. The row comes back
            # with no score and says why.
            unscorable = str(exc)
        else:
            basis = fit.score_basis(opp)
            score = assessment.get("overall_score")
            working = assessment.get("explain")
            verdict = fit.compact_verdict(assessment)
            must = assessment.get("must_have") or {}
            gaps = list(
                must.get("missing")
                or (assessment.get("skill_match") or {}).get("missing")
                or []
            )[:3]
            blockers = assessment.get("blockers") or []

    # The IDENTIFIER SPACES, and they must come from the JOB, not the wrapper.
    # On `my-opportunities` the wrapper is the APPLICATION: it carries no `id`
    # at all, and its `enc_id` is HIS TALENT id - MEASURED identical across all
    # nine of his pipeline rows while `hr.enc_id` differs per row. `enc_id` is
    # what the save/unsave route sends as `hr_id`, so reading the wrapper aims a
    # write at the wrong identifier space. `shaping.job_view` resolves this once
    # for every surface; it is a no-op on the three that do not nest.
    job = shaping.job_view(raw)
    job_id = _first(job, "id", "hr_id")
    return TalentRow(
        hr_number=opp.hr_number or None,
        title=opp.title,
        company=opp.company,
        role=opp.role,
        mode=opp.mode_of_work,
        # A Remote role's city names an office nobody attends, so it is dropped
        # here for the same reason fit.to_row drops it.
        city=None if (opp.mode_of_work or "") == "Remote" else opp.city,
        pay=fit.render_pay(opp),
        notice=opp.joining_period,
        min_years_experience=opp.min_years_experience,
        job_id=int(job_id) if isinstance(job_id, (int, str)) and str(job_id).isdigit() else None,
        enc_id=_stringify(_first(job, "enc_id", "encrypted_id")),
        applied=truthy(_first(raw, "is_intrested", "is_interested", "applied", "is_applied")),
        saved=truthy(_first(raw, "is_saved", "saved")),
        not_interested=truthy(raw.get("job_not_interested")),
        # NOT `status`/`badge`. Every captured live record carries `status` as the
        # integer 1 - a numeric state flag, not a pipeline status name - so
        # including it as a fallback spelling put an int into a str field and
        # crashed every write tool on the real record shape before it could do
        # anything. Guessing extra spellings is only safe where a wrong guess
        # returns nothing; here a wrong guess returned the wrong FIELD.
        uplers_status=_stringify(_first(raw, "statusName", "status_name")),
        uplers_badge=_stringify(_first(raw, "badgeName", "badge_name")),
        score=score,
        verdict=verdict,
        unscorable=unscorable,
        score_basis=basis,
        gaps=gaps,
        blockers=blockers,
        posted_at=(opp.posted_at or "")[:10] or None,
        explain=working,
        # --- what the WRAPPER knows and the job does not ---------------------
        # Read from `raw`, deliberately: these are facts about HIS application,
        # not about the requisition, and on the three unnested surfaces they are
        # simply absent.
        applied_at=_stringify(_first(raw, "applied_at", "applied_date")),
        uplers_match_score=_to_float(raw.get("matchmake_score")),
    )


def rows_from(
    payload: Any,
    *,
    route: str,
    profile=None,
    drop_test_records: bool = True,
    bound=None,
    explain: bool = False,
) -> tuple[list[TalentRow], dict, list[str]]:
    """`(rows, page_meta, notes)`. Raises rather than returning nothing quietly."""
    raw_rows, meta = unwrap_paginator(payload, route=route)
    notes: list[str] = []
    kept: list[dict] = []
    dropped = 0
    for raw in raw_rows:
        if drop_test_records and is_test_record(raw):
            dropped += 1
            continue
        kept.append(raw)
    if dropped:
        notes.append(
            "%d internal test requisition(s) hidden (is_test_hr), matching what "
            "Uplers' own UI does with them." % dropped
        )
    return (
        [
            to_talent_row(raw, profile=profile, bound=bound, explain=explain)
            for raw in kept
        ],
        meta,
        notes,
    )


def tally(rows: Iterable[TalentRow], attribute: str) -> dict:
    """Count rows by one attribute, commonest first. Absent values are skipped."""
    counts: dict[str, int] = {}
    for row in rows:
        value = getattr(row, attribute, None)
        if value:
            counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


# --- profile --------------------------------------------------------------

#: Where the profile object hides. VERIFIED: `res.data.talent_details`.
PROFILE_KEY = "talent_details"

#: Where the human-readable names hide. THE bug this module was fixed for.
#:
#: `talent_details.skills` does NOT carry skill names. It carries rows of
#: ``{id, skill_id, talent_id, years_of_experience, order, enc_id}`` - a join
#: table. The names live in a separate top-level `masters` lookup, 176,329
#: rows of ``{"value": <skill_id>, "label": "<name>"}``, shipped in the same
#: response.
#:
#: Reading the rows without the join finds no name-shaped key on any of them
#: and returns an empty list, which reads exactly like an empty profile. That
#: is what happened: the server reported "0 skills there vs 32 here" on the day
#: the operator finished filling his profile in, and recommended he go and add
#: to it. He had 61.
MASTERS_KEY = "masters"

#: Which section joins to which master, and on which foreign key. All three
#: are VERIFIED against the live record; none of them carries an inline name.
SKILL_SECTIONS = (
    ("skills", "skills", "skill_id"),
    ("primaryskills", "skills", "skill_id"),
    ("tools", "tools", "tool_id"),
)

#: Never read, never modelled, never printed. These arrive in every profile
#: payload and every one of them is his private business: pay, contact route,
#: identity document, home address, and the URLs of personal files. A shaped
#: profile ends up in transcripts, logs and reports, so the exclusion is
#: enforced here at the boundary rather than trusted to each caller.
#:
#: The names are filtered out of `sections_present` too. A section NAME is
#: normally harmless diagnostic - but "expected_ctc is populated" is itself a
#: disclosure, and the list is no less useful without them.
PRIVATE_KEYS = frozenset(
    {
        "current_ctc",
        "expected_ctc",
        "monthly_salary",
        "salary",
        "dob",
        "contact_number",
        "contact_number_country_code",
        "whatsapp_optin",
        "address",
        "email",
        "profile_pic",
        "profile_pic_url",
        "ra_profile_pic_url",
        "resume",
        "resume_url",
        "ra_resume_url",
        "gender",
    }
)


def masters_index(payload: Any) -> dict[str, dict[str, str]]:
    """`{master_name: {id_as_str: label}}` from the payload's `masters` block.

    Keyed by string throughout because the two sides disagree about type: the
    master writes `value` as an int, and the profile row writes `skill_id` as
    an int but `years_of_experience` as a string, so nothing about the payload
    justifies trusting either. One `str()` on both sides costs nothing and
    removes the whole class.
    """
    masters = payload.get(MASTERS_KEY) if isinstance(payload, dict) else None
    if not isinstance(masters, dict):
        return {}
    index: dict[str, dict[str, str]] = {}
    for name, rows in masters.items():
        if not isinstance(rows, list):
            continue
        lookup: dict[str, str] = {}
        for row in rows:
            if isinstance(row, dict) and row.get("value") is not None:
                label = row.get("label")
                if label not in (None, ""):
                    lookup[str(row["value"])] = str(label)
        if lookup:
            index[name] = lookup
    return index


def resolve_skill_rows(
    rows: Any, lookup: dict[str, str], id_key: str
) -> tuple[list[str], dict[str, float], list[str]]:
    """`(names, years_by_name, unresolved_ids)` for one joined section.

    Order is preserved: Uplers' own list is priority-ordered and re-sorting it
    would throw that away.

    An id with no row in the master is REPORTED, not dropped. That is the whole
    lesson of this module - a silently discarded skill is invisible, and
    invisibility is why the original bug survived 667 tests.
    """
    names: list[str] = []
    years: dict[str, float] = {}
    unresolved: list[str] = []
    if not isinstance(rows, (list, tuple)):
        return (names, years, unresolved)

    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get(id_key)
        if identifier is None:
            continue
        name = lookup.get(str(identifier))
        if not name:
            unresolved.append(str(identifier))
            continue
        if name not in names:
            names.append(name)
        # Uplers writes 0 for "not recorded", which is not the same claim as
        # "zero years", so only a positive figure is carried.
        recorded = shaping.to_float(row.get("years_of_experience"))
        if recorded:
            years[name] = recorded
    return (names, years, unresolved)


def _labels(rows: Any) -> list[str]:
    """Label strings out of a `[{"label": ..., "value": ...}]` list."""
    out: list[str] = []
    if not isinstance(rows, (list, tuple)):
        return out
    for row in rows:
        label = row.get("label") if isinstance(row, dict) else row
        if label not in (None, "") and str(label) not in out:
            out.append(str(label))
    return out


def _work_mode_preference(details: dict, index: dict) -> str | None:
    """Resolve `preferred_method` through its master.

    A trap worth naming. Uplers' `preferred_modes` reads like the local
    profile's field of the same name but means ENGAGEMENT type - "Full time",
    "Contract". The Remote/Office answer is `preferred_method`, an integer
    resolving through `preferredMethodMaster` to "Remote Only" or "Remote or
    Office". Mapping one onto the other would write "Full time" into a
    work-mode field and corrupt every mode filter downstream, silently.
    """
    raw = details.get("preferred_method")
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        raw = _first(raw, "preferred_method", "value", "id")
    if raw in (None, ""):
        return None
    return (index.get("preferredMethodMaster") or {}).get(str(raw))


def _experiences(rows: Any) -> list[ExperienceEntry]:
    out: list[ExperienceEntry] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        out.append(
            ExperienceEntry(
                title=_stringify(_first(row, "title", "designation", "job_title")),
                company=_stringify(_first(row, "company_name", "company", "organisation")),
                start_date=_stringify(row.get("start_date")),
                end_date=_stringify(row.get("end_date")),
                # `is_current` is 0/1/2 on the live record, so it is read as
                # truthy rather than compared to 1.
                is_current=truthy(row.get("is_current")),
            )
        )
    return out


def _educations(rows: Any) -> list[EducationEntry]:
    out: list[EducationEntry] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        out.append(
            EducationEntry(
                degree=_stringify(_first(row, "degree", "qualification")),
                university=_stringify(_first(row, "university", "institute", "college")),
                end_date=_stringify(row.get("end_date")),
            )
        )
    return out


def _projects(rows: Any) -> list[ProjectEntry]:
    """Title and description only - `project_url` is a personal link."""
    out: list[ProjectEntry] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        description = _stringify(row.get("description"))
        out.append(
            ProjectEntry(
                title=_stringify(_first(row, "title", "name")),
                description=(description or "")[:300] or None,
            )
        )
    return out


def to_talent_profile(payload: Any) -> TalentProfileResult:
    """His real Uplers profile. Raises when the envelope is not a profile.

    Refuses to return an empty profile for an unexpected payload, because an
    empty Uplers profile and an unreadable one lead to opposite actions: the
    first says "go and fill your profile in", the second says "this client is
    broken".

    Skills come out of the `masters` join described at MASTERS_KEY. When a
    payload carries no `masters` - a caller that fetched only the profile
    object, or a test - the reader falls back to inline names, so both shapes
    read.
    """
    if not isinstance(payload, dict):
        raise TalentError(
            "talent/profile returned %s, not a JSON object." % type(payload).__name__
        )
    details = payload.get(PROFILE_KEY)
    if not isinstance(details, dict) or not details:
        raise TalentError(
            "talent/profile returned no `%s` object, so no profile could be read. "
            "This is NOT an empty profile - the response did not have the expected "
            "shape. Top-level keys were: %s"
            % (PROFILE_KEY, sorted(payload)[:12] or "none")
        )

    index = masters_index(payload)
    resolved: dict[str, list[str]] = {}
    skill_years: dict[str, float] = {}
    unresolved: list[str] = []
    for section, master, id_key in SKILL_SECTIONS:
        rows = details.get(section)
        names, years, missing = resolve_skill_rows(rows, index.get(master) or {}, id_key)
        if not names and rows:
            # No join available (or none of it matched): the section may still
            # name its skills inline, which is what every hand-built payload
            # does and what an older API shape did.
            names = _skill_names(rows)
            if names:
                missing = []
        resolved[section] = names
        skill_years.update(years)
        unresolved.extend(missing)

    skills = resolved["skills"] or _skill_names(_first(details, "talent_skills", "skill") or [])
    titles = _skill_names(_first(details, "roles", "job_roles", "preferred_roles") or [])

    # `first_name` is deliberately NOT in this chain: listing it here made the
    # concat below unreachable, so a profile carrying first_name + last_name
    # silently lost the surname.
    name = _stringify(_first(details, "full_name", "name"))
    if not name:
        first = details.get("first_name") or ""
        last = details.get("last_name") or ""
        name = ("%s %s" % (first, last)).strip() or None

    objective = _stringify(_first(details, "objective", "summary", "about"))
    if not objective and isinstance(details.get("objective_data"), dict):
        objective = _stringify(details["objective_data"].get("objective"))

    notes: list[str] = []
    if unresolved:
        notes.append(
            "%d skill id(s) had no entry in Uplers' own lookup and are reported "
            "rather than dropped: %s. This is a gap in their masters table, not "
            "in your profile." % (len(unresolved), ", ".join(sorted(set(unresolved))[:10]))
        )

    return TalentProfileResult(
        name=name,
        headline=_first(details, "headline", "title", "designation", "job_title", "current_designation"),
        years_experience=shaping.to_float(
            _first(details, "total_experience", "experience", "yoe", "year_of_exp")
        ),
        location=_first(details, "city", "location", "current_location")
        or (_labels(details.get("preferred_cities")) or [None])[0],
        skills=skills,
        primary_skills=resolved["primaryskills"],
        tools=resolved["tools"],
        skill_years=skill_years,
        unresolved_skill_ids=sorted(set(unresolved)),
        titles=titles,
        objective=objective,
        notice_period=_stringify(
            _first(details, "notice_period", "joining_period", "availability_to_join")
        ),
        availability=_stringify(_first(details, "availability", "engagement_type")),
        engagement_types=_labels(details.get("preferred_modes")),
        work_mode_preference=_work_mode_preference(details, index),
        preferred_cities=_labels(details.get("preferred_cities")),
        account_status=_stringify(details.get("status_text")),
        experiences=_experiences(details.get("experiences")),
        educations=_educations(details.get("educations")),
        projects=_projects(details.get("projects")),
        achievements=[
            title
            for title in (
                _stringify(_first(row, "title", "name"))
                for row in (details.get("achievements") or [])
                if isinstance(row, dict)
            )
            if title
        ],
        completion_percentage=shaping.to_float(payload.get("profile_completion_percentage")),
        remaining_percentage=shaping.to_float(payload.get("profile_remaining_percentage")),
        sections_present=sorted(
            key
            for key in details
            if key not in PRIVATE_KEYS and details.get(key) not in (None, "", [], {})
        ),
        notes=notes,
    )


def _stringify(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, dict):
        return _first(value, "name", "title", "label", "value")
    return str(value)


def _to_float(value: Any) -> float | None:
    """`matchmake_score` arrives as the decimal STRING "84.15", like every
    other number on this API. None when absent or unparseable - never 0.0,
    which would read as "Uplers rated this job zero"."""
    return shaping.to_float(value)


def _skill_names(raw: Any) -> list[str]:
    """Skills arrive as strings, or as objects under any of several keys."""
    out: list[str] = []
    if isinstance(raw, str):
        raw = [piece.strip() for piece in raw.split(",")]
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        name = None
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = _stringify(_first(item, "name", "skill_name", "title", "label", "skill"))
        if name and name not in out:
            out.append(name)
    return out


# --- interviews -----------------------------------------------------------


def to_interview(raw: dict) -> Interview:
    company_id = raw.get("company_id")
    return Interview(
        company=_stringify(_first(raw, "company_name", "company", "client_name")),
        company_id=int(company_id) if isinstance(company_id, (int, str)) and str(company_id).isdigit() else None,
        role=_stringify(_first(raw, "RequestForTalent", "role", "job_title", "title")),
        status=_stringify(_first(raw, "status", "statusName", "interview_status")),
        scheduled_at=_stringify(
            _first(raw, "scheduled_at", "interview_date", "slot", "scheduled_date")
        ),
        feedback_given=truthy(_first(raw, "feedback", "is_feedback_given")),
    )


def interviews_from(payload: Any) -> tuple[list[Interview], list[str]]:
    """VERIFIED envelope: `res.status == "success"` and `res.data` is an array.

    A ZERO HERE HAS TWO READINGS AND THE PAYLOAD SAYS WHICH. Uplers builds this
    list by scanning a connected mailbox, so an empty `data` means either "no
    interviews have been arranged" or "the scan was never switched on". Those
    are opposite facts and `{count: 0}` alone cannot tell them apart. The
    distinguishing evidence rides in `meta` - and was being discarded.

    MEASURED live 2026-08-22: `meta` was `{has_consent: false,
    consent_interview_email_scan: null, gmail_connected: true}`, i.e. a mailbox
    IS connected and the scan has never been consented to. So the zero was a
    feature that was never turned on, and the tool reported it as an empty
    diary.
    """
    if not isinstance(payload, dict):
        raise TalentError(
            "interview-list returned %s, not a JSON object." % type(payload).__name__
        )
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise TalentError(
            "interview-list returned no `data` array (keys: %s), so no interviews "
            "could be read. This is NOT 'no interviews scheduled'."
            % (sorted(payload)[:12] or "none")
        )
    notes: list[str] = []
    status = payload.get("status")
    if status is not None and status != "success":
        notes.append("Uplers reported status %r on this response." % status)
    interviews = [to_interview(row) for row in rows if isinstance(row, dict)]
    if not interviews:
        notes.extend(_empty_diary_diagnosis(payload.get("meta")))
    return (interviews, notes)


def _empty_diary_diagnosis(meta: Any) -> list[str]:
    """Why the interview list is empty, in the terms Uplers itself reported.

    Never prints `meta.gmail_email`. WHETHER a mailbox is connected is
    diagnostic and belongs here; WHICH mailbox is his personal data and belongs
    in the same bin as every other key in `PRIVATE_KEYS` - a shaped result ends
    up in transcripts and reports.
    """
    if not isinstance(meta, dict):
        return [
            "No interviews. Uplers sent no `meta` block with this response, so "
            "there is no evidence either way about whether the interview email "
            "scan is switched on - read this as 'nothing scheduled that Uplers "
            "knows about', not as a confirmed empty diary."
        ]
    consent = truthy(meta.get("has_consent"))
    connected = truthy(meta.get("gmail_connected"))
    if consent is False:
        return [
            "No interviews, and this is NOT evidence that none are scheduled: "
            "Uplers reports has_consent=false, meaning the interview email scan "
            "that populates this list has never been consented to. A mailbox %s. "
            "Turn the scan on in Uplers' own settings before reading this zero "
            "as an empty diary."
            % (
                "IS connected (gmail_connected=true), so consent is the only "
                "thing missing"
                if connected
                else "is not connected either (gmail_connected=false)"
            )
        ]
    if connected is False:
        return [
            "No interviews. Uplers reports gmail_connected=false, so the mailbox "
            "this list is built by scanning is not connected - the zero describes "
            "the integration, not your diary."
        ]
    return [
        "No interviews. Uplers reports the email scan as consented (has_consent="
        "true) and the mailbox as connected, so this is a REAL zero: nothing is "
        "scheduled that Uplers can see."
    ]


# --- what the session actually buys ---------------------------------------

#: Trimmed so a field report stays small enough to read.
_VALUE_PREVIEW_CHARS = 120


def field_report(authenticated: dict, public: dict) -> FieldReport:
    """Which fields the authenticated record carries that the public one lacks.

    This is the tier's own justification made measurable: a session is worth
    holding exactly insofar as this list is non-empty.
    """
    auth_keys = {key for key in authenticated if authenticated.get(key) not in (None, "", [], {})}
    public_keys = {key for key in public if public.get(key) not in (None, "", [], {})}
    only_auth = sorted(auth_keys - public_keys)

    values: dict = {}
    for key in only_auth:
        rendered = authenticated.get(key)
        if isinstance(rendered, (dict, list)):
            rendered = "%s(%d)" % (type(rendered).__name__, len(rendered))
        else:
            rendered = str(rendered)[:_VALUE_PREVIEW_CHARS]
        values[key] = rendered

    return FieldReport(
        hr_number=authenticated.get("HR_Number") or public.get("HR_Number"),
        title=authenticated.get("RequestForTalent") or public.get("RequestForTalent"),
        only_in_authenticated=only_auth,
        only_in_public=sorted(public_keys - auth_keys),
        in_both=len(auth_keys & public_keys),
        values=values,
    )


# --- profile reconciliation -----------------------------------------------


def _norm_skills(names: Iterable[str]) -> dict[str, str]:
    """Lowercased key -> original spelling, so a diff is not case noise."""
    out: dict[str, str] = {}
    for name in names:
        key = str(name).strip().lower()
        if key:
            out.setdefault(key, str(name).strip())
    return out


#: Fields where a disagreement is a JUDGEMENT, not a defect.
#:
#: "Software Engineer" vs "Backend Software Engineer" is a positioning choice.
#: 5.2 vs 5.0 years is a rounding convention. Uplers is the source of truth for
#: everything else, but taking its side automatically on these two would be the
#: server overruling him on a question it has no basis to answer. They are
#: reported as a pair and left alone.
CONTESTED_FIELDS = ("headline", "years_experience")


def compare_profiles(
    local, remote: TalentProfileResult
) -> tuple[list[str], list[FieldDiff], list[str], list[str], list[FieldDiff]]:
    """`(agree, differ, only_local_skills, only_uplers_skills, contested)`.

    **Uplers is the source of truth.** The local profile is a scoring input, so
    a gap between the two is a defect in the LOCAL copy and every note here
    reads in that direction. This used to run the other way and recommended he
    edit the authoritative record to match its own cache.

    Compares only fields both sides actually have. A field the Uplers profile
    does not report is not a disagreement - it is a silence, and reporting a
    silence as a conflict would bury the real ones.

    Skills are compared against the UNION of Uplers' three skill sections. A
    skill listed only under `tools` is still a skill he has, and holding it
    against him because it landed in a different section of their schema would
    manufacture a gap out of their data model.
    """
    agree: list[str] = []
    differ: list[FieldDiff] = []
    contested: list[FieldDiff] = []

    def compare(field: str, local_value, remote_value, note: str | None = None) -> None:
        if remote_value in (None, "", [], {}):
            return
        if local_value in (None, "", [], {}):
            differ.append(
                FieldDiff(
                    field=field,
                    local="(not set)",
                    uplers=str(remote_value),
                    note="Only Uplers has this - copy it into the local profile.",
                )
            )
            return
        if str(local_value).strip().lower() == str(remote_value).strip().lower():
            agree.append(field)
            return
        diff = FieldDiff(
            field=field, local=str(local_value), uplers=str(remote_value), note=note
        )
        differ.append(diff)
        if field in CONTESTED_FIELDS:
            contested.append(diff)

    compare("name", getattr(local, "name", None), remote.name)
    compare(
        "headline",
        getattr(local, "headline", None),
        remote.headline,
        "Neither is wrong - a headline is positioning. Your call.",
    )
    compare(
        "years_experience",
        getattr(local, "years_experience", None),
        remote.years_experience,
        "Fit scores use the local value. Your call which figure is right.",
    )
    compare("location", getattr(local, "location", None), remote.location)

    # Notice period is compared in DAYS, not as text. Locally it is the integer
    # 0; on Uplers it is the string "Immediately". Those are the same answer,
    # and a string comparison called them a conflict - on the single most
    # decisive field on this board, which is the worst possible place to
    # manufacture a false alarm.
    local_notice = getattr(local, "notice_period_days", None)
    remote_notice_days = notice_days(remote.notice_period)
    if remote.notice_period:
        note = "THE decisive field on this board - most Uplers clients accept only 15-30 days."
        if local_notice is None:
            differ.append(
                FieldDiff(
                    field="notice_period",
                    local="(not set)",
                    uplers=remote.notice_period,
                    note=note,
                )
            )
        elif remote_notice_days is not None and int(local_notice) == remote_notice_days:
            agree.append("notice_period")
        else:
            differ.append(
                FieldDiff(
                    field="notice_period",
                    local="%s days" % local_notice,
                    uplers=remote.notice_period,
                    note=note,
                )
            )

    local_skills = _norm_skills(getattr(local, "skills", []) or [])
    remote_skills = _norm_skills(remote.all_skill_names())
    only_local = sorted(local_skills[key] for key in local_skills.keys() - remote_skills.keys())
    only_remote = sorted(remote_skills[key] for key in remote_skills.keys() - local_skills.keys())
    if local_skills and remote_skills and not (only_local or only_remote):
        agree.append("skills")

    return (agree, differ, only_local, only_remote, contested)
