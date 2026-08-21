"""Typed shapes for the authenticated tier.

Separate from `models.py` on purpose. Those models describe the PUBLIC
catalogue, where a record is just a job advert. These describe the same board
seen through his own account, where every row additionally carries what HE has
done about it - applied, saved, dismissed, and what Uplers' recruiters have
since done with it.

Two conventions carry over from `models.py` and one is new:

* Everything derives from :class:`~uplers_server.models.Compact`, so a field
  with nothing to say costs no tokens. Every field therefore has a default.
* Composite values render as one short string rather than a nested object.
* NEW: **local state and Uplers state never share a field.** `RankedRow.status`
  is what the operator told this server he did; `TalentRow.uplers_status` is
  what Uplers' own pipeline says. Merging them would let a local guess
  overwrite the authoritative record, which is the entire reason the
  authenticated tier is worth building.
"""

from __future__ import annotations

from pydantic import Field

from .models import Compact, ProfileSummary


class TalentRow(Compact):
    """One requisition as HIS account sees it.

    Carries both identifier spaces because the API is not consistent about
    which it wants: `id` is what an apply takes, `enc_id` is what a save takes,
    and `hr_number` is what everything else takes. Dropping either would make a
    row un-actionable without a second fetch.
    """

    hr_number: str | None = None
    title: str | None = None
    company: str | None = Field(None, description="The END CLIENT")
    role: str | None = None
    mode: str | None = Field(None, description="Remote | Hybrid | Onsite")
    city: str | None = None
    pay: str | None = Field(None, description="USD/year band, or 'confidential'")
    notice: str | None = Field(None, description="Notice period the client accepts")
    min_years_experience: float | None = None

    job_id: int | None = Field(
        None, description="Numeric id. This is what uplers_apply sends as hr_id."
    )
    enc_id: str | None = Field(
        None, description="Encrypted id. What the save/unsave route sends as hr_id."
    )

    applied: bool | None = Field(None, description="You have expressed interest. NOT reversible.")
    saved: bool | None = Field(None, description="Bookmarked on Uplers (their flag, not this server's)")
    not_interested: bool | None = Field(None, description="You dismissed it. Reversible.")
    uplers_status: str | None = Field(
        None, description="Uplers' OWN pipeline status, e.g. 'Interviewed'. Authoritative."
    )
    uplers_badge: str | None = Field(
        None, description="Uplers' badge, e.g. 'Slots Given', 'Interview Scheduled'"
    )

    score: int | None = Field(None, description="jobcore fit score, 0-100, when scored")
    verdict: str | None = None
    gaps: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    posted_at: str | None = None
    explain: dict | None = Field(
        None,
        description=(
            "The arithmetic behind `score`, when called with explain=True: "
            "weights, base components, bonuses and their cap, verdict band, "
            "and the scoring_hash. Absent unless asked for, and absent anyway "
            "when score=False - an unscored row has nothing to explain."
        ),
    )


class TalentFeed(Compact):
    """A page of the personalised feed. Always says what it searched."""

    rows: list[TalentRow] = Field(default_factory=list)
    returned: int = 0
    page: int | None = None
    last_page: int | None = None
    total: int | None = Field(None, description="Uplers' own jobs_count, when asked for")
    pages_fetched: int = 1
    source: str | None = Field(None, description="Which authenticated route produced this")
    filters_applied: dict = Field(default_factory=dict)
    scored_against: ProfileSummary | None = None
    notes: list[str] = Field(default_factory=list)


class PipelineResult(Compact):
    """His actual Uplers pipeline - the applications Uplers is acting on."""

    rows: list[TalentRow] = Field(default_factory=list)
    returned: int = 0
    page: int | None = None
    last_page: int | None = None
    pages_fetched: int = 1
    by_status: dict = Field(default_factory=dict, description="Counts of Uplers' own statuses")
    by_badge: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ExperienceEntry(Compact):
    """One role on his Uplers profile. Dates as given; no salary, ever."""

    title: str | None = None
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = Field(None, description="Absent means current")
    is_current: bool | None = None


