"""Typed shapes returned by the tools.

The raw API record has 112 top-level fields, most of which are internal ATS
bookkeeping (credit_type, rootle_campaign_id, matcherArray...). Handing all of
that to a model wastes tokens and buries the signal, so every tool returns one
of these projections instead.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
