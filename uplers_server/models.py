"""Typed shapes returned by the tools.

The raw API record has 112 top-level fields, most of which are internal ATS
bookkeeping (credit_type, rootle_campaign_id, matcherArray...). Handing all of
that to a model wastes tokens and buries the signal, so every tool returns one
of these projections instead.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_serializer

from .profile import Profile


class SkillSet(BaseModel):
    must_have: list[str] = Field(default_factory=list)
    good_to_have: list[str] = Field(default_factory=list)


class PayBand(BaseModel):
    currency: str | None = None
    text: str | None = Field(None, description="Uplers' own rendering, e.g. 'INR 9,00,000-15,00,000 / year'")
    local_min: int | None = Field(None, description="Low end in the listed currency. None with a set local_max means an 'Upto X' ceiling.")
    local_max: int | None = None
    local_period: str | None = Field(None, description="'year' or 'month' - Uplers quotes contract roles monthly, so never compare local_* across records without this")
    usd_year_min: int | None = Field(None, description="Uplers' own USD/year normalisation - use this to compare across currencies")
    usd_year_max: int | None = None
    confidential: bool = False


class ShiftWindow(BaseModel):
    timezone: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    ist_window: str | None = None


class CompanyInfo(BaseModel):
    name: str | None = Field(None, description="The END CLIENT. This is the field LinkedIn hides behind 'Uplers'.")
    industry: str | None = None
    team_size: str | None = None
    website: str | None = None
    linkedin: str | None = None
    about: str | None = None


class Assessment(BaseModel):
    name: str | None = None
    tool: str | None = None
    duration: str | None = None
    difficulty: str | None = None


class Opportunity(BaseModel):
    """Compact search-result row."""

    hr_number: str
    title: str | None = None
    role: str | None = Field(None, description="Uplers' normalised role title")
    company: str | None = Field(None, description="End client name")
    industry: str | None = None
    mode_of_work: str | None = Field(None, description="Remote | Hybrid | Office")
    city: str | None = None
    min_years_experience: float | None = None
    max_years_experience: float | None = Field(None, description="None means no stated upper bound")
    pay: PayBand = Field(default_factory=PayBand)
    joining_period: str | None = Field(None, description="Notice period the client will accept")
    availability: str | None = Field(None, description="Full Time | Part Time")
    duration_type: str | None = Field(None, description="Long Term | Short Term")
    skills: SkillSet = Field(default_factory=SkillSet)
    assessments_required: int = 0
    posted_at: str | None = Field(None, description="Creation time decoded from the HR number, native ids only")
    created_at: str | None = Field(None, description="created_at as reported by the API")
    is_native: bool = Field(True, description="False means an aggregated posting scraped from elsewhere")
    job_nature: str | None = None
    talents_count: int | None = Field(None, description="How many Uplers candidates match; high numbers mean a crowded requisition")
    url: str | None = None


class OpportunityDetail(Opportunity):
    """Everything a human needs to decide whether to chase a requisition."""

    description: str | None = Field(None, description="Job description, HTML stripped")
    description_truncated: bool = False
    company_info: CompanyInfo = Field(default_factory=CompanyInfo)
    shift: ShiftWindow = Field(default_factory=ShiftWindow)
    assessments: list[Assessment] = Field(default_factory=list)
    office_visit_frequency: str | None = None
    hiring_model: str | None = Field(None, description="PricingName, e.g. Direct-hire / Hire a Contractor")
    payroll: str | None = None
    positions_open: int | None = None
    status_note: str | None = Field(None, description="HR_Status, e.g. 'Reposted'")
    experience_flexible: bool = False


class SearchResult(BaseModel):
    """Search always reports what it searched, so an empty list is never ambiguous."""

    results: list[Opportunity] = Field(default_factory=list)
    matched: int = 0
    returned: int = 0
    searched: int = Field(0, description="Cached records the filters ran against")
    cohort: str = Field("native", description="native | native+aggregated")
    filters_applied: dict = Field(default_factory=dict)
    index_synced_at: str | None = None
    notes: list[str] = Field(default_factory=list)


class NewSinceResult(BaseModel):
    since: str
    results: list[Opportunity] = Field(default_factory=list)
    matched: int = 0
    returned: int = 0
    known_native_ids: int = 0
    unhydrated: list[str] = Field(
        default_factory=list,
        description="New native ids that are known but not yet fetched - run uplers_sync_index()",
    )
    index_synced_at: str | None = None
    notes: list[str] = Field(default_factory=list)


class SyncResult(BaseModel):
    sitemap_entries: int = 0
    ids_in_this_fetch: int = 0
    new_ids: int = 0
    new_native_ids: int = 0
    new_aggregated_ids: int = 0
    total_known_ids: int = 0
    total_known_native: int = 0
    total_known_aggregated: int = 0
    total_known_unknown_kind: int = 0
    records_fetched: int = 0
    records_cached_total: int = 0
    native_records_missing: int = 0
    requests_made: int = 0
    ratelimit_remaining: int | None = None
    newest_native: list[str] = Field(default_factory=list)
    failures: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class PayStats(BaseModel):
    n_with_pay: int = 0
    usd_year_min_p25: int | None = None
    usd_year_min_median: int | None = None
    usd_year_min_p75: int | None = None
    usd_year_max_median: int | None = None
    usd_year_overall_low: int | None = None
    usd_year_overall_high: int | None = None


class StatsGroup(BaseModel):
    key: str
    count: int
    pay: PayStats = Field(default_factory=PayStats)
    median_min_yoe: float | None = None
    remote_share: float | None = Field(None, description="Fraction of this group with ModeOfWork == Remote")
    top_skills: list[str] = Field(default_factory=list)
    currencies: dict[str, int] = Field(default_factory=dict)
    joining_periods: dict[str, int] = Field(default_factory=dict)
    example_companies: list[str] = Field(default_factory=list)


class MarketStats(BaseModel):
    group_by: str
    cohort: str
    population: int = Field(0, description="Records the aggregation ran over, after filters")
    groups: list[StatsGroup] = Field(default_factory=list)
    overall: StatsGroup | None = None
    filters_applied: dict = Field(default_factory=dict)
    index_synced_at: str | None = None
    notes: list[str] = Field(default_factory=list)


# ==========================================================================
# Tier 2: profile-aware shapes.
#
# Everything below is built for TOKEN ECONOMY. The operator's constraint on
# this server is per-use cost: a tool result is read by a model on every
# single call, forever, whereas the code that shapes it is written once. So
# these models are small on purpose, they render composite values as one
# short string instead of a nested object, and they omit any field that has
# nothing to say.
#
# `Compact` is what does the omitting: a field that is None or an empty
# list/dict/string never reaches the wire. Every field therefore carries a
# default, which also keeps it out of the JSON schema's `required` list -
# otherwise the pruning would produce output the MCP client rejects.
# ==========================================================================


class Compact(BaseModel):
    """A model that does not spend tokens saying nothing."""

    @model_serializer(mode="wrap")
    def _prune_empty(self, handler):
        data = handler(self)
        if not isinstance(data, dict):  # pragma: no cover - defensive
            return data
        return {key: value for key, value in data.items() if value not in (None, [], {}, "")}


class RankedRow(Compact):
    """One scored requisition, as small as it can be and still be actionable.

    No URL and no description: `hr_number` is the key to
    uplers_get_opportunity, and repeating a 60-character URL on every row of
    every ranking would be the single largest avoidable cost in this server.
    """

    hr_number: str | None = None
    title: str | None = None
    company: str | None = Field(None, description="The END CLIENT")
    score: int | None = Field(None, description="jobcore fit score, 0-100")
    verdict: str | None = None
    mode: str | None = None
    city: str | None = None
    pay: str | None = Field(None, description="USD/year band, or 'confidential'")
    notice: str | None = Field(None, description="Notice period the client accepts")
    must_have: str | None = Field(None, description="Must-have skills covered, e.g. '4/5'")
    gaps: list[str] = Field(default_factory=list, description="Top missing skills")
    flags: list[str] = Field(default_factory=list, description="Soft caveats")
    blockers: list[str] = Field(default_factory=list, description="Hard incompatibilities")
    posted_at: str | None = None
    saved: bool | None = None
    status: str | None = Field(None, description="Your tracked status, if any")
    explain: dict | None = Field(
        None,
        description=(
            "The arithmetic behind `score`, when the tool was called with "
            "explain=True: weights, the two base components and their "
            "combination, the bonus table and its cap, the verdict band, and "
            "the scoring_hash. Absent unless asked for."
        ),
    )


class ProfileSummary(Compact):
    """One line of "who was this scored against", so a score is never orphaned."""

    years_experience: float | None = None
    location: str | None = None
    skills: int | None = Field(None, description="Number of skills on the profile")
    notice_period_days: int | None = None
    min_pay_usd_year: int | None = None
    expected_pay_usd_year: int | None = Field(
        None,
        description="The USD/year figure the +5 salary bonus was scored against",
    )
    policy_hash: str | None = Field(
        None,
        description=(
            "Fingerprint of the WHOLE policy - the scoring arithmetic AND the "
            "candidate block it was layered with. This is the config-identity "
            "hash: it answers 'was this scored under the same setup', and it "
            "is what an approval gate compares."
        ),
    )
    scoring_hash: str | None = Field(
        None,
        description=(
            "Fingerprint of the ARITHMETIC ALONE - weights, bonuses, caps, "
            "verdict bands. THIS is the comparability field: two scores "
            "carrying the same one were produced by the same sums and can be "
            "compared directly; two carrying different ones cannot. It is the "
            "value stamped on a scored result and reported by uplers_config(), "
            "and it matches the Naukri server's for the same arithmetic. It "
            "deliberately differs from policy_hash, which also covers the "
            "candidate."
        ),
    )


class ProfileResult(Compact):
    profile: Profile | None = None
    path: str | None = None
    seeded_from_resume: bool = False
    config_source: str | None = Field(
        None,
        description="The shared jobhunt.json this scoring ran under, or None for built-in defaults",
    )
    field_source: dict = Field(
        default_factory=dict,
        description=(
            "Per field: 'config' when the shared candidate block supplied it, 'local' "
            "when data/profile.json did. Provenance, not emptiness, decides - "
            "notice_period_days defaults to 0 and 0 is also a real answer."
        ),
    )
    notes: list[str] = Field(default_factory=list)


class ConfigReport(Compact):
    """Where this server's numbers come from, and what was refused."""

    source: str | None = Field(
        None, description="The jobhunt.json in use, or None for built-in defaults"
    )
    status: str | None = Field(None, description="Loaded from X, or every path tried")
    revision: int | None = Field(None, description="The file's compare-and-swap token")
    policy_rev: int | None = Field(
        None, description="Counter the loader advances on every NEW fingerprint it sees"
    )
    policy_hash: str | None = Field(
        None,
        description=(
            "Fingerprint of the whole policy: the scoring arithmetic AND the "
            "candidate block. Config identity - 'is this the same setup'."
        ),
    )
    scoring_hash: str | None = Field(
        None,
        description=(
            "Fingerprint of the arithmetic alone. This is the one to compare "
            "against a scored result's stamp: equal means the result was "
            "produced by the sums currently in force. Different from "
            "policy_hash by construction, because that one also covers the "
            "candidate."
        ),
    )
    candidate: dict = Field(default_factory=dict)
    scoring: dict = Field(default_factory=dict)
    server: dict = Field(default_factory=dict, description="The servers.uplers block")
    field_source: dict = Field(
        default_factory=dict, description="Per profile field: 'config' or 'local'"
    )
    provenance: dict = Field(
        default_factory=dict, description="Per config key: 'file' or 'default'"
    )
    refused: list[str] = Field(
        default_factory=list,
        description="Tier C keys the file tried to set. Refused loudly, never ignored.",
    )
    unknown_keys: list[str] = Field(
        default_factory=list, description="Keys in the file that nothing reads"
    )
    searched: list[str] = Field(
        default_factory=list, description="Every path tried, when no file was found"
    )
    write: dict = Field(
        default_factory=dict, description="Result of a write_candidate=True call"
    )
    notes: list[str] = Field(default_factory=list)