class EducationEntry(Compact):
    degree: str | None = None
    university: str | None = None
    end_date: str | None = None


class ProjectEntry(Compact):
    """Title and description only. `project_url` is deliberately not read."""

    title: str | None = None
    description: str | None = None


class TalentProfileResult(Compact):
    """His real Uplers profile, as Uplers holds it. AUTHORITATIVE.

    This is the profile RECRUITERS see and the one Uplers' own matching runs
    against. It is also, by the operator's explicit instruction, the record of
    record: the local `data/profile.json` exists only so fit scores have a
    candidate to score against, and where the two disagree this one wins.

    **Nothing private is modelled here.** Pay (`current_ctc`, `expected_ctc`,
    `monthly_salary`), contact route (`contact_number`, `email`,
    `whatsapp_optin`), identity (`dob`, `address`) and the personal file URLs
    (`resume_url`, `profile_pic_url`) all arrive in the same payload and none
    of them has a field on this model. That is not an oversight to be tidied up
    later - `tests/test_talent_profile_real.py` asserts their absence, because
    a shaped profile ends up in transcripts, logs and reports.

    **Three skill lists, not one.** Uplers stores skills in three separate
    sections and they do not mean the same thing to its matching, so they are
    reported separately rather than merged into a number he cannot act on.
    """

    name: str | None = None
    headline: str | None = None
    years_experience: float | None = None
    location: str | None = None

    skills: list[str] = Field(
        default_factory=list,
        description="The `skills` section: everything on the profile, in Uplers' own order.",
    )
    primary_skills: list[str] = Field(
        default_factory=list,
        description=(
            "The `primaryskills` section - a subset of `skills` and, on the evidence "
            "of the live record, the technical half. These are what Uplers matches on."
        ),
    )
    tools: list[str] = Field(
        default_factory=list,
        description="The `tools` section: a separate Uplers master, largely overlapping skills.",
    )
    skill_years: dict[str, float] = Field(
        default_factory=dict,
        description="Per-skill years, for the few skills Uplers records one against.",
    )
    unresolved_skill_ids: list[str] = Field(
        default_factory=list,
        description="Skill ids with no name in the masters lookup. Reported, never dropped silently.",
    )

    titles: list[str] = Field(default_factory=list)
    objective: str | None = Field(None, description="His profile summary, as written")
    notice_period: str | None = None
    availability: str | None = None
    engagement_types: list[str] = Field(
        default_factory=list,
        description=(
            "Uplers' `preferred_modes`: 'Full time' / 'Contract'. NOT the local profile's "
            "preferred_modes, which is Remote/Hybrid/Office - see work_mode_preference."
        ),
    )
    work_mode_preference: str | None = Field(
        None, description="'Remote Only' or 'Remote or Office', from `preferred_method`."
    )
    preferred_cities: list[str] = Field(default_factory=list)
    account_status: str | None = Field(None, description="Uplers' own standing, e.g. 'In Network'")

    experiences: list[ExperienceEntry] = Field(default_factory=list)
    educations: list[EducationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)

    completion_percentage: float | None = Field(
        None, description="Uplers' own profile-completeness score"
    )
    remaining_percentage: float | None = None
    sections_present: list[str] = Field(
        default_factory=list,
        description=(
            "Which blocks talent_details actually carried. Key NAMES only, and the "
            "private ones are filtered out - naming them discloses what he has filled in."
        ),
    )
    notes: list[str] = Field(default_factory=list)

    def all_skill_names(self) -> list[str]:
        """Every distinct name across the three sections, first spelling wins."""
        seen: dict[str, str] = {}
        for name in list(self.skills) + list(self.primary_skills) + list(self.tools):
            seen.setdefault(str(name).strip().lower(), str(name).strip())
        return list(seen.values())


