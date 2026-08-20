"""Uplers MCP server - read-only reader for the public Uplers talent board.

Five tools over one unauthenticated public endpoint
(`/api/single-hr-public`, explicitly Allow-ed in robots.txt) plus the public
sitemap. No login, no account, no mutations, no browser.

The board has two populations and the difference is the whole point:

  NATIVE (~235 live)  - real Uplers requisitions. The record names the END
                        CLIENT, which is exactly what LinkedIn hides behind
                        "Uplers". Typed skills, pay band, notice period,
                        shift window, required assessments.
  AGGREGATED (~39k)   - postings scraped from elsewhere and republished.
                        Ordinary Indian corporate jobs already covered by
                        JobSpy and the Naukri MCP. Noise here, so every tool
                        defaults to native-only.
"""

from __future__ import annotations

import inspect
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# httpx logs every request at INFO. On a stdio transport that is noise at best
# and protocol corruption at worst, so it is muted before anything imports it.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

try:  # mcp >= 2.0 renamed FastMCP to MCPServer; the API is the same.
    from mcp.server import MCPServer as _Server
except ImportError:  # pragma: no cover - exercised only on mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from uplers_server import (
    __version__,
    alerts as alerts_mod,
    brief as brief_mod,
    config,
    fit,
    ids,
    insight,
    profile as prof,
    scheduler as sched_mod,
    search as search_mod,
    sync as sync_mod,
)
from uplers_server.client import UplersClient, UplersError
from uplers_server.models import (
    AlertList,
    AlertResult,
    AlertSpec,
    BriefSection,
    CompanyIntel,
    DailyBrief,
    FitAssessment,
    MarketStats,
    NewSinceResult,
    OpportunityDetail,
    ProfileResult,
    ProfileSummary,
    RankedRow,
    RankResult,
    SaveResult,
    SavedJob,
    SavedList,
    SchedulerStatus,
    SearchResult,
    SkillGapResult,
    SkillGapRow,
    SyncResult,
    TrackedJob,
    TrackedList,
    TrackResult,
)
from uplers_server.shaping import to_detail, to_opportunity
from uplers_server.store import Store

INSTRUCTIONS = (
    "Read-only reader and personal tracker for the Uplers talent board. Its unique "
    "value is the END CLIENT COMPANY NAME on Uplers-native requisitions, which job "
    "boards hide. Call uplers_sync_index() first (it builds the local index); after "
    "that everything is served from the local cache and costs no network. "
    "uplers_daily_brief() is the usual entry point, uplers_rank_opportunities() the "
    "main search. Scoring is jobcore's, shared with the Naukri server, so a fit score "
    "means the same thing on both. This server NEVER applies to anything: "
    "uplers_track() records what the human already did."
)

# mcp 1.x FastMCP has no `version` parameter; mcp 2.x MCPServer does.
_kwargs = {"instructions": INSTRUCTIONS}
if "version" in inspect.signature(_Server.__init__).parameters:
    _kwargs["version"] = __version__

mcp = _Server("uplers", **_kwargs)


def _open_store() -> Store:
    return Store()


def _no_cache_error(store: Store) -> UplersError:
    return UplersError(
        "The local Uplers index is empty (0 cached job records at %s). "
        "This is NOT 'no matching jobs' - nothing has been indexed yet. "
        "Run uplers_sync_index() first; it takes a few minutes on the first run."
        % store.path
    )


# ---------------------------------------------------------------- tool 1 ---


@mcp.tool()
async def uplers_sync_index(
    hydrate: bool = True,
    fetch_budget: int = config.DEFAULT_SYNC_FETCH_BUDGET,
    refresh_stale: bool = True,
) -> SyncResult:
    """Build/refresh the local Uplers index. RUN THIS FIRST, and periodically after.

    Fetches the public sitemap, UNIONs every requisition id it contains into a
    persistent local store, decodes creation timestamps from native ids, then
    fetches the job records for native requisitions that are missing or stale.

    Why the union matters: the Uplers sitemap is non-deterministic - three
    consecutive fetches returned 33,160 / 39,608 / 10,811 entries. Ids are
    therefore never removed on absence, and running this repeatedly is safe
    and strictly improves coverage.

    Use it: before the first search of a session, and any time you want the
    freshest board (roughly daily is plenty; the board turns over slowly).

    Args:
        hydrate: also fetch job records for native ids. False = index ids only.
        fetch_budget: cap on records fetched this run. Re-run to continue.
        refresh_stale: also re-fetch records older than the 24h cache TTL.
    """
    with _open_store() as store:
        async with UplersClient() as client:
            return await sync_mod.sync_index(
                store,
                client,
                hydrate=hydrate,
                fetch_budget=fetch_budget,
                refresh_stale=refresh_stale,
            )


# ---------------------------------------------------------------- tool 2 ---