class FitAssessment(Compact):
    """The full reasoning for one requisition. Bigger than a row, on purpose."""

    hr_number: str | None = None
    title: str | None = None
    company: str | None = None
    score: int | None = None
    verdict: str | None = None
    skills_matched: list[str] = Field(default_factory=list)
    skills_missing: list[str] = Field(default_factory=list)
    must_have_covered: int | None = None
    must_have_required: int | None = None
    must_have_missing: list[str] = Field(default_factory=list)
    experience: dict = Field(default_factory=dict)
    bonuses: dict = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    pay: str | None = None
    mode: str | None = None
    notice: str | None = None
    assessments: int | None = None
    url: str | None = None
    saved: bool | None = None
    status: str | None = None
    explain: dict | None = Field(
        None,
        description=(
            "The arithmetic behind `score`, when called with explain=True: "
            "weights, the two base components and their combination, the "
            "bonus table and its cap, the verdict band, and the scoring_hash. "
            "Absent unless asked for."
        ),
    )
    scored_against: ProfileSummary | None = None
    notes: list[str] = Field(default_factory=list)


class RankResult(Compact):
    rows: list[RankedRow] = Field(default_factory=list)
    returned: int = 0
    ranked: int = Field(0, description="Requisitions that survived filters and blockers")
    blocked: int = Field(0, description="Excluded for a hard incompatibility")
    scanned: int = Field(0, description="Cached records considered")
    cohort: str = "native"
    filters_applied: dict = Field(default_factory=dict)
    scored_against: ProfileSummary | None = None
    index_synced_at: str | None = None
    notes: list[str] = Field(default_factory=list)


