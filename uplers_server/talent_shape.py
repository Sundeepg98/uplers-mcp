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
from .talent import TalentError
from .talent_models import (
    FieldDiff,
    FieldReport,
    Interview,
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
    """
    return truthy(raw.get("is_test_hr")) is True


def to_talent_row(
    raw: dict,
    *,
    profile=None,
    opportunity: Opportunity | None = None,
) -> TalentRow:
    """One authenticated row: the public projection plus his own state.

    Scoring is optional and is jobcore's, unchanged. When `profile` is given
    the row carries a score comparable with every other score in this server.
    """
    opp = opportunity or shaping.to_opportunity(raw)

    score = verdict = None
    gaps: list[str] = []
    blockers: list[str] = []
    if profile is not None:
        assessment = fit.assess(opp, profile)
        score = assessment.get("overall_score")
        verdict = fit.compact_verdict(assessment)
        must = assessment.get("must_have") or {}
        gaps = list(
            must.get("missing")
            or (assessment.get("skill_match") or {}).get("missing")
            or []
        )[:3]
        blockers = assessment.get("blockers") or []

    job_id = _first(raw, "id", "hr_id")
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
        enc_id=_stringify(_first(raw, "enc_id", "encrypted_id")),
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
        gaps=gaps,
        blockers=blockers,
        posted_at=(opp.posted_at or "")[:10] or None,
    )


def rows_from(
    payload: Any,
    *,
    route: str,
    profile=None,
    drop_test_records: bool = True,
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
    return ([to_talent_row(raw, profile=profile) for raw in kept], meta, notes)


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


def to_talent_profile(payload: Any) -> TalentProfileResult:
    """His real Uplers profile. Raises when the envelope is not a profile.

    Refuses to return an empty profile for an unexpected payload, because an
    empty Uplers profile and an unreadable one lead to opposite actions: the
    first says "go and fill your profile in", the second says "this client is
    broken".
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

    skills = _skill_names(_first(details, "skills", "talent_skills", "skill") or [])
    titles = _skill_names(_first(details, "roles", "job_roles", "preferred_roles") or [])
    # `first_name` is deliberately NOT in this chain: listing it here made the
    # concat below unreachable, so a profile carrying first_name + last_name
    # silently lost the surname.
    name = _stringify(_first(details, "full_name", "name"))
    if not name:
        first = details.get("first_name") or ""
        last = details.get("last_name") or ""
        name = ("%s %s" % (first, last)).strip() or None

    return TalentProfileResult(
        name=name,
        headline=_first(details, "headline", "title", "designation", "current_designation"),
        years_experience=shaping.to_float(
            _first(details, "total_experience", "experience", "yoe", "year_of_exp")
        ),
        location=_first(details, "city", "location", "current_location"),
        skills=skills,
        titles=titles,
        notice_period=_stringify(
            _first(details, "notice_period", "joining_period", "availability_to_join")
        ),
        availability=_stringify(_first(details, "availability", "engagement_type")),
        completion_percentage=shaping.to_float(payload.get("profile_completion_percentage")),
        remaining_percentage=shaping.to_float(payload.get("profile_remaining_percentage")),
        sections_present=sorted(key for key in details if details.get(key) not in (None, "", [], {})),
    )


def _stringify(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, dict):
        return _first(value, "name", "title", "label", "value")
    return str(value)


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
    """VERIFIED envelope: `res.status == "success"` and `res.data` is an array."""
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
    return ([to_interview(row) for row in rows if isinstance(row, dict)], notes)


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


def compare_profiles(local, remote: TalentProfileResult) -> tuple[list[str], list[FieldDiff], list[str], list[str]]:
    """`(agree, differ, only_local_skills, only_uplers_skills)`.

    Compares only fields both sides actually have. A field the Uplers profile
    does not report is not a disagreement - it is a silence, and reporting a
    silence as a conflict would bury the real ones.
    """
    agree: list[str] = []
    differ: list[FieldDiff] = []

    def compare(field: str, local_value, remote_value, note: str | None = None) -> None:
        if remote_value in (None, "", [], {}):
            return
        if local_value in (None, "", [], {}):
            differ.append(
                FieldDiff(
                    field=field,
                    local="(not set)",
                    uplers=str(remote_value),
                    note="Only Uplers has this.",
                )
            )
            return
        if str(local_value).strip().lower() == str(remote_value).strip().lower():
            agree.append(field)
        else:
            differ.append(
                FieldDiff(
                    field=field,
                    local=str(local_value),
                    uplers=str(remote_value),
                    note=note,
                )
            )

    compare("name", getattr(local, "name", None), remote.name)
    compare("headline", getattr(local, "headline", None), remote.headline)
    compare(
        "years_experience",
        getattr(local, "years_experience", None),
        remote.years_experience,
        "Fit scores use the local value.",
    )
    compare("location", getattr(local, "location", None), remote.location)
    compare(
        "notice_period",
        getattr(local, "notice_period_days", None),
        remote.notice_period,
        "THE decisive field on this board - most Uplers clients accept only 15-30 days.",
    )

    local_skills = _norm_skills(getattr(local, "skills", []) or [])
    remote_skills = _norm_skills(remote.skills or [])
    only_local = sorted(local_skills[key] for key in local_skills.keys() - remote_skills.keys())
    only_remote = sorted(remote_skills[key] for key in remote_skills.keys() - local_skills.keys())
    if local_skills and remote_skills and not (only_local or only_remote):
        agree.append("skills")

    return (agree, differ, only_local, only_remote)