@mcp.tool()
async def uplers_search_opportunities(
    skill: str | None = None,
    title: str | None = None,
    company: str | None = None,
    min_yoe: float | None = None,
    max_yoe: float | None = None,
    yoe_admits: float | None = None,
    mode_of_work: str | None = None,
    remote_only: bool = False,
    currency: str | None = None,
    min_pay_usd_year: int | None = None,
    joining_period: str | None = None,
    min_notice_days: int | None = None,
    include_aggregated: bool = False,
    sort: str = "newest",
    limit: int = 20,
) -> SearchResult:
    """Search Uplers requisitions. Native-only by default - keep it that way.

    Runs against the local index (Uplers has no public search endpoint), so
    uplers_sync_index() must have run at least once. An empty index raises
    rather than returning an empty list, so "no results" always means
    "no matches", never "the fetch failed".

    Use it: to find roles where you can see WHO the end client actually is,
    with a typed pay band, notice period and skill split. Its edge over a
    generic job board is data quality on a small native cohort, not volume.

    Args:
        skill: substring-matched against must-have AND good-to-have skills.
        title: substring-matched against the job title and normalised role.
        company: substring-matched against the END CLIENT name.
        min_yoe / max_yoe: bound the role's OWN required minimum experience.
        yoe_admits: your years of experience; keeps only roles whose band
            admits you (role_min <= you <= role_max). Usually the one you want.
        mode_of_work: exact match on Remote / Hybrid / Office.
        remote_only: shorthand for mode_of_work="Remote".
        currency: exact match on INR / USD / GBP.
        min_pay_usd_year: floor on the band's top end, in Uplers' own USD/year
            normalisation - the only cross-currency-comparable pay figure.
        joining_period: substring match, e.g. "30 Days" or "Immediately".
        min_notice_days: keep only roles accepting at least this many days of
            notice. Most of the board wants 15-30 days, so this filter is the
            fastest way to find out whether the board is usable at all.
        include_aggregated: opt in to the ~39k scraped postings. Off by default
            because they duplicate JobSpy/Naukri coverage and drown the signal.
        sort: newest | oldest | pay_desc | pay_asc | least_competition.
        limit: max rows returned; `matched` reports the true total.
    """
    filters = {
        "skill": skill,
        "title": title,
        "company": company,
        "min_yoe": min_yoe,
        "max_yoe": max_yoe,
        "yoe_admits": yoe_admits,
        "mode_of_work": mode_of_work,
        "remote_only": remote_only,
        "currency": currency,
        "min_pay_usd_year": min_pay_usd_year,
        "joining_period": joining_period,
        "min_notice_days": min_notice_days,
    }
    with _open_store() as store:
        counts = store.count_records()
        if counts["total"] == 0:
            raise _no_cache_error(store)
        if not include_aggregated and counts["native"] == 0:
            raise UplersError(
                "The index holds %d record(s) but none are Uplers-native, so a "
                "native-only search cannot return anything. Run uplers_sync_index(), "
                "or pass include_aggregated=True to search the scraped cohort."
                % counts["total"]
            )

        results, matched, scanned = search_mod.search_records(
            (raw for raw, _ in store.iter_records(include_aggregated=include_aggregated)),
            sort=sort,
            limit=max(1, limit),
            **filters,
        )
        applied = {k: v for k, v in filters.items() if v not in (None, False)}
        notes = []
        if sort not in search_mod.SORTS:
            notes.append("Unknown sort %r; fell back to 'newest'." % sort)
        if matched == 0:
            notes.append(
                "Zero matches against %d cached record(s). The index IS populated, so "
                "this is a genuine empty result. Loosen a filter - min_notice_days and "
                "min_pay_usd_year are the usual culprits." % scanned
            )
        if matched > len(results):
            notes.append("Showing %d of %d matches; raise `limit` for more." % (len(results), matched))
        if include_aggregated:
            if counts["aggregated"] == 0:
                notes.append(
                    "include_aggregated=True had no effect: %d aggregated id(s) are indexed "
                    "but uplers_sync_index() deliberately fetches records only for native "
                    "requisitions, so none are cached to search. That is by design - the "
                    "aggregated cohort duplicates JobSpy and Naukri coverage."
                    % store.count_ids().get(ids.KIND_AGGREGATED, 0)
                )
            else:
                notes.append(
                    "include_aggregated=True: results mix real Uplers requisitions with "
                    "scraped postings. Check `is_native` on each row."
                )
        return SearchResult(
            results=results,
            matched=matched,
            returned=len(results),
            searched=scanned,
            cohort="native+aggregated" if include_aggregated else "native",
            filters_applied=applied,
            index_synced_at=store.last_sync,
            notes=notes,
        )


# ---------------------------------------------------------------- tool 3 ---


@mcp.tool()
async def uplers_get_opportunity(
    hr_number: str,
    refresh: bool = False,
    full_description: bool = False,
) -> OpportunityDetail:
    """Full record for one requisition, by its HR number (e.g. "HR030826155648").

    Served from the local cache when fresh, otherwise fetched live. Works for
    any id, native or aggregated, whether or not it has been indexed.

    Returns the things that make Uplers worth reading at all: the END CLIENT
    company with its industry and blurb, must-have vs good-to-have skills, the
    pay band in both local currency and USD/year, the shift window in IST,
    the notice period the client will accept, and any assessments required.

    Use it: after a search, on any row worth pursuing. Also fine as a direct
    lookup when someone pastes an Uplers URL or HR number.

    Args:
        hr_number: the requisition id, with or without the "HR" prefix casing.
        refresh: ignore the cache and re-fetch from Uplers.
        full_description: return the whole job description instead of the
            first few thousand characters.
    """
    normalised = ids.normalise(hr_number)
    if not ids.is_valid(normalised):
        raise UplersError(
            "%r is not a valid Uplers HR number. Expected 'HR' followed by digits, "
            "e.g. HR030826155648 (native) or HR1173448373079993 (aggregated)." % hr_number
        )

    with _open_store() as store:
        cached = None if refresh else store.get_record(normalised)
        if cached is not None:
            fresh = store.stale_or_missing([normalised], config.RECORD_TTL_SECONDS)
            if not fresh:
                return to_detail(cached[0], full_description=full_description)

        async with UplersClient() as client:
            raw = await client.get_record(normalised)  # raises loudly on failure
        store.put_record(normalised, raw)
        store.union_ids({normalised: None})
        return to_detail(raw, full_description=full_description)


# ---------------------------------------------------------------- tool 4 ---


@mcp.tool()
async def uplers_list_new_since(
    iso_date: str,
    limit: int = 50,
    include_unhydrated: bool = True,
) -> NewSinceResult:
    """Native requisitions created on or after `iso_date`. Cheap - no network.

    Native Uplers ids encode their own creation time (DDMMYYHHMMSS), so this
    answers "what is new" straight from the local id store without fetching
    anything. Ids known but not yet fetched are reported in `unhydrated`
    rather than being quietly dropped.

    Use it: as a daily/weekly "what appeared since I last looked" check, after
    uplers_sync_index(). Aggregated postings are excluded by design - their
    ids carry no timestamp.

    Args:
        iso_date: "2026-08-01" or a full ISO timestamp.
        limit: max rows returned.
        include_unhydrated: list known-but-unfetched ids (recommended).
    """
    since = iso_date.strip()
    if not since:
        raise UplersError("iso_date is required, e.g. '2026-08-01'.")
    if len(since) == 10:
        since += "T00:00:00"

    with _open_store() as store:
        candidates = store.native_ids(since_iso=since, newest_first=True)
        cached = store.cached_ids()
        hydrated = [h for h in candidates if h in cached]
        unhydrated = [h for h in candidates if h not in cached]

        raws = []
        for hr_number in hydrated[: max(1, limit)]:
            record = store.get_record(hr_number)
            if record:
                raws.append(record[0])
        results, _, _ = search_mod.search_records(raws, sort="newest", limit=limit)
        # `matched` counts every hydrated candidate, not just the page returned.
        matched = len(hydrated)

        notes = []
        if matched > len(results):
            notes.append(
                "Showing %d of %d matching requisition(s); raise `limit` for more."
                % (len(results), matched)
            )
        total_native = store.count_ids().get(ids.KIND_NATIVE, 0)
        if total_native == 0:
            raise UplersError(
                "The local id store knows about 0 native requisitions, so nothing can "
                "be new. Run uplers_sync_index() first."
            )
        if unhydrated:
            notes.append(
                "%d id(s) created since %s are known but not yet fetched. Run "
                "uplers_sync_index() to pull their records." % (len(unhydrated), since)
            )
        if not candidates:
            notes.append(
                "No native requisition in the local store was created on or after %s. "
                "The store knows %d native id(s) in total, so this is a genuine zero."
                % (since, total_native)
            )
        return NewSinceResult(
            since=since,
            results=results,
            matched=matched,
            returned=len(results),
            known_native_ids=total_native,
            unhydrated=unhydrated[:limit] if include_unhydrated else [],
            index_synced_at=store.last_sync,
            notes=notes,
        )


# ---------------------------------------------------------------- tool 5 ---