class SavedJob(Compact):
    hr_number: str | None = None
    title: str | None = None
    company: str | None = None
    saved_at: str | None = None
    note: str | None = None
    score: int | None = None
    pay: str | None = None
    notice: str | None = None
    status: str | None = None
    still_listed: bool | None = Field(
        None, description="False means the record is no longer in the local index"
    )
    explain: dict | None = Field(
        None,
        description=(
            "The arithmetic behind `score`, when called with explain=True. "
            "Absent unless asked for, and absent anyway when score=False - "
            "there is no score to explain."
        ),
    )


class SavedList(Compact):
    saved: list[SavedJob] = Field(default_factory=list)
    count: int = 0
    scored: bool = Field(False, description="Whether fit scores were computed this call")
    notes: list[str] = Field(default_factory=list)


class SaveResult(Compact):
    hr_number: str | None = None
    title: str | None = None
    company: str | None = None
    created: bool | None = Field(None, description="False means an existing entry was updated")
    removed: bool | None = None
    saved_total: int = 0
    notes: list[str] = Field(default_factory=list)


class TrackedJob(Compact):
    hr_number: str | None = None
    title: str | None = None
    company: str | None = None
    status: str | None = None
    notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    days_since_update: int | None = None
    history: list[str] = Field(default_factory=list, description="'status@date' transitions")


