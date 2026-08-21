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


class TalentProfileResult(Compact):
    """His real Uplers profile, as Uplers holds it.

    This is the profile RECRUITERS see and the one their matching runs against,
    which is why a thin one here directly limits what he is shown - regardless
    of how complete the local `data/profile.json` is.
    """

    name: str | None = None
    headline: str | None = None
    years_experience: float | None = None
    location: str | None = None
    skills: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    notice_period: str | None = None
    availability: str | None = None
    completion_percentage: float | None = Field(
        None, description="Uplers' own profile-completeness score"
    )
    remaining_percentage: float | None = None
    sections_present: list[str] = Field(
        default_factory=list, description="Which blocks talent_details actually carried"
    )
    notes: list[str] = Field(default_factory=list)


class FieldDiff(Compact):
    field: str | None = None
    local: str | None = None
    uplers: str | None = None
    note: str | None = None


class ProfileComparison(Compact):
    """Local profile vs Uplers profile. Reports; never overwrites.

    The local profile is what every fit score in this server is computed
    against. The Uplers profile is what actually gets him shown to clients.
    They can disagree, and which one is WRONG is a judgement only he can make -
    so this surfaces both and recommends, and a write needs a separate,
    explicit call.
    """

    agree: list[str] = Field(default_factory=list)
    differ: list[FieldDiff] = Field(default_factory=list)
    only_local: list[str] = Field(default_factory=list, description="Skills only on the local profile")
    only_uplers: list[str] = Field(default_factory=list, description="Skills only on the Uplers profile")
    local: ProfileSummary | None = None
    uplers: ProfileSummary | None = None
    recommendation: str | None = None
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