@mcp.tool()
async def uplers_get_market_stats(
    group_by: str = "role",
    skill: str | None = None,
    title: str | None = None,
    mode_of_work: str | None = None,
    remote_only: bool = False,
    currency: str | None = None,
    min_yoe: float | None = None,
    max_yoe: float | None = None,
    yoe_admits: float | None = None,
    min_group_size: int = 2,
    top_groups: int = 20,
    include_aggregated: bool = False,
) -> MarketStats:
    """Pay bands, experience levels and skill demand across the native cohort.

    Salary-negotiation intelligence, not a listing. Because Uplers publishes a
    normalised USD/year band on most native requisitions, this is one of the
    few places to get comparable pay data for India-based remote work - useful
    when negotiating a role that has nothing to do with Uplers.

    Reports per group: count, USD/year percentiles (p25 / median / p75 of the
    band low, plus the median band high), median required experience, remote
    share, the most-demanded skills, and currency / notice-period splits.
    `overall` carries the same figures for the whole filtered population.

    Use it: "what does a backend role pay", "which skills show up most",
    "how much more do Remote roles pay", "is 5 years enough for this band".

    Args:
        group_by: role | skill | mode_of_work | currency | company |
            joining_period | industry.
        skill / title / mode_of_work / remote_only / currency / min_yoe /
            max_yoe / yoe_admits: narrow the population before aggregating.
        min_group_size: drop groups smaller than this (noise control).
        top_groups: cap on groups returned, largest first.
        include_aggregated: fold in the ~39k scraped postings. Off by default;
            most of them carry no pay data, which skews every figure.
    """
    filters = {
        "skill": skill,
        "title": title,
        "mode_of_work": mode_of_work,
        "remote_only": remote_only,
        "currency": currency,
        "min_yoe": min_yoe,
        "max_yoe": max_yoe,
        "yoe_admits": yoe_admits,
    }
    with _open_store() as store:
        counts = store.count_records()
        if counts["total"] == 0:
            raise _no_cache_error(store)
        stats = search_mod.market_stats(
            (raw for raw, _ in store.iter_records(include_aggregated=include_aggregated)),
            group_by=group_by,
            min_group_size=min_group_size,
            top_groups=top_groups,
            cohort="native+aggregated" if include_aggregated else "native",
            filters_applied={k: v for k, v in filters.items() if v not in (None, False)},
            **filters,
        )
        stats.index_synced_at = store.last_sync
        if group_by not in search_mod.GROUP_BYS:
            stats.notes.insert(
                0, "Unknown group_by %r; grouped by 'role' instead." % group_by
            )
        stats.notes.append(
            "Pay figures are Uplers' own USD/year normalisation, present on most "
            "native requisitions and absent on confidential ones; n_with_pay says how "
            "many records actually carried a band."
        )
        return stats



# ==========================================================================
# Tier 2 - the profile-aware half of the server.
#
# Tools 1-5 above answer "what is on the board". Everything below answers
# "what is on the board FOR ME, and what have I done about it", which is the
# difference between a search box and an instrument. All of it is local: the
# scoring is jobcore's, the state is sqlite, and not one of these tools makes
# a network request except where it must fetch a record it has never seen.
#
# APPLYING IS NOT HERE AND NEVER WILL BE. uplers_track records what the human
# already did; it does not act on their behalf. Uplers' apply, outreach,
# resume-tailoring and referral endpoints are their paid candidate products
# and need an authenticated session this server deliberately does not have.
# ==========================================================================


def _load_pairs(store: Store, *, include_aggregated: bool = False):
    """(raw, Opportunity) for every cached record. Raises on an empty index."""
    counts = store.count_records()
    if counts["total"] == 0:
        raise _no_cache_error(store)
    pairs = [
        (raw, to_opportunity(raw))
        for raw, _ in store.iter_records(include_aggregated=include_aggregated)
    ]
    if not pairs:
        raise UplersError(
            "The index holds %d record(s) but none are Uplers-native. Run "
            "uplers_sync_index(), or pass include_aggregated=True." % counts["total"]
        )
    return pairs


def _load_opportunities(store: Store, *, include_aggregated: bool = False):
    return [opp for _, opp in _load_pairs(store, include_aggregated=include_aggregated)]


def _profile_summary(profile) -> ProfileSummary:
    """Attached to every scored result, so a score is never orphaned from
    the profile it was computed against."""
    return ProfileSummary(
        years_experience=profile.years_experience,
        location=profile.location,
        skills=len(profile.skills),
        notice_period_days=profile.notice_period_days,
        min_pay_usd_year=profile.min_pay_usd_year,
    )


def _profile_notes(profile, *, seeded: bool) -> list[str]:
    notes = []
    if seeded:
        notes.append(
            "No profile existed, so one was seeded from your resume at %s. Check it, "
            "then correct anything wrong with uplers_set_profile()." % (prof.resume_path() or "?")
        )
    if profile.notice_period_days is None:
        notes.append(
            "notice_period_days is not set. It is the single most decisive field on this "
            "board - 121 of 235 native requisitions want 15 days and only 4 accept more "
            "than 30 - so until it is set, no role can be ruled out on notice."
        )
    if profile.min_pay_usd_year is None:
        notes.append("min_pay_usd_year is not set, so the +5 salary bonus never applies.")
    return notes


def _require_profile():
    """(profile, notes). Seeds from the resume on first use, loudly."""
    try:
        profile, seeded = prof.load_or_seed()
    except prof.ProfileError as exc:
        raise UplersError(str(exc)) from exc
    if not profile.is_usable():
        raise UplersError(
            "The stored profile has no skills and no years_experience, so every fit score "
            "would be meaningless. Set it with uplers_set_profile(skills=[...], "
            "years_experience=...)."
        )
    return (profile, _profile_notes(profile, seeded=seeded))


def _ensure_scheduler() -> None:
    """Start background freshness on first use, inside the running event loop.

    Lazy rather than at import for two reasons: importing this module in a
    test must not spawn a network task, and a server nobody calls should not
    sync. Both MCP clients that register `uplers` run their own copy, so the
    task itself is lease-guarded - see scheduler.py.
    """
    if not sched_mod.enabled():
        return
    try:
        scheduler = sched_mod.get_scheduler()
        if not scheduler.running:
            scheduler.start()
    except RuntimeError:  # pragma: no cover - no running loop (direct import)
        pass


def _record_for(store: Store, hr_number: str) -> dict:
    """The cached raw record, or None. Never fetches."""
    cached = store.get_record(hr_number)
    return cached[0] if cached else None


async def _record_or_fetch(store: Store, hr_number: str) -> dict:
    """Cached record, falling back to one live fetch that fails loudly."""
    cached = _record_for(store, hr_number)
    if cached is not None:
        return cached
    async with UplersClient() as client:
        raw = await client.get_record(hr_number)
    store.put_record(hr_number, raw)
    store.union_ids({hr_number: None})
    return raw


def _validate_hr(hr_number: str) -> str:
    normalised = ids.normalise(hr_number)
    if not ids.is_valid(normalised):
        raise UplersError(
            "%r is not a valid Uplers HR number. Expected 'HR' followed by digits, "
            "e.g. HR030826155648." % hr_number
        )
    return normalised


# ---------------------------------------------------------------- tool 6 ---