class TrackResult(Compact):
    hr_number: str | None = None
    title: str | None = None
    company: str | None = None
    status: str | None = None
    previous_status: str | None = None
    created: bool | None = None
    counts: dict = Field(default_factory=dict, description="Your pipeline, by status")
    notes: list[str] = Field(default_factory=list)


class TrackedList(Compact):
    tracked: list[TrackedJob] = Field(default_factory=list)
    count: int = 0
    counts: dict = Field(default_factory=dict)
    needs_follow_up: list[str] = Field(
        default_factory=list, description="hr_numbers sitting in an active status too long"
    )
    notes: list[str] = Field(default_factory=list)


class AlertSpec(Compact):
    id: int | None = None
    name: str | None = None
    criteria: dict = Field(default_factory=dict)
    created_at: str | None = None
    last_evaluated_at: str | None = None
    matches: int | None = Field(None, description="Total current matches, when evaluated")
    new_matches: int | None = Field(None, description="Matches not previously reported")
    rows: list[RankedRow] = Field(default_factory=list)


class AlertList(Compact):
    alerts: list[AlertSpec] = Field(default_factory=list)
    count: int = 0
    evaluated: bool = False
    notes: list[str] = Field(default_factory=list)


class AlertResult(Compact):
    id: int | None = None
    name: str | None = None
    criteria: dict = Field(default_factory=dict)
    created: bool | None = None
    deleted: bool | None = None
    matches_now: int | None = None
    alerts_total: int = 0
    notes: list[str] = Field(default_factory=list)