class FieldDiff(Compact):
    field: str | None = None
    local: str | None = None
    uplers: str | None = None
    note: str | None = None


class ProfileComparison(Compact):
    """Local profile vs Uplers profile. Reports; never overwrites either.

    **The Uplers profile is the source of truth.** He maintains it, recruiters
    read it, and Uplers' matching runs on it. The local `data/profile.json` is
    a scoring input - a cache of him, not a record of him. So a gap between the
    two is a defect in the LOCAL copy, and the fix flows local <- Uplers.

    This tool used to have that backwards: it recommended adding local skills
    to Uplers, which is telling him to edit the authoritative record to match
    its own cache.

    The exception is a genuine two-sided disagreement - a headline, a years
    figure - where neither side is obviously right. Those go to
    `needs_your_decision` and stay there. The server does not arbitrate them.
    """

    source_of_truth: str = Field(
        "uplers",
        description="Which side wins a conflict. Always 'uplers'; stated so the output carries its own premise.",
    )
    agree: list[str] = Field(default_factory=list)
    differ: list[FieldDiff] = Field(default_factory=list)
    needs_your_decision: list[FieldDiff] = Field(
        default_factory=list,
        description="Two-sided disagreements this server refuses to resolve for you.",
    )
    only_local: list[str] = Field(
        default_factory=list,
        description="Skills the local profile has that Uplers does not list. Kept, not deleted.",
    )
    only_uplers: list[str] = Field(
        default_factory=list,
        description="Skills on Uplers and missing locally - every fit score is computed without them.",
    )
    uplers_skill_sections: dict = Field(
        default_factory=dict,
        description="Counts per Uplers section: skills / primary_skills / tools / distinct.",
    )
    local: ProfileSummary | None = None
    uplers: ProfileSummary | None = None
    recommendation: str | None = None
    notes: list[str] = Field(default_factory=list)


class FieldChange(Compact):
    field: str | None = None
    before: str | None = None
    after: str | None = None


class ProfileWriteResult(Compact):
    """A write to HIS Uplers profile - proposed, or performed.

    The only result type in this server that describes changing the person
    rather than acting on a requisition, and the fields reflect that. It
    carries the EXACT request rather than a summary, because the caller is
    being asked to authorise a REPLACEMENT write and the array is the
    decision - a summary cannot be reasoned about, and "add Rust" that quietly
    ships 62 rows is exactly the shape of the accident this guards against.
    """

    applied: bool = Field(
        False, description="False means this was a preview and NOTHING was sent."
    )
    request_method: str | None = None
    request_path: str | None = None
    request_body: dict = Field(
        default_factory=dict,
        description="The exact JSON that would be, or was, POSTed. Not a summary.",
    )
    skills_before: int | None = None
    skills_after: int | None = None
    skills_added: list[str] = Field(default_factory=list)
    skills_removed: list[str] = Field(default_factory=list)
    snapshot_id: str | None = Field(
        None, description="Restore point taken BEFORE the write. Pass to uplers_restore_profile()."
    )
    verified: bool | None = Field(
        None, description="Re-read after the write and the list matched. None = not checked."
    )
    notes: list[str] = Field(default_factory=list)


class SnapshotEntry(Compact):
    snapshot_id: str | None = None
    taken_at: str | None = None
    label: str | None = None
    skills: int | None = None


class SnapshotList(Compact):
    """Restore points, newest first. Reads disk only; needs no session."""

    snapshots: list[SnapshotEntry] = Field(default_factory=list)
    directory: str | None = None
    notes: list[str] = Field(default_factory=list)