@mcp.tool()
async def uplers_get_profile() -> ProfileResult:
    """Show the candidate profile every fit score is computed against.

    On first call, seeds itself from the resume markdown in
    `job-hunting/resumes/` (override with the UPLERS_RESUME environment
    variable) and says so. It never invents a profile: if there is no resume
    and nothing has been set, it raises rather than scoring you as a blank.

    Use it: before trusting any score, and whenever a ranking looks wrong -
    the usual cause is a stale skill list or an unset notice period.
    """
    _ensure_scheduler()
    try:
        profile, seeded = prof.load_or_seed()
    except prof.ProfileError as exc:
        raise UplersError(str(exc)) from exc
    return ProfileResult(
        profile=profile,
        path=str(prof.profile_path()),
        seeded_from_resume=seeded,
        notes=_profile_notes(profile, seeded=seeded),
    )


# ---------------------------------------------------------------- tool 7 ---


@mcp.tool()
async def uplers_set_profile(
    skills: list[str] | None = None,
    add_skills: list[str] | None = None,
    remove_skills: list[str] | None = None,
    years_experience: float | None = None,
    location: str | None = None,
    titles: list[str] | None = None,
    preferred_modes: list[str] | None = None,
    min_pay_usd_year: int | None = None,
    notice_period_days: int | None = None,
    avoid_companies: list[str] | None = None,
    headline: str | None = None,
    name: str | None = None,
    reseed_from_resume: bool = False,
) -> ProfileResult:
    """Update the profile. Only the arguments you pass are changed.

    Everything downstream keys off this: fit scores, ranking, alerts with a
    min_score, the daily brief and the skill gap.

    Use it: to set `notice_period_days` (the one field that decides whether
    this board is usable for you at all), to add a skill you have picked up,
    or to correct whatever the resume parser got wrong.

    Args:
        skills: REPLACE the whole skill list. Spelling does not matter -
            jobcore's taxonomy maps "reactjs", "react.js" and "React" together.
        add_skills / remove_skills: incremental edits, applied after `skills`.
        years_experience: total professional years, drives 40% of every score.
        location: your city, e.g. "Bangalore, India". Earns +5 when a role
            names the same city, and Remote roles earn it regardless.
        titles: roles you are targeting.
        preferred_modes: any of Remote / Hybrid / Office. A role outside them
            is flagged, never hidden.
        min_pay_usd_year: floor in Uplers' USD/year normalisation. Roles below
            it are flagged; roles at or above it earn the +5 salary bonus.
        notice_period_days: days you need before joining. Roles that accept
            fewer become BLOCKED rather than badly scored.
        avoid_companies: end clients to exclude from ranking entirely.
        reseed_from_resume: discard everything and re-read the resume.
    """
    _ensure_scheduler()
    if reseed_from_resume:
        try:
            profile = prof.seed_from_resume()
        except prof.ProfileError as exc:
            raise UplersError(str(exc)) from exc
    else:
        try:
            profile, _ = prof.load_or_seed()
        except prof.ProfileError:
            profile = prof.Profile()

    if skills is not None:
        profile.skills = list(skills)
    if add_skills:
        for skill in add_skills:
            if skill and skill not in profile.skills:
                profile.skills.append(skill)
    if remove_skills:
        drop = {s.strip().lower() for s in remove_skills if s}
        profile.skills = [s for s in profile.skills if s.strip().lower() not in drop]
    if years_experience is not None:
        profile.years_experience = years_experience
    if location is not None:
        profile.location = location
    if titles is not None:
        profile.titles = list(titles)
    if preferred_modes is not None:
        unknown = [
            mode
            for mode in preferred_modes
            if mode.strip().lower() not in {m.lower() for m in prof.MODES}
        ]
        if unknown:
            raise UplersError(
                "Unknown mode(s) %s. Uplers uses exactly: %s."
                % (", ".join(unknown), ", ".join(prof.MODES))
            )
        profile.preferred_modes = list(preferred_modes)
    if min_pay_usd_year is not None:
        profile.min_pay_usd_year = min_pay_usd_year
    if notice_period_days is not None:
        profile.notice_period_days = notice_period_days
    if avoid_companies is not None:
        profile.avoid_companies = list(avoid_companies)
    if headline is not None:
        profile.headline = headline
    if name is not None:
        profile.name = name
    if not reseed_from_resume:
        profile.source = "manual"

    path = prof.save(profile)
    notes = _profile_notes(profile, seeded=reseed_from_resume)
    if not profile.is_usable():
        notes.insert(
            0,
            "This profile has neither skills nor years_experience, so scoring tools will "
            "refuse to run against it.",
        )
    return ProfileResult(profile=profile, path=str(path), notes=notes)


# ---------------------------------------------------------------- tool 8 ---


@mcp.tool()
async def uplers_assess_fit(hr_number: str, refresh: bool = False) -> FitAssessment:
    """Score ONE requisition against your profile, with the full reasoning.

    The score is jobcore's - the same engine the Naukri server uses, so a 78
    here means what a 78 means there. On top of it this reports what Uplers
    uniquely publishes: how many of the client's MUST-HAVE skills you cover
    (a role can score well on good-to-haves while missing every mandatory
    one), and any hard `blockers` such as a notice period the client will not
    accept.

    Blockers are never folded into the score. A 90 you cannot take is more
    useful labelled than quietly turned into a 70.

    Use it: on any row from a search or ranking that you are considering, and
    before spending an evening on an assessment.

    Args:
        hr_number: the requisition id, e.g. "HR030826155648".
        refresh: re-fetch the record from Uplers before scoring.
    """
    _ensure_scheduler()
    normalised = _validate_hr(hr_number)
    profile, notes = _require_profile()
    with _open_store() as store:
        if refresh:
            async with UplersClient() as client:
                raw = await client.get_record(normalised)
            store.put_record(normalised, raw)
        else:
            raw = await _record_or_fetch(store, normalised)
        opp = to_opportunity(raw)
        if not opp.is_native:
            notes.append(
                "This is an AGGREGATED posting scraped from elsewhere, not an Uplers "
                "requisition. It carries no end-client detail and no typed skill split, "
                "so the score rests on thinner data than a native record."
            )
        assessment = fit.assess(opp, profile)
        must = assessment["must_have"]
        return FitAssessment(
            hr_number=opp.hr_number,
            title=opp.title,
            company=opp.company,
            score=assessment["overall_score"],
            verdict=assessment["recommendation"],
            skills_matched=assessment["skill_match"]["matched"],
            skills_missing=assessment["skill_match"]["missing"],
            must_have_covered=must["covered"],
            must_have_required=must["required"],
            must_have_missing=must["missing"],
            experience=assessment["experience_match"],
            bonuses=assessment.get("bonuses") or {},
            blockers=assessment["blockers"],
            flags=assessment["flags"],
            reasons=assessment["reasons"],
            pay=fit.render_pay(opp),
            mode=opp.mode_of_work,
            notice=opp.joining_period,
            assessments=opp.assessments_required or None,
            url=opp.url,
            saved=store.is_saved(normalised) or None,
            status=(store.get_tracked(normalised) or {}).get("status"),
            scored_against=_profile_summary(profile),
            notes=notes,
        )