class BriefSection(Compact):
    count: int = 0
    rows: list[RankedRow] = Field(default_factory=list)
    note: str | None = None


class DailyBrief(Compact):
    """The tool he will call most, so the one that must stay smallest."""

    generated_at: str | None = None
    since: str | None = Field(None, description="Start of the window this brief covers")
    index: dict = Field(default_factory=dict, description="Freshness of the local index")
    new_opportunities: BriefSection | None = None
    alert_hits: list[AlertSpec] = Field(default_factory=list)
    shortlist: dict = Field(default_factory=dict)
    pipeline: dict = Field(default_factory=dict)
    follow_up: list[RankedRow] = Field(default_factory=list)
    scored_against: ProfileSummary | None = None
    actions: list[str] = Field(default_factory=list, description="What to do next, if anything")
    notes: list[str] = Field(default_factory=list)


class SkillGapRow(Compact):
    skill: str | None = None
    roles: int | None = Field(None, description="Native requisitions naming this skill")
    as_must_have: int | None = None
    sole_blocker: int | None = Field(
        None,
        description="Roles where this is the ONLY must-have you lack - learning it alone unlocks them",
    )
    median_pay_usd: int | None = None
    pay_delta_usd: int | None = Field(None, description="Median pay minus the cohort median")
    example_companies: list[str] = Field(default_factory=list)


class SkillGapResult(Compact):
    population: int = 0
    cohort_median_pay_usd: int | None = None
    your_skills_in_demand: list[SkillGapRow] = Field(default_factory=list)
    missing_skills: list[SkillGapRow] = Field(default_factory=list)
    unused_skills: list[str] = Field(
        default_factory=list, description="Profile skills no native requisition asks for"
    )
    coverage: str | None = Field(None, description="Share of demanded skills you already have")
    scored_against: ProfileSummary | None = None
    notes: list[str] = Field(default_factory=list)


class CompanyIntel(Compact):
    company: str | None = None
    industry: str | None = None
    team_size: str | None = None
    website: str | None = None
    linkedin: str | None = None
    about: str | None = None
    open_requisitions: int = 0
    roles: list[str] = Field(default_factory=list)
    pay_usd_year: str | None = None
    modes: dict = Field(default_factory=dict)
    joining_periods: dict = Field(default_factory=dict)
    top_skills: list[str] = Field(default_factory=list)
    assessments_required: int | None = None
    first_posted: str | None = None
    latest_posted: str | None = None
    median_min_yoe: float | None = None
    best_fit: RankedRow | None = None
    your_history: list[str] = Field(default_factory=list, description="Saved/tracked with this client")
    rows: list[RankedRow] = Field(default_factory=list)
    candidates: list[str] = Field(
        default_factory=list, description="Other end clients matching the name, when ambiguous"
    )
    notes: list[str] = Field(default_factory=list)


class SchedulerStatus(Compact):
    enabled: bool = False
    running: bool = False
    interval_seconds: int | None = None
    owner: str | None = Field(None, description="Which process currently holds the sync lease")
    holds_lease: bool | None = None
    lease_expires_at: str | None = None
    last_sync: str | None = None
    last_auto_sync_at: str | None = None
    last_attempt_at: str | None = Field(
        None, description="Last sync ATTEMPT, success or not - the retry brake reads this"
    )
    last_auto_sync_result: str | None = None
    last_error: str | None = None
    runs: int = 0
    notes: list[str] = Field(default_factory=list)