class ProfileSyncResult(Compact):
    """What a local <- Uplers sync did, or would do. One direction only.

    There is no counterpart flowing the other way and there will not be one:
    this server never writes to his Uplers profile.
    """

    applied: bool = Field(False, description="False means this was a preview and nothing was written.")
    direction: str = Field("local <- uplers", description="The only direction that exists.")
    skills_before: int | None = None
    skills_after: int | None = None
    skills_added: list[str] = Field(default_factory=list)
    skills_removed: list[str] = Field(
        default_factory=list,
        description="Empty under the default union. Only a replace can populate it.",
    )
    local_only_kept: list[str] = Field(
        default_factory=list,
        description="Local skills Uplers does not list, kept because a fit score should know them.",
    )
    fields_changed: list[FieldChange] = Field(default_factory=list)
    left_for_you: list[FieldDiff] = Field(
        default_factory=list, description="Contested fields not touched. Pass them to `also=` to take Uplers'."
    )
    backup_path: str | None = Field(
        None, description="The pre-sync local profile, written before anything changed."
    )
    notes: list[str] = Field(default_factory=list)


class AuthStatus(Compact):
    """Measured, never inferred. `authenticated` may honestly be False or None."""

    authenticated: bool | None = Field(
        None, description="True/False measured against the API. None = could not determine."
    )
    reason: str | None = None
    signed_in_as: str | None = None
    token_present: bool | None = None
    token_format: str | None = None
    saved_at: str | None = None
    expires_at: str | None = Field(None, description="Only knowable for a JWT; None means ask the server")
    expired: bool | None = None
    profile_completion_percentage: float | None = None
    checked_against: str | None = Field(None, description="The exact request this verdict came from")
    error: str | None = None
    notes: list[str] = Field(default_factory=list)


class LoginResult(Compact):
    """Never carries the token, a prefix of it, or its length."""

    authenticated: bool | None = None
    reason: str | None = None
    signed_in_as: str | None = None
    method: str | None = None
    elapsed_seconds: float | None = None
    checks_run: int | None = None
    checked_against: str | None = None
    verified_by: str | None = None
    window_closed: bool | None = None
    token_present: bool | None = None
    guest_token_present: bool | None = None
    profile_completion_percentage: float | None = None
    session: dict = Field(default_factory=dict)
    error: str | None = None
    notes: list[str] = Field(default_factory=list)


class Interview(Compact):
    company: str | None = None
    company_id: int | None = None
    role: str | None = None
    status: str | None = None
    scheduled_at: str | None = None
    feedback_given: bool | None = None


class InterviewList(Compact):
    interviews: list[Interview] = Field(default_factory=list)
    count: int = 0
    notes: list[str] = Field(default_factory=list)


class FieldReport(Compact):
    """What the authenticated view of a job carries that the public one does not.

    Exists because that difference is the whole justification for the
    authenticated tier: if the two records were identical there would be no
    reason to hold a session at all.
    """

    hr_number: str | None = None
    title: str | None = None
    only_in_authenticated: list[str] = Field(default_factory=list)
    only_in_public: list[str] = Field(default_factory=list)
    in_both: int = 0
    values: dict = Field(
        default_factory=dict, description="Values of the authenticated-only fields, truncated"
    )
    notes: list[str] = Field(default_factory=list)


class WritePreview(Compact):
    """Exactly what a write WOULD send. Returned whenever confirm is False.

    `performed` is present and False on every preview, rather than omitted, so
    "it did not happen" is stated rather than inferred from a missing key.
    """

    action: str | None = None
    hr_number: str | None = None
    title: str | None = None
    company: str | None = None
    method: str | None = None
    endpoint: str | None = None
    body: dict = Field(default_factory=dict)
    reversible: bool | None = None
    performed: bool = False
    warning: str | None = None
    to_confirm: str | None = Field(None, description="The exact call that would perform this")
    notes: list[str] = Field(default_factory=list)


class WriteResult(Compact):
    action: str | None = None
    hr_number: str | None = None
    title: str | None = None
    company: str | None = None
    performed: bool = False
    reversible: bool | None = None
    reverse_with: str | None = Field(None, description="The call that undoes this, when one exists")
    response: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