# ---------------------------------------------------------------- tool 9 ---


@mcp.tool()
async def uplers_rank_opportunities(
    limit: int = 10,
    min_score: int | None = None,
    exclude_blocked: bool = True,
    skill: str | None = None,
    title: str | None = None,
    company: str | None = None,
    mode_of_work: str | None = None,
    remote_only: bool = False,
    currency: str | None = None,
    min_pay_usd_year: int | None = None,
    joining_period: str | None = None,
    min_notice_days: int | None = None,
    max_yoe: float | None = None,
    include_aggregated: bool = False,
    saved_only: bool = False,
) -> RankResult:
    """Rank the native cohort against your profile. The main tool of this server.

    Scores every cached requisition with jobcore, drops the ones you are
    hard-blocked from, and returns the best few as compact rows - a count of
    what matched plus the rows worth reading, not 235 records.

    Ordering is the fit score, with must-have coverage as the tiebreak; the
    tiebreak decides which of two equal scores to read first and never changes
    a score.

    Use it: as the daily "what should I look at" question, and after any
    profile edit to see what moved. Drill into a row with uplers_assess_fit()
    or uplers_get_opportunity().

    Args:
        limit: rows returned. `ranked` reports how many qualified.
        min_score: floor on the fit score, e.g. 60 for "worth applying".
        exclude_blocked: keep out roles with a hard incompatibility (a notice
            period you cannot meet, none of the must-have skills, a company on
            your avoid list). Set False to see them WITH their blockers listed.
        skill / title / company / mode_of_work / remote_only / currency /
            min_pay_usd_year / joining_period / min_notice_days / max_yoe:
            narrow the population before scoring, same meanings as
            uplers_search_opportunities.
        include_aggregated: fold in the ~39k scraped postings. Off by default.
        saved_only: rank just your shortlist.
    """
    _ensure_scheduler()
    profile, notes = _require_profile()
    filters = {
        "skill": skill,
        "title": title,
        "company": company,
        "mode_of_work": mode_of_work,
        "remote_only": remote_only,
        "currency": currency,
        "min_pay_usd_year": min_pay_usd_year,
        "joining_period": joining_period,
        "min_notice_days": min_notice_days,
        "max_yoe": max_yoe,
    }
    with _open_store() as store:
        population = _load_opportunities(store, include_aggregated=include_aggregated)
        scanned = len(population)
        saved_ids = store.saved_ids()
        tracked = store.tracked_ids()
        if saved_only:
            population = [opp for opp in population if opp.hr_number in saved_ids]
            if not population:
                notes.append(
                    "saved_only=True but your shortlist is empty, or none of it is in the "
                    "local index. Add roles with uplers_save_job()."
                )
        population = [opp for opp in population if search_mod.matches(opp, **filters)]
        ranked, blocked = fit.rank(population, profile, exclude_blocked=exclude_blocked)
        if min_score is not None:
            ranked = [pair for pair in ranked if pair[1]["overall_score"] >= min_score]
        rows = [
            fit.to_row(
                opp,
                assessment,
                saved=opp.hr_number in saved_ids,
                status=tracked.get(opp.hr_number),
            )
            for opp, assessment in ranked[: max(1, limit)]
        ]
        if blocked and exclude_blocked:
            notes.append(
                "%d requisition(s) were excluded for a hard blocker. Pass "
                "exclude_blocked=False to see them and why." % blocked
            )
        if not ranked:
            notes.append(
                "Zero requisitions qualified out of %d cached record(s). The index IS "
                "populated, so this is a genuine empty result, not a failed fetch. Lower "
                "min_score, loosen a filter, or set exclude_blocked=False." % scanned
            )
        if len(ranked) > len(rows):
            notes.append("Showing %d of %d; raise `limit` for more." % (len(rows), len(ranked)))
        return RankResult(
            rows=rows,
            returned=len(rows),
            ranked=len(ranked),
            blocked=blocked,
            scanned=scanned,
            cohort="native+aggregated" if include_aggregated else "native",
            filters_applied={
                key: value
                for key, value in dict(filters, min_score=min_score, saved_only=saved_only).items()
                if value not in (None, False)
            },
            scored_against=_profile_summary(profile),
            index_synced_at=store.last_sync,
            notes=notes,
        )


# --------------------------------------------------------------- tool 10 ---


@mcp.tool()
async def uplers_save_job(hr_number: str, note: str | None = None) -> SaveResult:
    """Add a requisition to your local shortlist.

    Stores a title/company snapshot alongside the id, so the shortlist keeps
    reading correctly even after Uplers closes the requisition and the record
    stops being fetchable. If the record is not cached it is fetched once,
    which fails loudly rather than saving a bare id.

    Use it: on anything from a ranking worth a second look. Saving is private
    and local - it tells Uplers nothing and applies to nothing.

    Args:
        hr_number: the requisition id.
        note: why you saved it. Free text, shown in uplers_list_saved().
    """
    _ensure_scheduler()
    normalised = _validate_hr(hr_number)
    with _open_store() as store:
        raw = await _record_or_fetch(store, normalised)
        opp = to_opportunity(raw)
        created = store.save_job(
            normalised, note=note, title=opp.title, company=opp.company
        )
        return SaveResult(
            hr_number=normalised,
            title=opp.title,
            company=opp.company,
            created=created,
            saved_total=len(store.saved_ids()),
            notes=(
                []
                if created
                else ["Already on the shortlist; the note and snapshot were updated."]
            ),
        )


# --------------------------------------------------------------- tool 11 ---


@mcp.tool()
async def uplers_list_saved(score: bool = True, limit: int = 25) -> SavedList:
    """Your shortlist, optionally re-scored against the current profile.

    Re-scoring matters: a profile edit changes what a saved role is worth, and
    a role saved three weeks ago may now be blocked by a notice period you have
    since recorded. `still_listed: false` marks entries whose record has fallen
    out of the local index.

    Use it: to review what you have collected, and to see which saved roles
    have no tracked status yet.

    Args:
        score: compute a current fit score for each entry. Costs nothing but
            local CPU; set False if you only want the list.
        limit: maximum entries returned, newest save first.
    """
    _ensure_scheduler()
    with _open_store() as store:
        rows = store.list_saved()
        notes = []
        profile = None
        if score and rows:
            try:
                profile, notes = _require_profile()
            except UplersError as exc:
                notes = ["Fit scores omitted: %s" % exc]
        tracked = store.tracked_ids()
        out = []
        for row in rows[: max(1, limit)]:
            raw = _record_for(store, row["hr_number"])
            entry = SavedJob(
                hr_number=row["hr_number"],
                title=row["title"],
                company=row["company"],
                saved_at=row["saved_at"],
                note=row["note"],
                status=tracked.get(row["hr_number"]),
                still_listed=raw is not None,
            )
            if raw is not None:
                opp = to_opportunity(raw)
                entry.pay = fit.render_pay(opp)
                entry.notice = opp.joining_period
                if profile is not None:
                    entry.score = fit.assess(opp, profile)["overall_score"]
            out.append(entry)
        if not rows:
            notes.append(
                "Your shortlist is empty. This is a real zero - nothing has been saved "
                "yet. Add entries with uplers_save_job()."
            )
        if len(rows) > len(out):
            notes.append("Showing %d of %d saved." % (len(out), len(rows)))
        return SavedList(
            saved=out, count=len(rows), scored=bool(profile is not None), notes=notes
        )


# --------------------------------------------------------------- tool 12 ---


@mcp.tool()
async def uplers_unsave_job(hr_number: str) -> SaveResult:
    """Remove a requisition from the shortlist.

    Leaves any tracked application history alone - dropping a role from the
    shortlist is not the same as forgetting that you applied to it. Returns
    removed=false when it was not on the list, rather than pretending it was.
    """
    _ensure_scheduler()
    normalised = _validate_hr(hr_number)
    with _open_store() as store:
        removed = store.unsave_job(normalised)
        notes = []
        if not removed:
            notes.append("%s was not on the shortlist; nothing changed." % normalised)
        if store.get_tracked(normalised):
            notes.append(
                "Tracking history for %s was kept - use uplers_update_status(status='closed') "
                "to close it out." % normalised
            )
        return SaveResult(
            hr_number=normalised,
            removed=removed,
            saved_total=len(store.saved_ids()),
            notes=notes,
        )


# --------------------------------------------------------------- tool 13 ---


@mcp.tool()
async def uplers_track(
    hr_number: str, status: str = "interested", notes: str | None = None
) -> TrackResult:
    """Record what YOU did about a requisition. This tool never acts for you.

    Uplers' apply and express-interest endpoints are their paid candidate
    product and need a logged-in session this server deliberately does not
    have. `applied_manually` means you went to their site and applied; nothing
    here submits anything.

    Every call appends to a history, including a repeat of the same status, so
    "still nothing on the 14th" is recorded and the follow-up logic can use it.

    Use it: right after applying on the Uplers site, and whenever a recruiter
    replies.

    Args:
        hr_number: the requisition id.
        status: interested | applied_manually | responded | interviewing |
            rejected | closed.
        notes: free text - who replied, what they asked, what you sent.
    """
    return await _track_impl(hr_number, status, notes)


# --------------------------------------------------------------- tool 14 ---


@mcp.tool()
async def uplers_update_status(
    hr_number: str, status: str, notes: str | None = None
) -> TrackResult:
    """Move an already-tracked requisition to a new status.

    Identical to uplers_track except that it refuses an id you have never
    tracked, so a typo'd HR number cannot quietly create a new pipeline entry
    that looks like progress.

    Use it: when something moves - a reply lands, an interview is scheduled,
    a rejection arrives.

    Args:
        hr_number: an id already in your pipeline.
        status: interested | applied_manually | responded | interviewing |
            rejected | closed.
        notes: what changed.
    """
    normalised = _validate_hr(hr_number)
    with _open_store() as store:
        if store.get_tracked(normalised) is None:
            raise UplersError(
                "%s is not being tracked, so there is no status to update. Use "
                "uplers_track() to start tracking it." % normalised
            )
    return await _track_impl(hr_number, status, notes)


async def _track_impl(hr_number: str, status: str, notes: str | None) -> TrackResult:
    _ensure_scheduler()
    normalised = _validate_hr(hr_number)
    if status not in prof.TRACK_STATUSES:
        raise UplersError(
            "%r is not a tracking status. Use one of: %s. A free-text status would "
            "create a bucket that no follow-up query looks in."
            % (status, ", ".join(prof.TRACK_STATUSES))
        )
    with _open_store() as store:
        raw = _record_for(store, normalised)
        title = company = None
        extra_notes = []
        if raw is None:
            try:
                raw = await _record_or_fetch(store, normalised)
            except UplersError as exc:
                extra_notes.append(
                    "Recorded, but the requisition could not be fetched for a title "
                    "snapshot (%s). The status is stored regardless." % exc
                )
        if raw is not None:
            opp = to_opportunity(raw)
            title, company = opp.title, opp.company
        previous, created = store.track(
            normalised, status, notes=notes, title=title, company=company
        )
        if created and not store.is_saved(normalised):
            store.save_job(normalised, title=title, company=company)
            extra_notes.append("Also added to your shortlist.")
        return TrackResult(
            hr_number=normalised,
            title=title,
            company=company,
            status=status,
            previous_status=previous,
            created=created,
            counts=store.count_tracked_by_status(),
            notes=extra_notes,
        )


# --------------------------------------------------------------- tool 15 ---


@mcp.tool()
async def uplers_list_tracked(
    status: str | None = None, history: bool = False, limit: int = 25
) -> TrackedList:
    """Your application pipeline, most recently touched first.

    `needs_follow_up` lists anything sitting in an active status for a week or
    more - the pipeline's real job is catching applications that went quiet,
    not storing them.

    Use it: as the weekly "where does everything stand" review.

    Args:
        status: filter to one status. Omit for everything.
        history: include the full status trail for each entry. Off by default
            because it multiplies the size of the result.
        limit: maximum entries returned.
    """
    _ensure_scheduler()
    if status is not None and status not in prof.TRACK_STATUSES:
        raise UplersError(
            "%r is not a tracking status. Use one of: %s."
            % (status, ", ".join(prof.TRACK_STATUSES))
        )
    with _open_store() as store:
        rows = store.list_tracked(status)
        out = []
        for row in rows[: max(1, limit)]:
            entry = TrackedJob(
                hr_number=row["hr_number"],
                title=row["title"],
                company=row["company"],
                status=row["status"],
                notes=row["notes"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                days_since_update=brief_mod._days_since(row["updated_at"]),
            )
            if history:
                entry.history = [
                    "%s@%s" % (event["to_status"], (event["at"] or "")[:10])
                    for event in store.tracked_events(row["hr_number"])
                ]
            out.append(entry)
        notes = []
        if not rows:
            notes.append(
                "Nothing is tracked%s. This is a real zero, not a lookup failure - "
                "record an application with uplers_track()."
                % (" with status %r" % status if status else "")
            )
        if len(rows) > len(out):
            notes.append("Showing %d of %d." % (len(out), len(rows)))
        due = brief_mod.follow_up_due(store)
        return TrackedList(
            tracked=out,
            count=len(rows),
            counts=store.count_tracked_by_status(),
            needs_follow_up=[row["hr_number"] for row in due],
            notes=notes,
        )


# --------------------------------------------------------------- tool 16 ---


@mcp.tool()
async def uplers_set_alert(
    name: str,
    skill: str | None = None,
    title: str | None = None,
    company: str | None = None,
    mode_of_work: str | None = None,
    remote_only: bool = False,
    currency: str | None = None,
    min_pay_usd_year: int | None = None,
    joining_period: str | None = None,
    min_notice_days: int | None = None,
    min_yoe: float | None = None,
    max_yoe: float | None = None,
    yoe_admits: float | None = None,
    min_score: int | None = None,
    exclude_blocked: bool = False,
) -> AlertResult:
    """Save a filter that the daily brief evaluates for you.

    Alerts are local. There is no Uplers alert API and no email subscription -
    an alert is a stored filter run against the index this server already
    keeps, so twenty alerts cost zero network requests.

    Each alert reports a requisition EXACTLY ONCE. The brief says "3 new" and
    means three you have not seen. Re-saving the same name changes the
    criteria and clears that memory, so a widened alert reports the matches it
    now covers instead of staying silent about them.

    Use it: for the searches you would otherwise re-run every morning -
    "remote Node roles paying over $40k", "anything at a fintech client".

    Args:
        name: unique label. Re-using one replaces its criteria.
        skill / title / company / mode_of_work / remote_only / currency /
            min_pay_usd_year / joining_period / min_notice_days / min_yoe /
            max_yoe / yoe_admits: the same filters as
            uplers_search_opportunities. At least one is required - an alert
            with no criteria would match the whole board.
        min_score: only fire above this fit score. Needs a profile.
        exclude_blocked: skip roles you are hard-blocked from.
    """
    _ensure_scheduler()
    label = (name or "").strip()
    if not label:
        raise UplersError("An alert needs a name so you can find and delete it later.")
    try:
        criteria = alerts_mod.normalise_criteria(
            {
                "skill": skill,
                "title": title,
                "company": company,
                "mode_of_work": mode_of_work,
                "remote_only": remote_only,
                "currency": currency,
                "min_pay_usd_year": min_pay_usd_year,
                "joining_period": joining_period,
                "min_notice_days": min_notice_days,
                "min_yoe": min_yoe,
                "max_yoe": max_yoe,
                "yoe_admits": yoe_admits,
                "min_score": min_score,
                "exclude_blocked": exclude_blocked,
            }
        )
    except alerts_mod.AlertError as exc:
        raise UplersError(str(exc)) from exc

    with _open_store() as store:
        alert_id, created = store.put_alert(label, criteria)
        notes = []
        matches = None
        try:
            population = _load_opportunities(store)
            profile = None
            if min_score is not None or exclude_blocked:
                profile, profile_notes = _require_profile()
                notes.extend(profile_notes)
            matches = len(alerts_mod.evaluate(population, criteria, profile))
            if matches == 0:
                notes.append(
                    "This alert matches nothing right now. Saved anyway - it will fire "
                    "when something new qualifies - but check the criteria if that is "
                    "a surprise."
                )
        except UplersError as exc:
            notes.append("Saved, but could not be evaluated yet: %s" % exc)
        if not created:
            notes.append(
                "Replaced the existing alert %r and cleared its seen-list, so its next "
                "evaluation reports every current match." % label
            )
        return AlertResult(
            id=alert_id,
            name=label,
            criteria=criteria,
            created=created,
            matches_now=matches,
            alerts_total=len(store.list_alerts()),
            notes=notes,
        )


# --------------------------------------------------------------- tool 17 ---


@mcp.tool()
async def uplers_list_alerts(evaluate: bool = False, rows: int = 3) -> AlertList:
    """Your saved alerts, optionally run right now.

    Use it: to see what is being watched, and to check an alert is not
    silently matching nothing.

    Args:
        evaluate: run each alert against the current index and report how many
            requisitions match and how many are new since it last reported.
            Local only, no network.
        rows: sample rows per alert when evaluating.
    """
    _ensure_scheduler()
    with _open_store() as store:
        stored = store.list_alerts()
        notes = []
        profile = None
        population = []
        if evaluate and stored:
            try:
                population = _load_opportunities(store)
            except UplersError as exc:
                notes.append("Could not evaluate: %s" % exc)
                evaluate = False
            if evaluate and any(
                "min_score" in alert["criteria"] or alert["criteria"].get("exclude_blocked")
                for alert in stored
            ):
                try:
                    profile, profile_notes = _require_profile()
                    notes.extend(profile_notes)
                except UplersError as exc:
                    notes.append("Score-gated alerts skipped: %s" % exc)

        out = []
        saved_ids = store.saved_ids()
        tracked = store.tracked_ids()
        for alert in stored:
            spec = AlertSpec(
                id=alert["id"],
                name=alert["name"],
                criteria=alert["criteria"],
                created_at=alert["created_at"],
                last_evaluated_at=alert["last_evaluated_at"],
            )
            if evaluate:
                try:
                    matches = alerts_mod.evaluate(population, alert["criteria"], profile)
                except Exception as exc:  # noqa: BLE001
                    notes.append("alert %r failed: %s" % (alert["name"], exc))
                    out.append(spec)
                    continue
                by_id = {opp.hr_number: (opp, a) for opp, a in matches}
                new_hits = store.record_alert_hits(alert["id"], list(by_id))
                spec.matches = len(by_id)
                spec.new_matches = len(new_hits)
                spec.rows = [
                    fit.to_row(
                        by_id[hr][0],
                        by_id[hr][1],
                        saved=hr in saved_ids,
                        status=tracked.get(hr),
                        with_flags=False,
                    )
                    for hr in list(by_id)[: max(0, rows)]
                ]
            out.append(spec)
        if not stored:
            notes.append(
                "No alerts are saved. This is a real zero - create one with "
                "uplers_set_alert(name=..., skill=...)."
            )
        return AlertList(alerts=out, count=len(stored), evaluated=evaluate, notes=notes)


# --------------------------------------------------------------- tool 18 ---


@mcp.tool()
async def uplers_delete_alert(name: str) -> AlertResult:
    """Delete an alert by name (or numeric id), with its seen-list.

    Returns deleted=false when there was no such alert, rather than reporting
    a success that did nothing.
    """
    _ensure_scheduler()
    with _open_store() as store:
        existing = store.get_alert(name)
        deleted = store.delete_alert(name)
        notes = []
        if not deleted:
            known = [alert["name"] for alert in store.list_alerts()]
            notes.append(
                "No alert named %r. Known alerts: %s."
                % (name, ", ".join(known) if known else "none")
            )
        return AlertResult(
            id=(existing or {}).get("id"),
            name=name,
            criteria=(existing or {}).get("criteria") or {},
            deleted=deleted,
            alerts_total=len(store.list_alerts()),
            notes=notes,
        )


# --------------------------------------------------------------- tool 19 ---


@mcp.tool()
async def uplers_daily_brief(
    limit: int = 5, since: str | None = None, peek: bool = False
) -> DailyBrief:
    """What changed since last time, ranked by fit. Start the day here.

    Five things in one compact result: index freshness, new native
    requisitions scored against your profile, alerts that fired, shortlist
    entries you have not actioned, and applications that have gone quiet.
    Every section reports a COUNT and at most a handful of rows - the point is
    to be cheap enough to call every morning.

    Calling it advances the window, so the second call of a day is nearly
    empty by design. Use peek=True to look without advancing it.

    Use it: first thing, every day. Drill into anything with
    uplers_assess_fit() or uplers_get_opportunity().

    Args:
        limit: rows per section.
        since: override the window start, e.g. "2026-08-01". Default is the
            last brief, or seven days on the first run.
        peek: do not advance the window or mark alert hits as reported.
    """
    _ensure_scheduler()
    profile, notes = _require_profile()
    with _open_store() as store:
        population = _load_opportunities(store)
        data = brief_mod.build(
            store, profile, population, limit=limit, since=since, peek=peek
        )
        data["notes"] = notes + data["notes"]
        if data.pop("_window_source", None) == "first_brief_7d":
            data["notes"].append(
                "First brief on this machine, so the window defaults to the last 7 days."
            )
        section = data.pop("new_opportunities")
        alert_hits = [AlertSpec(**alert) for alert in data.pop("alert_hits")]
        follow_up = [RankedRow(**row) for row in data.pop("follow_up")]
        return DailyBrief(
            **data,
            new_opportunities=BriefSection(**section),
            alert_hits=alert_hits,
            follow_up=follow_up,
            scored_against=_profile_summary(profile),
        )


# --------------------------------------------------------------- tool 20 ---


@mcp.tool()
async def uplers_skill_gap(top: int = 10, min_roles: int = 2) -> SkillGapResult:
    """Which ONE skill would unlock the most roles, and what it pays.

    Not a popularity chart - uplers_get_market_stats already reports raw
    demand. This answers the personal question: `sole_blocker` counts the
    requisitions where a skill is the ONLY must-have you are missing, so
    learning it alone moves them from ineligible to eligible. A skill named by
    forty roles you would fail anyway is worth less than one gating six you
    would otherwise pass.

    Also reports the pay delta - the median USD/year of roles demanding a
    skill against the cohort median - so "worth learning" has a number
    attached, and `unused_skills`: things on your profile that no native
    requisition asks for.

    Use it: when deciding what to study next, and to sanity-check that your
    profile skills are the ones this board actually buys.

    Args:
        top: rows per section.
        min_roles: ignore skills named by fewer requisitions than this.
    """
    _ensure_scheduler()
    profile, notes = _require_profile()
    with _open_store() as store:
        population = _load_opportunities(store)
        data = insight.skill_gap(population, profile, top=top, min_roles=min_roles)
        unlocks = [row for row in data["missing_skills"] if row.get("sole_blocker")]
        if not unlocks:
            notes.append(
                "No single missing skill is the sole blocker on any requisition, so "
                "there is no one-skill unlock on this board right now - the gaps are "
                "wider than one skill each."
            )
        return SkillGapResult(
            population=data["population"],
            cohort_median_pay_usd=data["cohort_median_pay_usd"],
            your_skills_in_demand=[SkillGapRow(**row) for row in data["your_skills_in_demand"]],
            missing_skills=[SkillGapRow(**row) for row in data["missing_skills"]],
            unused_skills=data["unused_skills"],
            coverage=data["coverage"],
            scored_against=_profile_summary(profile),
            notes=notes,
        )


# --------------------------------------------------------------- tool 21 ---


@mcp.tool()
async def uplers_company_intel(name: str, limit: int = 5) -> CompanyIntel:
    """Everything cached about one END CLIENT, plus its posture on this board.

    The end-client name is the whole reason this server exists - LinkedIn shows
    these requisitions as "Uplers" and stops. Given the name, this returns the
    company blurb, industry, size and website from the embedded company object,
    then aggregates every requisition they have open: how many, which roles,
    the pay range, their notice-period and work-mode habits, the skills they
    keep asking for, and how long they have been hiring.

    A name that matches several distinct clients returns the candidate list
    rather than guessing which one you meant.

    Use it: before an interview, and to spot a client posting five roles at
    once (a real hiring push) versus one stale requisition.

    Args:
        name: end-client name or a fragment, e.g. "Northladder".
        limit: requisition rows returned.
    """
    _ensure_scheduler()
    profile = None
    notes: list[str] = []
    try:
        profile, notes = _require_profile()
    except UplersError as exc:
        notes = ["Fit scores omitted: %s" % exc]
    with _open_store() as store:
        pairs = _load_pairs(store)
        data = insight.company_intel(pairs, name, profile)
        ranked = data.pop("_ranked", [])
        saved_ids = store.saved_ids()
        tracked = store.tracked_ids()
        if not data.get("open_requisitions"):
            if data.get("candidates"):
                notes.append(
                    "%r matches %d different end clients and none exactly. Ask again with "
                    "one of the names in `candidates`."
                    % (name, len(data["candidates"]))
                )
            else:
                notes.append(
                    "No cached native requisition names an end client matching %r. The "
                    "index holds %d record(s), so this is a genuine miss rather than a "
                    "failed lookup - try uplers_search_opportunities(company=...) for a "
                    "looser match." % (name, len(pairs))
                )
            return CompanyIntel(**data, notes=notes)

        rows = [
            fit.to_row(
                opp,
                assessment,
                saved=opp.hr_number in saved_ids,
                status=tracked.get(opp.hr_number),
                with_flags=False,
            )
            for opp, assessment in ranked[: max(1, limit)]
        ]
        history = []
        for opp, _ in ranked:
            if opp.hr_number in tracked:
                history.append("%s: %s" % (opp.hr_number, tracked[opp.hr_number]))
            elif opp.hr_number in saved_ids:
                history.append("%s: saved" % opp.hr_number)
        candidates = data.pop("candidates", [])
        if candidates:
            notes.append(
                "%r also matched %s; showing the exact/only match above."
                % (name, ", ".join(candidates[:5]))
            )
        return CompanyIntel(
            **data,
            best_fit=rows[0] if rows else None,
            rows=rows[1:] if len(rows) > 1 else [],
            your_history=history,
            notes=notes,
        )


# --------------------------------------------------------------- tool 22 ---


@mcp.tool()
async def uplers_scheduler_status() -> SchedulerStatus:
    """Is the index refreshing itself, and which process is doing it.

    A background task syncs the index every few hours so searches are not run
    against a week-old cache. Both Claude Code and Claude Desktop register this
    server and each spawns its own copy, so the duty is guarded by a lease in
    the shared sqlite file - exactly one process syncs, and a process that dies
    mid-sync frees the duty within the lease TTL instead of blocking the other
    forever.

    `owner` naming another process is the healthy two-client case, not a fault.

    Use it: when data looks stale, or to confirm the automatic sync is alive.
    Disable it entirely with UPLERS_AUTO_SYNC=0 in the server's environment.
    """
    _ensure_scheduler()
    scheduler = sched_mod.get_scheduler()
    status = scheduler.status()
    notes = []
    if not status["enabled"]:
        notes.append("Automatic sync is OFF (UPLERS_AUTO_SYNC=0). Run uplers_sync_index() by hand.")
    elif not status["running"]:
        notes.append(
            "The background task is not running in this process yet; it starts on the "
            "first tool call and may be running in the other MCP client's copy."
        )
    if status["owner"] and not status["holds_lease"]:
        notes.append(
            "Another process (%s) holds the sync lease. That is the expected state when "
            "Claude Code and Claude Desktop are both open." % status["owner"]
        )
    return SchedulerStatus(**status, notes=notes)


def main() -> None:
    # The background sync task is started lazily by the first tool call rather
    # than here: mcp.run() owns the event loop, and a task created before it
    # exists would have nowhere to live. See _ensure_scheduler().
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
